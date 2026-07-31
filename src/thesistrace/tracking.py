import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thesistrace.activity_contract import (
    MAX_RESOURCE_EXHAUSTION_EXECUTIONS,
    CooperativeActivityCancellation,
    is_resource_exhaustion,
)
from thesistrace.alpha import evaluate_alpha_matrix, validate_alpha
from thesistrace.datasets import DatasetPublisher
from thesistrace.factor import (
    HORIZONS,
    build_forward_labels,
    correlation_summary,
    evaluate_factor,
    factor_day,
    mean_or_none,
)
from thesistrace.numeric import canonical_binary64_bytes, canonical_decimal
from thesistrace.objects import canonical_json_bytes
from thesistrace.ports import (
    ControlMetadataPort,
    ObjectStorePort,
    ObjectWriterPort,
    WorkingCachePort,
)
from thesistrace.quota import QuotaExceededError
from thesistrace.research_runs import RUNTIME_BUILD
from thesistrace.result_objects import (
    EXECUTION_AGGREGATE_CONTRACT,
    REBALANCE_AGGREGATE_CONTRACT,
    STRATEGY_DAILY_CONTRACT,
    TERMINAL_POSITION_CONTRACT,
    execution_aggregate_rows,
    public_terminal_strategy_state,
    publish_compact_result_objects,
    put_partitioned_table_object,
    read_json_object,
    read_table_object,
    read_table_object_tail,
    rebalance_aggregate_rows,
    reconstruct_result_view,
    reconstruct_strategy_metrics,
    strategy_daily_rows,
    strategy_summary,
)
from thesistrace.result_objects import (
    factor_summary as compact_factor_summary,
)
from thesistrace.result_objects import (
    terminal_strategy_state as compact_terminal_strategy_state,
)
from thesistrace.storage_admission import (
    StorageAdmissionError,
    publication_storage_objects,
)
from thesistrace.strategy import (
    advance_strategy_metric_state,
    run_strategy,
    strategy_metrics_from_state,
)
from thesistrace.working_cache import WorkingCacheError


class DailyTrackingError(RuntimeError):
    pass


class EquivalenceError(DailyTrackingError):
    pass


class TrackingAdvanceLimitError(DailyTrackingError):
    pass


SUPPORTED_CALCULATION_KERNELS = {"kernel-v1", "kernel-v2"}
TRACKING_METADATA_HISTORY_LIMIT = 10
TRACKING_PRODUCT_HISTORY_LIMIT = 252
MAX_EFFECTIVE_ALPHA_LOOKBACK = 252
TRACKING_ADVANCE_CHUNK_SESSIONS = 25
MAX_TRACKING_ADVANCE_SESSIONS = 252
COMPACT_RESULT_OBJECTS = {
    "diagnostic_summary",
    "execution_aggregates",
    "factor_summary",
    "rebalance_aggregates",
    "strategy_daily_observations",
    "strategy_summary",
    "terminal_positions",
    "terminal_strategy_state",
}


@dataclass
class CorrectionImpactCache:
    calendars: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    memberships: dict[
        tuple[str, str],
        dict[str, set[str]],
    ] = field(default_factory=dict)


class DailyTrackingService:
    def __init__(
        self,
        metadata: ControlMetadataPort,
        datasets: DatasetPublisher,
        objects: ObjectStorePort,
        cache: WorkingCachePort,
    ) -> None:
        self.metadata = metadata
        self.datasets = datasets
        self.objects = objects
        self.cache = cache

    def activate(
        self,
        run_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        pending_track_id: str | None = None
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.metadata.lock_daily_track_activation(connection)
            existing = connection.execute(
                """
                SELECT daily_track_id
                FROM daily_track_activation_idempotency
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            reservation = connection.execute(
                """
                SELECT track_id
                FROM daily_track_activation_reservations
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is None and reservation is not None:
                pending_track_id = str(reservation["track_id"])
            if existing is None and pending_track_id is None:
                active_count = int(
                    connection.execute(
                        """
                        SELECT
                            (
                                SELECT COUNT(*)
                                FROM daily_tracks
                                WHERE status = 'active'
                            )
                            +
                            (
                                SELECT COUNT(*)
                                FROM daily_track_activation_reservations
                            )
                        """
                    ).fetchone()[0]
                )
                active_limit = self.metadata.active_daily_track_limit(
                    connection
                )
                if active_count >= active_limit:
                    raise QuotaExceededError(
                        dimension="max_active_daily_tracks",
                        limit=active_limit,
                    )
        if existing is not None:
            track = self.get_track(str(existing["daily_track_id"]))
            if track is None:
                raise DailyTrackingError("idempotent DailyTrack disappeared")
            return track, False
        if pending_track_id is not None:
            return self._await_reserved_activation(pending_track_id)

        run = self.metadata.research_run(run_id)
        if (
            run is None
            or run["status"] != "succeeded"
            or not isinstance(run["result_manifest_sha256"], str)
        ):
            raise DailyTrackingError(
                "DailyTrack requires a succeeded ResearchRun with a Result Bundle"
            )
        frozen = self.metadata.frozen_research_definition(str(run["definition_version_id"]))
        release = self.metadata.dataset_release(str(run["dataset_release_id"]))
        manifest = self.objects.read_json(str(run["result_manifest_sha256"]))
        if frozen is None or release is None or not isinstance(manifest, dict):
            raise DailyTrackingError("seed provenance is incomplete")
        content = frozen["content"]
        if not isinstance(content, dict):
            raise DailyTrackingError("seed Research Definition is invalid")
        public_entries = manifest.get("objects")
        if (
            not isinstance(public_entries, dict)
            or set(public_entries) != COMPACT_RESULT_OBJECTS
        ):
            raise DailyTrackingError("DailyTrack requires a complete compact Result Bundle")
        result_view = reconstruct_result_view(self.objects, manifest)
        tracking_seed_tables = {
            kind: read_table_object(
                self.objects,
                public_entries,
                kind,
            )
            for kind in (
                "strategy_daily_observations",
                "rebalance_aggregates",
                "execution_aggregates",
            )
        }
        strategy = result_view["strategy_backtest"]
        if not isinstance(strategy, dict):
            raise DailyTrackingError("seed Strategy state is incomplete")
        daily = strategy.get("daily")
        if not isinstance(daily, list) or len(daily) != 504:
            raise DailyTrackingError("seed Strategy state is incomplete")

        track_id = f"track_{uuid4().hex[:20]}"
        generation_id = f"generation_{uuid4().hex[:20]}"
        checkpoint_id = f"checkpoint_{uuid4().hex[:20]}"
        now = datetime.now(UTC).isoformat()
        origin_session = str(daily[0]["session"])
        activation_session = str(daily[-1]["session"])
        rebalance_interval = int(content["strategy"]["rebalance_interval"])
        pending_signal = (
            {
                "signal_session": activation_session,
                "execution": "next_research_session_open",
            }
            if (len(daily) - 1) % rebalance_interval == 0
            else None
        )
        checkpoint_manifest: dict[str, object] = {
            "id": checkpoint_id,
            "kind": "activation",
            "daily_track_id": track_id,
            "generation_id": generation_id,
            "predecessor_checkpoint_id": None,
            "target_dataset_release_id": release["id"],
            "processed_session_count": 0,
            "processed_session_range": None,
            "tracking_origin": {
                "session": origin_session,
                "activation_session": activation_session,
                "all_cash_cny": "1e+7",
                "rebalance_phase": origin_session,
            },
            "seed_result_bundle": {
                "id": manifest["id"],
                "manifest_sha256": run["result_manifest_sha256"],
            },
            "objects": public_entries,
            "pending_strategy_signal": pending_signal,
            "numeric_execution_contract": content["numeric_execution_contract"],
            "calculation_kernel": manifest["calculation_kernel"],
            "cache_fencing_token": 1,
            "runtime_build": RUNTIME_BUILD,
            "created_at": now,
        }
        admitted = False
        existing_track_id: str | None = None
        reserved = False
        stage_attempt_id = f"activation_{uuid4().hex[:20]}"
        expected_manifest_sha256: str | None = None
        try:
            with self.objects.stage(
                track_id,
                stage_attempt_id,
                cleanup_uncommitted_payloads=True,
            ) as staged_objects:
                try:
                    with self.metadata.connect() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        self.metadata.lock_daily_track_activation(
                            connection
                        )
                        existing = connection.execute(
                            """
                            SELECT daily_track_id
                            FROM daily_track_activation_idempotency
                            WHERE idempotency_key = ?
                            """,
                            (idempotency_key,),
                        ).fetchone()
                        reservation = connection.execute(
                            """
                            SELECT track_id
                            FROM daily_track_activation_reservations
                            WHERE idempotency_key = ?
                            """,
                            (idempotency_key,),
                        ).fetchone()
                        if existing is not None:
                            existing_track_id = str(
                                existing["daily_track_id"]
                            )
                            connection.rollback()
                        elif reservation is not None:
                            pending_track_id = str(
                                reservation["track_id"]
                            )
                            connection.rollback()
                        else:
                            active_count = int(
                                connection.execute(
                                    """
                                    SELECT
                                        (
                                            SELECT COUNT(*)
                                            FROM daily_tracks
                                            WHERE status = 'active'
                                        )
                                        +
                                        (
                                            SELECT COUNT(*)
                                            FROM
                                                daily_track_activation_reservations
                                        )
                                    """
                                ).fetchone()[0]
                            )
                            active_limit = (
                                self.metadata.active_daily_track_limit(
                                    connection
                                )
                            )
                            if active_count >= active_limit:
                                raise QuotaExceededError(
                                    dimension=(
                                        "max_active_daily_tracks"
                                    ),
                                    limit=active_limit,
                                )
                            connection.execute(
                                """
                                INSERT INTO
                                    daily_track_activation_reservations
                                    (track_id, idempotency_key,
                                     seed_run_id, created_at)
                                VALUES (?, ?, ?, ?)
                                """,
                                (
                                    track_id,
                                    idempotency_key,
                                    run_id,
                                    now,
                                ),
                            )
                            connection.commit()
                            reserved = True
                except Exception:
                    if (
                        track_id
                        not in self.metadata.daily_track_activation_reservation_ids()
                    ):
                        raise
                    reserved = True

                if (
                    existing_track_id is None
                    and pending_track_id is None
                ):
                    checkpoint_manifest["objects"] = {
                        **public_entries,
                        **{
                            kind: put_partitioned_table_object(
                                staged_objects,
                                tracking_seed_tables[kind],
                                {
                                    "strategy_daily_observations": (
                                        STRATEGY_DAILY_CONTRACT
                                    ),
                                    "rebalance_aggregates": (
                                        REBALANCE_AGGREGATE_CONTRACT
                                    ),
                                    "execution_aggregates": (
                                        EXECUTION_AGGREGATE_CONTRACT
                                    ),
                                }[kind],
                                kind=kind,
                            )
                            for kind in tracking_seed_tables
                        },
                    }
                    checkpoint_object = staged_objects.put_json(
                        checkpoint_manifest
                    )
                    expected_manifest_sha256 = str(
                        checkpoint_object["sha256"]
                    )
                    staged_objects.put_manifest(
                        checkpoint_id,
                        checkpoint_manifest,
                    )
                    self._commit_activation_cache(
                        track_id=track_id,
                        generation_id=generation_id,
                        checkpoint_id=checkpoint_id,
                        checkpoint_sha256=expected_manifest_sha256,
                        frozen=frozen,
                        release=release,
                        definition=content,
                        calculation_kernel=str(
                            manifest["calculation_kernel"]
                        ),
                    )
                    self.cache.advance_fence(
                        track_id,
                        1,
                        stopped=False,
                    )
                    with (
                        self.metadata.storage_mutation_fence(),
                        self.metadata.connect() as connection,
                    ):
                        connection.execute("BEGIN IMMEDIATE")
                        self.metadata.lock_daily_track_activation(
                            connection
                        )
                        reservation = connection.execute(
                            """
                            SELECT idempotency_key, seed_run_id
                            FROM daily_track_activation_reservations
                            WHERE track_id = ?
                            """,
                            (track_id,),
                        ).fetchone()
                        if (
                            reservation is None
                            or reservation["idempotency_key"]
                            != idempotency_key
                            or reservation["seed_run_id"] != run_id
                        ):
                            raise DailyTrackingError(
                                "DailyTrack activation reservation disappeared"
                            )
                        with staged_objects.publication(
                            manifest_sha256=expected_manifest_sha256
                        ):
                            self.metadata.commit_private_storage_references(
                                connection,
                                resource_kind="tracking_checkpoint",
                                resource_id=checkpoint_id,
                                objects=publication_storage_objects(
                                    checkpoint_manifest,
                                    manifest_object=checkpoint_object,
                                ),
                            )
                            connection.execute(
                                """
                                INSERT INTO daily_tracks
                                    (id, seed_run_id,
                                     definition_version_id,
                                     definition_content_hash,
                                     activation_release_id,
                                     origin_session,
                                     numeric_execution_contract,
                                     status,
                                     current_generation_id,
                                     head_checkpoint_id,
                                     created_at,
                                     fencing_token)
                                VALUES (?, ?, ?, ?, ?, ?, ?,
                                        'active', ?, ?, ?, 1)
                                """,
                                (
                                    track_id,
                                    run_id,
                                    frozen["id"],
                                    frozen["content_hash"],
                                    release["id"],
                                    origin_session,
                                    content[
                                        "numeric_execution_contract"
                                    ],
                                    generation_id,
                                    checkpoint_id,
                                    now,
                                ),
                            )
                            connection.execute(
                                """
                                INSERT INTO tracking_generations
                                    (id, daily_track_id, ordinal,
                                     calculation_kernel,
                                     numeric_execution_contract,
                                     basis_dataset_release_id,
                                     reason, created_at)
                                VALUES (?, ?, 0, ?, ?, ?,
                                        'activation', ?)
                                """,
                                (
                                    generation_id,
                                    track_id,
                                    manifest[
                                        "calculation_kernel"
                                    ],
                                    content[
                                        "numeric_execution_contract"
                                    ],
                                    release["id"],
                                    now,
                                ),
                            )
                            connection.execute(
                                """
                                INSERT INTO tracking_checkpoints
                                    (id, daily_track_id,
                                     generation_id,
                                     predecessor_checkpoint_id,
                                     target_dataset_release_id,
                                     manifest_sha256, created_at)
                                VALUES (?, ?, ?, NULL, ?, ?, ?)
                                """,
                                (
                                    checkpoint_id,
                                    track_id,
                                    generation_id,
                                    release["id"],
                                    expected_manifest_sha256,
                                    now,
                                ),
                            )
                            connection.execute(
                                """
                                INSERT INTO
                                    daily_track_activation_idempotency
                                    (idempotency_key,
                                     daily_track_id)
                                VALUES (?, ?)
                                """,
                                (idempotency_key, track_id),
                            )
                            connection.execute(
                                """
                                DELETE FROM
                                    daily_track_activation_reservations
                                WHERE track_id = ?
                                """,
                                (track_id,),
                            )
                            connection.commit()
                            admitted = True
        except Exception:
            committed_manifest_sha256 = (
                self.metadata.daily_track_head_manifest_sha256(
                    track_id
                )
            )
            if (
                expected_manifest_sha256 is not None
                and committed_manifest_sha256
                == expected_manifest_sha256
            ):
                admitted = True
                self.objects.recover_staged_publication(
                    track_id,
                    committed_manifest_sha256=(
                        committed_manifest_sha256
                    ),
                )
            else:
                if reserved:
                    self.metadata.delete_daily_track_activation_reservation(
                        track_id
                    )
                self.cache.delete(track_id)
                self.objects.recover_staged_publication(
                    track_id,
                    committed_manifest_sha256=None,
                )
                raise
        if pending_track_id is not None:
            return self._await_reserved_activation(pending_track_id)
        if not admitted:
            self.cache.delete(track_id)
            if existing_track_id is None:
                raise DailyTrackingError("DailyTrack activation was not admitted")
            existing_track = self.get_track(existing_track_id)
            if existing_track is None:
                raise DailyTrackingError("idempotent DailyTrack disappeared")
            return existing_track, False
        latest = self.metadata.latest_dataset_release()
        if latest is not None and latest["id"] != release["id"]:
            self.enqueue_toward(track_id, str(latest["id"]))
        track = self.get_track(track_id)
        if track is None:
            raise DailyTrackingError("activated DailyTrack disappeared")
        return track, True

    def _await_reserved_activation(
        self,
        track_id: str,
    ) -> tuple[dict[str, object], bool]:
        self.objects.wait_for_staged_publication(track_id)
        track = self.get_track(track_id)
        if track is not None:
            return track, False
        self.objects.recover_staged_publication(
            track_id,
            committed_manifest_sha256=None,
        )
        self.metadata.delete_daily_track_activation_reservation(
            track_id
        )
        raise DailyTrackingError("DailyTrack activation did not complete")

    def _commit_activation_cache(
        self,
        *,
        track_id: str,
        generation_id: str,
        checkpoint_id: str,
        checkpoint_sha256: str,
        frozen: dict[str, object],
        release: dict[str, object],
        definition: dict[str, object],
        calculation_kernel: str,
    ) -> None:
        canonical = self.datasets.materialize_canonical(release)
        alpha = self._alpha(
            canonical,
            definition,
            kernel=calculation_kernel,
        )
        alpha_sessions = alpha.get("sessions")
        if not isinstance(alpha_sessions, list):
            raise DailyTrackingError("seed Alpha Matrix is invalid")
        pending_alpha = {
            str(item["session"]): [
                {
                    "instrument_id": str(row["instrument_id"]),
                    "alpha": float(row["value"]),
                }
                for row in item["values"]
            ]
            for item in alpha_sessions[-21:]
            if isinstance(item, dict) and isinstance(item.get("values"), list)
        }
        labels = build_forward_labels(canonical, alpha, report_sessions=504)
        factor = evaluate_factor(labels)
        rolling_factor: list[dict[str, object]] = []
        horizons = factor.get("horizons")
        if not isinstance(horizons, dict):
            raise DailyTrackingError("seed Factor Evaluation is invalid")
        for horizon, value in sorted(horizons.items(), key=lambda item: int(item[0])):
            if not isinstance(value, dict) or not isinstance(value.get("daily"), list):
                raise DailyTrackingError("seed Factor Evaluation horizon is invalid")
            for row in value["daily"]:
                quantiles = row.get("quantile_returns")
                if not isinstance(row, dict) or not isinstance(quantiles, dict):
                    raise DailyTrackingError("seed Factor daily result is invalid")
                rolling_factor.append(
                    {
                        "session": str(row["session"]),
                        "horizon": int(horizon),
                        "sample_count": int(row["sample_count"]),
                        "ic": row["ic"],
                        "rank_ic": row["rank_ic"],
                        "q1": quantiles["q1"],
                        "q2": quantiles["q2"],
                        "q3": quantiles["q3"],
                        "q4": quantiles["q4"],
                        "q5": quantiles["q5"],
                        "top_bottom_return": row["top_bottom_return"],
                        "correlation_reason": row["correlation_reason"],
                        "quantile_reason": row["quantile_reason"],
                    }
                )
        self.cache.commit_seed(
            {
                "daily_track_id": track_id,
                "generation_id": generation_id,
                "basis_checkpoint_id": checkpoint_id,
                "basis_checkpoint_sha256": checkpoint_sha256,
                "definition_content_hash": frozen["content_hash"],
                "calculation_kernel": calculation_kernel,
                "numeric_execution_contract": definition[
                    "numeric_execution_contract"
                ],
                "basis_dataset_release_id": release["id"],
                "fencing_token": 1,
            },
            pending_alpha=pending_alpha,
            rolling_factor=rolling_factor,
        )

    def _ensure_working_cache(
        self,
        track: dict[str, object],
        generation: dict[str, object],
        *,
        write_fencing_token: int | None = None,
    ) -> dict[str, object]:
        head = track.get("head")
        if not isinstance(head, dict):
            raise DailyTrackingError("DailyTrack has no Head")
        head_manifest = self._checkpoint_manifest(str(head["manifest_sha256"]))
        expected = {
            "daily_track_id": track["id"],
            "generation_id": track["current_generation_id"],
            "basis_checkpoint_id": head["id"],
            "basis_checkpoint_sha256": head["manifest_sha256"],
            "definition_content_hash": track["definition_content_hash"],
            "calculation_kernel": generation["calculation_kernel"],
            "numeric_execution_contract": track["numeric_execution_contract"],
            "basis_dataset_release_id": head["target_dataset_release_id"],
            "fencing_token": head_manifest["cache_fencing_token"],
        }
        try:
            return self.cache.validate(str(track["id"]), expected)
        except (
            OSError,
            ValueError,
            KeyError,
            WorkingCacheError,
        ):
            if write_fencing_token is not None:
                self._assert_cache_write_authority(
                    str(track["id"]),
                    write_fencing_token,
                )
            self.cache.delete_if_not_newer(
                str(track["id"]),
                (
                    write_fencing_token
                    if write_fencing_token is not None
                    else int(expected["fencing_token"])
                ),
            )
            self.cache.discard_staging()
            self._rebuild_working_cache(
                track,
                generation,
                expected,
            )
            return self.cache.validate(str(track["id"]), expected)

    def _assert_cache_write_authority(
        self,
        track_id: str,
        fencing_token: int,
    ) -> None:
        with self.metadata.connect() as connection:
            row = connection.execute(
                """
                SELECT status, fencing_token
                FROM daily_tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()
        if (
            row is None
            or row["status"] != "active"
            or int(row["fencing_token"]) != fencing_token
        ):
            raise DailyTrackingError("Working Cache write authority was fenced")

    def _rebuild_working_cache(
        self,
        track: dict[str, object],
        generation: dict[str, object],
        coordinates: dict[str, object],
    ) -> None:
        head = track.get("head")
        if not isinstance(head, dict):
            raise DailyTrackingError("Working Cache rebuild Head is missing")
        head_manifest = self._checkpoint_manifest(
            str(head["manifest_sha256"])
        )
        if (
            str(head["id"]) != str(coordinates["basis_checkpoint_id"])
            or str(head["manifest_sha256"])
            != str(coordinates["basis_checkpoint_sha256"])
            or str(head["target_dataset_release_id"])
            != str(coordinates["basis_dataset_release_id"])
            or str(head_manifest.get("target_dataset_release_id"))
            != str(coordinates["basis_dataset_release_id"])
            or str(head_manifest.get("generation_id"))
            != str(coordinates["generation_id"])
        ):
            raise DailyTrackingError("Working Cache rebuild basis is stale")
        release = self.metadata.dataset_release(
            str(coordinates["basis_dataset_release_id"])
        )
        frozen = self.metadata.frozen_research_definition(
            str(track["definition_version_id"])
        )
        if release is None or frozen is None:
            raise DailyTrackingError("Working Cache rebuild truth is missing")
        definition = frozen["content"]
        if not isinstance(definition, dict):
            raise DailyTrackingError("Working Cache rebuild Definition is invalid")
        alpha_definition = definition.get("alpha")
        if not isinstance(alpha_definition, dict):
            raise DailyTrackingError("Working Cache rebuild Alpha is invalid")
        lookback = validate_alpha(
            str(alpha_definition["expression"])
        ).effective_lookback
        canonical = self.datasets.materialize_canonical_tail(
            release,
            504 + lookback,
        )
        calendar = [str(session) for session in canonical["research_calendar"]]
        report_sessions = calendar[-504:]
        alpha = self._alpha(
            canonical,
            definition,
            kernel=str(generation["calculation_kernel"]),
        )
        recent_sessions = set(report_sessions)
        recent_alpha = {
            **alpha,
            "sessions": [
                item
                for item in alpha["sessions"]
                if str(item["session"]) in recent_sessions
            ],
        }
        recent_alpha["checksum"] = alpha_matrix_checksum(recent_alpha)
        labels = build_forward_labels(
            canonical,
            recent_alpha,
            signal_sessions=report_sessions,
        )
        factor = evaluate_factor(labels)
        pending = {
            str(item["session"]): [
                {
                    "instrument_id": str(row["instrument_id"]),
                    "alpha": float(row["value"]),
                }
                for row in item["values"]
            ]
            for item in recent_alpha["sessions"][-21:]
        }
        self.cache.commit_seed(
            coordinates,
            pending_alpha=pending,
            rolling_factor=factor_artifact_to_rolling_rows(factor),
        )

    def _checkpoint_release_sequence(
        self,
        track: dict[str, object],
    ) -> list[str]:
        checkpoints = {
            str(item["id"]): item
            for item in track["checkpoints"]
            if isinstance(item, dict)
        }
        cursor: str | None = str(track["head_checkpoint_id"])
        release_ids: list[str] = []
        while cursor is not None:
            checkpoint = checkpoints.get(cursor)
            if checkpoint is None:
                raise DailyTrackingError("Checkpoint chain is incomplete")
            manifest = self._checkpoint_manifest(
                str(checkpoint["manifest_sha256"])
            )
            release_ids.append(str(manifest["target_dataset_release_id"]))
            predecessor = manifest.get("predecessor_checkpoint_id")
            cursor = str(predecessor) if predecessor is not None else None
        release_ids.reverse()
        for ancestor, descendant in zip(
            release_ids,
            release_ids[1:],
            strict=False,
        ):
            chain = self._release_chain(ancestor, descendant)
            if len(chain) != 1:
                raise DailyTrackingError(
                    "Checkpoint Dataset Releases are not an ordered sequence"
                )
        return release_ids

    def get_track(self, track_id: str) -> dict[str, object] | None:
        with self.metadata.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM daily_tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()
            if row is None:
                return None
            generations = connection.execute(
                """
                SELECT *
                FROM tracking_generations
                WHERE daily_track_id = ?
                ORDER BY ordinal
                """,
                (track_id,),
            ).fetchall()
            advances = connection.execute(
                """
                SELECT advance.*,
                       (SELECT COUNT(*) FROM tracking_advance_attempts AS attempt
                        WHERE attempt.advance_id = advance.id) AS attempt_count
                FROM tracking_advances AS advance
                WHERE daily_track_id = ?
                ORDER BY created_at, id
                """,
                (track_id,),
            ).fetchall()
            checkpoints = connection.execute(
                """
                SELECT *
                FROM tracking_checkpoints
                WHERE daily_track_id = ?
                ORDER BY created_at, id
                """,
                (track_id,),
            ).fetchall()
            deletion = connection.execute(
                """
                SELECT *
                FROM working_cache_deletions
                WHERE daily_track_id = ?
                """,
                (track_id,),
            ).fetchone()
        track = {key: row[key] for key in row.keys()}
        track["generations"] = [
            {key: generation[key] for key in generation.keys()} for generation in generations
        ]
        track["advances"] = [self._advance_from_row(advance) for advance in advances]
        track["checkpoints"] = [
            {key: checkpoint[key] for key in checkpoint.keys()} for checkpoint in checkpoints
        ]
        head = next(
            (
                checkpoint
                for checkpoint in track["checkpoints"]
                if checkpoint["id"] == track["head_checkpoint_id"]
            ),
            None,
        )
        track["head"] = head
        track["cache_deletion"] = (
            {key: deletion[key] for key in deletion.keys()}
            if deletion is not None
            else None
        )
        return track

    def _frontier_track(
        self,
        track_id: str,
        *,
        generation_id: str | None = None,
    ) -> dict[str, object] | None:
        with self.metadata.connect() as connection:
            row = connection.execute(
                "SELECT * FROM daily_tracks WHERE id = ?",
                (track_id,),
            ).fetchone()
            if row is None:
                return None
            requested_generation_id = (
                generation_id
                if generation_id is not None
                else str(row["current_generation_id"])
            )
            generations = connection.execute(
                """
                SELECT *
                FROM tracking_generations
                WHERE daily_track_id = ?
                  AND id IN (?, ?)
                ORDER BY ordinal
                """,
                (
                    track_id,
                    row["current_generation_id"],
                    requested_generation_id,
                ),
            ).fetchall()
            head = connection.execute(
                """
                SELECT *
                FROM tracking_checkpoints
                WHERE daily_track_id = ? AND id = ?
                """,
                (track_id, row["head_checkpoint_id"]),
            ).fetchone()
            unfinished = connection.execute(
                """
                SELECT *
                FROM tracking_advances
                WHERE daily_track_id = ?
                  AND status IN ('pending', 'running', 'blocked')
                ORDER BY created_at, id
                LIMIT 1
                """,
                (track_id,),
            ).fetchall()
        track = {key: row[key] for key in row.keys()}
        track["generations"] = [
            {key: item[key] for key in item.keys()}
            for item in generations
        ]
        track["advances"] = [
            self._advance_from_row(item)
            for item in unfinished
        ]
        track["head"] = (
            None
            if head is None
            else {key: head[key] for key in head.keys()}
        )
        return track

    def list_tracks(self) -> list[dict[str, object]]:
        with self.metadata.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM daily_tracks ORDER BY created_at, id"
            ).fetchall()
        return [track for row in rows if (track := self.get_track(str(row["id"]))) is not None]

    def bounded_track_view(
        self,
        track_id: str,
        *,
        history_limit: int = TRACKING_METADATA_HISTORY_LIMIT,
    ) -> dict[str, object] | None:
        bounded_limit = min(
            max(history_limit, 1),
            TRACKING_METADATA_HISTORY_LIMIT,
        )
        with self.metadata.connect() as connection:
            row = connection.execute(
                "SELECT * FROM daily_tracks WHERE id = ?",
                (track_id,),
            ).fetchone()
            if row is None:
                return None
            generations = connection.execute(
                """
                SELECT * FROM tracking_generations
                WHERE daily_track_id = ?
                ORDER BY ordinal DESC
                LIMIT ?
                """,
                (track_id, bounded_limit),
            ).fetchall()
            advances = connection.execute(
                """
                SELECT advance.*,
                       (SELECT COUNT(*) FROM tracking_advance_attempts AS attempt
                        WHERE attempt.advance_id = advance.id) AS attempt_count
                FROM tracking_advances AS advance
                WHERE daily_track_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (track_id, bounded_limit),
            ).fetchall()
            checkpoints = connection.execute(
                """
                SELECT * FROM tracking_checkpoints
                WHERE daily_track_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (track_id, bounded_limit),
            ).fetchall()
            head = connection.execute(
                """
                SELECT * FROM tracking_checkpoints
                WHERE daily_track_id = ? AND id = ?
                """,
                (track_id, row["head_checkpoint_id"]),
            ).fetchone()
            deletion = connection.execute(
                """
                SELECT * FROM working_cache_deletions
                WHERE daily_track_id = ?
                """,
                (track_id,),
            ).fetchone()
            counts = {
                "generation_count": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM tracking_generations
                        WHERE daily_track_id = ?
                        """,
                        (track_id,),
                    ).fetchone()[0]
                ),
                "advance_count": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM tracking_advances
                        WHERE daily_track_id = ?
                        """,
                        (track_id,),
                    ).fetchone()[0]
                ),
                "checkpoint_count": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM tracking_checkpoints
                        WHERE daily_track_id = ?
                        """,
                        (track_id,),
                    ).fetchone()[0]
                ),
            }
        view = {key: row[key] for key in row.keys()}
        view["generations"] = [
            {key: item[key] for key in item.keys()}
            for item in reversed(generations)
        ]
        view["advances"] = [
            self._advance_from_row(item)
            for item in reversed(advances)
        ]
        view["checkpoints"] = [
            {key: item[key] for key in item.keys()}
            for item in reversed(checkpoints)
        ]
        view["head"] = (
            None
            if head is None
            else {key: head[key] for key in head.keys()}
        )
        view["cache_deletion"] = (
            None
            if deletion is None
            else {key: deletion[key] for key in deletion.keys()}
        )
        view["history"] = {
            **counts,
            "returned_per_collection": bounded_limit,
        }
        return public_daily_track_view(view)

    def list_track_views(
        self,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        bounded_limit = min(max(limit, 1), 10)
        with self.metadata.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM daily_tracks
                ORDER BY created_at, id
                LIMIT ? OFFSET ?
                """,
                (bounded_limit + 1, offset),
            ).fetchall()
        selected = rows[:bounded_limit]
        return {
            "items": [
                view
                for row in selected
                if (
                    view := self.bounded_track_view(
                        str(row["id"]),
                        history_limit=TRACKING_METADATA_HISTORY_LIMIT,
                    )
                )
                is not None
            ],
            "offset": offset,
            "limit": bounded_limit,
            "has_more": len(rows) > bounded_limit,
        }

    def tracking_generation(
        self,
        track_id: str,
        generation_id: str,
    ) -> dict[str, object] | None:
        generation = self._tracking_child(
            "tracking_generations",
            track_id,
            generation_id,
        )
        return (
            None
            if generation is None
            else public_tracking_generation(generation)
        )

    def tracking_advance(
        self,
        track_id: str,
        advance_id: str,
    ) -> dict[str, object] | None:
        with self.metadata.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM tracking_advances
                WHERE daily_track_id = ? AND id = ?
                """,
                (track_id, advance_id),
            ).fetchone()
        if row is None:
            return None
        return public_tracking_advance(self._advance(advance_id))

    def tracking_checkpoint(
        self,
        track_id: str,
        checkpoint_id: str,
    ) -> dict[str, object] | None:
        checkpoint = self._tracking_checkpoint(
            track_id,
            checkpoint_id,
        )
        return (
            None
            if checkpoint is None
            else public_tracking_checkpoint(checkpoint)
        )

    def _tracking_checkpoint(
        self,
        track_id: str,
        checkpoint_id: str,
    ) -> dict[str, object] | None:
        return self._tracking_child(
            "tracking_checkpoints",
            track_id,
            checkpoint_id,
        )

    def _tracking_child(
        self,
        table: str,
        track_id: str,
        child_id: str,
    ) -> dict[str, object] | None:
        if table not in {
            "tracking_generations",
            "tracking_checkpoints",
        }:
            raise ValueError("unsupported Tracking child table")
        with self.metadata.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM {table}
                WHERE daily_track_id = ? AND id = ?
                """,
                (track_id, child_id),
            ).fetchone()
        return (
            None
            if row is None
            else {key: row[key] for key in row.keys()}
        )

    def current_view(
        self,
        track_id: str,
        *,
        limit: int = TRACKING_PRODUCT_HISTORY_LIMIT,
    ) -> dict[str, object]:
        track = self.bounded_track_view(track_id, history_limit=1)
        if track is None:
            raise KeyError(track_id)
        head_id = track.get("head_checkpoint_id")
        if not isinstance(head_id, str):
            raise DailyTrackingError("DailyTrack has no Head")
        return self.checkpoint_product_view(
            track_id,
            head_id,
            limit=limit,
        )

    def checkpoint_product_view(
        self,
        track_id: str,
        checkpoint_id: str,
        *,
        limit: int = TRACKING_PRODUCT_HISTORY_LIMIT,
    ) -> dict[str, object]:
        bounded_limit = min(
            max(limit, 1),
            TRACKING_PRODUCT_HISTORY_LIMIT,
        )
        track = self.bounded_track_view(track_id, history_limit=1)
        if track is None:
            raise KeyError(track_id)
        target = self._tracking_checkpoint(track_id, checkpoint_id)
        if target is None:
            raise KeyError(checkpoint_id)
        windows: list[
            tuple[
                dict[str, object],
                list[dict[str, object]],
                int,
            ]
        ] = []
        cursor: str | None = checkpoint_id
        collected_daily = 0
        while (
            cursor is not None
            and collected_daily < bounded_limit
            and len(windows) <= bounded_limit
        ):
            row = self._tracking_checkpoint(track_id, cursor)
            if row is None:
                raise DailyTrackingError(
                    "Tracking Checkpoint chain is incomplete"
                )
            manifest = self._checkpoint_manifest(
                str(row["manifest_sha256"])
            )
            entries = manifest.get("objects")
            if not isinstance(entries, dict):
                raise DailyTrackingError(
                    "compact Checkpoint object index is invalid"
                )
            daily_tail, total_daily = read_table_object_tail(
                self.objects,
                entries,
                "strategy_daily_observations",
                limit=bounded_limit - collected_daily,
            )
            windows.append((manifest, daily_tail, total_daily))
            collected_daily += len(daily_tail)
            predecessor = manifest.get("predecessor_checkpoint_id")
            cursor = (
                str(predecessor)
                if predecessor is not None
                else None
            )
        windows.reverse()
        daily: list[dict[str, object]] = []
        rebalances: list[dict[str, object]] = []
        executions: list[dict[str, object]] = []
        for manifest, daily_rows, _total_daily in windows:
            entries = manifest["objects"]
            daily.extend(daily_rows)
            if daily_rows:
                rebalance_rows, _ = read_table_object_tail(
                    self.objects,
                    entries,
                    "rebalance_aggregates",
                    limit=bounded_limit,
                )
                execution_rows, _ = read_table_object_tail(
                    self.objects,
                    entries,
                    "execution_aggregates",
                    limit=bounded_limit,
                )
                sessions = {
                    str(row["session"])
                    for row in daily_rows
                }
                rebalances.extend(
                    row
                    for row in rebalance_rows
                    if str(row["session"]) in sessions
                )
                executions.extend(
                    row
                    for row in execution_rows
                    if str(row["session"]) in sessions
                )
        daily = daily[-bounded_limit:]
        sessions = {str(row["session"]) for row in daily}
        rebalances = [
            row for row in rebalances if str(row["session"]) in sessions
        ]
        executions = [
            row for row in executions if str(row["session"]) in sessions
        ]
        target_manifest = windows[-1][0]
        entries = target_manifest["objects"]
        factor = read_json_object(
            self.objects,
            entries,
            "factor_summary",
        )
        summary = read_json_object(
            self.objects,
            entries,
            "strategy_summary",
        )
        terminal = read_json_object(
            self.objects,
            entries,
            "terminal_strategy_state",
        )
        terminal.pop("positions_object", None)
        terminal["positions"] = read_table_object(
            self.objects,
            entries,
            "terminal_positions",
        )
        return {
            "id": checkpoint_id,
            "daily_track": {
                "id": track_id,
                "status": track["status"],
                "generation_id": track["current_generation_id"],
                "head_checkpoint_id": track["head_checkpoint_id"],
                "viewed_generation_id": target_manifest["generation_id"],
                "viewed_checkpoint_id": checkpoint_id,
            },
            "checkpoint": public_checkpoint_manifest(
                target_manifest,
                limit=bounded_limit,
            ),
            "factor_summary": factor,
            "strategy": {
                "alpha_checksum": summary["alpha_checksum"],
                "initial_cash_cny": summary["initial_cash_cny"],
                "daily": [
                    {
                        **row,
                        "cash_ratio": (
                            float(
                                Decimal(str(row["net_cash"]))
                                / Decimal(str(row["net_nav"]))
                            )
                            if Decimal(str(row["net_nav"])) != 0
                            else 0.0
                        ),
                    }
                    for row in daily
                ],
                "metrics": summary["metrics"],
                "rebalance_aggregates": rebalances,
                "execution_aggregates": executions,
            },
            "terminal_strategy_state": public_terminal_strategy_state(
                terminal
            ),
            "recent_label_maturation": {"events": []},
            "window": {
                "maximum_sessions": bounded_limit,
                "returned_sessions": len(daily),
                "start_session": (
                    str(daily[0]["session"]) if daily else None
                ),
                "end_session": (
                    str(daily[-1]["session"]) if daily else None
                ),
                "has_earlier": (
                    cursor is not None
                    or sum(total for _, _, total in windows)
                    > len(daily)
                ),
            },
        }

    def _compact_tracking_projection(
        self,
        track: dict[str, object],
        checkpoint_id: str | None = None,
    ) -> dict[str, object]:
        checkpoint_rows = {
            str(item["id"]): item
            for item in track["checkpoints"]
            if isinstance(item, dict)
        }
        head_id = checkpoint_id or str(track["head_checkpoint_id"])
        manifests: list[dict[str, object]] = []
        cursor: str | None = head_id
        while cursor is not None:
            row = checkpoint_rows.get(cursor)
            if row is None:
                raise DailyTrackingError("Tracking Checkpoint chain is incomplete")
            manifest = self._checkpoint_manifest(str(row["manifest_sha256"]))
            manifests.append(manifest)
            predecessor = manifest.get("predecessor_checkpoint_id")
            cursor = str(predecessor) if predecessor is not None else None
        manifests.reverse()
        if not manifests or manifests[0].get("kind") not in {
            "activation",
            "replay",
        }:
            raise DailyTrackingError("Tracking basis Checkpoint is missing")

        daily: list[dict[str, object]] = []
        rebalances: list[dict[str, object]] = []
        executions: list[dict[str, object]] = []
        for manifest in manifests:
            entries = manifest.get("objects")
            if not isinstance(entries, dict):
                raise DailyTrackingError("compact Checkpoint object index is invalid")
            daily.extend(
                read_table_object(
                    self.objects,
                    entries,
                    "strategy_daily_observations",
                )
            )
            rebalances.extend(
                read_table_object(self.objects, entries, "rebalance_aggregates")
            )
            executions.extend(
                read_table_object(self.objects, entries, "execution_aggregates")
            )
        latest_entries = manifests[-1]["objects"]
        if not isinstance(latest_entries, dict):
            raise DailyTrackingError("compact Head object index is invalid")
        factor = read_json_object(self.objects, latest_entries, "factor_summary")
        strategy_summary_value = read_json_object(
            self.objects,
            latest_entries,
            "strategy_summary",
        )
        terminal = read_json_object(
            self.objects,
            latest_entries,
            "terminal_strategy_state",
        )
        positions = read_table_object(self.objects, latest_entries, "terminal_positions")
        terminal.pop("positions_object", None)
        terminal["positions"] = positions
        metrics = reconstruct_strategy_metrics(
            strategy_summary_value,
            daily,
            rebalances,
        )
        projected_daily = [
            {
                **row,
                "cash_ratio": (
                    float(Decimal(str(row["net_cash"])) / Decimal(str(row["net_nav"])))
                    if Decimal(str(row["net_nav"])) != 0
                    else 0.0
                ),
            }
            for row in daily
        ]
        return {
            "factor_summary": factor,
            "strategy": {
                "alpha_checksum": strategy_summary_value["alpha_checksum"],
                "initial_cash_cny": strategy_summary_value["initial_cash_cny"],
                "daily": projected_daily,
                "metrics": metrics,
                "rebalance_aggregates": rebalances,
                "execution_aggregates": executions,
            },
            "terminal_strategy_state": terminal,
        }

    def _checkpoint_state_projection(
        self,
        checkpoint: dict[str, object],
    ) -> dict[str, object]:
        manifest = self._checkpoint_manifest(
            str(checkpoint["manifest_sha256"])
        )
        entries = manifest.get("objects")
        if not isinstance(entries, dict):
            raise DailyTrackingError("compact Checkpoint object index is invalid")
        factor = read_json_object(self.objects, entries, "factor_summary")
        summary = read_json_object(self.objects, entries, "strategy_summary")
        terminal = read_json_object(
            self.objects,
            entries,
            "terminal_strategy_state",
        )
        terminal.pop("positions_object", None)
        terminal["positions"] = read_table_object(
            self.objects,
            entries,
            "terminal_positions",
        )
        if not isinstance(terminal.get("metric_state"), dict) or not isinstance(
            terminal.get("last_daily_observation"),
            dict,
        ):
            raise DailyTrackingError(
                "Tracking terminal continuation state is incomplete"
            )
        return {
            "factor_summary": factor,
            "strategy": {
                "alpha_checksum": summary["alpha_checksum"],
                "initial_cash_cny": summary["initial_cash_cny"],
                "metrics": summary["metrics"],
            },
            "terminal_strategy_state": terminal,
        }

    def reconcile_activation_staging(self) -> list[str]:
        reconciled: list[str] = []
        for track_id in self.objects.staged_publication_ids(
            prefix="track_"
        ):
            committed_manifest_sha256 = (
                self.metadata.daily_track_head_manifest_sha256(
                    track_id
                )
            )
            recovered = self.objects.recover_staged_publication(
                track_id,
                committed_manifest_sha256=committed_manifest_sha256,
            )
            if recovered:
                reconciled.append(track_id)
        reservation_ids = (
            self.metadata.daily_track_activation_reservation_ids()
        )
        staged_track_ids = set(
            self.objects.staged_publication_ids(prefix="track_")
        )
        for track_id in reservation_ids:
            if track_id not in staged_track_ids:
                self.metadata.delete_daily_track_activation_reservation(
                    track_id
                )
        return reconciled

    def stop(self, track_id: str) -> dict[str, object] | None:
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.metadata.lock_daily_track(connection, track_id)
            row = connection.execute(
                """
                SELECT status, fencing_token
                FROM daily_tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()
            if row is None:
                return None
            fencing_token = int(row["fencing_token"])
            if row["status"] == "active":
                fencing_token += 1
                connection.execute(
                    """
                    UPDATE daily_tracks
                    SET status = 'stopped', stopped_at = ?, fencing_token = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (now, fencing_token, track_id),
                )
            connection.execute(
                """
                INSERT INTO working_cache_deletions
                    (daily_track_id, fencing_token, status, requested_at)
                VALUES (?, ?, 'pending', ?)
                ON CONFLICT DO NOTHING
                """,
                (track_id, fencing_token, now),
            )
            connection.execute(
                """
                UPDATE working_cache_deletions
                SET
                    fencing_token = CASE
                        WHEN fencing_token > ?
                        THEN working_cache_deletions.fencing_token
                        ELSE ?
                    END,
                    status = CASE
                        WHEN working_cache_deletions.status = 'completed'
                        THEN 'completed'
                        ELSE 'pending'
                    END,
                    requested_at = CASE
                        WHEN requested_at < ?
                        THEN working_cache_deletions.requested_at
                        ELSE ?
                    END
                WHERE daily_track_id = ?
                """,
                (fencing_token, fencing_token, now, now, track_id),
            )
            connection.execute(
                """
                UPDATE tracking_advance_attempts
                SET status = 'cancelled', completed_at = ?,
                    diagnostic_json = ?
                WHERE advance_id IN (
                    SELECT id FROM tracking_advances
                    WHERE daily_track_id = ?
                ) AND status IN ('queued', 'running')
                """,
                (
                    now,
                    json.dumps(
                        {
                            "reason_code": "TRACK_STOPPED",
                            "message": "DailyTrack was stopped",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    track_id,
                ),
            )
            connection.execute(
                """
                UPDATE tracking_advances
                SET status = 'blocked', updated_at = ?
                WHERE daily_track_id = ?
                  AND status IN ('pending', 'queued', 'running')
                """,
                (now, track_id),
            )
        try:
            self.cache.advance_fence(
                track_id,
                fencing_token,
                stopped=True,
            )
            self.reconcile_cache_deletions(track_id=track_id)
        except Exception as error:
            with self.metadata.connect() as connection:
                connection.execute(
                    """
                    UPDATE working_cache_deletions
                    SET last_error = ?
                    WHERE daily_track_id = ? AND status = 'pending'
                    """,
                    (str(error), track_id),
                )
        return self.get_track(track_id)

    def reconcile_cache_deletions(
        self,
        *,
        track_id: str | None = None,
    ) -> list[dict[str, object]]:
        rows = self.metadata.pending_working_cache_deletions(
            track_id
        )
        outcomes: list[dict[str, object]] = []
        for row in rows:
            current_track_id = str(row["daily_track_id"])
            token = int(row["fencing_token"])
            try:
                self.cache.advance_fence(
                    current_track_id,
                    token,
                    stopped=True,
                )
                self.cache.delete_if_not_newer(current_track_id, token)
            except Exception as error:
                self.metadata.fail_working_cache_deletion(
                    current_track_id,
                    str(error),
                )
                outcomes.append(
                    {
                        "daily_track_id": current_track_id,
                        "status": "pending",
                        "error": str(error),
                    }
                )
                continue
            completed_at = datetime.now(UTC).isoformat()
            self.metadata.complete_working_cache_deletion(
                current_track_id,
                completed_at,
            )
            outcomes.append(
                {
                    "daily_track_id": current_track_id,
                    "status": "completed",
                }
            )

        if track_id is not None:
            return outcomes

        cached_track_ids = self.cache.list_track_ids()
        activation_reservations = set(
            self.metadata.daily_track_activation_reservation_ids()
        )
        states = self.metadata.daily_track_cache_states(
            cached_track_ids
        )
        for cached_track_id in cached_track_ids:
            if cached_track_id in activation_reservations:
                continue
            state = states.get(cached_track_id)
            if state is not None and state[0] == "active":
                continue
            if state is None:
                self.cache.delete(cached_track_id)
            else:
                self.cache.advance_fence(
                    cached_track_id,
                    state[1],
                    stopped=True,
                )
                self.cache.delete_if_not_newer(cached_track_id, state[1])
        return outcomes

    def enqueue_active_tracks(self, target_release_id: str) -> list[dict[str, str]]:
        failures: list[dict[str, str]] = []
        correction_cache = CorrectionImpactCache()
        for track in self.list_tracks():
            if track["status"] == "active":
                try:
                    self.enqueue_toward(
                        str(track["id"]),
                        target_release_id,
                        correction_cache=correction_cache,
                    )
                except DailyTrackingError as error:
                    failures.append(
                        {
                            "track_id": str(track["id"]),
                            "reason_code": "TRACK_ENQUEUE_FAILED",
                            "message": str(error),
                        }
                    )
        return failures

    def enqueue_toward(
        self,
        track_id: str,
        target_release_id: str,
        *,
        correction_cache: CorrectionImpactCache | None = None,
    ) -> dict[str, object] | None:
        track = self._frontier_track(track_id)
        if track is None or track["status"] != "active":
            return None
        head = track["head"]
        if not isinstance(head, dict):
            raise DailyTrackingError("DailyTrack has no Head")
        head_release_id = str(head["target_dataset_release_id"])
        if head_release_id == target_release_id:
            return None
        unfinished = [
            advance
            for advance in track["advances"]
            if advance["status"] in {"pending", "running", "blocked"}
        ]
        if unfinished:
            return unfinished[0]
        next_release = self.metadata.next_dataset_release_on_path(
            head_release_id,
            target_release_id,
        )
        if next_release is None:
            raise DailyTrackingError("target Release is not a descendant of Tracking Head")
        correction = self._corrections_affect_track(
            track,
            next_release.get("correction_change_set"),
            next_release,
            correction_cache=correction_cache,
        )
        correction_boundary = (
            {
                "accepted_correction_change_set": next_release[
                    "correction_change_set"
                ],
                "prior_checkpoint_id": head["id"],
                "prior_dataset_release_id": head_release_id,
                "target_dataset_release_id": next_release["id"],
            }
            if correction
            else None
        )
        return self._create_advance(
            track_id,
            str(track["current_generation_id"]),
            str(next_release["id"]),
            correction_boundary=correction_boundary,
        )

    def _corrections_affect_track(
        self,
        track: dict[str, object],
        change_set: object,
        target_release: dict[str, object],
        *,
        correction_cache: CorrectionImpactCache | None,
    ) -> bool:
        if not isinstance(change_set, list) or not change_set:
            return False
        frozen = self.metadata.frozen_research_definition(
            str(track["definition_version_id"])
        )
        if frozen is None or not isinstance(frozen["content"], dict):
            raise DailyTrackingError("Tracking Definition is missing")
        definition = frozen["content"]
        alpha = definition.get("alpha")
        if not isinstance(alpha, dict):
            raise DailyTrackingError("Alpha Definition is invalid")
        parsed_alpha = validate_alpha(str(alpha["expression"]))
        alpha_fields = set(parsed_alpha.field_names)
        origin_session = str(track["origin_session"])
        release_id = str(target_release["id"])
        cache = correction_cache or CorrectionImpactCache()
        origin_calendar_key = (release_id, origin_session)
        origin_calendar = cache.calendars.get(origin_calendar_key)
        if origin_calendar is None:
            origin_calendar = self.datasets.research_calendar_neighborhood(
                target_release,
                center_session=origin_session,
                preceding_sessions=MAX_EFFECTIVE_ALPHA_LOOKBACK,
                following_sessions=0,
            )
            cache.calendars[origin_calendar_key] = origin_calendar
        if origin_session not in origin_calendar:
            raise DailyTrackingError("Tracking origin is not in the Dataset Release")
        origin_index = origin_calendar.index(origin_session)
        alpha_start = origin_calendar[
            max(0, origin_index - parsed_alpha.effective_lookback)
        ]
        liquidity_start = origin_calendar[max(0, origin_index - 19)]
        alpha_dependency = {
            "open_raw": "open_adj",
            "high_raw": "high_adj",
            "low_raw": "low_adj",
            "close_raw": "close_adj",
            "volume_shares": "volume_shares",
            "turnover_cny": "turnover_amount_cny",
        }
        correction_rows = [
            correction
            for correction in change_set
            if isinstance(correction, dict)
        ]
        if len(correction_rows) != len(change_set):
            raise DailyTrackingError("Dataset correction change set is invalid")
        membership_sessions: set[str] = set()
        correction_impacts: list[
            tuple[dict[str, object], set[str]]
        ] = []
        for correction in correction_rows:
            session = str(correction.get("session"))
            calendar_key = (release_id, session)
            calendar = cache.calendars.get(calendar_key)
            if calendar is None:
                calendar = self.datasets.research_calendar_neighborhood(
                    target_release,
                    center_session=session,
                    preceding_sessions=21,
                    following_sessions=MAX_EFFECTIVE_ALPHA_LOOKBACK,
                )
                cache.calendars[calendar_key] = calendar
            if session not in calendar:
                raise DailyTrackingError("Dataset correction session is invalid")
            session_index = calendar.index(session)
            affected = set(
                calendar[
                    max(0, session_index - 21) :
                    min(
                        len(calendar),
                        session_index
                        + parsed_alpha.effective_lookback
                        + 1,
                    )
                ]
            )
            correction_impacts.append((correction, affected))
            membership_sessions.update(
                calendar[
                    max(0, session_index - 21) :
                    min(
                        len(calendar),
                        session_index
                        + MAX_EFFECTIVE_ALPHA_LOOKBACK
                        + 1,
                    )
                ]
            )
        universe_name = str(definition["universe"])
        membership_key = (release_id, universe_name)
        memberships = cache.memberships.get(membership_key)
        if memberships is None:
            memberships = self.datasets.liquidity_universe_membership(
                target_release,
                universe_name=universe_name,
                sessions=sorted(membership_sessions),
            )
            cache.memberships[membership_key] = memberships
        for correction, affected_sessions in correction_impacts:
            field = str(correction.get("field"))
            session = str(correction.get("session"))
            instrument_id = str(correction.get("instrument_id"))
            relevant_instrument = any(
                instrument_id in memberships.get(affected_session, set())
                for affected_session in affected_sessions
            )
            if field == "open_raw" and relevant_instrument:
                return True
            if field == "turnover_cny" and session >= liquidity_start:
                return True
            if (
                alpha_dependency.get(field) in alpha_fields
                and relevant_instrument
                and session >= alpha_start
            ):
                return True
        return False

    def execute_next(self) -> dict[str, object] | None:
        with self.metadata.connect() as connection:
            row = connection.execute(
                """
                SELECT advance.id
                FROM tracking_advances AS advance
                JOIN daily_tracks AS track ON track.id = advance.daily_track_id
                WHERE advance.status IN ('pending', 'blocked')
                  AND track.status = 'active'
                ORDER BY advance.created_at, advance.id
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else self.execute_advance(str(row["id"]))

    def recover_abandoned_attempts(
        self,
        *,
        stale_after_seconds: int,
    ) -> list[str]:
        cutoff = (datetime.now(UTC) - timedelta(seconds=stale_after_seconds)).isoformat()
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {
                "reason_code": "ABANDONED_ATTEMPT",
                "message": "tracking worker stopped before Checkpoint publication",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT attempt.id, attempt.advance_id
                FROM tracking_advance_attempts AS attempt
                JOIN tracking_advances AS advance ON advance.id = attempt.advance_id
                JOIN daily_tracks AS track ON track.id = advance.daily_track_id
                WHERE attempt.status = 'running'
                  AND advance.status = 'running'
                  AND track.status = 'active'
                  AND attempt.started_at < ?
                ORDER BY attempt.started_at, attempt.id
                """,
                (cutoff,),
            ).fetchall()
            advance_ids = [str(row["advance_id"]) for row in rows]
            for row in rows:
                connection.execute(
                    """
                    UPDATE tracking_advance_attempts
                    SET status = 'failed', completed_at = ?,
                        diagnostic_json = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, diagnostic, str(row["id"])),
                )
                connection.execute(
                    """
                    UPDATE tracking_advances
                    SET status = 'blocked', updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, str(row["advance_id"])),
                )
        return advance_ids

    def execute_advance(
        self,
        advance_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        report_progress(progress, "recover")
        self._recover_staged_advance(advance_id)
        claimed = self._claim_advance(advance_id)
        if claimed is None:
            return self._advance(advance_id)
        advance, attempt = claimed
        report_progress(progress, "claimed")
        try:
            with self.objects.publication_guard(advance_id):
                with self.objects.stage(
                    advance_id,
                    str(attempt["id"]),
                    cleanup_uncommitted_payloads=True,
                ) as staged_objects:
                    checkpoint = self._calculate_advance(
                        advance,
                        fencing_token=int(attempt["fencing_token"]),
                        attempt_id=str(attempt["id"]),
                        objects=staged_objects,
                        progress=progress,
                    )
                    report_progress(progress, "calculated")
                    with (
                        self.metadata.storage_mutation_fence(),
                        staged_objects.publication(
                            manifest_sha256=str(
                                checkpoint["manifest_sha256"]
                            )
                        ),
                    ):
                        report_progress(progress, "before-publication")
                        self._publish_advance_success(
                            advance,
                            attempt,
                            checkpoint,
                        )
        except CooperativeActivityCancellation:
            raise
        except Exception as error:
            current = self._recover_staged_advance(advance_id)
            if current["status"] == "succeeded":
                return current
            quota_exceeded = isinstance(error, QuotaExceededError)
            storage_rejected = isinstance(error, StorageAdmissionError)
            resource_exhausted = is_resource_exhaustion(error)
            session_limit_exceeded = isinstance(
                error,
                TrackingAdvanceLimitError,
            )
            if quota_exceeded:
                reason_code = error.reason_code
            elif storage_rejected:
                reason_code = error.reason_code
            elif resource_exhausted:
                reason_code = "RESOURCE_EXHAUSTED"
            elif session_limit_exceeded:
                reason_code = "TRACKING_ADVANCE_SESSION_LIMIT"
            elif isinstance(error, EquivalenceError):
                reason_code = "EQUIVALENCE_MISMATCH"
            else:
                reason_code = "TRACKING_CALCULATION_FAILED"
            self._block_advance(
                advance,
                attempt,
                {
                    "reason_code": reason_code,
                    "message": (
                        "accepted Compute Worker resource envelope was exhausted"
                        if resource_exhausted
                        else str(error)
                    ),
                    **(
                        {
                            "dimension": error.dimension,
                            "limit": error.limit,
                        }
                        if quota_exceeded or storage_rejected
                        else {}
                    ),
                },
                terminal=(
                    session_limit_exceeded
                    or (
                        resource_exhausted
                        and int(attempt["ordinal"])
                        >= MAX_RESOURCE_EXHAUSTION_EXECUTIONS
                    )
                ),
            )
        completed = self._advance(advance_id)
        if completed["status"] == "succeeded":
            latest = self.metadata.latest_dataset_release()
            if latest is not None:
                self.enqueue_toward(
                    str(completed["daily_track_id"]),
                    str(latest["id"]),
                )
        return completed

    def _recover_staged_advance(
        self,
        advance_id: str,
    ) -> dict[str, object]:
        with self.objects.publication_guard(advance_id):
            current = self._advance(advance_id)
            committed_manifest_sha256: str | None = None
            checkpoint_id = current.get("checkpoint_id")
            if current["status"] == "succeeded" and isinstance(
                checkpoint_id,
                str,
            ):
                with self.metadata.connect() as connection:
                    checkpoint = connection.execute(
                        """
                        SELECT manifest_sha256
                        FROM tracking_checkpoints
                        WHERE id = ? AND daily_track_id = ?
                        """,
                        (checkpoint_id, current["daily_track_id"]),
                    ).fetchone()
                if checkpoint is not None:
                    committed_manifest_sha256 = str(
                        checkpoint["manifest_sha256"]
                    )
            self.objects.recover_staged_publication(
                advance_id,
                committed_manifest_sha256=committed_manifest_sha256,
            )
            return current

    def prepare_advance_redelivery(
        self,
        advance_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {
                "reason_code": "ACTIVITY_REDELIVERED",
                "message": (
                    "prior Tracking Activity delivery ended before "
                    "Checkpoint publication"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            advance = connection.execute(
                """
                SELECT daily_track_id, status
                FROM tracking_advances
                WHERE id = ?
                """,
                (advance_id,),
            ).fetchone()
            if advance is None:
                raise KeyError(advance_id)
            self.metadata.lock_daily_track(
                connection,
                str(advance["daily_track_id"]),
            )
            if advance["status"] == "running":
                connection.execute(
                    """
                    UPDATE tracking_advance_attempts
                    SET status = 'failed', completed_at = ?,
                        diagnostic_json = ?
                    WHERE advance_id = ? AND status = 'running'
                    """,
                    (now, diagnostic, advance_id),
                )
                connection.execute(
                    """
                    UPDATE tracking_advances
                    SET status = 'blocked', updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, advance_id),
                )
        return self._advance(advance_id)

    def fail_advance_delivery(
        self,
        advance_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {
                "reason_code": "ACTIVITY_DELIVERY_FAILED",
                "message": (
                    "Tracking Activity delivery exhausted before "
                    "Checkpoint publication"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            advance = connection.execute(
                """
                SELECT daily_track_id, status
                FROM tracking_advances
                WHERE id = ?
                """,
                (advance_id,),
            ).fetchone()
            if advance is None:
                raise KeyError(advance_id)
            self.metadata.lock_daily_track(
                connection,
                str(advance["daily_track_id"]),
            )
            track = connection.execute(
                "SELECT status FROM daily_tracks WHERE id = ?",
                (advance["daily_track_id"],),
            ).fetchone()
            if (
                track is not None
                and track["status"] == "active"
                and advance["status"]
                in {"pending", "running", "blocked"}
            ):
                connection.execute(
                    """
                    UPDATE tracking_advance_attempts
                    SET status = 'failed', completed_at = ?,
                        diagnostic_json = ?
                    WHERE advance_id = ? AND status = 'running'
                    """,
                    (now, diagnostic, advance_id),
                )
                connection.execute(
                    """
                    UPDATE tracking_advances
                    SET status = 'failed', updated_at = ?
                    WHERE id = ?
                      AND status IN ('pending', 'running', 'blocked')
                    """,
                    (now, advance_id),
                )
        return self._advance(advance_id)

    def upgrade_kernel(
        self,
        track_id: str,
        *,
        calculation_kernel: str,
        numeric_execution_contract: str,
        enqueue_execution: bool = True,
        generation_rebuild_id: str | None = None,
    ) -> dict[str, object]:
        track = self.get_track(track_id)
        if track is None:
            raise KeyError(track_id)
        if track["status"] != "active":
            raise DailyTrackingError("stopped DailyTrack cannot upgrade")
        if numeric_execution_contract != track["numeric_execution_contract"]:
            raise DailyTrackingError(
                "Numeric Execution Contract changes require a new ResearchRun and DailyTrack"
            )
        if calculation_kernel not in SUPPORTED_CALCULATION_KERNELS:
            raise DailyTrackingError(f"unsupported calculation kernel: {calculation_kernel}")
        head = track["head"]
        if not isinstance(head, dict):
            raise DailyTrackingError("DailyTrack has no Head")
        current_kernel = self._generation_kernel(
            track,
            str(track["current_generation_id"]),
        )
        unfinished = [
            advance
            for advance in track["advances"]
            if advance["status"] in {"pending", "running", "blocked"}
        ]
        if unfinished:
            pending_kernels = {
                self._generation_kernel(track, str(advance["generation_id"]))
                for advance in unfinished
            }
            if pending_kernels == {calculation_kernel}:
                return track
            if pending_kernels == {current_kernel} and calculation_kernel == current_kernel:
                return track
            raise DailyTrackingError(
                "DailyTrack must reach its current frontier before a kernel upgrade"
            )
        if calculation_kernel == current_kernel:
            return track
        self._create_generation_with_advance(
            track_id,
            basis_release_id=str(head["target_dataset_release_id"]),
            kernel=calculation_kernel,
            reason="runtime_fix",
            target_release_id=str(head["target_dataset_release_id"]),
            expected_generation_id=str(track["current_generation_id"]),
            expected_head_checkpoint_id=str(track["head_checkpoint_id"]),
            enqueue_execution=enqueue_execution,
            generation_rebuild_id=generation_rebuild_id,
        )
        updated = self.get_track(track_id)
        if updated is None:
            raise KeyError(track_id)
        return updated

    def verify_equivalence(
        self,
        track_id: str,
        *,
        checkpoint_id: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        report_progress(progress, "load-track")
        track = self.get_track(track_id)
        if track is None:
            raise KeyError(track_id)
        target_checkpoint_id = (
            str(track["head_checkpoint_id"])
            if checkpoint_id is None
            else checkpoint_id
        )
        target_checkpoint = next(
            (
                item
                for item in track["checkpoints"]
                if str(item["id"]) == target_checkpoint_id
            ),
            None,
        )
        if not isinstance(target_checkpoint, dict):
            raise DailyTrackingError("DailyTrack has no Head")
        oracle = self._ordered_release_oracle(
            track,
            target_checkpoint_id,
            progress=progress,
        )
        return {
            "status": "equivalent",
            "daily_track_id": track_id,
            "generation_id": target_checkpoint["generation_id"],
            "target_dataset_release_id": target_checkpoint[
                "target_dataset_release_id"
            ],
            "checkpoint_id": target_checkpoint["id"],
            "release_sequence": oracle["release_sequence"],
            "trace_checksums": oracle["trace_checksums"],
        }

    def _ordered_release_oracle(
        self,
        track: dict[str, object],
        target_checkpoint_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        checkpoint_rows = {
            str(item["id"]): item
            for item in track["checkpoints"]
            if isinstance(item, dict)
        }
        cursor: str | None = target_checkpoint_id
        manifests: list[dict[str, object]] = []
        while cursor is not None:
            report_progress(progress, "read-checkpoint-chain")
            row = checkpoint_rows.get(cursor)
            if row is None:
                raise EquivalenceError(
                    f"EQUIVALENCE_MISMATCH at $.checkpoints.{cursor}"
                )
            manifest = self._checkpoint_manifest(str(row["manifest_sha256"]))
            manifests.append(manifest)
            predecessor = manifest.get("predecessor_checkpoint_id")
            cursor = str(predecessor) if predecessor is not None else None
        manifests.reverse()
        if not manifests or manifests[0].get("kind") not in {
            "activation",
            "replay",
        }:
            raise EquivalenceError("EQUIVALENCE_MISMATCH at $.checkpoints.root")

        frozen = self.metadata.frozen_research_definition(
            str(track["definition_version_id"])
        )
        if frozen is None or not isinstance(frozen["content"], dict):
            raise DailyTrackingError("equivalence Definition is missing")
        definition = frozen["content"]
        generation_id = str(manifests[0]["generation_id"])
        kernel = self._generation_kernel(track, generation_id)
        if any(
            str(manifest["generation_id"]) != generation_id
            for manifest in manifests
        ):
            raise EquivalenceError("EQUIVALENCE_MISMATCH at $.generation_id")

        root_release = self.metadata.dataset_release(
            str(manifests[0]["target_dataset_release_id"])
        )
        if root_release is None:
            raise DailyTrackingError("equivalence root Release is missing")
        report_progress(progress, "materialize-root-release")
        root_canonical = self.datasets.materialize_canonical(root_release)
        report_progress(progress, "calculate-root-alpha")
        root_alpha = self._alpha(root_canonical, definition, kernel=kernel)
        report_progress(progress, "calculate-root-labels")
        root_labels = build_forward_labels(
            root_canonical,
            root_alpha,
            report_sessions=504,
        )
        report_progress(progress, "calculate-root-factor")
        root_factor = evaluate_factor(root_labels)
        report_progress(progress, "calculate-root-strategy")
        root_batch = self._batch_oracle(
            track,
            str(root_release["id"]),
            alpha=root_alpha,
            labels=root_labels,
            factor=root_factor,
            kernel=kernel,
        )
        projection = self._projection_from_batch(
            root_batch,
            definition,
        )
        self._assert_equivalent(
            self._compact_tracking_projection(
                track,
                str(manifests[0]["id"]),
            ),
            projection,
            f"$.checkpoints.{manifests[0]['id']}",
        )

        pending = {
            str(item["session"]): [
                {
                    "instrument_id": str(row["instrument_id"]),
                    "value": float(row["value"]),
                }
                for row in item["values"]
            ]
            for item in root_alpha["sessions"][-21:]
        }
        rolling = factor_artifact_to_rolling_rows(root_factor)
        prior_release = root_release
        release_sequence = [str(root_release["id"])]
        trace_checksums = [
            hashlib.sha256(
                equivalence_bytes(
                    {
                        "alpha": root_alpha,
                        "labels": root_labels,
                        "factor": root_factor,
                        "strategy": {
                            key: root_batch["strategy_backtest"][key]
                            for key in (
                                "orders",
                                "child_orders",
                                "fills",
                                "rejections",
                            )
                        },
                    }
                )
            ).hexdigest()
        ]

        for manifest in manifests[1:]:
            report_progress(progress, "calculate-release-transition")
            release = self.metadata.dataset_release(
                str(manifest["target_dataset_release_id"])
            )
            if release is None:
                raise DailyTrackingError("equivalence Release is missing")
            transition = self._tracking_transition(
                canonical=self.datasets.materialize_canonical(release),
                definition=definition,
                kernel=kernel,
                origin_session=str(track["origin_session"]),
                prior_session=str(
                    prior_release["appended_session_range"]["end"]
                ),
                pending_alpha=pending,
                rolling_factor=rolling,
                prior_projection=projection,
            )
            if not checkpoint_processed_sessions_match(
                manifest,
                transition["processed_sessions"],
            ):
                raise EquivalenceError(
                    "EQUIVALENCE_MISMATCH at "
                    f"$.checkpoints.{manifest['id']}.processed_sessions"
                )
            expected_projection = transition["projection"]
            if not isinstance(expected_projection, dict):
                raise DailyTrackingError("equivalence projection is invalid")
            self._assert_equivalent(
                self._compact_tracking_projection(
                    track,
                    str(manifest["id"]),
                ),
                expected_projection,
                f"$.checkpoints.{manifest['id']}",
            )
            pending_value = transition["pending_alpha"]
            rolling_value = transition["rolling_factor"]
            if not isinstance(pending_value, dict) or not isinstance(
                rolling_value, list
            ):
                raise DailyTrackingError("equivalence rolling state is invalid")
            pending = pending_value
            rolling = rolling_value
            projection = expected_projection
            prior_release = release
            release_sequence.append(str(release["id"]))
            trace_checksums.append(
                hashlib.sha256(
                    equivalence_bytes(transition["trace"])
                ).hexdigest()
            )
            report_progress(progress, "verified-release-transition")
        return {
            "projection": projection,
            "release_sequence": release_sequence,
            "trace_checksums": trace_checksums,
        }

    @staticmethod
    def _assert_equivalent(
        actual: object,
        expected: object,
        coordinate: str,
    ) -> None:
        if equivalence_bytes(actual) == equivalence_bytes(expected):
            return
        divergence = first_divergence(actual, expected)
        suffix = divergence[1:] if divergence.startswith("$") else divergence
        raise EquivalenceError(
            f"EQUIVALENCE_MISMATCH at {coordinate}{suffix}"
        )

    @staticmethod
    def _projection_from_batch(
        oracle: dict[str, dict[str, object]],
        definition: dict[str, object],
    ) -> dict[str, object]:
        strategy = oracle["strategy_backtest"]
        factor = oracle["factor_evaluation"]
        daily_rows = strategy_daily_rows(strategy)
        rebalance_rows = rebalance_aggregate_rows(strategy)
        execution_rows = execution_aggregate_rows(strategy)
        strategy_summary_value = strategy_summary(strategy)
        terminal = compact_terminal_strategy_state(strategy, definition)
        terminal["positions"] = [
            dict(row) for row in strategy["positions"]
        ]
        return {
            "factor_summary": compact_factor_summary(factor),
            "strategy": {
                "alpha_checksum": strategy_summary_value["alpha_checksum"],
                "initial_cash_cny": strategy_summary_value[
                    "initial_cash_cny"
                ],
                "daily": [
                    {
                        **row,
                        "cash_ratio": (
                            float(
                                Decimal(str(row["net_cash"]))
                                / Decimal(str(row["net_nav"]))
                            )
                            if Decimal(str(row["net_nav"])) != 0
                            else 0.0
                        ),
                    }
                    for row in daily_rows
                ],
                "metrics": reconstruct_strategy_metrics(
                    strategy_summary_value,
                    daily_rows,
                    rebalance_rows,
                ),
                "rebalance_aggregates": rebalance_rows,
                "execution_aggregates": execution_rows,
            },
            "terminal_strategy_state": terminal,
        }

    def _calculate_advance(
        self,
        advance: dict[str, object],
        *,
        fencing_token: int,
        attempt_id: str,
        objects: ObjectWriterPort | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        writer = objects or self.objects
        report_progress(progress, "load-advance-inputs")
        track = self._frontier_track(
            str(advance["daily_track_id"]),
            generation_id=str(advance["generation_id"]),
        )
        if track is None:
            raise DailyTrackingError("DailyTrack not found")
        target = self.metadata.dataset_release(str(advance["target_dataset_release_id"]))
        frozen = self.metadata.frozen_research_definition(str(track["definition_version_id"]))
        if target is None or frozen is None:
            raise DailyTrackingError("Tracking inputs are missing")
        definition = frozen["content"]
        if not isinstance(definition, dict):
            raise DailyTrackingError("Tracking Definition is invalid")
        generation = next(
            item for item in track["generations"] if item["id"] == advance["generation_id"]
        )
        kernel = str(generation["calculation_kernel"])
        replay = (
            generation["reason"] != "activation"
            and generation["id"] != track["current_generation_id"]
        )
        current_head = track.get("head")
        current_head_manifest = (
            self._checkpoint_manifest(str(current_head["manifest_sha256"]))
            if isinstance(current_head, dict)
            else None
        )
        current_objects = (
            current_head_manifest.get("objects")
            if isinstance(current_head_manifest, dict)
            else None
        )
        compact_head = isinstance(current_objects, dict) and {
            "factor_summary",
            "strategy_summary",
            "strategy_daily_observations",
            "terminal_strategy_state",
        } <= set(current_objects)
        if replay:
            report_progress(progress, "materialize-replay-release")
            canonical = self.datasets.materialize_canonical(target)
            return self._calculate_compact_replay(
                track=track,
                target=target,
                frozen=frozen,
                definition=definition,
                canonical=canonical,
                generation=generation,
                kernel=kernel,
                fencing_token=fencing_token,
                attempt_id=attempt_id,
                objects=writer,
                progress=progress,
            )
        if compact_head:
            if not isinstance(current_head, dict):
                raise DailyTrackingError("DailyTrack has no Head")
            prior_release = self.metadata.dataset_release(
                str(current_head["target_dataset_release_id"])
            )
            alpha_definition = definition.get("alpha")
            if prior_release is None or not isinstance(alpha_definition, dict):
                raise DailyTrackingError("incremental Tracking inputs are missing")
            new_sessions = self.datasets.research_calendar_range(
                target,
                after_session=str(
                    prior_release["appended_session_range"]["end"]
                ),
                through_session=str(
                    target["appended_session_range"]["end"]
                ),
            )
            if not new_sessions:
                raise DailyTrackingError(
                    "incremental Tracking target has no new Research Session"
                )
            if len(new_sessions) > MAX_TRACKING_ADVANCE_SESSIONS:
                raise TrackingAdvanceLimitError(
                    "Tracking Advance contains "
                    f"{len(new_sessions)} Research Sessions; "
                    f"limit is {MAX_TRACKING_ADVANCE_SESSIONS}"
                )
            lookback = validate_alpha(
                str(alpha_definition["expression"])
            ).effective_lookback
            return self._calculate_incremental_advance(
                advance=advance,
                track=track,
                target=target,
                frozen=frozen,
                definition=definition,
                new_sessions=new_sessions,
                lookback=lookback,
                generation=generation,
                fencing_token=fencing_token,
                attempt_id=attempt_id,
                objects=writer,
                progress=progress,
            )
        raise DailyTrackingError("Tracking Head does not use the compact contract")

    def _calculate_compact_replay(
        self,
        *,
        track: dict[str, object],
        target: dict[str, object],
        frozen: dict[str, object],
        definition: dict[str, object],
        canonical: dict[str, object],
        generation: dict[str, object],
        kernel: str,
        fencing_token: int,
        attempt_id: str,
        objects: ObjectWriterPort,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        report_progress(progress, "calculate-replay-alpha")
        alpha = self._alpha(canonical, definition, kernel=kernel)
        report_progress(progress, "calculate-replay-labels")
        summary_labels = build_forward_labels(
            canonical,
            alpha,
            report_sessions=504,
        )
        report_progress(progress, "calculate-replay-factor")
        factor = evaluate_factor(summary_labels)
        report_progress(progress, "calculate-replay-strategy")
        strategy = self._batch_oracle(
            track,
            str(target["id"]),
            alpha=alpha,
            kernel=kernel,
        )["strategy_backtest"]
        artifacts = {
            "alpha_matrix": alpha,
            "forward_labels": summary_labels,
            "factor_evaluation": factor,
            "strategy_backtest": strategy,
            "diagnostics": {
                "alpha_coverage": [
                    {
                        "session": item["session"],
                        "coverage_loss": item["coverage_loss"],
                    }
                    for item in alpha["sessions"]
                ],
                "strategy": strategy["diagnostics"],
            },
        }
        report_progress(progress, "write-replay-result")
        entries = publish_compact_result_objects(
            objects,
            artifacts,
            definition,
        )
        activation_release = self.metadata.dataset_release(
            str(track["activation_release_id"])
        )
        if activation_release is None:
            raise DailyTrackingError("Activation Release is missing")
        calendar = [str(session) for session in canonical["research_calendar"]]
        origin_index = calendar.index(str(track["origin_session"]))
        checkpoint_id = f"checkpoint_{uuid4().hex[:20]}"
        now = datetime.now(UTC).isoformat()
        manifest = {
            "id": checkpoint_id,
            "kind": "replay",
            "daily_track_id": track["id"],
            "generation_id": generation["id"],
            "predecessor_checkpoint_id": None,
            "target_dataset_release_id": target["id"],
            **processed_session_manifest_fields(
                calendar[origin_index:]
            ),
            "tracking_origin": {
                "session": track["origin_session"],
                "activation_session": activation_release[
                    "appended_session_range"
                ]["end"],
            },
            "definition": {
                "id": frozen["id"],
                "content_hash": frozen["content_hash"],
            },
            "numeric_execution_contract": track["numeric_execution_contract"],
            "calculation_kernel": generation["calculation_kernel"],
            "cache_fencing_token": fencing_token,
            "runtime_build": RUNTIME_BUILD,
            "basis_dataset_release_id": target["id"],
            "supersedes_generation_id": generation[
                "supersedes_generation_id"
            ],
            "supersedes_head_checkpoint_id": generation[
                "supersedes_head_checkpoint_id"
            ],
            "objects": entries,
            "created_at": now,
        }
        manifest_object = objects.put_json(manifest)
        objects.put_manifest(checkpoint_id, manifest)

        pending_items = alpha["sessions"][-21:]
        pending = {
            str(item["session"]): [
                {
                    "instrument_id": str(row["instrument_id"]),
                    "alpha": float(row["value"]),
                }
                for row in item["values"]
            ]
            for item in pending_items
        }
        rolling_rows = factor_artifact_to_rolling_rows(factor)
        report_progress(progress, "before-replay-cache")
        self._assert_cache_write_authority(
            str(track["id"]),
            fencing_token,
        )
        self.cache.delete_if_not_newer(str(track["id"]), fencing_token)
        self.cache.discard_staging()
        self.cache.commit_seed(
            {
                "daily_track_id": track["id"],
                "generation_id": generation["id"],
                "basis_checkpoint_id": checkpoint_id,
                "basis_checkpoint_sha256": manifest_object["sha256"],
                "definition_content_hash": frozen["content_hash"],
                "calculation_kernel": generation["calculation_kernel"],
                "numeric_execution_contract": track[
                    "numeric_execution_contract"
                ],
                "basis_dataset_release_id": target["id"],
                "fencing_token": fencing_token,
            },
            pending_alpha=pending,
            rolling_factor=rolling_rows,
        )
        return {
            "id": checkpoint_id,
            "manifest_sha256": manifest_object["sha256"],
            "manifest": manifest,
            "storage_objects": publication_storage_objects(
                manifest,
                manifest_object=manifest_object,
            ),
        }

    def _calculate_incremental_advance(
        self,
        *,
        advance: dict[str, object],
        track: dict[str, object],
        target: dict[str, object],
        frozen: dict[str, object],
        definition: dict[str, object],
        new_sessions: list[str],
        lookback: int,
        generation: dict[str, object],
        fencing_token: int,
        attempt_id: str,
        objects: ObjectWriterPort,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        head = track["head"]
        if not isinstance(head, dict):
            raise DailyTrackingError("DailyTrack has no Head")
        self._ensure_working_cache(
            track,
            generation,
            write_fencing_token=fencing_token,
        )

        prior_release = self.metadata.dataset_release(str(head["target_dataset_release_id"]))
        if prior_release is None:
            raise DailyTrackingError("Head Release is missing")
        cached_pending = self.cache.read_pending_alpha(str(track["id"]))
        prior_projection = self._checkpoint_state_projection(
            head,
        )
        terminal = prior_projection["terminal_strategy_state"]
        if not isinstance(terminal, dict):
            raise DailyTrackingError("Tracking terminal state is invalid")
        pending: dict[str, list[dict[str, object]]] = {
            session: [
                {
                    "instrument_id": str(row["instrument_id"]),
                    "value": float(row["alpha"]),
                }
                for row in rows
            ]
            for session, rows in cached_pending.items()
        }
        rolling_rows = self.cache.read_rolling_factor(str(track["id"]))
        projected_daily: list[dict[str, object]] = []
        projected_rebalances: list[dict[str, object]] = []
        projected_executions: list[dict[str, object]] = []
        prior_session = str(prior_release["appended_session_range"]["end"])
        transition: dict[str, object] | None = None
        for offset in range(0, len(new_sessions), TRACKING_ADVANCE_CHUNK_SESSIONS):
            report_progress(progress, "calculate-incremental-chunk")
            chunk = new_sessions[
                offset : offset + TRACKING_ADVANCE_CHUNK_SESSIONS
            ]
            calendar = self.datasets.research_calendar_neighborhood(
                target,
                center_session=chunk[0],
                preceding_sessions=max(lookback, 21),
                following_sessions=len(chunk) - 1,
            )
            if not calendar or calendar[-1] != chunk[-1]:
                raise DailyTrackingError(
                    "Tracking chunk Research Calendar is incomplete"
                )
            canonical = self.datasets.materialize_canonical_window(
                target,
                calendar[0],
                chunk[-1],
            )
            transition = self._tracking_transition(
                canonical=canonical,
                definition=definition,
                kernel=str(generation["calculation_kernel"]),
                origin_session=str(track["origin_session"]),
                prior_session=prior_session,
                pending_alpha=pending,
                rolling_factor=rolling_rows,
                prior_projection=prior_projection,
            )
            pending_value = transition["pending_alpha"]
            rolling_value = transition["rolling_factor"]
            projection_value = transition["projection"]
            if (
                not isinstance(pending_value, dict)
                or not isinstance(rolling_value, list)
                or not isinstance(projection_value, dict)
            ):
                raise DailyTrackingError(
                    "Tracking chunk transition is invalid"
                )
            pending = pending_value
            rolling_rows = rolling_value
            projected_daily.extend(transition["projected_daily"])
            projected_rebalances.extend(
                transition["projected_rebalances"]
            )
            projected_executions.extend(
                transition["projected_executions"]
            )
            projected_daily = projected_daily[-TRACKING_PRODUCT_HISTORY_LIMIT:]
            projected_rebalances = projected_rebalances[
                -TRACKING_PRODUCT_HISTORY_LIMIT:
            ]
            projected_executions = projected_executions[
                -TRACKING_PRODUCT_HISTORY_LIMIT:
            ]
            prior_projection = bounded_tracking_projection(
                projection_value,
                TRACKING_PRODUCT_HISTORY_LIMIT,
            )
            prior_session = chunk[-1]
            report_progress(progress, "calculated-incremental-chunk")
        if transition is None:
            raise DailyTrackingError("Advance has no new Research Sessions")
        processed_sessions = new_sessions
        pending = transition["pending_alpha"]
        rolling_rows = transition["rolling_factor"]
        factor_summary_value = transition["factor_summary"]
        strategy_summary_value = transition["strategy_summary"]
        strategy = transition["strategy"]
        if not all(
            isinstance(value, list)
            for value in (
                processed_sessions,
                rolling_rows,
                projected_daily,
                projected_rebalances,
                projected_executions,
            )
        ) or not isinstance(pending, dict):
            raise DailyTrackingError("Tracking transition result is invalid")

        entries = {
            "strategy_daily_observations": put_partitioned_table_object(
                objects,
                projected_daily,
                STRATEGY_DAILY_CONTRACT,
                kind="strategy_daily_observations",
            ),
            "rebalance_aggregates": put_partitioned_table_object(
                objects,
                projected_rebalances,
                REBALANCE_AGGREGATE_CONTRACT,
                kind="rebalance_aggregates",
            ),
            "execution_aggregates": put_partitioned_table_object(
                objects,
                projected_executions,
                EXECUTION_AGGREGATE_CONTRACT,
                kind="execution_aggregates",
            ),
            "terminal_positions": {
                "kind": "terminal_positions",
                **objects.put_parquet_rows(
                    strategy["positions"],
                    TERMINAL_POSITION_CONTRACT,
                ),
            },
        }
        transition_terminal = transition.get("terminal_strategy_state")
        if not isinstance(transition_terminal, dict):
            raise DailyTrackingError("Tracking terminal state is incomplete")
        terminal_state = dict(transition_terminal)
        terminal_state.pop("positions", None)
        terminal_state["positions_object"] = {
            key: entries["terminal_positions"][key]
            for key in ("sha256", "bytes", "writer_contract_id")
        }
        for kind, value in (
            ("factor_summary", factor_summary_value),
            ("strategy_summary", strategy_summary_value),
            ("terminal_strategy_state", terminal_state),
        ):
            entries[kind] = {
                "kind": kind,
                "format": "json",
                **objects.put_json(value),
            }
        entries = {kind: entries[kind] for kind in sorted(entries)}

        checkpoint_id = f"checkpoint_{uuid4().hex[:20]}"
        now = datetime.now(UTC).isoformat()
        manifest = {
            "id": checkpoint_id,
            "kind": "advance",
            "daily_track_id": track["id"],
            "generation_id": generation["id"],
            "predecessor_checkpoint_id": head["id"],
            "target_dataset_release_id": target["id"],
            **processed_session_manifest_fields(processed_sessions),
            "correction_boundary": advance["correction_boundary"],
            "tracking_origin": {
                "session": track["origin_session"],
                "activation_session": str(
                    self.metadata.dataset_release(
                        str(track["activation_release_id"])
                    )["appended_session_range"]["end"]
                ),
            },
            "definition": {
                "id": frozen["id"],
                "content_hash": frozen["content_hash"],
            },
            "alpha_calculation": {
                "calculated_sessions": len(processed_sessions),
                "maximum_lookback_sessions": transition[
                    "maximum_lookback_sessions"
                ],
            },
            "numeric_execution_contract": track["numeric_execution_contract"],
            "calculation_kernel": generation["calculation_kernel"],
            "cache_fencing_token": fencing_token,
            "runtime_build": RUNTIME_BUILD,
            "basis_dataset_release_id": target["id"],
            "supersedes_generation_id": None,
            "supersedes_head_checkpoint_id": None,
            "objects": entries,
            "created_at": now,
        }
        manifest_object = objects.put_json(manifest)
        objects.put_manifest(checkpoint_id, manifest)

        retained = sorted(set(cached_pending) & set(pending))
        newly_retained = {
            session: [
                {
                    "instrument_id": str(row["instrument_id"]),
                    "alpha": float(row["value"]),
                }
                for row in pending[session]
            ]
            for session in sorted(set(pending) - set(retained))
        }
        report_progress(progress, "before-incremental-cache")
        self._assert_cache_write_authority(str(track["id"]), fencing_token)
        self.cache.commit_advance(
            {
                "daily_track_id": track["id"],
                "generation_id": generation["id"],
                "basis_checkpoint_id": checkpoint_id,
                "basis_checkpoint_sha256": manifest_object["sha256"],
                "definition_content_hash": frozen["content_hash"],
                "calculation_kernel": generation["calculation_kernel"],
                "numeric_execution_contract": track[
                    "numeric_execution_contract"
                ],
                "basis_dataset_release_id": target["id"],
                "fencing_token": fencing_token,
            },
            retained_pending_sessions=retained,
            new_pending_alpha=newly_retained,
            rolling_factor=rolling_rows,
            attempt_id=attempt_id,
        )
        return {
            "id": checkpoint_id,
            "manifest_sha256": manifest_object["sha256"],
            "manifest": manifest,
            "storage_objects": publication_storage_objects(
                manifest,
                manifest_object=manifest_object,
            ),
        }

    def _batch_oracle(
        self,
        track: dict[str, object],
        target_release_id: str,
        *,
        alpha: dict[str, object] | None = None,
        labels: dict[str, object] | None = None,
        factor: dict[str, object] | None = None,
        kernel: str | None = None,
    ) -> dict[str, dict[str, object]]:
        target = self.metadata.dataset_release(target_release_id)
        frozen = self.metadata.frozen_research_definition(str(track["definition_version_id"]))
        activation = self.metadata.dataset_release(str(track["activation_release_id"]))
        if target is None or frozen is None or activation is None:
            raise DailyTrackingError("batch oracle inputs are missing")
        definition = frozen["content"]
        if not isinstance(definition, dict):
            raise DailyTrackingError("batch oracle Definition is invalid")
        if kernel is None:
            head = track["head"]
            if not isinstance(head, dict):
                raise DailyTrackingError("DailyTrack has no Head")
            kernel = self._generation_kernel(track, str(head["generation_id"]))
        canonical = self.datasets.materialize_canonical(target)
        alpha = alpha or self._alpha(canonical, definition, kernel=kernel)
        origin_index = canonical["research_calendar"].index(track["origin_session"])
        labels = labels or build_forward_labels(
            canonical,
            alpha,
            report_sessions=len(canonical["research_calendar"]) - origin_index,
        )
        factor = factor or evaluate_factor(labels)
        activation_session = str(activation["appended_session_range"]["end"])
        seed_canonical = slice_canonical_through(canonical, activation_session)
        seed_alpha = self._alpha(seed_canonical, definition, kernel=kernel)
        seed_strategy = run_strategy(seed_canonical, seed_alpha, definition)
        strategy = run_strategy(
            canonical,
            alpha,
            definition,
            origin_session=str(track["origin_session"]),
            terminal_cutoff=False,
            continuation=seed_strategy,
        )
        return {
            "alpha_matrix": alpha,
            "forward_labels": labels,
            "factor_evaluation": factor,
            "strategy_backtest": strategy,
        }

    def _tracking_transition(
        self,
        *,
        canonical: dict[str, object],
        definition: dict[str, object],
        kernel: str,
        origin_session: str,
        prior_session: str,
        pending_alpha: dict[str, list[dict[str, object]]],
        rolling_factor: list[dict[str, object]],
        prior_projection: dict[str, object],
    ) -> dict[str, object]:
        calendar = [str(session) for session in canonical["research_calendar"]]
        prior_index = calendar.index(prior_session)
        processed_sessions = calendar[prior_index + 1 :]
        if not processed_sessions:
            raise DailyTrackingError("Advance has no new Research Sessions")

        alpha_definition = definition.get("alpha")
        if not isinstance(alpha_definition, dict):
            raise DailyTrackingError("Alpha Definition is invalid")
        parsed_alpha = validate_alpha(str(alpha_definition["expression"]))
        window_start = max(0, prior_index + 1 - parsed_alpha.effective_lookback)
        evaluated = self._alpha(
            slice_canonical_range(canonical, calendar[window_start]),
            definition,
            kernel=kernel,
        )
        new_session_set = set(processed_sessions)
        new_alpha_items = [
            item
            for item in evaluated["sessions"]
            if str(item["session"]) in new_session_set
        ]
        if len(new_alpha_items) != len(processed_sessions):
            raise DailyTrackingError("incremental Alpha calculation is incomplete")

        pending = {
            session: [dict(row) for row in rows]
            for session, rows in pending_alpha.items()
        }
        rolling = {
            (str(row["session"]), int(row["horizon"])): dict(row)
            for row in rolling_factor
        }
        new_alpha_by_session = {
            str(item["session"]): [dict(row) for row in item["values"]]
            for item in new_alpha_items
        }
        matured_labels: list[dict[str, object]] = []
        factor_observations: list[dict[str, object]] = []
        for session in processed_sessions:
            pending[session] = new_alpha_by_session[session]
            for horizon in HORIZONS:
                empty = rolling_factor_row(
                    session,
                    horizon,
                    factor_day([]),
                    sample_count=0,
                )
                rolling[(session, horizon)] = empty
                signal_index = calendar.index(session) - horizon - 1
                if signal_index < 0:
                    continue
                signal_session = calendar[signal_index]
                alpha_values = pending.get(signal_session)
                if alpha_values is None:
                    raise DailyTrackingError(
                        f"Pending Alpha is missing for {signal_session}"
                    )
                labels = build_forward_labels(
                    canonical,
                    alpha_matrix_from_pending(
                        definition,
                        {signal_session: alpha_values},
                    ),
                    signal_sessions=[signal_session],
                    horizons=(horizon,),
                )
                factor = evaluate_factor(labels)
                factor_row = factor["horizons"][str(horizon)]["daily"][0]
                observation = rolling_factor_row(
                    signal_session,
                    horizon,
                    factor_row,
                    sample_count=int(factor_row["sample_count"]),
                )
                rolling[(signal_session, horizon)] = observation
                matured_labels.append(labels)
                factor_observations.append(observation)

        strategy_pending = {
            session: [dict(row) for row in rows]
            for session, rows in pending.items()
        }
        pending_sessions = set(sorted(pending)[-21:])
        pending = {
            session: rows
            for session, rows in pending.items()
            if session in pending_sessions
        }
        rolling_sessions = set(
            sorted(
                {
                    session
                    for session, _horizon in rolling
                }
            )[-504:]
        )
        rolling_rows = [
            row
            for (session, _horizon), row in sorted(rolling.items())
            if session in rolling_sessions
        ]
        if len(rolling_rows) > 1_512:
            raise DailyTrackingError("rolling Factor window exceeds 1,512 rows")

        prior_strategy = prior_projection["strategy"]
        terminal = prior_projection["terminal_strategy_state"]
        if not isinstance(prior_strategy, dict) or not isinstance(terminal, dict):
            raise DailyTrackingError("compact Strategy continuation is invalid")
        last_daily = terminal.get("last_daily_observation")
        prior_metric_state = terminal.get("metric_state")
        if not isinstance(last_daily, dict) or not isinstance(
            prior_metric_state,
            dict,
        ):
            raise DailyTrackingError("compact Strategy state is incomplete")
        alpha_for_strategy = alpha_matrix_from_pending(
            definition,
            strategy_pending,
        )
        strategy = run_strategy(
            canonical,
            alpha_for_strategy,
            definition,
            origin_session=origin_session,
            terminal_cutoff=False,
            continuation={
                "daily": [
                    {
                        **last_daily,
                        "gross_cash": terminal["gross_cash"],
                        "cumulative_transaction_cost": terminal[
                            "cumulative_transaction_cost"
                        ],
                    }
                ],
                "positions": terminal["positions"],
                "report_session_count": terminal["rebalance_phase"][
                    "report_session_count"
                ],
            },
        )
        delta_daily = [
            row for row in strategy["daily"] if str(row["session"]) in new_session_set
        ]
        if len(delta_daily) != len(processed_sessions):
            raise DailyTrackingError("incremental Strategy calculation is incomplete")
        projected_daily = [
            row
            for row in strategy_daily_rows(strategy)
            if str(row["session"]) in new_session_set
        ]
        projected_rebalances = [
            row
            for row in rebalance_aggregate_rows(strategy)
            if str(row["session"]) in new_session_set
        ]
        projected_executions = [
            row
            for row in execution_aggregate_rows(strategy)
            if str(row["session"]) in new_session_set
        ]
        metric_state = advance_strategy_metric_state(
            prior_metric_state,
            daily=[dict(row) for row in delta_daily],
            turnover_events=[
                {"session": row["session"], "value": row["turnover"]}
                for row in projected_rebalances
            ],
            cumulative_cost=Decimal(
                str(delta_daily[-1]["cumulative_transaction_cost"])
            ),
            rejections=[
                dict(row)
                for row in strategy["rejections"]
                if isinstance(row, dict)
            ],
        )
        metrics = strategy_metrics_from_state(metric_state)
        summary = strategy_summary(
            {
                "alpha_checksum": alpha_for_strategy["checksum"],
                "initial_cash_cny": strategy["initial_cash_cny"],
                "checksum": strategy["checksum"],
                "metrics": metrics,
            }
        )
        terminal_state = incremental_terminal_state(
            strategy,
            terminal,
            definition,
            len(processed_sessions),
            metric_state,
            {
                "sha256": "0" * 64,
                "bytes": 0,
                "writer_contract_id": TERMINAL_POSITION_CONTRACT.identifier,
            },
        )
        terminal_state.pop("positions_object")
        terminal_state["positions"] = [dict(row) for row in strategy["positions"]]
        factor_summary_value = rolling_factor_summary(rolling_rows)
        prior_daily = prior_strategy.get("daily")
        prior_rebalances = prior_strategy.get("rebalance_aggregates")
        prior_executions = prior_strategy.get("execution_aggregates")
        full_projection = all(
            isinstance(value, list)
            for value in (prior_daily, prior_rebalances, prior_executions)
        )
        complete_daily = (
            [
                *prior_daily,
                *[
                    {
                        **row,
                        "cash_ratio": (
                            float(
                                Decimal(str(row["net_cash"]))
                                / Decimal(str(row["net_nav"]))
                            )
                            if Decimal(str(row["net_nav"])) != 0
                            else 0.0
                        ),
                    }
                    for row in projected_daily
                ],
            ]
            if full_projection
            else projected_daily
        )
        complete_rebalances = (
            [*prior_rebalances, *projected_rebalances]
            if full_projection
            else projected_rebalances
        )
        complete_executions = (
            [*prior_executions, *projected_executions]
            if full_projection
            else projected_executions
        )
        projection_metrics = (
            reconstruct_strategy_metrics(
                summary,
                complete_daily,
                complete_rebalances,
            )
            if full_projection
            else metrics
        )
        return {
            "processed_sessions": processed_sessions,
            "maximum_lookback_sessions": parsed_alpha.effective_lookback,
            "pending_alpha": pending,
            "rolling_factor": rolling_rows,
            "factor_summary": factor_summary_value,
            "strategy_summary": summary,
            "terminal_strategy_state": terminal_state,
            "strategy": strategy,
            "projected_daily": projected_daily,
            "projected_rebalances": projected_rebalances,
            "projected_executions": projected_executions,
            "projection": {
                "factor_summary": factor_summary_value,
                "strategy": {
                    "alpha_checksum": summary["alpha_checksum"],
                    "initial_cash_cny": summary["initial_cash_cny"],
                    "daily": complete_daily,
                    "metrics": projection_metrics,
                    "rebalance_aggregates": complete_rebalances,
                    "execution_aggregates": complete_executions,
                },
                "terminal_strategy_state": terminal_state,
            },
            "trace": {
                "alpha": new_alpha_items,
                "labels": matured_labels,
                "factor": factor_observations,
                "orders": strategy["orders"],
                "child_orders": strategy["child_orders"],
                "fills": strategy["fills"],
                "rejections": strategy["rejections"],
            },
        }

    def _alpha(
        self,
        canonical: dict[str, object],
        definition: dict[str, object],
        *,
        kernel: str,
    ) -> dict[str, object]:
        alpha = definition["alpha"]
        if not isinstance(alpha, dict):
            raise DailyTrackingError("Alpha Definition is invalid")
        matrix = evaluate_alpha_matrix(
            canonical,
            expression=str(alpha["expression"]),
            universe_name=str(definition["universe"]),
            neutralization=str(definition["neutralization"]),
        )
        return apply_calculation_kernel(matrix, kernel)

    @staticmethod
    def _generation_kernel(track: dict[str, object], generation_id: str) -> str:
        generation = next(
            (
                item
                for item in track["generations"]
                if str(item["id"]) == generation_id
            ),
            None,
        )
        if generation is None:
            raise DailyTrackingError("Tracking Generation is missing")
        return str(generation["calculation_kernel"])

    def _create_generation_with_advance(
        self,
        track_id: str,
        *,
        basis_release_id: str,
        kernel: str,
        reason: str,
        target_release_id: str,
        expected_generation_id: str,
        expected_head_checkpoint_id: str,
        enqueue_execution: bool = True,
        generation_rebuild_id: str | None = None,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.metadata.lock_daily_track(connection, track_id)
            track = connection.execute(
                """
                SELECT status, current_generation_id, head_checkpoint_id,
                       numeric_execution_contract
                FROM daily_tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()
            if track is None or track["status"] != "active":
                raise DailyTrackingError("DailyTrack is not active")
            if (
                track["current_generation_id"] != expected_generation_id
                or track["head_checkpoint_id"] != expected_head_checkpoint_id
            ):
                raise DailyTrackingError("DailyTrack Head changed before replay scheduling")
            if reason == "runtime_fix":
                head = connection.execute(
                    """
                    SELECT target_dataset_release_id
                    FROM tracking_checkpoints
                    WHERE id = ?
                    """,
                    (track["head_checkpoint_id"],),
                ).fetchone()
                if (
                    head is None
                    or head["target_dataset_release_id"] != basis_release_id
                    or target_release_id != basis_release_id
                ):
                    raise DailyTrackingError(
                        "runtime-fix replay must target the current Head Release"
                    )
            unfinished = connection.execute(
                """
                SELECT 1
                FROM tracking_advances
                WHERE daily_track_id = ?
                  AND status IN ('pending', 'running', 'blocked')
                LIMIT 1
                """,
                (track_id,),
            ).fetchone()
            if unfinished is not None:
                raise DailyTrackingError(
                    "DailyTrack must reach its current frontier before replay"
                )
            existing = connection.execute(
                """
                SELECT *
                FROM tracking_generations
                WHERE daily_track_id = ?
                  AND calculation_kernel = ?
                  AND basis_dataset_release_id = ?
                  AND supersedes_generation_id = ?
                  AND supersedes_head_checkpoint_id = ?
                  AND reason = ?
                """,
                (
                    track_id,
                    kernel,
                    basis_release_id,
                    track["current_generation_id"],
                    track["head_checkpoint_id"],
                    reason,
                ),
            ).fetchone()
            if existing is None:
                generation_id = f"generation_{uuid4().hex[:20]}"
                ordinal = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(ordinal), -1) + 1
                        FROM tracking_generations
                        WHERE daily_track_id = ?
                        """,
                        (track_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    INSERT INTO tracking_generations
                        (id, daily_track_id, ordinal, calculation_kernel,
                         numeric_execution_contract, basis_dataset_release_id,
                         supersedes_generation_id, supersedes_head_checkpoint_id,
                         reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        generation_id,
                        track_id,
                        ordinal,
                        kernel,
                        track["numeric_execution_contract"],
                        basis_release_id,
                        track["current_generation_id"],
                        track["head_checkpoint_id"],
                        reason,
                        now,
                    ),
                )
                existing = connection.execute(
                    "SELECT * FROM tracking_generations WHERE id = ?",
                    (generation_id,),
                ).fetchone()
            assert existing is not None
            advance = connection.execute(
                """
                SELECT id
                FROM tracking_advances
                WHERE daily_track_id = ? AND generation_id = ?
                  AND target_dataset_release_id = ?
                """,
                (track_id, existing["id"], target_release_id),
            ).fetchone()
            if advance is None:
                advance_id = f"advance_{uuid4().hex[:20]}"
                connection.execute(
                    """
                    INSERT INTO tracking_advances
                        (id, daily_track_id, generation_id,
                         target_dataset_release_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        advance_id,
                        track_id,
                        existing["id"],
                        target_release_id,
                        now,
                        now,
                    ),
                )
            else:
                advance_id = str(advance["id"])
            if generation_rebuild_id is not None:
                self.metadata.bind_tracking_generation_rebuild(
                    connection,
                    rebuild_id=generation_rebuild_id,
                    track_id=track_id,
                    basis_generation_id=expected_generation_id,
                    basis_head_checkpoint_id=(
                        expected_head_checkpoint_id
                    ),
                    generation_id=str(existing["id"]),
                    advance_id=advance_id,
                    updated_at=now,
                )
            if enqueue_execution:
                self.metadata.enqueue_tracking_advance_execution(
                    connection,
                    track_id=track_id,
                    advance_id=advance_id,
                    created_at=now,
                )
            return {key: existing[key] for key in existing.keys()}

    def _create_advance(
        self,
        track_id: str,
        generation_id: str,
        target_release_id: str,
        *,
        correction_boundary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        correction_boundary_json = (
            json.dumps(
                correction_boundary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if correction_boundary is not None
            else None
        )
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.metadata.lock_daily_track(connection, track_id)
            track = connection.execute(
                """
                SELECT status, current_generation_id
                FROM daily_tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()
            if (
                track is None
                or track["status"] != "active"
                or track["current_generation_id"] != generation_id
            ):
                raise DailyTrackingError("DailyTrack is not active")
            existing = connection.execute(
                """
                SELECT *
                FROM tracking_advances
                WHERE daily_track_id = ? AND generation_id = ?
                  AND target_dataset_release_id = ?
                """,
                (track_id, generation_id, target_release_id),
            ).fetchone()
            if existing is not None:
                self.metadata.enqueue_tracking_advance_execution(
                    connection,
                    track_id=track_id,
                    advance_id=str(existing["id"]),
                    created_at=now,
                )
                return self._advance_from_row(existing)
            advance_id = f"advance_{uuid4().hex[:20]}"
            connection.execute(
                """
                INSERT INTO tracking_advances
                    (id, daily_track_id, generation_id,
                     target_dataset_release_id, correction_boundary_json,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    advance_id,
                    track_id,
                    generation_id,
                    target_release_id,
                    correction_boundary_json,
                    now,
                    now,
                ),
            )
            self.metadata.enqueue_tracking_advance_execution(
                connection,
                track_id=track_id,
                advance_id=advance_id,
                created_at=now,
            )
        return self._advance(advance_id)

    def _claim_advance(
        self,
        advance_id: str,
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tracking_advances WHERE id = ?",
                (advance_id,),
            ).fetchone()
            if row is None:
                raise KeyError(advance_id)
            self.metadata.lock_daily_track(
                connection,
                str(row["daily_track_id"]),
            )
            row = connection.execute(
                "SELECT * FROM tracking_advances WHERE id = ?",
                (advance_id,),
            ).fetchone()
            if row is None:
                raise KeyError(advance_id)
            if row["status"] not in {"pending", "blocked"}:
                return None
            track = connection.execute(
                """
                SELECT status, fencing_token
                FROM daily_tracks
                WHERE id = ?
                """,
                (row["daily_track_id"],),
            ).fetchone()
            if track is None or track["status"] != "active":
                return None
            fencing_token = int(track["fencing_token"]) + 1
            ordinal = (
                int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(ordinal), 0)
                        FROM tracking_advance_attempts
                        WHERE advance_id = ?
                        """,
                        (advance_id,),
                    ).fetchone()[0]
                )
                + 1
            )
            attempt_id = f"track_attempt_{uuid4().hex[:20]}"
            advance_update = connection.execute(
                """
                UPDATE tracking_advances
                SET status = 'running', updated_at = ?
                WHERE id = ? AND status IN ('pending', 'blocked')
                """,
                (now, advance_id),
            )
            track_update = connection.execute(
                """
                UPDATE daily_tracks
                SET fencing_token = ?
                WHERE id = ? AND status = 'active'
                  AND fencing_token = ?
                """,
                (
                    fencing_token,
                    row["daily_track_id"],
                    track["fencing_token"],
                ),
            )
            if (
                advance_update.rowcount != 1
                or track_update.rowcount != 1
            ):
                raise DailyTrackingError("Advance claim was fenced")
            connection.execute(
                """
                INSERT INTO tracking_advance_attempts
                    (id, advance_id, ordinal, status, started_at, fencing_token)
                VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (attempt_id, advance_id, ordinal, now, fencing_token),
            )
        self.cache.advance_fence(
            str(row["daily_track_id"]),
            fencing_token,
            stopped=False,
        )
        return self._advance(advance_id), {
            "id": attempt_id,
            "ordinal": ordinal,
            "fencing_token": fencing_token,
        }

    def _publish_advance_success(
        self,
        advance: dict[str, object],
        attempt: dict[str, object],
        checkpoint: dict[str, object],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        manifest = checkpoint["manifest"]
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.metadata.lock_daily_track(
                connection,
                str(advance["daily_track_id"]),
            )
            track = connection.execute(
                """
                SELECT status, current_generation_id, head_checkpoint_id,
                       fencing_token
                FROM daily_tracks
                WHERE id = ?
                """,
                (advance["daily_track_id"],),
            ).fetchone()
            current = connection.execute(
                "SELECT status FROM tracking_advances WHERE id = ?",
                (advance["id"],),
            ).fetchone()
            current_attempt = connection.execute(
                """
                SELECT status, fencing_token
                FROM tracking_advance_attempts
                WHERE id = ? AND advance_id = ?
                """,
                (attempt["id"], advance["id"]),
            ).fetchone()
            predecessor_checkpoint_id = manifest["predecessor_checkpoint_id"]
            replay = predecessor_checkpoint_id is None
            expected_generation_id = (
                manifest["supersedes_generation_id"]
                if replay
                else advance["generation_id"]
            )
            expected_head_checkpoint_id = (
                manifest["supersedes_head_checkpoint_id"]
                if replay
                else predecessor_checkpoint_id
            )
            if (
                track is None
                or current is None
                or current_attempt is None
                or track["status"] != "active"
                or track["current_generation_id"] != expected_generation_id
                or track["head_checkpoint_id"] != expected_head_checkpoint_id
                or current["status"] != "running"
                or current_attempt["status"] != "running"
                or int(track["fencing_token"]) != int(
                    current_attempt["fencing_token"]
                )
                or int(manifest["cache_fencing_token"]) != int(
                    current_attempt["fencing_token"]
                )
            ):
                raise DailyTrackingError("Advance publication was fenced")
            storage_objects = checkpoint.get("storage_objects")
            if not isinstance(storage_objects, list):
                raise DailyTrackingError(
                    "Checkpoint storage accounting is missing"
                )
            self.metadata.commit_private_storage_references(
                connection,
                resource_kind="tracking_checkpoint",
                resource_id=str(checkpoint["id"]),
                objects=storage_objects,
            )
            connection.execute(
                """
                INSERT INTO tracking_checkpoints
                    (id, daily_track_id, generation_id,
                     predecessor_checkpoint_id, target_dataset_release_id,
                     manifest_sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint["id"],
                    advance["daily_track_id"],
                    advance["generation_id"],
                    manifest["predecessor_checkpoint_id"],
                    advance["target_dataset_release_id"],
                    checkpoint["manifest_sha256"],
                    now,
                ),
            )
            attempt_update = connection.execute(
                """
                UPDATE tracking_advance_attempts
                SET status = 'succeeded', completed_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, attempt["id"]),
            )
            advance_update = connection.execute(
                """
                UPDATE tracking_advances
                SET status = 'succeeded', checkpoint_id = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (checkpoint["id"], now, advance["id"]),
            )
            track_update = connection.execute(
                """
                UPDATE daily_tracks
                SET current_generation_id = ?, head_checkpoint_id = ?
                WHERE id = ? AND status = 'active'
                  AND current_generation_id = ?
                  AND head_checkpoint_id = ?
                  AND fencing_token = ?
                """,
                (
                    advance["generation_id"],
                    checkpoint["id"],
                    advance["daily_track_id"],
                    expected_generation_id,
                    expected_head_checkpoint_id,
                    current_attempt["fencing_token"],
                ),
            )
            if (
                attempt_update.rowcount != 1
                or advance_update.rowcount != 1
                or track_update.rowcount != 1
            ):
                raise DailyTrackingError("Advance publication was fenced")

    def _block_advance(
        self,
        advance: dict[str, object],
        attempt: dict[str, object],
        diagnostic: dict[str, object],
        *,
        terminal: bool = False,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        diagnostic_json = json.dumps(
            diagnostic,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT status FROM tracking_advances WHERE id = ?",
                (advance["id"],),
            ).fetchone()
            current_attempt = connection.execute(
                """
                SELECT status
                FROM tracking_advance_attempts
                WHERE id = ? AND advance_id = ?
                """,
                (attempt["id"], advance["id"]),
            ).fetchone()
            if (
                current is None
                or current_attempt is None
                or current["status"] != "running"
                or current_attempt["status"] != "running"
            ):
                return
            connection.execute(
                """
                UPDATE tracking_advance_attempts
                SET status = 'failed', completed_at = ?, diagnostic_json = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, diagnostic_json, attempt["id"]),
            )
            connection.execute(
                """
                UPDATE tracking_advances
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    "failed" if terminal else "blocked",
                    now,
                    advance["id"],
                ),
            )

    def _advance(self, advance_id: str) -> dict[str, object]:
        with self.metadata.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tracking_advances WHERE id = ?",
                (advance_id,),
            ).fetchone()
            if row is None:
                raise KeyError(advance_id)
            attempts = connection.execute(
                """
                SELECT *
                FROM tracking_advance_attempts
                WHERE advance_id = ?
                ORDER BY ordinal
                """,
                (advance_id,),
            ).fetchall()
        result = self._advance_from_row(row)
        result["attempts"] = [
            {
                **{key: attempt[key] for key in attempt.keys() if key != "diagnostic_json"},
                "diagnostic": (
                    json.loads(str(attempt["diagnostic_json"]))
                    if attempt["diagnostic_json"] is not None
                    else None
                ),
            }
            for attempt in attempts
        ]
        return result

    @staticmethod
    def _advance_from_row(row: object) -> dict[str, object]:
        result = {
            key: row[key]
            for key in row.keys()
            if key != "correction_boundary_json"
        }
        raw_boundary = row["correction_boundary_json"]
        result["correction_boundary"] = (
            json.loads(str(raw_boundary))
            if raw_boundary is not None
            else None
        )
        return result

    def _checkpoint_manifest(self, digest: str) -> dict[str, object]:
        value = self.objects.read_json(digest)
        if not isinstance(value, dict):
            raise DailyTrackingError("Tracking Checkpoint is invalid")
        return value

    def _release_chain(
        self,
        ancestor_id: str,
        descendant_id: str,
    ) -> list[dict[str, object]]:
        chain: list[dict[str, object]] = []
        current = self.metadata.dataset_release(descendant_id)
        while current is not None and current["id"] != ancestor_id:
            chain.append(current)
            predecessor = current.get("predecessor_id")
            current = (
                self.metadata.dataset_release(str(predecessor)) if predecessor is not None else None
            )
        if current is None:
            return []
        return list(reversed(chain))


def public_tracking_generation(
    generation: dict[str, object],
) -> dict[str, object]:
    return {
        key: generation[key]
        for key in (
            "id",
            "daily_track_id",
            "ordinal",
            "basis_dataset_release_id",
            "calculation_kernel",
            "reason",
            "supersedes_generation_id",
            "supersedes_head_checkpoint_id",
            "created_at",
        )
        if key in generation
    }


def processed_session_manifest_fields(
    sessions: list[str],
) -> dict[str, object]:
    return {
        "processed_session_count": len(sessions),
        "processed_session_range": (
            {
                "start": sessions[0],
                "end": sessions[-1],
            }
            if sessions
            else None
        ),
    }


def checkpoint_processed_sessions_match(
    manifest: dict[str, object],
    sessions: object,
) -> bool:
    if not isinstance(sessions, list) or not all(
        isinstance(session, str) for session in sessions
    ):
        return False
    legacy = manifest.get("processed_sessions")
    if isinstance(legacy, list):
        return legacy == sessions
    return processed_session_manifest_fields(sessions) == {
        "processed_session_count": manifest.get(
            "processed_session_count"
        ),
        "processed_session_range": manifest.get(
            "processed_session_range"
        ),
    }


def public_tracking_advance(
    advance: dict[str, object],
) -> dict[str, object]:
    result = {
        key: advance[key]
        for key in (
            "id",
            "daily_track_id",
            "generation_id",
            "target_dataset_release_id",
            "status",
            "correction_boundary",
            "attempt_count",
            "created_at",
            "updated_at",
        )
        if key in advance
    }
    attempts = advance.get("attempts")
    if isinstance(attempts, list):
        result["attempts"] = [
            {
                key: attempt[key]
                for key in (
                    "ordinal",
                    "status",
                    "created_at",
                    "completed_at",
                    "diagnostic",
                )
                if key in attempt
            }
            for attempt in attempts
            if isinstance(attempt, dict)
        ]
    return result


def public_tracking_checkpoint(
    checkpoint: dict[str, object],
) -> dict[str, object]:
    return {
        key: checkpoint[key]
        for key in (
            "id",
            "daily_track_id",
            "generation_id",
            "predecessor_checkpoint_id",
            "target_dataset_release_id",
            "created_at",
        )
        if key in checkpoint
    }


def public_checkpoint_manifest(
    manifest: dict[str, object],
    *,
    limit: int,
) -> dict[str, object]:
    processed = manifest.get("processed_sessions")
    processed_sessions = (
        [str(session) for session in processed[-limit:]]
        if isinstance(processed, list)
        else []
    )
    processed_count = int(
        manifest.get(
            "processed_session_count",
            len(processed) if isinstance(processed, list) else 0,
        )
    )
    processed_range = manifest.get("processed_session_range")
    if not isinstance(processed_range, dict):
        processed_range = (
            {
                "start": str(processed[0]),
                "end": str(processed[-1]),
            }
            if isinstance(processed, list) and processed
            else None
        )
    return {
        key: value
        for key, value in {
            "id": manifest.get("id"),
            "kind": manifest.get("kind"),
            "generation_id": manifest.get("generation_id"),
            "predecessor_checkpoint_id": manifest.get(
                "predecessor_checkpoint_id"
            ),
            "target_dataset_release_id": manifest.get(
                "target_dataset_release_id"
            ),
            "processed_sessions": processed_sessions,
            "processed_session_count": processed_count,
            "processed_session_range": processed_range,
            "correction_boundary": manifest.get(
                "correction_boundary"
            ),
            "created_at": manifest.get("created_at"),
        }.items()
        if value is not None
    }


def public_daily_track_view(
    track: dict[str, object],
) -> dict[str, object]:
    result = {
        key: track[key]
        for key in (
            "id",
            "seed_run_id",
            "definition_version_id",
            "activation_release_id",
            "origin_session",
            "numeric_execution_contract",
            "status",
            "current_generation_id",
            "head_checkpoint_id",
            "created_at",
            "stopped_at",
        )
        if key in track
    }
    result["generations"] = [
        public_tracking_generation(item)
        for item in track.get("generations", [])
        if isinstance(item, dict)
    ]
    result["advances"] = [
        public_tracking_advance(item)
        for item in track.get("advances", [])
        if isinstance(item, dict)
    ]
    result["checkpoints"] = [
        public_tracking_checkpoint(item)
        for item in track.get("checkpoints", [])
        if isinstance(item, dict)
    ]
    head = track.get("head")
    result["head"] = (
        public_tracking_checkpoint(head)
        if isinstance(head, dict)
        else None
    )
    history = track.get("history")
    if isinstance(history, dict):
        result["history"] = dict(history)
    deletion = track.get("cache_deletion")
    result["cache_cleanup_status"] = (
        str(deletion["status"])
        if isinstance(deletion, dict) and "status" in deletion
        else None
    )
    return result


def slice_canonical_through(
    canonical: dict[str, object],
    final_session: str,
) -> dict[str, object]:
    copied = json.loads(json.dumps(canonical, ensure_ascii=False, allow_nan=False))
    calendar = [str(item) for item in copied["research_calendar"]]
    final_index = calendar.index(final_session)
    selected = calendar[: final_index + 1]
    selected_set = set(selected)
    copied["research_calendar"] = selected
    for key in (
        "prices",
        "trading_states",
        "price_limits",
        "base_pool",
        "st_designations",
    ):
        rows = copied.get(key)
        if isinstance(rows, list):
            copied[key] = [
                row
                for row in rows
                if isinstance(row, dict)
                and str(row.get("session") or row.get("trade_date")) in selected_set
            ]
    copied["liquidity_universes"] = {
        name: [
            row for row in rows if isinstance(row, dict) and str(row.get("session")) in selected_set
        ]
        for name, rows in copied["liquidity_universes"].items()
    }
    return copied


def apply_calculation_kernel(
    matrix: dict[str, object],
    kernel: str,
) -> dict[str, object]:
    if kernel not in SUPPORTED_CALCULATION_KERNELS:
        raise DailyTrackingError(f"unsupported calculation kernel: {kernel}")
    if kernel == "kernel-v2":
        for session in matrix["sessions"]:
            for row in session["values"]:
                value = float(row["value"])
                if value == 0.0:
                    row["value"] = 0.0
        matrix["checksum"] = alpha_matrix_checksum(matrix)
    return matrix


def alpha_matrix_checksum(matrix: dict[str, object]) -> str:
    checksum = hashlib.sha256()
    for session in matrix["sessions"]:
        checksum.update(str(session["session"]).encode())
        checksum.update(b"\0")
        for row in session["values"]:
            checksum.update(str(row["instrument_id"]).encode())
            checksum.update(b"\0")
            checksum.update(canonical_binary64_bytes(float(row["value"])))
    return checksum.hexdigest()


def slice_canonical_range(
    canonical: dict[str, object],
    first_session: str,
) -> dict[str, object]:
    copied = json.loads(json.dumps(canonical, ensure_ascii=False, allow_nan=False))
    calendar = [str(item) for item in copied["research_calendar"]]
    first_index = calendar.index(first_session)
    selected = calendar[first_index:]
    selected_set = set(selected)
    copied["research_calendar"] = selected
    for key in (
        "prices",
        "trading_states",
        "price_limits",
        "base_pool",
        "st_designations",
    ):
        rows = copied.get(key)
        if isinstance(rows, list):
            copied[key] = [
                row
                for row in rows
                if isinstance(row, dict)
                and str(row.get("session") or row.get("trade_date")) in selected_set
            ]
    copied["liquidity_universes"] = {
        name: [
            row for row in rows if isinstance(row, dict) and str(row.get("session")) in selected_set
        ]
        for name, rows in copied["liquidity_universes"].items()
    }
    return copied


def alpha_matrix_from_pending(
    definition: dict[str, object],
    pending: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    alpha = definition.get("alpha")
    if not isinstance(alpha, dict):
        raise DailyTrackingError("Alpha Definition is invalid")
    matrix = {
        "expression": str(alpha["expression"]),
        "effective_lookback": validate_alpha(
            str(alpha["expression"])
        ).effective_lookback,
        "neutralization": definition["neutralization"],
        "sessions": [
            {
                "session": session,
                "values": [
                    {
                        "instrument_id": str(row["instrument_id"]),
                        "value": float(row["value"]),
                    }
                    for row in sorted(
                        rows,
                        key=lambda value: str(value["instrument_id"]),
                    )
                ],
                "coverage_loss": {},
            }
            for session, rows in sorted(pending.items())
        ],
    }
    matrix["checksum"] = alpha_matrix_checksum(matrix)
    return matrix


def rolling_factor_row(
    session: str,
    horizon: int,
    metrics: dict[str, object],
    *,
    sample_count: int,
) -> dict[str, object]:
    quantiles = metrics["quantile_returns"]
    if not isinstance(quantiles, dict):
        raise DailyTrackingError("Factor quantile result is invalid")
    return {
        "session": session,
        "horizon": horizon,
        "sample_count": sample_count,
        "ic": metrics["ic"],
        "rank_ic": metrics["rank_ic"],
        "q1": quantiles["q1"],
        "q2": quantiles["q2"],
        "q3": quantiles["q3"],
        "q4": quantiles["q4"],
        "q5": quantiles["q5"],
        "top_bottom_return": metrics["top_bottom_return"],
        "correlation_reason": metrics["correlation_reason"],
        "quantile_reason": metrics["quantile_reason"],
    }


def bounded_tracking_projection(
    projection: dict[str, object],
    limit: int,
) -> dict[str, object]:
    strategy = projection.get("strategy")
    if not isinstance(strategy, dict):
        raise DailyTrackingError("Tracking Strategy projection is invalid")
    bounded_strategy = dict(strategy)
    for key in (
        "daily",
        "rebalance_aggregates",
        "execution_aggregates",
    ):
        rows = bounded_strategy.get(key)
        if not isinstance(rows, list):
            raise DailyTrackingError(
                f"Tracking Strategy projection {key} is invalid"
            )
        bounded_strategy[key] = [dict(row) for row in rows[-limit:]]
    return {
        **projection,
        "strategy": bounded_strategy,
    }


def rolling_factor_summary(
    rolling_rows: list[dict[str, object]],
) -> dict[str, object]:
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        daily = [
            row for row in rolling_rows if int(row["horizon"]) == horizon
        ]
        daily.sort(key=lambda row: str(row["session"]))
        correlation_reasons = Counter(
            str(row["correlation_reason"])
            for row in daily
            if row["correlation_reason"] is not None
        )
        quantile_reasons = Counter(
            str(row["quantile_reason"])
            for row in daily
            if row["quantile_reason"] is not None
        )
        summary = {
            "ic": correlation_summary(daily, "ic"),
            "rank_ic": correlation_summary(daily, "rank_ic"),
            "quantile_returns": {
                name: mean_or_none(
                    [
                        float(row[name])
                        for row in daily
                        if row[name] is not None
                    ]
                )
                for name in ("q1", "q2", "q3", "q4", "q5")
            },
            "top_bottom_return": mean_or_none(
                [
                    float(row["top_bottom_return"])
                    for row in daily
                    if row["top_bottom_return"] is not None
                ]
            ),
        }
        source_checksum = hashlib.sha256(canonical_json_bytes(daily)).hexdigest()
        horizons[str(horizon)] = {
            "horizon": horizon,
            "alpha_checksum": source_checksum,
            "label_checksum": source_checksum,
            "source_checksum": source_checksum,
            "summary": summary,
            "diagnostics": {
                "session_count": len(daily),
                "missing_session_count": sum(
                    row["correlation_reason"] is not None
                    or row["quantile_reason"] is not None
                    for row in daily
                ),
                "correlation_reason_counts": dict(
                    sorted(correlation_reasons.items())
                ),
                "quantile_reason_counts": dict(sorted(quantile_reasons.items())),
            },
        }
    return {"horizons": horizons}


def factor_artifact_to_rolling_rows(
    factor: dict[str, object],
) -> list[dict[str, object]]:
    horizons = factor.get("horizons")
    if not isinstance(horizons, dict):
        raise DailyTrackingError("Factor Evaluation is invalid")
    rows: list[dict[str, object]] = []
    for horizon, value in sorted(horizons.items(), key=lambda item: int(item[0])):
        if not isinstance(value, dict) or not isinstance(value.get("daily"), list):
            raise DailyTrackingError("Factor horizon is invalid")
        for row in value["daily"]:
            rows.append(
                rolling_factor_row(
                    str(row["session"]),
                    int(horizon),
                    row,
                    sample_count=int(row["sample_count"]),
                )
            )
    return rows


def incremental_terminal_state(
    strategy: dict[str, object],
    prior_terminal: dict[str, object],
    definition: dict[str, object],
    processed_session_count: int,
    metric_state: dict[str, object],
    positions_entry: dict[str, object],
) -> dict[str, object]:
    daily = strategy.get("daily")
    if not isinstance(daily, list) or not daily:
        raise DailyTrackingError("incremental Strategy state is empty")
    terminal = daily[-1]
    prior_phase = prior_terminal.get("rebalance_phase")
    strategy_definition = definition.get("strategy")
    if not isinstance(prior_phase, dict) or not isinstance(
        strategy_definition,
        dict,
    ):
        raise DailyTrackingError("Strategy Rebalance phase is invalid")
    report_session_count = int(prior_phase["report_session_count"]) + (
        processed_session_count
    )
    rebalance_interval = int(strategy_definition["rebalance_interval"])
    pending_signal = (
        {
            "signal_session": str(terminal["session"]),
            "execution": "next_research_session_open",
        }
        if (report_session_count - 1) % rebalance_interval == 0
        else None
    )
    return {
        "session": str(terminal["session"]),
        "gross_cash": str(terminal["gross_cash"]),
        "net_cash": str(terminal["net_cash"]),
        "gross_nav": str(terminal["gross_nav"]),
        "net_nav": str(terminal["net_nav"]),
        "benchmark_nav": str(terminal["benchmark_nav"]),
        "cumulative_transaction_cost": str(
            terminal["cumulative_transaction_cost"]
        ),
        "rebalance_phase": {
            "origin_session": prior_phase["origin_session"],
            "report_session_count": report_session_count,
            "rebalance_interval": rebalance_interval,
            "completed_intervals": report_session_count - 1,
        },
        "pending_signal": pending_signal,
        "last_daily_observation": dict(terminal),
        "metric_state": dict(metric_state),
        "positions_object": {
            key: positions_entry[key]
            for key in ("sha256", "bytes", "writer_contract_id")
        },
    }


def first_divergence(actual: object, expected: object, path: str = "$") -> str:
    if type(actual) is not type(expected):
        return path
    if isinstance(actual, dict):
        keys = sorted(set(actual) | set(expected))
        for key in keys:
            if key not in actual or key not in expected:
                return f"{path}.{key}"
            divergence = first_divergence(actual[key], expected[key], f"{path}.{key}")
            if divergence:
                return divergence
        return ""
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}.length"
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            divergence = first_divergence(left, right, f"{path}[{index}]")
            if divergence:
                return divergence
        return ""
    return (
        ""
        if equivalence_bytes(actual) == equivalence_bytes(expected)
        else path
    )


def equivalence_bytes(value: object) -> bytes:
    def normalize(item: object) -> object:
        if isinstance(item, float):
            return {"$binary64": canonical_binary64_bytes(item).hex()}
        if isinstance(item, Decimal):
            return {"$decimal": canonical_decimal(item)}
        if isinstance(item, dict):
            return {
                str(key): normalize(child)
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    return canonical_json_bytes(normalize(value))


def report_progress(
    progress: Callable[[str], None] | None,
    stage: str,
) -> None:
    if progress is not None:
        progress(stage)

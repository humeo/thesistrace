import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from thesistrace.alpha import evaluate_alpha_matrix, validate_alpha
from thesistrace.datasets import DatasetPublisher
from thesistrace.factor import build_forward_labels, evaluate_factor
from thesistrace.numeric import canonical_binary64_bytes
from thesistrace.objects import ImmutableObjectStore, canonical_json_bytes
from thesistrace.research_runs import RUNTIME_BUILD
from thesistrace.storage import MetadataStore
from thesistrace.strategy import run_strategy


class DailyTrackingError(RuntimeError):
    pass


class EquivalenceError(DailyTrackingError):
    pass


SUPPORTED_CALCULATION_KERNELS = {"kernel-v1", "kernel-v2"}


class DailyTrackingService:
    def __init__(
        self,
        metadata: MetadataStore,
        datasets: DatasetPublisher,
        objects: ImmutableObjectStore,
    ) -> None:
        self.metadata = metadata
        self.datasets = datasets
        self.objects = objects

    def activate(
        self,
        run_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        with self.metadata.connect() as connection:
            existing = connection.execute(
                """
                SELECT daily_track_id
                FROM daily_track_activation_idempotency
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        if existing is not None:
            track = self.get_track(str(existing["daily_track_id"]))
            if track is None:
                raise DailyTrackingError("idempotent DailyTrack disappeared")
            return track, False

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
        entries = manifest.get("objects")
        if not isinstance(entries, dict):
            raise DailyTrackingError("seed Result Manifest is invalid")
        strategy = self._read_result_object(entries, "strategy_backtest")
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
            "processed_sessions": [],
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
            "objects": {
                "alpha_matrix": entries["alpha_matrix"],
                "forward_labels": entries["forward_labels"],
                "factor_evaluation": entries["factor_evaluation"],
                "strategy_backtest": entries["strategy_backtest"],
            },
            "pending_strategy_signal": pending_signal,
            "numeric_execution_contract": content["numeric_execution_contract"],
            "calculation_kernel": manifest["calculation_kernel"],
            "runtime_build": RUNTIME_BUILD,
            "created_at": now,
        }
        checkpoint_object = self.objects.put_json(checkpoint_manifest)
        self.objects.put_manifest(checkpoint_id, checkpoint_manifest)
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO daily_tracks
                    (id, seed_run_id, definition_version_id,
                     definition_content_hash, activation_release_id,
                     origin_session, numeric_execution_contract, status,
                     current_generation_id, head_checkpoint_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    track_id,
                    run_id,
                    frozen["id"],
                    frozen["content_hash"],
                    release["id"],
                    origin_session,
                    content["numeric_execution_contract"],
                    generation_id,
                    checkpoint_id,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO tracking_generations
                    (id, daily_track_id, ordinal, calculation_kernel,
                     numeric_execution_contract, basis_dataset_release_id,
                     reason, created_at)
                VALUES (?, ?, 0, ?, ?, ?, 'activation', ?)
                """,
                (
                    generation_id,
                    track_id,
                    manifest["calculation_kernel"],
                    content["numeric_execution_contract"],
                    release["id"],
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO tracking_checkpoints
                    (id, daily_track_id, generation_id,
                     predecessor_checkpoint_id, target_dataset_release_id,
                     manifest_sha256, created_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    track_id,
                    generation_id,
                    release["id"],
                    checkpoint_object["sha256"],
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO daily_track_activation_idempotency
                    (idempotency_key, daily_track_id)
                VALUES (?, ?)
                """,
                (idempotency_key, track_id),
            )
        latest = self.metadata.latest_dataset_release()
        if latest is not None and latest["id"] != release["id"]:
            self.enqueue_toward(track_id, str(latest["id"]))
        track = self.get_track(track_id)
        if track is None:
            raise DailyTrackingError("activated DailyTrack disappeared")
        return track, True

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
        track = {key: row[key] for key in row.keys()}
        track["generations"] = [
            {key: generation[key] for key in generation.keys()} for generation in generations
        ]
        track["advances"] = [{key: advance[key] for key in advance.keys()} for advance in advances]
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
        return track

    def list_tracks(self) -> list[dict[str, object]]:
        with self.metadata.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM daily_tracks ORDER BY created_at, id"
            ).fetchall()
        return [track for row in rows if (track := self.get_track(str(row["id"]))) is not None]

    def current_view(self, track_id: str) -> dict[str, object]:
        track = self.get_track(track_id)
        if track is None:
            raise KeyError(track_id)
        head = track["head"]
        if not isinstance(head, dict):
            raise DailyTrackingError("DailyTrack has no Head")
        manifest = self._checkpoint_manifest(str(head["manifest_sha256"]))
        objects = manifest.get("objects")
        factor_kind = (
            "factor_summary"
            if isinstance(objects, dict) and "factor_summary" in objects
            else "factor_evaluation"
        )
        label_maturation = (
            self._read_result_object(objects, "label_maturation")
            if isinstance(objects, dict) and "label_maturation" in objects
            else {"events": []}
        )
        return {
            "daily_track": {
                "id": track["id"],
                "status": track["status"],
                "generation_id": track["current_generation_id"],
                "head_checkpoint_id": track["head_checkpoint_id"],
            },
            "checkpoint": manifest,
            "factor_summary": self._read_result_object(objects, factor_kind),
            "strategy": self._read_result_object(objects, "strategy_backtest"),
            "recent_label_maturation": label_maturation,
        }

    def stop(self, track_id: str) -> dict[str, object] | None:
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute(
                """
                UPDATE daily_tracks
                SET status = 'stopped', stopped_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, track_id),
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
                WHERE daily_track_id = ? AND status = 'running'
                """,
                (now, track_id),
            )
        return self.get_track(track_id)

    def enqueue_active_tracks(self, target_release_id: str) -> list[dict[str, str]]:
        failures: list[dict[str, str]] = []
        for track in self.list_tracks():
            if track["status"] == "active":
                try:
                    self.enqueue_toward(str(track["id"]), target_release_id)
                except DailyTrackingError as error:
                    failures.append(
                        {
                            "track_id": str(track["id"]),
                            "reason_code": "TRACK_ENQUEUE_FAILED",
                            "message": str(error),
                        }
                    )
        return failures

    def enqueue_toward(self, track_id: str, target_release_id: str) -> dict[str, object] | None:
        track = self.get_track(track_id)
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
        chain = self._release_chain(head_release_id, target_release_id)
        if not chain:
            raise DailyTrackingError("target Release is not a descendant of Tracking Head")
        next_release = chain[0]
        correction = self._corrections_affect_track(
            track,
            next_release.get("correction_change_set"),
            next_release,
        )
        if correction:
            generation = next(
                (
                    item
                    for item in track["generations"]
                    if item["reason"] == "historical_correction"
                    and item["basis_dataset_release_id"] == next_release["id"]
                    and item["supersedes_generation_id"]
                    == track["current_generation_id"]
                    and item["supersedes_head_checkpoint_id"]
                    == track["head_checkpoint_id"]
                ),
                None,
            )
            if generation is None:
                generation = self._create_generation_with_advance(
                    str(track["id"]),
                    basis_release_id=str(next_release["id"]),
                    kernel=self._generation_kernel(
                        track,
                        str(track["current_generation_id"]),
                    ),
                    reason="historical_correction",
                    target_release_id=str(next_release["id"]),
                    expected_generation_id=str(track["current_generation_id"]),
                    expected_head_checkpoint_id=str(track["head_checkpoint_id"]),
                )
            generation_id = str(generation["id"])
        else:
            generation_id = str(track["current_generation_id"])
        return self._create_advance(
            track_id,
            generation_id,
            str(next_release["id"]),
        )

    def _corrections_affect_track(
        self,
        track: dict[str, object],
        change_set: object,
        target_release: dict[str, object],
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
        canonical = self.datasets.materialize_canonical(target_release)
        calendar = [str(session) for session in canonical["research_calendar"]]
        origin_index = calendar.index(str(track["origin_session"]))
        alpha_start = max(
            0,
            origin_index - parsed_alpha.effective_lookback,
        )
        liquidity_start = max(0, origin_index - 19)
        universes = canonical.get("liquidity_universes")
        selected_universe = (
            universes.get(str(definition["universe"]))
            if isinstance(universes, dict)
            else None
        )
        if not isinstance(selected_universe, list):
            raise DailyTrackingError("Tracking Universe is missing")
        potentially_relevant_instruments = {
            str(instrument_id)
            for snapshot in selected_universe[alpha_start:]
            if isinstance(snapshot, dict)
            for instrument_id in snapshot.get("instrument_ids", [])
        }
        alpha_dependency = {
            "open_raw": "open_adj",
            "high_raw": "high_adj",
            "low_raw": "low_adj",
            "close_raw": "close_adj",
            "volume_shares": "volume_shares",
            "turnover_cny": "turnover_amount_cny",
        }
        for correction in change_set:
            if not isinstance(correction, dict):
                raise DailyTrackingError("Dataset correction change set is invalid")
            field = str(correction.get("field"))
            session = str(correction.get("session"))
            instrument_id = str(correction.get("instrument_id"))
            if session not in calendar:
                raise DailyTrackingError("Dataset correction session is invalid")
            session_index = calendar.index(session)
            if (
                field == "open_raw"
                and instrument_id in potentially_relevant_instruments
            ):
                return True
            if field == "turnover_cny" and session_index >= liquidity_start:
                return True
            if (
                alpha_dependency.get(field) in alpha_fields
                and instrument_id in potentially_relevant_instruments
                and session_index >= alpha_start
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

    def execute_advance(self, advance_id: str) -> dict[str, object]:
        claimed = self._claim_advance(advance_id)
        if claimed is None:
            return self._advance(advance_id)
        advance, attempt = claimed
        try:
            checkpoint = self._calculate_advance(advance)
            self._publish_advance_success(
                advance,
                attempt,
                checkpoint,
            )
        except Exception as error:
            self._block_advance(
                advance,
                attempt,
                {
                    "reason_code": (
                        "EQUIVALENCE_MISMATCH"
                        if isinstance(error, EquivalenceError)
                        else "TRACKING_CALCULATION_FAILED"
                    ),
                    "message": str(error),
                },
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

    def upgrade_kernel(
        self,
        track_id: str,
        *,
        calculation_kernel: str,
        numeric_execution_contract: str,
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
        )
        updated = self.get_track(track_id)
        if updated is None:
            raise KeyError(track_id)
        return updated

    def verify_equivalence(self, track_id: str) -> dict[str, object]:
        track = self.get_track(track_id)
        if track is None:
            raise KeyError(track_id)
        head = track["head"]
        if not isinstance(head, dict):
            raise DailyTrackingError("DailyTrack has no Head")
        checkpoint = self._checkpoint_manifest(str(head["manifest_sha256"]))
        oracle = self._batch_oracle(
            track,
            str(head["target_dataset_release_id"]),
            kernel=self._generation_kernel(track, str(head["generation_id"])),
        )
        comparisons = {
            "alpha_matrix": oracle["alpha_matrix"],
            "forward_labels": oracle["forward_labels"],
            "factor_evaluation": oracle["factor_evaluation"],
            "strategy_backtest": oracle["strategy_backtest"],
        }
        objects = checkpoint.get("objects")
        if not isinstance(objects, dict):
            raise EquivalenceError("Checkpoint object index is invalid")
        for kind, expected in comparisons.items():
            entry = objects.get(kind)
            if not isinstance(entry, dict):
                raise EquivalenceError(f"missing checkpoint object: {kind}")
            actual = self.objects.read_json(str(entry["sha256"]))
            if equivalence_bytes(actual) != equivalence_bytes(expected):
                coordinate = first_divergence(actual, expected)
                raise EquivalenceError(f"{kind} diverged at {coordinate}")
        return {
            "status": "equivalent",
            "daily_track_id": track_id,
            "generation_id": head["generation_id"],
            "target_dataset_release_id": head["target_dataset_release_id"],
            "checkpoint_id": head["id"],
        }

    def _calculate_advance(
        self,
        advance: dict[str, object],
    ) -> dict[str, object]:
        track = self.get_track(str(advance["daily_track_id"]))
        if track is None:
            raise DailyTrackingError("DailyTrack not found")
        target = self.metadata.dataset_release(str(advance["target_dataset_release_id"]))
        frozen = self.metadata.frozen_research_definition(str(track["definition_version_id"]))
        if target is None or frozen is None:
            raise DailyTrackingError("Tracking inputs are missing")
        definition = frozen["content"]
        if not isinstance(definition, dict):
            raise DailyTrackingError("Tracking Definition is invalid")
        canonical = self.datasets.materialize_canonical(target)
        generation = next(
            item for item in track["generations"] if item["id"] == advance["generation_id"]
        )
        kernel = str(generation["calculation_kernel"])
        replay = (
            generation["reason"] != "activation"
            and generation["id"] != track["current_generation_id"]
        )
        activation_release = self.metadata.dataset_release(str(track["activation_release_id"]))
        if activation_release is None:
            raise DailyTrackingError("Activation Release is missing")
        activation_session = str(activation_release["appended_session_range"]["end"])
        prior_manifest: dict[str, object] | None = None
        prior_strategy: dict[str, object] | None = None
        if replay:
            alpha = self._alpha(canonical, definition, kernel=kernel)
            predecessor_id = None
            prior_session = str(track["origin_session"])
        else:
            head = track["head"]
            if not isinstance(head, dict):
                raise DailyTrackingError("DailyTrack has no Head")
            prior_manifest = self._checkpoint_manifest(str(head["manifest_sha256"]))
            prior_alpha = self._read_result_object(
                prior_manifest["objects"],
                "alpha_matrix",
            )
            prior_strategy = self._read_result_object(
                prior_manifest["objects"],
                "strategy_backtest",
            )
            prior_release = self.metadata.dataset_release(str(head["target_dataset_release_id"]))
            if prior_release is None:
                raise DailyTrackingError("Head Release is missing")
            prior_session = str(prior_release["appended_session_range"]["end"])
            alpha = append_alpha_matrix(
                canonical,
                definition,
                prior_alpha,
                prior_session,
                kernel=kernel,
            )
            predecessor_id = str(head["id"])
        origin_index = canonical["research_calendar"].index(track["origin_session"])
        report_sessions = len(canonical["research_calendar"]) - origin_index
        labels = build_forward_labels(
            canonical,
            alpha,
            report_sessions=report_sessions,
        )
        factor = evaluate_factor(labels)
        summary_labels = build_forward_labels(canonical, alpha, report_sessions=504)
        factor_summary = evaluate_factor(summary_labels)
        if replay:
            strategy = self._batch_oracle(
                track,
                str(target["id"]),
                alpha=alpha,
                labels=labels,
                factor=factor,
                kernel=kernel,
            )["strategy_backtest"]
        else:
            assert prior_strategy is not None
            strategy = run_strategy(
                canonical,
                alpha,
                definition,
                origin_session=str(track["origin_session"]),
                terminal_cutoff=False,
                continuation=prior_strategy,
            )
        calendar = [str(item) for item in canonical["research_calendar"]]
        processed_sessions = (
            calendar[origin_index:] if replay else calendar[calendar.index(prior_session) + 1 :]
        )
        checkpoint_id = f"checkpoint_{uuid4().hex[:20]}"
        maturation = label_maturation_events(
            labels,
            calendar,
            processed_sessions,
            generation_id=str(generation["id"]),
            basis_release_id=str(target["id"]),
            checkpoint_id=checkpoint_id,
        )
        artifacts = {
            "alpha_matrix": alpha,
            "forward_labels": labels,
            "factor_evaluation": factor,
            "factor_summary": factor_summary,
            "strategy_backtest": strategy,
            "label_maturation": {"events": maturation},
        }
        entries = {
            kind: {"kind": kind, **self.objects.put_json(value)}
            for kind, value in sorted(artifacts.items())
        }
        now = datetime.now(UTC).isoformat()
        manifest = {
            "id": checkpoint_id,
            "kind": "replay" if replay else "advance",
            "daily_track_id": track["id"],
            "generation_id": generation["id"],
            "predecessor_checkpoint_id": predecessor_id,
            "target_dataset_release_id": target["id"],
            "processed_sessions": processed_sessions,
            "tracking_origin": {
                "session": track["origin_session"],
                "activation_session": activation_session,
            },
            "definition": {
                "id": frozen["id"],
                "content_hash": frozen["content_hash"],
            },
            "numeric_execution_contract": track["numeric_execution_contract"],
            "calculation_kernel": generation["calculation_kernel"],
            "runtime_build": RUNTIME_BUILD,
            "basis_dataset_release_id": target["id"],
            "supersedes_generation_id": generation["supersedes_generation_id"],
            "supersedes_head_checkpoint_id": generation["supersedes_head_checkpoint_id"],
            "objects": entries,
            "created_at": now,
        }
        manifest_object = self.objects.put_json(manifest)
        self.objects.put_manifest(checkpoint_id, manifest)
        return {
            "id": checkpoint_id,
            "manifest_sha256": manifest_object["sha256"],
            "manifest": manifest,
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
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            return {key: existing[key] for key in existing.keys()}

    def _create_advance(
        self,
        track_id: str,
        generation_id: str,
        target_release_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
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
                return {key: existing[key] for key in existing.keys()}
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
                    generation_id,
                    target_release_id,
                    now,
                    now,
                ),
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
            if row["status"] not in {"pending", "blocked"}:
                return None
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
            connection.execute(
                """
                UPDATE tracking_advances
                SET status = 'running', updated_at = ?
                WHERE id = ?
                """,
                (now, advance_id),
            )
            connection.execute(
                """
                INSERT INTO tracking_advance_attempts
                    (id, advance_id, ordinal, status, started_at)
                VALUES (?, ?, ?, 'running', ?)
                """,
                (attempt_id, advance_id, ordinal, now),
            )
        return self._advance(advance_id), {
            "id": attempt_id,
            "ordinal": ordinal,
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
            track = connection.execute(
                """
                SELECT status, current_generation_id, head_checkpoint_id
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
                SELECT status
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
            ):
                raise DailyTrackingError("Advance publication was fenced")
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
            connection.execute(
                """
                UPDATE tracking_advance_attempts
                SET status = 'succeeded', completed_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, attempt["id"]),
            )
            connection.execute(
                """
                UPDATE tracking_advances
                SET status = 'succeeded', checkpoint_id = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (checkpoint["id"], now, advance["id"]),
            )
            connection.execute(
                """
                UPDATE daily_tracks
                SET current_generation_id = ?, head_checkpoint_id = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    advance["generation_id"],
                    checkpoint["id"],
                    advance["daily_track_id"],
                ),
            )

    def _block_advance(
        self,
        advance: dict[str, object],
        attempt: dict[str, object],
        diagnostic: dict[str, object],
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
                SET status = 'blocked', updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, advance["id"]),
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
        result = {key: row[key] for key in row.keys()}
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

    def _checkpoint_manifest(self, digest: str) -> dict[str, object]:
        value = self.objects.read_json(digest)
        if not isinstance(value, dict):
            raise DailyTrackingError("Tracking Checkpoint is invalid")
        return value

    def _read_result_object(
        self,
        entries: object,
        kind: str,
    ) -> dict[str, object]:
        if not isinstance(entries, dict):
            raise DailyTrackingError("object index is invalid")
        entry = entries.get(kind)
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
            raise DailyTrackingError(f"object index is missing {kind}")
        value = self.objects.read_json(str(entry["sha256"]))
        if not isinstance(value, dict):
            raise DailyTrackingError(f"{kind} object is invalid")
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


def label_maturation_events(
    labels: dict[str, object],
    calendar: list[str],
    processed_sessions: list[str],
    *,
    generation_id: str,
    basis_release_id: str,
    checkpoint_id: str,
) -> list[dict[str, object]]:
    processed = set(processed_sessions)
    events: list[dict[str, object]] = []
    for horizon_text, artifact in labels["horizons"].items():
        horizon = int(horizon_text)
        by_signal = {str(item["signal_session"]): item for item in artifact["sessions"]}
        for maturity_index, maturity_session in enumerate(calendar):
            if maturity_session not in processed:
                continue
            signal_index = maturity_index - 1 - horizon
            if signal_index < 0:
                continue
            signal_session = calendar[signal_index]
            item = by_signal.get(signal_session)
            if item is None:
                continue
            for resolution in item["resolutions"]:
                if resolution["reason"] == "right_censored_by_release_end":
                    continue
                events.append(
                    {
                        "generation_id": generation_id,
                        "signal_session": signal_session,
                        "horizon": horizon,
                        "maturity_session": maturity_session,
                        "instrument_id": resolution["instrument_id"],
                        "alpha": resolution["alpha"],
                        "label": resolution["label"],
                        "reason": resolution["reason"],
                        "basis_dataset_release_id": basis_release_id,
                        "publishing_checkpoint_id": checkpoint_id,
                    }
                )
    events.sort(
        key=lambda item: (
            item["maturity_session"],
            item["horizon"],
            item["signal_session"],
            item["instrument_id"],
        )
    )
    return events


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


def append_alpha_matrix(
    canonical: dict[str, object],
    definition: dict[str, object],
    prior: dict[str, object],
    prior_session: str,
    *,
    kernel: str,
) -> dict[str, object]:
    calendar = [str(item) for item in canonical["research_calendar"]]
    next_index = calendar.index(prior_session) + 1
    if next_index >= len(calendar):
        return prior
    lookback = int(prior["effective_lookback"])
    window_start = max(0, next_index - lookback)
    window = slice_canonical_range(canonical, calendar[window_start])
    alpha_definition = definition["alpha"]
    if not isinstance(alpha_definition, dict):
        raise DailyTrackingError("Alpha Definition is invalid")
    evaluated = evaluate_alpha_matrix(
        window,
        expression=str(alpha_definition["expression"]),
        universe_name=str(definition["universe"]),
        neutralization=str(definition["neutralization"]),
    )
    evaluated = apply_calculation_kernel(evaluated, kernel)
    new_sessions = set(calendar[next_index:])
    merged_sessions = [
        *prior["sessions"],
        *[item for item in evaluated["sessions"] if item["session"] in new_sessions],
    ]
    checksum = hashlib.sha256()
    for item in merged_sessions:
        checksum.update(str(item["session"]).encode())
        checksum.update(b"\0")
        for row in item["values"]:
            checksum.update(str(row["instrument_id"]).encode())
            checksum.update(b"\0")
            checksum.update(canonical_binary64_bytes(float(row["value"])))
    return {
        "expression": prior["expression"],
        "effective_lookback": lookback,
        "neutralization": prior["neutralization"],
        "sessions": merged_sessions,
        "checksum": checksum.hexdigest(),
    }


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
    return "" if actual == expected else path


def equivalence_bytes(value: object) -> bytes:
    def normalize(item: object) -> object:
        if isinstance(item, float):
            return {"$binary64": canonical_binary64_bytes(item).hex()}
        if isinstance(item, dict):
            return {
                str(key): normalize(child)
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    return canonical_json_bytes(normalize(value))

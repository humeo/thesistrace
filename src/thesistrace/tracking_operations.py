import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from thesistrace.objects import canonical_json_bytes
from thesistrace.tracking import (
    DailyTrackingError,
    DailyTrackingService,
    EquivalenceError,
)


class TrackingOperationError(RuntimeError):
    pass


class TrackingOperationResourceExhaustion(MemoryError):
    pass


MAX_EQUIVALENCE_CHECKPOINTS = 252
MAX_GENERATION_REBUILD_SESSIONS = 5_040


class TrackingOperationService:
    def __init__(
        self,
        metadata,
        tracking: DailyTrackingService,
    ) -> None:
        self.metadata = metadata
        self.tracking = tracking

    def request_equivalence(
        self,
        track_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        now = datetime.now(UTC).isoformat()
        request_id = f"equivalence_{uuid4().hex[:20]}"
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.metadata._lock_idempotent_admission(
                connection,
                operation="tracking_equivalence",
                idempotency_key=idempotency_key,
            )
            existing = connection.execute(
                """
                SELECT *
                FROM tracking_equivalence_requests
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return public_equivalence_request(dict(existing)), False
            track = connection.execute(
                """
                SELECT id, status, current_generation_id,
                       head_checkpoint_id
                FROM daily_tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()
            if (
                track is None
                or track["status"] != "active"
                or track["current_generation_id"] is None
                or track["head_checkpoint_id"] is None
            ):
                raise KeyError(track_id)
            self.metadata._admit_user_compute(
                connection,
                resource_kind="tracking_equivalence",
                resource_id=request_id,
                admitted_at=now,
            )
            connection.execute(
                """
                INSERT INTO tracking_equivalence_requests (
                    id, daily_track_id, generation_id,
                    head_checkpoint_id, idempotency_key,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    request_id,
                    track_id,
                    track["current_generation_id"],
                    track["head_checkpoint_id"],
                    idempotency_key,
                    now,
                    now,
                ),
            )
            self.metadata._enqueue_tracking_operation(
                connection,
                resource_kind="tracking_equivalence",
                resource_id=request_id,
                created_at=now,
            )
        request = self.equivalence_request(request_id)
        if request is None:
            raise TrackingOperationError("Equivalence request disappeared")
        return request, True

    def equivalence_request(
        self,
        request_id: str,
    ) -> dict[str, object] | None:
        with self.metadata.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM tracking_equivalence_requests
                WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
        return (
            None
            if row is None
            else public_equivalence_request(dict(row))
        )

    def execute_equivalence(
        self,
        request_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        request = self._claim_equivalence(request_id)
        if request["status"] in {"succeeded", "failed", "cancelled"}:
            return public_equivalence_request(request)
        report_progress(progress, "claimed")
        track_id = str(request["daily_track_id"])
        track = self.tracking.get_track(track_id)
        if track is None:
            raise KeyError(track_id)
        if (
            self._checkpoint_chain_length(
                track,
                str(request["head_checkpoint_id"]),
            )
            > MAX_EQUIVALENCE_CHECKPOINTS
        ):
            return self.fail_equivalence(
                request_id,
                "EQUIVALENCE_CHECKPOINT_LIMIT",
            )
        try:
            result = self.tracking.verify_equivalence(
                track_id,
                checkpoint_id=str(request["head_checkpoint_id"]),
                progress=progress,
            )
            compact = compact_equivalence_result(result)
        except EquivalenceError as error:
            compact = {
                "outcome": "first_divergence",
                "path": equivalence_divergence_path(str(error)),
            }
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE tracking_equivalence_requests
                SET status = 'succeeded', result_json = ?,
                    diagnostic_json = NULL, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    canonical_json_bytes(compact).decode(),
                    now,
                    request_id,
                ),
            )
            if updated.rowcount != 1:
                current = self.equivalence_request(request_id)
                if current is not None and current["status"] == "succeeded":
                    return current
                raise TrackingOperationError(
                    "Equivalence publication was fenced"
                )
            self.metadata._complete_user_compute(
                connection,
                resource_kind="tracking_equivalence",
                resource_id=request_id,
                completed_at=now,
            )
        completed = self.equivalence_request(request_id)
        if completed is None:
            raise TrackingOperationError("Equivalence request disappeared")
        return completed

    def cancel_equivalence(
        self,
        request_id: str,
        *,
        enqueue_workflow_cancellation: bool = False,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = canonical_json_bytes(
            {"reason_code": "CANCELLED"}
        ).decode()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE tracking_equivalence_requests
                SET status = 'cancelled', result_json = NULL,
                    diagnostic_json = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (diagnostic, now, request_id),
            )
            current = connection.execute(
                """
                SELECT id
                FROM tracking_equivalence_requests
                WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
            if current is None:
                raise KeyError(request_id)
            if updated.rowcount == 1:
                self.metadata._complete_user_compute(
                    connection,
                    resource_kind="tracking_equivalence",
                    resource_id=request_id,
                    completed_at=now,
                )
            if (
                enqueue_workflow_cancellation
                and updated.rowcount == 1
            ):
                self.metadata._enqueue_tracking_operation(
                    connection,
                    resource_kind="tracking_equivalence_cancel",
                    resource_id=request_id,
                    created_at=now,
                )
        cancelled = self.equivalence_request(request_id)
        if cancelled is None:
            raise KeyError(request_id)
        return cancelled

    def fail_equivalence(
        self,
        request_id: str,
        reason_code: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = canonical_json_bytes(
            {"reason_code": reason_code}
        ).decode()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE tracking_equivalence_requests
                SET status = 'failed', diagnostic_json = ?,
                    updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (diagnostic, now, request_id),
            )
            self.metadata._complete_user_compute(
                connection,
                resource_kind="tracking_equivalence",
                resource_id=request_id,
                completed_at=now,
            )
        failed = self.equivalence_request(request_id)
        if failed is None:
            raise KeyError(request_id)
        return failed

    def request_generation_rebuild(
        self,
        track_id: str,
        *,
        calculation_kernel: str,
        numeric_execution_contract: str,
        idempotency_key: str,
        operator_authorized: bool,
    ) -> tuple[dict[str, object], bool]:
        if not operator_authorized:
            raise PermissionError("Generation rebuild is Operator-only")
        now = datetime.now(UTC).isoformat()
        rebuild_id = f"rebuild_{uuid4().hex[:20]}"
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.metadata._lock_idempotent_admission(
                connection,
                operation="tracking_generation_rebuild",
                idempotency_key=idempotency_key,
            )
            existing = connection.execute(
                """
                SELECT *
                FROM tracking_generation_rebuilds
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return public_generation_rebuild(dict(existing)), False
            track = connection.execute(
                """
                SELECT id, status, current_generation_id,
                       head_checkpoint_id
                FROM daily_tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()
            if (
                track is None
                or track["status"] != "active"
                or track["current_generation_id"] is None
                or track["head_checkpoint_id"] is None
            ):
                raise KeyError(track_id)
            connection.execute(
                """
                INSERT INTO tracking_generation_rebuilds (
                    id, daily_track_id, calculation_kernel,
                    numeric_execution_contract, basis_generation_id,
                    basis_head_checkpoint_id, idempotency_key, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    rebuild_id,
                    track_id,
                    calculation_kernel,
                    numeric_execution_contract,
                    track["current_generation_id"],
                    track["head_checkpoint_id"],
                    idempotency_key,
                    now,
                    now,
                ),
            )
            self.metadata._enqueue_tracking_operation(
                connection,
                resource_kind="tracking_generation_rebuild",
                resource_id=rebuild_id,
                created_at=now,
            )
        rebuild = self.generation_rebuild(rebuild_id)
        if rebuild is None:
            raise TrackingOperationError("Generation rebuild disappeared")
        return rebuild, True

    def generation_rebuild(
        self,
        rebuild_id: str,
    ) -> dict[str, object] | None:
        with self.metadata.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM tracking_generation_rebuilds
                WHERE id = ?
                """,
                (rebuild_id,),
            ).fetchone()
        return (
            None
            if row is None
            else public_generation_rebuild(dict(row))
        )

    def execute_generation_rebuild(
        self,
        rebuild_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        rebuild = self._claim_generation_rebuild(rebuild_id)
        if rebuild["status"] in {"succeeded", "failed", "cancelled"}:
            return public_generation_rebuild(rebuild)
        report_progress(progress, "claimed")
        current = self.tracking.get_track(
            str(rebuild["daily_track_id"])
        )
        if (
            current is None
            or current["status"] != "active"
            or current["current_generation_id"]
            != rebuild["basis_generation_id"]
            or current["head_checkpoint_id"]
            != rebuild["basis_head_checkpoint_id"]
        ):
            raise TrackingOperationError(
                "Generation rebuild basis changed before execution"
            )
        head = current.get("head")
        if not isinstance(head, dict):
            raise TrackingOperationError(
                "Generation rebuild Head is missing"
            )
        release = self.metadata.dataset_release(
            str(head["target_dataset_release_id"])
        )
        if (
            release is None
            or int(release["session_count"])
            > MAX_GENERATION_REBUILD_SESSIONS
        ):
            return self.fail_generation_rebuild(
                rebuild_id,
                "GENERATION_REBUILD_SESSION_LIMIT",
            )
        track = self.tracking.upgrade_kernel(
            str(rebuild["daily_track_id"]),
            calculation_kernel=str(rebuild["calculation_kernel"]),
            numeric_execution_contract=str(
                rebuild["numeric_execution_contract"]
            ),
            enqueue_execution=False,
            generation_rebuild_id=rebuild_id,
        )
        del track
        report_progress(progress, "generation-prepared")
        bound = self.generation_rebuild(rebuild_id)
        if (
            bound is None
            or bound.get("generation_id") is None
            or bound.get("advance_id") is None
        ):
            raise TrackingOperationError(
                "Generation rebuild binding is missing"
            )
        generation_id = str(bound["generation_id"])
        advance_id = str(bound["advance_id"])
        completed = self.tracking.execute_advance(
            advance_id,
            progress=progress,
        )
        if completed["status"] != "succeeded":
            reason_code = latest_advance_reason_code(completed)
            if reason_code == "RESOURCE_EXHAUSTED":
                raise TrackingOperationResourceExhaustion(
                    "Generation rebuild exhausted Worker resources"
                )
            raise TrackingOperationError(
                "Generation rebuild Advance did not succeed"
            )
        report_progress(progress, "before-publication")
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute(
                """
                UPDATE tracking_generation_rebuilds
                SET status = 'succeeded', generation_id = ?,
                    advance_id = ?, diagnostic_json = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    generation_id,
                    advance_id,
                    now,
                    rebuild_id,
                ),
            )
        completed_rebuild = self.generation_rebuild(rebuild_id)
        if completed_rebuild is None:
            raise TrackingOperationError("Generation rebuild disappeared")
        return completed_rebuild

    def cancel_generation_rebuild(
        self,
        rebuild_id: str,
        *,
        enqueue_workflow_cancellation: bool = False,
    ) -> dict[str, object]:
        return self._terminate_generation_rebuild(
            rebuild_id,
            terminal_status="cancelled",
            reason_code="CANCELLED",
            enqueue_workflow_cancellation=(
                enqueue_workflow_cancellation
            ),
        )

    def fail_generation_rebuild(
        self,
        rebuild_id: str,
        reason_code: str,
    ) -> dict[str, object]:
        return self._terminate_generation_rebuild(
            rebuild_id,
            terminal_status="failed",
            reason_code=reason_code,
        )

    def _terminate_generation_rebuild(
        self,
        rebuild_id: str,
        *,
        terminal_status: str,
        reason_code: str,
        enqueue_workflow_cancellation: bool = False,
    ) -> dict[str, object]:
        if terminal_status not in {"failed", "cancelled"}:
            raise ValueError("unsupported rebuild terminal status")
        now = datetime.now(UTC).isoformat()
        cache_fence: tuple[str, int] | None = None
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rebuild = connection.execute(
                """
                SELECT daily_track_id, generation_id, advance_id, status
                FROM tracking_generation_rebuilds
                WHERE id = ?
                """,
                (rebuild_id,),
            ).fetchone()
            if rebuild is None:
                raise KeyError(rebuild_id)
            if rebuild["status"] in {
                "succeeded",
                "failed",
                "cancelled",
            }:
                current = self.generation_rebuild(rebuild_id)
                if current is None:
                    raise KeyError(rebuild_id)
                return current
            generation_id = rebuild["generation_id"]
            advance_id = rebuild["advance_id"]
            self.metadata.lock_daily_track(
                connection,
                str(rebuild["daily_track_id"]),
            )
            track = connection.execute(
                """
                SELECT current_generation_id, fencing_token
                FROM daily_tracks
                WHERE id = ?
                """,
                (rebuild["daily_track_id"],),
            ).fetchone()
            advance = (
                connection.execute(
                    """
                    SELECT status
                    FROM tracking_advances
                    WHERE id = ?
                    """,
                    (advance_id,),
                ).fetchone()
                if advance_id is not None
                else None
            )
            if (
                generation_id is not None
                and track is not None
                and track["current_generation_id"] == generation_id
                and advance is not None
                and advance["status"] == "succeeded"
            ):
                connection.execute(
                    """
                    UPDATE tracking_generation_rebuilds
                    SET status = 'succeeded', diagnostic_json = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, rebuild_id),
                )
                connection.commit()
                recovered = self.generation_rebuild(rebuild_id)
                if recovered is None:
                    raise KeyError(rebuild_id)
                return recovered
            if (
                track is not None
                and (
                    generation_id is not None
                    or advance_id is not None
                )
            ):
                next_fencing_token = int(track["fencing_token"]) + 1
                connection.execute(
                    """
                    UPDATE daily_tracks
                    SET fencing_token = ?
                    WHERE id = ? AND fencing_token = ?
                    """,
                    (
                        next_fencing_token,
                        rebuild["daily_track_id"],
                        track["fencing_token"],
                    ),
                )
                cache_fence = (
                    str(rebuild["daily_track_id"]),
                    next_fencing_token,
                )
            connection.execute(
                """
                UPDATE tracking_generation_rebuilds
                SET generation_id = NULL, advance_id = NULL
                WHERE id = ? AND status = 'running'
                """,
                (rebuild_id,),
            )
            if advance_id is not None:
                connection.execute(
                    """
                    DELETE FROM tracking_advance_attempts
                    WHERE advance_id = ?
                    """,
                    (advance_id,),
                )
                connection.execute(
                    """
                    DELETE FROM tracking_advances
                    WHERE id = ? AND status <> 'succeeded'
                    """,
                    (advance_id,),
                )
            if generation_id is not None:
                connection.execute(
                    """
                    DELETE FROM tracking_generations
                    WHERE id = ?
                      AND id <> COALESCE(
                          (
                              SELECT current_generation_id
                              FROM daily_tracks
                              WHERE id = ?
                          ),
                          ''
                      )
                    """,
                    (generation_id, rebuild["daily_track_id"]),
                )
            connection.execute(
                """
                UPDATE tracking_generation_rebuilds
                SET status = ?, generation_id = NULL,
                    advance_id = NULL, diagnostic_json = ?,
                    updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (
                    terminal_status,
                    canonical_json_bytes(
                        {"reason_code": reason_code}
                    ).decode(),
                    now,
                    rebuild_id,
                ),
            )
            if enqueue_workflow_cancellation:
                self.metadata._enqueue_tracking_operation(
                    connection,
                    resource_kind=(
                        "tracking_generation_rebuild_cancel"
                    ),
                    resource_id=rebuild_id,
                    created_at=now,
                )
        if cache_fence is not None:
            self.tracking.cache.advance_fence(
                cache_fence[0],
                cache_fence[1],
                stopped=False,
            )
        terminated = self.generation_rebuild(rebuild_id)
        if terminated is None:
            raise KeyError(rebuild_id)
        return terminated

    def _claim_equivalence(
        self,
        request_id: str,
    ) -> dict[str, object]:
        return self._claim_operation(
            "tracking_equivalence_requests",
            request_id,
        )

    def _checkpoint_chain_length(
        self,
        track: dict[str, object],
        head_checkpoint_id: str,
    ) -> int:
        checkpoints = {
            str(item["id"]): item
            for item in track["checkpoints"]
            if isinstance(item, dict)
        }
        cursor: str | None = head_checkpoint_id
        count = 0
        while cursor is not None:
            checkpoint = checkpoints.get(cursor)
            if checkpoint is None:
                raise TrackingOperationError(
                    "Equivalence Checkpoint chain is incomplete"
                )
            count += 1
            if count > MAX_EQUIVALENCE_CHECKPOINTS:
                return count
            manifest = self.tracking._checkpoint_manifest(
                str(checkpoint["manifest_sha256"])
            )
            predecessor = manifest.get("predecessor_checkpoint_id")
            cursor = (
                str(predecessor)
                if predecessor is not None
                else None
            )
        return count

    def _claim_generation_rebuild(
        self,
        rebuild_id: str,
    ) -> dict[str, object]:
        return self._claim_operation(
            "tracking_generation_rebuilds",
            rebuild_id,
        )

    def _claim_operation(
        self,
        table: str,
        operation_id: str,
    ) -> dict[str, object]:
        if table not in {
            "tracking_equivalence_requests",
            "tracking_generation_rebuilds",
        }:
            raise ValueError("unsupported Tracking operation table")
        now = datetime.now(UTC).isoformat()
        with self.metadata.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            if row["status"] in {
                "succeeded",
                "failed",
                "cancelled",
            }:
                return dict(row)
            connection.execute(
                f"""
                UPDATE {table}
                SET status = 'running', updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (now, operation_id),
            )
            claimed = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?",
                (operation_id,),
            ).fetchone()
        if claimed is None:
            raise KeyError(operation_id)
        return dict(claimed)


def compact_equivalence_result(
    result: dict[str, object],
) -> dict[str, object]:
    release_sequence = result.get("release_sequence")
    trace_checksums = result.get("trace_checksums")
    if not isinstance(release_sequence, list) or not isinstance(
        trace_checksums,
        list,
    ):
        raise DailyTrackingError("Equivalence result is incomplete")
    return {
        "outcome": "equivalent",
        "daily_track_id": result["daily_track_id"],
        "generation_id": result["generation_id"],
        "target_dataset_release_id": result[
            "target_dataset_release_id"
        ],
        "checkpoint_id": result["checkpoint_id"],
        "release_count": len(release_sequence),
        "trace_chain_sha256": hashlib.sha256(
            canonical_json_bytes(trace_checksums)
        ).hexdigest(),
    }


def equivalence_divergence_path(message: str) -> str:
    marker = " at "
    return message.split(marker, 1)[1] if marker in message else "$"


def public_equivalence_request(
    row: dict[str, object],
) -> dict[str, object]:
    return public_tracking_operation(
        row,
        result_key="result_json",
        exposed=(
            "id",
            "daily_track_id",
            "generation_id",
            "head_checkpoint_id",
            "status",
            "created_at",
            "updated_at",
        ),
    )


def public_generation_rebuild(
    row: dict[str, object],
) -> dict[str, object]:
    return public_tracking_operation(
        row,
        result_key=None,
        exposed=(
            "id",
            "daily_track_id",
            "calculation_kernel",
            "numeric_execution_contract",
            "basis_generation_id",
            "basis_head_checkpoint_id",
            "status",
            "generation_id",
            "advance_id",
            "created_at",
            "updated_at",
        ),
    )


def public_tracking_operation(
    row: dict[str, object],
    *,
    result_key: str | None,
    exposed: tuple[str, ...],
) -> dict[str, object]:
    result = {
        key: row[key]
        for key in exposed
        if key in row
    }
    if result_key is not None and row.get(result_key):
        result["result"] = json.loads(str(row[result_key]))
    if row.get("diagnostic_json"):
        result["diagnostic"] = json.loads(
            str(row["diagnostic_json"])
        )
    return result


def latest_advance_reason_code(
    advance: dict[str, object],
) -> str | None:
    attempts = advance.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return None
    latest = attempts[-1]
    if not isinstance(latest, dict):
        return None
    diagnostic = latest.get("diagnostic")
    return (
        str(diagnostic.get("reason_code"))
        if isinstance(diagnostic, dict)
        and diagnostic.get("reason_code") is not None
        else None
    )


def report_progress(
    progress: Callable[[str], None] | None,
    stage: str,
) -> None:
    if progress is not None:
        progress(stage)

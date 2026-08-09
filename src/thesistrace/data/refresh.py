from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from psycopg.errors import UniqueViolation

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
from thesistrace.data.head_store import DatasetHead, DatasetHeadConflict, MountedDatasetHeadStore
from thesistrace.data.lifecycle import DatasetLifecycle, lock_data_lifecycle
from thesistrace.data.source import DataSource, DataSourceError, refresh_collection_plan
from thesistrace.data.validation import validate_release_batch
from thesistrace.publication.serialization import canonical_json_bytes


class DataRefreshError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RefreshOutcome:
    idempotency_key: str
    status: str
    outcome: str | None
    data_through_session: str | None
    last_refresh_at: str | None
    failure_code: str | None


class DataRefreshService:
    """Private asynchronous Refresh lifecycle over the mounted current Dataset."""

    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database = database
        self._mount_root = Path(mount_root)
        self._clock = clock
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._heads = MountedDatasetHeadStore(mount_root)
        self._generations = MountedGenerationStore(mount_root)

    def submit(self, *, idempotency_key: str, as_of: datetime) -> RefreshOutcome:
        key = _identity(idempotency_key)
        if as_of.tzinfo is None:
            raise DataRefreshError("INVALID_AS_OF")
        normalized_as_of = as_of.astimezone(UTC)
        fingerprint = hashlib.sha256(
            canonical_json_bytes(
                {
                    "command": "data-operator/refresh/v1",
                    "as_of": normalized_as_of.isoformat(),
                }
            )
        ).hexdigest()
        with self._database.transaction() as transaction:
            existing = transaction.execute(
                "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                (key,),
            ).fetchone()
        if existing is not None:
            if existing["fingerprint"] != fingerprint:
                raise DataRefreshError("IDEMPOTENCY_KEY_CONFLICT")
            return _outcome(existing)
        if self._lifecycle.current_head() is None:
            raise DataRefreshError("DATA_NOT_READY")
        try:
            with self._database.transaction() as transaction:
                row = transaction.execute(
                    """
                    INSERT INTO data.refresh_operations (
                        idempotency_key, fingerprint, status, as_of
                    ) VALUES (%s, %s, 'accepted', %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING *
                    """,
                    (key, fingerprint, normalized_as_of),
                ).fetchone()
                if row is None:
                    row = transaction.execute(
                        """
                        SELECT * FROM data.refresh_operations
                        WHERE idempotency_key = %s
                        """,
                        (key,),
                    ).fetchone()
        except UniqueViolation as error:
            raise DataRefreshError("REFRESH_ALREADY_ACTIVE") from error
        assert row is not None
        if row["fingerprint"] != fingerprint:
            raise DataRefreshError("IDEMPOTENCY_KEY_CONFLICT")
        return _outcome(row)

    def inspect(self, idempotency_key: str) -> RefreshOutcome:
        key = _identity(idempotency_key)
        with self._database.transaction() as transaction:
            row = transaction.execute(
                "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                (key,),
            ).fetchone()
        if row is None:
            raise DataRefreshError("REFRESH_NOT_FOUND")
        return _outcome(row)

    def process_next(self, source: DataSource) -> bool:
        operation = self._claim()
        if operation is None:
            return False
        key = str(operation["idempotency_key"])
        candidate_manifest: str | None = None
        candidate_live = False
        try:
            head = self._lifecycle.current_head()
            if head is None:
                raise DataRefreshError("DATA_NOT_READY")
            expected_manifest = head.generation_manifest_sha256
            plan = refresh_collection_plan(operation["as_of"], head.generation.canonical)
            batch = source.collect(plan)
            validate_release_batch(batch, predecessor_session=head.data_through_session)
            candidate_canonical = batch.canonical
            if canonical_json_bytes(candidate_canonical) == canonical_json_bytes(
                head.generation.canonical
            ):
                completed_at = self._operator_time()
                self._complete_no_change(
                    key,
                    expected_manifest=expected_manifest,
                    data_through_session=head.data_through_session,
                    completed_at=completed_at,
                )
                return True
            prepared_at = self._operator_time()
            generation = self._generations.materialize(
                candidate_canonical,
                prepared_at=prepared_at,
                source_name=batch.source_name,
                source_lineage=batch.source_lineage,
            )
            candidate_manifest = generation.manifest_sha256
            operation_id = f"refresh:{key}"
            self._lifecycle.protect_candidate(
                operation_id=operation_id,
                generation_manifest_sha256=candidate_manifest,
                lease_seconds=900,
            )
            candidate_live = True
            moved = self._lifecycle.compare_and_swap_head(
                expected_generation_manifest_sha256=expected_manifest,
                candidate_generation_manifest_sha256=candidate_manifest,
                operation_id=operation_id,
                prepared_at=prepared_at,
            )
            candidate_live = False
            completed_at = self._operator_time()
            self._complete_published(key, moved, completed_at)
        except DataRefreshError as error:
            self._fail(key, error.code)
            raise
        except DataSourceError as error:
            code = f"SOURCE_{error.category.upper()}"
            self._fail(key, code)
            raise DataRefreshError(code) from error
        except DatasetHeadConflict as error:
            self._fail(key, "HEAD_CHANGED")
            raise DataRefreshError("HEAD_CHANGED") from error
        except (GenerationStoreError, ValueError) as error:
            self._fail(key, "INVALID_CANONICAL_DATA")
            raise DataRefreshError("INVALID_CANONICAL_DATA") from error
        except (OSError, RuntimeError) as error:
            self._fail(key, "REFRESH_INFRASTRUCTURE_FAILURE")
            raise DataRefreshError("REFRESH_INFRASTRUCTURE_FAILURE") from error
        finally:
            if candidate_live:
                self._lifecycle.release_candidate(operation_id=f"refresh:{key}")
        return True

    def _claim(self) -> dict[str, object] | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT * FROM data.refresh_operations
                WHERE status = 'accepted'
                ORDER BY created_at, idempotency_key
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            transaction.execute(
                """
                UPDATE data.refresh_operations
                SET status = 'running', started_at = now(), updated_at = now()
                WHERE idempotency_key = %s AND status = 'accepted'
                """,
                (row["idempotency_key"],),
            )
            return {**row, "status": "running"}

    def _complete_no_change(
        self,
        key: str,
        *,
        expected_manifest: str,
        data_through_session: str,
        completed_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            pointer = self._heads.current_pointer()
            if pointer is None or pointer.generation_manifest_sha256 != expected_manifest:
                raise DataRefreshError("HEAD_CHANGED")
            _complete_operation(
                transaction,
                key,
                outcome="no_change",
                generation_manifest_sha256=expected_manifest,
                data_through_session=data_through_session,
                completed_at=completed_at,
            )

    def _complete_published(self, key: str, head: DatasetHead, completed_at: datetime) -> None:
        with self._database.transaction() as transaction:
            _complete_operation(
                transaction,
                key,
                outcome="published",
                generation_manifest_sha256=head.generation_manifest_sha256,
                data_through_session=head.data_through_session,
                completed_at=completed_at,
            )

    def _fail(self, key: str, code: str) -> None:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.refresh_operations
                SET status = 'failed', failure_code = %s,
                    finished_at = now(), updated_at = now()
                WHERE idempotency_key = %s AND status IN ('accepted', 'running')
                """,
                (code, key),
            )

    def _operator_time(self) -> datetime:
        selected = self._clock()
        if selected.tzinfo is None:
            raise DataRefreshError("INVALID_PREPARATION_TIME")
        return selected.astimezone(UTC)


def _complete_operation(
    transaction: PostgresTransaction,
    key: str,
    *,
    outcome: str,
    generation_manifest_sha256: str,
    data_through_session: str,
    completed_at: datetime,
) -> None:
    updated = transaction.execute(
        """
        UPDATE data.refresh_operations
        SET status = 'succeeded', outcome = %s,
            generation_manifest_sha256 = %s, data_through_session = %s,
            last_refresh_at = %s, failure_code = NULL,
            finished_at = now(), updated_at = now()
        WHERE idempotency_key = %s AND status = 'running'
        """,
        (
            outcome,
            generation_manifest_sha256,
            data_through_session,
            completed_at,
            key,
        ),
    )
    if updated.rowcount != 1:
        raise DataRefreshError("REFRESH_OWNERSHIP_LOST")
    transaction.execute(
        """
        UPDATE data.current_dataset_state
        SET last_refresh_at = %s
        WHERE singleton = 1
        """,
        (completed_at,),
    )


def _identity(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DataRefreshError("INVALID_IDEMPOTENCY_KEY")
    return normalized


def _outcome(row: dict[str, object]) -> RefreshOutcome:
    return RefreshOutcome(
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        outcome=None if row["outcome"] is None else str(row["outcome"]),
        data_through_session=(
            None if row["data_through_session"] is None else str(row["data_through_session"])
        ),
        last_refresh_at=(
            None if row["last_refresh_at"] is None else row["last_refresh_at"].isoformat()
        ),
        failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
    )


__all__ = ("DataRefreshError", "DataRefreshService", "RefreshOutcome")

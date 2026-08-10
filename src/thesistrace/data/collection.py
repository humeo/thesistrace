from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.generation_store import (
    GenerationFileRef,
    GenerationStoreError,
    MountedGenerationStore,
)
from thesistrace.data.head_store import DatasetHeadError
from thesistrace.data.lifecycle import (
    DataLifecycleError,
    DatasetLifecycle,
    lock_data_lifecycle,
)
from thesistrace.publication.serialization import canonical_json_bytes

_COLLECTION_LOCK = "thesistrace-generation-collection"


class DataCollectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CollectionOutcome:
    status: str
    target_file_count: int
    deleted_file_count: int
    remaining_file_count: int


class DataGarbageCollector:
    """Explicit, fixed-plan collection behind the shared Data Lifecycle fence."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._database = database
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._generations = MountedGenerationStore(mount_root)

    def collect(self, *, idempotency_key: str) -> CollectionOutcome:
        key = _identity(idempotency_key)
        with self._database.session_advisory_lock(_COLLECTION_LOCK):
            try:
                self._ensure_plan(key)
                failure_code = self._execute_plan(key)
            except (DataLifecycleError, DatasetHeadError, GenerationStoreError) as error:
                raise DataCollectionError("COLLECTION_ROOTS_INVALID") from error
            if failure_code is not None:
                raise DataCollectionError(failure_code)
            return self._outcome(key)

    def _ensure_plan(self, key: str) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            existing = transaction.execute(
                """
                SELECT status
                FROM data.collection_operations
                WHERE idempotency_key = %s
                FOR UPDATE
                """,
                (key,),
            ).fetchone()
            if existing is not None:
                if existing["status"] == "succeeded":
                    return
                if _data_work_is_active(transaction):
                    raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
                retained = self._retained_files(transaction)
                targets = _targets(transaction, key)
                if retained & targets:
                    raise DataCollectionError("COLLECTION_ROOT_SET_CHANGED")
                transaction.execute(
                    """
                    UPDATE data.collection_operations
                    SET status = 'running', failure_code = NULL,
                        finished_at = NULL, updated_at = now()
                    WHERE idempotency_key = %s
                    """,
                    (key,),
                )
                return
            if _data_work_is_active(transaction):
                raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
            retained = self._retained_files(transaction)
            targets = tuple(sorted(self._generations.inventory() - retained))
            plan_sha256 = hashlib.sha256(
                canonical_json_bytes(
                    [{"kind": target.kind, "sha256": target.sha256} for target in targets]
                )
            ).hexdigest()
            transaction.execute(
                """
                INSERT INTO data.collection_operations (
                    idempotency_key, plan_sha256, status, target_count
                ) VALUES (%s, %s, 'running', %s)
                """,
                (key, plan_sha256, len(targets)),
            )
            with transaction.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO data.collection_targets (
                        idempotency_key, ordinal, file_kind, sha256, status
                    ) VALUES (%s, %s, %s, %s, 'pending')
                    """,
                    [
                        (key, ordinal, target.kind, target.sha256)
                        for ordinal, target in enumerate(targets)
                    ],
                )

    def _execute_plan(self, key: str) -> str | None:
        while True:
            reference = self._claim_target(key)
            if reference is None:
                self._succeed(key)
                return None
            try:
                self._generations.delete_file(reference)
            except GenerationStoreError:
                self._fail(key, "COLLECTION_FILESYSTEM_FAILURE")
                return "COLLECTION_FILESYSTEM_FAILURE"
            self._complete_target(key, reference)

    def _claim_target(self, key: str) -> GenerationFileRef | None:
        failure_code: str | None = None
        reference: GenerationFileRef | None = None
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            operation = transaction.execute(
                """
                SELECT status
                FROM data.collection_operations
                WHERE idempotency_key = %s
                FOR UPDATE
                """,
                (key,),
            ).fetchone()
            if operation is None:
                raise RuntimeError("Collection operation disappeared")
            if operation["status"] == "succeeded":
                return None
            if operation["status"] != "running":
                raise RuntimeError("Collection operation is not running")
            row = transaction.execute(
                """
                SELECT ordinal, file_kind, sha256
                FROM data.collection_targets
                WHERE idempotency_key = %s AND status IN ('pending', 'deleting')
                ORDER BY ordinal
                LIMIT 1
                FOR UPDATE
                """,
                (key,),
            ).fetchone()
            if row is None:
                return None
            reference = GenerationFileRef(str(row["file_kind"]), str(row["sha256"]))
            if reference in self._retained_files(transaction):
                failure_code = "COLLECTION_ROOT_SET_CHANGED"
                _fail_operation(transaction, key, failure_code)
            else:
                transaction.execute(
                    """
                    UPDATE data.collection_targets
                    SET status = 'deleting'
                    WHERE idempotency_key = %s AND ordinal = %s
                    """,
                    (key, row["ordinal"]),
                )
        if failure_code is not None:
            raise DataCollectionError(failure_code)
        return reference

    def _complete_target(self, key: str, reference: GenerationFileRef) -> None:
        with self._database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE data.collection_targets
                SET status = 'deleted', deleted_at = now()
                WHERE idempotency_key = %s AND file_kind = %s AND sha256 = %s
                  AND status = 'deleting'
                """,
                (key, reference.kind, reference.sha256),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Collection target progress is inconsistent")
            transaction.execute(
                """
                UPDATE data.collection_operations
                SET deleted_count = deleted_count + 1, updated_at = now()
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (key,),
            )

    def _succeed(self, key: str) -> None:
        with self._database.transaction() as transaction:
            pending = transaction.execute(
                """
                SELECT count(*) AS count
                FROM data.collection_targets
                WHERE idempotency_key = %s AND status <> 'deleted'
                """,
                (key,),
            ).fetchone()
            if pending is None or int(pending["count"]) != 0:
                raise RuntimeError("Collection completed with pending targets")
            transaction.execute(
                """
                UPDATE data.collection_operations
                SET status = 'succeeded', failure_code = NULL,
                    finished_at = now(), updated_at = now()
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (key,),
            )

    def _fail(self, key: str, failure_code: str) -> None:
        with self._database.transaction() as transaction:
            _fail_operation(transaction, key, failure_code)

    def _retained_files(
        self,
        transaction: PostgresTransaction,
    ) -> frozenset[GenerationFileRef]:
        retained: set[GenerationFileRef] = set()
        for manifest_sha256 in self._lifecycle.retention_roots_in_transaction(transaction):
            retained.update(self._generations.referenced_files(manifest_sha256))
        return frozenset(retained)

    def _outcome(self, key: str) -> CollectionOutcome:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, target_count, deleted_count
                FROM data.collection_operations
                WHERE idempotency_key = %s
                """,
                (key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Collection operation disappeared")
        target_count = int(row["target_count"])
        deleted_count = int(row["deleted_count"])
        return CollectionOutcome(
            status=str(row["status"]),
            target_file_count=target_count,
            deleted_file_count=deleted_count,
            remaining_file_count=target_count - deleted_count,
        )


def _fail_operation(
    transaction: PostgresTransaction,
    key: str,
    failure_code: str,
) -> None:
    transaction.execute(
        """
        UPDATE data.collection_operations
        SET status = 'failed', failure_code = %s,
            finished_at = now(), updated_at = now()
        WHERE idempotency_key = %s
        """,
        (failure_code, key),
    )


def _data_work_is_active(transaction: PostgresTransaction) -> bool:
    row = transaction.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM data.bootstrap_operations WHERE status = 'running'
            UNION ALL
            SELECT 1 FROM data.refresh_operations WHERE status = 'running'
        ) AS active
        """
    ).fetchone()
    return bool(row and row["active"])


def _targets(
    transaction: PostgresTransaction,
    key: str,
) -> frozenset[GenerationFileRef]:
    rows = transaction.execute(
        """
        SELECT file_kind, sha256
        FROM data.collection_targets
        WHERE idempotency_key = %s
        """,
        (key,),
    ).fetchall()
    return frozenset(GenerationFileRef(str(row["file_kind"]), str(row["sha256"])) for row in rows)


def _identity(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized != value:
        raise DataCollectionError("INVALID_IDEMPOTENCY_KEY")
    return normalized


__all__ = (
    "CollectionOutcome",
    "DataCollectionError",
    "DataGarbageCollector",
)

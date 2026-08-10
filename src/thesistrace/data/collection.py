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
    try_exclusive_mounted_data_mutation_lock,
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
        with try_exclusive_mounted_data_mutation_lock(self._database) as acquired:
            if not acquired:
                raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
            return self._collect(key)

    def _collect(self, key: str) -> CollectionOutcome:
        with self._database.session_advisory_lock(_COLLECTION_LOCK):
            self._reconcile_abandoned()
            try:
                self._ensure_plan(key)
                failure_code = self._execute_plan(key)
            except (DataLifecycleError, DatasetHeadError, GenerationStoreError) as error:
                raise DataCollectionError("COLLECTION_ROOTS_INVALID") from error
            if failure_code is not None:
                raise DataCollectionError(failure_code)
            return self._outcome(key)

    def _ensure_plan(self, key: str) -> None:
        for _ in range(4):
            root_ids = self._snapshot_root_ids()
            retained = self._validated_retained_files(root_ids)
            inventory = self._generations.inventory()
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                if _data_work_is_active(transaction):
                    raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
                if self._lifecycle.retention_root_ids_in_transaction(transaction) != root_ids:
                    continue
                existing = transaction.execute(
                    """
                    SELECT status
                    FROM data.collection_operations
                    WHERE idempotency_key = %s
                    FOR UPDATE
                    """,
                    (key,),
                ).fetchone()
                if existing is not None and existing["status"] == "succeeded":
                    return
                if existing is None:
                    targets = tuple(sorted(inventory - retained))
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
                else:
                    if retained & _targets(transaction, key):
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
                _replace_roots(transaction, key, root_ids)
                return
        raise DataCollectionError("COLLECTION_ROOTS_CHANGED")

    def _reconcile_abandoned(self) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            transaction.execute(
                """
                UPDATE data.collection_operations
                SET status = 'failed', failure_code = 'COLLECTION_ABANDONED',
                    finished_at = now(), updated_at = now()
                WHERE status = 'running'
                """
            )

    def _snapshot_root_ids(self) -> tuple[str, ...]:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            if _data_work_is_active(transaction):
                raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
            return self._lifecycle.retention_root_ids_in_transaction(transaction)

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
            current_roots = set(self._lifecycle.retention_root_ids_in_transaction(transaction))
            planned_roots = _planned_roots(transaction, key)
            if not current_roots.issubset(planned_roots):
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

    def _validated_retained_files(
        self,
        root_ids: tuple[str, ...],
    ) -> frozenset[GenerationFileRef]:
        retained: set[GenerationFileRef] = set()
        for manifest_sha256 in root_ids:
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


def _replace_roots(
    transaction: PostgresTransaction,
    key: str,
    root_ids: tuple[str, ...],
) -> None:
    transaction.execute(
        "DELETE FROM data.collection_roots WHERE idempotency_key = %s",
        (key,),
    )
    with transaction.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO data.collection_roots (
                idempotency_key, generation_manifest_sha256
            ) VALUES (%s, %s)
            """,
            [(key, root_id) for root_id in root_ids],
        )


def _planned_roots(
    transaction: PostgresTransaction,
    key: str,
) -> set[str]:
    return {
        str(row["generation_manifest_sha256"])
        for row in transaction.execute(
            """
            SELECT generation_manifest_sha256
            FROM data.collection_roots
            WHERE idempotency_key = %s
            """,
            (key,),
        ).fetchall()
    }


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

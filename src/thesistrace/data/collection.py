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
                return
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
        failure_code: str | None = None
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
            retained = self._retained_files(transaction)
            rows = transaction.execute(
                """
                SELECT ordinal, file_kind, sha256, status
                FROM data.collection_targets
                WHERE idempotency_key = %s
                ORDER BY ordinal
                FOR UPDATE
                """,
                (key,),
            ).fetchall()
            targets = {GenerationFileRef(str(row["file_kind"]), str(row["sha256"])) for row in rows}
            if retained & targets:
                failure_code = "COLLECTION_ROOT_SET_CHANGED"
                _fail_operation(transaction, key, failure_code)
            else:
                transaction.execute(
                    """
                    UPDATE data.collection_operations
                    SET status = 'running', failure_code = NULL,
                        finished_at = NULL, updated_at = now()
                    WHERE idempotency_key = %s
                    """,
                    (key,),
                )
                for row in rows:
                    if row["status"] == "deleted":
                        continue
                    reference = GenerationFileRef(
                        str(row["file_kind"]),
                        str(row["sha256"]),
                    )
                    try:
                        self._generations.delete_file(reference)
                    except (OSError, RuntimeError):
                        failure_code = "COLLECTION_FILESYSTEM_FAILURE"
                        _fail_operation(transaction, key, failure_code)
                        break
                    transaction.execute(
                        """
                        UPDATE data.collection_targets
                        SET status = 'deleted', deleted_at = now()
                        WHERE idempotency_key = %s AND ordinal = %s
                          AND status = 'pending'
                        """,
                        (key, row["ordinal"]),
                    )
                    transaction.execute(
                        """
                        UPDATE data.collection_operations
                        SET deleted_count = deleted_count + 1, updated_at = now()
                        WHERE idempotency_key = %s
                        """,
                        (key,),
                    )
                if failure_code is None:
                    transaction.execute(
                        """
                        UPDATE data.collection_operations
                        SET status = 'succeeded', failure_code = NULL,
                            finished_at = now(), updated_at = now()
                        WHERE idempotency_key = %s
                        """,
                        (key,),
                    )
        return failure_code

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

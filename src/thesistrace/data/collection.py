from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


class DataCollectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_REFRESH_RECEIPT_RETENTION_DAYS = 180
_REFRESH_RECEIPT_CLEANUP_LIMIT = 500


@dataclass(frozen=True)
class CollectionOutcome:
    status: str
    target_file_count: int
    deleted_file_count: int
    remaining_file_count: int
    deleted_receipt_count: int


class DataGarbageCollector:
    """Explicit, fixed-plan collection behind the shared Data Lifecycle fence."""

    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        receipt_cleanup_limit: int = _REFRESH_RECEIPT_CLEANUP_LIMIT,
    ) -> None:
        if (
            not isinstance(receipt_cleanup_limit, int)
            or isinstance(receipt_cleanup_limit, bool)
            or receipt_cleanup_limit <= 0
        ):
            raise ValueError("Receipt cleanup limit must be a positive integer")
        self._database = database
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._generations = MountedGenerationStore(mount_root)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._receipt_cleanup_limit = receipt_cleanup_limit

    def collect(self, *, idempotency_key: str) -> CollectionOutcome:
        key = _identity(idempotency_key)
        with try_exclusive_mounted_data_mutation_lock(self._database) as acquired:
            if not acquired:
                raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
            return self._collect(key)

    def _collect(self, key: str) -> CollectionOutcome:
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
        receipt_cutoff: datetime | None = None
        for _ in range(4):
            root_ids, financial_outputs = self._snapshot_retention()
            retained = self._validated_retained_files(root_ids, financial_outputs)
            inventory = self._generations.inventory()
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                if _data_work_is_active(transaction):
                    raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
                if _retention_snapshot(self._lifecycle, transaction) != (
                    root_ids,
                    financial_outputs,
                ):
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
                    if receipt_cutoff is None:
                        receipt_cutoff = self._validated_clock() - timedelta(
                            days=_REFRESH_RECEIPT_RETENTION_DAYS
                        )
                    targets = tuple(sorted(inventory - retained))
                    receipt_rows = transaction.execute(
                        """
                        SELECT idempotency_key
                        FROM data.refresh_operations
                        WHERE status IN ('succeeded', 'failed', 'cancelled')
                          AND finished_at < %s
                        ORDER BY finished_at, idempotency_key
                        LIMIT %s
                        FOR UPDATE
                        """,
                        (receipt_cutoff, self._receipt_cleanup_limit),
                    ).fetchall()
                    receipt_keys = tuple(str(row["idempotency_key"]) for row in receipt_rows)
                    plan_sha256 = hashlib.sha256(
                        canonical_json_bytes(
                            {
                                "files": [
                                    {"kind": target.kind, "sha256": target.sha256}
                                    for target in targets
                                ],
                                "refresh_receipts": receipt_keys,
                            }
                        )
                    ).hexdigest()
                    transaction.execute(
                        """
                        INSERT INTO data.collection_operations (
                            idempotency_key, plan_sha256, status, target_count,
                            deleted_receipt_count
                        ) VALUES (%s, %s, 'running', %s, %s)
                        """,
                        (key, plan_sha256, len(targets), len(receipt_keys)),
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
                    if receipt_keys:
                        deleted = transaction.execute(
                            """
                            DELETE FROM data.refresh_operations
                            WHERE idempotency_key = ANY(%s::text[])
                            """,
                            (list(receipt_keys),),
                        )
                        if deleted.rowcount != len(receipt_keys):
                            raise RuntimeError("Refresh receipt cleanup plan is inconsistent")
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

    def _snapshot_retention(
        self,
    ) -> tuple[tuple[str, ...], tuple[GenerationFileRef, ...]]:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            if _data_work_is_active(transaction):
                raise DataCollectionError("COLLECTION_DATA_WORK_ACTIVE")
            return _retention_snapshot(self._lifecycle, transaction)

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
        retained_outputs: tuple[GenerationFileRef, ...],
    ) -> frozenset[GenerationFileRef]:
        retained: set[GenerationFileRef] = set()
        for manifest_sha256 in root_ids:
            self._generations.validate_generation(manifest_sha256)
            retained.update(self._generations.referenced_files(manifest_sha256))
        for output in retained_outputs:
            if output.kind == "financial_candidate":
                retained.update(
                    self._generations.financial_candidate_referenced_files(output.sha256)
                )
            elif output.kind == "raw_financial":
                self._generations.validate_raw_financial_batch(output.sha256)
                retained.add(output)
            elif output.kind == "industry_candidate":
                retained.update(
                    self._generations.industry_candidate_referenced_files(output.sha256)
                )
            elif output.kind == "raw_industry":
                self._generations.validate_raw_industry_batch(output.sha256)
                retained.add(output)
            else:
                raise DataCollectionError("COLLECTION_ROOTS_INVALID")
        return frozenset(retained)

    def _outcome(self, key: str) -> CollectionOutcome:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, target_count, deleted_count, deleted_receipt_count
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
            deleted_receipt_count=int(row["deleted_receipt_count"]),
        )

    def _validated_clock(self) -> datetime:
        selected = self._clock()
        if selected.tzinfo is None or selected.utcoffset() is None:
            raise ValueError("Receipt cleanup clock must include a timezone")
        return selected.astimezone(UTC)


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
            UNION ALL
            SELECT 1 FROM data.financial_collection_operations WHERE status = 'running'
            UNION ALL
            SELECT 1 FROM data.financial_refresh_operations WHERE status = 'running'
            UNION ALL
            SELECT 1 FROM data.financial_daily_refresh_operations WHERE status = 'running'
            UNION ALL
            SELECT 1 FROM data.industry_refresh_operations WHERE status = 'running'
        ) AS active
        """
    ).fetchone()
    return bool(row and row["active"])


def _retention_snapshot(
    lifecycle: DatasetLifecycle,
    transaction: PostgresTransaction,
) -> tuple[tuple[str, ...], tuple[GenerationFileRef, ...]]:
    roots = lifecycle.retention_root_ids_in_transaction(transaction)
    retained: set[GenerationFileRef] = set()
    candidate_rows = transaction.execute(
        """
        SELECT candidate_manifest_sha256
        FROM data.financial_refresh_operations
        WHERE status = 'succeeded' AND retention_released_at IS NULL
        """
    ).fetchall()
    retained.update(
        GenerationFileRef("financial_candidate", str(row["candidate_manifest_sha256"]))
        for row in candidate_rows
    )
    daily_candidate_rows = transaction.execute(
        """
        SELECT candidate_manifest_sha256
        FROM data.financial_daily_refresh_operations
        WHERE status IN ('succeeded', 'succeeded_with_pending', 'succeeded_with_gaps')
          AND retention_released_at IS NULL
        """
    ).fetchall()
    retained.update(
        GenerationFileRef("financial_candidate", str(row["candidate_manifest_sha256"]))
        for row in daily_candidate_rows
    )
    raw_rows = transaction.execute(
        """
        SELECT DISTINCT shard.batch_sha256
        FROM data.financial_collection_operations AS operation
        JOIN data.financial_collection_shards AS shard
          ON shard.idempotency_key = operation.idempotency_key
        WHERE operation.status = 'succeeded'
          AND operation.retention_released_at IS NULL
          AND shard.status = 'completed'
        """
    ).fetchall()
    retained.update(
        GenerationFileRef("raw_financial", str(row["batch_sha256"])) for row in raw_rows
    )
    daily_raw_rows = transaction.execute(
        """
        SELECT DISTINCT checkpoint.value ->> 'batch_sha256' AS batch_sha256
        FROM data.financial_daily_refresh_operations AS operation
        JOIN data.financial_refresh_instrument_attempts AS attempt
          ON attempt.idempotency_key = operation.idempotency_key
        CROSS JOIN LATERAL jsonb_array_elements(attempt.checkpoints) AS checkpoint(value)
        WHERE operation.status IN (
                  'succeeded', 'succeeded_with_pending', 'succeeded_with_gaps'
              )
          AND operation.retention_released_at IS NULL
          AND attempt.status = 'accepted'
        """
    ).fetchall()
    retained.update(
        GenerationFileRef("raw_financial", str(row["batch_sha256"]))
        for row in daily_raw_rows
    )
    industry_candidate_rows = transaction.execute(
        """
        SELECT candidate_manifest_sha256
        FROM data.industry_refresh_operations
        WHERE status = 'succeeded' AND retention_released_at IS NULL
        """
    ).fetchall()
    retained.update(
        GenerationFileRef("industry_candidate", str(row["candidate_manifest_sha256"]))
        for row in industry_candidate_rows
    )
    industry_raw_rows = transaction.execute(
        """
        SELECT source_lineage_sha256
        FROM data.industry_refresh_operations
        WHERE source_lineage_sha256 IS NOT NULL AND retention_released_at IS NULL
        """
    ).fetchall()
    retained.update(
        GenerationFileRef("raw_industry", str(row["source_lineage_sha256"]))
        for row in industry_raw_rows
    )
    return roots, tuple(sorted(retained))


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

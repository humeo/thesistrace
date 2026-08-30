from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from benchmark_support import benchmark_mount_for_data_mount

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import (
    DataRefreshService,
    DataRefreshWorkerLease,
    DatasetLifecycle,
    DatasetOperationalStatusService,
    DatasetOverviewService,
    MountedGenerationStore,
)
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture


def test_worker_lease_heartbeats_and_expired_owner_is_fenced(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        _clear_worker_lease(database)
        status = _status(database, tmp_path).status(cursor=None)
        assert status.worker.available is False
        assert status.worker.last_heartbeat_at is None

        first = DataRefreshWorkerLease(
            database,
            lease_seconds=15,
            heartbeat_seconds=0.01,
        )
        with first.maintain() as first_owner:
            first_status = _status(database, tmp_path).status(cursor=None)
            assert first_status.worker.available is True
            first_heartbeat = first_status.worker.last_heartbeat_at
            assert first_heartbeat is not None
            _wait_for_new_heartbeat(database, after=first_heartbeat, timeout=2)

            with database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.refresh_worker_leases
                    SET lease_expires_at = (
                        last_heartbeat_at + interval '1 microsecond'
                    )
                    WHERE singleton = 1
                    """
                )
            expired = _status(database, tmp_path).status(cursor=None)
            assert expired.worker.available is False
            assert expired.worker.last_heartbeat_at is not None

            replacement = DataRefreshWorkerLease(database)
            with replacement.maintain() as replacement_owner:
                replacement_owner.assert_owned()
                with pytest.raises(RuntimeError, match="Worker lease was lost"):
                    first_owner.assert_owned()
                recovered = _status(database, tmp_path).status(cursor=None)
                assert recovered.worker.available is True
                replacement_heartbeat = recovered.worker.last_heartbeat_at
                assert replacement_heartbeat is not None

        unavailable = _status(database, tmp_path).status(cursor=None)
        assert unavailable.worker.available is False
        assert unavailable.worker.last_heartbeat_at == replacement_heartbeat
    finally:
        _clear_worker_lease(database)
        database.close()


def test_persisted_submission_stays_accepted_without_a_worker(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    key = "worker-unavailable-accepted"
    try:
        _clear_worker_lease(database)
        _establish_head(database, tmp_path)
        refresh = DataRefreshService(
            database,
            tmp_path,
            benchmark_mount_root=benchmark_mount_for_data_mount(tmp_path),
        )

        accepted = refresh.submit(
            idempotency_key=key,
            as_of=datetime(2026, 8, 30, 8, tzinfo=UTC),
        )

        assert accepted.status == "accepted"
        snapshot = _status(database, tmp_path).status(cursor=None)
        assert snapshot.worker.available is False
        persisted = next(
            operation
            for operation in snapshot.operations
            if operation.idempotency_key == key
        )
        assert persisted.status == "accepted"
        assert persisted.attempt_count == 0
    finally:
        with database.transaction() as transaction:
            transaction.execute(
                "DELETE FROM data.refresh_operations WHERE idempotency_key = %s",
                (key,),
            )
        _clear_worker_lease(database)
        database.close()


def _database(settings: CoreSettings) -> PostgresDatabase:
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    return database


def _status(
    database: PostgresDatabase,
    mount_root: Path,
) -> DatasetOperationalStatusService:
    return DatasetOperationalStatusService(
        database,
        DatasetOverviewService(
            database,
            mount_root,
            benchmark_mount_for_data_mount(mount_root),
        ),
    )


def _clear_worker_lease(database: PostgresDatabase) -> None:
    with database.transaction() as transaction:
        transaction.execute("DELETE FROM data.refresh_worker_leases")


def _establish_head(database: PostgresDatabase, mount_root: Path) -> None:
    generation = MountedGenerationStore(mount_root).materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 29, 23, tzinfo=UTC),
        source_name="worker-availability-fixture",
        source_lineage={"fixture": "worker-availability"},
    )
    lifecycle = DatasetLifecycle(database, mount_root)
    lifecycle.protect_candidate(
        operation_id="worker-availability-head",
        generation_manifest_sha256=generation.manifest_sha256,
        lease_seconds=60,
    )
    lifecycle.compare_and_swap_head(
        expected_generation_manifest_sha256=None,
        candidate_generation_manifest_sha256=generation.manifest_sha256,
        operation_id="worker-availability-head",
    )


def _wait_for_new_heartbeat(
    database: PostgresDatabase,
    *,
    after: datetime,
    timeout: float,
) -> None:
    deadline = monotonic() + timeout
    poll = Event()
    while monotonic() < deadline:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT last_heartbeat_at
                FROM data.refresh_worker_leases
                WHERE singleton = 1
                """
            ).fetchone()
        if row is not None and row["last_heartbeat_at"] > after:
            return
        poll.wait(timeout=0.01)
    raise AssertionError("Data Operator Worker heartbeat was not renewed")

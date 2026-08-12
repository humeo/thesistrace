from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from psycopg import Connection, connect
from psycopg.conninfo import make_conninfo

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import (
    DatasetLifecycle,
    MountedGenerationStore,
    read_alpha_field_series,
)
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import RunInput, run
from thesistrace.research_run.result import build_result_payload, read_result_bundle

SESSIONS = ("2026-08-03", "2026-08-04", "2026-08-05")
ADVISORY_KEY = 150015


@dataclass
class _BlockedWorker:
    settings: CoreSettings
    run_id: str
    process: subprocess.Popen[str]
    advisory_owner: Connection[object]
    application_name: str
    barrier_released: bool = False
    stopped: bool = False
    stdout: str = ""
    stderr: str = ""

    def wait_until_blocked(self) -> None:
        poll = Event()
        for _ in range(500):
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                raise AssertionError(
                    "Worker exited before reaching the PostgreSQL barrier; "
                    f"exit={self.process.returncode}; stdout={stdout!r}; "
                    f"stderr={stderr!r}; attempts={_attempts(self.settings, self.run_id)!r}"
                )
            if self._matching_locks():
                return
            poll.wait(0.02)
        self.terminate()
        raise AssertionError(
            "Worker did not reach the PostgreSQL barrier; "
            f"exit={self.process.returncode}; stdout={self.stdout!r}; "
            f"stderr={self.stderr!r}; attempts={_attempts(self.settings, self.run_id)!r}; "
            f"locks={self._matching_locks()!r}"
        )

    def backend_pid(self) -> int:
        rows = self._matching_locks()
        if len(rows) != 1:
            raise AssertionError(f"expected one blocked Worker backend, got {rows!r}")
        return int(rows[0]["pid"])

    def stop(self) -> None:
        os.kill(self.process.pid, signal.SIGSTOP)
        self.stopped = True

    def resume(self) -> None:
        if self.stopped and self.process.poll() is None:
            os.kill(self.process.pid, signal.SIGCONT)
        self.stopped = False

    def terminate(self) -> None:
        self.resume()
        if self.process.poll() is None:
            self.process.terminate()
        self.stdout, self.stderr = self.process.communicate(timeout=10)

    def release_barrier(self) -> None:
        if self.barrier_released:
            return
        self.advisory_owner.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_KEY,)).fetchone()
        self.advisory_owner.close()
        _drop_worker_block(self.settings)
        self.barrier_released = True

    def close(self) -> None:
        self.terminate()
        self.release_barrier()

    def _matching_locks(self) -> list[dict[str, object]]:
        database = PostgresDatabase(self.settings.database_url)
        database.open()
        try:
            with database.transaction() as transaction:
                rows = transaction.execute(
                    """
                    SELECT lock.pid, lock.granted, activity.state,
                           activity.wait_event_type, activity.wait_event
                    FROM pg_locks AS lock
                    JOIN pg_stat_activity AS activity ON activity.pid = lock.pid
                    WHERE lock.locktype = 'advisory'
                      AND lock.database = (
                          SELECT oid FROM pg_database
                          WHERE datname = current_database()
                      )
                      AND lock.classid = 0
                      AND lock.objid = %s
                      AND lock.objsubid = 1
                      AND NOT lock.granted
                      AND activity.application_name = %s
                    ORDER BY lock.pid
                    """,
                    (ADVISORY_KEY, self.application_name),
                ).fetchall()
            return rows
        finally:
            database.close()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_worker_loss_retry_recomputes_on_the_then_current_head(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as first_process:
        run_id = _admit_run(first_process, request_id="retry-current-head")
        with _blocked_worker(settings, run_id) as blocked:
            blocked.wait_until_blocked()
            blocked.terminate()
            assert blocked.process.returncode != 0, blocked.stdout + blocked.stderr
        assert _attempts(settings, run_id) == [
            {
                "ordinal": 1,
                "status": "running",
                "failure_reason": None,
                "data_generation_id": head_a,
            }
        ]
        _expire_live_attempt(settings, run_id)
        head_b = _publish_head(settings, price_offset=7, expected_manifest=head_a)

    with TestClient(create_app(settings)) as restarted_process:
        runtime = restarted_process.app.state.core_runtime
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        detail = restarted_process.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded"
        assert "attempt" not in str(detail).lower()
        assert "generation" not in str(detail).lower()

        attempts = _attempts(settings, run_id)
        assert attempts == [
            {
                "ordinal": 1,
                "status": "failed",
                "failure_reason": "WorkerLost",
                "data_generation_id": head_a,
            },
            {
                "ordinal": 2,
                "status": "succeeded",
                "failure_reason": None,
                "data_generation_id": head_b,
            },
        ]
        stored = _stored_run(settings, run_id)
        assert stored["result_provenance"]["data_generation_id"] == head_b
        assert stored["result_provenance"]["data_through_session"] == SESSIONS[-1]
        assert set(_read_result(runtime, stored)) == {
            "factor_summary",
            "strategy_summary",
            "strategy_daily_observations",
            "terminal_strategy_state",
        }
        expected = _reference_result(settings, head_b)
        assert canonical_json_bytes(_read_result(runtime, stored)) == canonical_json_bytes(expected)
        assert len(_attempts(settings, run_id)) == 2


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_recovered_winner_fences_a_stale_prepared_attempt(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(client, request_id="retry-stale-fence")
        with _blocked_worker(settings, run_id) as stale:
            stale.wait_until_blocked()
            backend_pid = stale.backend_pid()
            stale.stop()
            _terminate_backend(settings, backend_pid)
            stale.release_barrier()
            _expire_live_attempt(settings, run_id)
            head_b = _publish_head(settings, price_offset=9, expected_manifest=head_a)

            completed_worker = _run_worker_once(settings)
            assert completed_worker.returncode == 0, (
                completed_worker.stdout + completed_worker.stderr
            )
            winning = client.get(f"/api/research-runs/{run_id}").json()
            assert winning["status"] == "succeeded"
            stale.resume()
            stale.stdout, stale.stderr = stale.process.communicate(timeout=10)
            assert stale.process.returncode == 0, stale.stdout + stale.stderr

        assert client.get(f"/api/research-runs/{run_id}").json() == winning
        assert [row["status"] for row in _attempts(settings, run_id)] == [
            "failed",
            "succeeded",
        ]
        stored = _stored_run(settings, run_id)
        assert stored["result_provenance"]["data_generation_id"] == head_b
        assert _research_result_manifest_count(settings) == 1


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_worker_loss_retry_exhaustion_is_bounded_and_restart_stable(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(client, request_id="retry-exhaustion")
        for ordinal in range(1, 4):
            with _blocked_worker(settings, run_id) as blocked:
                blocked.wait_until_blocked()
                blocked.terminate()
                assert blocked.process.returncode != 0, blocked.stdout + blocked.stderr
            assert len(_attempts(settings, run_id)) == ordinal
            _expire_live_attempt(settings, run_id)

        exhausted = _run_worker_once(settings)
        assert exhausted.returncode == 0, exhausted.stdout + exhausted.stderr
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == (
            "Research execution could not complete after automatic retries."
        )
        assert "WorkerLost" not in str(failed)
        assert [row["status"] for row in _attempts(settings, run_id)] == [
            "failed",
            "failed",
            "failed",
        ]

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-runs/{run_id}").json() == failed
        idle = _run_worker_once(settings)
        assert idle.returncode == 0, idle.stdout + idle.stderr
        assert len(_attempts(settings, run_id)) == 3


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_resource_exhaustion_is_bounded_sanitized_and_restart_stable(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(client, request_id="resource-exhaustion")
        _install_resource_exhaustion(settings)
        try:
            first = _run_worker_once(settings)
            assert first.returncode == 0, first.stdout + first.stderr
            retrying = client.get(f"/api/research-runs/{run_id}").json()
            assert retrying["status"] == "running"
            assert "failure_reason" not in retrying

            second = _run_worker_once(settings)
            assert second.returncode == 0, second.stdout + second.stderr
        finally:
            _remove_resource_exhaustion(settings)
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == ("Research execution exceeded its resource limit.")
        assert "secret-resource-pressure-detail" not in str(failed)
        assert [row["failure_reason"] for row in _attempts(settings, run_id)] == [
            "ResourceExhausted",
            "ResourceExhausted",
        ]
        assert _research_result_manifest_count(settings) == 0

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-runs/{run_id}").json() == failed
        assert len(_attempts(settings, run_id)) == 2


def _admit_run(client: TestClient, *, request_id: str) -> str:
    response = client.post("/api/research-runs", json=_run_command(request_id))
    assert response.status_code == 202
    return str(response.json()["id"])


def _run_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "Same research question on current data",
        "start_date": SESSIONS[0],
        "end_date": SESSIONS[-1],
        "formula": "close_adj",
        "universe": "top300",
        "neutralization": "none",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _publish_head(
    settings: CoreSettings,
    *,
    price_offset: int,
    expected_manifest: str | None = None,
) -> str:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        _canonical(price_offset=price_offset),
        prepared_at=datetime(2026, 8, 10, 0, price_offset, tzinfo=UTC),
        source_name="retry-current-head-test",
        source_lineage={"price_offset": price_offset},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        operation_id = f"retry-current-head-{price_offset}"
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected_manifest,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _canonical(*, price_offset: int) -> dict[str, object]:
    template = build_minimal_canonical_fixture(price_offset=price_offset)
    instrument_id = str(template["instruments"][0]["instrument_id"])
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "research_calendar": list(SESSIONS),
        "prices": [{**template["prices"][0], "session": session} for session in SESSIONS],
        "trading_states": [
            {**template["trading_states"][0], "session": session} for session in SESSIONS
        ],
        "price_limits": [
            {**template["price_limits"][0], "session": session} for session in SESSIONS
        ],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in SESSIONS
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in SESSIONS]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _reference_result(settings: CoreSettings, generation_id: str) -> dict[str, object]:
    canonical = MountedGenerationStore(settings.data_mount).open_generation(generation_id).canonical
    output = run(
        RunInput(
            canonical_data=canonical,
            alpha_expression={"kind": "field", "field_id": "price.close.adjusted"},
            field_bindings={"price.close.adjusted": "close_adj"},
            effective_alpha_lookback=0,
            universe="top300",
            neutralization="none",
            holdings_count=1,
            rebalance_interval=1,
            initial_cash_cny="10000000",
            commission_rate_all_in="0.0003",
            commission_min_cny="5",
            stamp_duty_sell_rate="0.0005",
            transfer_fee_rate="0.00001",
            read_field_series=read_alpha_field_series,
            research_start_session=SESSIONS[0],
            research_end_session=SESSIONS[-1],
        )
    )
    return build_result_payload(output, rebalance_interval=1, universe="top300")


def _read_result(runtime, stored: dict[str, object]) -> dict[str, object]:
    return read_result_bundle(
        runtime.publication.read(
            PublishedRef(
                manifest_sha256=str(stored["result_manifest_sha256"]),
                kind="research.result",
                provenance=stored["result_provenance"],
            )
        )
    )


def _expire_live_attempt(settings: CoreSettings, run_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET lease_expires_at = '2000-01-01'
                WHERE run_id = %s AND status = 'running'
                """,
                (run_id,),
            )
        assert updated.rowcount == 1
    finally:
        database.close()


def _attempts(settings: CoreSettings, run_id: str) -> list[dict[str, object]]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT ordinal, status, failure_reason, data_generation_id
                FROM research_runs.attempts
                WHERE run_id = %s
                ORDER BY ordinal
                """,
                (run_id,),
            ).fetchall()
        return rows
    finally:
        database.close()


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT immutable_input, result_manifest_sha256, result_provenance
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return row
    finally:
        database.close()


def _research_result_manifest_count(settings: CoreSettings) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS count
                FROM publication.manifests
                WHERE kind = 'research.result'
                """
            ).fetchone()
        assert row is not None
        return int(row["count"])
    finally:
        database.close()


def _install_resource_exhaustion(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION publication.reject_ticket15_out_of_memory()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'secret-resource-pressure-detail'
                        USING ERRCODE = '53200';
                END
                $$;
                CREATE TRIGGER reject_ticket15_out_of_memory
                BEFORE INSERT ON publication.manifests
                FOR EACH ROW
                EXECUTE FUNCTION publication.reject_ticket15_out_of_memory();
                """
            )
    finally:
        database.close()


def _remove_resource_exhaustion(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_ticket15_out_of_memory ON publication.manifests;
                DROP FUNCTION publication.reject_ticket15_out_of_memory();
                """
            )
    finally:
        database.close()


def _terminate_backend(settings: CoreSettings, backend_pid: int) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT pg_terminate_backend(%s) AS terminated",
                (backend_pid,),
            ).fetchone()
        assert row == {"terminated": True}
    finally:
        database.close()


@contextmanager
def _blocked_worker(
    settings: CoreSettings,
    run_id: str,
) -> Iterator[_BlockedWorker]:
    advisory_owner: Connection[object] | None = None
    trigger_created = False
    blocked: _BlockedWorker | None = None
    try:
        advisory_owner = connect(settings.database_url, autocommit=True)
        advisory_owner.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_KEY,)).fetchone()
        database = PostgresDatabase(settings.database_url)
        database.open()
        try:
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    CREATE FUNCTION publication.block_ticket15_manifest()
                    RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    BEGIN
                        PERFORM pg_advisory_xact_lock(150015);
                        RETURN NEW;
                    END
                    $$;
                    CREATE TRIGGER block_ticket15_manifest
                    BEFORE INSERT ON publication.manifests
                    FOR EACH ROW
                    EXECUTE FUNCTION publication.block_ticket15_manifest();
                    """
                )
            trigger_created = True
        finally:
            database.close()
        application_name = f"ticket15_{uuid4().hex}"
        worker_settings = replace(
            settings,
            database_url=make_conninfo(
                settings.database_url,
                application_name=application_name,
            ),
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
            env=_worker_environment(worker_settings),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        blocked = _BlockedWorker(
            settings=settings,
            run_id=run_id,
            process=process,
            advisory_owner=advisory_owner,
            application_name=application_name,
        )
        yield blocked
    finally:
        if blocked is not None:
            blocked.close()
        else:
            if advisory_owner is not None and not advisory_owner.closed:
                advisory_owner.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_KEY,)).fetchone()
                advisory_owner.close()
            if trigger_created:
                _drop_worker_block(settings)


def _drop_worker_block(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER IF EXISTS block_ticket15_manifest
                    ON publication.manifests;
                DROP FUNCTION IF EXISTS publication.block_ticket15_manifest();
                """
            )
    finally:
        database.close()


def _run_worker_once(settings: CoreSettings) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=_worker_environment(settings),
    )


def _worker_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
    }

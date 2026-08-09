from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from core_runtime import create_migrated_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from psycopg import Connection, connect

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import RunInput, run
from thesistrace.research_run.result import build_result_payload, read_result_bundle

SESSIONS = ("2026-08-03", "2026-08-04", "2026-08-05")


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_worker_loss_retry_recomputes_on_the_then_current_head(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as first_process:
        run_id = _admit_run(first_process, request_id="retry-current-head")
        blocked_worker, advisory_owner = _start_blocked_worker(settings)
        try:
            assert _wait_for_advisory_waiter(settings)
            blocked_worker.terminate()
            stdout, stderr = blocked_worker.communicate(timeout=10)
            assert blocked_worker.returncode != 0, stdout + stderr
        finally:
            if blocked_worker.poll() is None:
                blocked_worker.terminate()
                blocked_worker.communicate(timeout=10)
            _release_worker_block(settings, advisory_owner)
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
        idle = _run_worker_once(settings)
        assert idle.returncode == 0, idle.stdout + idle.stderr
        assert len(_attempts(settings, run_id)) == 2


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_recovered_winner_fences_a_stale_prepared_attempt(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(client, request_id="retry-stale-fence")
        stale_worker, advisory_owner = _start_blocked_worker(settings)
        block_released = False
        stale_stopped = False
        try:
            assert _wait_for_advisory_waiter(settings)
            backend_pid = _waiting_advisory_backend_pid(settings)
            os.kill(stale_worker.pid, signal.SIGSTOP)
            stale_stopped = True
            _terminate_backend(settings, backend_pid)
            _release_worker_block(settings, advisory_owner)
            block_released = True
            _expire_live_attempt(settings, run_id)
            head_b = _publish_head(settings, price_offset=9, expected_manifest=head_a)

            completed_worker = _run_worker_once(settings)
            assert completed_worker.returncode == 0, (
                completed_worker.stdout + completed_worker.stderr
            )
            winning = client.get(f"/api/research-runs/{run_id}").json()
            assert winning["status"] == "succeeded"
            os.kill(stale_worker.pid, signal.SIGCONT)
            stale_stopped = False
            stdout, stderr = stale_worker.communicate(timeout=10)
            assert stale_worker.returncode == 0, stdout + stderr
        finally:
            if stale_stopped and stale_worker.poll() is None:
                os.kill(stale_worker.pid, signal.SIGCONT)
            if stale_worker.poll() is None:
                stale_worker.terminate()
                stale_worker.communicate(timeout=10)
            if not block_released:
                _release_worker_block(settings, advisory_owner)

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
    migrate_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(client, request_id="retry-exhaustion")
        for ordinal in range(1, 4):
            blocked_worker, advisory_owner = _start_blocked_worker(settings)
            try:
                assert _wait_for_advisory_waiter(settings)
                blocked_worker.terminate()
                stdout, stderr = blocked_worker.communicate(timeout=10)
                assert blocked_worker.returncode != 0, stdout + stderr
            finally:
                if blocked_worker.poll() is None:
                    blocked_worker.terminate()
                    blocked_worker.communicate(timeout=10)
                _release_worker_block(settings, advisory_owner)
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
    migrate_core(settings.database_url)
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
        idle = _run_worker_once(settings)
        assert idle.returncode == 0, idle.stdout + idle.stderr

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-runs/{run_id}").json() == failed
        restarted_worker = _run_worker_once(settings)
        assert restarted_worker.returncode == 0, (
            restarted_worker.stdout + restarted_worker.stderr
        )
        assert len(_attempts(settings, run_id)) == 2


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_rerun_preserves_the_question_and_executes_on_current_data(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        source_id = _admit_run(client, request_id="rerun-source")
        source_worker = _run_worker_once(settings)
        assert source_worker.returncode == 0, source_worker.stdout + source_worker.stderr
        source_before = client.get(f"/api/research-runs/{source_id}").json()
        source_stored_before = _stored_run(settings, source_id)
        source_input = source_stored_before["immutable_input"]
        assert source_stored_before["result_provenance"]["data_generation_id"] == head_a

        edited = client.put(
            f"/api/definitions/{source_before['definition_id']}",
            json={
                "expected_revision": source_before["definition_revision"],
                "name": "Edited after source Run",
                "holdings_count": 2,
            },
        )
        assert edited.status_code == 200
        head_b = _publish_head(settings, price_offset=11, expected_manifest=head_a)

        command = {"request_id": "rerun-current-data"}
        accepted = client.post(f"/api/research-runs/{source_id}/rerun", json=command)
        assert accepted.status_code == 202
        rerun = accepted.json()
        assert rerun["status"] == "queued"
        assert rerun["rerun_of_id"] == source_id
        assert rerun["start_date"] == SESSIONS[0]
        assert rerun["end_date"] == SESSIONS[-1]
        rerun_stored = _stored_run(settings, rerun["id"])
        assert canonical_json_bytes(rerun_stored["immutable_input"]) == canonical_json_bytes(
            source_input
        )

        replay = client.post(f"/api/research-runs/{source_id}/rerun", json=command)
        assert replay.status_code == 202
        assert replay.json() == rerun
        conflict = client.post(
            f"/api/research-runs/{rerun['id']}/rerun",
            json=command,
        )
        assert conflict.status_code == 409

        rerun_worker = _run_worker_once(settings)
        assert rerun_worker.returncode == 0, rerun_worker.stdout + rerun_worker.stderr
        completed = client.get(f"/api/research-runs/{rerun['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["rerun_of_id"] == source_id
        completed_stored = _stored_run(settings, rerun["id"])
        assert completed_stored["result_provenance"]["data_generation_id"] == head_b
        assert canonical_json_bytes(_read_result(runtime, completed_stored)) == (
            canonical_json_bytes(_reference_result(settings, head_b))
        )
        assert client.get(f"/api/research-runs/{source_id}").json() == source_before
        assert _stored_run(settings, source_id) == source_stored_before


def _admit_run(client: TestClient, *, request_id: str) -> str:
    response = client.post("/api/definitions/run", json=_run_command(request_id))
    assert response.status_code == 200
    return str(response.json()["run"]["id"])


def _run_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "name": "Same research question on current data",
        "start_date": SESSIONS[0],
        "end_date": SESSIONS[-1],
        "alpha": {"field_id": "price.close.adjusted"},
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
            alpha_expression={"field_id": "price.close.adjusted"},
            field_bindings={"price.close.adjusted": "close_adj"},
            universe="top300",
            neutralization="none",
            holdings_count=1,
            rebalance_interval=1,
            initial_cash_cny="10000000",
            commission_rate_all_in="0.0003",
            commission_min_cny="5",
            stamp_duty_sell_rate="0.0005",
            transfer_fee_rate="0.00001",
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


def _start_blocked_worker(
    settings: CoreSettings,
) -> tuple[subprocess.Popen[str], Connection[object]]:
    advisory_owner = connect(settings.database_url, autocommit=True)
    advisory_owner.execute("SELECT pg_advisory_lock(150015)").fetchone()
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION publication.block_ticket15_manifest() RETURNS trigger
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
    finally:
        database.close()
    worker = subprocess.Popen(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        env=_worker_environment(settings),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return worker, advisory_owner


def _wait_for_advisory_waiter(settings: CoreSettings) -> bool:
    poll = Event()
    for _ in range(500):
        database = PostgresDatabase(settings.database_url)
        database.open()
        try:
            with database.transaction() as transaction:
                row = transaction.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_locks
                        WHERE locktype = 'advisory' AND NOT granted
                    ) AS waiting
                    """
                ).fetchone()
        finally:
            database.close()
        assert row is not None
        if bool(row["waiting"]):
            return True
        poll.wait(0.02)
    return False


def _waiting_advisory_backend_pid(settings: CoreSettings) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT pid
                FROM pg_locks
                WHERE locktype = 'advisory' AND NOT granted
                ORDER BY pid
                LIMIT 1
                """
            ).fetchone()
        assert row is not None
        return int(row["pid"])
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


def _release_worker_block(
    settings: CoreSettings,
    advisory_owner: Connection[object],
) -> None:
    advisory_owner.execute("SELECT pg_advisory_unlock(150015)").fetchone()
    advisory_owner.close()
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER block_ticket15_manifest ON publication.manifests;
                DROP FUNCTION publication.block_ticket15_manifest();
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

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

import pytest
from core_runtime import create_migrated_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import RunInput, run
from thesistrace.research_run import ResearchRunService
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
        runtime = first_process.app.state.core_runtime
        run_id = _admit_run(first_process, request_id="retry-current-head")
        lost_worker = _processor(
            runtime,
            settings,
            progress=lambda stage, _run_id: _exit_after_claim(stage),
        )

        with pytest.raises(SystemExit, match="simulated worker loss"):
            lost_worker.process_next()
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
        assert runtime.research_runs.process_next() is True
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
        assert runtime.research_runs.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_recovered_winner_fences_a_stale_prepared_attempt(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0)
    prepared = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="retry-stale-fence")

        def pause_after_prepare(stage: str, current_run_id: str) -> None:
            if stage != "prepared":
                return
            _expire_live_attempt(settings, current_run_id)
            prepared.set()
            assert release_stale.wait(timeout=10)

        stale = _processor(runtime, settings, progress=pause_after_prepare)
        stale_thread = Thread(target=stale.process_next)
        stale_thread.start()
        assert prepared.wait(timeout=10)
        head_b = _publish_head(settings, price_offset=9, expected_manifest=head_a)

        assert runtime.research_runs.process_next() is True
        winning = client.get(f"/api/research-runs/{run_id}").json()
        assert winning["status"] == "succeeded"
        release_stale.set()
        stale_thread.join(timeout=10)
        assert not stale_thread.is_alive()

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
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="retry-exhaustion")
        for ordinal in range(1, 4):
            lost_worker = _processor(
                runtime,
                settings,
                progress=lambda stage, _run_id: _exit_after_claim(stage),
            )
            with pytest.raises(SystemExit, match="simulated worker loss"):
                lost_worker.process_next()
            assert len(_attempts(settings, run_id)) == ordinal
            _expire_live_attempt(settings, run_id)

        assert runtime.research_runs.process_next() is False
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
        assert restarted.app.state.core_runtime.research_runs.process_next() is False
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
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="resource-exhaustion")

        def exhaust_after_real_preparation(stage: str, _run_id: str) -> None:
            if stage == "prepared":
                raise MemoryError("secret-resource-pressure-detail")

        exhausted = _processor(
            runtime,
            settings,
            progress=exhaust_after_real_preparation,
        )
        assert exhausted.process_next() is True
        retrying = client.get(f"/api/research-runs/{run_id}").json()
        assert retrying["status"] == "running"
        assert "failure_reason" not in retrying

        assert exhausted.process_next() is True
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == ("Research execution exceeded its resource limit.")
        assert "secret-resource-pressure-detail" not in str(failed)
        assert [row["failure_reason"] for row in _attempts(settings, run_id)] == [
            "ResourceExhausted",
            "ResourceExhausted",
        ]
        assert _research_result_manifest_count(settings) == 0
        assert exhausted.process_next() is False

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-runs/{run_id}").json() == failed
        assert restarted.app.state.core_runtime.research_runs.process_next() is False
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
        assert runtime.research_runs.process_next() is True
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

        assert runtime.research_runs.process_next() is True
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


def _processor(runtime, settings: CoreSettings, *, progress=None) -> ResearchRunService:
    return ResearchRunService(
        runtime.database,
        dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
        generation_store=MountedGenerationStore(settings.data_mount),
        publication=runtime.publication,
        progress=progress,
        heartbeat_seconds=60,
    )


def _exit_after_claim(stage: str) -> None:
    if stage == "claimed":
        raise SystemExit("simulated worker loss")


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

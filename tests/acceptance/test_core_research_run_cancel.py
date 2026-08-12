from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_current_head_research_run_retry import _admit_run, _publish_head

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_run import ResearchRunService


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_queued_cancel_replays_and_conflicts_without_malformed_receipt(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="current-data-queued-cancel")
        second_id = _admit_run(client, request_id="current-data-conflict-target")

        cancelled = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-cancel"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert _run_storage(runtime.database, run_id) == {
            "status": "cancelled",
            "execution_fence": 1,
            "attempt_count": 0,
            "result_count": 0,
        }

        replay = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-cancel"},
        )
        assert replay.status_code == 200
        assert replay.json() == cancelled.json()
        assert _cancel_receipt_count(runtime.database) == 1

        conflict = client.post(
            f"/api/research-runs/{second_id}/cancel",
            json={"request_id": "current-data-cancel"},
        )
        assert conflict.status_code == 409
        malformed = client.post(
            f"/api/research-runs/{second_id}/cancel",
            json={"unexpected": "field"},
        )
        assert malformed.status_code == 422
        assert _run_storage(runtime.database, second_id)["status"] == "queued"
        missing = client.post(
            "/api/research-runs/run_missing/cancel",
            json={"request_id": "current-data-missing"},
        )
        assert missing.status_code == 404


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_running_cancel_fences_a_stale_prepared_worker_and_survives_restart(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)
    prepared = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="current-data-running-cancel")

        def pause_after_prepare(stage: str, _run_id: str) -> None:
            if stage == "prepared":
                prepared.set()
                assert release_stale.wait(timeout=30)

        stale = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            progress=pause_after_prepare,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale.process_next)
            assert prepared.wait(timeout=20)
            try:
                cancelled = client.post(
                    f"/api/research-runs/{run_id}/cancel",
                    json={"request_id": "current-data-running-cancel-request"},
                )
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelled"
            finally:
                release_stale.set()
            assert future.result(timeout=30) is True

        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _run_storage(runtime.database, run_id)["result_count"] == 0

    with TestClient(create_app(settings)) as restarted:
        replay = restarted.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-running-cancel-request"},
        )
        assert replay.status_code == 200
        assert replay.json() == cancelled.json()
        assert restarted.app.state.core_runtime.research_runs.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_terminal_run_wins_over_late_cancel(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="current-data-terminal-cancel")
        assert runtime.research_runs.process_next() is True
        before = client.get(f"/api/research-runs/{run_id}").json()
        assert before["status"] == "succeeded"

        outcome = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-after-success"},
        )
        assert outcome.status_code == 200
        assert outcome.json() == {
            key: before[key]
            for key in (
                "id",
                "status",
                "definition_id",
                "definition_revision",
                "start_date",
                "end_date",
            )
        }
        assert client.get(f"/api/research-runs/{run_id}").json() == before


def _run_storage(database: PostgresDatabase, run_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT run.status, run.execution_fence,
                   (SELECT count(*) FROM research_runs.attempts AS attempt
                    WHERE attempt.run_id = run.id) AS attempt_count,
                   (SELECT count(*) FROM publication.manifests
                    WHERE kind = 'research.result') AS result_count
            FROM research_runs.runs AS run
            WHERE run.id = %s
            """,
            (run_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _attempt_status(database: PostgresDatabase, run_id: str) -> str:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT status FROM research_runs.attempts WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _cancel_receipt_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS count FROM research_runs.cancel_receipts"
        ).fetchone()
    assert row is not None
    return int(row["count"])

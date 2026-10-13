from dataclasses import replace

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, isolated_core_settings
from fastapi.testclient import TestClient
from test_core_independent_strategy_batch import command as batch_command
from test_core_research_batch_admission import SESSIONS, _publish_current_data
from test_core_research_batch_factor_execution import _ordinary_factor_command

from thesistrace.entrypoints.runtime import core_environment_is_configured

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="isolated Core runtime is not configured",
)


class RepeatedMeasurementsExecutor:
    def __init__(self, delegate):
        self.delegate = delegate

    def execute(self, request, *, emit, cancel_requested):
        def repeated(event):
            emit(event)
            if (
                event.get("event") == "research_execution_chunk_received"
                or "child_processing_seconds" in event
            ):
                emit(event)

        return self.delegate.execute(request, emit=repeated, cancel_requested=cancel_requested)


@pytest.mark.parametrize("kind", ["ordinary", "independent_strategies"])
def test_public_run_timing_reports_processing_excludes_long_wait_and_deduplicates_events(
    tmp_path,
    kind,
):
    settings = replace(isolated_core_settings(tmp_path), research_max_chunk_sessions=2)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings, instrument_count=3, sessions=("2026-07-31", *SESSIONS))
        runtime = client.app.state.core_runtime
        events = []
        if kind == "ordinary":
            submitted = client.post(
                "/api/research-runs",
                json=_ordinary_factor_command(
                    "timing-ordinary",
                    formula="rank(close)",
                ),
            )
            assert submitted.status_code == 202, submitted.text
            run_id = submitted.json()["id"]
            processor = runtime.research_runs
        else:
            submitted = client.post("/api/research-batches", json=batch_command("timing-batch"))
            assert submitted.status_code == 202, submitted.text
            run_id = submitted.json()["items"][0]["research_run_id"]
            processor = runtime.research_batches
        processor._execution = RepeatedMeasurementsExecutor(processor._execution)
        assert processor.process_next(on_execution_event=events.append)
        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded", detail
        if kind == "ordinary":
            chunks = {
                e["chunk_ordinal"]: e["child_chunk_seconds"]
                for e in events
                if e.get("event") == "research_execution_chunk_received"
            }
            measured = sum(chunks.values())
            table, predicate = "research_runs.attempts", "run_id=%s"
            params = (run_id,)
        else:
            completed = next(
                e
                for e in events
                if e.get("event") == "research_batch_execution_item_succeeded"
                and e.get("run_id") == run_id
            )
            measured = completed["child_processing_seconds"]
            table = "research_batches.task_attempts"
            predicate = "batch_id=%s AND item_ordinal=1"
            params = (submitted.json()["id"],)
        assert measured > 0
        assert detail["execution_timing"]["elapsed_seconds"] == pytest.approx(measured)
        with runtime.database.transaction() as tx:
            tx.execute(
                f"UPDATE {table} SET started_at=started_at-interval '1 hour' WHERE {predicate}",
                params,
            )
        waited = client.get(f"/api/research-runs/{run_id}").json()["execution_timing"]
        assert waited["elapsed_seconds"] == pytest.approx(measured)
        assert waited["started_at"] != detail["execution_timing"]["started_at"]
        with runtime.database.transaction() as tx:
            tx.execute(f"UPDATE {table} SET processing_seconds=NULL WHERE {predicate}", params)
        assert (
            client.get(f"/api/research-runs/{run_id}").json()["execution_timing"]["elapsed_seconds"]
            is None
        )

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, isolated_core_settings
from fastapi.testclient import TestClient
from test_core_research_batch_admission import _factor_command, _publish_current_data

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_batch import ResearchBatchService
from thesistrace.research_batch.execution import SupervisedResearchBatchExecutor
from thesistrace.research_run.result import read_result_bundle


class _PreparationBarrierExecutor:
    def __init__(self, delegate: SupervisedResearchBatchExecutor) -> None:
        self._delegate = delegate
        self.prepared = Event()
        self.release = Event()

    def execute(self, request, *, emit, cancel_requested):
        execution = self._delegate.execute(request, emit=emit, cancel_requested=cancel_requested)
        self.prepared.set()
        if not self.release.wait(timeout=10):
            execution.close()
            raise TimeoutError("Factor Batch preparation barrier timed out")
        return execution


class _TransportFailureExecutor:
    def execute(self, request, *, emit, cancel_requested):
        raise RuntimeError("injected Batch transport failure")


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_factor_batch_shares_preparation_preserves_frozen_generation_and_matches_ordinary(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []

    with TestClient(create_app(settings)) as client:
        frozen_generation = _publish_current_data(settings)
        runtime = client.app.state.core_runtime
        batch = client.post(
            "/api/research-batches",
            json=_factor_command("factor-batch-execution"),
        ).json()
        ordinary = [
            client.post(
                "/api/research-runs",
                json=_ordinary_factor_command(
                    f"ordinary-equivalent-{ordinal}",
                    formula=formula,
                ),
            ).json()
            for ordinal, formula in enumerate(("close", "rank(close)"), start=1)
        ]
        barrier = _PreparationBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            )
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=barrier,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                processor.process_next,
                on_execution_event=events.append,
            )
            if not barrier.prepared.wait(timeout=10):
                future.result(timeout=1)
                raise AssertionError("Batch preparation barrier was not reached")
            active = client.get(f"/api/research-batches/{batch['id']}").json()
            assert active["status"] == "running"
            assert all(item["status"] == "running" for item in active["items"])
            assert active["progress"] == {
                "completed_factor_tasks": 0,
                "total_factor_tasks": 2,
            }
            assert active["attempt"]["number"] == 1
            assert active["attempt"]["status"] == "running"
            assert active["live_progress"]["task_role"] == "preparation"
            assert active["live_progress"]["phase"] == "preparing_data"
            assert active["live_progress"]["is_estimate"] is True
            assert _batch_pin_state(settings, batch["id"]) == (1, 0)

            replacement_generation = _publish_current_data(
                settings,
                operation_id="factor-batch-replacement-head",
                expected_generation=frozen_generation,
                prepared_at=datetime(2026, 8, 11, 13, tzinfo=UTC),
            )
            assert replacement_generation != frozen_generation
            for ordinary_run in ordinary:
                assert runtime.research_runs.process_next() is True
                assert (
                    client.get(f"/api/research-runs/{ordinary_run['id']}").json()["status"]
                    == "succeeded"
                )
            barrier.release.set()
            assert future.result(timeout=20) is True

        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["progress"] == {
            "completed_factor_tasks": 2,
            "total_factor_tasks": 2,
        }
        assert completed["live_progress"] is None
        assert completed["execution_timing"]["is_final"] is True
        assert completed["attempt"]["status"] == "succeeded"
        assert [item["status"] for item in completed["items"]] == [
            "succeeded",
            "succeeded",
        ]
        assert [item["outcome"] for item in completed["items"]] == [
            "succeeded",
            "succeeded",
        ]
        for item, ordinary_run in zip(completed["items"], ordinary, strict=True):
            batch_detail = client.get(f"/api/research-runs/{item['research_run_id']}").json()
            ordinary_detail = client.get(f"/api/research-runs/{ordinary_run['id']}").json()
            assert canonical_json_bytes(batch_detail["result"]["factor"]) == (
                canonical_json_bytes(ordinary_detail["result"]["factor"])
            )
            batch_stored = _stored_run(settings, batch_detail["id"])
            ordinary_stored = _stored_run(settings, ordinary_detail["id"])
            assert batch_stored["result_provenance"]["data_generation_id"] == frozen_generation
            assert batch_stored["result_provenance"]["research_run_id"] == batch_detail["id"]
            assert (
                batch_stored["result_provenance"]["semantic_versions"]
                == (ordinary_stored["result_provenance"]["semantic_versions"])
            )
            assert (
                batch_stored["result_provenance"]["calculation_contracts"]
                == (ordinary_stored["result_provenance"]["calculation_contracts"])
            )
            assert canonical_json_bytes(
                _stored_factor_summary(runtime, batch_stored)
            ) == canonical_json_bytes(_stored_factor_summary(runtime, ordinary_stored))
        assert _batch_pin_state(settings, batch["id"]) == (0, 1)

    prepared = [
        event for event in events if event["event"] == "research_batch_execution_batch_prepared"
    ]
    assert len(prepared) == 1
    assert int(prepared[0]["data_io"]["parquet_object_opens"]) > 0
    assert int(prepared[0]["data_io"]["rows_scanned"]) > 0
    item_events = [
        event
        for event in events
        if event["event"] == "research_batch_execution_item_chunk_succeeded"
    ]
    assert sorted({int(event["item_ordinal"]) for event in item_events}) == [1, 2]
    assert sum(event["alpha_factor_task_started"] is True for event in item_events) == 2
    assert sum(event["alpha_factor_task_completed"] is True for event in item_events) == 2
    assert [
        int(event["item_ordinal"])
        for event in item_events
        if int(event["chunk_ordinal"])
        == max(
            int(candidate["chunk_ordinal"])
            for candidate in item_events
            if candidate["item_ordinal"] == event["item_ordinal"]
        )
    ] == [1, 2]
    assert all(float(event["child_data_read_seconds"]) == 0 for event in item_events)
    assert all(event["data_io"] == prepared[0]["data_io"] for event in item_events)
    assert (
        max(
            int(event["child_peak_rss_bytes"])
            for event in events
            if "child_peak_rss_bytes" in event
        )
        <= settings.research_execution_memory_bytes
    )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_factor_batch_isolates_one_deterministic_item_failure_and_continues(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _factor_command("factor-batch-mixed")
        admitted = client.post(
            "/api/research-batches",
            json={
                **command,
                "factors": [
                    {"item_key": "value", "formula": "close"},
                    {"item_key": "broken", "formula": "close + 1"},
                    {"item_key": "rank", "formula": "rank(close)"},
                ],
            },
        ).json()
        _invalidate_item_binding(settings, admitted["id"], ordinal=2)
        events: list[dict[str, object]] = []

        assert (
            client.app.state.core_runtime.research_batches.process_next(
                on_execution_event=events.append
            )
            is True
        )

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "completed_with_failures"
        assert completed["progress"] == {
            "completed_factor_tasks": 3,
            "total_factor_tasks": 3,
        }
        assert [item["status"] for item in completed["items"]] == [
            "succeeded",
            "failed",
            "succeeded",
        ]
        assert completed["items"][1]["outcome"] == "failed"
        assert completed["items"][1]["diagnostic"] == {
            "code": "RESEARCH_ITEM_CALCULATION_FAILED",
            "category": "calculation",
            "message": "Factor item calculation failed.",
        }
        assert "traceback" not in str(completed["items"][1]["diagnostic"]).lower()
        failed = client.get(f"/api/research-runs/{completed['items'][1]['research_run_id']}").json()
        assert failed["failure_reason"] == "Research calculation failed."
        assert _stored_run(settings, failed["id"])["result_manifest_sha256"] is None
        assert (
            client.get(f"/api/research-runs/{completed['items'][2]['research_run_id']}").json()[
                "result"
            ]
            is not None
        )
        assert any(
            event["event"] == "research_batch_execution_item_failed"
            and event["item_ordinal"] == 2
            and event["item_key"] == "broken"
            for event in events
        )

        no_success_command = _factor_command("factor-batch-no-success")
        no_success = client.post(
            "/api/research-batches",
            json={
                **no_success_command,
                "factors": [{"item_key": "broken", "formula": "close"}],
            },
        ).json()
        _invalidate_item_binding(settings, no_success["id"], ordinal=1)
        assert client.app.state.core_runtime.research_batches.process_next() is True
        failed_batch = client.get(f"/api/research-batches/{no_success['id']}").json()
        assert failed_batch["status"] == "failed"
        assert failed_batch["progress"] == {
            "completed_factor_tasks": 1,
            "total_factor_tasks": 1,
        }
        assert failed_batch["items"][0]["status"] == "failed"
        assert failed_batch["items"][0]["outcome"] == "failed"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_transport_failure_before_child_ready_does_not_charge_a_task_attempt(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _factor_command("factor-batch-partial-cleanup")
        admitted = client.post(
            "/api/research-batches",
            json={
                **command,
                "factors": [
                    {"item_key": "one", "formula": "close"},
                    {"item_key": "two", "formula": "close + 1"},
                    {"item_key": "three", "formula": "rank(close)"},
                ],
            },
        ).json()
        runtime = client.app.state.core_runtime
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=_TransportFailureExecutor(),
        )

        assert processor.process_next() is True

        current = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert current["status"] == "queued"
        assert [item["status"] for item in current["items"]] == ["queued"] * 3
        assert [item["task_attempt_count"] for item in current["items"]] == [0, 0, 0]
        assert [(item["outcome"], item["diagnostic"]) for item in current["items"]] == [
            (None, None),
            (None, None),
            (None, None),
        ]
        assert current["attempt"] is None
        assert _batch_pin_state(settings, admitted["id"]) == (0, 0)

        recovery = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            ),
        )
        assert recovery.process_next() is True
        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert [item["status"] for item in completed["items"]] == ["succeeded"] * 3
        assert [item["task_attempt_count"] for item in completed["items"]] == [1, 1, 1]
        assert completed["attempt"]["number"] == 1


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_widest_admitted_shared_slice_stays_inside_child_memory_budget(
    tmp_path: Path,
) -> None:
    sessions = _weekday_sessions(date(2026, 5, 1), 58)
    memory_bytes = 200 * 1024**2
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path,
        research_execution_memory_bytes=memory_bytes,
    )
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(
            settings,
            operation_id="factor-batch-widest-admitted",
            sessions=sessions,
            instrument_count=512,
        )
        command = _factor_command("factor-batch-widest-admitted")
        response = client.post(
            "/api/research-batches",
            json={
                **command,
                "start_date": sessions[0],
                "end_date": sessions[-1],
                "universe": "top1000",
                "factors": [{"item_key": "widest", "formula": "close"}],
            },
        )
        assert response.status_code == 202

        assert client.app.state.core_runtime.research_batches.process_next(
            on_execution_event=events.append
        )
        completed = client.get(f"/api/research-batches/{response.json()['id']}").json()
        assert completed["status"] == "succeeded"

    prepared = next(
        event for event in events if event["event"] == "research_batch_execution_batch_prepared"
    )
    assert prepared["shared_session_count"] == 58
    assert int(prepared["data_io"]["rows_scanned"]) >= 58 * 512
    assert (
        max(
            int(event["child_peak_rss_bytes"])
            for event in events
            if "child_peak_rss_bytes" in event
        )
        <= memory_bytes
    )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_one_and_twenty_factor_items_use_the_same_ordered_execution_contract(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        base = _factor_command("factor-batch-one")
        one = client.post(
            "/api/research-batches",
            json={
                **base,
                "factors": [{"item_key": "only", "formula": "close"}],
            },
        ).json()
        twenty = client.post(
            "/api/research-batches",
            json={
                **_factor_command("factor-batch-twenty"),
                "factors": [
                    {
                        "item_key": f"factor-{ordinal:02d}",
                        "formula": f"close + {ordinal}",
                    }
                    for ordinal in range(1, 21)
                ],
            },
        ).json()
        one_events: list[dict[str, object]] = []
        twenty_events: list[dict[str, object]] = []

        assert (
            client.app.state.core_runtime.research_batches.process_next(
                on_execution_event=one_events.append
            )
            is True
        )
        assert (
            client.app.state.core_runtime.research_batches.process_next(
                on_execution_event=twenty_events.append
            )
            is True
        )

        assert client.get(f"/api/research-batches/{one['id']}").json()["status"] == ("succeeded")
        twenty_completed = client.get(f"/api/research-batches/{twenty['id']}").json()
        assert twenty_completed["status"] == "succeeded"
        assert twenty_completed["progress"] == {
            "completed_factor_tasks": 20,
            "total_factor_tasks": 20,
        }
        final_ordinals = [
            int(event["item_ordinal"])
            for event in twenty_events
            if event["event"] == "research_batch_execution_item_chunk_succeeded"
            and event["boundary_session"] == "2026-08-04"
        ]
        assert final_ordinals == list(range(1, 21))
        for events, expected_items in ((one_events, 1), (twenty_events, 20)):
            assert (
                sum(event["event"] == "research_batch_execution_child_started" for event in events)
                == 1
            )
            assert (
                sum(event["event"] == "research_batch_execution_batch_prepared" for event in events)
                == 1
            )
            assert (
                len(
                    {
                        int(event["item_ordinal"])
                        for event in events
                        if event["event"] == "research_batch_execution_item_chunk_succeeded"
                    }
                )
                == expected_items
            )
            assert (
                sum(event.get("alpha_factor_task_started") is True for event in events)
                == expected_items
            )
            assert (
                sum(event.get("alpha_factor_task_completed") is True for event in events)
                == expected_items
            )


def _ordinary_factor_command(request_id: str, *, formula: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": request_id,
        "start_date": "2026-08-03",
        "end_date": "2026-08-04",
        "formula": formula,
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "factor_evaluation",
    }


def _weekday_sessions(first: date, count: int) -> tuple[str, ...]:
    sessions: list[str] = []
    current = first
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(sessions)


def _invalidate_item_binding(
    settings: CoreSettings,
    batch_id: str,
    *,
    ordinal: int,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.runs AS run
                SET immutable_input = jsonb_set(
                    run.immutable_input,
                    '{field_bindings}',
                    '{}'::jsonb
                )
                FROM research_batches.items AS item
                WHERE item.batch_id = %s AND item.ordinal = %s
                  AND run.id = item.research_run_id
                """,
                (batch_id, ordinal),
            )
        assert updated.rowcount == 1
    finally:
        database.close()


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT result_manifest_sha256, result_provenance
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        database.close()


def _stored_factor_summary(runtime, stored: dict[str, object]) -> object:
    bundle = runtime.publication.read(
        PublishedRef(
            manifest_sha256=str(stored["result_manifest_sha256"]),
            kind="research.result",
            provenance=stored["result_provenance"],
        )
    )
    return read_result_bundle(bundle, research_kind="factor_evaluation")["factor_summary"]


def _batch_attempt_status(settings: CoreSettings, batch_id: str) -> str:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status
                FROM research_batches.attempts
                WHERE batch_id = %s
                """,
                (batch_id,),
            ).fetchone()
        assert row is not None
        return str(row["status"])
    finally:
        database.close()


def _batch_pin_state(settings: CoreSettings, batch_id: str) -> tuple[int, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) FILTER (WHERE pin.status = 'active') AS active,
                       count(*) FILTER (WHERE pin.status = 'released') AS released
                FROM research_batches.attempts AS attempt
                JOIN data.generation_pins AS pin ON pin.id = attempt.generation_pin_id
                WHERE attempt.batch_id = %s
                """,
                (batch_id,),
            ).fetchone()
        assert row is not None
        return int(row["active"]), int(row["released"])
    finally:
        database.close()

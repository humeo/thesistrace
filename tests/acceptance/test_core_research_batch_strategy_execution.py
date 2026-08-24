from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_research_batch_admission import _publish_current_data, _strategy_command

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_batch.planning import (
    ResearchBatchCapacityError,
    validate_research_batch_capacity,
)
from thesistrace.research_run.models import StrategyBacktestAdmissionCommand
from thesistrace.research_run.result import read_result_bundle


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_reuses_shared_alpha_factor_and_matches_ordinary_runs(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        generation_id = _publish_current_data(settings)
        command = _strategy_command("strategy-sweep-equivalence")
        batch = client.post("/api/research-batches", json=command).json()
        ordinary = [
            client.post(
                "/api/research-runs",
                json=_ordinary_strategy_command(
                    f"ordinary-strategy-{ordinal}",
                    holdings_count=int(item["holdings_count"]),
                    rebalance_every_sessions=int(item["rebalance_every_sessions"]),
                ),
            ).json()
            for ordinal, item in enumerate(command["strategies"], start=1)
        ]
        runtime = client.app.state.core_runtime
        for run in ordinary:
            assert runtime.research_runs.process_next() is True
            assert client.get(f"/api/research-runs/{run['id']}").json()["status"] == (
                "succeeded"
            )

        assert runtime.research_batches.process_next(
            on_execution_event=events.append
        ) is True

        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["progress"] == {"completed_items": 2, "total_items": 2}
        for item, ordinary_run in zip(completed["items"], ordinary, strict=True):
            batch_stored = _stored_run(settings, str(item["research_run_id"]))
            ordinary_stored = _stored_run(settings, str(ordinary_run["id"]))
            assert canonical_json_bytes(
                _stored_result(runtime, batch_stored)
            ) == canonical_json_bytes(_stored_result(runtime, ordinary_stored))
            assert batch_stored["result_provenance"]["data_generation_id"] == (
                generation_id
            )
            assert batch_stored["result_provenance"]["research_run_id"] == (
                item["research_run_id"]
            )
            assert batch_stored["result_provenance"]["calculation_contracts"] == (
                ordinary_stored["result_provenance"]["calculation_contracts"]
            )
            assert batch_stored["result_provenance"]["semantic_versions"] == (
                ordinary_stored["result_provenance"]["semantic_versions"]
            )

        track = client.post(
            f"/api/research-runs/{completed['items'][0]['research_run_id']}/daily-tracks",
            json={"request_id": "batch-strategy-seed-track"},
        )
        assert track.status_code == 201
        assert track.json()["status"] == "active"

    prepared = [
        event
        for event in events
        if event["event"] == "research_batch_execution_batch_prepared"
    ]
    shared = [
        event
        for event in events
        if event["event"]
        == "research_batch_execution_shared_alpha_factor_succeeded"
    ]
    strategies = [
        event
        for event in events
        if event["event"] == "research_batch_execution_item_succeeded"
    ]
    assert len(prepared) == 1
    assert len(shared) == 1
    assert shared[0]["alpha_factor_task_started"] is True
    assert shared[0]["alpha_factor_task_completed"] is True
    assert [event["item_ordinal"] for event in strategies] == [1, 2]
    assert all(event["alpha_factor_task_started"] is False for event in strategies)
    assert all(event["strategy_task_started"] is True for event in strategies)
    assert all(event["strategy_task_completed"] is True for event in strategies)
    assert all(event["data_io"] == prepared[0]["data_io"] for event in strategies)
    assert max(
        int(event["child_peak_rss_bytes"])
        for event in events
        if "child_peak_rss_bytes" in event
    ) <= settings.research_execution_memory_bytes


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_shared_failure_fails_all_dependants_before_strategy(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-sweep-shared-failure"),
        ).json()
        _replace_item_json(settings, admitted["id"], 1, "field_bindings", {})

        assert client.app.state.core_runtime.research_batches.process_next(
            on_execution_event=events.append
        ) is True

        failed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert failed["status"] == "failed"
        assert [item["status"] for item in failed["items"]] == ["failed", "failed"]
        assert all(
            client.get(f"/api/research-runs/{item['research_run_id']}").json()[
                "failure_reason"
            ]
            == "Research calculation failed."
            for item in failed["items"]
        )

    shared_failure = next(
        event
        for event in events
        if event["event"] == "research_batch_execution_shared_alpha_factor_failed"
    )
    assert shared_failure["alpha_factor_task_failed"] is True
    assert shared_failure["strategy_task_started"] is False
    assert not any(event.get("strategy_task_started") is True for event in events)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_isolates_one_strategy_failure_and_keeps_order(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _strategy_command("strategy-sweep-item-failure")
        admitted = client.post(
            "/api/research-batches",
            json={
                **command,
                "strategies": [
                    command["strategies"][0],
                    command["strategies"][1],
                    {
                        "item_key": "later",
                        "holdings_count": 3,
                        "rebalance_every_sessions": 1,
                    },
                ],
            },
        ).json()
        _replace_nested_strategy_holdings(settings, admitted["id"], 2, 0)

        assert client.app.state.core_runtime.research_batches.process_next(
            on_execution_event=events.append
        ) is True

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "completed_with_failures"
        assert [item["status"] for item in completed["items"]] == [
            "succeeded",
            "failed",
            "succeeded",
        ]
        assert client.get(
            f"/api/research-runs/{completed['items'][2]['research_run_id']}"
        ).json()["result"] is not None

    item_events = [
        event
        for event in events
        if event["event"]
        in {
            "research_batch_execution_item_succeeded",
            "research_batch_execution_item_failed",
        }
    ]
    assert [event["item_ordinal"] for event in item_events] == [1, 2, 3]
    assert item_events[1]["strategy_task_failed"] is True
    assert item_events[2]["strategy_task_completed"] is True


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize("item_count", [1, 20])
def test_strategy_sweep_one_and_twenty_items_use_the_same_ordered_contract(
    tmp_path: Path,
    item_count: int,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _strategy_command(f"strategy-sweep-{item_count}")
        strategies = [
            {
                "item_key": f"strategy-{ordinal}",
                "holdings_count": ordinal,
                "rebalance_every_sessions": ordinal,
            }
            for ordinal in range(1, item_count + 1)
        ]
        admitted = client.post(
            "/api/research-batches",
            json={**command, "strategies": strategies},
        ).json()

        assert client.app.state.core_runtime.research_batches.process_next(
            on_execution_event=events.append
        ) is True

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["progress"] == {
            "completed_items": item_count,
            "total_items": item_count,
        }
        assert [item["item_key"] for item in completed["items"]] == [
            strategy["item_key"] for strategy in strategies
        ]

    shared_events = [
        event
        for event in events
        if event["event"]
        == "research_batch_execution_shared_alpha_factor_succeeded"
    ]
    strategy_events = [
        event
        for event in events
        if event["event"] == "research_batch_execution_item_succeeded"
    ]
    assert len(shared_events) == 1
    assert [event["item_ordinal"] for event in strategy_events] == list(
        range(1, item_count + 1)
    )
    assert all(event["alpha_factor_task_started"] is False for event in strategy_events)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_long_strategy_sweep_preserves_ordinary_result_partitions_and_equivalence(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    sessions = _business_sessions(505, ending=date(2026, 8, 4))
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings, sessions=sessions)
        command = _strategy_command("strategy-sweep-long-result")
        command = {
            **command,
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "strategies": [command["strategies"][0]],
        }
        batch = client.post("/api/research-batches", json=command).json()
        ordinary = client.post(
            "/api/research-runs",
            json=_ordinary_strategy_command(
                "ordinary-strategy-long-result",
                holdings_count=1,
                rebalance_every_sessions=1,
                start_date=sessions[0],
                end_date=sessions[-1],
            ),
        ).json()
        runtime = client.app.state.core_runtime

        assert runtime.research_runs.process_next() is True
        assert runtime.research_batches.process_next() is True

        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "succeeded"
        batch_stored = _stored_run(
            settings,
            str(completed["items"][0]["research_run_id"]),
        )
        ordinary_stored = _stored_run(settings, str(ordinary["id"]))
        batch_result = _stored_result(runtime, batch_stored)
        ordinary_result = _stored_result(runtime, ordinary_stored)
        assert len(batch_result["strategy_daily_observations"]) == 505
        assert canonical_json_bytes(batch_result) == canonical_json_bytes(ordinary_result)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_widest_admitted_multi_chunk_strategy_sweep_stays_inside_memory_budget(
    tmp_path: Path,
) -> None:
    _assert_widest_strategy_capacity_boundary(
        tmp_path,
        case="wide",
        memory_bytes=300 * 1024**2,
        sessions=_business_sessions(324, ending=date(2026, 8, 4)),
        instrument_count=512,
        formula="close",
        minimum_research_sessions=65,
    )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_high_work_small_chunk_strategy_sweep_prices_pending_overlap(
    tmp_path: Path,
) -> None:
    formula = " + ".join("ts_mean(close, 252)" for _ in range(16))
    _assert_widest_strategy_capacity_boundary(
        tmp_path,
        case="high-work",
        memory_bytes=512 * 1024**2,
        sessions=_business_sessions(400, ending=date(2026, 8, 4)),
        instrument_count=512,
        formula=formula,
        minimum_research_sessions=22,
    )


def _assert_widest_strategy_capacity_boundary(
    tmp_path: Path,
    *,
    case: str,
    memory_bytes: int,
    sessions: tuple[str, ...],
    instrument_count: int,
    formula: str,
    minimum_research_sessions: int,
) -> None:
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
            operation_id=f"strategy-sweep-{case}-widest-admitted",
            sessions=sessions,
            instrument_count=instrument_count,
        )
        command = _strategy_command(f"strategy-sweep-{case}-widest-admitted")
        runtime = client.app.state.core_runtime
        dataset = runtime.research_runs.current_admission_dataset()
        admitted_start_index: int | None = None
        effective_lookback = alpha_language.compile(formula).effective_lookback
        for start_index in range(effective_lookback, len(sessions)):
            start_session = sessions[start_index]
            prepared = runtime.research_runs.prepare_child_admission(
                StrategyBacktestAdmissionCommand.model_validate(
                    {
                        **_ordinary_strategy_command(
                            f"capacity-probe-{start_index}",
                            holdings_count=1,
                            rebalance_every_sessions=1,
                            start_date=start_session,
                            end_date=sessions[-1],
                            formula=formula,
                        ),
                        "universe": "top1000",
                    }
                ),
                dataset=dataset,
            )
            try:
                validate_research_batch_capacity("strategy_sweep", [prepared])
            except ResearchBatchCapacityError:
                continue
            admitted_start_index = start_index
            break
        assert admitted_start_index is not None
        assert admitted_start_index > effective_lookback
        assert len(sessions) - admitted_start_index >= minimum_research_sessions
        command = {
            **command,
            "start_date": sessions[admitted_start_index],
            "end_date": sessions[-1],
            "universe": "top1000",
            "alpha": {"formula": formula, "hypothesis": "capacity boundary"},
            "strategies": [command["strategies"][0]],
        }
        admitted = client.post("/api/research-batches", json=command)
        assert admitted.status_code == 202

        rejected = client.post(
            "/api/research-batches",
            json={
                **command,
                "request_id": f"strategy-sweep-{case}-one-session-too-wide",
                "start_date": sessions[admitted_start_index - 1],
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["issues"][0]["code"] == (
            "RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY"
        )

        assert client.app.state.core_runtime.research_batches.process_next(
            on_execution_event=events.append
        ) is True
        completed = client.get(
            f"/api/research-batches/{admitted.json()['id']}"
        ).json()
        assert completed["status"] == "succeeded"

    shared = next(
        event
        for event in events
        if event["event"]
        == "research_batch_execution_shared_alpha_factor_succeeded"
    )
    assert int(shared["shared_chunk_count"]) > 1
    assert int(shared["shared_artifact_bytes"]) <= int(
        shared["shared_artifact_capacity_bytes"]
    )
    assert max(
        int(event["child_peak_rss_bytes"])
        for event in events
        if "child_peak_rss_bytes" in event
    ) <= memory_bytes


def _ordinary_strategy_command(
    request_id: str,
    *,
    holdings_count: int,
    rebalance_every_sessions: int,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-04",
    formula: str = "close",
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": request_id,
        "start_date": start_date,
        "end_date": end_date,
        "formula": formula,
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "strategy_backtest",
        "holdings_count": holdings_count,
        "rebalance_every_sessions": rebalance_every_sessions,
    }


def _business_sessions(count: int, *, ending: date) -> tuple[str, ...]:
    sessions: list[str] = []
    current = ending
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current -= timedelta(days=1)
    return tuple(reversed(sessions))


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


def _stored_result(runtime, stored: dict[str, object]) -> dict[str, object]:
    bundle = runtime.publication.read(
        PublishedRef(
            manifest_sha256=str(stored["result_manifest_sha256"]),
            kind="research.result",
            provenance=stored["result_provenance"],
        )
    )
    return read_result_bundle(bundle, research_kind="strategy_backtest")


def _replace_item_json(
    settings: CoreSettings,
    batch_id: str,
    ordinal: int,
    field: str,
    value: object,
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
                    ARRAY[%s]::text[],
                    %s::jsonb
                )
                FROM research_batches.items AS item
                WHERE item.batch_id = %s AND item.ordinal = %s
                  AND run.id = item.research_run_id
                """,
                (field, canonical_json_bytes(value).decode(), batch_id, ordinal),
            )
        assert updated.rowcount == 1
    finally:
        database.close()


def _replace_nested_strategy_holdings(
    settings: CoreSettings,
    batch_id: str,
    ordinal: int,
    holdings_count: int,
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
                    '{strategy,holdings_count}',
                    to_jsonb(%s::integer)
                )
                FROM research_batches.items AS item
                WHERE item.batch_id = %s AND item.ordinal = %s
                  AND run.id = item.research_run_id
                """,
                (holdings_count, batch_id, ordinal),
            )
        assert updated.rowcount == 1
    finally:
        database.close()

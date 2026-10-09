import json
from copy import deepcopy
from dataclasses import replace

import anyio
import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, isolated_core_settings
from fastapi.testclient import TestClient
from test_core_research_agent_mcp_runs import _mcp_client
from test_core_research_batch_admission import SESSIONS, _publish_current_data, _strategy_command
from test_core_research_batch_factor_recovery import _expire_batch_attempt
from test_core_research_batch_strategy_execution import _stored_result, _stored_run
from test_python_direct_strategy import command as direct_command

from thesistrace.entrypoints.runtime import core_environment_is_configured
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_authoring import ResearchAuthoringService
from thesistrace.research_batch.execution import ResearchBatchChildLost

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(), reason="isolated Core runtime is not configured"
)


def command(request_id):
    sweep = _strategy_command(request_id)
    return {
        key: value
        for key, value in {
            **sweep,
            "batch_kind": "independent_strategies",
            "end_date": SESSIONS[4],
            "strategies": [
                {
                    **item,
                    "formula": "close" if index == 0 else "-close",
                    "neutralization": "industry" if index == 0 else "none",
                }
                for index, item in enumerate(sweep["strategies"])
            ],
        }.items()
        if key not in {"alpha", "neutralization"}
    }


def _processor(client, events=None):
    return client.app.state.core_runtime.research_batches.process_next(on_execution_event=events)


def test_independent_batch_atomically_admits_and_matches_formula_and_python_runs(tmp_path):
    settings = replace(isolated_core_settings(tmp_path), research_max_chunk_sessions=2)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        generation = _publish_current_data(settings, instrument_count=3)
        submitted = command("independent-mixed")
        python = direct_command("python", end=SESSIONS[4])
        python["program"]["source"] = """from quantgrove import Values

def compute(data, state):
    values = data.history("price.close.adjusted")
    state["days"] = state.get("days", 0) + len(data.sessions)
    return Values({"close": values})

""" + python["program"]["source"]
        submitted["strategies"].append(
            {
                **{
                    key: value
                    for key, value in python.items()
                    if key
                    not in {
                        "request_id",
                        "folder_id",
                        "research_kind",
                        "start_date",
                        "end_date",
                        "universe",
                    }
                },
                "item_key": "direct",
            }
        )
        submitted["strategies"].append(
            {
                "item_key": "framework",
                "initial_cash_cny": "200000",
                "holdings_count": 2,
                "selection_every_sessions": 1,
                "modules": {
                    "universe_selection": "dataset_universe/v1",
                    "alpha": {
                        "kind": "python",
                        "program": {
                            "source": """from quantgrove import Decision

def decide(data, account, state):
    state['days'] = state.get('days', 0) + 1
    return Decision({'reason': 'fresh_opportunities', 'signals': [
        {'instrument_id': item['instrument_id'], 'value': 1.0, 'valid_for_sessions': 2}
        for item in data.candidate_details
    ]})
"""
                        },
                    },
                    "portfolio_construction": "periodic_top_n/v1",
                    "risk_management": "no_risk/v1",
                },
            }
        )
        invalid = deepcopy(submitted)
        invalid["request_id"] = "invalid-independent"
        invalid["strategies"][1]["formula"] = "unknown_field"
        rejected = client.post("/api/research-batches", json=invalid)
        assert rejected.status_code == 422, rejected.text
        assert any(issue["item_key"] == "broad" for issue in rejected.json()["issues"])
        assert client.get("/api/research-batches").json()["items"] == []

        response = client.post("/api/research-batches", json=submitted)
        assert response.status_code == 202, response.text
        batch = response.json()
        assert client.post("/api/research-batches", json=submitted).json() == batch
        assert batch["scope"]["neutralization"] is None
        ordinary = []
        for index, item in enumerate(submitted["strategies"]):
            single = {
                **{key: submitted[key] for key in ("start_date", "end_date", "universe")},
                **{key: value for key, value in item.items() if key != "item_key"},
                "request_id": f"ordinary-{index}",
                "research_kind": "strategy_backtest",
                "folder_id": "folder_default",
            }
            response = client.post("/api/research-runs", json=single)
            assert response.status_code == 202, response.text
            ordinary.append(response.json())
        runtime = client.app.state.core_runtime
        for run in ordinary:
            assert runtime.research_runs.process_next()
            detail = client.get(f"/api/research-runs/{run['id']}").json()
            assert detail["status"] == "succeeded", str(detail)
        progress = []

        def observe(event):
            if event.get("event") == "research_batch_execution_item_strategy_chunk_succeeded":
                progress.append(
                    [
                        client.get(f"/api/research-runs/{item['research_run_id']}").json()[
                            "progress"
                        ]
                        for item in batch["items"]
                    ]
                )

        assert _processor(client, observe)
        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "succeeded", completed
        assert completed["progress"] == {"completed_strategy_tasks": 4, "total_strategy_tasks": 4}
        assert any(
            all(item["completed_research_sessions"] >= 2 for item in row) for row in progress
        )
        assert not any(item["phase"] == "waiting_for_execution" for row in progress for item in row)
        for item, solo in zip(completed["items"], ordinary, strict=True):
            actual = _stored_run(settings, item["research_run_id"])
            expected = _stored_run(settings, solo["id"])
            assert actual["key_metrics"] == expected["key_metrics"]
            assert actual["result_provenance"]["data_generation_id"] == generation
            assert canonical_json_bytes(_stored_result(runtime, actual)) == canonical_json_bytes(
                _stored_result(runtime, expected)
            )


@pytest.mark.parametrize("interrupt_after_completion", [False, True])
def test_independent_batch_retries_only_incomplete_strategies(tmp_path, interrupt_after_completion):
    settings = replace(isolated_core_settings(tmp_path), research_max_chunk_sessions=2)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings, instrument_count=3)
        batch = client.post("/api/research-batches", json=command("recover")).json()
        events = []

        def interrupt(event):
            events.append(event)
            if (
                event.get("event") == "research_batch_execution_item_strategy_chunk_succeeded"
                and event.get("item_ordinal") == 2
                and (
                    not interrupt_after_completion
                    or event.get("completed_research_sessions")
                    == event.get("total_research_sessions")
                )
            ):
                raise ResearchBatchChildLost("injected interruption after shared-window work")

        assert _processor(client, interrupt)
        interrupted = client.get(f"/api/research-batches/{batch['id']}").json()
        assert interrupted["status"] == "queued", interrupted
        assert interrupted["progress"]["completed_strategy_tasks"] == int(
            interrupt_after_completion
        )
        retry_events = []
        assert _processor(client, retry_events.append)
        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "succeeded", completed
        assert [item["task_attempt_count"] for item in completed["items"]] == (
            [1, 2] if interrupt_after_completion else [2, 2]
        )
        started = [
            e["item_ordinal"]
            for e in retry_events
            if e.get("event") == "research_batch_execution_item_started"
        ]
        assert started == ([2] if interrupt_after_completion else [1, 2])


def test_independent_batch_isolates_program_failure_and_cancels_remaining_items(tmp_path):
    settings = replace(isolated_core_settings(tmp_path), research_max_chunk_sessions=2)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings, instrument_count=3)
        submitted = command("partial-failure")
        python = direct_command("fail", end=SESSIONS[4], parameters={"fail_session": SESSIONS[1]})
        submitted["strategies"].insert(
            1,
            {
                "item_key": "failing",
                "strategy_mode": "direct",
                "initial_cash_cny": python["initial_cash_cny"],
                "program": python["program"],
            },
        )
        batch = client.post("/api/research-batches", json=submitted).json()
        assert _processor(client)
        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "completed_with_failures", completed
        assert [item["status"] for item in completed["items"]] == [
            "succeeded",
            "failed",
            "succeeded",
        ]
        assert completed["items"][1]["diagnostic"] is not None

        batch = client.post("/api/research-batches", json=command("cancel-active")).json()
        cancelled = False

        def cancel(event):
            nonlocal cancelled
            if (
                not cancelled
                and event.get("event") == "research_batch_execution_item_strategy_chunk_succeeded"
            ):
                cancelled = True
                response = client.post(
                    f"/api/research-batches/{batch['id']}/cancel", json={"request_id": "cancel"}
                )
                assert response.status_code in {200, 202}, response.text

        assert _processor(client, cancel)
        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "cancelled", completed
        assert all(item["status"] == "cancelled" for item in completed["items"])


@pytest.mark.parametrize("after_completion", [False, True])
def test_independent_batch_recovers_all_expired_tasks_after_worker_loss(tmp_path, after_completion):
    settings = replace(isolated_core_settings(tmp_path), research_max_chunk_sessions=2)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        batch = client.post("/api/research-batches", json=command("worker-loss")).json()

        def worker_lost(event):
            if (
                event.get("event") == "research_batch_execution_item_strategy_chunk_succeeded"
                and event.get("item_ordinal") == 2
                and (not after_completion or event["completed_research_sessions"]
                     == event["total_research_sessions"])
            ):
                # Bypass the ordinary classified child-error handler, as an abrupt
                # Worker exit does; durable recovery must close every active task.
                raise SystemExit("injected Worker loss")

        with pytest.raises(SystemExit, match="injected Worker loss"):
            _processor(client, worker_lost)
        interrupted = client.get(f"/api/research-batches/{batch['id']}").json()
        assert interrupted["status"] == "running", interrupted
        _expire_batch_attempt(client.app.state.core_runtime, interrupted["attempt"]["id"])
        assert _processor(client)
        recovered = client.get(f"/api/research-batches/{batch['id']}").json()
        assert recovered["status"] == "succeeded", recovered
        assert [item["task_attempt_count"] for item in recovered["items"]] == (
            [1, 2] if after_completion else [2, 2]
        )


def test_independent_batch_mcp_submits_vectorized_python_and_reads_each_result(tmp_path):
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings, instrument_count=3)
        submitted = json.loads(
            ResearchAuthoringService().reference("workflow", "batches").entry.examples[1].source
        )
        # Keep the documented mixed-mode program; the small fixture needs no warmup formula.
        submitted.update(start_date=SESSIONS[0], end_date=SESSIONS[4])
        submitted["strategies"][0].update(formula="close", holdings_count=2)

        async def exercise():
            async with _mcp_client(settings, tmp_path / "independent-mcp.stderr.log") as mcp:
                response = await mcp.call_tool("submit_research_batch", submitted)
                assert response.is_error is False, response
                receipt = response.structured_content
                assert receipt["outcome"] == "accepted"
                assert receipt["next_tool"] == "get_research_batch"
                assert await anyio.to_thread.run_sync(_processor, client)
                detail = await mcp.call_tool(
                    "get_research_batch", {"batch_id": receipt["batch_id"]}
                )
                assert detail.is_error is False, detail
                assert detail.structured_content["status"] == "succeeded", detail
                for item in detail.structured_content["items"]:
                    result = await mcp.call_tool("get_research_run_result", {
                        "run_id": item["research_run_id"], "section": "strategy_summary",
                    })
                    assert result.is_error is False, result

        anyio.run(exercise)

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import anyio
import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row
from test_core_current_head_research_run_execution import _stored_execution
from test_core_current_head_research_run_retry import (
    _install_transient_result_publication_failure,
    _remove_transient_result_publication_failure,
)
from test_core_daily_track_detail import _business_sessions, _publish_head, _run_worker_once
from test_core_research_agent_mcp_runs import _mcp_client

from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication import PublishedRef
from thesistrace.research_run.factor_result import read_factor_daily_partition


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
def test_factor_daily_checkpoint_is_published_and_reused_after_result_failure(
    tmp_path: Path,
):
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "data",
        benchmark_mount=tmp_path / "benchmark",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=45)
    _publish_head(settings, sessions=sessions, expected_manifest=None, operation_id="factor-daily")
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json={
                "request_id": "factor-daily",
                "folder_id": "folder_default",
                "name": "Daily Factor evidence",
                "formula": "close",
                "start_date": sessions[0],
                "end_date": sessions[4],
                "universe": "top300",
                "neutralization": "none",
                "research_kind": "factor_evaluation",
            },
        )
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["id"]
        _install_transient_result_publication_failure(settings)
        try:
            completed = _run_worker_once(settings, "research")
            (tmp_path / "research-worker.stdout").write_text(completed.stdout)
            (tmp_path / "research-worker.stderr").write_text(completed.stderr)
            assert completed.returncode == 0, completed.stderr
        finally:
            _remove_transient_result_publication_failure(settings)
        after_worker = client.get(f"/api/research-runs/{run_id}").json()
        assert after_worker["status"] == "running", (
            after_worker,
            _stored_execution(settings, run_id),
        )
        with connect(settings.database_url, row_factory=dict_row) as connection:
            checkpoints = connection.execute(
                """SELECT checkpoint.ordinal, checkpoint.checkpoint_manifest_sha256,
                          checkpoint.factor_observation_payload, manifest.manifest_bytes
                   FROM research_runs.execution_checkpoints AS checkpoint
                   JOIN publication.manifests AS manifest
                     ON manifest.sha256 = checkpoint.checkpoint_manifest_sha256
                   WHERE checkpoint.run_id = %s ORDER BY checkpoint.ordinal""",
                (run_id,),
            ).fetchall()
        assert checkpoints
        observed = []
        publication = client.app.state.core_runtime.publication
        for checkpoint in checkpoints:
            if checkpoint["factor_observation_payload"] is None:
                continue
            bundle = publication.read(
                PublishedRef(
                    manifest_sha256=checkpoint["checkpoint_manifest_sha256"],
                    kind="research.execution-checkpoint",
                    provenance=json.loads(bytes(checkpoint["manifest_bytes"]))["provenance"],
                )
            )
            observed.extend(
                read_factor_daily_partition(bundle.payloads["factor_daily_observations"].content)
            )
        assert len(observed) == 15
        for horizon in (1, 5, 20):
            daily = [row for row in observed if row["horizon"] == horizon]
            assert [row["session"] for row in daily] == list(sessions[:5])
            assert sum(
                row["label_status"] == "right_censored_by_research_period_end" for row in daily
            ) == min(5, horizon + 1)
            assert daily[-1]["label_exit_session"] is None
        events = []
        assert client.app.state.core_runtime.research_runs.process_next(
            on_execution_event=events.append
        )
        assert any(event.get("resumed_from_checkpoint") is True for event in events)
        assert any(event.get("reused_checkpoint") is True for event in events)
        stored = _stored_execution(settings, run_id)
        assert stored["status"] == "succeeded", stored
        result = publication.read(
            PublishedRef(
                manifest_sha256=str(stored["result_manifest_sha256"]),
                kind="research.result",
                provenance=stored["result_provenance"],
            )
        )
        descriptor = json.loads(result.payloads["factor_daily_observations"].content)
        retained = [
            row
            for part in descriptor["partitions"]
            for row in read_factor_daily_partition(result.payloads[part["name"]].content)
        ]
        assert retained == observed
        periods = json.loads(result.payloads["factor_period_statistics"].content)
        full = [row for row in periods if row["granularity"] == "all"]
        assert len(full) == 3
        assert all(row["coverage"]["signal_session_count"] == 5 for row in full)
        assert all(row["summary"]["ic"]["mean"] is None for row in full)
        detail = client.get(f"/api/research-runs/{run_id}")
        assert detail.status_code == 200, detail.text
        assert (
            detail.json()["result"]["factor"]["horizons"]["1"]["coverage"]["signal_session_count"]
            == 5
        )
        batch = client.post(
            "/api/research-batches",
            json={
                "request_id": "factor-daily-batch",
                "batch_kind": "factor_evaluation",
                "start_date": sessions[0],
                "end_date": sessions[4],
                "universe": "top300",
                "neutralization": "none",
                "factors": [
                    {"item_key": "close", "name": "Close", "formula": "close"},
                    {"item_key": "rank", "name": "Rank", "formula": "rank(close)"},
                ],
            },
        )
        assert batch.status_code == 202, batch.text
        assert client.app.state.core_runtime.research_batches.process_next()
        batch_detail = client.get(f"/api/research-batches/{batch.json()['id']}").json()
        assert all(item["outcome"] == "succeeded" for item in batch_detail["items"]), batch_detail
        for item in batch_detail["items"]:
            item_id = item["research_run_id"]
            item_detail = client.get(f"/api/research-runs/{item_id}")
            assert item_detail.status_code == 200, item_detail.text
            with connect(settings.database_url, row_factory=dict_row) as connection:
                item_stored = connection.execute(
                    """SELECT result_manifest_sha256, result_provenance
                       FROM research_runs.runs WHERE id = %s""",
                    (item_id,),
                ).fetchone()
            assert item_stored is not None
            item_result = publication.read(
                PublishedRef(
                    manifest_sha256=str(item_stored["result_manifest_sha256"]),
                    kind="research.result",
                    provenance=item_stored["result_provenance"],
                )
            )
            directory = json.loads(item_result.payloads["factor_daily_observations"].content)
            item_rows = [
                row
                for part in directory["partitions"]
                for row in read_factor_daily_partition(item_result.payloads[part["name"]].content)
            ]
            assert len(item_rows) == 15
            for horizon in (1, 5, 20):
                assert [row["session"] for row in item_rows if row["horizon"] == horizon] == list(
                    sessions[:5]
                )
            assert "factor_period_statistics" in item_result.payloads
        page = client.get(
            f"/api/research-runs/{run_id}/factor-observations",
            params={
                "horizon": 5,
                "limit": 2,
                "start_session": sessions[1],
            },
        )
        assert page.status_code == 200, page.text
        assert [row["session"] for row in page.json()["items"]] == list(sessions[1:3])
        cursor = page.json()["next_cursor"]
        assert cursor
        continued = client.get(
            f"/api/research-runs/{run_id}/factor-observations",
            params={
                "horizon": 5,
                "limit": 2,
                "start_session": sessions[1],
                "cursor": cursor,
            },
        )
        assert continued.status_code == 200, continued.text
        assert [row["session"] for row in continued.json()["items"]] == list(sessions[3:5])
        assert continued.json()["next_cursor"] is None
        for changed in ({"horizon": 20}, {"start_session": sessions[0]}):
            rejected = client.get(
                f"/api/research-runs/{run_id}/factor-observations",
                params={
                    "horizon": 5,
                    "start_session": sessions[1],
                    "cursor": cursor,
                    **changed,
                },
            )
            assert rejected.status_code == 400, rejected.text
        invalid = client.get(
            f"/api/research-runs/{run_id}/factor-observations",
            params={
                "horizon": 5,
                "start_session": "2026-02-30",
            },
        )
        assert invalid.status_code == 422

        for granularity in ("all", "year", "month"):
            period_page = client.get(
                f"/api/research-runs/{run_id}/factor-periods",
                params={
                    "horizon": 5,
                    "granularity": granularity,
                },
            )
            assert period_page.status_code == 200, period_page.text
            period = period_page.json()["items"][0]
            assert period["coverage"]["signal_session_count"] == 5
            assert period["coverage"]["right_censored_session_count"] == 5
            assert period["summary"]["rank_ic"]["mean"] is None
            assert period_page.json()["return_basis"] == "forward_open_labels_before_costs"
            assert period_page.json()["next_cursor"] is None
        invalid_period = client.get(
            f"/api/research-runs/{run_id}/factor-periods",
            params={
                "horizon": 5,
                "granularity": "week",
            },
        )
        assert invalid_period.status_code == 422
        long_run = client.post(
            "/api/research-runs",
            json={
                "request_id": "factor-mcp-months",
                "folder_id": "folder_default",
                "name": "Factor calendar pages",
                "formula": "close",
                "start_date": sessions[0],
                "end_date": sessions[-1],
                "universe": "top300",
                "neutralization": "none",
                "research_kind": "factor_evaluation",
            },
        )
        assert long_run.status_code == 202, long_run.text
        assert client.app.state.core_runtime.research_runs.process_next()
        long_id = long_run.json()["id"]
        expected_months = client.get(
            f"/api/research-runs/{long_id}/factor-periods",
            params={
                "horizon": 5,
                "granularity": "month",
            },
        )
        assert expected_months.status_code == 200, expected_months.text
        assert len(expected_months.json()["items"]) >= 2
        anyio.run(
            _check_native_factor_evidence,
            settings,
            tmp_path,
            run_id,
            long_id,
            page.json()["items"],
            expected_months.json()["items"],
        )


async def _check_native_factor_evidence(
    settings, tmp_path, run_id, long_id, expected_daily, expected_months
):
    async with _mcp_client(settings, tmp_path / "factor-evidence-mcp.stderr") as mcp:
        discovered = await mcp.list_tools()
        assert "get_research_run_result" in {tool.name for tool in discovered.tools}
        daily_query = {
            "run_id": run_id,
            "section": "factor_observations",
            "horizon": 5,
            "start_session": expected_daily[0]["session"],
            "limit": 2,
        }
        daily = await mcp.call_tool("get_research_run_result", daily_query)
        assert not daily.is_error, daily
        assert daily.structured_content["items"] == expected_daily
        cursor = daily.structured_content["next_cursor"]
        assert cursor
        for changed in (
            {"horizon": 20},
            {"run_id": long_id},
            {"cursor": cursor[:10] + ("a" if cursor[10] != "a" else "b") + cursor[11:]},
        ):
            rejected = await mcp.call_tool(
                "get_research_run_result",
                {
                    **daily_query,
                    "cursor": cursor,
                    **changed,
                },
            )
            assert rejected.is_error
            assert rejected.structured_content["code"] == "INVALID_INPUT"
        query = {
            "run_id": long_id,
            "section": "factor_periods",
            "horizon": 5,
            "granularity": "month",
            "limit": 1,
        }
        periods = []
        first_cursor = None
        for _ in range(len(expected_months) + 1):
            result = await mcp.call_tool("get_research_run_result", query)
            assert not result.is_error, result
            periods.extend(result.structured_content["items"])
            next_cursor = result.structured_content["next_cursor"]
            if first_cursor is None:
                first_cursor = next_cursor
            if next_cursor is None:
                break
            query = {**query, "cursor": next_cursor}
        assert periods == expected_months
        assert first_cursor
        changed = await mcp.call_tool(
            "get_research_run_result",
            {
                **query,
                "granularity": "year",
                "cursor": first_cursor,
            },
        )
        assert changed.is_error
        assert changed.structured_content["code"] == "INVALID_INPUT"
    async with _mcp_client(
        settings,
        tmp_path / "factor-other-owner.stderr",
        environment={
            "THESISTRACE_RESEARCH_AGENT_RESEARCHER_ID": "018f6f7e-8342-7c9a-a4df-9a86147d2999",
        },
    ) as other:
        denied = await other.call_tool("get_research_run_result", daily_query)
        assert denied.is_error
        assert denied.structured_content["code"] == "NOT_FOUND"

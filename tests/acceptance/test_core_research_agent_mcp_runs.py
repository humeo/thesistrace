from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from base64 import urlsafe_b64decode
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from multiprocessing import get_context
from pathlib import Path

import anyio
import boto3
import pytest
from core_runtime import drop_product_schemas, isolated_core_settings
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import TypeAdapter

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.canonical_mapping import field_catalog
from thesistrace.entrypoints.research_agent_mcp import (
    RESEARCH_CANCEL_ENABLE_ENVIRONMENT,
)
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.research_run.execution import SupervisedResearchExecutor
from thesistrace.research_run.models import (
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionRejectedOutcome,
)
from thesistrace.research_run.service import ResearchRunService


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_stdio_research_runs_survive_disconnect_and_real_worker_restarts(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path / "data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    try:
        sessions = _publish_current_data(settings)
        _assert_concurrent_rejection_receipt(settings)
        anyio.run(_exercise_research_runs, settings, tmp_path, sessions[54])
    finally:
        drop_product_schemas(settings)


async def _exercise_research_runs(
    settings: CoreSettings,
    tmp_path: Path,
    long_strategy_end: str,
) -> None:
    factor_command = _command("mcp-factor", research_kind="factor_evaluation")
    strategy_command = {
        **_command("mcp-strategy", research_kind="strategy_backtest"),
        "end_date": long_strategy_end,
        "holdings_count": 51,
    }
    rejected_command = {**_command("mcp-rejected"), "formula": "unknown_alpha"}

    first_log = tmp_path / "mcp-first.stderr.log"
    async with _mcp_client(settings, first_log) as client:
        discovered = await client.list_tools()
        tool_names = {tool.name for tool in discovered.tools}
        assert {"list_research_runs", "get_research_run", "submit_research_run"} <= (
            tool_names
        )
        assert "cancel_research_run" not in tool_names
        assert all("retry" not in name and "delete" not in name for name in tool_names)

        factor = await client.call_tool("submit_research_run", factor_command)
        strategy = await client.call_tool("submit_research_run", strategy_command)
        rejected = await client.call_tool("submit_research_run", rejected_command)
        assert factor.is_error is False
        assert strategy.is_error is False
        assert rejected.is_error is False
        assert factor.structured_content == {
            "outcome": "accepted",
            "run_id": factor.structured_content["run_id"],
            "status": "queued",
            "replayed": False,
            "retry_after_seconds": 2,
        }
        assert strategy.structured_content["outcome"] == "accepted"
        assert strategy.structured_content["replayed"] is False
        assert rejected.structured_content["outcome"] == "rejected"
        assert rejected.structured_content["issues"][0]["code"] == "UNKNOWN_IDENTIFIER"
        assert rejected.structured_content["replayed"] is False

        queued = await client.call_tool(
            "get_research_run",
            {"run_id": factor.structured_content["run_id"]},
        )
        assert queued.is_error is False
        assert queued.structured_content["status"] == "queued"
        assert queued.structured_content["input"]["formula"] == "close"
        assert queued.structured_content["result_available"] is False
        assert queued.structured_content["retry_after_seconds"] == 2
        _assert_compact_polling_payload(queued.structured_content)
        unavailable_result = await client.call_tool(
            "get_research_run_result",
            {"run_id": factor.structured_content["run_id"], "section": "factor"},
        )
        assert unavailable_result.is_error is True
        assert unavailable_result.structured_content["code"] == "STATE_CONFLICT"

    first_worker = await anyio.to_thread.run_sync(_run_worker_once, settings)
    second_worker = await anyio.to_thread.run_sync(_run_worker_once, settings)
    _assert_worker_succeeded(first_worker)
    _assert_worker_succeeded(second_worker)

    second_log = tmp_path / "mcp-second.stderr.log"
    async with _mcp_client(settings, second_log) as client:
        factor_replay = await client.call_tool("submit_research_run", factor_command)
        strategy_replay = await client.call_tool("submit_research_run", strategy_command)
        rejected_replay = await client.call_tool("submit_research_run", rejected_command)
        conflict = await client.call_tool(
            "submit_research_run",
            {**rejected_command, "formula": "close"},
        )

        assert factor_replay.structured_content["run_id"] == factor.structured_content["run_id"]
        assert strategy_replay.structured_content["run_id"] == (
            strategy.structured_content["run_id"]
        )
        assert factor_replay.structured_content["status"] == "succeeded"
        assert strategy_replay.structured_content["status"] == "succeeded"
        assert factor_replay.structured_content["replayed"] is True
        assert strategy_replay.structured_content["replayed"] is True
        assert factor_replay.structured_content["retry_after_seconds"] is None
        assert rejected_replay.structured_content["outcome"] == "rejected"
        assert rejected_replay.structured_content["replayed"] is True
        assert conflict.is_error is True
        assert conflict.structured_content["code"] == "IDEMPOTENCY_CONFLICT"
        assert conflict.structured_content["retryable"] is False

        factor_detail = await _poll_terminal(
            client,
            str(factor.structured_content["run_id"]),
        )
        strategy_detail = await _poll_terminal(
            client,
            str(strategy.structured_content["run_id"]),
        )
        assert factor_detail["result_available"] is True
        assert factor_detail["available_result_sections"] == ["factor", "provenance"]
        assert strategy_detail["result_available"] is True
        assert strategy_detail["available_result_sections"] == [
            "factor",
            "strategy_summary",
            "strategy_observations",
            "terminal_strategy_state",
            "terminal_positions",
            "provenance",
        ]
        assert factor_detail["retry_after_seconds"] is None
        assert strategy_detail["retry_after_seconds"] is None
        _assert_compact_polling_payload(factor_detail)
        _assert_compact_polling_payload(strategy_detail)

        (
            observation_page,
            position_page,
            strategy_summary,
            terminal_state,
        ) = await _assert_first_semantic_result_pages(
            client,
            factor_run_id=str(factor.structured_content["run_id"]),
            strategy_run_id=str(strategy.structured_content["run_id"]),
            strategy_command=strategy_command,
        )
        observation_cursor = observation_page["next_cursor"]
        position_cursor = position_page["next_cursor"]
        assert isinstance(observation_cursor, str)
        assert isinstance(position_cursor, str)

        first_page = await client.call_tool("list_research_runs", {"limit": 1})
        assert first_page.is_error is False
        assert len(first_page.structured_content["items"]) == 1
        cursor = first_page.structured_content["next_cursor"]
        assert isinstance(cursor, str)
        second_page = await client.call_tool(
            "list_research_runs",
            {"limit": 1, "cursor": cursor},
        )
        assert second_page.is_error is False
        assert second_page.structured_content["items"][0]["id"] != (
            first_page.structured_content["items"][0]["id"]
        )
        wrong_filter = await client.call_tool(
            "list_research_runs",
            {
                "limit": 1,
                "cursor": cursor,
                "research_kind": "factor_evaluation",
            },
        )
        assert wrong_filter.is_error is True
        assert wrong_filter.structured_content["code"] == "INVALID_INPUT"

        missing = await client.call_tool(
            "get_research_run",
            {"run_id": "run_missing"},
        )
        assert missing.is_error is True
        assert missing.structured_content["code"] == "NOT_FOUND"

        recovery = await client.call_tool(
            "submit_research_run",
            _command("mcp-worker-recovery", research_kind="strategy_backtest"),
        )
        assert recovery.is_error is False
        assert recovery.structured_content["status"] == "queued"

    _assert_polling_does_not_read_result(
        settings,
        str(factor.structured_content["run_id"]),
    )
    lost_worker = await anyio.to_thread.run_sync(_run_worker_lost_after_claim, settings)
    assert lost_worker.returncode == 17, {
        "stdout": lost_worker.stdout[-4096:],
        "stderr": lost_worker.stderr[-4096:],
    }
    _expire_active_attempt(settings, str(recovery.structured_content["run_id"]))
    replacement_worker = await anyio.to_thread.run_sync(_run_worker_once, settings)
    _assert_worker_succeeded(replacement_worker)

    await anyio.to_thread.run_sync(_seed_pagination_runs, settings, 48)
    third_log = tmp_path / "mcp-third.stderr.log"
    async with _mcp_client(settings, third_log) as client:
        recovered = await _poll_terminal(
            client,
            str(recovery.structured_content["run_id"]),
        )
        assert recovered["status"] == "succeeded"

        observation_tail = await client.call_tool(
            "get_research_run_result",
            {
                "run_id": strategy.structured_content["run_id"],
                "section": "strategy_observations",
                "limit": 50,
                "cursor": observation_cursor,
            },
        )
        assert observation_tail.is_error is False
        assert len(observation_tail.structured_content["items"]) == 5
        assert observation_tail.structured_content["next_cursor"] is None
        observation_sessions = [
            item["session"]
            for item in observation_page["items"] + observation_tail.structured_content["items"]
        ]
        assert len(observation_sessions) == len(set(observation_sessions)) == 55
        assert observation_sessions == sorted(observation_sessions)
        last_observation = observation_tail.structured_content["items"][-1]
        assert terminal_state["session"] == last_observation["session"]
        assert terminal_state["net_nav"] == last_observation["net_nav"]
        assert terminal_state["benchmark_nav"] == last_observation["benchmark_nav"]
        initial_cash = Decimal(strategy_summary["initial_cash_cny"])
        assert math.isclose(
            strategy_summary["comparison"]["net_cumulative_return"],
            float(Decimal(last_observation["net_nav"]) / initial_cash - Decimal(1)),
            rel_tol=0,
            abs_tol=1e-12,
        )
        assert math.isclose(
            strategy_summary["comparison"]["benchmark_cumulative_return"],
            float(Decimal(last_observation["benchmark_nav"]) - Decimal(1)),
            rel_tol=0,
            abs_tol=1e-12,
        )

        position_tail = await client.call_tool(
            "get_research_run_result",
            {
                "run_id": strategy.structured_content["run_id"],
                "section": "terminal_positions",
                "limit": 50,
                "cursor": position_cursor,
            },
        )
        assert position_tail.is_error is False
        assert len(position_tail.structured_content["items"]) == 1
        assert position_tail.structured_content["next_cursor"] is None
        instrument_ids = [
            item["instrument_id"]
            for item in position_page["items"] + position_tail.structured_content["items"]
        ]
        assert len(instrument_ids) == len(set(instrument_ids)) == 51
        assert instrument_ids == sorted(instrument_ids)

        wrong_section_cursor = await client.call_tool(
            "get_research_run_result",
            {
                "run_id": strategy.structured_content["run_id"],
                "section": "terminal_positions",
                "cursor": observation_cursor,
            },
        )
        assert wrong_section_cursor.is_error is True
        assert wrong_section_cursor.structured_content["code"] == "INVALID_INPUT"
        wrong_run_cursor = await client.call_tool(
            "get_research_run_result",
            {
                "run_id": recovery.structured_content["run_id"],
                "section": "strategy_observations",
                "cursor": observation_cursor,
            },
        )
        assert wrong_run_cursor.is_error is True
        assert wrong_run_cursor.structured_content["code"] == "INVALID_INPUT"
        tampered_result_cursor = await client.call_tool(
            "get_research_run_result",
            {
                "run_id": strategy.structured_content["run_id"],
                "section": "strategy_observations",
                "cursor": _tamper_cursor(observation_cursor),
            },
        )
        assert tampered_result_cursor.is_error is True
        assert tampered_result_cursor.structured_content["code"] == "INVALID_INPUT"

        default_page = await client.call_tool("list_research_runs", {})
        assert default_page.is_error is False
        assert len(default_page.structured_content["items"]) == 20
        assert isinstance(default_page.structured_content["next_cursor"], str)

        first_fifty = await client.call_tool("list_research_runs", {"limit": 50})
        assert first_fifty.is_error is False
        assert len(first_fifty.structured_content["items"]) == 50
        stable_cursor = first_fifty.structured_content["next_cursor"]
        assert isinstance(stable_cursor, str)
        first_ids = [item["id"] for item in first_fifty.structured_content["items"]]
        assert first_ids == sorted(first_ids)
        decoded_cursor = urlsafe_b64decode(stable_cursor)
        assert b"created_at" not in decoded_cursor
        assert b"folder_id" not in decoded_cursor
        assert all(run_id.encode() not in decoded_cursor for run_id in first_ids)

        invalid_limit = await client.call_tool("list_research_runs", {"limit": 51})
        assert invalid_limit.is_error is True
        assert invalid_limit.structured_content["code"] == "INVALID_INPUT"
        tampered_cursor = _tamper_cursor(stable_cursor)
        tampered = await client.call_tool(
            "list_research_runs",
            {"limit": 50, "cursor": tampered_cursor},
        )
        assert tampered.is_error is True
        assert tampered.structured_content["code"] == "INVALID_INPUT"

    fourth_log = tmp_path / "mcp-fourth.stderr.log"
    async with _mcp_client(settings, fourth_log) as client:
        final_page = await client.call_tool(
            "list_research_runs",
            {"limit": 50, "cursor": stable_cursor},
        )
        assert final_page.is_error is False
        assert len(final_page.structured_content["items"]) == 1
        final_ids = [item["id"] for item in final_page.structured_content["items"]]
        assert len(set(first_ids + final_ids)) == 51
        assert first_ids + final_ids == sorted(first_ids + final_ids)
        assert final_page.structured_content["next_cursor"] is None

        wrong_filter_after_restart = await client.call_tool(
            "list_research_runs",
            {
                "limit": 50,
                "cursor": stable_cursor,
                "research_kind": "factor_evaluation",
            },
        )
        assert wrong_filter_after_restart.is_error is True
        assert wrong_filter_after_restart.structured_content["code"] == "INVALID_INPUT"

        cancel_target = await client.call_tool(
            "submit_research_run",
            _command("mcp-cancel-target", research_kind="factor_evaluation"),
        )
        conflict_target = await client.call_tool(
            "submit_research_run",
            _command("mcp-cancel-conflict-target", research_kind="factor_evaluation"),
        )
        denied_cancel = await client.call_tool(
            "cancel_research_run",
            {
                "run_id": cancel_target.structured_content["run_id"],
                "request_id": "mcp-cancel-request",
            },
        )
        assert denied_cancel.is_error is True
        assert denied_cancel.structured_content["code"] == "FORBIDDEN"
        still_queued = await client.call_tool(
            "get_research_run",
            {"run_id": cancel_target.structured_content["run_id"]},
        )
        assert still_queued.structured_content["status"] == "queued"

    _prioritize_run_for_worker(
        settings,
        str(cancel_target.structured_content["run_id"]),
    )
    process_context = get_context("spawn")
    prepared = process_context.Event()
    release_worker = process_context.Event()
    worker_process = process_context.Process(
        target=_run_barrier_worker,
        args=(settings, prepared, release_worker),
    )
    worker_process.start()
    try:
        assert await anyio.to_thread.run_sync(prepared.wait, 20)

        fifth_log = tmp_path / "mcp-fifth-cancel-enabled.stderr.log"
        async with _mcp_client(
            settings,
            fifth_log,
            enable_research_cancel=True,
        ) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            cancel_tool = tools["cancel_research_run"]
            assert cancel_tool.annotations is not None
            assert cancel_tool.annotations.read_only_hint is False
            assert cancel_tool.annotations.destructive_hint is True
            assert cancel_tool.annotations.idempotent_hint is True
            assert cancel_tool.annotations.open_world_hint is False

            rejected_confirmation = await client.call_tool(
                "cancel_research_run",
                {
                    "run_id": cancel_target.structured_content["run_id"],
                    "request_id": "mcp-cancel-request",
                    "confirmation_token": "host-confirmation-is-not-authority",
                },
            )
            assert rejected_confirmation.is_error is True
            assert rejected_confirmation.structured_content["code"] == "INVALID_INPUT"

            missing_cancel = await client.call_tool(
                "cancel_research_run",
                {"run_id": "run_missing", "request_id": "mcp-cancel-missing"},
            )
            assert missing_cancel.is_error is True
            assert missing_cancel.structured_content["code"] == "NOT_FOUND"

            cancelled = await client.call_tool(
                "cancel_research_run",
                {
                    "run_id": cancel_target.structured_content["run_id"],
                    "request_id": "mcp-cancel-request",
                },
            )
            assert cancelled.is_error is False
            assert cancelled.structured_content["outcome"] == "accepted"
            assert cancelled.structured_content["run"]["status"] == "cancelling"
            assert cancelled.structured_content["replayed"] is False
            assert cancelled.structured_content["retry_after_seconds"] == 2

            concurrent_replays = await _concurrent_stdio_cancel_replays(
                settings,
                tmp_path,
                run_id=str(cancel_target.structured_content["run_id"]),
                request_id="mcp-cancel-request",
            )
            assert all(not result.is_error for result in concurrent_replays)
            assert all(
                result.structured_content["run"] == cancelled.structured_content["run"]
                for result in concurrent_replays
            )
            assert all(
                result.structured_content["replayed"] is True
                for result in concurrent_replays
            )

            idempotency_conflict = await client.call_tool(
                "cancel_research_run",
                {
                    "run_id": conflict_target.structured_content["run_id"],
                    "request_id": "mcp-cancel-request",
                },
            )
            assert idempotency_conflict.is_error is True
            assert idempotency_conflict.structured_content["code"] == (
                "IDEMPOTENCY_CONFLICT"
            )

            _install_transient_cancel_failure(settings)
            try:
                temporarily_unavailable = await client.call_tool(
                    "cancel_research_run",
                    {
                        "run_id": conflict_target.structured_content["run_id"],
                        "request_id": "mcp-cancel-temporary",
                    },
                )
            finally:
                _remove_transient_cancel_failure(settings)
            assert temporarily_unavailable.is_error is True
            assert temporarily_unavailable.structured_content["code"] == (
                "TEMPORARILY_UNAVAILABLE"
            )
            assert temporarily_unavailable.structured_content["retryable"] is True
            assert temporarily_unavailable.structured_content[
                "retry_after_seconds"
            ] == 2
            assert temporarily_unavailable.structured_content["trace_id"]

            conflict_target_detail = await client.call_tool(
                "get_research_run",
                {"run_id": conflict_target.structured_content["run_id"]},
            )
            assert conflict_target_detail.structured_content["status"] == "queued"

            terminal_conflict = await client.call_tool(
                "cancel_research_run",
                {
                    "run_id": factor.structured_content["run_id"],
                    "request_id": "mcp-cancel-terminal",
                },
            )
            assert terminal_conflict.is_error is True
            assert terminal_conflict.structured_content["code"] == "STATE_CONFLICT"
    finally:
        release_worker.set()
        await _join_or_stop_worker_process(worker_process)
    assert worker_process.exitcode == 0

    sixth_log = tmp_path / "mcp-sixth-cancel-replay.stderr.log"
    async with _mcp_client(
        settings,
        sixth_log,
        enable_research_cancel=True,
    ) as client:
        replay = await client.call_tool(
            "cancel_research_run",
            {
                "run_id": cancel_target.structured_content["run_id"],
                "request_id": "mcp-cancel-request",
            },
        )
        assert replay.is_error is False
        assert replay.structured_content["run"] == cancelled.structured_content["run"]
        assert replay.structured_content["replayed"] is True
        assert replay.structured_content["retry_after_seconds"] == 2
        stable_cancelled = await client.call_tool(
            "get_research_run",
            {"run_id": cancel_target.structured_content["run_id"]},
        )
        assert stable_cancelled.structured_content["status"] == "cancelled"


async def _assert_first_semantic_result_pages(
    client: Client,
    *,
    factor_run_id: str,
    strategy_run_id: str,
    strategy_command: dict[str, object],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    factor = await client.call_tool(
        "get_research_run_result",
        {"run_id": factor_run_id, "section": "factor"},
    )
    assert factor.is_error is False
    assert factor.structured_content["research_kind"] == "factor_evaluation"
    assert factor.structured_content["units"] == {
        "horizon": "research_sessions",
        "ic": "correlation",
        "rank_ic": "rank_correlation",
        "quantile_returns": "decimal_return",
        "top_bottom_return": "decimal_return",
    }
    assert factor.structured_content["missing_values"] == {
        "unavailable_optional_metric": "null",
        "observed_zero_is_missing": False,
    }
    horizons = factor.structured_content["factor"]["horizons"]
    assert set(horizons) == {"1", "5", "20"}
    assert [horizons[name]["horizon"] for name in ("1", "5", "20")] == [1, 5, 20]
    assert all(horizons[name]["coverage"]["signal_session_count"] > 0 for name in horizons)
    _assert_optional_numbers_are_finite(factor.structured_content)

    factor_provenance = await client.call_tool(
        "get_research_run_result",
        {"run_id": factor_run_id, "section": "provenance"},
    )
    assert factor_provenance.is_error is False
    assert factor_provenance.structured_content["authoring_input"]["formula"] == "close"
    _assert_public_result_payload(factor_provenance.structured_content)

    incompatible = await client.call_tool(
        "get_research_run_result",
        {"run_id": factor_run_id, "section": "strategy_summary"},
    )
    assert incompatible.is_error is True
    assert incompatible.structured_content["code"] == "STATE_CONFLICT"

    strategy_factor = await client.call_tool(
        "get_research_run_result",
        {"run_id": strategy_run_id, "section": "factor"},
    )
    assert strategy_factor.is_error is False
    assert strategy_factor.structured_content["research_kind"] == "strategy_backtest"

    summary = await client.call_tool(
        "get_research_run_result",
        {"run_id": strategy_run_id, "section": "strategy_summary"},
    )
    assert summary.is_error is False
    assert summary.structured_content["benchmark"] == {
        "universe": strategy_command["universe"],
        "methodology": "selected_universe_equal_weight",
    }
    _assert_optional_numbers_are_finite(summary.structured_content)

    observations = await client.call_tool(
        "get_research_run_result",
        {
            "run_id": strategy_run_id,
            "section": "strategy_observations",
            "limit": 50,
        },
    )
    assert observations.is_error is False
    assert len(observations.structured_content["items"]) == 50
    assert isinstance(observations.structured_content["next_cursor"], str)
    decoded_observation_cursor = urlsafe_b64decode(
        observations.structured_content["next_cursor"]
    )
    assert strategy_run_id.encode() not in decoded_observation_cursor
    assert b"strategy_observations" not in decoded_observation_cursor
    assert len(json.dumps(observations.structured_content).encode()) < 64 * 1024

    terminal = await client.call_tool(
        "get_research_run_result",
        {"run_id": strategy_run_id, "section": "terminal_strategy_state"},
    )
    assert terminal.is_error is False
    assert "positions" not in terminal.structured_content
    assert terminal.structured_content["session"] == strategy_command["end_date"]

    positions = await client.call_tool(
        "get_research_run_result",
        {"run_id": strategy_run_id, "section": "terminal_positions", "limit": 50},
    )
    assert positions.is_error is False
    assert len(positions.structured_content["items"]) == 50
    assert isinstance(positions.structured_content["next_cursor"], str)

    provenance = await client.call_tool(
        "get_research_run_result",
        {"run_id": strategy_run_id, "section": "provenance"},
    )
    assert provenance.is_error is False
    assert provenance.structured_content["authoring_input"] == {
        "formula": strategy_command["formula"],
        "hypothesis": strategy_command["hypothesis"],
        "start_date": strategy_command["start_date"],
        "end_date": strategy_command["end_date"],
        "universe": strategy_command["universe"],
        "neutralization": strategy_command["neutralization"],
        "research_kind": "strategy_backtest",
        "holdings_count": 51,
        "rebalance_every_sessions": 1,
    }
    assert provenance.structured_content["data"]["data_through_session"] >= (
        strategy_command["end_date"]
    )
    _assert_public_result_payload(provenance.structured_content)

    malformed = await client.call_tool(
        "get_research_run_result",
        {"run_id": strategy_run_id, "section": "strategy_summary", "limit": 20},
    )
    assert malformed.is_error is True
    assert malformed.structured_content["code"] == "INVALID_INPUT"
    missing = await client.call_tool(
        "get_research_run_result",
        {"run_id": "run_missing", "section": "factor"},
    )
    assert missing.is_error is True
    assert missing.structured_content["code"] == "NOT_FOUND"
    return (
        observations.structured_content,
        positions.structured_content,
        summary.structured_content,
        terminal.structured_content,
    )


def _assert_public_result_payload(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload, sort_keys=True).lower()
    for private_name in (
        "manifest",
        "partition",
        "rustfs",
        "object_key",
        "checkpoint",
        "attempt",
        "lease",
        "recovery",
        "sql",
        "path",
    ):
        assert private_name not in serialized


def _assert_optional_numbers_are_finite(value: object) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _assert_optional_numbers_are_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_optional_numbers_are_finite(item)
    elif isinstance(value, float):
        assert math.isfinite(value)


async def _poll_terminal(client: Client, run_id: str) -> dict[str, object]:
    with anyio.fail_after(10):
        while True:
            response = await client.call_tool("get_research_run", {"run_id": run_id})
            assert response.is_error is False
            detail = response.structured_content
            if detail["status"] in {"succeeded", "failed", "cancelled"}:
                return detail
            await anyio.sleep(0)


def _assert_compact_polling_payload(payload: dict[str, object]) -> None:
    serialized = str(payload).lower()
    assert "result" not in payload
    for private_name in (
        "manifest",
        "checkpoint",
        "attempt",
        "lease",
        "object_key",
        "sql",
        "path",
    ):
        assert private_name not in serialized


class _PublicationReadForbidden:
    def read(self, _published_ref: object) -> object:
        raise AssertionError("compact ResearchRun polling must not read the Result bundle")


def _assert_polling_does_not_read_result(settings: CoreSettings, run_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        service = ResearchRunService(
            database,
            publication=_PublicationReadForbidden(),  # type: ignore[arg-type]
        )
        detail = service.get_polling_detail(run_id)
        assert detail is not None
        assert detail.status == "succeeded"
        assert detail.result_available is True
    finally:
        database.close()


def _run_worker_lost_after_claim(
    settings: CoreSettings,
) -> subprocess.CompletedProcess[str]:
    program = (
        "import os\n"
        "from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime\n"
        "with open_core_runtime(CoreSettings.from_environment()) as runtime:\n"
        "    runtime.research_runs.process_next(on_claim=lambda *_args: os._exit(17))\n"
    )
    return subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path.cwd(),
        env={**os.environ, **_core_environment(settings)},
    )


def _expire_active_attempt(settings: CoreSettings, run_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            expired = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET lease_expires_at = now() - interval '1 second'
                WHERE run_id = %s AND status = 'running'
                """,
                (run_id,),
            )
        assert expired.rowcount == 1
    finally:
        database.close()


def _seed_pagination_runs(settings: CoreSettings, count: int) -> None:
    with open_core_runtime(settings) as runtime:
        for index in range(count):
            command = TypeAdapter(ResearchRunAdmissionCommand).validate_python(
                _command(
                    f"mcp-pagination-{index}",
                    research_kind="factor_evaluation",
                )
            )
            outcome = runtime.research_runs.admit_with_outcome(command)
            assert outcome.outcome == "accepted"
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.runs
                SET created_at = '2026-08-26T00:00:00+00'::timestamptz
                """
            )
        assert updated.rowcount == count + 3
    finally:
        database.close()


def _tamper_cursor(cursor: str) -> str:
    index = len(cursor) // 2
    replacement = "A" if cursor[index] != "A" else "B"
    return f"{cursor[:index]}{replacement}{cursor[index + 1:]}"


def _prioritize_run_for_worker(settings: CoreSettings, run_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.runs
                SET created_at = '2026-08-25T00:00:00+00'::timestamptz
                WHERE id = %s AND status = 'queued'
                """,
                (run_id,),
            )
        assert updated.rowcount == 1
    finally:
        database.close()


def _assert_concurrent_rejection_receipt(settings: CoreSettings) -> None:
    command = TypeAdapter(ResearchRunAdmissionCommand).validate_python(
        {**_command("mcp-concurrent-rejection"), "formula": "unknown_alpha"}
    )
    with open_core_runtime(settings) as runtime:
        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(
                executor.map(
                    lambda _index: runtime.research_runs.admit_with_outcome(command),
                    range(8),
                )
            )
    assert all(isinstance(outcome, ResearchRunAdmissionRejectedOutcome) for outcome in outcomes)
    assert sum(not outcome.replayed for outcome in outcomes) == 1
    assert sum(outcome.replayed for outcome in outcomes) == 7
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS receipt_count,
                       count(run_id) AS run_count
                FROM research_runs.admission_requests
                WHERE request_id = 'mcp-concurrent-rejection'
                """
            ).fetchone()
        assert row == {"receipt_count": 1, "run_count": 0}
    finally:
        database.close()


def _run_barrier_worker(settings: CoreSettings, prepared, release_worker) -> None:
    def pause_after_prepare(stage: str, _run_id: str) -> None:
        if stage == "prepared":
            prepared.set()
            assert release_worker.wait(timeout=30)

    with open_core_runtime(settings) as runtime:
        worker = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(settings.data_mount),
            progress=pause_after_prepare,
        )
        assert worker.process_next() is True


async def _join_or_stop_worker_process(process) -> None:
    await anyio.to_thread.run_sync(process.join, 30)
    if process.is_alive():
        process.terminate()
        await anyio.to_thread.run_sync(process.join, 5)
    if process.is_alive():
        process.kill()
        await anyio.to_thread.run_sync(process.join, 5)


async def _concurrent_stdio_cancel_replays(
    settings: CoreSettings,
    tmp_path: Path,
    *,
    run_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def replay(index: int) -> None:
        async with _mcp_client(
            settings,
            tmp_path / f"mcp-concurrent-cancel-{index}.stderr.log",
            enable_research_cancel=True,
        ) as client:
            results.append(
                await client.call_tool(
                    "cancel_research_run",
                    {"run_id": run_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for index in range(4):
            task_group.start_soon(replay, index)
    return results


@asynccontextmanager
async def _mcp_client(
    settings: CoreSettings,
    stderr_path: Path,
    *,
    enable_research_cancel: bool = False,
    environment: dict[str, str] | None = None,
) -> AsyncIterator[Client]:
    executable = Path(sys.executable).with_name("thesistrace-research-agent-mcp")
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stderr_path.open("w+") as errlog:
        async with Client(
            stdio_client(
                StdioServerParameters(
                    command=str(executable),
                    cwd=Path.cwd(),
                    env={
                        **_core_environment(settings),
                        **({} if environment is None else environment),
                        **(
                            {RESEARCH_CANCEL_ENABLE_ENVIRONMENT: "true"}
                            if enable_research_cancel
                            else {}
                        ),
                    },
                ),
                errlog=errlog,
            )
        ) as client:
            yield client


def _install_transient_cancel_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION research_runs.reject_stdio_cancel_transiently()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF OLD.status = 'queued' AND NEW.status = 'cancelled' THEN
                        RAISE EXCEPTION 'injected stdio cancellation dependency failure'
                            USING ERRCODE = '08006';
                    END IF;
                    RETURN NEW;
                END
                $$;
                CREATE TRIGGER reject_stdio_cancel_transiently
                BEFORE UPDATE ON research_runs.runs
                FOR EACH ROW
                EXECUTE FUNCTION research_runs.reject_stdio_cancel_transiently();
                """
            )
    finally:
        database.close()


def _remove_transient_cancel_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_stdio_cancel_transiently ON research_runs.runs;
                DROP FUNCTION research_runs.reject_stdio_cancel_transiently();
                """
            )
    finally:
        database.close()


def _command(request_id: str, *, research_kind: str = "strategy_backtest") -> dict[str, object]:
    command: dict[str, object] = {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "MCP Research",
        "formula": "close",
        "hypothesis": "Close prices preserve a stable cross-sectional signal.",
        "start_date": "2026-08-03",
        "end_date": "2026-08-04",
        "universe": "top300",
        "neutralization": "none",
        "research_kind": research_kind,
    }
    if research_kind == "strategy_backtest":
        command.update({"holdings_count": 1, "rebalance_every_sessions": 1})
    return command


def _weekday_sessions(start: date, count: int) -> tuple[str, ...]:
    sessions: list[str] = []
    cursor = start
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(sessions)


def _publish_current_data(settings: CoreSettings) -> tuple[str, ...]:
    sessions = _weekday_sessions(date(2026, 8, 3), 75)
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        try:
            s3.create_bucket(Bucket=settings.s3_bucket)
        except s3.exceptions.BucketAlreadyOwnedByYou:
            pass
    finally:
        s3.close()
    template = build_minimal_canonical_fixture()
    instrument_template = template["instruments"][0]
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    industry = template["industry_membership"][0]
    instruments = []
    instrument_ids = []
    for index in range(1, 52):
        ts_code = f"{index:06d}.SZ"
        instrument_id = f"equity:{ts_code}"
        instrument_ids.append(instrument_id)
        instruments.append(
            {
                **instrument_template,
                "instrument_id": instrument_id,
                "ts_code": ts_code,
            }
        )
    universe = {"instrument_ids": instrument_ids, "status": "available"}
    canonical = {
        **template,
        "field_catalog": [
            next(
                row
                for row in field_catalog(sessions[0])
                if row["field_id"] == "price.close.adjusted"
            )
        ],
        "research_calendar": list(sessions),
        "instruments": instruments,
        "prices": [
            {**price, "instrument_id": instrument_id, "session": session}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "trading_states": [
            {**state, "instrument_id": instrument_id, "session": session}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "price_limits": [
            {**limit, "instrument_id": instrument_id, "session": session}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "base_pool": [
            {"session": session, "instrument_ids": instrument_ids} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
        "industry_membership": [
            {**industry, "instrument_id": instrument_id}
            for instrument_id in instrument_ids
        ],
    }
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        source_name="research-agent-mcp-acceptance",
        source_lineage={"contract": "research-agent-mcp"},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id="research-agent-mcp-head",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="research-agent-mcp-head",
        )
    finally:
        database.close()
    return sessions


def _run_worker_once(settings: CoreSettings) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            "research",
            "--once",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path.cwd(),
        env={**os.environ, **_core_environment(settings)},
    )


def _assert_worker_succeeded(completed: subprocess.CompletedProcess[str]) -> None:
    assert completed.returncode == 0, {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4096:],
        "stderr": completed.stderr[-4096:],
    }


def _core_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
            settings.batch_attempt_control_directory
        ),
    }

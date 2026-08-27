from __future__ import annotations

from base64 import urlsafe_b64decode
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from core_runtime import drop_product_schemas, isolated_core_settings
from pydantic import TypeAdapter
from research_agent_mcp_runtime import (
    assert_worker_succeeded,
    publish_current_data,
    run_research_worker_once,
)
from test_core_research_agent_mcp_runs import _mcp_client
from test_core_research_batch_fifo import (
    _release_claim_barrier_worker,
    _start_claim_barrier_worker,
    _terminate_worker,
    _wait_for_worker_event,
)
from test_core_research_batch_fifo import (
    _run_worker_once as _run_batch_worker_once,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_batch import ResearchBatchAdmissionCommand

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)


def test_stdio_research_batches_execute_read_child_results_and_cancel_across_restart(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path / "data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    try:
        sessions = publish_current_data(settings)
        anyio.run(_exercise_batches, settings, tmp_path, sessions[20])
    finally:
        drop_product_schemas(settings)


def test_stdio_research_batch_pagination_is_bounded_stable_and_restartable(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path / "pagination-data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    try:
        publish_current_data(settings)
        expected_ids = _prepare_tied_pagination_batches(settings)
        anyio.run(_exercise_batch_pagination, settings, tmp_path, expected_ids)
    finally:
        drop_product_schemas(settings)


async def _exercise_batch_pagination(
    settings: CoreSettings,
    tmp_path: Path,
    expected_ids: list[str],
) -> None:
    async with _mcp_client(settings, tmp_path / "batch-page-first.stderr.log") as client:
        default_page = await client.call_tool("list_research_batches", {})
        assert default_page.is_error is False
        assert len(default_page.structured_content["items"]) == 20
        assert [item["id"] for item in default_page.structured_content["items"]] == (
            expected_ids[:20]
        )

        first_page = await client.call_tool("list_research_batches", {"limit": 50})
        assert first_page.is_error is False
        assert [item["id"] for item in first_page.structured_content["items"]] == (
            expected_ids[:50]
        )
        cursor = first_page.structured_content["next_cursor"]
        assert isinstance(cursor, str)
        decoded = urlsafe_b64decode(cursor)
        assert all(batch_id.encode() not in decoded for batch_id in expected_ids)

        oversized = await client.call_tool("list_research_batches", {"limit": 51})
        assert oversized.is_error is True
        assert oversized.structured_content["code"] == "INVALID_INPUT"
        unicode_cursor = await client.call_tool(
            "list_research_batches",
            {"cursor": "游标"},
        )
        assert unicode_cursor.is_error is True
        assert unicode_cursor.structured_content["code"] == "INVALID_INPUT"

    async with _mcp_client(settings, tmp_path / "batch-page-restart.stderr.log") as client:
        second_page = await client.call_tool(
            "list_research_batches",
            {"limit": 50, "cursor": cursor},
        )
        assert second_page.is_error is False
        assert [item["id"] for item in second_page.structured_content["items"]] == (
            expected_ids[50:]
        )
        assert second_page.structured_content["next_cursor"] is None


def _prepare_tied_pagination_batches(settings: CoreSettings) -> list[str]:
    adapter = TypeAdapter(ResearchBatchAdmissionCommand)
    batch_ids: list[str] = []
    with open_core_runtime(settings) as runtime:
        for index in range(51):
            command = adapter.validate_python(
                _factor_batch_command(
                    f"mcp-pagination-batch-{index:02d}",
                    end_date="2026-08-04",
                )
            )
            batch_ids.append(runtime.research_batches.admit(command).id)
        tied_created_at = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)
        with runtime.database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_batches.batches
                SET created_at = %s
                WHERE id = ANY(%s)
                """,
                (tied_created_at, batch_ids),
            )
        assert updated.rowcount == 51
    return sorted(batch_ids)


async def _exercise_batches(
    settings: CoreSettings,
    tmp_path: Path,
    end_date: str,
) -> None:
    factor_command = _factor_batch_command("mcp-factor-batch", end_date=end_date)
    strategy_command = _strategy_batch_command("mcp-strategy-batch", end_date=end_date)
    rejected_command = {
        **_factor_batch_command("mcp-rejected-batch", end_date=end_date),
        "factors": [{"item_key": "invalid", "formula": "unknown_alpha"}],
    }
    transient_rejected_command = {
        **_factor_batch_command("mcp-transient-rejected-batch", end_date=end_date),
        "factors": [{"item_key": "invalid", "formula": "unknown_alpha"}],
    }
    concurrent_command = _factor_batch_command(
        "mcp-concurrent-accepted-batch",
        end_date=end_date,
    )
    concurrent_rejected_command = {
        **_factor_batch_command("mcp-concurrent-rejected-batch", end_date=end_date),
        "factors": [{"item_key": "invalid", "formula": "unknown_alpha"}],
    }

    async with _mcp_client(settings, tmp_path / "batch-first.stderr.log") as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        assert {
            "list_research_batches",
            "get_research_batch",
            "submit_research_batch",
        } <= tools
        assert "cancel_research_batch" not in tools
        assert "get_research_batch_result" not in tools

        factor = await client.call_tool("submit_research_batch", factor_command)
        strategy = await client.call_tool("submit_research_batch", strategy_command)
        rejected = await client.call_tool("submit_research_batch", rejected_command)
        assert factor.is_error is False
        assert strategy.is_error is False
        assert factor.structured_content["outcome"] == "accepted"
        assert strategy.structured_content["outcome"] == "accepted"
        assert factor.structured_content["replayed"] is False
        assert strategy.structured_content["replayed"] is False
        assert rejected.is_error is False
        assert rejected.structured_content["outcome"] == "rejected"
        assert rejected.structured_content["issues"][0]["item_key"] == "invalid"

        _install_transient_rejection_receipt_failure(settings)
        try:
            unavailable_rejection = await client.call_tool(
                "submit_research_batch",
                transient_rejected_command,
            )
        finally:
            _remove_transient_rejection_receipt_failure(settings)
        assert unavailable_rejection.is_error is True
        assert unavailable_rejection.structured_content["code"] == ("TEMPORARILY_UNAVAILABLE")
        assert unavailable_rejection.structured_content["retryable"] is True
        assert unavailable_rejection.structured_content["retry_after_seconds"] == 2
        assert (
            _admission_receipt_count(
                settings,
                "mcp-transient-rejected-batch",
            )
            == 0
        )
        retried_rejection = await client.call_tool(
            "submit_research_batch",
            transient_rejected_command,
        )
        assert retried_rejection.is_error is False
        assert retried_rejection.structured_content["outcome"] == "rejected"
        assert retried_rejection.structured_content["replayed"] is False

        first_page = await client.call_tool("list_research_batches", {"limit": 1})
        assert first_page.is_error is False
        assert [item["id"] for item in first_page.structured_content["items"]] == [
            strategy.structured_content["batch_id"]
        ]
        cursor = first_page.structured_content["next_cursor"]
        assert isinstance(cursor, str)
        decoded_cursor = urlsafe_b64decode(cursor)
        assert str(strategy.structured_content["batch_id"]).encode() not in decoded_cursor
        second_page = await client.call_tool(
            "list_research_batches",
            {"limit": 1, "cursor": cursor},
        )
        assert [item["id"] for item in second_page.structured_content["items"]] == [
            factor.structured_content["batch_id"]
        ]
        tampered = f"{cursor[:-1]}{'A' if cursor[-1] != 'A' else 'B'}"
        invalid_cursor = await client.call_tool(
            "list_research_batches",
            {"cursor": tampered},
        )
        assert invalid_cursor.is_error is True
        assert invalid_cursor.structured_content["code"] == "INVALID_INPUT"

        factor_detail = await client.call_tool(
            "get_research_batch",
            {"batch_id": factor.structured_content["batch_id"]},
        )
        assert factor_detail.is_error is False
        assert [item["item_key"] for item in factor_detail.structured_content["items"]] == ["value"]
        assert "result" not in factor_detail.structured_content
        assert "result" not in factor_detail.structured_content["items"][0]
        _assert_public_batch_payload(factor_detail.structured_content)

        concurrent_accepts = await _concurrent_submits(client, concurrent_command)
        assert all(not result.is_error for result in concurrent_accepts)
        assert len({result.structured_content["batch_id"] for result in concurrent_accepts}) == 1
        assert (
            sum(result.structured_content["replayed"] is False for result in concurrent_accepts)
            == 1
        )
        concurrent_rejections = await _concurrent_submits(
            client,
            concurrent_rejected_command,
        )
        assert all(not result.is_error for result in concurrent_rejections)
        assert all(
            result.structured_content["outcome"] == "rejected" for result in concurrent_rejections
        )
        assert (
            sum(result.structured_content["replayed"] is False for result in concurrent_rejections)
            == 1
        )
        changed_submit = await client.call_tool(
            "submit_research_batch",
            {
                **concurrent_command,
                "factors": [{"item_key": "changed", "formula": "open"}],
            },
        )
        assert changed_submit.is_error is True
        assert changed_submit.structured_content["code"] == "IDEMPOTENCY_CONFLICT"
        unchanged_batch = await client.call_tool(
            "get_research_batch",
            {"batch_id": concurrent_accepts[0].structured_content["batch_id"]},
        )
        assert unchanged_batch.structured_content["status"] == "queued"
        assert [item["item_key"] for item in unchanged_batch.structured_content["items"]] == [
            "value"
        ]

    ordinary_worker = await anyio.to_thread.run_sync(run_research_worker_once, settings)
    assert_worker_succeeded(ordinary_worker)
    for _index in range(3):
        batch_worker = await anyio.to_thread.run_sync(
            _run_batch_worker_once,
            settings,
            "batch-research",
        )
        assert_worker_succeeded(batch_worker)

    async with _mcp_client(settings, tmp_path / "batch-second.stderr.log") as client:
        factor_replay = await client.call_tool("submit_research_batch", factor_command)
        strategy_replay = await client.call_tool("submit_research_batch", strategy_command)
        rejected_replay = await client.call_tool("submit_research_batch", rejected_command)
        transient_rejected_replay = await client.call_tool(
            "submit_research_batch",
            transient_rejected_command,
        )
        concurrent_replay = await client.call_tool(
            "submit_research_batch",
            concurrent_command,
        )
        concurrent_rejected_replay = await client.call_tool(
            "submit_research_batch",
            concurrent_rejected_command,
        )
        assert factor_replay.structured_content["status"] == "succeeded"
        assert strategy_replay.structured_content["status"] == "succeeded"
        assert factor_replay.structured_content["replayed"] is True
        assert strategy_replay.structured_content["replayed"] is True
        assert rejected_replay.structured_content["replayed"] is True
        assert transient_rejected_replay.structured_content["replayed"] is True
        assert concurrent_replay.structured_content["status"] == "succeeded"
        assert concurrent_replay.structured_content["replayed"] is True
        assert concurrent_rejected_replay.structured_content["outcome"] == "rejected"
        assert concurrent_rejected_replay.structured_content["replayed"] is True

        factor_detail = await client.call_tool(
            "get_research_batch",
            {"batch_id": factor.structured_content["batch_id"]},
        )
        strategy_detail = await client.call_tool(
            "get_research_batch",
            {"batch_id": strategy.structured_content["batch_id"]},
        )
        assert factor_detail.structured_content["status"] == "succeeded"
        assert strategy_detail.structured_content["status"] == "succeeded"
        factor_run_id = factor_detail.structured_content["items"][0]["research_run_id"]
        strategy_run_id = strategy_detail.structured_content["items"][0]["research_run_id"]
        factor_result = await client.call_tool(
            "get_research_run_result",
            {"run_id": factor_run_id, "section": "factor"},
        )
        strategy_result = await client.call_tool(
            "get_research_run_result",
            {"run_id": strategy_run_id, "section": "strategy_summary"},
        )
        assert factor_result.is_error is False
        assert factor_result.structured_content["run_id"] == factor_run_id
        assert strategy_result.is_error is False
        assert strategy_result.structured_content["run_id"] == strategy_run_id

        cancel_target = await client.call_tool(
            "submit_research_batch",
            _factor_batch_command("mcp-cancel-batch", end_date=end_date),
        )
        assert cancel_target.is_error is False

    worker = _start_claim_barrier_worker(settings, "batch-research")
    try:
        await anyio.to_thread.run_sync(_wait_for_worker_event, worker, "worker_claim")
        async with _mcp_client(
            settings,
            tmp_path / "batch-cancel.stderr.log",
            enable_research_cancel=True,
        ) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            cancel_tool = tools["cancel_research_batch"]
            assert cancel_tool.annotations is not None
            assert cancel_tool.annotations.destructive_hint is True
            running = await client.call_tool(
                "get_research_batch",
                {"batch_id": cancel_target.structured_content["batch_id"]},
            )
            assert running.structured_content["status"] == "running"
            assert running.structured_content["retry_after_seconds"] == 2
            cancel_arguments = {
                "batch_id": cancel_target.structured_content["batch_id"],
                "request_id": "mcp-cancel-batch-request",
            }
            cancelled = await client.call_tool(
                "cancel_research_batch",
                cancel_arguments,
            )
            assert cancelled.is_error is False
            assert cancelled.structured_content["batch"]["status"] == "cancelling"
            assert cancelled.structured_content["replayed"] is False
            assert cancelled.structured_content["retry_after_seconds"] == 2
            _assert_public_batch_payload(cancelled.structured_content["batch"])

            concurrent_replays: list[object] = []

            async def replay_cancel() -> None:
                concurrent_replays.append(
                    await client.call_tool("cancel_research_batch", cancel_arguments)
                )

            async with anyio.create_task_group() as task_group:
                for _index in range(4):
                    task_group.start_soon(replay_cancel)
            assert all(not result.is_error for result in concurrent_replays)
            assert all(
                result.structured_content["batch"] == cancelled.structured_content["batch"]
                for result in concurrent_replays
            )
            assert all(
                result.structured_content["replayed"] is True for result in concurrent_replays
            )

            terminal_conflict = await client.call_tool(
                "cancel_research_batch",
                {
                    "batch_id": factor.structured_content["batch_id"],
                    "request_id": "mcp-cancel-terminal-batch",
                },
            )
            assert terminal_conflict.is_error is True
            assert terminal_conflict.structured_content["code"] == "STATE_CONFLICT"
        await anyio.to_thread.run_sync(_release_claim_barrier_worker, worker)
        worker = None
    finally:
        if worker is not None:
            _terminate_worker(worker)

    async with _mcp_client(
        settings,
        tmp_path / "batch-cancel-replay.stderr.log",
        enable_research_cancel=True,
    ) as client:
        replay = await client.call_tool(
            "cancel_research_batch",
            {
                "batch_id": cancel_target.structured_content["batch_id"],
                "request_id": "mcp-cancel-batch-request",
            },
        )
        assert replay.is_error is False
        assert replay.structured_content["batch"] == cancelled.structured_content["batch"]
        assert replay.structured_content["replayed"] is True
        stable = await client.call_tool(
            "get_research_batch",
            {"batch_id": cancel_target.structured_content["batch_id"]},
        )
        assert stable.structured_content["status"] == "cancelled"
        assert stable.structured_content["retry_after_seconds"] is None


def _factor_batch_command(request_id: str, *, end_date: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "batch_kind": "factor_evaluation",
        "start_date": "2026-08-03",
        "end_date": end_date,
        "universe": "top300",
        "neutralization": "none",
        "factors": [
            {
                "item_key": "value",
                "name": "Value Factor",
                "formula": "close",
                "hypothesis": "Close preserves a stable cross-sectional signal.",
            }
        ],
    }


def _assert_public_batch_payload(payload: dict[str, object]) -> None:
    assert "diagnostic" in payload

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert not {
                "attempt",
                "live_progress",
                "task_attempt_count",
                "attempt_number",
            } & set(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)


async def _concurrent_submits(client, command: dict[str, object]) -> list[object]:
    results: list[object] = []

    async def submit() -> None:
        results.append(await client.call_tool("submit_research_batch", command))

    async with anyio.create_task_group() as task_group:
        for _index in range(4):
            task_group.start_soon(submit)
    return results


def _strategy_batch_command(request_id: str, *, end_date: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "batch_kind": "strategy_sweep",
        "start_date": "2026-08-03",
        "end_date": end_date,
        "universe": "top300",
        "neutralization": "none",
        "alpha": {
            "formula": "close",
            "hypothesis": "Close preserves a stable cross-sectional signal.",
        },
        "strategies": [
            {
                "item_key": "focused",
                "name": "Focused Strategy",
                "holdings_count": 1,
                "rebalance_every_sessions": 1,
            }
        ],
    }


def _install_transient_rejection_receipt_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION research_batches.reject_mcp_rejection_receipt_transiently()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.request_id = 'mcp-transient-rejected-batch' THEN
                        RAISE EXCEPTION 'injected Batch rejection receipt failure'
                            USING ERRCODE = '08006';
                    END IF;
                    RETURN NEW;
                END
                $$;
                CREATE TRIGGER reject_mcp_rejection_receipt_transiently
                BEFORE INSERT ON research_batches.admission_receipts
                FOR EACH ROW
                EXECUTE FUNCTION research_batches.reject_mcp_rejection_receipt_transiently();
                """
            )
    finally:
        database.close()


def _remove_transient_rejection_receipt_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_mcp_rejection_receipt_transiently
                    ON research_batches.admission_receipts;
                DROP FUNCTION research_batches.reject_mcp_rejection_receipt_transiently();
                """
            )
    finally:
        database.close()


def _admission_receipt_count(settings: CoreSettings, request_id: str) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_batches.admission_receipts
                WHERE request_id = %s
                """,
                (request_id,),
            ).fetchone()
        assert row is not None
        return int(row["count"])
    finally:
        database.close()

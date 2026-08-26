from __future__ import annotations

import os
import subprocess
import sys
from base64 import urlsafe_b64decode
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
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
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
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
        _publish_current_data(settings)
        _assert_concurrent_rejection_receipt(settings)
        anyio.run(_exercise_research_runs, settings, tmp_path)
    finally:
        drop_product_schemas(settings)


async def _exercise_research_runs(settings: CoreSettings, tmp_path: Path) -> None:
    factor_command = _command("mcp-factor", research_kind="factor_evaluation")
    strategy_command = _command("mcp-strategy", research_kind="strategy_backtest")
    rejected_command = {**_command("mcp-rejected"), "formula": "unknown_alpha"}

    first_log = tmp_path / "mcp-first.stderr.log"
    async with _mcp_client(settings, first_log) as client:
        discovered = await client.list_tools()
        tool_names = {tool.name for tool in discovered.tools}
        assert {"list_research_runs", "get_research_run", "submit_research_run"} <= (
            tool_names
        )
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
            _command("mcp-worker-recovery", research_kind="factor_evaluation"),
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


@asynccontextmanager
async def _mcp_client(
    settings: CoreSettings,
    stderr_path: Path,
) -> AsyncIterator[Client]:
    executable = Path(sys.executable).with_name("thesistrace-research-agent-mcp")
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stderr_path.open("w+") as errlog:
        async with Client(
            stdio_client(
                StdioServerParameters(
                    command=str(executable),
                    cwd=Path.cwd(),
                    env=_core_environment(settings),
                ),
                errlog=errlog,
            )
        ) as client:
            yield client


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


def _publish_current_data(settings: CoreSettings) -> None:
    sessions = _weekday_sessions(date(2026, 8, 3), 30)
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
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
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
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
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

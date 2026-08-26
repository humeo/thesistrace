from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from base64 import urlsafe_b64decode
from pathlib import Path

import anyio
import pytest
from core_runtime import drop_product_schemas, isolated_core_settings
from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb
from test_core_research_agent_mcp_runs import (
    _assert_worker_succeeded,
    _command,
    _core_environment,
    _mcp_client,
    _publish_current_data,
    _run_worker_once,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)


def test_stdio_daily_tracks_survive_disconnect_progress_and_enforce_capacity(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path / "data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    try:
        _publish_current_data(settings)
        anyio.run(_exercise_daily_tracks, settings, tmp_path)
    finally:
        drop_product_schemas(settings)


def test_start_tracking_receipt_rejects_malformed_durable_outcomes(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path / "receipt-data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    valid = {
        "id": "track_missing",
        "status": "active",
        "seed_run_id": "run_missing",
        "result_checksum_sha256": "f" * 64,
        "origin_session": "2026-08-04",
        "strategy_session": "2026-08-04",
    }
    malformed = (
        {**valid, "result_checksum_sha256": None},
        {**valid, "result_checksum_sha256": "not-a-checksum"},
        {**valid, "origin_session": None},
        {**valid, "origin_session": "2026/08/04"},
        {**valid, "strategy_session": {}},
        {**valid, "strategy_session": "04-08-2026"},
    )
    try:
        for index, outcome in enumerate(malformed):
            with pytest.raises(CheckViolation):
                with database.transaction() as transaction:
                    transaction.execute(
                        """
                        INSERT INTO research_runs.start_tracking_receipts (
                            request_id, request_fingerprint, seed_run_id,
                            track_id, outcome
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            f"malformed_start_tracking_{index}",
                            "f" * 64,
                            "run_missing",
                            "track_missing",
                            Jsonb(outcome),
                        ),
                    )
    finally:
        database.close()
        drop_product_schemas(settings)


async def _exercise_daily_tracks(settings: CoreSettings, tmp_path: Path) -> None:
    async with _mcp_client(settings, tmp_path / "track-submit.stderr.log") as client:
        strategy_runs = []
        for index in range(5):
            response = await client.call_tool(
                "submit_research_run",
                _command(f"track-strategy-{index}"),
            )
            assert response.is_error is False
            strategy_runs.append(str(response.structured_content["run_id"]))
        factor = await client.call_tool(
            "submit_research_run",
            _command("track-factor", research_kind="factor_evaluation"),
        )
        assert factor.is_error is False
        factor_run_id = str(factor.structured_content["run_id"])

    for _ in range(6):
        completed = await anyio.to_thread.run_sync(_run_worker_once, settings)
        _assert_worker_succeeded(completed)

    concurrent = await _concurrent_start(
        settings,
        tmp_path,
        run_id=strategy_runs[1],
        request_id="track-concurrent-start",
    )
    assert all(not result.is_error for result in concurrent)
    assert len({result.structured_content["track_id"] for result in concurrent}) == 1
    assert sorted(result.structured_content["replayed"] for result in concurrent) == [
        False,
        True,
        True,
        True,
    ]
    concurrent_track_id = str(concurrent[0].structured_content["track_id"])

    async with _mcp_client(settings, tmp_path / "track-start.stderr.log") as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert {"list_daily_tracks", "get_daily_track", "start_daily_track"} <= set(tools)
        assert "delete_daily_track" not in tools
        assert tools["start_daily_track"].annotations.read_only_hint is False
        assert tools["start_daily_track"].annotations.destructive_hint is False

        factor_rejected = await client.call_tool(
            "start_daily_track",
            {"run_id": factor_run_id, "request_id": "track-factor-rejected"},
        )
        assert factor_rejected.is_error is True
        assert factor_rejected.structured_content["code"] == "STATE_CONFLICT"

        queued = await client.call_tool(
            "submit_research_run",
            _command("track-queued-origin"),
        )
        queued_rejected = await client.call_tool(
            "start_daily_track",
            {
                "run_id": queued.structured_content["run_id"],
                "request_id": "track-queued-rejected",
            },
        )
        assert queued_rejected.is_error is True
        assert queued_rejected.structured_content["code"] == "STATE_CONFLICT"

        started = await client.call_tool(
            "start_daily_track",
            {"run_id": strategy_runs[0], "request_id": "track-start"},
        )
        assert started.is_error is False
        track_id = str(started.structured_content["track_id"])
        assert started.structured_content == {
            "outcome": "accepted",
            "track_id": track_id,
            "status": "active",
            "replayed": False,
            "retry_after_seconds": 30,
        }
        replay = await client.call_tool(
            "start_daily_track",
            {"run_id": strategy_runs[0], "request_id": "track-start"},
        )
        assert replay.structured_content["track_id"] == track_id
        assert replay.structured_content["replayed"] is True
        duplicate_origin = await client.call_tool(
            "start_daily_track",
            {"run_id": strategy_runs[0], "request_id": "track-duplicate-origin"},
        )
        assert duplicate_origin.is_error is True
        assert duplicate_origin.structured_content["code"] == "STATE_CONFLICT"
        fingerprint_conflict = await client.call_tool(
            "start_daily_track",
            {"run_id": strategy_runs[2], "request_id": "track-start"},
        )
        assert fingerprint_conflict.is_error is True
        assert fingerprint_conflict.structured_content["code"] == "IDEMPOTENCY_CONFLICT"

        initial = await client.call_tool("get_daily_track", {"track_id": track_id})
        assert initial.is_error is False
        assert initial.structured_content["progress"]["lag_sessions"] > 0
        _assert_compact_track(initial.structured_content)

    async with _mcp_client(settings, tmp_path / "track-replay.stderr.log") as client:
        replay_after_restart = await client.call_tool(
            "start_daily_track",
            {"run_id": strategy_runs[0], "request_id": "track-start"},
        )
        assert replay_after_restart.is_error is False
        assert replay_after_restart.structured_content["track_id"] == track_id
        assert replay_after_restart.structured_content["replayed"] is True

    await _assert_transient_daily_track_reads(settings, tmp_path, track_id)
    async with _mcp_client(settings, tmp_path / "track-fault-recovery.stderr.log") as client:
        recovered = await client.call_tool("get_daily_track", {"track_id": track_id})
        assert recovered.is_error is False

        original_origin = _corrupt_track_origin(settings, track_id)
        try:
            corrupted = await client.call_tool("get_daily_track", {"track_id": track_id})
        finally:
            _restore_track_origin(settings, track_id, original_origin)
        assert corrupted.is_error is True
        assert corrupted.structured_content["code"] == "INTERNAL"
        assert corrupted.structured_content["retryable"] is False
        assert "origin" not in corrupted.structured_content["message"].lower()

        _install_transient_start_failure(settings)
        try:
            transient_start = await client.call_tool(
                "start_daily_track",
                {
                    "run_id": strategy_runs[3],
                    "request_id": "track-transient-start",
                },
            )
        finally:
            _remove_transient_start_failure(settings)
        assert transient_start.is_error is True
        assert transient_start.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
        assert _start_tracking_storage(settings, strategy_runs[3], "track-transient-start") == (
            0,
            0,
        )
        recovered_start = await client.call_tool(
            "start_daily_track",
            {
                "run_id": strategy_runs[3],
                "request_id": "track-transient-start",
            },
        )
        assert recovered_start.is_error is False
        transient_track_id = str(recovered_start.structured_content["track_id"])

    blocked_worker = await anyio.to_thread.run_sync(
        _run_tracking_worker_once,
        settings,
        1,
    )
    _assert_worker_succeeded(blocked_worker)
    async with _mcp_client(settings, tmp_path / "track-blocked.stderr.log") as client:
        blocked = await client.call_tool(
            "get_daily_track",
            {"track_id": concurrent_track_id},
        )
        assert blocked.is_error is False
        assert blocked.structured_content["progress"]["phase"] == "blocked"
        assert blocked.structured_content["blocked_reason"] == (
            "DailyTrack target exceeds Tracking Worker capacity."
        )
        assert blocked.structured_content["action_eligibility"] == {
            "retry": True,
            "stop": True,
        }
        assert blocked.structured_content["retry_after_seconds"] is None
        _assert_compact_track(blocked.structured_content, retry=True)

    for _ in range(4):
        completed = await anyio.to_thread.run_sync(_run_tracking_worker_once, settings)
        _assert_worker_succeeded(completed)

    async with _mcp_client(settings, tmp_path / "track-reconnect.stderr.log") as client:
        advanced = await client.call_tool("get_daily_track", {"track_id": track_id})
        blocked_after_restart = await client.call_tool(
            "get_daily_track",
            {"track_id": concurrent_track_id},
        )
        transient_advanced = await client.call_tool(
            "get_daily_track",
            {"track_id": transient_track_id},
        )
        assert advanced.is_error is False
        assert blocked_after_restart.is_error is False
        assert transient_advanced.is_error is False
        assert advanced.structured_content["progress"]["phase"] == "up_to_date"
        assert advanced.structured_content["progress"]["lag_sessions"] == 0
        assert blocked_after_restart.structured_content["progress"]["phase"] == "blocked"
        assert blocked_after_restart.structured_content["blocked_reason"] == (
            "DailyTrack target exceeds Tracking Worker capacity."
        )
        assert transient_advanced.structured_content["progress"]["phase"] == "up_to_date"
        assert advanced.structured_content["origin"]["research_run_id"] == strategy_runs[0]
        _assert_compact_track(advanced.structured_content)

    _seed_active_capacity_clones(settings, source_track_id=track_id, count=6)
    capacity = await _concurrent_capacity_start(
        settings,
        tmp_path,
        run_ids=(strategy_runs[2], strategy_runs[4]),
    )
    assert sorted(result.is_error for result in capacity) == [False, True]
    accepted_capacity = next(result for result in capacity if not result.is_error)
    rejected_capacity = next(result for result in capacity if result.is_error)
    assert accepted_capacity.structured_content["status"] == "active"
    assert rejected_capacity.structured_content["code"] == "STATE_CONFLICT"

    expected_ids = _seed_tied_stopped_history(settings, source_track_id=track_id, count=51)
    async with _mcp_client(settings, tmp_path / "track-pagination.stderr.log") as client:
        default_page = await client.call_tool("list_daily_tracks", {})
        assert default_page.is_error is False
        assert len(default_page.structured_content["items"]) == 20
        first_page = await client.call_tool("list_daily_tracks", {"limit": 50})
        assert [item["id"] for item in first_page.structured_content["items"]] == expected_ids[:50]
        cursor = first_page.structured_content["next_cursor"]
        assert isinstance(cursor, str)
        decoded = urlsafe_b64decode(cursor)
        assert all(track_id.encode() not in decoded for track_id in expected_ids)
        for invalid_cursor in (cursor[:-1] + ("A" if cursor[-1] != "A" else "B"), "游标"):
            invalid = await client.call_tool(
                "list_daily_tracks",
                {"cursor": invalid_cursor},
            )
            assert invalid.is_error is True
            assert invalid.structured_content["code"] == "INVALID_INPUT"
        oversized = await client.call_tool("list_daily_tracks", {"limit": 51})
        assert oversized.is_error is True
        assert oversized.structured_content["code"] == "INVALID_INPUT"

    async with _mcp_client(settings, tmp_path / "track-pagination-restart.stderr.log") as client:
        tail = await client.call_tool(
            "list_daily_tracks",
            {"limit": 50, "cursor": cursor},
        )
        assert [item["id"] for item in tail.structured_content["items"]] == expected_ids[50:]
        assert tail.structured_content["next_cursor"] is None


async def _concurrent_start(
    settings: CoreSettings,
    tmp_path: Path,
    *,
    run_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def start(index: int) -> None:
        async with _mcp_client(
            settings,
            tmp_path / f"track-concurrent-{index}.stderr.log",
        ) as client:
            results.append(
                await client.call_tool(
                    "start_daily_track",
                    {"run_id": run_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for index in range(4):
            task_group.start_soon(start, index)
    return results


async def _concurrent_capacity_start(
    settings: CoreSettings,
    tmp_path: Path,
    *,
    run_ids: tuple[str, str],
) -> list[object]:
    results: list[object] = []

    async def start(index: int) -> None:
        async with _mcp_client(
            settings,
            tmp_path / f"track-capacity-{index}.stderr.log",
        ) as client:
            results.append(
                await client.call_tool(
                    "start_daily_track",
                    {
                        "run_id": run_ids[index],
                        "request_id": f"track-capacity-{index}",
                    },
                )
            )

    async with anyio.create_task_group() as task_group:
        for index in range(2):
            task_group.start_soon(start, index)
    return results


def _run_tracking_worker_once(
    settings: CoreSettings,
    execution_memory_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = _core_environment(settings)
    if execution_memory_bytes is not None:
        environment["THESISTRACE_TRACKING_WORKER_EXECUTION_MEMORY_BYTES"] = str(
            execution_memory_bytes
        )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            "tracking",
            "--once",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path.cwd(),
        env={**os.environ, **environment},
    )


async def _assert_transient_daily_track_reads(
    settings: CoreSettings,
    tmp_path: Path,
    track_id: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("LOCK TABLE daily_tracks.tracks IN ACCESS EXCLUSIVE MODE")
            async with _mcp_client(
                settings,
                tmp_path / "track-transient-read.stderr.log",
                environment={"PGOPTIONS": "-c statement_timeout=100ms"},
            ) as client:
                transient_list = await client.call_tool("list_daily_tracks", {"limit": 1})
                transient_get = await client.call_tool(
                    "get_daily_track",
                    {"track_id": track_id},
                )
            for transient in (transient_list, transient_get):
                assert transient.is_error is True
                assert transient.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
                assert transient.structured_content["retryable"] is True
                assert transient.structured_content["retry_after_seconds"] == 2
                assert transient.structured_content["trace_id"]
    finally:
        database.close()


def _install_transient_start_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION research_runs.reject_mcp_start_transiently()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'injected DailyTrack start dependency failure'
                        USING ERRCODE = '08006';
                END
                $$;
                CREATE TRIGGER reject_mcp_start_transiently
                BEFORE INSERT ON research_runs.start_tracking_receipts
                FOR EACH ROW
                EXECUTE FUNCTION research_runs.reject_mcp_start_transiently();
                """
            )
    finally:
        database.close()


def _remove_transient_start_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_mcp_start_transiently
                    ON research_runs.start_tracking_receipts;
                DROP FUNCTION research_runs.reject_mcp_start_transiently();
                """
            )
    finally:
        database.close()


def _start_tracking_storage(
    settings: CoreSettings,
    run_id: str,
    request_id: str,
) -> tuple[int, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            tracks = transaction.execute(
                "SELECT count(*) AS count FROM daily_tracks.tracks WHERE seed_run_id = %s",
                (run_id,),
            ).fetchone()
            receipts = transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_runs.start_tracking_receipts
                WHERE request_id = %s
                """,
                (request_id,),
            ).fetchone()
        assert tracks is not None
        assert receipts is not None
        return int(tracks["count"]), int(receipts["count"])
    finally:
        database.close()


def _corrupt_track_origin(settings: CoreSettings, track_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT origin FROM daily_tracks.tracks WHERE id = %s",
                (track_id,),
            ).fetchone()
            assert row is not None
            transaction.execute(
                "UPDATE daily_tracks.tracks SET origin = '{}'::jsonb WHERE id = %s",
                (track_id,),
            )
        return dict(row["origin"])
    finally:
        database.close()


def _restore_track_origin(
    settings: CoreSettings,
    track_id: str,
    origin: dict[str, object],
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                "UPDATE daily_tracks.tracks SET origin = %s WHERE id = %s",
                (Jsonb(origin), track_id),
            )
    finally:
        database.close()


def _seed_active_capacity_clones(
    settings: CoreSettings,
    *,
    source_track_id: str,
    count: int,
) -> None:
    _clone_tracks(
        settings,
        source_track_id=source_track_id,
        prefix="track_capacity_clone",
        count=count,
        status="active",
    )


def _seed_tied_stopped_history(
    settings: CoreSettings,
    *,
    source_track_id: str,
    count: int,
) -> list[str]:
    _clone_tracks(
        settings,
        source_track_id=source_track_id,
        prefix="track_history",
        count=count,
        status="stopped",
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                "UPDATE daily_tracks.tracks SET created_at = '2026-08-27T00:00:00Z'"
            )
            rows = transaction.execute(
                """
                SELECT id
                FROM daily_tracks.tracks
                ORDER BY created_at DESC, id
                """
            ).fetchall()
        return [str(row["id"]) for row in rows]
    finally:
        database.close()


def _clone_tracks(
    settings: CoreSettings,
    *,
    source_track_id: str,
    prefix: str,
    count: int,
    status: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            source = transaction.execute(
                """
                SELECT track.origin, state.origin_session,
                       checkpoint.terminal_strategy_state,
                       checkpoint.data_generation_id,
                       checkpoint.provenance
                FROM daily_tracks.tracks AS track
                JOIN daily_tracks.session_tracking_states AS state
                  ON state.track_id = track.id
                JOIN daily_tracks.session_checkpoints AS checkpoint
                  ON checkpoint.track_id = track.id
                 AND checkpoint.manifest_sha256 = state.current_checkpoint_manifest_sha256
                WHERE track.id = %s
                """,
                (source_track_id,),
            ).fetchone()
            assert source is not None
            for index in range(count):
                track_id = f"{prefix}_{index:03d}"
                seed_run_id = f"run_{prefix}_{index:03d}"
                manifest = hashlib.sha256(track_id.encode()).hexdigest()
                origin = {
                    **source["origin"],
                    "seed_run_id": seed_run_id,
                }
                transaction.execute(
                    """
                    INSERT INTO daily_tracks.tracks (
                        id, status, seed_run_id, origin
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (track_id, status, seed_run_id, Jsonb(origin)),
                )
                transaction.execute(
                    """
                    INSERT INTO daily_tracks.session_checkpoints (
                        manifest_sha256, track_id, progression_id,
                        predecessor_manifest_sha256, boundary_session,
                        terminal_strategy_state, data_generation_id, provenance
                    ) VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s)
                    """,
                    (
                        manifest,
                        track_id,
                        source["origin_session"],
                        Jsonb(source["terminal_strategy_state"]),
                        source["data_generation_id"],
                        Jsonb(source["provenance"]),
                    ),
                )
                transaction.execute(
                    """
                    INSERT INTO daily_tracks.session_tracking_states (
                        track_id, origin_session,
                        origin_checkpoint_manifest_sha256,
                        current_checkpoint_manifest_sha256
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (track_id, source["origin_session"], manifest, manifest),
                )
    finally:
        database.close()


def _assert_compact_track(payload: dict[str, object], *, retry: bool = False) -> None:
    serialized = str(payload).lower()
    assert payload["available_result_sections"] == [
        "factor",
        "strategy_summary",
        "strategy_observations",
        "origin",
        "provenance",
    ]
    assert payload["action_eligibility"] == {"retry": retry, "stop": True}
    for private_name in (
        "positions",
        "checkpoint",
        "attempt",
        "lease",
        "fence",
        "manifest",
        "object_key",
        "sql",
        "path",
    ):
        assert private_name not in serialized

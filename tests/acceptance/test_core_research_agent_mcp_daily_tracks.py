from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from base64 import urlsafe_b64decode
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from threading import Event

import anyio
import pytest
from core_runtime import drop_product_schemas, isolated_core_settings
from psycopg.errors import CheckViolation, ForeignKeyViolation
from psycopg.types.json import Jsonb
from research_agent_mcp_runtime import (
    assert_worker_succeeded,
    core_environment,
    publish_current_data,
    run_research_worker_once,
)
from test_core_research_agent_mcp_runs import _command, _mcp_client

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import DailyTrackService
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.research_agent_mcp import TRACKING_STOP_ENABLE_ENVIRONMENT
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_run.result import read_result_bundle

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
        publish_current_data(settings)
        anyio.run(_exercise_daily_tracks, settings, tmp_path)
    finally:
        drop_product_schemas(settings)


def test_daily_track_action_receipts_reject_malformed_durable_outcomes(tmp_path: Path) -> None:
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
        for table, allowed_status in (
            ("retry_receipts", "active"),
            ("stop_receipts", "stopped"),
        ):
            malformed_actions = (
                {**valid, "status": None},
                {**valid, "status": "invalid"},
                {**valid, "status": allowed_status, "result_checksum_sha256": {}},
                {**valid, "status": allowed_status, "origin_session": "invalid"},
            )
            for index, outcome in enumerate(malformed_actions):
                with pytest.raises(CheckViolation):
                    with database.transaction() as transaction:
                        if table == "retry_receipts":
                            transaction.execute(
                                """
                                INSERT INTO daily_tracks.retry_receipts (
                                    request_id, request_fingerprint, track_id,
                                    progression_id, outcome
                                ) VALUES (%s, %s, %s, %s, %s)
                                """,
                                (
                                    f"malformed_retry_{index}",
                                    "f" * 64,
                                    "track_missing",
                                    "progression_missing",
                                    Jsonb(outcome),
                                ),
                            )
                        else:
                            transaction.execute(
                                """
                                INSERT INTO daily_tracks.stop_receipts (
                                    request_id, request_fingerprint, track_id, outcome
                                ) VALUES (%s, %s, %s, %s)
                                """,
                                (
                                    f"malformed_stop_{index}",
                                    "f" * 64,
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
            command = _command(f"track-strategy-{index}")
            if index in (0, 3):
                command["holdings_count"] = 51
            if index in (0, 3):
                command["end_date"] = "2026-08-10"
            response = await client.call_tool(
                "submit_research_run",
                command,
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
        completed = await anyio.to_thread.run_sync(run_research_worker_once, settings)
        assert_worker_succeeded(completed)

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
        assert "retry_daily_track" in tools
        assert "stop_daily_track" not in tools
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
            corrupted_result = await client.call_tool(
                "get_daily_track_result",
                {"track_id": track_id, "section": "factor"},
            )
        finally:
            _restore_track_origin(settings, track_id, original_origin)
        for corrupted_read in (corrupted, corrupted_result):
            assert corrupted_read.is_error is True
            assert corrupted_read.structured_content["code"] == "INTERNAL"
            assert corrupted_read.structured_content["retryable"] is False
            assert "origin" not in corrupted_read.structured_content["message"].lower()

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
        transient_origin_before = await client.call_tool(
            "get_daily_track_result",
            {"track_id": transient_track_id, "section": "origin", "limit": 50},
        )
        assert transient_origin_before.is_error is False
        assert len(transient_origin_before.structured_content["positions"]) == 50
        transient_origin_cursor = transient_origin_before.structured_content["next_cursor"]
        assert isinstance(transient_origin_cursor, str)
        transient_seed_summary = await client.call_tool(
            "get_daily_track_result",
            {"track_id": transient_track_id, "section": "strategy_summary"},
        )
        assert transient_seed_summary.is_error is False
        transient_seed_summary_keys = set(
            transient_seed_summary.structured_content["summary"]
        )
        transient_seed_observations = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": transient_track_id,
                "section": "strategy_observations",
                "limit": 1,
            },
        )
        assert transient_seed_observations.is_error is False
        stale_observation_cursor = transient_seed_observations.structured_content["next_cursor"]
        assert isinstance(stale_observation_cursor, str)
        missing_result = await client.call_tool(
            "get_daily_track_result",
            {"track_id": "track_missing", "section": "factor"},
        )
        assert missing_result.is_error is True
        assert missing_result.structured_content["code"] == "NOT_FOUND"
        invalid_result_section = await client.call_tool(
            "get_daily_track_result",
            {"track_id": transient_track_id, "section": "checkpoint"},
        )
        assert invalid_result_section.is_error is True
        assert invalid_result_section.structured_content["code"] == "INVALID_INPUT"

    blocked_worker = await anyio.to_thread.run_sync(
        _run_tracking_worker_once,
        settings,
        1,
    )
    assert_worker_succeeded(blocked_worker)
    second_blocked_worker = await anyio.to_thread.run_sync(
        _run_tracking_worker_once,
        settings,
        1,
    )
    assert_worker_succeeded(second_blocked_worker)
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
        blocked_factor = await client.call_tool(
            "get_daily_track_result",
            {"track_id": concurrent_track_id, "section": "factor"},
        )
        assert blocked_factor.is_error is False
        second_blocked = await client.call_tool(
            "get_daily_track",
            {"track_id": track_id},
        )
        assert second_blocked.structured_content["progress"]["phase"] == "blocked"
        _assert_retry_receipt_rejects_cross_track_progression(
            settings,
            track_id=track_id,
            other_track_id=concurrent_track_id,
        )
        denied_stop = await client.call_tool(
            "stop_daily_track",
            {"track_id": track_id, "request_id": "track-stop"},
        )
        assert denied_stop.is_error is True
        assert denied_stop.structured_content["code"] == "FORBIDDEN"
        retry_storage_before = _daily_track_action_storage(
            settings,
            concurrent_track_id,
            request_id="track-retry-transient",
            action="retry",
        )
        assert retry_storage_before["receipt_count"] == 0
        _install_transient_retry_failure(settings)
        try:
            transient_retry = await client.call_tool(
                "retry_daily_track",
                {
                    "track_id": concurrent_track_id,
                    "request_id": "track-retry-transient",
                },
            )
        finally:
            _remove_transient_retry_failure(settings)
        assert transient_retry.is_error is True
        assert transient_retry.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
        assert (
            _daily_track_action_storage(
                settings,
                concurrent_track_id,
                request_id="track-retry-transient",
                action="retry",
            )
            == retry_storage_before
        )
        retry_rollback = await client.call_tool(
            "get_daily_track",
            {"track_id": concurrent_track_id},
        )
        assert retry_rollback.structured_content["progress"]["phase"] == "blocked"

    async with _mcp_client(
        settings,
        tmp_path / "track-retry-still-blocked.stderr.log",
        environment={"THESISTRACE_TRACKING_WORKER_EXECUTION_MEMORY_BYTES": "1"},
    ) as client:
        unchanged_retry = await client.call_tool(
            "retry_daily_track",
            {"track_id": concurrent_track_id, "request_id": "track-retry-transient"},
        )
        assert unchanged_retry.is_error is False
        assert unchanged_retry.structured_content == {
            "outcome": "accepted",
            "track_id": concurrent_track_id,
            "status": "blocked",
            "replayed": False,
            "retry_after_seconds": None,
        }

    async with _mcp_client(
        settings,
        tmp_path / "track-retry-still-blocked-restart.stderr.log",
        environment={"THESISTRACE_TRACKING_WORKER_EXECUTION_MEMORY_BYTES": "1"},
    ) as client:
        unchanged_retry_replay = await client.call_tool(
            "retry_daily_track",
            {"track_id": concurrent_track_id, "request_id": "track-retry-transient"},
        )
        assert unchanged_retry_replay.structured_content == {
            **unchanged_retry.structured_content,
            "replayed": True,
        }
    assert (
        _daily_track_action_storage(
            settings,
            concurrent_track_id,
            request_id="track-retry-transient",
            action="retry",
        )["receipt_count"]
        == 1
    )

    retried = await _concurrent_retry(
        settings,
        tmp_path,
        track_id=concurrent_track_id,
        request_id="track-retry-scheduled",
    )
    assert all(not result.is_error for result in retried)
    assert all(result.structured_content["status"] == "active" for result in retried)
    assert all(result.structured_content["retry_after_seconds"] == 2 for result in retried)
    assert sum(result.structured_content["replayed"] is False for result in retried) == 1
    await _exercise_live_tracking_stop(
        settings,
        tmp_path,
        track_id=concurrent_track_id,
    )
    async with _mcp_client(settings, tmp_path / "track-retry-conflict.stderr.log") as client:
        retry_conflict = await client.call_tool(
            "retry_daily_track",
            {"track_id": track_id, "request_id": "track-retry-scheduled"},
        )
        assert retry_conflict.is_error is True
        assert retry_conflict.structured_content["code"] == "IDEMPOTENCY_CONFLICT"
        still_blocked = await client.call_tool("get_daily_track", {"track_id": track_id})
        assert still_blocked.structured_content["progress"]["phase"] == "blocked"

    _install_transient_stop_failure(settings)
    stop_storage_before = _daily_track_action_storage(
        settings,
        track_id,
        request_id="track-stop-transient",
        action="stop",
    )
    assert stop_storage_before["receipt_count"] == 0
    try:
        async with _mcp_client(
            settings,
            tmp_path / "track-stop-transient.stderr.log",
            environment={TRACKING_STOP_ENABLE_ENVIRONMENT: "true"},
        ) as client:
            transient_stop = await client.call_tool(
                "stop_daily_track",
                {"track_id": track_id, "request_id": "track-stop-transient"},
            )
    finally:
        _remove_transient_stop_failure(settings)
    assert transient_stop.is_error is True
    assert transient_stop.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
    assert (
        _daily_track_action_storage(
            settings,
            track_id,
            request_id="track-stop-transient",
            action="stop",
        )
        == stop_storage_before
    )
    async with _mcp_client(settings, tmp_path / "track-stop-rollback.stderr.log") as client:
        stop_rollback = await client.call_tool("get_daily_track", {"track_id": track_id})
        assert stop_rollback.structured_content["progress"]["phase"] == "blocked"

    stopped = await _concurrent_stop(
        settings,
        tmp_path,
        track_id=track_id,
        request_id="track-stop-transient",
    )
    assert all(not result.is_error for result in stopped)
    assert all(result.structured_content["status"] == "stopped" for result in stopped)
    assert sum(result.structured_content["replayed"] is False for result in stopped) == 1
    assert (
        _daily_track_action_storage(
            settings,
            track_id,
            request_id="track-stop-transient",
            action="stop",
        )["receipt_count"]
        == 1
    )

    for _ in range(6):
        completed = await anyio.to_thread.run_sync(_run_tracking_worker_once, settings)
        assert_worker_succeeded(completed)

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
        assert advanced.structured_content["progress"]["phase"] == "stopped"
        assert blocked_after_restart.structured_content["progress"]["phase"] == "stopped"
        assert blocked_after_restart.structured_content["progress"]["lag_sessions"] > 0
        assert transient_advanced.structured_content["progress"]["phase"] == "up_to_date"
        assert advanced.structured_content["origin"]["research_run_id"] == strategy_runs[0]
        assert advanced.structured_content["action_eligibility"] == {
            "retry": False,
            "stop": False,
        }

        stale_cursor = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": transient_track_id,
                "section": "strategy_observations",
                "cursor": stale_observation_cursor,
                "limit": 1,
            },
        )
        assert stale_cursor.is_error is True
        assert stale_cursor.structured_content["code"] == "INVALID_INPUT"

        factor_result = await client.call_tool(
            "get_daily_track_result",
            {"track_id": transient_track_id, "section": "factor"},
        )
        summary_result = await client.call_tool(
            "get_daily_track_result",
            {"track_id": transient_track_id, "section": "strategy_summary"},
        )
        provenance_result = await client.call_tool(
            "get_daily_track_result",
            {"track_id": transient_track_id, "section": "provenance"},
        )
        assert factor_result.is_error is False
        assert summary_result.is_error is False
        assert provenance_result.is_error is False
        assert (
            factor_result.structured_content["strategy_session"]
            == (transient_advanced.structured_content["progress"]["head_session"])
        )
        assert summary_result.structured_content["origin_session"] == "2026-08-10"
        assert (
            summary_result.structured_content["strategy_session"]
            == (transient_advanced.structured_content["progress"]["head_session"])
        )
        assert summary_result.structured_content["comparison"]["status"] == "available"
        assert summary_result.structured_content["comparison"]["benchmark"]["id"] == (
            "csi300-price-index-open"
        )
        assert "curves" not in summary_result.structured_content["comparison"]
        assert set(summary_result.structured_content["summary"]) == (
            transient_seed_summary_keys
        )
        _assert_finite_result(factor_result.structured_content)
        _assert_finite_result(summary_result.structured_content)
        serialized_provenance = json.dumps(
            provenance_result.structured_content,
            sort_keys=True,
        ).lower()
        for private_name in (
            "generation_id",
            "manifest",
            "object_key",
            "cache",
            "checkpoint",
            "attempt",
            "lease",
            "sql",
            "path",
        ):
            assert private_name not in serialized_provenance
        assert provenance_result.structured_content["origin_research_run_id"] == strategy_runs[3]
        assert provenance_result.structured_content["frozen_research_input"]["formula"] == "close"

        observation_pages = []
        observation_cursor = None
        while True:
            page = await client.call_tool(
                "get_daily_track_result",
                {
                    "track_id": transient_track_id,
                    "section": "strategy_observations",
                    "limit": 50,
                    **({"cursor": observation_cursor} if observation_cursor else {}),
                },
            )
            assert page.is_error is False
            assert len(json.dumps(page.structured_content).encode()) < 64 * 1024
            observation_pages.extend(page.structured_content["items"])
            observation_cursor = page.structured_content["next_cursor"]
            if observation_cursor is None:
                break
        observation_sessions = [item["session"] for item in observation_pages]
        assert len(observation_sessions) == 75
        assert observation_sessions == sorted(set(observation_sessions))
        _assert_finite_result(observation_pages)

        origin_first = await client.call_tool(
            "get_daily_track_result",
            {"track_id": track_id, "section": "origin", "limit": 50},
        )
        assert origin_first.is_error is False
        assert len(origin_first.structured_content["positions"]) == 50
        origin_cursor = origin_first.structured_content["next_cursor"]
        assert isinstance(origin_cursor, str)
        origin_second = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": track_id,
                "section": "origin",
                "cursor": origin_cursor,
                "limit": 50,
            },
        )
        assert origin_second.is_error is False
        assert len(origin_second.structured_content["positions"]) == 1
        assert origin_second.structured_content["next_cursor"] is None
        position_ids = [
            position["instrument_id"]
            for position in [
                *origin_first.structured_content["positions"],
                *origin_second.structured_content["positions"],
            ]
        ]
        assert position_ids == sorted(set(position_ids))

        wrong_section_cursor = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": transient_track_id,
                "section": "strategy_observations",
                "cursor": origin_cursor,
                "limit": 1,
            },
        )
        wrong_resource_cursor = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": concurrent_track_id,
                "section": "origin",
                "cursor": origin_cursor,
                "limit": 1,
            },
        )
        tampered_cursor = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": track_id,
                "section": "origin",
                "cursor": origin_cursor[:-1] + ("A" if origin_cursor[-1] != "A" else "B"),
                "limit": 1,
            },
        )
        for invalid_cursor in (
            wrong_section_cursor,
            wrong_resource_cursor,
            tampered_cursor,
        ):
            assert invalid_cursor.is_error is True
            assert invalid_cursor.structured_content["code"] == "INVALID_INPUT"

        transient_origin_after = await client.call_tool(
            "get_daily_track_result",
            {"track_id": transient_track_id, "section": "origin", "limit": 50},
        )
        assert {
            name: value
            for name, value in transient_origin_after.structured_content.items()
            if name != "next_cursor"
        } == {
            name: value
            for name, value in transient_origin_before.structured_content.items()
            if name != "next_cursor"
        }
        assert isinstance(transient_origin_after.structured_content["next_cursor"], str)
        transient_origin_continuation = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": transient_track_id,
                "section": "origin",
                "cursor": transient_origin_cursor,
                "limit": 50,
            },
        )
        assert transient_origin_continuation.is_error is False
        assert len(transient_origin_continuation.structured_content["positions"]) == 1
        assert transient_origin_continuation.structured_content["next_cursor"] is None

        retry_replay_after_restart = await client.call_tool(
            "retry_daily_track",
            {"track_id": concurrent_track_id, "request_id": "track-retry-scheduled"},
        )
        assert retry_replay_after_restart.is_error is False
        assert retry_replay_after_restart.structured_content["replayed"] is True

    async with _mcp_client(
        settings,
        tmp_path / "track-stop-replay.stderr.log",
        environment={TRACKING_STOP_ENABLE_ENVIRONMENT: "true"},
    ) as client:
        stop_replay_after_restart = await client.call_tool(
            "stop_daily_track",
            {"track_id": track_id, "request_id": "track-stop-transient"},
        )
        assert stop_replay_after_restart.is_error is False
        assert stop_replay_after_restart.structured_content["status"] == "stopped"
        assert stop_replay_after_restart.structured_content["replayed"] is True
        stop_conflict = await client.call_tool(
            "stop_daily_track",
            {"track_id": transient_track_id, "request_id": "track-stop-transient"},
        )
        assert stop_conflict.is_error is True
        assert stop_conflict.structured_content["code"] == "IDEMPOTENCY_CONFLICT"

    _seed_active_capacity_clones(settings, source_track_id=track_id, count=8)
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


async def _concurrent_retry(
    settings: CoreSettings,
    tmp_path: Path,
    *,
    track_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def retry(index: int) -> None:
        async with _mcp_client(
            settings,
            tmp_path / f"track-concurrent-retry-{index}.stderr.log",
        ) as client:
            results.append(
                await client.call_tool(
                    "retry_daily_track",
                    {"track_id": track_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for index in range(4):
            task_group.start_soon(retry, index)
    return results


async def _concurrent_stop(
    settings: CoreSettings,
    tmp_path: Path,
    *,
    track_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def stop(index: int) -> None:
        async with _mcp_client(
            settings,
            tmp_path / f"track-concurrent-stop-{index}.stderr.log",
            environment={TRACKING_STOP_ENABLE_ENVIRONMENT: "true"},
        ) as client:
            results.append(
                await client.call_tool(
                    "stop_daily_track",
                    {"track_id": track_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for index in range(4):
            task_group.start_soon(stop, index)
    return results


async def _exercise_live_tracking_stop(
    settings: CoreSettings,
    tmp_path: Path,
    *,
    track_id: str,
) -> None:
    _prioritize_daily_track(settings, track_id)
    prepared = Event()
    release_prepared = Event()
    cooperative_stop_requested = Event()
    release_cooperative_stop = Event()
    execution_events: list[dict[str, object]] = []

    def progress(stage: str, selected_track_id: str, _target: str) -> None:
        if stage == "prepared" and selected_track_id == track_id:
            prepared.set()
            assert release_prepared.wait(timeout=10)

    def capture_execution_event(event: dict[str, object]) -> None:
        execution_events.append(event)
        if event.get("event") == "tracking_execution_child_stop_requested":
            cooperative_stop_requested.set()
            assert release_cooperative_stop.wait(timeout=10)

    with open_core_runtime(settings) as runtime:
        processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=partial(
                read_result_bundle,
                research_kind="strategy_backtest",
            ),
            progress=progress,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                processor.process_next,
                on_execution_event=capture_execution_event,
            )
            assert await anyio.to_thread.run_sync(prepared.wait, 10)
            async with _mcp_client(
                settings,
                tmp_path / "track-live-stop.stderr.log",
                environment={TRACKING_STOP_ENABLE_ENVIRONMENT: "true"},
            ) as client:
                retry_during_claim = await client.call_tool(
                    "retry_daily_track",
                    {"track_id": track_id, "request_id": "track-retry-during-claim"},
                )
                assert retry_during_claim.is_error is True
                assert retry_during_claim.structured_content["code"] == "STATE_CONFLICT"

                stopping = await client.call_tool(
                    "stop_daily_track",
                    {"track_id": track_id, "request_id": "track-live-stop"},
                )
                assert stopping.is_error is False
                assert stopping.structured_content == {
                    "outcome": "accepted",
                    "track_id": track_id,
                    "status": "stopping",
                    "replayed": False,
                    "retry_after_seconds": 2,
                }
                retry_while_stopping = await client.call_tool(
                    "retry_daily_track",
                    {"track_id": track_id, "request_id": "track-retry-while-stopping"},
                )
                assert retry_while_stopping.is_error is True
                assert retry_while_stopping.structured_content["code"] == "STATE_CONFLICT"
                fresh_stop_while_stopping = await client.call_tool(
                    "stop_daily_track",
                    {"track_id": track_id, "request_id": "track-stop-while-stopping"},
                )
                assert fresh_stop_while_stopping.is_error is True
                assert fresh_stop_while_stopping.structured_content["code"] == "STATE_CONFLICT"
                stopping_detail = await client.call_tool(
                    "get_daily_track",
                    {"track_id": track_id},
                )
                assert stopping_detail.is_error is False
                assert stopping_detail.structured_content["status"] == "stopping"
                assert stopping_detail.structured_content["progress"]["phase"] == "stopping"
                assert stopping_detail.structured_content["retry_after_seconds"] == 2

            assert await anyio.to_thread.run_sync(cooperative_stop_requested.wait, 5)
            release_cooperative_stop.set()
            release_prepared.set()
            assert await anyio.to_thread.run_sync(future.result, 20) is True

    assert any(
        event.get("event") == "tracking_execution_child_exited" for event in execution_events
    )
    async with _mcp_client(
        settings,
        tmp_path / "track-live-stop-restart.stderr.log",
        environment={TRACKING_STOP_ENABLE_ENVIRONMENT: "true"},
    ) as client:
        terminal = await client.call_tool("get_daily_track", {"track_id": track_id})
        assert terminal.is_error is False
        assert terminal.structured_content["status"] == "stopped"
        assert terminal.structured_content["progress"]["phase"] == "stopped"
        assert terminal.structured_content["retry_after_seconds"] is None
        retry_stopped = await client.call_tool(
            "retry_daily_track",
            {"track_id": track_id, "request_id": "track-retry-stopped"},
        )
        assert retry_stopped.is_error is True
        assert retry_stopped.structured_content["code"] == "STATE_CONFLICT"
        replay = await client.call_tool(
            "stop_daily_track",
            {"track_id": track_id, "request_id": "track-live-stop"},
        )
        assert replay.is_error is False
        assert replay.structured_content == {
            **stopping.structured_content,
            "replayed": True,
        }


def _prioritize_daily_track(settings: CoreSettings, track_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            track = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET queue_position = 0
                WHERE id = %s AND status = 'active'
                """,
                (track_id,),
            )
            progression = transaction.execute(
                """
                UPDATE daily_tracks.session_progressions
                SET queue_position = 0, next_attempt_eligible_at = now()
                WHERE track_id = %s AND status = 'running'
                """,
                (track_id,),
            )
        assert track.rowcount == 1
        assert progression.rowcount == 1
    finally:
        database.close()


def _run_tracking_worker_once(
    settings: CoreSettings,
    execution_memory_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = core_environment(settings)
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
                transient_result = await client.call_tool(
                    "get_daily_track_result",
                    {"track_id": track_id, "section": "factor"},
                )
            for transient in (transient_list, transient_get, transient_result):
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


def _install_transient_retry_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION daily_tracks.reject_mcp_retry_transiently()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'injected DailyTrack Retry dependency failure'
                        USING ERRCODE = '08006';
                END
                $$;
                CREATE TRIGGER reject_mcp_retry_transiently
                BEFORE INSERT ON daily_tracks.retry_receipts
                FOR EACH ROW
                EXECUTE FUNCTION daily_tracks.reject_mcp_retry_transiently();
                """
            )
    finally:
        database.close()


def _remove_transient_retry_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_mcp_retry_transiently ON daily_tracks.retry_receipts;
                DROP FUNCTION daily_tracks.reject_mcp_retry_transiently();
                """
            )
    finally:
        database.close()


def _install_transient_stop_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION daily_tracks.reject_mcp_stop_transiently()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'injected DailyTrack Stop dependency failure'
                        USING ERRCODE = '08006';
                END
                $$;
                CREATE TRIGGER reject_mcp_stop_transiently
                BEFORE INSERT ON daily_tracks.stop_receipts
                FOR EACH ROW
                EXECUTE FUNCTION daily_tracks.reject_mcp_stop_transiently();
                """
            )
    finally:
        database.close()


def _remove_transient_stop_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_mcp_stop_transiently ON daily_tracks.stop_receipts;
                DROP FUNCTION daily_tracks.reject_mcp_stop_transiently();
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


def _daily_track_action_storage(
    settings: CoreSettings,
    track_id: str,
    *,
    request_id: str,
    action: str,
) -> dict[str, object]:
    assert action in {"retry", "stop"}
    receipt_table = (
        "daily_tracks.retry_receipts" if action == "retry" else "daily_tracks.stop_receipts"
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            track = transaction.execute(
                """
                SELECT status, execution_fence, blocked_progression_id,
                       blocked_reason, queue_position
                FROM daily_tracks.tracks
                WHERE id = %s
                """,
                (track_id,),
            ).fetchone()
            progressions = transaction.execute(
                """
                SELECT id, status, current_cycle_ordinal,
                       next_attempt_eligible_at, queue_position, finished_at
                FROM daily_tracks.session_progressions
                WHERE track_id = %s
                ORDER BY id
                """,
                (track_id,),
            ).fetchall()
            attempts = transaction.execute(
                """
                SELECT id, status, fence, heartbeat_at, finished_at, failure_reason
                FROM daily_tracks.session_progression_attempts
                WHERE track_id = %s
                ORDER BY id
                """,
                (track_id,),
            ).fetchall()
            receipt = transaction.execute(
                f"SELECT count(*) AS count FROM {receipt_table} WHERE request_id = %s",
                (request_id,),
            ).fetchone()
        assert track is not None
        assert receipt is not None
        return {
            "track": dict(track),
            "progressions": [dict(row) for row in progressions],
            "attempts": [dict(row) for row in attempts],
            "receipt_count": int(receipt["count"]),
        }
    finally:
        database.close()


def _assert_retry_receipt_rejects_cross_track_progression(
    settings: CoreSettings,
    *,
    track_id: str,
    other_track_id: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            track = transaction.execute(
                """
                SELECT track.id, track.status, track.seed_run_id,
                       track.origin -> 'verified_result' ->> 'result_checksum_sha256'
                           AS result_checksum_sha256,
                       state.origin_session,
                       checkpoint.boundary_session AS strategy_session
                FROM daily_tracks.tracks AS track
                JOIN daily_tracks.session_tracking_states AS state
                  ON state.track_id = track.id
                JOIN daily_tracks.session_checkpoints AS checkpoint
                  ON checkpoint.track_id = state.track_id
                 AND checkpoint.manifest_sha256 = state.current_checkpoint_manifest_sha256
                WHERE track.id = %s
                """,
                (track_id,),
            ).fetchone()
            other_progression = transaction.execute(
                """
                SELECT id
                FROM daily_tracks.session_progressions
                WHERE track_id = %s
                ORDER BY id
                LIMIT 1
                """,
                (other_track_id,),
            ).fetchone()
        assert track is not None
        assert other_progression is not None
        outcome = {
            "id": str(track["id"]),
            "status": str(track["status"]),
            "seed_run_id": str(track["seed_run_id"]),
            "result_checksum_sha256": str(track["result_checksum_sha256"]),
            "origin_session": track["origin_session"].isoformat(),
            "strategy_session": track["strategy_session"].isoformat(),
        }
        with pytest.raises(ForeignKeyViolation):
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    INSERT INTO daily_tracks.retry_receipts (
                        request_id, request_fingerprint, track_id,
                        progression_id, outcome
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        "cross-track-progression",
                        "f" * 64,
                        track_id,
                        other_progression["id"],
                        Jsonb(outcome),
                    ),
                )
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


def _assert_finite_result(value: object) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
        return
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_result(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_finite_result(item)

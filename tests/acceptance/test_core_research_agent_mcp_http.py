from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from itertools import count
from multiprocessing import get_context
from pathlib import Path
from threading import Event

import anyio
import httpx2
import jwt
from core_runtime import drop_product_schemas, isolated_core_settings
from jsonschema import validate
from jwt import PyJWTError
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from test_core_research_agent_mcp_runs import (
    _assert_worker_succeeded,
    _core_environment,
)
from test_core_research_batch_fifo import (
    _release_claim_barrier_worker,
    _start_claim_barrier_worker,
    _terminate_worker,
    _wait_for_worker_event,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import DailyTrackService
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture, field_catalog
from thesistrace.operational_events import OperationalEvent
from thesistrace.research_agent import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentHTTPConfiguration,
    ResearchAgentScope,
)
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.execution import SupervisedResearchExecutor
from thesistrace.research_run.result import read_result_bundle

_ISSUER_URL = "https://issuer.test/"
_RESOURCE_URL = "https://core.test/mcp"
_TRUSTED_ORIGIN = "https://codex.test"
_TEST_NOW = 2_000_000_000
_SIGNING_KEY = "deterministic-local-oauth-signing-key"


class _DeterministicOAuthIssuer:
    def __init__(self) -> None:
        self._grant_overrides: dict[str, tuple[str, ...]] = {}
        self._token_ids = count()

    def issue(
        self,
        *,
        scopes: tuple[str, ...] = (ResearchAgentScope.RESEARCH_READ.value,),
        lifetime_seconds: int = 120,
        not_before_seconds: int = 0,
        issuer: str = _ISSUER_URL,
        audience: str = _RESOURCE_URL,
        signing_key: str = _SIGNING_KEY,
    ) -> str:
        return jwt.encode(
            {
                "iss": issuer,
                "aud": audience,
                "sub": "researcher_test",
                "client_id": "codex_test_client",
                "iat": _TEST_NOW,
                "nbf": _TEST_NOW + not_before_seconds,
                "exp": _TEST_NOW + lifetime_seconds,
                "jti": f"token_{next(self._token_ids)}",
                "scope": " ".join(scopes),
            },
            signing_key,
            algorithm="HS256",
        )

    def replace_grant(self, token: str, scopes: tuple[str, ...]) -> None:
        self._grant_overrides[token] = scopes

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                _SIGNING_KEY,
                algorithms=["HS256"],
                issuer=_ISSUER_URL,
                audience=_RESOURCE_URL,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "client_id",
                        "iat",
                        "nbf",
                        "exp",
                        "jti",
                        "scope",
                    ],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except PyJWTError:
            return None
        temporal_claims = (claims["iat"], claims["nbf"], claims["exp"])
        if any(type(value) is not int for value in temporal_claims):
            return None
        if claims["iat"] > _TEST_NOW or claims["nbf"] > _TEST_NOW:
            return None
        if claims["exp"] <= _TEST_NOW:
            return None
        if not isinstance(claims["scope"], str):
            return None
        scopes = self._grant_overrides.get(token, tuple(claims["scope"].split()))
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=list(scopes),
            expires_at=claims["exp"],
            resource=_RESOURCE_URL,
            subject=claims["sub"],
            claims={"iss": claims["iss"], "jti": claims["jti"]},
        )


def test_mounted_oauth_streamable_http_read_loop_and_fail_closed_boundaries(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path / "data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_current_data(settings)
    issuer = _DeterministicOAuthIssuer()
    events: list[OperationalEvent] = []
    app = _app(settings, issuer, events=events)
    try:
        anyio.run(_exercise_http_contract, app, issuer, settings)
        serialized_events = str(events)
        mcp_events = [event for event in events if event.component == "research_agent_mcp"]
        assert mcp_events
        assert all(event.context["transport"] == "streamable_http" for event in mcp_events)
        expected_subject = f"oauth_{sha256(b'researcher_test').hexdigest()[:32]}"
        assert all(event.context["subject"] == expected_subject for event in mcp_events)
        assert "researcher_test" not in serialized_events
        assert _SIGNING_KEY not in serialized_events
        assert "eyJ" not in serialized_events
    finally:
        drop_product_schemas(settings)


def test_http_discovery_intersects_deployment_allowlist_with_grant(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path / "allowlist-data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    issuer = _DeterministicOAuthIssuer()
    app = _app(
        settings,
        issuer,
        deployment_tool_allowlist=frozenset({"get_research_context"}),
    )
    try:
        anyio.run(
            _exercise_allowlist_intersection,
            app,
            issuer.issue(
                scopes=(
                    ResearchAgentScope.RESEARCH_READ.value,
                    ResearchAgentScope.RESEARCH_CANCEL.value,
                )
            ),
        )
    finally:
        drop_product_schemas(settings)


def _app(
    settings: CoreSettings,
    issuer: _DeterministicOAuthIssuer,
    *,
    deployment_tool_allowlist: frozenset[str] = RESEARCH_AGENT_TOOL_NAMES,
    events: list[OperationalEvent] | None = None,
):
    return create_app(
        settings,
        event_sink=(lambda _event: None) if events is None else events.append,
        enable_research_agent_http=True,
        research_agent_http=ResearchAgentHTTPConfiguration(
            token_verifier=issuer,
            issuer_url=_ISSUER_URL,
            resource_server_url=_RESOURCE_URL,
            deployment_tool_allowlist=deployment_tool_allowlist,
            allowed_hosts=("core.test",),
            allowed_origins=(_TRUSTED_ORIGIN,),
        ),
    )


async def _exercise_http_contract(
    app,
    issuer: _DeterministicOAuthIssuer,
    settings: CoreSettings,
) -> None:
    read_token = issuer.issue()
    action_scopes = (
        ResearchAgentScope.RESEARCH_READ.value,
        ResearchAgentScope.RESEARCH_EXECUTE.value,
        ResearchAgentScope.RESEARCH_CANCEL.value,
        ResearchAgentScope.TRACKING_READ.value,
        ResearchAgentScope.TRACKING_EXECUTE.value,
    )
    action_token = issuer.issue(scopes=action_scopes)
    stop_token = issuer.issue(scopes=(*action_scopes, ResearchAgentScope.TRACKING_STOP.value))
    no_grant_token = issuer.issue(scopes=())
    async with app.router.lifespan_context(app):
        await _assert_protected_resource_and_authentication_boundaries(
            app,
            issuer,
            read_token=read_token,
        )

        first_context: dict[str, object]
        async with _mcp_client(app, read_token) as client:
            tools = await client.list_tools()
            tools_by_name = {tool.name: tool for tool in tools.tools}
            assert set(tools_by_name) == RESEARCH_AGENT_TOOL_NAMES - {
                "submit_research_batch",
                "submit_research_run",
                "cancel_research_batch",
                "cancel_research_run",
                "list_daily_tracks",
                "get_daily_track",
                "start_daily_track",
                "retry_daily_track",
                "stop_daily_track",
            }

            context = await client.call_tool("get_research_context", {})
            assert context.is_error is False
            validate(
                context.structured_content,
                tools_by_name["get_research_context"].output_schema,
            )
            first_context = context.structured_content

            catalog = await client.call_tool(
                "get_alpha_catalog",
                {"identifiers": ["close", "ts_mean", "unknown_identifier"]},
            )
            assert catalog.is_error is False
            validate(catalog.structured_content, tools_by_name["get_alpha_catalog"].output_schema)
            assert catalog.structured_content["unknown_identifiers"] == ["unknown_identifier"]

            diagnostic = await client.call_tool(
                "diagnose_alpha_formula",
                {"source": "unknown_alpha + close"},
            )
            assert diagnostic.is_error is False
            validate(
                diagnostic.structured_content,
                tools_by_name["diagnose_alpha_formula"].output_schema,
            )
            assert diagnostic.structured_content["valid"] is False

            issuer.replace_grant(read_token, ())
            denied_after_discovery = await client.call_tool("get_research_context", {})
            assert denied_after_discovery.is_error is True
            assert denied_after_discovery.structured_content["code"] == "FORBIDDEN"
            issuer.replace_grant(read_token, (ResearchAgentScope.RESEARCH_READ.value,))

        async with _mcp_client(app, action_token) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(tools) == RESEARCH_AGENT_TOOL_NAMES - {"stop_daily_track"}
            cancel_tool = tools["cancel_research_run"]
            assert cancel_tool.annotations is not None
            assert cancel_tool.annotations.destructive_hint is True
            assert cancel_tool.annotations.idempotent_hint is True
            batch_cancel_tool = tools["cancel_research_batch"]
            assert batch_cancel_tool.annotations is not None
            assert batch_cancel_tool.annotations.destructive_hint is True
            assert batch_cancel_tool.annotations.idempotent_hint is True

            batch = await client.call_tool(
                "submit_research_batch",
                _batch_command("http-batch-cancel-target"),
            )
            assert batch.is_error is False
            assert batch.structured_content["status"] == "queued"
            batch_replay = await client.call_tool(
                "submit_research_batch",
                _batch_command("http-batch-cancel-target"),
            )
            assert (
                batch_replay.structured_content["batch_id"]
                == (batch.structured_content["batch_id"])
            )
            assert batch_replay.structured_content["replayed"] is True
            rejected_batch_command = {
                **_batch_command("http-batch-rejected"),
                "factors": [{"item_key": "invalid", "formula": "unknown_alpha"}],
            }
            rejected_batch = await client.call_tool(
                "submit_research_batch",
                rejected_batch_command,
            )
            rejected_batch_replay = await client.call_tool(
                "submit_research_batch",
                rejected_batch_command,
            )
            assert rejected_batch.structured_content["outcome"] == "rejected"
            assert rejected_batch.structured_content["replayed"] is False
            assert rejected_batch_replay.structured_content["replayed"] is True
            rejected_batch_conflict = await client.call_tool(
                "submit_research_batch",
                {
                    **rejected_batch_command,
                    "factors": [{"item_key": "changed", "formula": "close"}],
                },
            )
            assert rejected_batch_conflict.is_error is True
            assert rejected_batch_conflict.structured_content["code"] == ("IDEMPOTENCY_CONFLICT")
            concurrent_batch_command = _batch_command("http-batch-concurrent-accepted")
            concurrent_batch_results = await _concurrent_batch_submits(
                app,
                action_token,
                concurrent_batch_command,
            )
            assert all(not result.is_error for result in concurrent_batch_results)
            assert (
                len({result.structured_content["batch_id"] for result in concurrent_batch_results})
                == 1
            )
            assert (
                sum(
                    result.structured_content["replayed"] is False
                    for result in concurrent_batch_results
                )
                == 1
            )
            concurrent_rejected_command = {
                **_batch_command("http-batch-concurrent-rejected"),
                "factors": [{"item_key": "invalid", "formula": "unknown_alpha"}],
            }
            concurrent_rejected_results = await _concurrent_batch_submits(
                app,
                action_token,
                concurrent_rejected_command,
            )
            assert all(not result.is_error for result in concurrent_rejected_results)
            assert all(
                result.structured_content["outcome"] == "rejected"
                for result in concurrent_rejected_results
            )
            assert (
                sum(
                    result.structured_content["replayed"] is False
                    for result in concurrent_rejected_results
                )
                == 1
            )
            concurrent_submit_conflict = await client.call_tool(
                "submit_research_batch",
                {
                    **concurrent_batch_command,
                    "factors": [{"item_key": "changed", "formula": "open"}],
                },
            )
            assert concurrent_submit_conflict.is_error is True
            assert concurrent_submit_conflict.structured_content["code"] == ("IDEMPOTENCY_CONFLICT")
            unchanged_concurrent_batch = await client.call_tool(
                "get_research_batch",
                {"batch_id": concurrent_batch_results[0].structured_content["batch_id"]},
            )
            assert unchanged_concurrent_batch.structured_content["status"] == "queued"
            assert [
                item["item_key"] for item in unchanged_concurrent_batch.structured_content["items"]
            ] == ["value"]
            listed_batches = await client.call_tool(
                "list_research_batches",
                {"limit": 20},
            )
            assert {item["id"] for item in listed_batches.structured_content["items"]} == {
                batch.structured_content["batch_id"],
                concurrent_batch_results[0].structured_content["batch_id"],
            }
            batch_detail = await client.call_tool(
                "get_research_batch",
                {"batch_id": batch.structured_content["batch_id"]},
            )
            assert batch_detail.structured_content["items"][0]["item_key"] == "value"
            assert "result" not in batch_detail.structured_content
            assert batch_detail.structured_content["retry_after_seconds"] == 2

            batch_worker = _start_claim_barrier_worker(settings, "batch-research")
            try:
                await anyio.to_thread.run_sync(
                    _wait_for_worker_event,
                    batch_worker,
                    "worker_claim",
                )
                running_batch = await client.call_tool(
                    "get_research_batch",
                    {"batch_id": batch.structured_content["batch_id"]},
                )
                assert running_batch.structured_content["status"] == "running"
                assert running_batch.structured_content["retry_after_seconds"] == 2
                cancelled_batch = await client.call_tool(
                    "cancel_research_batch",
                    {
                        "batch_id": batch.structured_content["batch_id"],
                        "request_id": "http-batch-cancel-request",
                    },
                )
                assert cancelled_batch.is_error is False
                assert cancelled_batch.structured_content["batch"]["status"] == ("cancelling")
                assert cancelled_batch.structured_content["replayed"] is False
                assert cancelled_batch.structured_content["retry_after_seconds"] == 2
                concurrent_batch_replays = await _concurrent_batch_cancel_replays(
                    app,
                    action_token,
                    batch_id=str(batch.structured_content["batch_id"]),
                    request_id="http-batch-cancel-request",
                )
                assert all(not result.is_error for result in concurrent_batch_replays)
                assert all(
                    result.structured_content["batch"]
                    == cancelled_batch.structured_content["batch"]
                    for result in concurrent_batch_replays
                )
                assert all(
                    result.structured_content["replayed"] is True
                    for result in concurrent_batch_replays
                )
                batch_conflict_target = await client.call_tool(
                    "submit_research_batch",
                    _batch_command("http-batch-conflict-target"),
                )
                batch_cancel_conflict = await client.call_tool(
                    "cancel_research_batch",
                    {
                        "batch_id": batch_conflict_target.structured_content["batch_id"],
                        "request_id": "http-batch-cancel-request",
                    },
                )
                assert batch_cancel_conflict.is_error is True
                assert batch_cancel_conflict.structured_content["code"] == ("IDEMPOTENCY_CONFLICT")
                untouched_conflict_target = await client.call_tool(
                    "get_research_batch",
                    {"batch_id": batch_conflict_target.structured_content["batch_id"]},
                )
                assert untouched_conflict_target.structured_content["status"] == "queued"
                await anyio.to_thread.run_sync(
                    _release_claim_barrier_worker,
                    batch_worker,
                )
                batch_worker = None
            finally:
                if batch_worker is not None:
                    _terminate_worker(batch_worker)
            terminal_batch = await client.call_tool(
                "get_research_batch",
                {"batch_id": batch.structured_content["batch_id"]},
            )
            assert terminal_batch.structured_content["status"] == "cancelled"
            assert terminal_batch.structured_content["retry_after_seconds"] is None

            cancel_target = await client.call_tool(
                "submit_research_run",
                _research_command("http-cancel-target"),
            )
            conflict_target = await client.call_tool(
                "submit_research_run",
                _research_command("http-cancel-conflict-target"),
            )
            assert cancel_target.is_error is False
            assert conflict_target.is_error is False

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
                issuer.replace_grant(
                    action_token,
                    (
                        ResearchAgentScope.RESEARCH_READ.value,
                        ResearchAgentScope.RESEARCH_EXECUTE.value,
                    ),
                )
                denied_after_discovery = await client.call_tool(
                    "cancel_research_run",
                    {
                        "run_id": cancel_target.structured_content["run_id"],
                        "request_id": "http-cancel-request",
                    },
                )
                assert denied_after_discovery.is_error is True
                assert denied_after_discovery.structured_content["code"] == "FORBIDDEN"
                issuer.replace_grant(action_token, action_scopes)

                rejected_confirmation = await client.call_tool(
                    "cancel_research_run",
                    {
                        "run_id": cancel_target.structured_content["run_id"],
                        "request_id": "http-cancel-request",
                        "confirmation_token": "host-confirmation-is-not-authority",
                    },
                )
                assert rejected_confirmation.is_error is True
                assert rejected_confirmation.structured_content["code"] == "INVALID_INPUT"

                cancelled = await client.call_tool(
                    "cancel_research_run",
                    {
                        "run_id": cancel_target.structured_content["run_id"],
                        "request_id": "http-cancel-request",
                    },
                )
                assert cancelled.is_error is False
                assert cancelled.structured_content["run"]["status"] == "cancelling"
                assert cancelled.structured_content["replayed"] is False
                assert cancelled.structured_content["retry_after_seconds"] == 2

                concurrent_replays = await _concurrent_cancel_replays(
                    app,
                    action_token,
                    run_id=str(cancel_target.structured_content["run_id"]),
                    request_id="http-cancel-request",
                )
                assert all(not result.is_error for result in concurrent_replays)
                assert all(
                    result.structured_content["run"] == cancelled.structured_content["run"]
                    for result in concurrent_replays
                )
                assert all(
                    result.structured_content["replayed"] is True for result in concurrent_replays
                )

                idempotency_conflict = await client.call_tool(
                    "cancel_research_run",
                    {
                        "run_id": conflict_target.structured_content["run_id"],
                        "request_id": "http-cancel-request",
                    },
                )
                assert idempotency_conflict.is_error is True
                assert idempotency_conflict.structured_content["code"] == ("IDEMPOTENCY_CONFLICT")

                _install_transient_cancel_failure(settings)
                try:
                    temporarily_unavailable = await client.call_tool(
                        "cancel_research_run",
                        {
                            "run_id": conflict_target.structured_content["run_id"],
                            "request_id": "http-cancel-temporary",
                        },
                    )
                finally:
                    _remove_transient_cancel_failure(settings)
                assert temporarily_unavailable.is_error is True
                assert temporarily_unavailable.structured_content["code"] == (
                    "TEMPORARILY_UNAVAILABLE"
                )
                assert temporarily_unavailable.structured_content["retryable"] is True
                assert temporarily_unavailable.structured_content["retry_after_seconds"] == 2
                assert temporarily_unavailable.structured_content["trace_id"]

                conflict_state = await client.call_tool(
                    "get_research_run",
                    {"run_id": conflict_target.structured_content["run_id"]},
                )
                assert conflict_state.structured_content["status"] == "queued"

                missing = await client.call_tool(
                    "cancel_research_run",
                    {"run_id": "run_missing", "request_id": "http-cancel-missing"},
                )
                assert missing.is_error is True
                assert missing.structured_content["code"] == "NOT_FOUND"
            finally:
                release_worker.set()
                await _join_or_stop_worker_process(worker_process)
            assert worker_process.exitcode == 0

            stable_cancelled = await client.call_tool(
                "get_research_run",
                {"run_id": cancel_target.structured_content["run_id"]},
            )
            assert stable_cancelled.structured_content["status"] == "cancelled"
            terminal_conflict = await client.call_tool(
                "cancel_research_run",
                {
                    "run_id": cancel_target.structured_content["run_id"],
                    "request_id": "http-cancel-terminal",
                },
            )
            assert terminal_conflict.is_error is True
            assert terminal_conflict.structured_content["code"] == "STATE_CONFLICT"

            strategy = await client.call_tool(
                "submit_research_run",
                _strategy_command("http-track-origin"),
            )
            assert strategy.is_error is False
            assert (
                await anyio.to_thread.run_sync(app.state.core_runtime.research_runs.process_next)
                is True
            )
            assert (
                await anyio.to_thread.run_sync(app.state.core_runtime.research_runs.process_next)
                is True
            )
            daily_track = await client.call_tool(
                "start_daily_track",
                {
                    "run_id": strategy.structured_content["run_id"],
                    "request_id": "http-start-track",
                },
            )
            assert daily_track.is_error is False
            assert daily_track.structured_content == {
                "outcome": "accepted",
                "track_id": daily_track.structured_content["track_id"],
                "status": "active",
                "replayed": False,
                "retry_after_seconds": 30,
            }
            track_detail = await client.call_tool(
                "get_daily_track",
                {"track_id": daily_track.structured_content["track_id"]},
            )
            assert track_detail.is_error is False
            assert (
                track_detail.structured_content["origin"]["research_run_id"]
                == (strategy.structured_content["run_id"])
            )
            _assert_compact_track(track_detail.structured_content)
            duplicate_origin = await client.call_tool(
                "start_daily_track",
                {
                    "run_id": strategy.structured_content["run_id"],
                    "request_id": "http-start-track-different-command",
                },
            )
            assert duplicate_origin.is_error is True
            assert duplicate_origin.structured_content["code"] == "STATE_CONFLICT"

            _advance_current_data(settings)
            blocked_worker = await anyio.to_thread.run_sync(
                _run_tracking_worker_once,
                settings,
                1,
            )
            _assert_worker_succeeded(blocked_worker)
            blocked_track = await client.call_tool(
                "get_daily_track",
                {"track_id": daily_track.structured_content["track_id"]},
            )
            assert blocked_track.structured_content["progress"]["phase"] == "blocked"
            concurrent_retries = await _concurrent_track_retries(
                app,
                action_token,
                track_id=str(daily_track.structured_content["track_id"]),
                request_id="http-track-retry",
            )
            assert all(not result.is_error for result in concurrent_retries), [
                (result.is_error, result.structured_content)
                for result in concurrent_retries
            ]
            assert all(
                result.structured_content["status"] == "active" for result in concurrent_retries
            )
            assert all(
                result.structured_content["retry_after_seconds"] == 2
                for result in concurrent_retries
            )
            assert (
                sum(result.structured_content["replayed"] is False for result in concurrent_retries)
                == 1
            )
            retry_state_conflict = await client.call_tool(
                "retry_daily_track",
                {
                    "track_id": daily_track.structured_content["track_id"],
                    "request_id": "http-track-retry-active",
                },
            )
            assert retry_state_conflict.is_error is True
            assert retry_state_conflict.structured_content["code"] == "STATE_CONFLICT"
            await _exercise_http_live_tracking_stop(
                app,
                client,
                stop_token,
                settings=settings,
                track_id=str(daily_track.structured_content["track_id"]),
            )

            concurrent_strategy = await client.call_tool(
                "submit_research_run",
                _strategy_command("http-track-concurrent-origin"),
            )
            changed_strategy = await client.call_tool(
                "submit_research_run",
                _strategy_command("http-track-changed-origin"),
            )
            assert concurrent_strategy.is_error is False
            assert changed_strategy.is_error is False
            assert (
                await anyio.to_thread.run_sync(app.state.core_runtime.research_runs.process_next)
                is True
            )
            assert (
                await anyio.to_thread.run_sync(app.state.core_runtime.research_runs.process_next)
                is True
            )
            concurrent_tracks = await _concurrent_track_starts(
                app,
                action_token,
                run_id=str(concurrent_strategy.structured_content["run_id"]),
                request_id="http-track-concurrent-start",
            )
            assert all(not result.is_error for result in concurrent_tracks)
            assert len({result.structured_content["track_id"] for result in concurrent_tracks}) == 1
            assert (
                sum(result.structured_content["replayed"] is False for result in concurrent_tracks)
                == 1
            )
            concurrent_track_id = str(concurrent_tracks[0].structured_content["track_id"])
            changed_fingerprint = await client.call_tool(
                "start_daily_track",
                {
                    "run_id": changed_strategy.structured_content["run_id"],
                    "request_id": "http-track-concurrent-start",
                },
            )
            assert changed_fingerprint.is_error is True
            assert changed_fingerprint.structured_content["code"] == "IDEMPOTENCY_CONFLICT"
            unchanged_after_conflict = await client.call_tool(
                "start_daily_track",
                {
                    "run_id": changed_strategy.structured_content["run_id"],
                    "request_id": "http-track-changed-fresh-start",
                },
            )
            assert unchanged_after_conflict.is_error is False
            retry_fingerprint_conflict = await client.call_tool(
                "retry_daily_track",
                {
                    "track_id": unchanged_after_conflict.structured_content["track_id"],
                    "request_id": "http-track-retry",
                },
            )
            assert retry_fingerprint_conflict.is_error is True
            assert retry_fingerprint_conflict.structured_content["code"] == ("IDEMPOTENCY_CONFLICT")
            denied_stop = await client.call_tool(
                "stop_daily_track",
                {
                    "track_id": unchanged_after_conflict.structured_content["track_id"],
                    "request_id": "http-stop-track",
                },
            )
            assert denied_stop.is_error is True
            assert denied_stop.structured_content["code"] == "FORBIDDEN"

        async with _mcp_client(app, stop_token) as stopper:
            stop_tools = {tool.name: tool for tool in (await stopper.list_tools()).tools}
            assert set(stop_tools) == RESEARCH_AGENT_TOOL_NAMES
            assert stop_tools["stop_daily_track"].annotations.destructive_hint is True
            rejected_confirmation = await stopper.call_tool(
                "stop_daily_track",
                {
                    "track_id": unchanged_after_conflict.structured_content["track_id"],
                    "request_id": "http-stop-track",
                    "confirmation_token": "host-confirmation-is-not-authority",
                },
            )
            assert rejected_confirmation.is_error is True
            assert rejected_confirmation.structured_content["code"] == "INVALID_INPUT"
            concurrent_stops = await _concurrent_track_stops(
                app,
                stop_token,
                track_id=str(unchanged_after_conflict.structured_content["track_id"]),
                request_id="http-stop-track",
            )
            assert all(not result.is_error for result in concurrent_stops)
            assert all(
                result.structured_content["status"] == "stopped" for result in concurrent_stops
            )
            assert (
                sum(result.structured_content["replayed"] is False for result in concurrent_stops)
                == 1
            )
            stopped_track = concurrent_stops[0]
            stopped_replay = await stopper.call_tool(
                "stop_daily_track",
                {
                    "track_id": unchanged_after_conflict.structured_content["track_id"],
                    "request_id": "http-stop-track",
                },
            )
            assert (
                stopped_replay.structured_content["track_id"]
                == (stopped_track.structured_content["track_id"])
            )
            assert stopped_replay.structured_content["replayed"] is True
            stop_fingerprint_conflict = await stopper.call_tool(
                "stop_daily_track",
                {
                    "track_id": daily_track.structured_content["track_id"],
                    "request_id": "http-stop-track",
                },
            )
            assert stop_fingerprint_conflict.is_error is True
            assert stop_fingerprint_conflict.structured_content["code"] == ("IDEMPOTENCY_CONFLICT")
            stop_state_conflict = await stopper.call_tool(
                "stop_daily_track",
                {
                    "track_id": unchanged_after_conflict.structured_content["track_id"],
                    "request_id": "http-stop-track-terminal",
                },
            )
            assert stop_state_conflict.is_error is True
            assert stop_state_conflict.structured_content["code"] == "STATE_CONFLICT"

        async with _mcp_client(app, no_grant_token) as client:
            assert (await client.list_tools()).tools == []

        async with _mcp_client(app, read_token) as reconnected:
            second_context = await reconnected.call_tool("get_research_context", {})
            assert second_context.is_error is False
            assert second_context.structured_content["data_overview"][
                "data_through_session"
            ] == "2026-08-10"
            assert second_context.structured_content["folders"] == first_context["folders"]
            assert second_context.structured_content["authoring_constraints"] == first_context[
                "authoring_constraints"
            ]

    restarted_app = _app(settings, issuer)
    async with restarted_app.router.lifespan_context(restarted_app):
        async with _mcp_client(restarted_app, action_token) as restarted:
            track_replay = await restarted.call_tool(
                "start_daily_track",
                {
                    "run_id": strategy.structured_content["run_id"],
                    "request_id": "http-start-track",
                },
            )
            assert track_replay.is_error is False
            assert (
                track_replay.structured_content["track_id"]
                == (daily_track.structured_content["track_id"])
            )
            assert track_replay.structured_content["replayed"] is True
            concurrent_track_replay = await restarted.call_tool(
                "start_daily_track",
                {
                    "run_id": concurrent_strategy.structured_content["run_id"],
                    "request_id": "http-track-concurrent-start",
                },
            )
            assert concurrent_track_replay.is_error is False
            assert concurrent_track_replay.structured_content["track_id"] == concurrent_track_id
            assert concurrent_track_replay.structured_content["replayed"] is True
            retry_replay_after_restart = await restarted.call_tool(
                "retry_daily_track",
                {
                    "track_id": daily_track.structured_content["track_id"],
                    "request_id": "http-track-retry",
                },
            )
            assert retry_replay_after_restart.is_error is False
            assert retry_replay_after_restart.structured_content["replayed"] is True
            reopened_track = await restarted.call_tool(
                "get_daily_track",
                {"track_id": daily_track.structured_content["track_id"]},
            )
            assert reopened_track.is_error is False
            assert (
                reopened_track.structured_content["id"] == (track_detail.structured_content["id"])
            )
            assert (
                reopened_track.structured_content["origin"]
                == (track_detail.structured_content["origin"])
            )
            replay = await restarted.call_tool(
                "cancel_research_run",
                {
                    "run_id": cancel_target.structured_content["run_id"],
                    "request_id": "http-cancel-request",
                },
            )
            assert replay.is_error is False
            assert replay.structured_content["run"] == cancelled.structured_content["run"]
            assert replay.structured_content["replayed"] is True
            assert replay.structured_content["retry_after_seconds"] == 2
            stable_after_restart = await restarted.call_tool(
                "get_research_run",
                {"run_id": cancel_target.structured_content["run_id"]},
            )
            assert stable_after_restart.structured_content["status"] == "cancelled"
            batch_cancel_replay = await restarted.call_tool(
                "cancel_research_batch",
                {
                    "batch_id": batch.structured_content["batch_id"],
                    "request_id": "http-batch-cancel-request",
                },
            )
            assert batch_cancel_replay.is_error is False
            assert (
                batch_cancel_replay.structured_content["batch"]
                == (cancelled_batch.structured_content["batch"])
            )
            assert batch_cancel_replay.structured_content["replayed"] is True
            restarted_batch_submit = await restarted.call_tool(
                "submit_research_batch",
                concurrent_batch_command,
            )
            restarted_rejected_submit = await restarted.call_tool(
                "submit_research_batch",
                concurrent_rejected_command,
            )
            assert (
                restarted_batch_submit.structured_content["batch_id"]
                == (concurrent_batch_results[0].structured_content["batch_id"])
            )
            assert restarted_batch_submit.structured_content["replayed"] is True
            assert restarted_rejected_submit.structured_content["outcome"] == "rejected"
            assert restarted_rejected_submit.structured_content["replayed"] is True
        async with _mcp_client(restarted_app, stop_token) as restarted_stopper:
            live_stop_replay_after_restart = await restarted_stopper.call_tool(
                "stop_daily_track",
                {
                    "track_id": daily_track.structured_content["track_id"],
                    "request_id": "http-live-stop",
                },
            )
            assert live_stop_replay_after_restart.is_error is False
            assert live_stop_replay_after_restart.structured_content["status"] == "stopping"
            assert live_stop_replay_after_restart.structured_content["replayed"] is True
            assert live_stop_replay_after_restart.structured_content["retry_after_seconds"] == 2
            stop_replay_after_restart = await restarted_stopper.call_tool(
                "stop_daily_track",
                {
                    "track_id": unchanged_after_conflict.structured_content["track_id"],
                    "request_id": "http-stop-track",
                },
            )
            assert stop_replay_after_restart.is_error is False
            assert stop_replay_after_restart.structured_content == stopped_replay.structured_content


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


async def _concurrent_cancel_replays(
    app,
    token: str,
    *,
    run_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def replay() -> None:
        async with _mcp_client(app, token) as client:
            results.append(
                await client.call_tool(
                    "cancel_research_run",
                    {"run_id": run_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for _index in range(4):
            task_group.start_soon(replay)
    return results


async def _concurrent_batch_cancel_replays(
    app,
    token: str,
    *,
    batch_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def replay() -> None:
        async with _mcp_client(app, token) as client:
            results.append(
                await client.call_tool(
                    "cancel_research_batch",
                    {"batch_id": batch_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for _index in range(4):
            task_group.start_soon(replay)
    return results


async def _concurrent_batch_submits(
    app,
    token: str,
    command: dict[str, object],
) -> list[object]:
    results: list[object] = []

    async def submit() -> None:
        async with _mcp_client(app, token) as client:
            results.append(await client.call_tool("submit_research_batch", command))

    async with anyio.create_task_group() as task_group:
        for _index in range(4):
            task_group.start_soon(submit)
    return results


async def _concurrent_track_starts(
    app,
    token: str,
    *,
    run_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def start() -> None:
        async with _mcp_client(app, token) as client:
            results.append(
                await client.call_tool(
                    "start_daily_track",
                    {"run_id": run_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for _index in range(4):
            task_group.start_soon(start)
    return results


async def _concurrent_track_retries(
    app,
    token: str,
    *,
    track_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def retry() -> None:
        async with _mcp_client(app, token) as client:
            results.append(
                await client.call_tool(
                    "retry_daily_track",
                    {"track_id": track_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for _index in range(2):
            task_group.start_soon(retry)
    return results


async def _concurrent_track_stops(
    app,
    token: str,
    *,
    track_id: str,
    request_id: str,
) -> list[object]:
    results: list[object] = []

    async def stop() -> None:
        async with _mcp_client(app, token) as client:
            results.append(
                await client.call_tool(
                    "stop_daily_track",
                    {"track_id": track_id, "request_id": request_id},
                )
            )

    async with anyio.create_task_group() as task_group:
        for _index in range(2):
            task_group.start_soon(stop)
    return results


async def _exercise_http_live_tracking_stop(
    app,
    action_client,
    stop_token: str,
    *,
    settings: CoreSettings,
    track_id: str,
) -> None:
    prepared = Event()
    release_prepared = Event()
    cooperative_stop_requested = Event()
    release_cooperative_stop = Event()
    execution_events: list[dict[str, object]] = []
    runtime = app.state.core_runtime

    def progress(stage: str, selected_track_id: str, _target: str) -> None:
        if stage == "prepared" and selected_track_id == track_id:
            prepared.set()
            assert release_prepared.wait(timeout=10)

    def capture_execution_event(event: dict[str, object]) -> None:
        execution_events.append(event)
        if event.get("event") == "tracking_execution_child_stop_requested":
            cooperative_stop_requested.set()
            assert release_cooperative_stop.wait(timeout=10)

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
        retry_during_claim = await action_client.call_tool(
            "retry_daily_track",
            {"track_id": track_id, "request_id": "http-retry-during-claim"},
        )
        assert retry_during_claim.is_error is True
        assert retry_during_claim.structured_content["code"] == "STATE_CONFLICT"

        async with _mcp_client(app, stop_token) as stopper:
            stopping = await stopper.call_tool(
                "stop_daily_track",
                {"track_id": track_id, "request_id": "http-live-stop"},
            )
            assert stopping.is_error is False
            assert stopping.structured_content == {
                "outcome": "accepted",
                "track_id": track_id,
                "status": "stopping",
                "replayed": False,
                "retry_after_seconds": 2,
            }
            fresh_stop_while_stopping = await stopper.call_tool(
                "stop_daily_track",
                {"track_id": track_id, "request_id": "http-stop-while-stopping"},
            )
            assert fresh_stop_while_stopping.is_error is True
            assert fresh_stop_while_stopping.structured_content["code"] == "STATE_CONFLICT"

        retry_while_stopping = await action_client.call_tool(
            "retry_daily_track",
            {"track_id": track_id, "request_id": "http-retry-while-stopping"},
        )
        assert retry_while_stopping.is_error is True
        assert retry_while_stopping.structured_content["code"] == "STATE_CONFLICT"
        stopping_detail = await action_client.call_tool(
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
        event.get("event") == "tracking_execution_child_exited"
        for event in execution_events
    )
    terminal = await action_client.call_tool("get_daily_track", {"track_id": track_id})
    assert terminal.is_error is False
    assert terminal.structured_content["status"] == "stopped"
    assert terminal.structured_content["progress"]["phase"] == "stopped"
    assert terminal.structured_content["retry_after_seconds"] is None
    retry_stopped = await action_client.call_tool(
        "retry_daily_track",
        {"track_id": track_id, "request_id": "http-retry-stopped"},
    )
    assert retry_stopped.is_error is True
    assert retry_stopped.structured_content["code"] == "STATE_CONFLICT"


def _run_tracking_worker_once(
    settings: CoreSettings,
    execution_memory_bytes: int,
) -> subprocess.CompletedProcess[str]:
    environment = _core_environment(settings)
    environment["THESISTRACE_TRACKING_WORKER_EXECUTION_MEMORY_BYTES"] = str(execution_memory_bytes)
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


async def _exercise_allowlist_intersection(app, token: str) -> None:
    async with app.router.lifespan_context(app):
        async with _mcp_client(app, token) as client:
            discovered = await client.list_tools()
            assert [tool.name for tool in discovered.tools] == ["get_research_context"]
            denied = await client.call_tool("get_alpha_catalog", {})
            assert denied.is_error is True
            assert denied.structured_content["code"] == "FORBIDDEN"
            denied_cancel = await client.call_tool(
                "cancel_research_run",
                {"run_id": "run_missing", "request_id": "allowlist-cancel"},
            )
            assert denied_cancel.is_error is True
            assert denied_cancel.structured_content["code"] == "FORBIDDEN"


def _research_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "HTTP MCP Cancellation",
        "formula": "close",
        "hypothesis": "Close prices preserve a stable cross-sectional signal.",
        "start_date": "2026-08-07",
        "end_date": "2026-08-07",
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "factor_evaluation",
    }


def _strategy_command(request_id: str) -> dict[str, object]:
    return {
        **_research_command(request_id),
        "research_kind": "strategy_backtest",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _assert_compact_track(payload: dict[str, object]) -> None:
    serialized = str(payload).lower()
    assert payload["available_result_sections"] == [
        "factor",
        "strategy_summary",
        "strategy_observations",
        "origin",
        "provenance",
    ]
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


def _batch_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "batch_kind": "factor_evaluation",
        "start_date": "2026-08-07",
        "end_date": "2026-08-07",
        "universe": "top300",
        "neutralization": "none",
        "factors": [
            {
                "item_key": "value",
                "name": "HTTP MCP Batch",
                "formula": "close",
                "hypothesis": "Close prices preserve a stable cross-sectional signal.",
            }
        ],
    }


def _publish_current_data(settings: CoreSettings) -> None:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        source_name="research-agent-http-cancel-acceptance",
        source_lineage={"contract": "research-agent-http-cancel"},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id="research-agent-http-cancel-head",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="research-agent-http-cancel-head",
        )
    finally:
        database.close()


def _advance_current_data(settings: CoreSettings) -> None:
    sessions = ("2026-08-07", "2026-08-10")
    template = build_minimal_canonical_fixture(price_offset=1)
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    canonical = {
        **template,
        "research_calendar": list(sessions),
        "field_catalog": [
            next(
                row
                for row in field_catalog(sessions[-1])
                if row["field_id"] == "price.close.adjusted"
            )
        ],
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in sessions
        ],
        "liquidity_universes": {
            name: [
                {
                    "session": session,
                    "instrument_ids": [instrument_id],
                    "status": "available",
                }
                for session in sessions
            ]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        source_name="research-agent-http-tracking-head",
        source_lineage={"contract": "research-agent-http-tracking"},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        current = lifecycle.current_pointer()
        assert current is not None
        lifecycle.protect_candidate(
            operation_id="research-agent-http-tracking-head",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=current.generation_manifest_sha256,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="research-agent-http-tracking-head",
        )
    finally:
        database.close()


def _install_transient_cancel_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION research_runs.reject_mcp_cancel_transiently()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF OLD.status = 'queued' AND NEW.status = 'cancelled' THEN
                        RAISE EXCEPTION 'injected MCP cancellation dependency failure'
                            USING ERRCODE = '08006';
                    END IF;
                    RETURN NEW;
                END
                $$;
                CREATE TRIGGER reject_mcp_cancel_transiently
                BEFORE UPDATE ON research_runs.runs
                FOR EACH ROW
                EXECUTE FUNCTION research_runs.reject_mcp_cancel_transiently();
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
                DROP TRIGGER reject_mcp_cancel_transiently ON research_runs.runs;
                DROP FUNCTION research_runs.reject_mcp_cancel_transiently();
                """
            )
    finally:
        database.close()


async def _assert_protected_resource_and_authentication_boundaries(
    app,
    issuer: _DeterministicOAuthIssuer,
    *,
    read_token: str,
) -> None:
    async with _raw_http_client(app) as client:
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == _RESOURCE_URL
        assert metadata.json()["authorization_servers"] == [_ISSUER_URL]
        assert set(metadata.json()["scopes_supported"]) == {
            scope.value for scope in ResearchAgentScope
        }

        invalid_tokens = [
            None,
            "malformed-token",
            issuer.issue(lifetime_seconds=-1),
            issuer.issue(not_before_seconds=60),
            issuer.issue(issuer="https://wrong-issuer.test"),
            issuer.issue(audience="https://wrong-resource.test/mcp"),
            issuer.issue(signing_key="wrong-signing-key-that-is-at-least-32-bytes"),
        ]
        for token in invalid_tokens:
            response = await _initialize(client, token=token)
            assert response.status_code == 401
            assert "resource_metadata=" in response.headers["www-authenticate"]

        basic = await _initialize(client, authorization="Basic not-a-bearer-token")
        assert basic.status_code == 401
        query_token = await client.post(
            f"/mcp?access_token={read_token}",
            json=_initialize_request(),
            headers=_protocol_headers(),
        )
        assert query_token.status_code == 401
        scope_header = await client.post(
            "/mcp",
            json=_initialize_request(),
            headers={**_protocol_headers(), "X-Research-Scopes": "research:read"},
        )
        assert scope_header.status_code == 401

        untrusted_host = await _initialize(
            client,
            token=read_token,
            extra_headers={"Host": "attacker.test"},
        )
        assert untrusted_host.status_code == 421
        untrusted_origin = await _initialize(
            client,
            token=read_token,
            extra_headers={"Origin": "https://attacker.test"},
        )
        assert untrusted_origin.status_code == 403
        trusted = await _initialize(
            client,
            token=read_token,
            extra_headers={"Origin": _TRUSTED_ORIGIN},
        )
        assert trusted.status_code == 200

        for path in ("/sse", "/mcp/sse", "/mcp/v1"):
            response = await client.post(
                path,
                json=_initialize_request(),
                headers={
                    **_protocol_headers(),
                    "Authorization": f"Bearer {read_token}",
                },
            )
            assert response.status_code == 404


@asynccontextmanager
async def _mcp_client(app, token: str) -> AsyncIterator[Client]:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="https://core.test",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": _TRUSTED_ORIGIN,
        },
    ) as http_client:
        async with Client(
            streamable_http_client(
                _RESOURCE_URL,
                http_client=http_client,
            ),
            mode="legacy",
        ) as client:
            yield client


def _raw_http_client(app) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="https://core.test",
    )


async def _initialize(
    client: httpx2.AsyncClient,
    *,
    token: str | None = None,
    authorization: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx2.Response:
    headers = _protocol_headers()
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if authorization is not None:
        headers["Authorization"] = authorization
    if extra_headers is not None:
        headers.update(extra_headers)
    return await client.post("/mcp", json=_initialize_request(), headers=headers)


def _protocol_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_HANDSHAKE_VERSION,
    }


def _initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_HANDSHAKE_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "acceptance", "version": "1"},
        },
    }

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from itertools import count
from multiprocessing import get_context
from pathlib import Path

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
from test_core_research_batch_fifo import (
    _release_claim_barrier_worker,
    _start_claim_barrier_worker,
    _terminate_worker,
    _wait_for_worker_event,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.operational_events import OperationalEvent
from thesistrace.research_agent import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentHTTPConfiguration,
    ResearchAgentScope,
)
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.execution import SupervisedResearchExecutor

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
    )
    action_token = issuer.issue(scopes=action_scopes)
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
            assert set(tools) == RESEARCH_AGENT_TOOL_NAMES
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

        async with _mcp_client(app, no_grant_token) as client:
            assert (await client.list_tools()).tools == []

        async with _mcp_client(app, read_token) as reconnected:
            second_context = await reconnected.call_tool("get_research_context", {})
            assert second_context.is_error is False
            assert second_context.structured_content == first_context

    restarted_app = _app(settings, issuer)
    async with restarted_app.router.lifespan_context(restarted_app):
        async with _mcp_client(restarted_app, action_token) as restarted:
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

"""Discovery remains available during pool pressure; legal bodies survive real HTTP framing."""

import json
import socket
from functools import partial
from pathlib import Path

import anyio
import httpx
import pytest
import uvicorn
from core_runtime import (
    TEST_RESEARCHER,
    _TestSessionVerifier,
    drop_product_schemas,
    isolated_core_settings,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from pydantic import TypeAdapter
from test_core_research_agent_mcp_http import _app, _DeterministicOAuthIssuer, _mcp_client

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetOverviewService
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_agent.mcp_server import RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES
from thesistrace.research_authoring import ResearchAuthoringService
from thesistrace.research_batch.models import ResearchBatchAdmissionCommand
from thesistrace.research_kernel.strategy_program_runtime import get_strategy_runtime
from thesistrace.researcher import ResearcherService


def _prepare(tmp_path):
    settings = isolated_core_settings(tmp_path / "data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        ResearcherService(database).bootstrap(TEST_RESEARCHER)
    finally:
        database.close()
    return settings


def test_http_discovery_reports_real_pool_pressure_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _prepare(tmp_path)
    monkeypatch.setattr(
        "thesistrace.entrypoints.runtime.PostgresDatabase",
        partial(PostgresDatabase, pool_max_size=1, pool_timeout_seconds=1),
    )
    issuer = _DeterministicOAuthIssuer()
    token = issuer.issue()
    app = _app(settings, issuer)

    async def exercise():
        discovery_started = anyio.Event()
        discovery_finished = anyio.Event()
        discovery_results = []
        overview = DatasetOverviewService.overview

        def observed_overview(service):
            anyio.from_thread.run_sync(discovery_started.set)
            return overview(service)

        async def read_discovery(client):
            discovery_results.append(await client.call_tool("get_research_context", {}))
            discovery_finished.set()

        async with app.router.lifespan_context(app):
            monkeypatch.setattr(DatasetOverviewService, "overview", observed_overview)
            app.state.auth_verifier = _TestSessionVerifier()
            async with _mcp_client(app, token) as client, httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://core.test",
            ) as http:
                with app.state.core_runtime.database.transaction():
                    tools = await client.list_tools()
                    assert "get_research_context" in {tool.name for tool in tools.tools}
                    formula = await client.call_tool("diagnose_alpha_formula", {"source": "close"})
                    assert formula.is_error is False
                    async with anyio.create_task_group() as group:
                        group.start_soon(read_discovery, client)
                        with anyio.fail_after(5):
                            await discovery_started.wait()
                        with anyio.fail_after(0.5):
                            assert (await http.get("/health/live")).status_code == 200
                        assert not discovery_finished.is_set()
                    discovery_results.append(await client.call_tool("get_alpha_catalog", {}))
                    for result in discovery_results:
                        assert result.is_error is True
                        assert result.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
                        assert result.structured_content["retryable"] is True
                        assert result.structured_content["retry_after_seconds"] == 2
                    for path in ("/api/data", "/api/alpha/catalog", "/api/research-folders"):
                        response = await http.get(path)
                        assert response.status_code == 503, (path, response.text)
                        assert "pool" not in response.text.lower()
                recovered = await client.call_tool("get_research_context", {})
                assert recovered.is_error is False
                assert recovered.structured_content["folders"]["items"]
                issuer.replace_grant(token, ())
                assert (await client.list_tools()).tools == []

    try:
        anyio.run(exercise)
    finally:
        drop_product_schemas(settings)


def test_maximum_framework_batch_reaches_authorization_over_chunked_real_http(tmp_path: Path):
    settings = _prepare(tmp_path)
    issuer = _DeterministicOAuthIssuer()
    app = _app(settings, issuer)
    constraints = ResearchAuthoringService().constraints()
    modules = {}
    for stage in constraints.framework.stages:
        prefix = stage.source_template + "#"
        source = prefix + "\x01" * (constraints.python_program.maximum_source_bytes - len(prefix))
        get_strategy_runtime().validate(source)
        modules[stage.stage] = {"kind": "python", "program": {"source": source}}
    batch = {
        "batch_kind": "strategy_sweep", "request_id": "legal-chunked-framework-batch",
        "start_date": "2026-08-03", "end_date": "2026-08-04", "universe": "top300",
        "strategies": [{
            "item_key": str(index), "strategy_mode": "framework",
            "initial_cash_cny": "100000", "modules": modules,
        } for index in range(20)],
    }
    TypeAdapter(ResearchBatchAdmissionCommand).validate_python(batch)
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "submit_research_batch", "arguments": batch},
    }, separators=(",", ":")).encode()
    assert 29 * 1024**2 < len(body) < RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES

    async def exercise():
        async with app.router.lifespan_context(app):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                server = uvicorn.Server(uvicorn.Config(
                    app, lifespan="off", access_log=False, log_level="warning",
                ))
                async with anyio.create_task_group() as group:
                    group.start_soon(partial(server.serve, sockets=[listener]))
                    try:
                        with anyio.fail_after(10):
                            while not server.started:
                                await anyio.sleep(0.01)

                        async def chunks():
                            for offset in range(0, len(body), 64 * 1024):
                                yield body[offset:offset + 64 * 1024]
                                await anyio.sleep(0.001)

                        async with httpx.AsyncClient(timeout=30) as client:
                            response = await client.post(
                                f"http://127.0.0.1:{listener.getsockname()[1]}/mcp",
                                content=chunks(), headers={
                                    "Host": "core.test", "Origin": "https://codex.test",
                                    "Authorization": f"Bearer {issuer.issue()}",
                                    "Content-Type": "application/json",
                                    "Accept": "application/json, text/event-stream",
                                    "MCP-Protocol-Version": LATEST_HANDSHAKE_VERSION,
                                },
                            )
                        assert response.status_code == 200, response.text
                        result = response.json()["result"]
                        assert result["isError"] is True
                        assert result["structuredContent"]["code"] == "FORBIDDEN"
                    finally:
                        server.should_exit = True
    try:
        anyio.run(exercise)
    finally:
        drop_product_schemas(settings)

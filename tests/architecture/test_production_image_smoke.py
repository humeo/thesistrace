from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from threading import Thread
from types import ModuleType, SimpleNamespace

import anyio
import pytest


def test_outage_polling_ignores_transient_fail_closed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_smoke_module()
    transient = (
        503,
        {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {
                    "status": "unavailable",
                    "code": "POSTGRESQL_UNAVAILABLE",
                },
                "rustfs": {"status": "unavailable", "code": "RUSTFS_UNAVAILABLE"},
                "dataset_store": {
                    "status": "unavailable",
                    "code": "DATASET_STORE_UNAVAILABLE",
                },
                "auth": {"status": "unavailable", "code": "AUTH_UNAVAILABLE"},
            },
        },
        0.01,
    )
    expected = (
        503,
        {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {
                    "status": "unavailable",
                    "code": "POSTGRESQL_UNAVAILABLE",
                },
                "rustfs": {"status": "ready", "code": "RUSTFS_READY"},
                "dataset_store": {"status": "ready", "code": "DATASET_STORE_READY"},
                "auth": {"status": "unavailable", "code": "AUTH_UNAVAILABLE"},
            },
        },
        0.01,
    )
    responses = iter((transient, expected))
    monkeypatch.setattr(smoke, "_request_health", lambda *_args: next(responses))

    assert smoke._wait_for_readiness("http://api:8100", unavailable="postgresql") == expected


def test_image_smoke_allows_one_bounded_slow_result_response() -> None:
    smoke = _load_smoke_module()

    assert smoke.HTTP_REQUEST_TIMEOUT_SECONDS == 10


def test_image_smoke_run_polling_retries_exact_auth_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_smoke_module()
    terminal = {
        "status": "succeeded",
        "research_kind": "factor_evaluation",
        "result": {
            "factor": {},
            "provenance": {"research_kind": "factor_evaluation"},
        },
    }
    responses = iter(
        (
            (503, {"detail": "Authentication unavailable"}, "unavailable"),
            (200, terminal, "succeeded"),
        )
    )
    monkeypatch.setattr(smoke, "_request_json_response", lambda *_args: next(responses))
    monkeypatch.setattr(
        smoke,
        "Event",
        lambda: SimpleNamespace(wait=lambda _seconds: None),
    )

    assert smoke._wait_for_run(
        "http://api:8100",
        "run_retryable_auth",
        research_kind="factor_evaluation",
    ) == terminal


def test_image_smoke_wraps_empty_gateway_error_as_retryable_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_smoke_module()

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "http://api:8100/api/data",
            502,
            "Bad Gateway",
            {},
            BytesIO(b""),
        )

    monkeypatch.setattr(smoke, "_authenticated_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(smoke.urllib.request, "urlopen", unavailable)

    with pytest.raises(AssertionError) as failure:
        smoke._request_json("http://api:8100", "GET", "/api/data")

    assert failure.value.args == (
        {
            "status": 502,
            "method": "GET",
            "path": "/api/data",
            "body": "",
        },
    )


def test_mounted_data_hash_detects_batch_attempt_control_pollution(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    dataset_file = tmp_path / "generations" / "generation-id" / "manifest.json"
    dataset_file.parent.mkdir(parents=True)
    dataset_file.write_text("immutable dataset", encoding="utf-8")
    expected = smoke._directory_sha256(tmp_path)

    control_file = tmp_path / ".batch-attempts" / "batch_attempt_id.lock"
    control_file.parent.mkdir()
    control_file.write_text("runtime state", encoding="utf-8")

    assert smoke._directory_sha256(tmp_path) != expected


def test_web_image_probe_uses_the_public_origin_host_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_host = "thesistrace.test:8443"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Host") != expected_host:
                self.send_response(421)
                self.end_headers()
                return
            body = b'<!doctype html><div id="root"></div>'
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "THESISTRACE_PUBLIC_ORIGIN",
        f"https://{expected_host}",
    )
    try:
        smoke = _load_smoke_module()
        smoke._assert_web_image(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mcp_image_smoke_rejects_private_evidence_and_generic_tools() -> None:
    smoke = _load_mcp_smoke_module()

    with pytest.raises(smoke._SmokeFailure, match="protocol_evidence_contract"):
        smoke._assert_public_evidence({"formula": "private-formula-canary"})
    with pytest.raises(smoke._SmokeFailure, match="http_discovery_contract"):
        smoke._assert_no_generic_tools({"execute_sql"})


def test_mcp_image_smoke_reports_only_bounded_exception_types() -> None:
    smoke = _load_mcp_smoke_module()
    nested = ExceptionGroup(
        "private-formula-canary",
        [ValueError("private-hypothesis-canary"), TimeoutError("private-cursor-canary")],
    )

    assert smoke._error_types(nested) == [
        "ExceptionGroup",
        "ValueError",
        "TimeoutError",
    ]

    contract_failure = smoke._SmokeFailure("http_result_contract")
    wrapped = ExceptionGroup("private-message", [contract_failure])
    assert smoke._nested_smoke_failure_code(wrapped) == "http_result_contract"


def test_mcp_image_smoke_requires_graceful_restart_order(tmp_path: Path) -> None:
    smoke = _load_mcp_smoke_module()
    log = tmp_path / "api-events.jsonl"
    log.write_text(
        "\n".join(
            (
                '{"component":"research_agent_mcp","tool_name":"submit_research_run"}',
                "INFO:     Shutting down",
                "INFO:     Application shutdown complete.",
                "INFO:     Finished server process [6]",
                "INFO:     Started server process [6]",
                '{"component":"research_agent_mcp","tool_name":"get_research_run"}',
            )
        )
    )

    smoke._assert_graceful_mcp_restart(log)

    log.write_text(
        "\n".join(
            (
                '{"component":"research_agent_mcp","tool_name":"submit_research_run"}',
                "INFO:     Shutting down",
                "INFO:     Started server process [6]",
                '{"component":"research_agent_mcp","tool_name":"get_research_run"}',
            )
        )
    )
    with pytest.raises(smoke._SmokeFailure, match="api_lifecycle_contract"):
        smoke._assert_graceful_mcp_restart(log)


def test_mcp_image_smoke_scans_current_shared_canaries_in_all_evidence(
    tmp_path: Path,
) -> None:
    smoke = _load_mcp_smoke_module()
    (tmp_path / "smoke-before.json").write_text('{"formula":"rank(close)"}')

    smoke._assert_canaries_absent(tmp_path)

    protocol_log = tmp_path / "api-events.jsonl"
    protocol_log.write_text(json.dumps({"formula": smoke.FORMULA}))
    with pytest.raises(smoke._SmokeFailure, match="protocol_evidence_contract"):
        smoke._assert_canaries_absent(tmp_path)

    protocol_log.write_text("{}")
    (tmp_path / "compose-logs.txt").write_text(smoke.HYPOTHESIS)
    with pytest.raises(smoke._SmokeFailure, match="protocol_evidence_contract"):
        smoke._assert_canaries_absent(tmp_path)


def test_mcp_image_smoke_reads_stopped_state_without_passed_phase_status(
    tmp_path: Path,
) -> None:
    smoke = _load_mcp_smoke_module()
    stopped = tmp_path / "mcp-api-stopped.json"
    stopped.write_text('{"status":"exited","exit_code":143,"oom_killed":false}')

    assert smoke._read_object(stopped) == {
        "status": "exited",
        "exit_code": 143,
        "oom_killed": False,
    }
    with pytest.raises(smoke._SmokeFailure, match="protocol_evidence_contract"):
        smoke._read_json(stopped)


def test_mcp_image_smoke_retry_guidance_cannot_exceed_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_mcp_smoke_module()

    class SlowGuidanceClient:
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, object],
        ) -> object:
            assert name == "get_research_run"
            assert arguments == {"run_id": "run_deadline"}
            return SimpleNamespace(
                is_error=False,
                structured_content={
                    "status": "running",
                    "retry_after_seconds": 86_400,
                },
            )

    monkeypatch.setattr(smoke, "_record_protocol_envelope", lambda **_: None)

    async def exercise() -> None:
        with pytest.raises(smoke._SmokeFailure, match="timeout"):
            await smoke._poll_run_until_succeeded(
                SlowGuidanceClient(),
                "run_deadline",
                timeout_seconds=0.01,
            )

    anyio.run(exercise)


def test_mcp_image_stdio_probe_requires_unique_order_and_clean_process_exit() -> None:
    smoke = _load_mcp_smoke_module()
    source = (Path(__file__).parents[1] / "production_mcp_image_smoke.py").read_text()

    assert len(smoke.SAFE_STDIO_TOOL_ORDER) == 15
    assert len(set(smoke.SAFE_STDIO_TOOL_ORDER)) == 15
    assert "tuple(names) == SAFE_STDIO_TOOL_ORDER" in source
    assert "len(names) == 15 and len(set(names)) == 15" in source
    assert 'returncode == 0 and stdout_tail == b""' in source
    assert "process.stdin.close()" in source


def test_mcp_raw_stdio_reader_rejects_partial_frame_without_newline() -> None:
    smoke = _load_mcp_smoke_module()
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,time; os.write(1,b'{partial'); time.sleep(2)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with pytest.raises(smoke._SmokeFailure, match="timeout"):
            smoke._read_bounded_process_line(process, timeout_seconds=0.02)
    finally:
        process.kill()
        process.wait(timeout=10)


def test_mcp_raw_stdio_reader_rejects_oversized_frame() -> None:
    smoke = _load_mcp_smoke_module()
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,time; os.write(1,b'x'*32); time.sleep(2)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with pytest.raises(smoke._SmokeFailure, match="stdio_contract"):
            smoke._read_bounded_process_line(
                process,
                timeout_seconds=1,
                max_bytes=16,
            )
    finally:
        process.kill()
        process.wait(timeout=10)


def test_mcp_protocol_envelopes_are_incremental_closed_set_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_mcp_smoke_module()
    monkeypatch.setenv("THESISTRACE_TEST_EVIDENCE_DIR", str(tmp_path))

    smoke._record_protocol_envelope(
        transport="streamable_http",
        direction="request",
        method="tools/call",
        tool_name="submit_research_run",
    )
    smoke._record_protocol_envelope(
        transport="streamable_http",
        direction="response",
        method="tools/call",
        tool_name="submit_research_run",
        outcome="succeeded",
    )

    envelopes = [
        json.loads(line)
        for line in (tmp_path / "mcp-protocol-envelopes.jsonl").read_text().splitlines()
    ]
    assert envelopes == [
        {
            "direction": "request",
            "method": "tools/call",
            "tool_name": "submit_research_run",
            "transport": "streamable_http",
        },
        {
            "direction": "response",
            "method": "tools/call",
            "outcome": "succeeded",
            "tool_name": "submit_research_run",
            "transport": "streamable_http",
        },
    ]


def test_mcp_evidence_sanitizer_atomically_redacts_shared_canaries(
    tmp_path: Path,
) -> None:
    sanitizer = _load_mcp_sanitizer_module()
    canaries = sys.modules["production_mcp_image_canaries"]
    evidence = tmp_path / "compose-logs.txt"
    evidence.write_text("\n".join(canaries.SENSITIVE_CANARIES))
    binary_evidence = tmp_path / "trace.zip"
    binary_evidence.write_bytes(
        b"x" * (sanitizer.READ_CHUNK_BYTES - 3)
        + canaries.FORMULA.encode()
        + b"y" * (sanitizer.READ_CHUNK_BYTES * 2)
    )
    large_text = tmp_path / "large.log"
    large_text.write_bytes(
        b"x" * (sanitizer.READ_CHUNK_BYTES - 3)
        + canaries.HYPOTHESIS.encode()
        + b"y" * (sanitizer.READ_CHUNK_BYTES * 2)
    )

    sanitizer.sanitize_evidence(tmp_path)

    assert evidence.read_text().splitlines() == ["<redacted>"] * len(
        canaries.SENSITIVE_CANARIES
    )
    assert os.stat(evidence).st_mode & 0o777 == 0o600
    assert not binary_evidence.exists()
    large_content = large_text.read_bytes()
    assert canaries.HYPOTHESIS.encode() not in large_content
    assert b"<redacted>" in large_content
    sanitizer.verify_evidence(tmp_path)


@pytest.mark.parametrize("operation", ("chmod", "replace"))
def test_mcp_evidence_sanitizer_reports_atomic_io_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    sanitizer = _load_mcp_sanitizer_module()
    canaries = sys.modules["production_mcp_image_canaries"]
    evidence = tmp_path / "compose-logs.txt"
    evidence.write_text(canaries.FORMULA)

    def fail(*_: object) -> None:
        raise PermissionError("simulated")

    monkeypatch.setattr(sanitizer.os, operation, fail)
    with pytest.raises(sanitizer.EvidenceSanitizationError, match="PermissionError"):
        sanitizer.sanitize_evidence(tmp_path)

    assert evidence.read_text() == canaries.FORMULA
    assert not (tmp_path / ".compose-logs.txt.redacted").exists()


def test_mcp_evidence_discard_reports_unlink_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sanitizer = _load_mcp_sanitizer_module()
    evidence = tmp_path / "compose-logs.txt"
    evidence.write_text("sensitive")
    original_unlink = Path.unlink

    def fail_unlink(path: Path, *_: object, **__: object) -> None:
        if path == evidence:
            raise PermissionError("simulated")
        original_unlink(path)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(sanitizer.EvidenceSanitizationError, match="PermissionError"):
        sanitizer.discard_evidence(tmp_path)
    assert evidence.exists()


def test_mcp_image_api_uses_only_explicit_local_token_grants() -> None:
    smoke = _load_mcp_smoke_module()
    routes = {route.path for route in smoke.application().routes}
    assert "/mcp" in routes
    assert "/mcp/v1" not in routes

    api = sys.modules["production_mcp_image_api"]

    async def verify() -> None:
        token_verifier = api.LocalImageSmokeTokenVerifier()
        read = await token_verifier.verify_token(api.READ_TOKEN)
        action = await token_verifier.verify_token(api.ACTION_TOKEN)
        missing = await token_verifier.verify_token("unknown-token")
        assert read is not None
        assert read.scopes == ["research:read"]
        assert action is not None
        assert set(action.scopes) == {"research:read", "research:execute"}
        assert missing is None

    anyio.run(verify)


def _load_smoke_module() -> ModuleType:
    path = Path(__file__).parents[1] / "production_image_smoke.py"
    spec = spec_from_file_location("thesistrace_production_image_smoke", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_mcp_smoke_module() -> ModuleType:
    path = Path(__file__).parents[1] / "production_mcp_image_smoke.py"
    tests_root = str(path.parent)
    sys.path.insert(0, tests_root)
    try:
        spec = spec_from_file_location("thesistrace_production_mcp_image_smoke", path)
        assert spec is not None
        assert spec.loader is not None
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(tests_root)


def _load_mcp_sanitizer_module() -> ModuleType:
    path = Path(__file__).parents[1] / "sanitize_production_mcp_evidence.py"
    tests_root = str(path.parent)
    sys.path.insert(0, tests_root)
    try:
        spec = spec_from_file_location("thesistrace_mcp_evidence_sanitizer", path)
        assert spec is not None
        assert spec.loader is not None
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(tests_root)

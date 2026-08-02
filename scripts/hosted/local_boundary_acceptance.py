#!/usr/bin/env python3
import hashlib
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import psycopg

from thesistrace.hosted.backup_operations import (
    canonical_json_bytes,
    load_restore_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]
LOCAL_POSTGRES = ROOT / "scripts" / "hosted" / "local_postgres_acceptance.py"
CONTROLLED_TARGETS = (
    "tests/hosted/test_edge_policy.py",
    "tests/hosted/test_edge_rate_limits.py",
    "tests/hosted/test_container_boundaries.py",
    "tests/hosted/test_storage_admission.py",
    "tests/hosted/test_object_store_boundary.py",
    "tests/hosted/test_health_views.py",
    "tests/hosted/test_compose_stack.py::"
    "test_otel_sampling_and_export_failure_are_bounded_and_visible",
)
Runner = Callable[[tuple[str, ...]], bytes]
StateReader = Callable[[], dict[str, object]]
EdgeProber = Callable[[], dict[str, object]]


class LocalBoundaryAcceptanceError(RuntimeError):
    pass


def execute(command: tuple[str, ...]) -> bytes:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ,
        capture_output=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise LocalBoundaryAcceptanceError(
            f"local boundary command failed with exit {completed.returncode}:\n"
            + output[-8000:].decode("utf-8", errors="replace")
        )
    return output


def _last_json(output: bytes) -> dict[str, object]:
    for line in reversed(output.decode("utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LocalBoundaryAcceptanceError("local PostgreSQL gate returned no JSON evidence")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def core_state_digest() -> dict[str, object]:
    state_value = os.environ.get("THESISTRACE_HOST_STATE_DIR")
    if not state_value:
        raise LocalBoundaryAcceptanceError("THESISTRACE_HOST_STATE_DIR is required")
    state_dir = Path(state_value).resolve()
    try:
        port = int(os.environ.get("THESISTRACE_LOCAL_POSTGRES_PORT", "25432"))
        password = (state_dir / "secrets" / "postgres_password").read_text().strip()
        connection_info = psycopg.conninfo.make_conninfo(
            host="127.0.0.1",
            port=port,
            user="postgres",
            password=password,
            dbname=os.environ.get("THESISTRACE_POSTGRES_DB", "thesistrace"),
            connect_timeout=10,
        )
        authoritative = load_restore_snapshot(connection_info)
        files = {
            "session_manifest": state_dir / "local-acceptance-session.json",
            "release_pointer": state_dir / "releases" / "current.json",
            "product_context": state_dir / "public-origin-context.json",
        }
        return {
            "authoritative_state_sha256": hashlib.sha256(
                canonical_json_bytes(authoritative)
            ).hexdigest(),
            "input_files": {name: _sha256(path) for name, path in files.items()},
        }
    except (OSError, TypeError, ValueError, psycopg.Error) as error:
        raise LocalBoundaryAcceptanceError(
            "local Core state digest is unavailable"
        ) from error


def _http_json(
    origin: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{origin.rstrip('/')}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        context = (
            ssl._create_unverified_context()
            if origin.startswith("https://")
            and os.environ.get("THESISTRACE_SMOKE_INSECURE_TLS") == "1"
            else None
        )
        response = urllib.request.urlopen(request, timeout=30, context=context)
    except urllib.error.HTTPError as error:
        response = error
    try:
        payload = json.loads(response.read())
    except json.JSONDecodeError:
        payload = {}
    return int(response.status), payload if isinstance(payload, dict) else {}


def probe_live_edge() -> dict[str, object]:
    origin = os.environ.get("THESISTRACE_HOSTED_ORIGIN")
    state_value = os.environ.get("THESISTRACE_HOST_STATE_DIR")
    if not origin or not state_value:
        raise LocalBoundaryAcceptanceError(
            "THESISTRACE_HOSTED_ORIGIN and THESISTRACE_HOST_STATE_DIR are required"
        )
    try:
        credentials = json.loads(
            (Path(state_value) / "public-origin-credentials.json").read_text()
        )
        email = str(credentials["email_a"])
        password = str(credentials["password_a"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise LocalBoundaryAcceptanceError(
            "retained local identity is unavailable for edge probing"
        ) from error
    login_status, login = _http_json(
        origin,
        "/api/auth/sessions?client_type=server",
        method="POST",
        body={"email": email, "password": password},
    )
    token = login.get("accessToken")
    if login_status != 200 or not isinstance(token, str):
        raise LocalBoundaryAcceptanceError("live edge login failed")

    routes = {
        "/api/v1/session": 200,
        "/storage/acceptance": 404,
        "/storage/nested/acceptance": 404,
        "/storage/%2e%2e/acceptance": 404,
        "/storage/v1/object/sign/acceptance": 404,
        "/api/storage/acceptance": 404,
    }
    results: dict[str, object] = {}
    for path, expected in routes.items():
        status, _payload = _http_json(origin, path, token=token)
        if status != expected:
            raise LocalBoundaryAcceptanceError(
                f"live edge route {path} returned {status}, expected {expected}"
            )
        results[path] = {"status": status, "expected": expected}
    unauthenticated, _payload = _http_json(origin, "/api/v1/session")
    if unauthenticated not in {401, 403}:
        raise LocalBoundaryAcceptanceError(
            f"unauthenticated product route returned {unauthenticated}"
        )
    results["/api/v1/session#unauthenticated"] = {
        "status": unauthenticated,
        "expected": [401, 403],
    }
    return {"status": "passed", "routes": results}


def run_boundary_acceptance(
    *,
    runner: Runner = execute,
    state_reader: StateReader = core_state_digest,
    edge_prober: EdgeProber = probe_live_edge,
) -> dict[str, object]:
    state_before = state_reader()
    postgres_output = runner((sys.executable, str(LOCAL_POSTGRES)))
    postgres = _last_json(postgres_output)
    if postgres.get("status") != "passed":
        raise LocalBoundaryAcceptanceError("local PostgreSQL evidence did not pass")
    controlled_results: dict[str, object] = {}
    for target in CONTROLLED_TARGETS:
        controlled_output = runner((sys.executable, "-m", "pytest", "-q", target))
        controlled_results[target] = {
            "status": "passed",
            "output_sha256": hashlib.sha256(controlled_output).hexdigest(),
        }
    edge = edge_prober()
    state_after = state_reader()
    if state_after != state_before:
        raise LocalBoundaryAcceptanceError(
            "local boundary probes changed the reusable Core state digest"
        )
    return {
        "status": "passed",
        "schema_version": "hosted-local-boundary-v1",
        "postgresql": postgres,
        "edge_routes": edge,
        "controlled_tests": controlled_results,
        "core_state": {"before": state_before, "after": state_after, "restored": True},
        "sub_boundaries": {
            "postgresql_rls": {"status": "passed", "evidence": "postgresql"},
            "edge": {"status": "passed", "evidence": "edge_routes"},
            "storage": {
                "status": "passed",
                "evidence": [
                    "tests/hosted/test_storage_admission.py",
                    "tests/hosted/test_object_store_boundary.py",
                ],
            },
            "container_and_network": {
                "status": "passed",
                "evidence": "tests/hosted/test_container_boundaries.py",
            },
            "telemetry_redaction": {
                "status": "passed",
                "evidence": (
                    "tests/hosted/test_compose_stack.py::"
                    "test_otel_sampling_and_export_failure_are_bounded_and_visible"
                ),
            },
        },
    }


def main() -> None:
    if os.environ.get("THESISTRACE_LOCAL_ACCEPTANCE") != "1":
        raise LocalBoundaryAcceptanceError(
            "local boundary acceptance requires THESISTRACE_LOCAL_ACCEPTANCE=1"
        )
    print(json.dumps(run_boundary_acceptance(), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except LocalBoundaryAcceptanceError as error:
        raise SystemExit(str(error)) from error

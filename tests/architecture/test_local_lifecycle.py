from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_development_commands_use_the_canonical_compose_runtime() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    scripts = package["scripts"]

    assert scripts["bootstrap"] == "./scripts/dev-runtime bootstrap"
    assert scripts["dev"] == "./scripts/dev-runtime watch"
    assert scripts["dev:logs"] == "./scripts/dev-runtime logs"
    assert scripts["dev:up"] == "./scripts/dev-runtime up"
    assert scripts["dev:reset"] == "./scripts/dev-runtime reset"
    assert scripts["dev:stop"] == "./scripts/dev-runtime stop"
    assert "dev:down" not in scripts

    lifecycle = (ROOT / "scripts" / "dev-runtime").read_text()
    assert "project_name=thesistrace-dev" in lifecycle
    assert "mise exec -- pnpm install --frozen-lockfile" in lifecycle
    assert "compose up --detach --build --wait --wait-timeout 300" in lifecycle
    assert "compose up --watch" in lifecycle
    assert "compose logs --follow --timestamps" in lifecycle
    assert "compose stop" in lifecycle


@pytest.mark.parametrize(
    "project_name",
    (
        "",
        "thesistrace-test-run-123",
        "thesistrace-production",
        "ThesisTrace-Dev",
        "unrelated-project",
    ),
)
def test_development_reset_rejects_every_noncanonical_project(project_name: str) -> None:
    environment = {**os.environ, "THESISTRACE_DEV_PROJECT_NAME": project_name}

    completed = subprocess.run(
        ["mise", "exec", "--", "pnpm", "dev:reset"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 2
    assert "refusing non-canonical Development project" in completed.stderr


def test_development_topology_declares_every_core_service_and_pinned_infrastructure() -> None:
    compose = (ROOT / "deploy" / "core" / "compose.yaml").read_text()

    for service in ("postgres", "rustfs", "migrate", "api", "worker", "web"):
        assert f"  {service}:\n" in compose
    assert "postgres:16.10-alpine" in compose
    assert "rustfs/rustfs:1.0.0-beta.12" in compose
    assert ":latest" not in compose
    assert "service_completed_successfully" in compose
    assert "thesistrace-core-worker\", \"--healthcheck" in compose


def test_container_builds_exclude_host_dependency_directories() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    backend = (ROOT / "deploy" / "core" / "Dockerfile.backend").read_text()
    web = (ROOT / "deploy" / "core" / "Dockerfile.web").read_text()

    assert ".venv" in dockerignore
    assert "node_modules" in dockerignore
    assert "web/node_modules" in dockerignore
    assert "node_modules" not in backend
    assert "node_modules" not in web
    assert "node:24.14.0-bookworm-slim" in web
    assert "pnpm@11.9.0" in web


def test_development_watch_assigns_service_appropriate_actions() -> None:
    development = (ROOT / "deploy" / "core" / "compose.dev.yaml").read_text()

    assert "thesistrace.entrypoints.http:app" in development
    assert "--reload-dir" in development
    assert "action: sync+restart" in development
    assert "action: sync" in development
    assert "action: rebuild" in development
    assert "node_modules/" in development
    assert "target: /app/src" in development
    assert "target: /app/web" in development


@pytest.mark.parametrize("wrapper_signal", (signal.SIGINT, signal.SIGTERM))
def test_development_watch_streams_stderr_and_forwards_termination(
    tmp_path: Path,
    wrapper_signal: signal.Signals,
) -> None:
    signal_file = tmp_path / "watch-signal"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os
import signal
import sys

arguments = " ".join(sys.argv[1:])
if "config --quiet" in arguments:
    raise SystemExit(0)
if "up --watch" not in arguments:
    raise SystemExit(2)

def terminate(_signum, _frame):
    with open(os.environ["WATCH_SIGNAL_FILE"], "w") as signal_file:
        signal_file.write("TERM")
    print("panic: close of closed channel", file=sys.stderr, flush=True)
    print("watch panic trace", file=sys.stderr, flush=True)
    raise SystemExit(2)

signal.signal(signal.SIGTERM, terminate)
print("watch-warning", file=sys.stderr, flush=True)
signal.pause()
"""
    )
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "WATCH_SIGNAL_FILE": str(signal_file),
    }

    process = subprocess.Popen(
        [ROOT / "scripts" / "dev-runtime", "watch"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stderr is not None
        assert process.stderr.readline() == "watch-warning\n"
        process.send_signal(wrapper_signal)
        _, remaining_stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 0
    assert signal_file.read_text() == "TERM"
    assert "panic: close of closed channel" not in remaining_stderr

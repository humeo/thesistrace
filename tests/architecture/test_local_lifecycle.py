from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fake_test_runtime_commands(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    command_log = tmp_path / "commands.log"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/bin/sh
printf 'docker %s\\n' "$*" >> "$TEST_COMMAND_LOG"
case " $* " in
  *" port postgres 5432 ") printf '127.0.0.1:40101\\n' ;;
  *" port rustfs 9000 ") printf '127.0.0.1:40102\\n' ;;
  *" ps --all --quiet ") printf 'container-test-id\\n' ;;
  *" ps --all ") printf 'test services\\n' ;;
  *" logs --no-color --timestamps ") printf 'test logs\\n' ;;
esac
if [ "${1:-}" = inspect ]; then
  printf 'container inspection\\n'
fi
"""
    )
    docker.chmod(0o755)
    uv = tmp_path / "uv"
    uv.write_text(
        """#!/bin/sh
printf 'uv %s db=%s s3=%s bucket=%s\\n' \
  "$*" "$THESISTRACE_DATABASE_URL" "$THESISTRACE_S3_ENDPOINT_URL" \
  "$THESISTRACE_S3_BUCKET" >> "$TEST_COMMAND_LOG"
for argument in "$@"; do
  case "$argument" in
    --junitxml=*)
      report=${argument#--junitxml=}
      mkdir -p "$(dirname "$report")"
      printf '<testsuite />\\n' > "$report"
      ;;
  esac
done
exit "${FAKE_PYTEST_STATUS:-0}"
"""
    )
    uv.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "TEST_COMMAND_LOG": str(command_log),
        "THESISTRACE_TEST_STATE_ROOT": str(tmp_path / "runs"),
    }
    return command_log, environment


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


def test_integration_command_generates_unique_test_identities() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    assert package["scripts"]["test:integration"] == "./scripts/test-runtime integration"

    projects = {
        subprocess.run(
            [ROOT / "scripts" / "test-runtime", "identity"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for _ in range(2)
    }

    assert len(projects) == 2
    assert all(project.startswith("thesistrace-test-") for project in projects)
    assert "thesistrace-dev" not in projects


def test_test_overlay_uses_random_loopback_ports_and_project_scoped_volumes() -> None:
    overlay = (ROOT / "deploy" / "core" / "compose.test-run.yaml").read_text()
    base = (ROOT / "deploy" / "core" / "compose.yaml").read_text()

    for port in (5432, 9000, 8100, 5173):
        assert f"127.0.0.1::{port}" in overlay
    for development_port in (55432, 59010, 8101, 5274):
        assert str(development_port) not in overlay
    assert "postgres-data:" in base
    assert "rustfs-data:" in base
    assert "name:" not in base.split("volumes:", maxsplit=1)[1]


@pytest.mark.parametrize(
    "project_name",
    (
        "",
        "thesistrace-dev",
        "thesistrace-core-test",
        "thesistrace-test-production",
        "thesistrace-test-release-1",
        "ThesisTrace-test-run-1",
        "unrelated-project",
    ),
)
def test_test_cleanup_rejects_unsafe_project_identities(
    tmp_path: Path,
    project_name: str,
) -> None:
    marker = tmp_path / "docker-invoked"
    docker = tmp_path / "docker"
    docker.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n")
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "THESISTRACE_TEST_PROJECT_NAME": project_name,
    }

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "cleanup"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 2
    assert "refusing non-canonical Test project" in completed.stderr
    assert not marker.exists()


def test_integration_runtime_validates_starts_host_tests_and_cleans(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "integration"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    commands = command_log.read_text()
    assert commands.index("config --quiet") < commands.index("up --detach")
    assert "up --detach --build --wait --wait-timeout 300 postgres rustfs migrate" in commands
    assert "uv run pytest -q tests/integration tests/acceptance" in commands
    assert "db=postgresql://thesistrace:thesistrace-test@127.0.0.1:40101" in commands
    assert "s3=http://127.0.0.1:40102" in commands
    assert "down --volumes --remove-orphans" in commands


def test_failed_integration_captures_evidence_before_default_cleanup(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_PYTEST_STATUS"] = "7"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "integration"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 7
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    evidence = tmp_path / "runs" / run_id / "evidence"
    assert (evidence / "pytest.xml").exists()
    assert (evidence / "compose-ps.txt").read_text().strip() == "test services"
    assert (evidence / "compose-logs.txt").read_text().strip() == "test logs"
    assert "container inspection" in (evidence / "container-inspect.txt").read_text()
    commands = command_log.read_text()
    assert commands.index("ps --all") < commands.index("down --volumes")


def test_keep_environment_preserves_only_a_failing_test_project(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_PYTEST_STATUS"] = "9"

    completed = subprocess.run(
        [
            ROOT / "scripts" / "test-runtime",
            "integration",
            "--keep-environment",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 9
    assert "preserved failing Test project thesistrace-test-" in completed.stderr
    assert "down --volumes --remove-orphans" not in command_log.read_text()

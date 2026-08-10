from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fake_test_runtime_commands(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    command_log = tmp_path / "commands.log"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
import time

arguments = sys.argv[1:]
log = Path(os.environ["TEST_COMMAND_LOG"])
with log.open("a") as stream:
    stream.write(f"docker {' '.join(arguments)}\\n")
if arguments[0] == "inspect":
    print("container inspection")
    raise SystemExit(0)
if arguments[:2] == ["network", "inspect"]:
    print("true")
    raise SystemExit(0)
if arguments[:2] == ["image", "tag"]:
    raise SystemExit(0)

project = arguments[arguments.index("--project-name") + 1]
if "up" in arguments:
    with log.open("a") as stream:
        stream.write(
            f"resources {project}_default {project}_postgres-data "
            f"{project}_rustfs-data\\n"
        )
if "port" in arguments:
    mapping_path = Path(os.environ["TEST_PORT_MAP"])
    lock_path = mapping_path.with_suffix(".lock")
    while True:
        try:
            lock_path.mkdir()
            break
        except FileExistsError:
            time.sleep(0.01)
    try:
        mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
        if project not in mapping:
            mapping[project] = 41000 + len(mapping) * 4
            mapping_path.write_text(json.dumps(mapping))
        base_port = mapping[project]
    finally:
        lock_path.rmdir()
    service = arguments[arguments.index("port") + 1]
    offset = {"postgres": 1, "rustfs": 2, "api": 3, "web": 4}[service]
    print(f"127.0.0.1:{base_port + offset}")
elif "ps" in arguments and "--quiet" in arguments:
    print("container-test-id")
elif "ps" in arguments:
    print("test services")
elif "logs" in arguments:
    print("test logs")
elif "images" in arguments:
    print('{"ID":"sha256:test-image"}')
smoke_script = next(
    (argument for argument in arguments if argument.endswith("production_image_smoke.py")),
    None,
)
if "run" in arguments and smoke_script is not None:
    phase = arguments[arguments.index(smoke_script) + 1]
    failing_phase = os.environ.get("FAKE_IMAGE_SMOKE_PHASE", "before")
    if phase == failing_phase and os.environ.get("FAKE_IMAGE_SMOKE_STATUS"):
        print(f"fake {phase} image smoke failure", file=sys.stderr)
        raise SystemExit(int(os.environ["FAKE_IMAGE_SMOKE_STATUS"]))
if "down" in arguments:
    raise SystemExit(int(os.environ.get("FAKE_CLEANUP_STATUS", "0")))
"""
    )
    docker.chmod(0o755)
    uv = tmp_path / "uv"
    uv.write_text(
        """#!/bin/sh
release_pipe=
cleanup_fake_pytest() {
  if [ -n "$release_pipe" ]; then
    rm -f -- "$release_pipe"
  fi
}
terminate_fake_pytest() {
  cleanup_fake_pytest
  if [ -n "${TEST_SIGNAL_FILE:-}" ]; then
    printf TERM > "$TEST_SIGNAL_FILE"
  fi
  exit 143
}
trap terminate_fake_pytest TERM
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
case " $* " in
  *" pytest "*)
    if [ -n "${FAKE_PYTEST_READY_DIR:-}" ] && \
       [ -z "${THESISTRACE_DATABASE_RESTART_PHASE:-}" ]; then
      mkdir -p "$FAKE_PYTEST_READY_DIR" "$FAKE_PYTEST_RELEASE_DIR"
      release_pipe="$FAKE_PYTEST_RELEASE_DIR/$$"
      mkfifo "$release_pipe"
      : > "$FAKE_PYTEST_READY_DIR/$$"
      IFS= read -r _ < "$release_pipe"
      cleanup_fake_pytest
    fi
    exit "${FAKE_PYTEST_STATUS:-0}"
    ;;
esac
exit 0
"""
    )
    uv.chmod(0o755)
    bun = tmp_path / "bun"
    bun.write_text(
        """#!/bin/sh
printf 'bun %s origin=%s evidence=%s\\n' \
  "$*" "$THESISTRACE_TEST_WEB_ORIGIN" "$THESISTRACE_TEST_EVIDENCE_DIR" \
  >> "$TEST_COMMAND_LOG"
mkdir -p "$THESISTRACE_TEST_EVIDENCE_DIR/playwright-report"
printf '<html>report</html>\\n' \
  > "$THESISTRACE_TEST_EVIDENCE_DIR/playwright-report/index.html"
if [ "${FAKE_PLAYWRIGHT_STATUS:-0}" -ne 0 ]; then
  mkdir -p "$THESISTRACE_TEST_EVIDENCE_DIR/playwright-results/failure"
  printf trace > "$THESISTRACE_TEST_EVIDENCE_DIR/playwright-results/failure/trace.zip"
  printf screenshot \
    > "$THESISTRACE_TEST_EVIDENCE_DIR/playwright-results/failure/test-failed-1.png"
  printf video > "$THESISTRACE_TEST_EVIDENCE_DIR/playwright-results/failure/video.webm"
fi
exit "${FAKE_PLAYWRIGHT_STATUS:-0}"
"""
    )
    bun.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "TEST_COMMAND_LOG": str(command_log),
        "TEST_PORT_MAP": str(tmp_path / "ports.json"),
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
    assert "compose_exec up --watch" in lifecycle
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
        [ROOT / "scripts" / "dev-runtime", "reset"],
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
    assert "web/.test-workspace" in dockerignore
    assert "web/test-results" in dockerignore
    assert "web/playwright-report" in dockerignore
    assert "node_modules" not in backend
    assert "node_modules" not in web
    assert backend.index("uv sync --frozen --no-dev --no-install-project") < backend.index(
        "COPY src ./src"
    )
    assert backend.index("COPY src ./src") < backend.rindex("uv sync --frozen --no-dev")
    assert "--mount=type=cache,target=/root/.cache/uv" in backend
    assert "node:24.14.0-bookworm-slim" in web
    assert "nginx:1.27.5-alpine" in web
    assert "pnpm@11.9.0" in web
    assert "--mount=type=cache,target=/root/.local/share/pnpm/store" in web
    assert "pnpm --dir web build" in web
    assert "COPY --from=build /app/web/dist" in web


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
    stop_file = tmp_path / "watch-stop"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os
import signal
import sys

arguments = " ".join(sys.argv[1:])
if "config --quiet" in arguments:
    raise SystemExit(0)
if "stop" in arguments:
    with open(os.environ["WATCH_STOP_FILE"], "w") as stop_file:
        stop_file.write("stop")
    raise SystemExit(0)
if "up --watch" not in arguments:
    raise SystemExit(2)

def terminate(signum, _frame):
    with open(os.environ["WATCH_SIGNAL_FILE"], "w") as signal_file:
        signal_file.write(signal.Signals(signum).name)
    print("panic: close of closed channel", file=sys.stderr, flush=True)
    print("watch panic trace", file=sys.stderr, flush=True)
    raise SystemExit(2)

signal.signal(signal.SIGINT, terminate)
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
        "WATCH_STOP_FILE": str(stop_file),
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
    assert signal_file.read_text() == wrapper_signal.name
    assert stop_file.read_text() == "stop"
    assert "panic: close of closed channel" not in remaining_stderr


def test_development_watch_keeps_compose_in_the_wrapper_process_group(
    tmp_path: Path,
) -> None:
    process_group_file = tmp_path / "watch-process-group.json"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import sys

arguments = " ".join(sys.argv[1:])
if "config --quiet" in arguments:
    raise SystemExit(0)
if "up --watch" not in arguments:
    raise SystemExit(2)

Path(os.environ["WATCH_PROCESS_GROUP_FILE"]).write_text(
    json.dumps(
        {
            "process_group": os.getpgrp(),
            "wrapper_process_group": os.getpgid(os.getppid()),
        }
    )
)
signal.pause()
"""
    )
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "WATCH_PROCESS_GROUP_FILE": str(process_group_file),
    }

    process_id, terminal = os.forkpty()
    if process_id == 0:
        os.chdir(ROOT)
        os.execve(ROOT / "scripts" / "dev-runtime", ["dev-runtime", "watch"], environment)

    try:
        deadline = time.monotonic() + 5
        while not process_group_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert process_group_file.exists()
        process_groups = json.loads(process_group_file.read_text())
        assert process_groups["process_group"] == process_groups["wrapper_process_group"]
    finally:
        if process_group_file.exists():
            process_group = json.loads(process_group_file.read_text())["process_group"]
            os.killpg(process_group, signal.SIGKILL)
        else:
            os.kill(process_id, signal.SIGKILL)
        os.waitpid(process_id, 0)
        os.close(terminal)


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
        "thesistrace-test-20260806t120000z-123-abcdef12",
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
    assert "refusing" in completed.stderr
    assert not marker.exists()


def test_test_cleanup_accepts_only_an_identity_with_matching_run_metadata(
    tmp_path: Path,
) -> None:
    project_name = "thesistrace-test-20260806t120000z-123-abcdef12"
    run_id = project_name.removeprefix("thesistrace-test-")
    run_root = tmp_path / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / "run.txt").write_text(f"run_id={run_id}\nproject_name={project_name}\n")
    (run_root / "canonical-data").mkdir()
    (run_root / "canonical-data" / "HEAD.json").write_text("test data")
    marker = tmp_path / "docker-invoked"
    docker = tmp_path / "docker"
    docker.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n")
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "THESISTRACE_TEST_PROJECT_NAME": project_name,
        "THESISTRACE_TEST_STATE_ROOT": str(tmp_path / "runs"),
    }

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "cleanup"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.exists()
    assert not (run_root / "canonical-data").exists()


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
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    assert not (tmp_path / "runs" / run_id / "canonical-data").exists()
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text().splitlines()
    assert len([line for line in metadata if line.startswith("git_revision=")]) == 1
    assert len(
        [
            line
            for line in metadata
            if line in {"git_worktree_dirty=true", "git_worktree_dirty=false"}
        ]
    ) == 1
    for phase in (
        "integration-infrastructure",
        "integration-migration",
        "integration-pytest",
        "integration-database-restart",
    ):
        assert any(
            line.startswith(f"phase={phase} seconds=") and line.endswith(" status=0")
            for line in metadata
        )
    commands = command_log.read_text()
    assert commands.index("config --quiet") < commands.index("up --detach")
    assert "up --detach --wait --wait-timeout 300 postgres rustfs" in commands
    assert "--build" not in commands
    assert "uv run thesistrace-migrate" in commands
    assert "uv run pytest -q tests/integration tests/acceptance" in commands
    assert "db=postgresql://thesistrace:thesistrace-test@127.0.0.1:41001" in commands
    assert "s3=http://127.0.0.1:41002" in commands
    assert "down --volumes --remove-orphans" in commands


def test_e2e_runtime_starts_full_topology_and_runs_only_host_playwright(
    tmp_path: Path,
) -> None:
    package = json.loads((ROOT / "package.json").read_text())
    assert package["scripts"]["test:e2e"] == "./scripts/test-runtime e2e"
    command_log, environment = _fake_test_runtime_commands(tmp_path)

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "e2e"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    project_name = completed.stdout.splitlines()[1].removeprefix("Compose project: ")
    commands = command_log.read_text()
    assert commands.index("config --quiet") < commands.index("up --detach")
    assert commands.count("build migrate web\n") == 1
    assert (
        f"docker image tag {project_name}-migrate {project_name}-api\n" in commands
    )
    assert (
        f"docker image tag {project_name}-migrate {project_name}-worker\n" in commands
    )
    assert (
        "up --detach --no-build --wait --wait-timeout 300 postgres rustfs migrate\n"
        in commands
    )
    assert "wait migrate\n" in commands
    assert "up --detach --no-build --wait --wait-timeout 300 api worker web\n" in commands
    assert "--build" not in commands
    assert "uv run thesistrace-migrate" not in commands
    assert "bun run --cwd web test:e2e origin=http://127.0.0.1:41004" in commands
    assert "thesistrace-api" not in commands
    assert "thesistrace-worker" not in commands
    assert "vite --host" not in commands
    assert "down --volumes --remove-orphans" in commands


def test_standard_and_release_gates_delegate_without_repeating_the_standard_gate() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    scripts = package["scripts"]

    assert scripts["check"] == "pnpm test && pnpm test:integration && pnpm test:e2e"
    assert scripts["check"].split(" && ") == [
        "pnpm test",
        "pnpm test:integration",
        "pnpm test:e2e",
    ]
    assert scripts["check:release"] == "pnpm check && pnpm test:image-smoke"
    assert scripts["check:release"].split(" && ") == [
        "pnpm check",
        "pnpm test:image-smoke",
    ]
    assert scripts["test:integration"] == "./scripts/test-runtime integration"
    assert scripts["test:e2e"] == "./scripts/test-runtime e2e"
    assert scripts["test:image-smoke"] == "./scripts/test-runtime image-smoke"
    assert scripts["test:cleanup"] == "./scripts/test-runtime cleanup"


def test_production_image_smoke_runs_entirely_inside_an_internal_network() -> None:
    test_runtime = (ROOT / "scripts" / "test-runtime").read_text()
    image_overlay = (ROOT / "deploy" / "core" / "compose.image-smoke.yaml").read_text()
    smoke = (ROOT / "tests" / "production_image_smoke.py").read_text()

    assert "internal: true" in image_overlay
    assert "tests:/smoke:ro" in image_overlay
    assert "python /smoke/browser/prepare_current_data.py" in test_runtime
    assert test_runtime.count("python /smoke/production_image_smoke.py") == 2
    assert "compose restart api worker" in test_runtime
    assert "compose images --format json" in test_runtime
    assert 'test "$network_internal" = true' in test_runtime
    assert 'expected["attempt_count"] == 1' in smoke
    assert "read_result_bundle" in smoke


def test_production_image_smoke_builds_once_and_reuses_the_images(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "image-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    project_name = completed.stdout.splitlines()[1].removeprefix("Compose project: ")
    commands = command_log.read_text()
    assert commands.count("build migrate web\n") == 1
    assert (
        f"docker image tag {project_name}-migrate {project_name}-api\n" in commands
    )
    assert (
        f"docker image tag {project_name}-migrate {project_name}-worker\n" in commands
    )
    assert (
        "up --detach --no-build --wait --wait-timeout 300 postgres rustfs migrate\n"
        in commands
    )
    assert "wait migrate\n" in commands
    assert "up --detach --no-build --wait --wait-timeout 300 api worker web\n" in commands
    assert "up --detach --no-build --wait --wait-timeout 120 api worker\n" in commands
    assert "--build" not in commands


def test_failed_image_smoke_persists_runner_diagnostics_before_cleanup(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_IMAGE_SMOKE_STATUS"] = "9"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "image-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 9
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    evidence = tmp_path / "runs" / run_id / "evidence"
    assert "fake before image smoke failure" in (
        evidence / "smoke-before.stderr.log"
    ).read_text()
    assert (evidence / "compose-ps.txt").exists()
    assert (evidence / "compose-logs.txt").exists()
    assert (evidence / "container-inspect.txt").exists()
    commands = command_log.read_text()
    assert commands.index("production_image_smoke.py before") < commands.rindex(
        "ps --all"
    )
    assert commands.rindex("ps --all") < commands.index("down --volumes")


def test_active_lifecycle_rejects_legacy_and_hybrid_entrypoints() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    test_runtime = (ROOT / "scripts" / "test-runtime").read_text()
    active_sources = "\n".join(
        (
            package["scripts"]["test"],
            package["scripts"]["test:integration"],
            package["scripts"]["test:e2e"],
            package["scripts"]["check"],
            test_runtime,
        )
    )

    assert not (ROOT / "Makefile").exists()
    assert not (ROOT / "scripts" / "core-test-runtime").exists()
    assert not (ROOT / "deploy" / "core" / "compose.test.yaml").exists()
    assert "project_name=thesistrace-dev" not in test_runtime
    assert "--project-name thesistrace-dev" not in test_runtime
    for host_application in (
        "uv run thesistrace-core-api",
        "uv run thesistrace-core-worker",
        "vite --host",
    ):
        assert host_application not in active_sources


def test_web_assets_do_not_depend_on_the_public_network() -> None:
    active_web_source = "\n".join(
        path.read_text()
        for path in (ROOT / "web" / "src").rglob("*")
        if path.is_file() and path.suffix in {".css", ".ts", ".tsx"}
    )

    assert "fonts.googleapis.com" not in active_web_source
    assert "fonts.gstatic.com" not in active_web_source
    assert "@import url(\"http" not in active_web_source


def test_failed_e2e_groups_playwright_and_compose_evidence_before_cleanup(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_PLAYWRIGHT_STATUS"] = "6"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "e2e"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 6
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    evidence = tmp_path / "runs" / run_id / "evidence"
    assert (evidence / "playwright-report" / "index.html").exists()
    failure = evidence / "playwright-results" / "failure"
    assert (failure / "trace.zip").exists()
    assert (failure / "test-failed-1.png").exists()
    assert (failure / "video.webm").exists()
    assert (evidence / "compose-ps.txt").exists()
    assert (evidence / "compose-logs.txt").exists()
    assert (evidence / "container-inspect.txt").exists()
    commands = command_log.read_text()
    assert commands.index("bun run --cwd web test:e2e") < commands.index("ps --all")
    assert commands.index("ps --all") < commands.index("down --volumes")


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


def test_cleanup_failure_is_reported_without_masking_the_test_failure(
    tmp_path: Path,
) -> None:
    _, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_PYTEST_STATUS"] = "7"
    environment["FAKE_CLEANUP_STATUS"] = "5"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "integration"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 7
    assert "cleanup failed for Test project" in completed.stderr
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text()
    assert "cleanup_status=5" in metadata
    assert metadata.endswith("status=7\n")


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


def test_test_runtime_forwards_termination_before_evidence_and_cleanup(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    signal_file = tmp_path / "pytest-signal"
    ready_dir = tmp_path / "pytest-ready"
    release_dir = tmp_path / "pytest-release"
    environment["FAKE_PYTEST_READY_DIR"] = str(ready_dir)
    environment["FAKE_PYTEST_RELEASE_DIR"] = str(release_dir)
    environment["TEST_SIGNAL_FILE"] = str(signal_file)
    process = subprocess.Popen(
        [ROOT / "scripts" / "test-runtime", "integration"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_fake_pytest_workers(
            ready_dir,
            count=1,
            command_log=command_log,
        )
    except BaseException:
        process.kill()
        process.communicate()
        raise

    process.terminate()
    process.communicate(timeout=10)

    assert process.returncode == 143
    assert signal_file.read_text() == "TERM"
    commands = command_log.read_text()
    assert commands.index("uv run pytest") < commands.index("ps --all")
    assert commands.index("ps --all") < commands.index("down --volumes")


def test_two_concurrent_test_runs_have_disjoint_resources_and_state(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    ready_dir = tmp_path / "pytest-ready"
    release_dir = tmp_path / "pytest-release"
    environment["FAKE_PYTEST_READY_DIR"] = str(ready_dir)
    environment["FAKE_PYTEST_RELEASE_DIR"] = str(release_dir)
    processes = [
        subprocess.Popen(
            [ROOT / "scripts" / "test-runtime", "integration"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]

    try:
        worker_pids = _wait_for_fake_pytest_workers(
            ready_dir,
            count=2,
            command_log=command_log,
        )
        assert all(process.poll() is None for process in processes)
        _release_fake_pytest_workers(
            release_dir,
            worker_pids,
            command_log=command_log,
        )
        results = [process.communicate(timeout=10) for process in processes]
    except BaseException:
        for process in processes:
            process.kill()
            process.communicate()
        raise
    assert [process.returncode for process in processes] == [0, 0], results

    run_directories = sorted((tmp_path / "runs").iterdir())
    assert len(run_directories) == 2
    records = []
    for run_directory in run_directories:
        record = dict(
            line.split("=", maxsplit=1)
            for line in (run_directory / "run.txt").read_text().splitlines()
        )
        records.append(record)
    assert len({record["project_name"] for record in records}) == 2
    assert len({(record["postgres_port"], record["s3_port"]) for record in records}) == 2

    commands = command_log.read_text()
    for record in records:
        project = record["project_name"]
        assert f"resources {project}_default {project}_postgres-data" in commands
        assert f"bucket={project}" in commands
    assert "thesistrace-dev" not in commands


def _wait_for_fake_pytest_workers(
    ready_dir: Path,
    *,
    count: int,
    command_log: Path,
    timeout: float = 10,
) -> list[int]:
    deadline = time.monotonic() + timeout
    observed: list[Path] = []
    while time.monotonic() < deadline:
        observed = sorted(ready_dir.iterdir()) if ready_dir.exists() else []
        if len(observed) == count:
            return [int(path.name) for path in observed]
        time.sleep(0.01)
    commands = command_log.read_text() if command_log.exists() else "<no command log>"
    pytest.fail(
        f"expected {count} blocked fake Pytest workers; "
        f"observed={[path.name for path in observed]!r}; commands={commands!r}"
    )


def _release_fake_pytest_workers(
    release_dir: Path,
    worker_pids: list[int],
    *,
    command_log: Path,
    timeout: float = 10,
) -> None:
    for worker_pid in worker_pids:
        release_pipe = release_dir / str(worker_pid)
        deadline = time.monotonic() + timeout
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            try:
                descriptor = os.open(release_pipe, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as error:
                if error.errno not in {errno.ENOENT, errno.ENXIO}:
                    raise
                last_error = error
                time.sleep(0.01)
                continue
            try:
                payload = b"continue\n"
                written = os.write(descriptor, payload)
                if written != len(payload):
                    pytest.fail(
                        f"partial fake Pytest release for worker {worker_pid}: "
                        f"wrote {written} of {len(payload)} bytes"
                    )
                break
            finally:
                os.close(descriptor)
        else:
            commands = command_log.read_text() if command_log.exists() else "<no command log>"
            pytest.fail(
                f"timed out releasing fake Pytest worker {worker_pid}; "
                f"last_error={last_error!r}; commands={commands!r}"
            )


def test_active_documentation_exposes_the_complete_mise_pnpm_lifecycle() -> None:
    readme = (ROOT / "README.md").read_text()
    guide = (ROOT / "docs" / "runbook" / "local-lifecycle.md").read_text()
    tushare = (ROOT / "docs" / "runbook" / "tushare-live-bootstrap.md").read_text()
    active_docs = "\n".join((readme, guide, tushare))

    for command in (
        "mise exec -- pnpm bootstrap",
        "mise exec -- pnpm dev",
        "mise exec -- pnpm dev:up",
        "mise exec -- pnpm dev:logs",
        "mise exec -- pnpm dev:stop",
        "mise exec -- pnpm dev:reset",
        "mise exec -- pnpm test",
        "mise exec -- pnpm test:integration",
        "mise exec -- pnpm test:e2e",
        "mise exec -- pnpm check",
    ):
        assert command in active_docs
    assert "Node.js 24.14.0" in guide
    assert "pnpm 11.9.0" in guide
    assert "uv" in guide
    assert ".local/test-runs/<run-id>/" in guide
    assert "--keep-environment" in guide
    assert "mise exec -- pnpm test:integration --keep-environment" in guide
    assert "mise exec -- pnpm test:e2e --keep-environment" in guide
    assert "mise exec -- pnpm test:cleanup" in guide
    assert "./scripts/test-runtime cleanup" not in guide
    assert " -- --keep-environment" not in guide
    assert "only local Development and local Test" in guide
    assert "not Production readiness" in active_docs
    for retired in (
        "Makefile",
        "make dev",
        "make check",
        "dev:down",
        "core-test-runtime",
        "compose.test.yaml",
    ):
        assert retired not in active_docs


def test_full_compose_lifecycle_decision_is_recorded_without_glossary_drift() -> None:
    adr = (
        ROOT
        / "docs"
        / "adr"
        / "0152-use-one-full-compose-topology-for-local-development-and-test.md"
    ).read_text()
    glossary = (ROOT / "CONTEXT.md").read_text()

    assert "status: accepted" in adr
    assert "Web, API, Worker, PostgreSQL, RustFS" in adr
    assert "one-shot Migration" in adr
    assert "hybrid" in adr
    assert "host test runners" in adr
    assert "not Production readiness" in adr
    for engineering_term in (
        "Compose Watch",
        "Development environment",
        "Test environment",
        "pnpm bootstrap",
        "test:integration",
        "test:e2e",
    ):
        assert engineering_term not in glossary

from __future__ import annotations

import ast
import errno
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fake_development_docker(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    command_log = tmp_path / "development-commands.log"
    volume_root = tmp_path / "volumes"
    volume_root.mkdir()
    for volume in (
        "thesistrace-dev_batch-attempt-control",
        "thesistrace-dev_benchmark-data",
        "thesistrace-dev_canonical-data",
        "thesistrace-dev_postgres-data",
        "thesistrace-dev_rustfs-data",
    ):
        target = volume_root / volume
        target.mkdir()
        (target / "preserved-marker").write_text(volume)
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import os
import shutil
import sys

arguments = sys.argv[1:]
log = Path(os.environ["DEVELOPMENT_COMMAND_LOG"])
with log.open("a") as stream:
    stream.write(f"docker {' '.join(arguments)}\\n")
volume_root = Path(os.environ["DEVELOPMENT_VOLUME_ROOT"])
if arguments[:2] == ["volume", "inspect"]:
    raise SystemExit(0 if (volume_root / arguments[2]).exists() else 1)
if arguments[:2] == ["volume", "rm"]:
    for volume in arguments[2:]:
        shutil.rmtree(volume_root / volume)
    raise SystemExit(0)
if arguments[0] != "compose":
    raise SystemExit(2)
if "down" in arguments and "--volumes" in arguments:
    for volume in volume_root.iterdir():
        shutil.rmtree(volume)
if "up" in arguments:
    for volume in (
        "thesistrace-dev_batch-attempt-control",
        "thesistrace-dev_benchmark-data",
        "thesistrace-dev_canonical-data",
        "thesistrace-dev_postgres-data",
        "thesistrace-dev_rustfs-data",
    ):
        (volume_root / volume).mkdir(exist_ok=True)
raise SystemExit(0)
"""
    )
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "DEVELOPMENT_COMMAND_LOG": str(command_log),
        "DEVELOPMENT_VOLUME_ROOT": str(volume_root),
    }
    return command_log, volume_root, environment


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
backend_marker = Path(os.environ["FAKE_BACKEND_MARKER"])
if "stop" in arguments and "auth" in arguments and "api" in arguments:
    backend_marker.write_text("stopped")
if "up" in arguments and "auth" in arguments and "api" in arguments:
    backend_marker.unlink(missing_ok=True)
if arguments[0] == "inspect":
    if any(argument.startswith('{"status"') for argument in arguments):
        print('{"status":"exited","exit_code":143,"oom_killed":false}')
    elif any("Config.Env" in argument for argument in arguments):
        failing_target = os.environ.get("FAKE_ENV_INSPECT_FAILURE_TARGET")
        if failing_target and arguments[-1].endswith(f"-{failing_target}-1"):
            raise SystemExit(23)
        if arguments[-1].endswith("-data-operator-worker-1"):
            print("THESISTRACE_TUSHARE_TOKEN=worker-only-secret")
        else:
            print("PATH=/usr/bin")
    else:
        print("container inspection")
    raise SystemExit(0)
if arguments[0] == "stop":
    raise SystemExit(0)
if arguments[0] == "logs":
    print("outage api logs")
    raise SystemExit(0)
if arguments[:2] == ["network", "inspect"]:
    print("true")
    raise SystemExit(0)
if arguments[:2] == ["image", "tag"]:
    failing_target = os.environ.get("FAKE_IMAGE_TAG_FAILURE_TARGET")
    if failing_target and arguments[-1].endswith(f"-{failing_target}"):
        raise SystemExit(6)
    raise SystemExit(0)
if arguments[:2] == ["image", "inspect"]:
    print("sha256:test-image")
    raise SystemExit(0)
if arguments[:2] == ["image", "rm"]:
    raise SystemExit(0)
if arguments[:2] == ["volume", "inspect"]:
    raise SystemExit(0)
if arguments[:2] == ["volume", "rm"]:
    raise SystemExit(0)
if arguments[0] == "run" and "--project-name" not in arguments:
    print('{"classified":true,"child_returncode":-9}')
    raise SystemExit(0)
if "config" in arguments and os.environ.get("FAKE_CONFIG_STATUS"):
    raise SystemExit(int(os.environ["FAKE_CONFIG_STATUS"]))

project = arguments[arguments.index("--project-name") + 1]
if "build" in arguments and os.environ.get("FAKE_BUILD_STATUS"):
    raise SystemExit(int(os.environ["FAKE_BUILD_STATUS"]))
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
            mapping[project] = 41000 + len(mapping) * 5
            mapping_path.write_text(json.dumps(mapping))
        base_port = mapping[project]
    finally:
        lock_path.rmdir()
    service = arguments[arguments.index("port") + 1]
    offset = {
        "postgres": 1,
        "rustfs": 2,
        "auth": 3,
        "api": 4,
        "web": 5,
        "resend-fake": 6,
    }[service]
    print(f"127.0.0.1:{base_port + offset}")
elif "ps" in arguments and "--quiet" in arguments:
    print(f"container-test-id-{arguments[-1]}")
elif "ps" in arguments:
    print("test services")
elif "logs" in arguments:
    if "research-worker" in arguments and "tracking-worker" in arguments:
        print('{"event":"worker_started","role":"research"}')
        print('{"event":"worker_started","role":"tracking"}')
        print('{"event":"worker_claim","role":"research"}')
        print('{"event":"worker_claim","role":"tracking"}')
    else:
        print(os.environ.get("FAKE_COMPOSE_LOGS", "test logs"))
elif "images" in arguments:
    print('{"ID":"sha256:test-image"}')
if (
    "run" in arguments
    and "thesistrace-data-operator" in arguments
    and "bootstrap" in arguments
):
    data_mount = Path(os.environ["THESISTRACE_TEST_DATA_MOUNT"])
    data_mount.mkdir(parents=True, exist_ok=True)
    (data_mount / "HEAD.json").write_text("fake Dataset Head")
smoke_script = next(
    (argument for argument in arguments if argument.endswith("production_image_smoke.py")),
    None,
)
mcp_smoke_script = next(
    (argument for argument in arguments if argument.endswith("production_mcp_image_smoke.py")),
    None,
)
qualification_script = next(
    (argument for argument in arguments if argument.endswith("long_research_qualification.py")),
    None,
)
if (
    "run" in arguments
    and qualification_script is not None
    and arguments[arguments.index(qualification_script) + 1] == "sample"
):
    failure_target = os.environ.get("FAKE_LONG_RESEARCH_SAMPLE_FAILURE")
    research_kind = arguments[arguments.index("--research-kind") + 1]
    phase = arguments[arguments.index("--phase") + 1]
    index = arguments[arguments.index("--index") + 1]
    if failure_target == f"{research_kind}:{phase}:{index}":
        raise SystemExit(7)
if "run" in arguments and mcp_smoke_script is not None:
    print('{"status":"passed"}')
    phase = arguments[arguments.index(mcp_smoke_script) + 1]
    if phase == os.environ.get("FAKE_MCP_IMAGE_SMOKE_PHASE") and os.environ.get(
        "FAKE_MCP_IMAGE_SMOKE_STATUS"
    ):
        print(f"fake {phase} MCP image smoke failure", file=sys.stderr)
        raise SystemExit(int(os.environ["FAKE_MCP_IMAGE_SMOKE_STATUS"]))
if "run" in arguments and smoke_script is not None:
    phase = arguments[arguments.index(smoke_script) + 1]
    failing_phase = os.environ.get("FAKE_IMAGE_SMOKE_PHASE", "before")
    if phase == failing_phase and os.environ.get("FAKE_IMAGE_SMOKE_STATUS"):
        print(f"fake {phase} image smoke failure", file=sys.stderr)
        raise SystemExit(int(os.environ["FAKE_IMAGE_SMOKE_STATUS"]))
if "run" in arguments and "--cpu-count" in arguments:
    role = arguments[arguments.index("--role") + 1]
    print(
        '{"component":"' + role + '_worker","event":"worker_startup_failed",'
        '"failure_code":"WORKER_CAPACITY_INVALID","level":"ERROR"}',
        file=sys.stderr,
    )
    raise SystemExit(2)
if "run" in arguments and "--memory-bytes" in arguments:
    role = arguments[arguments.index("--role") + 1]
    print(
        '{"component":"' + role + '_worker","event":"worker_startup_failed",'
        '"failure_code":"WORKER_CAPACITY_INVALID","level":"ERROR"}',
        file=sys.stderr,
    )
    raise SystemExit(2)
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
case "${3:-}" in
  */locked-loopback-port)
    shift 2
    exec python3 "$@"
    ;;
esac
printf 'uv %s db=%s s3=%s bucket=%s\\n' \
  "$*" "$THESISTRACE_DATABASE_URL" "$THESISTRACE_S3_ENDPOINT_URL" \
  "$THESISTRACE_S3_BUCKET" >> "$TEST_COMMAND_LOG"
if [ "${1:-}" = run ] && [ "${2:-}" = python ] && \
   [ "$(basename "${3:-}")" = sanitize_production_mcp_evidence.py ]; then
  if [ "${4:-}" = sanitize ] && [ -n "${FAKE_SANITIZER_STATUS:-}" ]; then
    exit "$FAKE_SANITIZER_STATUS"
  fi
  python3 "$3" "$4" "$5"
  exit $?
fi
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
  *" provision_image_smoke_auth.py "*)
    output=
    for argument in "$@"; do
      output=$argument
    done
    mkdir -p "$(dirname "$output")"
    printf '%s\n' \
      '{"cookie":"fake-session-cookie","researcher_id":"00000000-0000-4000-8000-000000000099"}' \
      > "$output"
    chmod 600 "$output"
    ;;
  *" python -c "*)
    target=
    for argument in "$@"; do
      target=$argument
    done
    test -s "$target" || exit 1
    grep -Fqx '{"status": "passed"}' "$target" || exit 1
    ;;
  *" pytest "*)
    if [ -n "${THESISTRACE_REAL_CODEX_EVIDENCE_PATH:-}" ] && \
       [ -z "${FAKE_SKIP_CODEX_EVIDENCE:-}" ]; then
      mkdir -p "$(dirname "$THESISTRACE_REAL_CODEX_EVIDENCE_PATH")"
      if [ -n "${FAKE_INVALID_CODEX_EVIDENCE:-}" ]; then
        printf '{"status": "failed", "nested": {"status": "passed"}}\n' \
          > "$THESISTRACE_REAL_CODEX_EVIDENCE_PATH"
      else
        printf '{"status": "passed"}\n' > "$THESISTRACE_REAL_CODEX_EVIDENCE_PATH"
      fi
    fi
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
    pnpm = tmp_path / "pnpm"
    pnpm.write_text(
        """#!/bin/sh
printf 'pnpm %s origin=%s evidence=%s\\n' \
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
    pnpm.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text(
        """#!/bin/sh
set -eu
output=
write_out=false
fail=false
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output|-o)
      output=$2
      shift 2
      ;;
    --write-out|-w)
      write_out=true
      shift 2
      ;;
    --fail|-f)
      fail=true
      shift
      ;;
    http://*)
      url=$1
      shift
      ;;
    *) shift ;;
  esac
done
status=200
body='<html><div id="root"></div></html>'
case "$url" in
  */health/*|*/internal/*) status=404; body='' ;;
  */api/auth/ok) body='{"ok":true}' ;;
  */api/data) status=401; body='{"detail":"Authentication required"}' ;;
esac
if [ -f "$FAKE_BACKEND_MARKER" ]; then
  case "$url" in
    */api/auth/*|*/api/*) status=502; body='' ;;
  esac
fi
if [ -n "$output" ]; then
  if [ "$output" != /dev/null ]; then
    printf '%s\\n' "$body" >"$output"
  fi
else
  printf '%s\\n' "$body"
fi
if [ "$write_out" = true ]; then
  printf '%s' "$status"
fi
if [ "$fail" = true ] && [ "$status" -ge 400 ]; then
  exit 22
fi
"""
    )
    curl.chmod(0o755)
    codex = tmp_path / "codex"
    codex.write_text('#!/bin/sh\nexit "${FAKE_CODEX_STATUS:-0}"\n')
    codex.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_BACKEND_MARKER": str(tmp_path / "backends-stopped"),
        "TEST_COMMAND_LOG": str(command_log),
        "TEST_PORT_MAP": str(tmp_path / "ports.json"),
        "THESISTRACE_TEST_STATE_ROOT": str(tmp_path / "runs"),
        "THESISTRACE_TEST_PORT_LOCK_ROOT": str(tmp_path / "port-locks"),
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
    assert scripts["dev:erase"] == "./scripts/dev-runtime erase"
    assert scripts["dev:stop"] == "./scripts/dev-runtime stop"
    assert "dev:down" not in scripts

    lifecycle = (ROOT / "scripts" / "dev-runtime").read_text()
    assert "project_name=thesistrace-dev" in lifecycle
    assert "mise exec -- pnpm install --frozen-lockfile" in lifecycle
    assert "compose up --detach --build --wait --wait-timeout 300" in lifecycle
    assert "compose_exec up --watch" in lifecycle
    assert "compose logs --follow --timestamps" in lifecycle
    assert "compose stop" in lifecycle


@pytest.mark.parametrize("command", ("reset", "erase"))
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
def test_destructive_development_commands_reject_every_noncanonical_project(
    command: str,
    project_name: str,
) -> None:
    environment = {**os.environ, "THESISTRACE_DEV_PROJECT_NAME": project_name}

    completed = subprocess.run(
        [ROOT / "scripts" / "dev-runtime", command],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 2
    assert "refusing non-canonical Development project" in completed.stderr


def test_development_reset_recreates_only_product_state_volumes(tmp_path: Path) -> None:
    command_log, volume_root, environment = _fake_development_docker(tmp_path)
    canonical_head = volume_root / "thesistrace-dev_canonical-data" / "HEAD.json"
    canonical_head.write_text("frozen-dataset-head")
    benchmark_snapshot = (
        volume_root
        / "thesistrace-dev_benchmark-data"
        / "csi300-price-index-open.json"
    )
    benchmark_snapshot.write_text("frozen-benchmark-snapshot")

    completed = subprocess.run(
        [ROOT / "scripts" / "dev-runtime", "reset"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert canonical_head.read_text() == "frozen-dataset-head"
    assert benchmark_snapshot.read_text() == "frozen-benchmark-snapshot"
    assert (
        volume_root / "thesistrace-dev_canonical-data" / "preserved-marker"
    ).exists()
    for volume in ("batch-attempt-control", "postgres-data", "rustfs-data"):
        recreated = volume_root / f"thesistrace-dev_{volume}"
        assert recreated.is_dir()
        assert not (recreated / "preserved-marker").exists()
    commands = command_log.read_text()
    assert "down --remove-orphans" in commands
    assert "down --volumes" not in commands
    assert "volume rm thesistrace-dev_postgres-data" in commands
    assert "volume rm thesistrace-dev_rustfs-data" in commands
    assert "volume rm thesistrace-dev_batch-attempt-control" in commands
    assert "volume rm thesistrace-dev_canonical-data" not in commands
    assert "volume rm thesistrace-dev_benchmark-data" not in commands
    assert "up --detach --build --wait --wait-timeout 300" in commands


def test_development_erase_removes_every_development_volume(tmp_path: Path) -> None:
    command_log, volume_root, environment = _fake_development_docker(tmp_path)

    completed = subprocess.run(
        [ROOT / "scripts" / "dev-runtime", "erase"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert list(volume_root.iterdir()) == []
    commands = command_log.read_text()
    assert "down --remove-orphans" in commands
    assert "down --volumes" not in commands
    assert "volume rm thesistrace-dev_postgres-data" in commands
    assert "volume rm thesistrace-dev_rustfs-data" in commands
    assert "volume rm thesistrace-dev_batch-attempt-control" in commands
    assert "volume rm thesistrace-dev_canonical-data" in commands
    assert "volume rm thesistrace-dev_benchmark-data" in commands
    assert "up --detach" not in commands


def test_development_topology_declares_every_core_service_and_pinned_infrastructure() -> None:
    compose = (ROOT / "deploy" / "core" / "compose.yaml").read_text()

    for service in (
        "postgres",
        "rustfs",
        "auth-initialize",
        "auth",
        "initialize",
        "api",
        "research-worker",
        "batch-research-worker",
        "tracking-worker",
        "web",
    ):
        assert f"  {service}:\n" in compose
    assert "postgres:16.10-alpine" in compose
    assert "rustfs/rustfs:1.0.0-beta.12" in compose
    assert ":latest" not in compose
    assert "service_completed_successfully" in compose
    research_worker = compose.split("  research-worker:\n", maxsplit=1)[1].split(
        "  batch-research-worker:\n", maxsplit=1
    )[0]
    batch_research_worker = compose.split(
        "  batch-research-worker:\n", maxsplit=1
    )[1].split("  tracking-worker:\n", maxsplit=1)[0]
    tracking_worker = compose.split("  tracking-worker:\n", maxsplit=1)[1].split(
        "  web:\n", maxsplit=1
    )[0]
    for role, variable_role, service in (
        ("research", "RESEARCH", research_worker),
        ("batch-research", "BATCH_RESEARCH", batch_research_worker),
        ("tracking", "TRACKING", tracking_worker),
    ):
        assert f"      - {role}\n" in service
        assert f"THESISTRACE_{variable_role}_WORKER_CPU_COUNT:-2" in service
        assert f"THESISTRACE_{variable_role}_WORKER_MEMORY_BYTES:-2147483648" in service
        assert (
            f"THESISTRACE_{variable_role}_WORKER_EXECUTION_MEMORY_BYTES:-1610612736"
            in service
        )
        assert f"THESISTRACE_{variable_role}_WORKER_CALCULATION_THREADS:-2" in service
        assert "healthcheck:" not in service
    assert "--healthcheck" not in compose
    api_service = compose.split("  api:\n", maxsplit=1)[1].split(
        "  research-worker:\n", maxsplit=1
    )[0]
    assert "/health/live" in api_service
    assert "/api/data" not in api_service


def test_every_compose_service_uses_bounded_docker_json_logs() -> None:
    compose = (ROOT / "deploy" / "core" / "compose.yaml").read_text()

    assert "x-bounded-logging: &bounded-logging" in compose
    assert "driver: json-file" in compose
    assert 'max-size: "10m"' in compose
    assert 'max-file: "3"' in compose
    for service in (
        "postgres",
        "rustfs",
        "auth-initialize",
        "auth",
        "initialize",
        "api",
        "research-worker",
        "batch-research-worker",
        "tracking-worker",
        "web",
    ):
        remaining = compose.split(f"  {service}:\n", maxsplit=1)[1]
        section_lines: list[str] = []
        for line in remaining.splitlines():
            if line.startswith("  ") and not line.startswith("    "):
                break
            section_lines.append(line)
        assert "    logging: *bounded-logging" in section_lines


def test_core_has_one_operational_output_schema_and_no_log_files() -> None:
    source_root = ROOT / "src" / "thesistrace"
    sources = {path: path.read_text() for path in source_root.rglob("*.py")}
    direct_print_files = {
        path.relative_to(source_root).as_posix()
        for path, source in sources.items()
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            for node in ast.walk(ast.parse(source))
        )
    }

    assert direct_print_files == {
        "entrypoints/batch_research_child.py",
        "entrypoints/data_operator.py",
        "entrypoints/diagnose.py",
        "entrypoints/live_tushare.py",
        "entrypoints/research_child.py",
        "entrypoints/tracking_child.py",
    }
    assert not [
        path.relative_to(source_root).as_posix()
        for path, source in sources.items()
        if "logger.info(" in source
        or "logger.warning(" in source
        or "logger.error(" in source
        or "logger.exception(" in source
    ]
    combined = "\n".join(sources.values())
    for obsolete in (
        "FileHandler(",
        "RotatingFileHandler(",
        "TimedRotatingFileHandler(",
        "FallbackEvent",
        "CompatibilityFormatter",
    ):
        assert obsolete not in combined
    assert not (ROOT / "logs").exists()
    assert not (ROOT / "log").exists()
    schemas = "\n".join(path.read_text() for path in source_root.rglob("schema.sql"))
    assert "telemetry" not in schemas.lower()


def test_development_api_disables_duplicate_uvicorn_access_logs() -> None:
    development = (ROOT / "deploy" / "core" / "compose.dev.yaml").read_text()

    assert "      - --no-access-log\n" in development


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
    assert "caddy:2.11.4-alpine" in web
    assert "pnpm@11.9.0" in web
    assert "--mount=type=cache,target=/root/.local/share/pnpm/store" in web
    assert "pnpm --dir web build" in web
    assert "COPY --from=build /app/web/dist /srv" in web
    assert "caddy validate --config /etc/caddy/Caddyfile" in web


def test_development_watch_assigns_service_appropriate_actions() -> None:
    development = (ROOT / "deploy" / "core" / "compose.dev.yaml").read_text()

    assert "thesistrace.entrypoints.http:app" in development
    assert "--reload-dir" in development
    assert "action: sync+restart" in development
    assert "action: sync" in development
    assert "action: rebuild" in development
    assert "target: /app/src" in development
    assert "path: ../../auth" in development
    assert "path: ./Dockerfile.auth" in development
    for service, next_service in (
        ("research-worker", "batch-research-worker"),
        ("batch-research-worker", "tracking-worker"),
        ("tracking-worker", "data-operator-worker"),
        ("data-operator-worker", "web"),
    ):
        assert f"  {service}:\n" in development
        section = development.split(f"  {service}:\n", maxsplit=1)[1].split(
            f"  {next_service}:\n", maxsplit=1
        )[0]
        assert "action: sync+restart" in section
        assert "target: /app/src" in section


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
    os.write(2, b"panic: close of closed channel\\n")
    os.write(2, b"watch panic trace\\n")
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
    assert package["scripts"]["test:integration"] == (
        "./scripts/test-runtime integration && pnpm --dir auth test:integration"
    )

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


def test_parallel_worktrees_share_one_caddy_port_lock_namespace(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first-worktree"
    second_root = tmp_path / "second-worktree"
    first_root.mkdir()
    second_root.mkdir()
    _, first_environment = _fake_test_runtime_commands(first_root)
    _, second_environment = _fake_test_runtime_commands(second_root)
    command_log = tmp_path / "commands.log"
    shared_lock_root = tmp_path / "host-port-locks"
    ready_dir = tmp_path / "pytest-ready"
    release_dir = tmp_path / "pytest-release"
    for environment, state_root in (
        (first_environment, first_root / "state"),
        (second_environment, second_root / "state"),
    ):
        environment["THESISTRACE_TEST_STATE_ROOT"] = str(state_root)
        environment["THESISTRACE_TEST_PORT_LOCK_ROOT"] = str(shared_lock_root)
        environment["FAKE_PYTEST_READY_DIR"] = str(ready_dir)
        environment["FAKE_PYTEST_RELEASE_DIR"] = str(release_dir)
        environment["TEST_COMMAND_LOG"] = str(command_log)

    processes = [
        subprocess.Popen(
            [ROOT / "scripts" / "test-runtime", "integration"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for environment in (first_environment, second_environment)
    ]
    try:
        worker_pids = _wait_for_fake_pytest_workers(
            ready_dir,
            count=2,
            command_log=command_log,
        )

        ports: list[str] = []
        for state_root in (first_root / "state", second_root / "state"):
            runs = list(state_root.iterdir())
            assert len(runs) == 1
            metadata = (runs[0] / "run.txt").read_text().splitlines()
            ports.append(
                next(
                    line.removeprefix("caddy_port=")
                    for line in metadata
                    if line.startswith("caddy_port=")
                )
            )
        assert len(set(ports)) == 2

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

    for process, (_, stderr) in zip(processes, results, strict=True):
        assert process.returncode == 0, stderr
    assert list(shared_lock_root.iterdir()) == []


def test_rustfs_restart_waits_for_the_authenticated_s3_api() -> None:
    runtime = (ROOT / "scripts" / "test-runtime").read_text()
    probe = (ROOT / "scripts" / "probe-rustfs-ready").read_text()

    assert "uv run python \"$rustfs_readiness_probe\"" in runtime
    assert "RustFS S3 API did not become ready after restart" in runtime
    assert runtime.index("curl -fsS http://127.0.0.1:9000/health") < runtime.index(
        "uv run python \"$rustfs_readiness_probe\""
    )
    assert "client.list_buckets()" in probe
    assert 'retries={"max_attempts": 0, "mode": "standard"}' in probe


def test_real_codex_mcp_runtime_is_explicit_isolated_and_evidence_backed(
    tmp_path: Path,
) -> None:
    package = json.loads((ROOT / "package.json").read_text())
    assert package["scripts"]["test:codex-mcp"] == "./scripts/test-runtime codex-mcp"
    command_log, environment = _fake_test_runtime_commands(tmp_path)

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "codex-mcp"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    commands = command_log.read_text()
    assert "up --detach --wait --wait-timeout 300 postgres rustfs" in commands
    assert "uv run thesistrace-initialize" in commands
    assert (
        "uv run pytest -q tests/acceptance/"
        "test_real_codex_research_agent_mcp.py -m real_codex" in commands
    )
    assert "--junitxml=" not in commands
    assert not (tmp_path / "runs" / run_id / "evidence" / "pytest.xml").exists()
    runtime = (ROOT / "scripts" / "test-runtime").read_text()
    assert (
        'THESISTRACE_REAL_CODEX_EVIDENCE_PATH="$evidence_dir/'
        'codex-stdio-acceptance.json"' in runtime
    )
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text()
    assert "test_kind=codex-mcp\n" in metadata
    assert "phase=codex-mcp-host-preflight " in metadata
    assert "phase=codex-mcp-infrastructure " in metadata
    assert "phase=codex-mcp-initialization " in metadata
    assert "phase=codex-mcp-acceptance " in metadata
    assert "phase=codex-mcp-evidence " in metadata
    assert "down --volumes --remove-orphans" in commands


def test_real_codex_mcp_runtime_fails_closed_without_host_or_evidence(
    tmp_path: Path,
) -> None:
    _, environment = _fake_test_runtime_commands(tmp_path)
    (tmp_path / "codex").unlink()
    environment["PATH"] = f"{tmp_path}:/usr/bin:/bin"

    missing_host = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "codex-mcp"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert missing_host.returncode != 0
    assert "requires the Codex CLI" in missing_host.stderr

    unsupported_root = tmp_path / "unsupported"
    unsupported_root.mkdir()
    _, unsupported_environment = _fake_test_runtime_commands(unsupported_root)
    unsupported_environment["FAKE_CODEX_STATUS"] = "2"
    unsupported_contract = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "codex-mcp"],
        cwd=ROOT,
        env=unsupported_environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert unsupported_contract.returncode != 0
    assert "supported noninteractive CLI contract" in unsupported_contract.stderr

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    _, evidence_environment = _fake_test_runtime_commands(evidence_root)
    evidence_environment["FAKE_SKIP_CODEX_EVIDENCE"] = "1"
    missing_evidence = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "codex-mcp"],
        cwd=ROOT,
        env=evidence_environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert missing_evidence.returncode != 0
    run_id = missing_evidence.stdout.splitlines()[0].removeprefix("Test run: ")
    metadata = (tmp_path / "evidence" / "runs" / run_id / "run.txt").read_text()
    assert any(
        line.startswith("phase=codex-mcp-evidence ") and not line.endswith("status=0")
        for line in metadata.splitlines()
    )

    invalid_root = tmp_path / "invalid-evidence"
    invalid_root.mkdir()
    _, invalid_environment = _fake_test_runtime_commands(invalid_root)
    invalid_environment["FAKE_INVALID_CODEX_EVIDENCE"] = "1"
    invalid_evidence = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "codex-mcp"],
        cwd=ROOT,
        env=invalid_environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert invalid_evidence.returncode != 0


def test_test_overlay_uses_random_loopback_ports_and_project_scoped_volumes() -> None:
    overlay = (ROOT / "deploy" / "core" / "compose.test-run.yaml").read_text()
    base = (ROOT / "deploy" / "core" / "compose.yaml").read_text()

    for port in (5432, 9000):
        assert f"127.0.0.1::{port}" in overlay
    assert (
        "127.0.0.1:${THESISTRACE_TEST_CADDY_PORT}:"
        "${THESISTRACE_TEST_CADDY_PORT}" in overlay
    )
    assert "127.0.0.1::8100" not in overlay
    assert "127.0.0.1::5173" not in overlay
    for development_port in (55432, 59010, 8101, 5274):
        assert str(development_port) not in overlay
    assert "checkpoint_timeout=30min" in overlay
    assert "max_wal_size=2GB" in overlay
    assert "fsync=off" not in overlay
    assert "synchronous_commit=off" not in overlay
    assert "postgres-data:" in base
    assert "rustfs-data:" in base
    assert "batch-attempt-control:" in base
    assert "benchmark-data:" in base
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
    port_lock_root = tmp_path / "port-locks"
    allocator = subprocess.run(
        [
            sys.executable,
            ROOT / "scripts" / "locked-loopback-port",
            "acquire",
            "--lock-root",
            port_lock_root,
            "--owner",
            project_name,
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    caddy_port = allocator.stdout.strip()
    (run_root / "run.txt").write_text(
        f"run_id={run_id}\nproject_name={project_name}\ncaddy_port={caddy_port}\n"
    )
    (run_root / "canonical-data").mkdir()
    (run_root / "canonical-data" / "HEAD.json").write_text("test data")
    (run_root / "benchmark-data").mkdir()
    (run_root / "benchmark-data" / "csi300-price-index-open.json").write_text(
        "test benchmark"
    )
    marker = tmp_path / "docker-invoked"
    docker = tmp_path / "docker"
    docker.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n")
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "THESISTRACE_TEST_PROJECT_NAME": project_name,
        "THESISTRACE_TEST_STATE_ROOT": str(tmp_path / "runs"),
        "THESISTRACE_TEST_PORT_LOCK_ROOT": str(port_lock_root),
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
    assert not (run_root / "benchmark-data").exists()
    assert list(port_lock_root.iterdir()) == []


def test_compose_preflight_failure_releases_the_caddy_port_lock(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_CONFIG_STATUS"] = "11"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "integration"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 11
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text()
    assert "cleanup_status=0\n" in metadata
    assert metadata.endswith("status=11\n")
    assert list((tmp_path / "port-locks").iterdir()) == []
    assert "down --volumes --remove-orphans" not in command_log.read_text()


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
    project_name = f"thesistrace-test-{run_id}"
    assert not (tmp_path / "runs" / run_id / "canonical-data").exists()
    assert not (tmp_path / "runs" / run_id / "benchmark-data").exists()
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
        "integration-auth-initialization",
        "integration-auth-initializer-exit",
        "integration-auth",
        "integration-initialization",
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
    assert "uv run thesistrace-initialize" in commands
    assert "uv run pytest -q tests/integration tests/acceptance" in commands
    assert (
        "db=postgresql://thesistrace_owner:owner-test-password@127.0.0.1:41001"
        in commands
    )
    assert "s3=http://127.0.0.1:41002" in commands
    assert "port auth 8200" in commands
    assert "down --volumes --remove-orphans" in commands
    assert f"docker volume rm {project_name}_canonical-data\n" in commands
    assert f"docker volume rm {project_name}_benchmark-data\n" in commands


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
    assert commands.count("build initialize auth-initialize web\n") == 1
    assert (
        f"docker image tag {project_name}-initialize {project_name}-api\n" in commands
    )
    for role in (
        "research-worker",
        "batch-research-worker",
        "tracking-worker",
        "data-operator-worker",
    ):
        assert (
            f"docker image tag {project_name}-initialize {project_name}-{role}\n"
            in commands
        )
    assert (
        "up --detach --no-build --wait --wait-timeout 300 postgres rustfs\n"
        in commands
    )
    assert "up --detach --no-build initialize auth-initialize\n" in commands
    assert "wait initialize auth-initialize\n" in commands
    assert (
        "up --detach --no-build --wait --wait-timeout 300 "
        "auth api research-worker batch-research-worker tracking-worker "
        "data-operator-worker web\n"
        in commands
    )
    assert "--build" not in commands
    assert "uv run thesistrace-initialize" not in commands
    run_id = project_name.removeprefix("thesistrace-test-")
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text()
    public_origin = next(
        line.removeprefix("public_origin=")
        for line in metadata.splitlines()
        if line.startswith("public_origin=")
    )
    assert f"pnpm --dir web test:e2e origin={public_origin}" in commands
    assert "thesistrace-api" not in commands
    assert "thesistrace-worker" not in commands
    assert "vite --host" not in commands
    for service in (
        "api",
        "research-worker",
        "batch-research-worker",
        "tracking-worker",
        "data-operator-worker",
        "initialize",
        "auth",
        "web",
    ):
        assert f"docker image rm {project_name}-{service}\n" in commands
    assert "down --volumes --remove-orphans" in commands


def test_e2e_secret_scope_fails_closed_when_container_inspection_fails(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_ENV_INSPECT_FAILURE_TARGET"] = "api"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "e2e"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0
    commands = command_log.read_text()
    assert "inspect --format {{range .Config.Env}}" in commands
    assert "pnpm --dir web test:e2e" not in commands
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text()
    assert any(
        line.startswith("phase=e2e-tushare-secret-scope ")
        and not line.endswith("status=0")
        for line in metadata.splitlines()
    )


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
    assert scripts["test:integration"] == (
        "./scripts/test-runtime integration && pnpm --dir auth test:integration"
    )
    assert scripts["check:performance"] == "./scripts/test-runtime performance"
    assert scripts["test:benchmark"] == "./scripts/test-runtime benchmark"
    assert scripts["test:e2e"] == "./scripts/test-runtime e2e"
    assert scripts["test:image-smoke"] == (
        "./scripts/test-runtime image-smoke && pnpm --dir auth test:image-smoke "
        "&& pnpm test:caddy-image-smoke"
    )
    assert scripts["test:caddy-image-smoke"] == "./scripts/test-caddy-production-image"
    assert scripts["test:cleanup"] == "./scripts/test-runtime cleanup"


def test_test_runtime_managed_phases_cannot_read_from_the_controlling_terminal() -> None:
    runtime = (ROOT / "scripts" / "test-runtime").read_text()
    managed_phase = runtime.split("run_managed() {", maxsplit=1)[1].split(
        "\n}\n\nrun_phase()", maxsplit=1
    )[0]

    assert '"$@" </dev/null' in managed_phase


def test_image_smoke_provisions_auth_inside_the_private_compose_network() -> None:
    runtime = (ROOT / "scripts" / "test-runtime").read_text()
    image_smoke = runtime.split("  image-smoke)\n", maxsplit=1)[1]
    provisioner = (
        ROOT / "tests" / "acceptance" / "provision_image_smoke_auth.py"
    ).read_text()
    overlay = (ROOT / "deploy" / "core" / "compose.image-smoke.yaml").read_text()

    assert "auth_port=$(mapped_port auth 8200)" not in image_smoke
    assert "resend_port=$(mapped_port resend-fake 8300)" not in image_smoke
    assert "create_private_compose_login_session" in provisioner
    assert "../../auth/test-fixtures:/test-fixtures:ro" in overlay


def test_benchmark_reprovisions_an_authenticated_researcher_after_each_reset(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "benchmark"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    commands = command_log.read_text()
    benchmark_samples = 2 * 5 * 2 + 2
    assert commands.count(
        "up --detach --no-build --wait --wait-timeout 120 auth api\n"
    ) == benchmark_samples
    provision_lines = [
        line
        for line in commands.splitlines()
        if "provision_image_smoke_auth.py" in line
    ]
    assert len(provision_lines) == benchmark_samples

    overlay = (ROOT / "deploy" / "core" / "compose.image-smoke.yaml").read_text()
    qualification = (ROOT / "scripts" / "long_research_qualification.py").read_text()
    research_worker = overlay.split("  research-worker:\n", maxsplit=1)[1].split(
        "  batch-research-worker:\n", maxsplit=1
    )[0]
    assert "THESISTRACE_TEST_AUTH_SESSION_FILE: /smoke-secrets/auth-session.json" in (
        research_worker
    )
    assert "${THESISTRACE_TEST_SECRET_DIR}:/smoke-secrets:ro" in research_worker
    assert "_ensure_researcher_bootstrap(api_origin)" in qualification
    assert 'headers = {"Cookie": _auth_session()["cookie"]}' in qualification
    assert 'headers["Origin"]' in qualification
    assert "is_research_execution_child_started_event(event, run_id)" in qualification
    assert 'event.get("resource_id") == run_id' not in qualification


def test_long_research_performance_stops_after_the_first_failed_sample(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_LONG_RESEARCH_SAMPLE_FAILURE"] = "factor_evaluation:warm:1"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "performance"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 7
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    commands = command_log.read_text()
    assert "--research-kind factor_evaluation --phase warm --index 1" in commands
    assert "--research-kind factor_evaluation --phase warm --index 2" not in commands
    assert "--research-kind strategy_backtest --phase warm" not in commands
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text()
    assert "phase=performance-factor_evaluation-warm-1 " in metadata
    assert "status=7" in metadata


def test_managed_compose_run_phases_never_read_from_the_parent_terminal() -> None:
    runtime = (ROOT / "scripts" / "test-runtime").read_text()
    normalized_runtime = re.sub(r"\\\s*\n\s*", " ", runtime)
    raw_compose_runs = re.findall(
        r"(?<![A-Za-z0-9_])(?:base_)?compose\s+run\b",
        normalized_runtime,
    )

    assert raw_compose_runs == ["compose run", "base_compose run"]
    for invocation in (
        'compose run --rm --no-deps -T --interactive=false "$@"',
        'base_compose run --rm --no-deps -T --interactive=false "$@"',
    ):
        assert invocation in normalized_runtime


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
    assert commands.count("build initialize auth-initialize web\n") == 1
    assert (
        f"docker image tag {project_name}-initialize {project_name}-api\n" in commands
    )
    for role in (
        "research-worker",
        "batch-research-worker",
        "tracking-worker",
        "data-operator-worker",
    ):
        assert (
            f"docker image tag {project_name}-initialize {project_name}-{role}\n"
            in commands
        )
    assert (
        "up --detach --no-build --wait --wait-timeout 300 postgres rustfs\n"
        in commands
    )
    assert "up --detach --no-build initialize auth-initialize\n" in commands
    assert "wait initialize auth-initialize\n" in commands
    assert (
        "up --detach --no-build --wait --wait-timeout 300 "
        "auth api web\n" in commands
    )
    assert (
        "up --detach --no-build --wait --wait-timeout 120 "
        "research-worker batch-research-worker tracking-worker "
        "data-operator-worker\n" in commands
    )
    assert "production_mcp_image_smoke.py preflight" in commands
    assert "production_mcp_image_smoke.py http-before" in commands
    assert "stop --timeout 30 api" in commands
    assert "production_mcp_image_smoke.py http-after" in commands
    assert "production_mcp_image_smoke.py stdio" in commands
    assert "production_mcp_image_smoke.py evidence" in commands
    assert "THESISTRACE_TEST_RANDOM_SEED=1401" in commands
    assert (
        "up --detach --no-build --wait --wait-timeout 120 "
        "api research-worker batch-research-worker tracking-worker "
        "data-operator-worker\n" in commands
    )
    provision_lines = [
        line
        for line in commands.splitlines()
        if "provision_image_smoke_auth.py" in line
    ]
    assert len(provision_lines) == 2
    session_paths = {
        Path(line.split(" db=", 1)[0].split()[-1]) for line in provision_lines
    }
    assert len(session_paths) == 1
    session_path = session_paths.pop()
    assert "evidence" not in session_path.parts
    assert not session_path.exists()
    assert commands.rindex(provision_lines[0]) < commands.index(
        "production_image_smoke.py reset\n"
    )
    secret_root = tmp_path / "runs" / ".runtime-secrets"
    assert secret_root.is_dir()
    assert list(secret_root.iterdir()) == []
    assert "THESISTRACE_DATA_MOUNT=/smoke-data/dataset-store-outage/current" in commands
    assert "production_image_smoke.py health" in commands
    assert "production_image_smoke.py readiness-outage" in commands
    assert "--build" not in commands


def test_image_smoke_mounts_explicit_local_mcp_api_without_changing_production_image() -> None:
    overlay = (ROOT / "deploy" / "core" / "compose.image-smoke.yaml").read_text()
    dockerfile = (ROOT / "deploy" / "core" / "Dockerfile.backend").read_text()
    api_harness = (ROOT / "tests" / "production_mcp_image_api.py").read_text()
    smoke = (ROOT / "tests" / "production_mcp_image_smoke.py").read_text()

    assert 'command: ["python", "/smoke/production_mcp_image_api.py"]' in overlay
    assert "../../tests:/smoke:ro" in overlay
    assert "THESISTRACE_RESEARCH_AGENT_TEST" not in dockerfile
    assert "LocalImageSmokeTokenVerifier" in api_harness
    assert "create_app(" in api_harness
    assert "enable_research_agent_http=True" in api_harness
    assert '"/mcp" not in default_routes' in smoke
    assert "create_app(enable_research_agent_http=True)" in smoke
    assert "terminate_on_close=False" in smoke


def test_production_image_base_tags_are_locked_to_content_digests() -> None:
    backend = (ROOT / "deploy" / "core" / "Dockerfile.backend").read_text()
    web = (ROOT / "deploy" / "core" / "Dockerfile.web").read_text()

    for dockerfile in (backend, web):
        from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
        assert from_lines
        assert all("@sha256:" in line for line in from_lines)
        assert all(len(line.partition("@sha256:")[2].split()[0]) == 64 for line in from_lines)


def test_failed_image_build_stops_smoke_before_runtime_phases(tmp_path: Path) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_BUILD_STATUS"] = "7"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "image-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 7
    commands = command_log.read_text()
    assert "build initialize auth-initialize web\n" in commands
    assert "entrypoint /bin/true batch-research-worker" not in commands
    assert "production_image_smoke.py" not in commands


@pytest.mark.parametrize(
    "target",
    (
        "api",
        "research-worker",
        "batch-research-worker",
        "tracking-worker",
        "data-operator-worker",
    ),
)
def test_failed_backend_image_tag_stops_smoke_before_runtime_phases(
    tmp_path: Path,
    target: str,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_IMAGE_TAG_FAILURE_TARGET"] = target

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "image-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 6
    commands = command_log.read_text()
    assert f"-{target}\n" in commands
    assert "entrypoint /bin/true batch-research-worker" not in commands
    assert "production_image_smoke.py" not in commands


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
    assert not (evidence / "auth-session.json").exists()
    secret_root = tmp_path / "runs" / ".runtime-secrets"
    assert secret_root.is_dir()
    assert list(secret_root.iterdir()) == []
    commands = command_log.read_text()
    assert commands.index("production_image_smoke.py before") < commands.rindex(
        "ps --all"
    )
    assert commands.rindex("ps --all") < commands.index("down --volumes")


def test_failed_image_build_stops_before_infrastructure_and_preserves_status(
    tmp_path: Path,
) -> None:
    command_log, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_BUILD_STATUS"] = "12"

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "image-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 12
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    metadata = (tmp_path / "runs" / run_id / "run.txt").read_text()
    assert "phase=image-smoke-images " in metadata
    assert "status=12" in metadata
    commands = command_log.read_text()
    assert "build initialize auth-initialize web" in commands
    assert "image tag" not in commands
    assert "up --detach" not in commands


def test_failed_mcp_image_smoke_sanitizes_preserved_protocol_evidence(
    tmp_path: Path,
) -> None:
    _, environment = _fake_test_runtime_commands(tmp_path)
    environment.update(
        {
            "FAKE_MCP_IMAGE_SMOKE_PHASE": "http-before",
            "FAKE_MCP_IMAGE_SMOKE_STATUS": "17",
            "FAKE_COMPOSE_LOGS": " ".join(
                (
                    "mcp-image-action-token-canary",
                    "mcp-image-read-token-canary",
                    "mcp-image-hypothesis-canary",
                    "018f6f7e-8342-7c9a-a4df-9a86147d2e02",
                    "rank(close) + 0.123456789",
                )
            ),
        }
    )

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "image-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 17
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    run_root = tmp_path / "runs" / run_id
    metadata = (run_root / "run.txt").read_text()
    assert "failure_evidence_sanitization_status=0" in metadata
    assert "failure_canary_scan_status=0" in metadata
    compose_logs = (run_root / "evidence" / "compose-logs.txt").read_text()
    assert compose_logs.count("<redacted>") == 5
    assert "rank(close)" not in compose_logs
    for canary in (
        "mcp-image-action-token-canary",
        "mcp-image-read-token-canary",
        "mcp-image-hypothesis-canary",
        "018f6f7e-8342-7c9a-a4df-9a86147d2e02",
        "0.123456789",
    ):
        assert canary not in compose_logs


def test_failed_evidence_sanitization_discards_all_text_evidence(
    tmp_path: Path,
) -> None:
    _, environment = _fake_test_runtime_commands(tmp_path)
    environment.update(
        {
            "FAKE_MCP_IMAGE_SMOKE_PHASE": "http-before",
            "FAKE_MCP_IMAGE_SMOKE_STATUS": "17",
            "FAKE_SANITIZER_STATUS": "19",
            "FAKE_COMPOSE_LOGS": "rank(close) + 0.123456789",
        }
    )

    completed = subprocess.run(
        [ROOT / "scripts" / "test-runtime", "image-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 17
    run_id = completed.stdout.splitlines()[0].removeprefix("Test run: ")
    run_root = tmp_path / "runs" / run_id
    metadata = (run_root / "run.txt").read_text()
    assert "failure_evidence_sanitization_status=1" in metadata
    assert "failure_evidence_discard_status=0" in metadata
    assert "failure_canary_scan_status=0" in metadata
    assert not (run_root / "evidence" / "compose-logs.txt").exists()


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
    assert commands.index("pnpm --dir web test:e2e") < commands.index("ps --all")
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


def test_failed_runtime_sanitizes_then_scans_new_failure_evidence(
    tmp_path: Path,
) -> None:
    _, environment = _fake_test_runtime_commands(tmp_path)
    environment["FAKE_PYTEST_STATUS"] = "7"
    environment["FAKE_COMPOSE_LOGS"] = "observability-secret-canary"

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
    run_root = tmp_path / "runs" / run_id
    evidence = run_root / "evidence"
    assert (evidence / "secret-canary-scan.txt").read_text() == "passed\n"
    assert (evidence / "compose-logs.txt").read_text().strip() == "<redacted>"
    metadata = (run_root / "run.txt").read_text()
    assert "failure_evidence_sanitization_status=0\n" in metadata
    assert "failure_canary_scan_status=0\n" in metadata


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
    assert len(
        {
            (record["postgres_port"], record["s3_port"], record["auth_port"])
            for record in records
        }
    ) == 2

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
    architecture = (ROOT / "docs" / "architecture" / "core.md").read_text()
    guide = (ROOT / "docs" / "runbook" / "local-lifecycle.md").read_text()
    production = (
        ROOT / "docs" / "runbook" / "single-node-production.md"
    ).read_text()
    tushare = (ROOT / "docs" / "runbook" / "tushare-live-bootstrap.md").read_text()
    active_docs = "\n".join((readme, architecture, guide, production, tushare))

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
    assert "./scripts/production-runtime validate" in production
    assert "./scripts/production-runtime up" in production
    assert "root with mode `0600`" in production
    assert "not Production readiness" in active_docs
    for command in (
        "mise exec -- pnpm test",
        "mise exec -- pnpm test:integration",
        "mise exec -- pnpm test:e2e",
        "mise exec -- pnpm test:image-smoke",
        "mise exec -- pnpm check",
        "mise exec -- pnpm check:release",
        "mise exec -- pnpm check:performance",
    ):
        assert f"`{command}`" in architecture
    assert "`bun run " not in architecture
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

    assert adr.startswith(
        "# Use one full Compose topology for local Development and Test\n\n"
    )
    assert "same complete Compose product topology" in adr
    assert "isolated identities, ports, credentials" in adr
    assert "hybrid alternate runtime" in adr
    assert "status: accepted" not in adr
    for engineering_term in (
        "Compose Watch",
        "Development environment",
        "Test environment",
        "pnpm bootstrap",
        "test:integration",
        "test:e2e",
    ):
        assert engineering_term not in glossary


def test_current_architecture_documents_only_the_active_data_and_schema_contracts() -> None:
    architecture = (ROOT / "docs" / "architecture" / "core.md").read_text()

    for current in (
        "two one-shot schema initializers",
        "thesistrace_meta.schema_contract",
        "private `thesistrace-data-operator`",
        "one browser-local Draft per Research Folder",
        "direct Run admission",
        "`Create draft` is the sole reuse action",
        "Attempt starts",
        "pins the Data Generation frozen at Run",
        "There is no upgrade, downgrade, fallback",
    ):
        assert current in architecture

    for obsolete in (
        "one-shot Migration",
        "migration-runner",
        "data.next_release",
        "Data Update product action",
        "## Research Definitions",
        "/definitions/:definitionId",
        "Run saves the submitted revision",
        "Rerun always creates a new ResearchRun ID using exactly",
    ):
        assert obsolete not in architecture

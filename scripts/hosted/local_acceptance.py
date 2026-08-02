#!/usr/bin/env python3
import argparse
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote, urlencode

from thesistrace.objects import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "scripts" / "hosted-stack"
LOCAL_SMOKE = ROOT / "scripts" / "hosted-local-smoke.py"
LOCAL_POSTGRES = ROOT / "scripts" / "hosted" / "local_postgres_acceptance.py"
LOCAL_SCHEMA_VERSION = "hosted-v2-local-v1"
MINIMUM_LOCAL_LOGICAL_CPU = 2
MINIMUM_LOCAL_MEMORY_BYTES = int(3.5 * 1024**3)
PRODUCTION_ONLY_NOT_CLAIMED = (
    "capacity_qualification",
    "cloudflare",
    "off_node_recovery",
    "production_rto_rpo",
    "real_smtp_delivery",
    "whole_node_resilience",
)


class LocalAcceptanceError(RuntimeError):
    pass


class Phase(NamedTuple):
    name: str
    command: tuple[str, ...]
    timeout_seconds: int


Executor = Callable[
    [Phase, dict[str, str]],
    tuple[dict[str, object], dict[str, object]],
]
RuntimeReader = Callable[[], dict[str, object]]
SnapshotReader = Callable[[str], dict[str, dict[str, object]]]


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str) -> None:
        super().__init__("localhost", timeout=10)
        self.socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(self.socket_path)
        self.sock = connection


class DockerEngineClient:
    def __init__(self, socket_path: str = "/var/run/docker.sock") -> None:
        self.socket_path = socket_path

    def request_bytes(
        self,
        path: str,
        *,
        accepted: tuple[int, ...] = (200,),
        method: str = "GET",
        body: dict[str, object] | None = None,
    ) -> tuple[int, bytes]:
        connection = UnixSocketHTTPConnection(self.socket_path)
        try:
            serialized = None if body is None else json.dumps(body).encode("utf-8")
            headers = {"Content-Type": "application/json"} if body is not None else {}
            connection.request(method, path, body=serialized, headers=headers)
            response = connection.getresponse()
            payload = response.read()
        finally:
            connection.close()
        if response.status not in accepted:
            raise LocalAcceptanceError(
                f"Docker Engine API {path} returned {response.status}"
            )
        return response.status, payload

    def request_json(
        self,
        path: str,
        *,
        accepted: tuple[int, ...] = (200,),
        method: str = "GET",
        body: dict[str, object] | None = None,
    ) -> object:
        _status, payload = self.request_bytes(
            path,
            accepted=accepted,
            method=method,
            body=body,
        )
        return json.loads(payload)

    def project_containers(self, project: str) -> list[dict[str, object]]:
        filters = json.dumps(
            {"label": [f"com.docker.compose.project={project}"]},
            separators=(",", ":"),
        )
        value = self.request_json(
            "/containers/json?"
            + urlencode({"all": "true", "filters": filters})
        )
        if not isinstance(value, list):
            raise LocalAcceptanceError("Docker Engine returned invalid container inventory")
        return [item for item in value if isinstance(item, dict)]

    def container_json(self, container_id: str, endpoint: str) -> dict[str, object]:
        value = self.request_json(
            f"/containers/{quote(container_id, safe='')}/{endpoint}"
        )
        if not isinstance(value, dict):
            raise LocalAcceptanceError("Docker Engine returned invalid container evidence")
        return value

    def container_swap_peak(self, container_id: str) -> int | None:
        created = self.request_json(
            f"/containers/{quote(container_id, safe='')}/exec",
            accepted=(201,),
            method="POST",
            body={
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": True,
                "Cmd": ["cat", "/sys/fs/cgroup/memory.swap.peak"],
            },
        )
        if not isinstance(created, dict) or not isinstance(created.get("Id"), str):
            return None
        try:
            _status, payload = self.request_bytes(
                f"/exec/{quote(created['Id'], safe='')}/start",
                method="POST",
                body={"Detach": False, "Tty": True},
            )
            return int(payload.strip())
        except (LocalAcceptanceError, ValueError):
            return None


def _cpu_percent(stats: dict[str, object]) -> float:
    cpu = stats.get("cpu_stats")
    previous = stats.get("precpu_stats")
    if not isinstance(cpu, dict) or not isinstance(previous, dict):
        return 0.0
    current_usage = cpu.get("cpu_usage")
    previous_usage = previous.get("cpu_usage")
    if not isinstance(current_usage, dict) or not isinstance(previous_usage, dict):
        return 0.0
    cpu_delta = int(current_usage.get("total_usage", 0)) - int(
        previous_usage.get("total_usage", 0)
    )
    system_delta = int(cpu.get("system_cpu_usage", 0)) - int(
        previous.get("system_cpu_usage", 0)
    )
    online = int(cpu.get("online_cpus", 0))
    if online <= 0:
        per_cpu = current_usage.get("percpu_usage")
        online = len(per_cpu) if isinstance(per_cpu, list) and per_cpu else 1
    if cpu_delta <= 0 or system_delta <= 0:
        return 0.0
    return round((cpu_delta / system_delta) * online * 100.0, 3)


def docker_project_snapshot(
    project: str,
    *,
    client: DockerEngineClient | None = None,
) -> dict[str, dict[str, object]]:
    engine = client or DockerEngineClient()
    snapshot: dict[str, dict[str, object]] = {}
    for summary in engine.project_containers(project):
        container_id = str(summary.get("Id", ""))
        names = summary.get("Names")
        if not container_id or not isinstance(names, list) or not names:
            continue
        name = str(names[0]).removeprefix("/")
        try:
            inspect = engine.container_json(container_id, "json")
            state = inspect.get("State")
            if not isinstance(state, dict):
                state = {}
            memory_bytes = 0
            cpu_percent = 0.0
            if bool(state.get("Running")):
                stats = engine.container_json(
                    container_id,
                    "stats?stream=false&one-shot=true",
                )
                memory = stats.get("memory_stats")
                if isinstance(memory, dict):
                    memory_bytes = int(memory.get("usage", 0))
                    memory_detail = memory.get("stats")
                    if isinstance(memory_detail, dict):
                        memory_bytes -= int(memory_detail.get("inactive_file", 0))
                    memory_bytes = max(0, memory_bytes)
                cpu_percent = _cpu_percent(stats)
            health = state.get("Health")
            host_config = inspect.get("HostConfig")
            if not isinstance(host_config, dict):
                host_config = {}
            memory_limit = int(host_config.get("Memory", 0))
            memory_swap_limit = int(host_config.get("MemorySwap", 0))
            if memory_limit > 0 and memory_swap_limit == memory_limit:
                swap_peak = 0
            elif bool(state.get("Running")):
                swap_peak = engine.container_swap_peak(container_id)
            else:
                swap_peak = None
        except LocalAcceptanceError as error:
            if " returned 404" in str(error):
                continue
            raise
        snapshot[name] = {
            "memory_bytes": memory_bytes,
            "cpu_percent": cpu_percent,
            "swap_peak_bytes": swap_peak,
            "restart_count": int(inspect.get("RestartCount", 0)),
            "oom_killed": bool(state.get("OOMKilled")),
            "health": health.get("Status") if isinstance(health, dict) else None,
        }
    return snapshot


class DockerPhaseSampler:
    def __init__(
        self,
        project: str,
        *,
        snapshot_reader: SnapshotReader = docker_project_snapshot,
    ) -> None:
        self.project = project
        self.snapshot_reader = snapshot_reader
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.sample_count = 0
        self.peak_memory_bytes = 0
        self.peak_cpu_percent = 0.0
        self.peak_swap_bytes = 0
        self.container_peaks: dict[str, dict[str, int | float]] = {}
        self.initial_restart_counts: dict[str, int] = {}
        self.maximum_restart_counts: dict[str, int] = {}
        self.oom_killed_containers: set[str] = set()
        self.unhealthy_containers: set[str] = set()
        self.swap_unavailable_containers: set[str] = set()
        self.sampling_errors: list[str] = []
        self.lock = threading.Lock()

    def observe_snapshot(self, snapshot: dict[str, dict[str, object]]) -> None:
        with self.lock:
            self.sample_count += 1
            total_memory = 0
            total_cpu = 0.0
            total_swap = 0
            for name, value in snapshot.items():
                memory = int(value.get("memory_bytes", 0))
                cpu = float(value.get("cpu_percent", 0.0))
                swap_value = value.get("swap_peak_bytes")
                restart_count = int(value.get("restart_count", 0))
                total_memory += memory
                total_cpu += cpu
                if isinstance(swap_value, int):
                    total_swap += swap_value
                else:
                    self.swap_unavailable_containers.add(name)
                peaks = self.container_peaks.setdefault(
                    name,
                    {"memory_bytes": 0, "cpu_percent": 0.0, "swap_bytes": 0},
                )
                peaks["memory_bytes"] = max(int(peaks["memory_bytes"]), memory)
                peaks["cpu_percent"] = max(float(peaks["cpu_percent"]), cpu)
                if isinstance(swap_value, int):
                    peaks["swap_bytes"] = max(int(peaks["swap_bytes"]), swap_value)
                self.initial_restart_counts.setdefault(name, restart_count)
                self.maximum_restart_counts[name] = max(
                    self.maximum_restart_counts.get(name, restart_count),
                    restart_count,
                )
                if value.get("oom_killed") is True:
                    self.oom_killed_containers.add(name)
                if value.get("health") == "unhealthy":
                    self.unhealthy_containers.add(name)
            self.peak_memory_bytes = max(self.peak_memory_bytes, total_memory)
            self.peak_cpu_percent = max(self.peak_cpu_percent, total_cpu)
            self.peak_swap_bytes = max(self.peak_swap_bytes, total_swap)

    def _sample(self) -> None:
        try:
            self.observe_snapshot(self.snapshot_reader(self.project))
        except Exception as error:  # evidence must retain sampler failures
            with self.lock:
                self.sampling_errors.append(f"{type(error).__name__}: {error}")

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self._sample()
            self.stop_event.wait(2.0)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> dict[str, object]:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=15)
        self._sample()
        return self.summary()

    def summary(self) -> dict[str, object]:
        unexpected_restarts = sorted(
            name
            for name, maximum in self.maximum_restart_counts.items()
            if maximum > self.initial_restart_counts.get(name, maximum)
        )
        return {
            "sample_count": self.sample_count,
            "peak_memory_bytes": self.peak_memory_bytes,
            "peak_cpu_percent": round(self.peak_cpu_percent, 3),
            "peak_swap_bytes": self.peak_swap_bytes,
            "container_peaks": dict(sorted(self.container_peaks.items())),
            "unexpected_restart_containers": unexpected_restarts,
            "oom_killed_containers": sorted(self.oom_killed_containers),
            "unhealthy_containers": sorted(self.unhealthy_containers),
            "swap_unavailable_containers": sorted(self.swap_unavailable_containers),
            "sampling_errors": list(self.sampling_errors),
        }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run non-attested Hosted Local Acceptance on constrained Docker",
    )
    result.add_argument("--output", type=Path, required=True)
    result.add_argument(
        "--state-dir",
        type=Path,
        default=ROOT / ".hosted" / "local-acceptance",
    )
    result.add_argument("--project", default="thesistrace-hosted-local")
    result.add_argument("--http-port", type=int, default=28080)
    result.add_argument("--https-port", type=int, default=28443)
    result.add_argument("--postgres-port", type=int, default=25432)
    result.add_argument("--grafana-port", type=int, default=23001)
    return result


def local_phases() -> tuple[Phase, ...]:
    return (
        Phase("reset", (str(STACK), "local-reset"), 300),
        Phase("core_stack", (str(STACK), "local-up"), 1800),
        Phase("public_origin", (sys.executable, str(LOCAL_SMOKE)), 2700),
        Phase("postgresql_rls", (sys.executable, str(LOCAL_POSTGRES)), 1200),
        Phase(
            "temporal_and_failure_contracts",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "tests/hosted/test_compute_dispatch.py",
                "tests/hosted/test_temporal_worker_heartbeat.py",
                "tests/hosted/test_research_workflow.py",
                "tests/hosted/test_dataset_publication_workflow.py",
                "tests/hosted/test_tracking_workflow.py",
                "tests/hosted/test_tracking_operations_workflow.py",
            ),
            1200,
        ),
        Phase(
            "security_and_storage",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "tests/hosted/test_edge_policy.py",
                "tests/hosted/test_edge_rate_limits.py",
                "tests/hosted/test_container_boundaries.py",
                "tests/hosted/test_storage_admission.py",
                "tests/hosted/test_object_store_boundary.py",
                "tests/hosted/test_health_views.py",
                "tests/hosted/test_compose_stack.py::"
                "test_otel_sampling_and_export_failure_are_bounded_and_visible",
            ),
            1200,
        ),
        Phase("operational_health", (str(STACK), "local-ops-check"), 600),
        Phase("local_recovery", (str(STACK), "local-recovery-smoke"), 1200),
        Phase("pause_core", (str(STACK), "local-pause"), 300),
        Phase("frontend", ("make", "hosted-local-frontend"), 1200),
        Phase("cleanup", (str(STACK), "local-down"), 300),
    )


def local_environment(arguments: argparse.Namespace) -> dict[str, str]:
    state_dir = arguments.state_dir.resolve()
    return {
        **os.environ,
        "THESISTRACE_ACCEPTANCE_MODE": "1",
        "THESISTRACE_LOCAL_ACCEPTANCE": "1",
        "THESISTRACE_HOST_STATE_DIR": str(state_dir),
        "INSFORGE_SOURCE_DIR": str(ROOT / ".hosted" / "insforge-v2.2.9"),
        "THESISTRACE_COMPOSE_PROJECT_NAME": arguments.project,
        "THESISTRACE_HTTP_PORT": str(arguments.http_port),
        "THESISTRACE_HTTPS_PORT": str(arguments.https_port),
        "THESISTRACE_LOCAL_POSTGRES_PORT": str(arguments.postgres_port),
        "GRAFANA_HOST_PORT": str(arguments.grafana_port),
        "THESISTRACE_HOSTED_ORIGIN": f"https://localhost:{arguments.https_port}",
        "THESISTRACE_SMOKE_INSECURE_TLS": "1",
    }


def docker_runtime_capacity() -> dict[str, object]:
    value = json.loads(
        subprocess.check_output(
            ["docker", "info", "--format", "{{json .}}"],
            text=True,
        )
    )
    return {
        "source": "docker-info",
        "logical_cpu": int(value["NCPU"]),
        "memory_bytes": int(value["MemTotal"]),
    }


def validate_local_runtime(runtime: dict[str, object]) -> None:
    try:
        logical_cpu = int(runtime["logical_cpu"])
        memory_bytes = int(runtime["memory_bytes"])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise LocalAcceptanceError("Docker runtime capacity is invalid") from error
    if runtime.get("source") != "docker-info":
        raise LocalAcceptanceError("Docker runtime capacity must come from docker info")
    if logical_cpu < MINIMUM_LOCAL_LOGICAL_CPU:
        raise LocalAcceptanceError(
            "Hosted Local Acceptance requires at least 2 logical CPU"
        )
    if memory_bytes < MINIMUM_LOCAL_MEMORY_BYTES:
        raise LocalAcceptanceError(
            "Hosted Local Acceptance requires at least 3.5 GiB memory"
        )


def execute_phase(
    phase: Phase,
    environment: dict[str, str],
) -> tuple[dict[str, object], dict[str, object]]:
    print(f"[{phase.name}] {' '.join(phase.command)}", flush=True)
    started = time.monotonic()
    sampler = DockerPhaseSampler(environment["THESISTRACE_COMPOSE_PROJECT_NAME"])
    sampler.start()
    try:
        completed = subprocess.run(
            phase.command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            timeout=phase.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise LocalAcceptanceError(
            f"{phase.name} exceeded {phase.timeout_seconds} seconds"
        ) from error
    finally:
        resources = sampler.stop()
    elapsed = round(time.monotonic() - started, 3)
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        tail = output[-8000:].decode("utf-8", errors="replace")
        raise LocalAcceptanceError(
            f"{phase.name} failed with exit {completed.returncode}:\n{tail}"
        )
    payload: dict[str, object] = {"status": "passed"}
    decoded = output.decode("utf-8", errors="replace")
    for line in reversed(decoded.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    record = {
        "status": "passed",
        "elapsed_seconds": elapsed,
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "resources": resources,
    }
    print(f"[{phase.name}] passed in {elapsed}s", flush=True)
    return payload, record


def write_evidence(path: Path, evidence: dict[str, object]) -> None:
    output = path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(evidence))


def summarize_runtime_observations(
    records: dict[str, object],
) -> dict[str, object]:
    phase_peaks: dict[str, object] = {}
    swap_used = False
    oom_kill = False
    unexpected_restart = False
    unhealthy = False
    sampling_errors: list[str] = []
    swap_unavailable: set[str] = set()
    for phase_name, value in records.items():
        if not isinstance(value, dict):
            continue
        resources = value.get("resources")
        if not isinstance(resources, dict):
            continue
        phase_peaks[phase_name] = resources
        swap_used = swap_used or int(resources.get("peak_swap_bytes", 0)) > 0
        oom_kill = oom_kill or bool(resources.get("oom_killed_containers"))
        unexpected_restart = unexpected_restart or bool(
            resources.get("unexpected_restart_containers")
        )
        unhealthy = unhealthy or bool(resources.get("unhealthy_containers"))
        for error in resources.get("sampling_errors", []):
            sampling_errors.append(f"{phase_name}: {error}")
        swap_unavailable.update(resources.get("swap_unavailable_containers", []))
    operational = records.get("operational_health")
    heartbeat_verified = (
        isinstance(operational, dict)
        and operational.get("status") == "passed"
        and isinstance(operational.get("evidence"), dict)
        and operational["evidence"].get("status") == "passed"
    )
    return {
        "sampler": "docker-engine-api-v1",
        "phase_peaks_recorded": bool(phase_peaks),
        "phase_peaks": phase_peaks,
        "swap_used": swap_used,
        "oom_kill": oom_kill,
        "unexpected_restart": unexpected_restart,
        "unhealthy_container": unhealthy,
        "missing_required_heartbeat": False if heartbeat_verified else None,
        "swap_measurement_incomplete_for": sorted(swap_unavailable),
        "sampling_errors": sampling_errors,
    }


def runtime_observation_failures(observations: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if observations.get("swap_used") is True:
        failures.append("Docker containers used swap")
    if observations.get("oom_kill") is True:
        failures.append("Docker reported an OOM kill")
    if observations.get("unexpected_restart") is True:
        failures.append("Docker reported an unexpected container restart")
    if observations.get("unhealthy_container") is True:
        failures.append("Docker reported an unhealthy container")
    if observations.get("missing_required_heartbeat") is not False:
        failures.append("required runtime heartbeat was not verified")
    if observations.get("swap_measurement_incomplete_for"):
        failures.append("container swap-peak measurement was incomplete")
    if observations.get("sampling_errors"):
        failures.append("Docker resource sampling was incomplete")
    return failures


def run_acceptance(
    arguments: argparse.Namespace,
    *,
    executor: Executor = execute_phase,
    runtime_reader: RuntimeReader = docker_runtime_capacity,
) -> dict[str, object]:
    runtime: dict[str, object] = {}
    records: dict[str, object] = {}
    release_bundle_id: str | None = None
    failure: dict[str, str] | None = None
    pending_error: LocalAcceptanceError | None = None
    current_phase = "preflight"
    environment = local_environment(arguments)
    phases = local_phases()
    cleanup = phases[-1]
    started_stack = False

    try:
        runtime = runtime_reader()
        validate_local_runtime(runtime)
        for phase in phases[:-1]:
            current_phase = phase.name
            payload, record = executor(phase, environment)
            records[phase.name] = {**record, "evidence": payload}
            if phase.name == "reset":
                started_stack = True
            if phase.name == "core_stack":
                candidate = payload.get("release_bundle_id")
                if isinstance(candidate, str) and candidate:
                    release_bundle_id = candidate
    except LocalAcceptanceError as error:
        pending_error = error
        failure = {"phase": current_phase, "message": str(error)}
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        pending_error = LocalAcceptanceError(str(error))
        failure = {"phase": current_phase, "message": str(error)}
    finally:
        if started_stack:
            try:
                payload, record = executor(cleanup, environment)
                records[cleanup.name] = {**record, "evidence": payload}
            except LocalAcceptanceError as cleanup_error:
                records[cleanup.name] = {
                    "status": "failed",
                    "message": str(cleanup_error),
                }
                if pending_error is None:
                    pending_error = cleanup_error
                    failure = {
                        "phase": cleanup.name,
                        "message": str(cleanup_error),
                    }

    runtime_observations = summarize_runtime_observations(records)
    if pending_error is None and runtime_observations["phase_peaks_recorded"]:
        observation_failures = runtime_observation_failures(runtime_observations)
        if observation_failures:
            pending_error = LocalAcceptanceError("; ".join(observation_failures))
            failure = {
                "phase": "runtime_observations",
                "message": str(pending_error),
            }

    evidence: dict[str, object] = {
        "schema_version": LOCAL_SCHEMA_VERSION,
        "status": "failed" if failure else "passed",
        "launch_qualified": False,
        "release_bundle_id": release_bundle_id,
        "runtime_capacity": runtime,
        "runtime_observations": runtime_observations,
        "records": records,
        "production_only_not_claimed": list(PRODUCTION_ONLY_NOT_CLAIMED),
    }
    if failure:
        evidence["failure"] = failure
    write_evidence(arguments.output, evidence)
    if pending_error is not None:
        raise pending_error
    return evidence


def main() -> None:
    arguments = parser().parse_args()
    evidence = run_acceptance(arguments)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except LocalAcceptanceError as error:
        raise SystemExit(str(error)) from error

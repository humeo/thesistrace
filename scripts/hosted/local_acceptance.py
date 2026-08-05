#!/usr/bin/env python3
import argparse
import hashlib
import http.client
import json
import os
import re
import shlex
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote, urlencode

import psycopg

from thesistrace.hosted.backup_operations import load_restore_snapshot
from thesistrace.objects import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "scripts" / "hosted-stack"
LOCAL_SMOKE = ROOT / "scripts" / "hosted-local-smoke.py"
LOCAL_BOUNDARIES = ROOT / "scripts" / "hosted" / "local_boundary_acceptance.py"
LOCAL_WORKFLOWS = ROOT / "scripts" / "hosted" / "local_workflow_acceptance.py"
LOCAL_SCHEMA_VERSION = "hosted-v2-local-v1"
MINIMUM_LOCAL_LOGICAL_CPU = 2
MINIMUM_LOCAL_MEMORY_BYTES = int(3.5 * 1024**3)
RESOURCE_SAMPLE_INTERVAL_SECONDS = 30.0
PRODUCTION_ONLY_NOT_CLAIMED = (
    "capacity_qualification",
    "cloudflare",
    "co_resident_maximum_load",
    "external_dns_tls",
    "off_node_recovery",
    "production_invitation_admission",
    "production_rto_rpo",
    "real_smtp_delivery",
    "whole_node_resilience",
)
CANONICAL_GATE_NAMES = (
    "reset",
    "core_session",
    "identity_product",
    "postgres_edge_storage",
    "api_relay_recovery",
    "compute_recovery",
    "publication_recovery",
    "controlled_workflows",
    "operational_health",
    "local_recovery",
    "browser_ready",
    "frontend_browser",
)


class LocalAcceptanceError(RuntimeError):
    pass


class PhaseExecutionError(LocalAcceptanceError):
    def __init__(self, message: str, record: dict[str, object]) -> None:
        super().__init__(message)
        self.record = record


class Phase(NamedTuple):
    name: str
    command: tuple[str, ...]
    timeout_seconds: int
    prerequisites: tuple[str, ...] = ()


Executor = Callable[
    [Phase, dict[str, str]],
    tuple[dict[str, object], dict[str, object]],
]
RuntimeReader = Callable[[], dict[str, object]]
SnapshotReader = Callable[[str], dict[str, dict[str, object]]]
FingerprintReader = Callable[[], dict[str, object]]
StateReader = Callable[[dict[str, str]], dict[str, object]]


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
            "running": bool(state.get("Running")),
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
                elif value.get("running") is True:
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
            self.stop_event.wait(RESOURCE_SAMPLE_INTERVAL_SECONDS)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> dict[str, object]:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=120)
        if self.thread is None or not self.thread.is_alive():
            self._sample()
        else:
            with self.lock:
                self.sampling_errors.append("resource sampler did not stop in 120 seconds")
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
    result.add_argument("--project")
    result.add_argument("--http-port", type=int, default=28080)
    result.add_argument("--https-port", type=int, default=28443)
    result.add_argument("--postgres-port", type=int, default=25432)
    result.add_argument("--grafana-port", type=int, default=23001)
    selector = result.add_mutually_exclusive_group()
    selector.add_argument("--phase", choices=CANONICAL_GATE_NAMES)
    selector.add_argument(
        "--from",
        dest="from_phase",
        choices=CANONICAL_GATE_NAMES,
    )
    selector.add_argument("--resume", action="store_true")
    result.add_argument(
        "--until",
        dest="until_phase",
        choices=CANONICAL_GATE_NAMES,
    )
    result.add_argument(
        "--cleanup-policy",
        choices=("always", "on-success", "never"),
        default="never",
    )
    result.add_argument("--cleanup", action="store_true")
    result.add_argument("--fresh", action="store_true")
    return result


def local_phases() -> tuple[Phase, ...]:
    return (
        Phase("reset", (str(STACK), "local-reset"), 300),
        Phase("core_session", (str(STACK), "local-up"), 1800, ("reset",)),
        Phase(
            "identity_product",
            (sys.executable, str(LOCAL_SMOKE), "--gate", "identity-product"),
            1200,
            ("core_session",),
        ),
        Phase(
            "postgres_edge_storage",
            (sys.executable, str(LOCAL_BOUNDARIES)),
            1200,
            ("core_session",),
        ),
        Phase(
            "api_relay_recovery",
            (sys.executable, str(LOCAL_SMOKE), "--gate", "api-relay-recovery"),
            600,
            ("identity_product",),
        ),
        Phase(
            "compute_recovery",
            (sys.executable, str(LOCAL_SMOKE), "--gate", "compute-recovery"),
            900,
            ("identity_product",),
        ),
        Phase(
            "publication_recovery",
            (sys.executable, str(LOCAL_SMOKE), "--gate", "publication-recovery"),
            900,
            ("identity_product",),
        ),
        Phase(
            "controlled_workflows",
            (sys.executable, str(LOCAL_WORKFLOWS)),
            1200,
        ),
        Phase(
            "operational_health",
            (str(STACK), "local-ops-check"),
            600,
            ("identity_product",),
        ),
        Phase(
            "local_recovery",
            (str(STACK), "local-recovery-smoke"),
            1200,
            ("identity_product",),
        ),
        Phase(
            "browser_ready",
            (str(STACK), "local-browser-ready"),
            300,
            ("identity_product",),
        ),
        Phase(
            "frontend_browser",
            ("make", "hosted-local-frontend"),
            1200,
            ("identity_product", "browser_ready"),
        ),
        Phase("cleanup", (str(STACK), "local-down"), 300),
    )


def session_manifest_path(arguments: argparse.Namespace) -> Path:
    return arguments.state_dir.resolve() / "local-acceptance-session.json"


def _state_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def reject_authentication_material(value: object, *, path: str = "evidence") -> None:
    sensitive_names = {
        "authorization",
        "password",
        "secret",
        "access_token",
        "accesstoken",
        "refresh_token",
        "refreshtoken",
        "session_token",
        "sessiontoken",
        "reset_token",
        "resettoken",
        "bearer",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if normalized in sensitive_names or normalized.endswith("_password"):
                raise LocalAcceptanceError(
                    f"authentication material is forbidden in persisted {path}"
                )
            reject_authentication_material(item, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            reject_authentication_material(item, path=f"{path}[{index}]")


def _write_private_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(value))
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def read_session_manifest(arguments: argparse.Namespace) -> dict[str, object] | None:
    path = session_manifest_path(arguments)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise LocalAcceptanceError("local acceptance session manifest is invalid") from error
    if not isinstance(value, dict) or value.get("schema_version") != "hosted-local-session-v1":
        raise LocalAcceptanceError("local acceptance session manifest is incompatible")
    return value


def invalidate_from(
    manifest: dict[str, object],
    gate_name: str,
    *,
    reason: str,
    preserve_runtime_state: bool = False,
) -> None:
    gate_records = manifest.get("gates")
    if not isinstance(gate_records, dict):
        return
    try:
        start = CANONICAL_GATE_NAMES.index(gate_name)
    except ValueError:
        start = 0
    for name in CANONICAL_GATE_NAMES[start:]:
        record = gate_records.get(name)
        if isinstance(record, dict):
            gate_records[name] = {
                **record,
                "status": "invalidated",
                "invalidation_reason": reason,
            }
    if not preserve_runtime_state:
        prior_digests = [
            gate_records[name].get("output_state_digest")
            for name in CANONICAL_GATE_NAMES[:start]
            if isinstance(gate_records.get(name), dict)
            and gate_records[name].get("status") == "passed"
        ]
        manifest["current_state_digest"] = prior_digests[-1] if prior_digests else None


def new_session_manifest(
    arguments: argparse.Namespace,
    *,
    fingerprint: dict[str, object],
    runtime: dict[str, object],
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": "hosted-local-session-v1",
        "run_id": str(uuid.uuid4()),
        "state_epoch": str(uuid.uuid4()),
        "project": arguments.project,
        "fingerprint": fingerprint,
        "runtime_capacity": runtime,
        "gates": {},
        "gate_history": [],
        "cleaned": False,
    }
    _write_private_json(session_manifest_path(arguments), manifest)
    return manifest


def append_gate_record(
    manifest: dict[str, object],
    gate_name: str,
    record: dict[str, object],
) -> None:
    gates = manifest.get("gates")
    history = manifest.get("gate_history")
    if not isinstance(gates, dict) or not isinstance(history, list):
        raise LocalAcceptanceError("local acceptance gate history is invalid")
    gates[gate_name] = record
    history.append({"gate": gate_name, **record})


def public_web_asset_manifest(
    origin: str,
    *,
    insecure_tls: bool = False,
) -> dict[str, str] | None:
    context = (
        ssl._create_unverified_context()
        if origin.startswith("https://") and insecure_tls
        else None
    )
    try:
        with urllib.request.urlopen(
            origin.rstrip("/") + "/",
            timeout=3,
            context=context,
        ) as response:
            index = response.read()
        paths = sorted(
            set(
                re.findall(
                    rb'''(?:src|href)=["'](/assets/[^"']+)["']''',
                    index,
                )
            )
        )
        if not paths:
            return None
        result = {"/": hashlib.sha256(index).hexdigest()}
        for raw_path in paths:
            path = raw_path.decode("utf-8")
            with urllib.request.urlopen(
                origin.rstrip("/") + path,
                timeout=3,
                context=context,
            ) as response:
                result[path] = hashlib.sha256(response.read()).hexdigest()
        return result
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def source_fingerprint(
    root: Path = ROOT,
    *,
    include_roots: tuple[str, ...] | None = None,
) -> dict[str, object]:
    resolved = root.resolve()
    excluded_roots = (
        ".git",
        ".hosted",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "web/dist",
    )
    listed = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=resolved,
    )
    paths: list[Path] = []
    for raw_path in listed.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(os.fsdecode(raw_path))
        portable = relative.as_posix()
        if include_roots is not None and not any(
            portable == included or portable.startswith(included.rstrip("/") + "/")
            for included in include_roots
        ):
            continue
        if any(
            portable == excluded
            or portable.startswith(excluded + "/")
            or f"/{excluded}/" in f"/{portable}/"
            for excluded in excluded_roots
        ):
            continue
        paths.append(relative)
    digest = hashlib.sha256()
    for relative in sorted(paths, key=lambda value: value.as_posix()):
        path = resolved / relative
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0" + os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"file\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"missing\0")
    return {
        "files_sha256": digest.hexdigest(),
        "file_count": len(paths),
        "include_roots": list(include_roots) if include_roots is not None else None,
        "excluded_roots": list(excluded_roots),
    }


def default_fingerprint() -> dict[str, object]:
    release_core_roots = (
        "deploy/hosted",
        "src/thesistrace",
        "pyproject.toml",
        "uv.lock",
        "web/src",
        "web/package.json",
        "web/bun.lock",
    )
    harness_roots = (
        "Makefile",
        "scripts/hosted-local-smoke.py",
        "scripts/hosted-release-smoke.py",
        "scripts/hosted/local_acceptance.py",
        "scripts/hosted/local_boundary_acceptance.py",
        "scripts/hosted/local_frontend_acceptance.py",
        "scripts/hosted/local_ops_probe.py",
        "scripts/hosted/local_recovery_acceptance.py",
        "scripts/hosted/local_workflow_acceptance.py",
        "scripts/hosted/seed_acceptance_state.py",
        "tests/hosted",
    )
    return {
        "release_core": source_fingerprint(ROOT, include_roots=release_core_roots),
        "harness": source_fingerprint(ROOT, include_roots=harness_roots),
    }


def compatibility_fingerprint(
    arguments: argparse.Namespace,
    *,
    source: dict[str, object],
    runtime: dict[str, object],
) -> dict[str, object]:
    release_core_source = source.get("release_core", source)
    harness_source = source.get("harness", source)
    return {
        "release_core": {
            "source": release_core_source,
            "runtime": runtime,
            "configuration": {
                "project": arguments.project,
                "http_port": arguments.http_port,
                "https_port": arguments.https_port,
                "postgres_port": arguments.postgres_port,
                "grafana_port": arguments.grafana_port,
            },
        },
        "harness": {
            "source": harness_source,
            "canonical_gates": list(CANONICAL_GATE_NAMES),
        },
    }


def reconcile_fingerprint(
    manifest: dict[str, object],
    fingerprint: dict[str, object],
) -> str | None:
    previous = manifest.get("fingerprint")
    if previous == fingerprint:
        return None
    if not isinstance(previous, dict) or "release_core" not in previous:
        gates = manifest.get("gates")
        core = gates.get("core_session") if isinstance(gates, dict) else None
        if not isinstance(core, dict) or core.get("status") != "passed":
            return "release_core"
        manifest["fingerprint"] = fingerprint
        invalidate_from(
            manifest,
            "identity_product",
            reason="acceptance harness model changed",
            preserve_runtime_state=True,
        )
        return "harness"
    if previous.get("release_core") != fingerprint.get("release_core"):
        return "release_core"
    if previous.get("harness") != fingerprint.get("harness"):
        manifest["fingerprint"] = fingerprint
        invalidate_from(
            manifest,
            "identity_product",
            reason="acceptance harness inputs changed",
            preserve_runtime_state=True,
        )
        return "harness"
    return None


def default_state(environment: dict[str, str]) -> dict[str, object]:
    state_dir = Path(environment["THESISTRACE_HOST_STATE_DIR"])
    release_root = state_dir / "releases"
    release_pointer = release_root / "current.json"
    release_evidence: dict[str, object] | None = None
    if release_pointer.exists():
        try:
            pointer = json.loads(release_pointer.read_text())
        except json.JSONDecodeError as error:
            raise LocalAcceptanceError("local Release pointer is invalid") from error
        bundle_id = pointer.get("bundle_id") if isinstance(pointer, dict) else None
        if not isinstance(bundle_id, str) or not bundle_id:
            raise LocalAcceptanceError("local Release pointer has no Bundle identity")
        bundle_root = release_root / "bundles" / bundle_id
        release_evidence = {
            "bundle_id": bundle_id,
            "pointer_sha256": hashlib.sha256(release_pointer.read_bytes()).hexdigest(),
            "bundle_sha256": hashlib.sha256(
                (bundle_root / "bundle.json").read_bytes()
            ).hexdigest(),
            "image_lock_sha256": hashlib.sha256(
                (bundle_root / "image-lock.json").read_bytes()
            ).hexdigest(),
            "web_asset_manifest": public_web_asset_manifest(
                environment["THESISTRACE_HOSTED_ORIGIN"],
                insecure_tls=environment.get("THESISTRACE_SMOKE_INSECURE_TLS") == "1",
            ),
        }

    client = DockerEngineClient()
    topology: list[dict[str, object]] = []
    for container in client.project_containers(
        environment["THESISTRACE_COMPOSE_PROJECT_NAME"]
    ):
        labels = container.get("Labels")
        mounts = container.get("Mounts")
        topology.append(
            {
                "service": labels.get("com.docker.compose.service")
                if isinstance(labels, dict)
                else None,
                "image_id": container.get("ImageID"),
                "mounts": sorted(
                    (
                        {
                            "type": mount.get("Type"),
                            "name": mount.get("Name"),
                            "destination": mount.get("Destination"),
                        }
                        for mount in mounts
                        if isinstance(mount, dict)
                    ),
                    key=lambda value: (
                        str(value["destination"]),
                        str(value["name"]),
                    ),
                )
                if isinstance(mounts, list)
                else [],
            }
        )

    password_path = state_dir / "secrets" / "postgres_password"
    authoritative_state: dict[str, object] | None = None
    if password_path.exists():
        password = password_path.read_text().strip()
        if password:
            connection_info = psycopg.conninfo.make_conninfo(
                host="127.0.0.1",
                port=int(environment["THESISTRACE_LOCAL_POSTGRES_PORT"]),
                user=os.environ.get("POSTGRES_USER", "postgres"),
                password=password,
                dbname=os.environ.get("POSTGRES_DB", "insforge"),
                connect_timeout=3,
            )
            try:
                authoritative_state = load_restore_snapshot(connection_info)
            except psycopg.Error:
                authoritative_state = None
    product_context = state_dir / "public-origin-context.json"
    return {
        "project": environment["THESISTRACE_COMPOSE_PROJECT_NAME"],
        "release": release_evidence,
        "topology": sorted(topology, key=lambda value: str(value["service"])),
        "authoritative_state": authoritative_state,
        "product_context_sha256": (
            hashlib.sha256(product_context.read_bytes()).hexdigest()
            if product_context.exists()
            else None
        ),
    }


def validate_core_runtime_state(
    state: dict[str, object],
    release_bundle_id: str,
) -> dict[str, object]:
    release = state.get("release")
    if not isinstance(release, dict) or release.get("bundle_id") != release_bundle_id:
        raise LocalAcceptanceError("core_session has no matching staged Release Bundle")
    if not isinstance(state.get("authoritative_state"), dict):
        raise LocalAcceptanceError("core_session authoritative PostgreSQL state is unavailable")
    if not isinstance(release.get("web_asset_manifest"), dict):
        raise LocalAcceptanceError("core_session staged Web asset manifest is unavailable")
    topology = state.get("topology")
    if not isinstance(topology, list):
        raise LocalAcceptanceError("core_session topology evidence is unavailable")
    services = {
        value.get("service")
        for value in topology
        if isinstance(value, dict) and isinstance(value.get("service"), str)
    }
    required = {
        "api",
        "postgres",
    }
    missing = sorted(required - services)
    if missing:
        raise LocalAcceptanceError(
            "core_session is missing required services: " + ", ".join(missing)
        )
    for forbidden in (
        "otel-collector",
        "prometheus",
        "grafana",
    ):
        if forbidden in services:
            raise LocalAcceptanceError(
                f"core_session unexpectedly started {forbidden}"
            )
    return {"bundle_id": release_bundle_id}


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


def select_phases(arguments: argparse.Namespace) -> tuple[Phase, ...]:
    if arguments.cleanup:
        if arguments.phase or arguments.from_phase or arguments.until_phase:
            raise LocalAcceptanceError("--cleanup cannot be combined with gate selectors")
        return ()
    if arguments.resume:
        if arguments.until_phase is not None:
            raise LocalAcceptanceError("--resume cannot be combined with --until")
        return ()
    phases = tuple(phase for phase in local_phases() if phase.name != "cleanup")
    by_name = {phase.name: index for index, phase in enumerate(phases)}
    exact = arguments.phase
    start_name = arguments.from_phase
    end_name = arguments.until_phase
    if exact is not None:
        if end_name is not None:
            raise LocalAcceptanceError("--phase cannot be combined with --until")
        return (phases[by_name[exact]],)
    start = 0 if start_name is None else by_name[start_name]
    end = len(phases) - 1 if end_name is None else by_name[end_name]
    if start > end:
        raise LocalAcceptanceError("selected gates are reversed in canonical order")
    return phases[start : end + 1]


def resolve_local_project(arguments: argparse.Namespace) -> str:
    selected = select_phases(arguments)
    manifest = read_session_manifest(arguments)
    project = arguments.project
    if project is None:
        if selected and selected[0].name == "reset":
            project = f"thesistrace-hosted-local-{uuid.uuid4().hex[:12]}"
        elif isinstance(manifest, dict) and isinstance(manifest.get("project"), str):
            project = manifest["project"]
        else:
            project = "thesistrace-hosted-local-missing"
    if re.fullmatch(r"thesistrace-hosted-local-[a-z0-9][a-z0-9-]{0,47}", project) is None:
        raise LocalAcceptanceError(
            "local acceptance project name must use the thesistrace-hosted-local-* namespace"
        )
    arguments.project = project
    return project


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
    started_at = datetime.now(UTC).isoformat()
    sampler = DockerPhaseSampler(environment["THESISTRACE_COMPOSE_PROJECT_NAME"])
    sampler.start()
    completed: subprocess.CompletedProcess[bytes] | None = None
    timeout_error: subprocess.TimeoutExpired | None = None
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
        timeout_error = error
    finally:
        resources = sampler.stop()
    elapsed = round(time.monotonic() - started, 3)
    if timeout_error is not None:
        raw_output = (timeout_error.stdout or b"") + (timeout_error.stderr or b"")
        returncode: int | None = None
        status = "timed_out"
    else:
        assert completed is not None
        raw_output = completed.stdout + completed.stderr
        returncode = completed.returncode
        status = "passed" if completed.returncode == 0 else "failed"
    decoded_output = raw_output.decode("utf-8", errors="replace")
    for pattern in (
        r"(?i)(authorization:\s*bearer\s+)\S+",
        r'''(?i)(["']?(?:access|refresh|session|reset)[_-]?token["']?\s*[:=]\s*["']?)[^"',\s}]+''',
        r'''(?i)(["']?(?:password|secret)["']?\s*[:=]\s*["']?)[^"',\s}]+''',
    ):
        decoded_output = re.sub(pattern, r"\1[REDACTED]", decoded_output)
    output = decoded_output.encode("utf-8")
    log_path = (
        Path(environment["THESISTRACE_HOST_STATE_DIR"]).resolve()
        / "logs"
        / f"{phase.name}.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path.write_bytes(output)
    log_path.chmod(0o600)
    record: dict[str, object] = {
        "status": status,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": elapsed,
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "log_path": str(log_path),
        "resources": resources,
    }
    if returncode is not None:
        record["returncode"] = returncode
    if timeout_error is not None:
        raise PhaseExecutionError(
            f"{phase.name} exceeded {phase.timeout_seconds} seconds",
            record,
        ) from timeout_error
    assert completed is not None
    if completed.returncode != 0:
        tail = output[-8000:].decode("utf-8", errors="replace")
        raise PhaseExecutionError(
            f"{phase.name} failed with exit {completed.returncode}:\n{tail}",
            record,
        )
    payload: dict[str, object] = {"status": "passed"}
    for line in reversed(decoded_output.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
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


def runtime_observation_failures(
    observations: dict[str, object],
    *,
    require_heartbeat: bool = True,
) -> list[str]:
    failures: list[str] = []
    if observations.get("swap_used") is True:
        failures.append("Docker containers used swap")
    if observations.get("oom_kill") is True:
        failures.append("Docker reported an OOM kill")
    if observations.get("unexpected_restart") is True:
        failures.append("Docker reported an unexpected container restart")
    if observations.get("unhealthy_container") is True:
        failures.append("Docker reported an unhealthy container")
    if require_heartbeat and observations.get("missing_required_heartbeat") is not False:
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
    fingerprint_reader: FingerprintReader = default_fingerprint,
    state_reader: StateReader = default_state,
) -> dict[str, object]:
    runtime: dict[str, object] = {}
    records: dict[str, object] = {}
    release_bundle_id: str | None = None
    failure: dict[str, str] | None = None
    pending_error: LocalAcceptanceError | None = None
    current_phase = "preflight"
    current_input_state_digest: str | None = None
    phase_execution_started = False
    resolve_local_project(arguments)
    environment = local_environment(arguments)
    selected_phases: tuple[Phase, ...] = ()
    cleanup = local_phases()[-1]
    manifest: dict[str, object] | None = None
    fingerprint: dict[str, object] = {}

    try:
        runtime = runtime_reader()
        validate_local_runtime(runtime)
        fingerprint = compatibility_fingerprint(
            arguments,
            source=fingerprint_reader(),
            runtime=runtime,
        )
        selected_phases = select_phases(arguments)
        manifest = read_session_manifest(arguments)
        if arguments.fresh and (arguments.cleanup or arguments.resume):
            raise LocalAcceptanceError("--fresh cannot be combined with cleanup or resume")
        if arguments.resume:
            if manifest is None:
                raise LocalAcceptanceError("no local acceptance session is available to resume")
            if manifest.get("cleaned") is True:
                raise LocalAcceptanceError("cleaned local acceptance state cannot be resumed")
            fingerprint_change = reconcile_fingerprint(manifest, fingerprint)
            if fingerprint_change == "release_core":
                invalidate_from(
                    manifest,
                    "reset",
                    reason="Release/Core inputs changed",
                )
                _write_private_json(session_manifest_path(arguments), manifest)
                raise LocalAcceptanceError(
                    "local Release/Core inputs changed; run an explicit reset"
                )
            if fingerprint_change == "harness":
                _write_private_json(session_manifest_path(arguments), manifest)
            gate_records = manifest.get("gates")
            if not isinstance(gate_records, dict):
                raise LocalAcceptanceError("local acceptance gate records are invalid")
            pending = next(
                (
                    phase
                    for phase in local_phases()
                    if phase.name != "cleanup"
                    and (
                        not isinstance(gate_records.get(phase.name), dict)
                        or gate_records[phase.name].get("status") != "passed"
                    )
                ),
                None,
            )
            if pending is None:
                raise LocalAcceptanceError("all canonical local acceptance gates passed")
            selected_phases = (pending,)
        if arguments.cleanup:
            if manifest is None:
                raise LocalAcceptanceError("no local acceptance session is available to clean")
            payload, record = executor(cleanup, environment)
            records[cleanup.name] = {**record, "evidence": payload}
            invalidate_from(manifest, "reset", reason="session cleanup completed")
            manifest["cleaned"] = True
            manifest["current_state_digest"] = None
            _write_private_json(session_manifest_path(arguments), manifest)
            selected_phases = ()
        elif selected_phases:
            if arguments.fresh and selected_phases[0].name != "reset":
                raise LocalAcceptanceError("--fresh requires a selection beginning with reset")
            if selected_phases[0].name == "reset":
                manifest = new_session_manifest(
                    arguments,
                    fingerprint=fingerprint,
                    runtime=runtime,
                )
            elif manifest is None:
                raise LocalAcceptanceError(
                    "selected gate requires reset in the same local acceptance session"
                )
            if manifest is None:
                raise LocalAcceptanceError("local acceptance session could not be created")
            if manifest.get("project") != arguments.project:
                raise LocalAcceptanceError("local acceptance project does not match the session")
            fingerprint_change = reconcile_fingerprint(manifest, fingerprint)
            if fingerprint_change == "release_core":
                invalidate_from(
                    manifest,
                    selected_phases[0].name,
                    reason="Release/Core inputs changed",
                )
                _write_private_json(session_manifest_path(arguments), manifest)
                raise LocalAcceptanceError(
                    "local Release/Core inputs changed; run an explicit reset"
                )
            if fingerprint_change == "harness":
                _write_private_json(session_manifest_path(arguments), manifest)
            gate_records = manifest.get("gates")
            if not isinstance(gate_records, dict):
                raise LocalAcceptanceError("local acceptance gate records are invalid")

        for phase in selected_phases:
            current_phase = phase.name
            phase_execution_started = False
            assert manifest is not None
            gate_records = manifest["gates"]
            assert isinstance(gate_records, dict)
            missing = [
                prerequisite
                for prerequisite in phase.prerequisites
                if not isinstance(gate_records.get(prerequisite), dict)
                or gate_records[prerequisite].get("status") != "passed"
            ]
            if missing:
                raise LocalAcceptanceError(
                    f"{phase.name} requires passed prerequisite(s): {', '.join(missing)}"
                )
            input_state = state_reader(environment)
            input_state_digest = _state_digest(input_state)
            current_input_state_digest = input_state_digest
            expected_state_digest = manifest.get("current_state_digest")
            if (
                phase.name != "reset"
                and isinstance(expected_state_digest, str)
                and expected_state_digest != input_state_digest
            ):
                invalidate_from(
                    manifest,
                    phase.name,
                    reason="runtime state differs from checkpoint",
                )
                _write_private_json(session_manifest_path(arguments), manifest)
                raise LocalAcceptanceError(
                    f"{phase.name} input state differs from the session checkpoint"
                )
            phase_execution_started = True
            payload, record = executor(phase, environment)
            reject_authentication_material(payload)
            reject_authentication_material(record, path="gate record")
            output_state = state_reader(environment)
            output_state_digest = _state_digest(output_state)
            gate_record = {
                **record,
                "evidence": payload,
                "input_state_digest": input_state_digest,
                "output_state_digest": output_state_digest,
            }
            core_runtime: dict[str, object] | None = None
            if phase.name == "core_session":
                candidate = payload.get("release_bundle_id")
                release_state = output_state.get("release")
                if not isinstance(candidate, str) or not candidate:
                    raise PhaseExecutionError(
                        "core_session returned no staged Release Bundle identity",
                        {**gate_record, "status": "failed"},
                    )
                if (
                    isinstance(release_state, dict)
                    and release_state.get("bundle_id") != candidate
                ):
                    raise PhaseExecutionError(
                        "core_session Release Bundle differs from runtime state",
                        {**gate_record, "status": "failed"},
                    )
                if {
                    "release",
                    "topology",
                    "authoritative_state",
                }.issubset(output_state):
                    try:
                        core_runtime = validate_core_runtime_state(
                            output_state,
                            candidate,
                        )
                    except LocalAcceptanceError as error:
                        raise PhaseExecutionError(
                            str(error),
                            {**gate_record, "status": "failed"},
                        ) from error
            records[phase.name] = gate_record
            append_gate_record(manifest, phase.name, gate_record)
            manifest["current_state_digest"] = output_state_digest
            manifest["cleaned"] = False
            _write_private_json(session_manifest_path(arguments), manifest)
            _write_private_json(
                arguments.state_dir.resolve() / "evidence" / f"{phase.name}.json",
                {"run_id": manifest["run_id"], "gate": phase.name, **gate_record},
            )
            if phase.name == "core_session":
                release_bundle_id = candidate
                manifest["release_bundle_id"] = candidate
                manifest["release_state"] = output_state.get("release")
                if core_runtime is not None:
                    manifest["core_runtime"] = core_runtime
                _write_private_json(session_manifest_path(arguments), manifest)
            phase_execution_started = False
    except LocalAcceptanceError as error:
        if (
            phase_execution_started
            and current_phase in CANONICAL_GATE_NAMES
            and isinstance(manifest, dict)
        ):
            failure_record: dict[str, object] = (
                {
                    **error.record,
                    "message": str(error),
                }
                if isinstance(error, PhaseExecutionError)
                else {"status": "failed", "message": str(error)}
            )
            if current_input_state_digest is not None:
                failure_record["input_state_digest"] = current_input_state_digest
            try:
                failure_state_digest = _state_digest(state_reader(environment))
            except Exception as state_error:
                failure_record["failure_state_error"] = type(state_error).__name__
            else:
                failure_record["output_state_digest"] = failure_state_digest
                manifest["current_state_digest"] = failure_state_digest
            records[current_phase] = failure_record
            append_gate_record(manifest, current_phase, failure_record)
            _write_private_json(session_manifest_path(arguments), manifest)
        pending_error = error
        failure = {"phase": current_phase, "message": str(error)}
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        pending_error = LocalAcceptanceError(str(error))
        failure = {"phase": current_phase, "message": str(error)}
    except KeyboardInterrupt:
        pending_error = LocalAcceptanceError(
            f"{current_phase} interrupted by operator signal"
        )
        failure = {"phase": current_phase, "message": str(pending_error)}
    finally:
        should_cleanup = (
            manifest is not None
            and not arguments.cleanup
            and (
                arguments.cleanup_policy == "always"
                or (arguments.cleanup_policy == "on-success" and pending_error is None)
            )
        )
        if should_cleanup:
            try:
                payload, record = executor(cleanup, environment)
                records[cleanup.name] = {**record, "evidence": payload}
                invalidate_from(manifest, "reset", reason="session cleanup completed")
                manifest["cleaned"] = True
                manifest["current_state_digest"] = None
                _write_private_json(session_manifest_path(arguments), manifest)
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
    if (
        pending_error is None
        and not arguments.cleanup
        and runtime_observations["phase_peaks_recorded"]
    ):
        observation_failures = runtime_observation_failures(
            runtime_observations,
            require_heartbeat="operational_health" in records,
        )
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
        "release_bundle_id": release_bundle_id
        or (manifest.get("release_bundle_id") if isinstance(manifest, dict) else None),
        "run_id": manifest.get("run_id") if isinstance(manifest, dict) else None,
        "state_epoch": manifest.get("state_epoch") if isinstance(manifest, dict) else None,
        "selected_gates": [phase.name for phase in selected_phases],
        "clean_run": arguments.fresh
        and [phase.name for phase in selected_phases] == list(CANONICAL_GATE_NAMES),
        "checkpoint_reused": arguments.resume
        or bool(selected_phases and selected_phases[0].name != "reset"),
        "runtime_capacity": runtime,
        "runtime_observations": runtime_observations,
        "records": records,
        "production_only_not_claimed": list(PRODUCTION_ONLY_NOT_CLAIMED),
    }
    if failure:
        evidence["failure"] = failure
        retry = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--output",
            str(arguments.output),
            "--state-dir",
            str(arguments.state_dir),
            "--project",
            arguments.project,
            "--phase",
            current_phase,
            "--cleanup-policy",
            "never",
        ]
        cleanup_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--output",
            str(arguments.output),
            "--state-dir",
            str(arguments.state_dir),
            "--project",
            arguments.project,
            "--cleanup",
        ]
        evidence["diagnostics"] = {
            "preserved": arguments.cleanup_policy != "always",
            "retry_command": shlex.join(retry),
            "cleanup_command": shlex.join(cleanup_command),
        }
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

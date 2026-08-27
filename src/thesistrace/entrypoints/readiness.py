from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic

POSTGRESQL_READY = "POSTGRESQL_READY"
POSTGRESQL_UNAVAILABLE = "POSTGRESQL_UNAVAILABLE"
RUSTFS_READY = "RUSTFS_READY"
RUSTFS_UNAVAILABLE = "RUSTFS_UNAVAILABLE"
DATASET_STORE_READY = "DATASET_STORE_READY"
DATASET_STORE_UNAVAILABLE = "DATASET_STORE_UNAVAILABLE"
READINESS_DEADLINE_SECONDS = 2.0
_MAX_COMPLETION_RESERVE_SECONDS = 0.1
_MIN_PROBE_BUDGET_FRACTION = 0.75

_DEPENDENCIES = {
    "postgresql": (POSTGRESQL_READY, POSTGRESQL_UNAVAILABLE),
    "rustfs": (RUSTFS_READY, RUSTFS_UNAVAILABLE),
    "dataset_store": (DATASET_STORE_READY, DATASET_STORE_UNAVAILABLE),
}


@dataclass(frozen=True)
class CoreReadiness:
    database_url: str = field(repr=False)
    s3_endpoint_url: str = field(repr=False)
    s3_access_key_id: str = field(repr=False)
    s3_secret_access_key: str = field(repr=False)
    s3_bucket: str = field(repr=False)
    s3_region: str
    data_mount: Path
    deadline_seconds: float = READINESS_DEADLINE_SECONDS
    probe_command: tuple[str, ...] = (
        sys.executable,
        "-m",
        "thesistrace.entrypoints.readiness_child",
    )
    _probe_lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)
    _lingering_probes: dict[str, subprocess.Popen[bytes]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.deadline_seconds <= 0:
            raise ValueError("Core readiness deadline must be positive")
        if not self.probe_command:
            raise ValueError("Core readiness probe command must be non-empty")

    def snapshot(self) -> dict[str, object]:
        if not self._probe_lock.acquire(blocking=False):
            return _unavailable_snapshot()

        completed = Event()
        result: list[dict[str, object]] = []
        probe_budget_seconds = max(
            self.deadline_seconds * _MIN_PROBE_BUDGET_FRACTION,
            self.deadline_seconds - _MAX_COMPLETION_RESERVE_SECONDS,
        )

        def probe() -> None:
            try:
                result.append(self._snapshot(probe_budget_seconds))
            except Exception:
                result.append(_unavailable_snapshot())
            finally:
                self._probe_lock.release()
                completed.set()

        try:
            Thread(
                target=probe,
                name="thesistrace-readiness",
                daemon=True,
            ).start()
        except Exception:
            self._probe_lock.release()
            return _unavailable_snapshot()
        if not completed.wait(timeout=self.deadline_seconds):
            return _unavailable_snapshot()
        return result[0] if result else _unavailable_snapshot()

    def _snapshot(self, deadline_seconds: float) -> dict[str, object]:
        deadline = monotonic() + deadline_seconds
        environment = {
            **os.environ,
            "THESISTRACE_DATABASE_URL": self.database_url,
            "THESISTRACE_S3_ENDPOINT_URL": self.s3_endpoint_url,
            "THESISTRACE_S3_ACCESS_KEY_ID": self.s3_access_key_id,
            "THESISTRACE_S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
            "THESISTRACE_S3_BUCKET": self.s3_bucket,
            "THESISTRACE_S3_REGION": self.s3_region,
            "THESISTRACE_DATA_MOUNT": os.fspath(self.data_mount),
        }
        probes: dict[str, subprocess.Popen[bytes] | None] = {}
        for name in _DEPENDENCIES:
            lingering = self._lingering_probes.get(name)
            if lingering is not None:
                try:
                    still_running = lingering.poll() is None
                except Exception:
                    still_running = True
                if still_running:
                    probes[name] = None
                    continue
                self._lingering_probes.pop(name, None)
            if monotonic() >= deadline:
                probes[name] = None
                continue
            try:
                probes[name] = subprocess.Popen(
                    [*self.probe_command, name],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                    env=environment,
                )
            except Exception:
                probes[name] = None

        dependencies: dict[str, dict[str, str]] = {}
        try:
            for name, codes in _DEPENDENCIES.items():
                process = probes[name]
                ready = False
                if process is not None:
                    try:
                        ready = process.wait(timeout=max(0, deadline - monotonic())) == 0
                    except subprocess.TimeoutExpired:
                        ready = False
                dependencies[name] = {
                    "status": "ready" if ready else "unavailable",
                    "code": codes[0] if ready else codes[1],
                }
        finally:
            for name, process in probes.items():
                if process is None:
                    continue
                try:
                    if process.poll() is None:
                        process.kill()
                    if process.poll() is None:
                        self._lingering_probes[name] = process
                    else:
                        self._lingering_probes.pop(name, None)
                except Exception:
                    self._lingering_probes[name] = process

        ready = all(value["status"] == "ready" for value in dependencies.values())
        return {
            "status": "ready" if ready else "unavailable",
            "dependencies": dependencies,
        }


def _unavailable_snapshot() -> dict[str, object]:
    return {
        "status": "unavailable",
        "dependencies": {
            name: {"status": "unavailable", "code": codes[1]}
            for name, codes in _DEPENDENCIES.items()
        },
    }


__all__ = (
    "CoreReadiness",
    "DATASET_STORE_READY",
    "DATASET_STORE_UNAVAILABLE",
    "POSTGRESQL_READY",
    "POSTGRESQL_UNAVAILABLE",
    "READINESS_DEADLINE_SECONDS",
    "RUSTFS_READY",
    "RUSTFS_UNAVAILABLE",
)

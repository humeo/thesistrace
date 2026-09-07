from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

MAX_PROTOCOL_LINE_BYTES = 16 * 1024 * 1024
CANCEL_COOPERATIVE_GRACE_SECONDS = 1.0
CANCEL_CHILD_EXIT_BUDGET_SECONDS = 3.0
_THREAD_ENVIRONMENT_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


class ChildTransportError(RuntimeError):
    pass


class ChildTransportCancelled(ChildTransportError):
    pass


class ChildTransportCgroupOom(ChildTransportError):
    pass


@dataclass(frozen=True)
class SupervisedChildTransport:
    process: subprocess.Popen[str]
    oom_kill_count_before: int | None

    @classmethod
    def spawn(cls, module: str) -> SupervisedChildTransport:
        return cls(
            process=subprocess.Popen(
                [sys.executable, "-m", module],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=child_environment(),
            ),
            oom_kill_count_before=cgroup_oom_kill_count(),
        )

    def write(self, value: Mapping[str, object]) -> None:
        if self.process.stdin is None or self.process.stdin.closed:
            raise ChildTransportError("Supervised child input pipe is unavailable")
        self.process.stdin.write(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()

    def read(
        self,
        *,
        cancel_requested: Callable[[], bool] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_termination: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        stream = self.process.stdout
        if stream is None:
            raise ChildTransportError("Supervised child output pipe is unavailable")
        selector = selectors.DefaultSelector()
        selector.register(stream, selectors.EVENT_READ)
        cancellation_started: float | None = None
        termination_sent = False
        try:
            while True:
                now = monotonic()
                if (
                    cancel_requested is not None
                    and cancellation_started is None
                    and cancel_requested()
                ):
                    cancellation_started = now
                    self.write({"command": "cancel"})
                    if on_cancel is not None:
                        on_cancel()
                if cancellation_started is not None:
                    termination_sent = enforce_cancellation_deadline(
                        self.process,
                        elapsed=now - cancellation_started,
                        termination_sent=termination_sent,
                        on_termination=on_termination,
                    )
                if selector.select(timeout=0.05):
                    line = stream.readline(MAX_PROTOCOL_LINE_BYTES + 1)
                    if line:
                        break
                if self.process.poll() is not None:
                    if cancellation_started is not None:
                        raise ChildTransportCancelled
                    if confirmed_cgroup_oom(
                        self.process,
                        self.oom_kill_count_before,
                    ):
                        raise ChildTransportCgroupOom
                    raise ChildTransportError(
                        "Supervised child exited without a response"
                    )
        finally:
            selector.close()
        if cancellation_started is not None:
            raise ChildTransportCancelled
        if len(line.encode()) > MAX_PROTOCOL_LINE_BYTES or not line.endswith("\n"):
            raise ChildTransportError("Supervised child response exceeds its bound")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ChildTransportError("Supervised child response is invalid") from error
        if not isinstance(value, dict):
            raise ChildTransportError("Supervised child response is invalid")
        return value


def child_environment() -> dict[str, str]:
    environment = {"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"}
    for name in _THREAD_ENVIRONMENT_NAMES:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    if os.environ.get("THESISTRACE_QUALIFICATION_COLD_DATA_READS") == "1":
        environment["THESISTRACE_QUALIFICATION_COLD_DATA_READS"] = "1"
    return environment


def enforce_cancellation_deadline(
    process: subprocess.Popen[str],
    *,
    elapsed: float,
    termination_sent: bool,
    on_termination: Callable[[], None] | None,
) -> bool:
    if process.poll() is not None:
        return termination_sent
    if elapsed >= CANCEL_CHILD_EXIT_BUDGET_SECONDS:
        process.kill()
        return termination_sent
    if elapsed >= CANCEL_COOPERATIVE_GRACE_SECONDS and not termination_sent:
        process.send_signal(signal.SIGTERM)
        if on_termination is not None:
            on_termination()
        return True
    return termination_sent


def cgroup_oom_kill_count() -> int | None:
    for path in (
        Path("/sys/fs/cgroup/memory.events.local"),
        Path("/sys/fs/cgroup/memory.events"),
    ):
        try:
            values = dict(
                line.split(maxsplit=1)
                for line in path.read_text(encoding="utf-8").splitlines()
            )
        except (FileNotFoundError, OSError, ValueError):
            continue
        value = values.get("oom_kill")
        if value is not None:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def confirmed_cgroup_oom(
    process: subprocess.Popen[str],
    oom_kill_count_before: int | None,
) -> bool:
    if process.returncode not in {-signal.SIGKILL, 128 + signal.SIGKILL}:
        return False
    oom_kill_count_after = cgroup_oom_kill_count()
    return (
        oom_kill_count_before is not None
        and oom_kill_count_after is not None
        and oom_kill_count_after > oom_kill_count_before
    )


__all__ = (
    "ChildTransportCancelled",
    "ChildTransportCgroupOom",
    "ChildTransportError",
    "SupervisedChildTransport",
    "enforce_cancellation_deadline",
)

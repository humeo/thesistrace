from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread

from thesistrace.research_kernel.numeric import NumericContractError

ExecutionEvent = Callable[[dict[str, object]], None]
_MAX_PROTOCOL_LINE_BYTES = 64 * 1024 * 1024
_THREAD_ENVIRONMENT_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


class TrackingExecutionError(RuntimeError):
    pass


class TrackingExecutionOwnershipLost(TrackingExecutionError):
    pass


@dataclass(frozen=True)
class TrackingExecutionRequest:
    track_id: str
    attempt_id: str
    data_generation_id: str
    data_through_session: str
    origin: Mapping[str, object]
    predecessor: Mapping[str, object]
    predecessor_manifest_sha256: str
    current_session: str
    target_sessions: tuple[str, ...]
    watchdog_grace_seconds: float


@dataclass(frozen=True)
class TrackingExecutionResult:
    checkpoint: dict[str, object]
    terminal_strategy_state: dict[str, object]
    continuation: dict[str, object]
    continuation_basis_sha256: str
    child_peak_rss_bytes: int


class SupervisedTrackingExecution:
    def __init__(
        self,
        process: subprocess.Popen[str],
        request: TrackingExecutionRequest,
        result: TrackingExecutionResult,
        emit: ExecutionEvent,
        heartbeat: _ChildHeartbeat,
    ) -> None:
        self._process = process
        self._request = request
        self.result = result
        self._emit = emit
        self._heartbeat = heartbeat
        self._acknowledged = False
        self._exit_emitted = False

    def acknowledge(self) -> None:
        if self._acknowledged:
            raise TrackingExecutionError("Tracking execution was already acknowledged")
        self._heartbeat.acknowledge()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            self._process.kill()
            self._process.wait(timeout=2)
            raise TrackingExecutionError(
                "Tracking execution child did not exit after acknowledgement"
            ) from error
        if self._process.returncode != 0:
            raise TrackingExecutionError(self._child_failure("after acknowledgement"))
        self._acknowledged = True
        self._emit(self._event("tracking_execution_child_acknowledged"))
        self._emit_exit()

    def close(self) -> None:
        self._heartbeat.close()
        if self._process.poll() is None:
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
        self._emit_exit()

    def _event(self, event: str) -> dict[str, object]:
        return {
            "event": event,
            "resource_type": "TrackingAdvance",
            "resource_id": self._request.track_id,
            "attempt_id": self._request.attempt_id,
            "child_pid": self._process.pid,
        }

    def _emit_exit(self) -> None:
        if self._exit_emitted:
            return
        self._exit_emitted = True
        self._emit(
            {
                **self._event("tracking_execution_child_exited"),
                "exit_code": self._process.returncode,
                "acknowledged": self._acknowledged,
            }
        )

    def _child_failure(self, stage: str) -> str:
        stderr = ""
        if self._process.stderr is not None:
            stderr = self._process.stderr.read().strip()
        detail = f": {stderr}" if stderr else ""
        return f"Tracking execution child failed {stage}{detail}"


class _ChildHeartbeat:
    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        grace_seconds: float,
        authority_lost: Event,
    ) -> None:
        self._process = process
        self._interval = grace_seconds / 3
        self._authority_lost = authority_lost
        self._stopped = Event()
        self._stdin_lock = Lock()
        self._thread = Thread(
            target=self._run,
            name=f"tracking-child-heartbeat-{process.pid}",
            daemon=True,
        )
        self._thread.start()

    def acknowledge(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=2)
        with self._stdin_lock:
            self._write('{"command":"acknowledge"}\n', close=True)

    def close(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=2)
        with self._stdin_lock:
            if self._process.stdin is not None and not self._process.stdin.closed:
                self._process.stdin.close()

    def _run(self) -> None:
        while not self._stopped.is_set():
            if self._authority_lost.is_set():
                with self._stdin_lock:
                    if self._process.stdin is not None and not self._process.stdin.closed:
                        self._process.stdin.close()
                return
            with self._stdin_lock:
                try:
                    self._write('{"command":"heartbeat"}\n')
                except (BrokenPipeError, OSError):
                    return
            if self._stopped.wait(timeout=self._interval):
                return

    def _write(self, value: str, *, close: bool = False) -> None:
        if self._process.stdin is None or self._process.stdin.closed:
            raise TrackingExecutionError("Tracking execution child input is closed")
        self._process.stdin.write(value)
        self._process.stdin.flush()
        if close:
            self._process.stdin.close()


class SupervisedTrackingExecutor:
    def __init__(self, data_mount: Path, *, execution_memory_bytes: int) -> None:
        if execution_memory_bytes <= 0:
            raise ValueError("Tracking execution memory must be positive")
        self._data_mount = data_mount.resolve()
        self._execution_memory_bytes = execution_memory_bytes

    def execute(
        self,
        request: TrackingExecutionRequest,
        *,
        emit: ExecutionEvent,
        authority_lost: Event,
    ) -> SupervisedTrackingExecution:
        process = subprocess.Popen(
            [sys.executable, "-m", "thesistrace.entrypoints.tracking_child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_child_environment(),
        )
        heartbeat: _ChildHeartbeat | None = None
        try:
            emit(
                {
                    "event": "tracking_execution_child_started",
                    "resource_type": "TrackingAdvance",
                    "resource_id": request.track_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                }
            )
            assert process.stdin is not None
            process.stdin.write(
                json.dumps(
                    {
                        "schema_version": "tracking-child-request-v1",
                        "data_mount": str(self._data_mount),
                        "data_generation_id": request.data_generation_id,
                        "data_through_session": request.data_through_session,
                        "origin": dict(request.origin),
                        "predecessor": dict(request.predecessor),
                        "predecessor_manifest_sha256": (
                            request.predecessor_manifest_sha256
                        ),
                        "current_session": request.current_session,
                        "target_sessions": list(request.target_sessions),
                        "watchdog_grace_seconds": request.watchdog_grace_seconds,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.flush()
            heartbeat = _ChildHeartbeat(
                process,
                grace_seconds=request.watchdog_grace_seconds,
                authority_lost=authority_lost,
            )
            response = _read_message(
                process,
                request=request,
                emit=emit,
                authority_lost=authority_lost,
            )
            result = _result_from_response(response)
            if result.child_peak_rss_bytes > self._execution_memory_bytes:
                raise TrackingExecutionError(
                    "Tracking execution exceeded its declared memory budget"
                )
            emit(
                {
                    "event": "tracking_execution_result_received",
                    "resource_type": "TrackingAdvance",
                    "resource_id": request.track_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                    "boundary_session": request.target_sessions[-1],
                    "child_peak_rss_bytes": result.child_peak_rss_bytes,
                }
            )
            return SupervisedTrackingExecution(
                process,
                request,
                result,
                emit,
                heartbeat,
            )
        except Exception:
            if heartbeat is not None:
                heartbeat.close()
            elif process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            emit(
                {
                    "event": "tracking_execution_child_exited",
                    "resource_type": "TrackingAdvance",
                    "resource_id": request.track_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                    "exit_code": process.returncode,
                    "acknowledged": False,
                }
            )
            raise


def _read_message(
    process: subprocess.Popen[str],
    *,
    request: TrackingExecutionRequest,
    emit: ExecutionEvent,
    authority_lost: Event,
) -> dict[str, object]:
    if process.stdout is None:
        raise TrackingExecutionError("Tracking execution child has no output pipe")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            if authority_lost.is_set():
                raise TrackingExecutionOwnershipLost(
                    "Tracking execution ownership was lost"
                )
            if selector.select(timeout=0.05):
                line = process.stdout.readline(_MAX_PROTOCOL_LINE_BYTES + 1)
                if len(line.encode()) > _MAX_PROTOCOL_LINE_BYTES:
                    raise TrackingExecutionError("Tracking execution response is too large")
                if not line:
                    break
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TrackingExecutionError("Tracking execution response is invalid")
                if value.get("status") == "progress":
                    phase = value.get("phase")
                    current_session = value.get("current_session")
                    if phase not in {"calculating", "result_ready"} or not isinstance(
                        current_session, str
                    ):
                        raise TrackingExecutionError(
                            "Tracking execution progress is invalid"
                        )
                    if current_session not in request.target_sessions:
                        raise TrackingExecutionError(
                            "Tracking execution progress is outside its Target"
                        )
                    emit(
                        {
                            "event": "tracking_execution_progress",
                            "resource_type": "TrackingAdvance",
                            "resource_id": request.track_id,
                            "attempt_id": request.attempt_id,
                            "child_pid": process.pid,
                            "phase": phase,
                            "current_session": current_session,
                        }
                    )
                    continue
                if value.get("status") != "succeeded":
                    if value.get("category") == "NumericContractError":
                        raise NumericContractError(str(value.get("message", "")))
                    raise TrackingExecutionError(
                        str(value.get("message", "Tracking execution failed"))
                    )
                return value
            if process.poll() is not None:
                break
    finally:
        selector.close()
    stderr = ""
    if process.stderr is not None:
        stderr = process.stderr.read().strip()
    detail = f": {stderr}" if stderr else ""
    raise TrackingExecutionError(f"Tracking execution child exited without a result{detail}")


def _result_from_response(value: Mapping[str, object]) -> TrackingExecutionResult:
    checkpoint = value.get("checkpoint")
    terminal = value.get("terminal_strategy_state")
    continuation = value.get("continuation")
    if not all(isinstance(item, dict) for item in (checkpoint, terminal, continuation)):
        raise TrackingExecutionError("Tracking execution result payload is invalid")
    try:
        basis = str(value["continuation_basis_sha256"])
        peak = int(value["child_peak_rss_bytes"])
    except (KeyError, TypeError, ValueError) as error:
        raise TrackingExecutionError("Tracking execution result metadata is invalid") from error
    if len(basis) != 64 or peak <= 0:
        raise TrackingExecutionError("Tracking execution result metadata is invalid")
    return TrackingExecutionResult(
        checkpoint=dict(checkpoint),
        terminal_strategy_state=dict(terminal),
        continuation=dict(continuation),
        continuation_basis_sha256=basis,
        child_peak_rss_bytes=peak,
    )


def _child_environment() -> dict[str, str]:
    environment = {"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"}
    for name in _THREAD_ENVIRONMENT_NAMES:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    return environment

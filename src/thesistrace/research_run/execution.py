from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from thesistrace.data import GenerationStoreError, MountedGenerationStore
from thesistrace.research_kernel.kernel_run import (
    InsufficientCalculationWarmupError,
    KernelRunError,
    RunInput,
    run_columnar_chunk,
)
from thesistrace.research_run.models import ImmutableRunInput
from thesistrace.research_run.result import build_result_payload

_MAX_PROTOCOL_LINE_BYTES = 16 * 1024 * 1024
_THREAD_ENVIRONMENT_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
ExecutionEvent = Callable[[dict[str, object]], None]


class ResearchExecutionError(RuntimeError):
    pass


class ResearchExecutionInputInvalid(ResearchExecutionError):
    pass


class ResearchExecutionInsufficientWarmup(ResearchExecutionError):
    pass


@dataclass(frozen=True)
class ResearchExecutionRequest:
    run_id: str
    attempt_id: str
    data_generation_id: str
    immutable_input: ImmutableRunInput


class SupervisedResearchExecution:
    def __init__(
        self,
        process: subprocess.Popen[str],
        request: ResearchExecutionRequest,
        result: dict[str, object],
        emit: ExecutionEvent,
    ) -> None:
        self._process = process
        self._request = request
        self.result = result
        self._emit = emit
        self._acknowledged = False
        self._exit_emitted = False

    def acknowledge(self) -> None:
        if self._acknowledged:
            raise ResearchExecutionError("Research execution child was already acknowledged")
        assert self._process.stdin is not None
        self._process.stdin.write('{"command":"acknowledge"}\n')
        self._process.stdin.flush()
        self._process.stdin.close()
        self._process.wait(timeout=10)
        if self._process.returncode != 0:
            raise ResearchExecutionError(self._child_failure("after acknowledgement"))
        self._acknowledged = True
        self._emit(self._event("research_execution_child_acknowledged"))
        self._emit_exit()

    def close(self) -> None:
        if self._process.poll() is None:
            if self._process.stdin is not None and not self._process.stdin.closed:
                self._process.stdin.close()
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

    def _emit_exit(self) -> None:
        if self._exit_emitted:
            return
        self._exit_emitted = True
        self._emit(
            {
                **self._event("research_execution_child_exited"),
                "exit_code": self._process.returncode,
                "acknowledged": self._acknowledged,
            }
        )

    def _event(self, event: str) -> dict[str, object]:
        return {
            "event": event,
            "resource_type": "ResearchRun",
            "resource_id": self._request.run_id,
            "attempt_id": self._request.attempt_id,
            "child_pid": self._process.pid,
        }

    def _child_failure(self, stage: str) -> str:
        stderr = ""
        if self._process.stderr is not None:
            stderr = self._process.stderr.read().strip()
        detail = f": {stderr}" if stderr else ""
        return f"Research execution child failed {stage}{detail}"


class SupervisedResearchExecutor:
    def __init__(self, data_mount: Path) -> None:
        self._data_mount = data_mount.resolve()

    def execute(
        self,
        request: ResearchExecutionRequest,
        *,
        emit: ExecutionEvent,
    ) -> SupervisedResearchExecution:
        process = subprocess.Popen(
            [sys.executable, "-m", "thesistrace.entrypoints.research_child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_child_environment(),
        )
        try:
            emit(
                {
                    "event": "research_execution_child_started",
                    "resource_type": "ResearchRun",
                    "resource_id": request.run_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                }
            )
            assert process.stdin is not None
            process.stdin.write(
                json.dumps(
                    {
                        "schema_version": "research-child-request-v1",
                        "data_mount": str(self._data_mount),
                        "data_generation_id": request.data_generation_id,
                        "immutable_input": request.immutable_input.model_dump(mode="json"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.flush()
            try:
                response = _read_message(process.stdout)
            except ResearchExecutionError as error:
                process.wait(timeout=5)
                raise ResearchExecutionError(
                    f"{error}{_child_stderr_detail(process)}"
                ) from error
            if response.get("status") != "succeeded":
                category = response.get("category")
                message = str(response.get("message", "Research execution child failed"))
                if category == "insufficient_warmup":
                    raise ResearchExecutionInsufficientWarmup(message)
                if category == "invalid_input":
                    raise ResearchExecutionInputInvalid(message)
                raise ResearchExecutionError(message)
            result = response.get("result")
            if not isinstance(result, dict):
                raise ResearchExecutionError("Research execution child returned no Result")
            return SupervisedResearchExecution(process, request, result, emit)
        except Exception:
            if process.stdin is not None and not process.stdin.closed:
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
                    "event": "research_execution_child_exited",
                    "resource_type": "ResearchRun",
                    "resource_id": request.run_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                    "exit_code": process.returncode,
                    "acknowledged": False,
                }
            )
            raise


def execute_request(value: Mapping[str, object]) -> dict[str, object]:
    try:
        if value.get("schema_version") != "research-child-request-v1":
            raise ResearchExecutionInputInvalid("Research child request is incompatible")
        data_mount = Path(str(value["data_mount"]))
        generation_id = str(value["data_generation_id"])
        immutable_input = ImmutableRunInput.model_validate(value["immutable_input"])
        result = _calculate_result(data_mount, generation_id, immutable_input)
        return {"status": "succeeded", "result": result}
    except ResearchExecutionInsufficientWarmup as error:
        return {
            "status": "failed",
            "category": "insufficient_warmup",
            "message": str(error),
        }
    except (ResearchExecutionInputInvalid, GenerationStoreError, KernelRunError) as error:
        return {
            "status": "failed",
            "category": "invalid_input",
            "message": str(error),
        }


def _calculate_result(
    data_mount: Path,
    generation_id: str,
    immutable_input: ImmutableRunInput,
) -> dict[str, object]:
    store = MountedGenerationStore(data_mount)
    admission = store.open_admission(generation_id)
    start_session, end_session = _selected_research_period(
        immutable_input,
        research_sessions=list(admission.research_calendar),
        available_field_ids=frozenset(admission.generation.field_availability),
    )
    calendar = list(admission.research_calendar)
    start_index = calendar.index(start_session)
    warmup_start = start_index - immutable_input.alpha_admission.effective_lookback
    if warmup_start < 0:
        raise ResearchExecutionInsufficientWarmup(
            "insufficient Calculation Warm-up for selected Research Period"
        )
    calculation_sessions = calendar[warmup_start : calendar.index(end_session) + 1]
    research_data = store.read_columnar_slice(
        generation_id,
        sessions=calculation_sessions,
        universe_name=immutable_input.universe,
        neutralization=immutable_input.neutralization,
        field_bindings=immutable_input.field_bindings,
    )
    try:
        output = run_columnar_chunk(
            _kernel_input(
                immutable_input,
                research_data,
                research_start_session=start_session,
                research_end_session=end_session,
            )
        )
    except InsufficientCalculationWarmupError as error:
        raise ResearchExecutionInsufficientWarmup(str(error)) from error
    return build_result_payload(
        output,
        rebalance_interval=int(immutable_input.strategy["rebalance_every_sessions"]),
        universe=immutable_input.universe,
    )


def _selected_research_period(
    immutable_input: ImmutableRunInput,
    *,
    research_sessions: list[str],
    available_field_ids: frozenset[str],
) -> tuple[str, str]:
    if not research_sessions:
        raise ResearchExecutionInputInvalid(
            "selected Data Generation has no Research Sessions"
        )
    sessions = [str(session) for session in research_sessions]
    requested_start = immutable_input.requested_start_date.isoformat()
    requested_end = immutable_input.requested_end_date.isoformat()
    if requested_start < sessions[0] or requested_end > sessions[-1]:
        raise ResearchExecutionInputInvalid(
            "requested Research Period is outside Dataset Coverage"
        )
    selected = [
        session for session in sessions if requested_start <= session <= requested_end
    ]
    if not selected:
        raise ResearchExecutionInputInvalid("requested dates contain no Research Session")
    if set(immutable_input.field_bindings) - available_field_ids:
        raise ResearchExecutionInputInvalid(
            "selected Data Generation lacks a frozen field"
        )
    return selected[0], selected[-1]


def _kernel_input(
    immutable_input: ImmutableRunInput,
    research_data,
    *,
    research_start_session: str,
    research_end_session: str,
) -> RunInput:
    strategy = immutable_input.strategy
    costs = immutable_input.costs
    return RunInput(
        research_data=research_data,
        alpha_expression=immutable_input.alpha_expression,
        field_bindings=immutable_input.field_bindings,
        effective_alpha_lookback=immutable_input.alpha_admission.effective_lookback,
        universe=immutable_input.universe,
        neutralization=immutable_input.neutralization,
        holdings_count=int(strategy["holdings_count"]),
        rebalance_interval=int(strategy["rebalance_every_sessions"]),
        initial_cash_cny=str(strategy["initial_cash_cny"]),
        commission_rate_all_in=str(costs["commission_rate_all_in"]),
        commission_min_cny=str(costs["commission_min_cny"]),
        stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(costs["transfer_fee_rate"]),
        research_start_session=research_start_session,
        research_end_session=research_end_session,
    )


def _child_environment() -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONUNBUFFERED": "1",
    }
    for name in _THREAD_ENVIRONMENT_NAMES:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    return environment


def _read_message(stream: IO[str] | None) -> dict[str, object]:
    if stream is None:
        raise ResearchExecutionError("Research execution child has no output pipe")
    line = stream.readline(_MAX_PROTOCOL_LINE_BYTES + 1)
    if not line:
        raise ResearchExecutionError("Research execution child exited without a response")
    if len(line.encode()) > _MAX_PROTOCOL_LINE_BYTES or not line.endswith("\n"):
        raise ResearchExecutionError("Research execution child response exceeds its bound")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ResearchExecutionError("Research execution child response is invalid")
    return value


def _child_stderr_detail(process: subprocess.Popen[str]) -> str:
    if process.stderr is None:
        return ""
    stderr = process.stderr.read().strip()
    return f": {stderr}" if stderr else ""

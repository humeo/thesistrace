from __future__ import annotations

import json
import os
import resource
import selectors
import signal
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from thesistrace.data import GenerationStoreError, MountedGenerationStore
from thesistrace.research_kernel.kernel_run import KernelRunError, RunInput
from thesistrace.research_kernel.research_chunks import (
    empty_research_continuation,
    execute_research_chunk,
)
from thesistrace.research_run.models import ImmutableRunInput

_MAX_PROTOCOL_LINE_BYTES = 16 * 1024 * 1024
_CANCEL_COOPERATIVE_GRACE_SECONDS = 1.0
_CANCEL_CHILD_EXIT_BUDGET_SECONDS = 3.0
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


class ResearchExecutionCancelled(ResearchExecutionError):
    pass


class ResearchExecutionCalculationFailed(ResearchExecutionError):
    pass


class ResearchExecutionResourceExhausted(ResearchExecutionError):
    pass


@dataclass(frozen=True)
class ResearchExecutionRequest:
    run_id: str
    attempt_id: str
    data_generation_id: str
    immutable_input: ImmutableRunInput
    resume_from: ResearchExecutionResume | None = None


@dataclass(frozen=True)
class ResearchExecutionResume:
    completed_chunk_ordinal: int
    boundary_session: str
    completed_warmup_sessions: int
    completed_research_sessions: int
    continuation: Mapping[str, object]
    final_values: Mapping[str, object] | None


class SupervisedResearchExecution:
    def __init__(
        self,
        process: subprocess.Popen[str],
        request: ResearchExecutionRequest,
        chunk: dict[str, object],
        emit: ExecutionEvent,
        execution_memory_bytes: int,
        oom_kill_count_before: int | None,
    ) -> None:
        self._process = process
        self._request = request
        self.chunk = chunk
        self._emit = emit
        self._execution_memory_bytes = execution_memory_bytes
        self._oom_kill_count_before = oom_kill_count_before
        self._acknowledged = False
        self._exit_emitted = False

    def advance(self, *, cancel_requested: Callable[[], bool]) -> None:
        if self.chunk.get("final") is True:
            raise ResearchExecutionError("Final Research Chunk cannot advance")
        if cancel_requested():
            self.cancel()
            raise ResearchExecutionCancelled("Research execution was cancelled")
        assert self._process.stdin is not None
        self._process.stdin.write('{"command":"acknowledge_chunk"}\n')
        self._process.stdin.flush()
        response = _read_message(
            self._process,
            self._request,
            emit=self._emit,
            cancel_requested=cancel_requested,
            oom_kill_count_before=self._oom_kill_count_before,
        )
        self.chunk = _chunk_from_response(
            response,
            execution_memory_bytes=self._execution_memory_bytes,
        )
        self._emit(
            {
                **self._event("research_execution_chunk_received"),
                "chunk_ordinal": self.chunk["ordinal"],
                "boundary_session": self.chunk["boundary_session"],
                "reused_checkpoint": self.chunk["reused_checkpoint"],
                "child_peak_rss_bytes": _peak_rss_bytes(response),
                "child_chunk_seconds": _chunk_seconds(response),
                "child_data_read_seconds": _chunk_phase_seconds(
                    response, "child_data_read_seconds"
                ),
                "child_calculation_seconds": _chunk_phase_seconds(
                    response, "child_calculation_seconds"
                ),
                "child_calculation_phase_seconds": _calculation_phase_seconds(response),
                "data_io": _data_io(response),
            }
        )

    def acknowledge(self, *, cancel_requested: Callable[[], bool]) -> None:
        if self._acknowledged:
            raise ResearchExecutionError("Research execution child was already acknowledged")
        if self.chunk.get("final") is not True:
            raise ResearchExecutionError("Research execution has uncommitted Chunks")
        if cancel_requested():
            self.cancel()
            raise ResearchExecutionCancelled("Research execution was cancelled")
        assert self._process.stdin is not None
        self._process.stdin.write('{"command":"acknowledge"}\n')
        self._process.stdin.flush()
        self._process.stdin.close()
        cancellation_started: float | None = None
        termination_sent = False
        while self._process.poll() is None:
            now = monotonic()
            if cancellation_started is None and cancel_requested():
                cancellation_started = now
                self._emit(self._event("research_execution_child_cancel_requested"))
            if cancellation_started is not None:
                termination_sent = _enforce_cancellation_deadline(
                    self._process,
                    elapsed=now - cancellation_started,
                    termination_sent=termination_sent,
                    emit_termination=lambda: self._emit(
                        self._event("research_execution_child_termination_requested")
                    ),
                )
            try:
                self._process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                continue
        if cancellation_started is not None:
            self._emit_exit()
            raise ResearchExecutionCancelled("Research execution was cancelled")
        if self._process.returncode != 0:
            raise ResearchExecutionError(self._child_failure("after acknowledgement"))
        self._acknowledged = True
        self._emit(self._event("research_execution_child_acknowledged"))
        self._emit_exit()

    def cancel(self) -> None:
        if self._process.poll() is not None:
            self._emit_exit()
            return
        assert self._process.stdin is not None
        if not self._process.stdin.closed:
            self._process.stdin.write('{"command":"cancel"}\n')
            self._process.stdin.flush()
        self._emit(self._event("research_execution_child_cancel_requested"))
        started = monotonic()
        termination_sent = False
        while self._process.poll() is None:
            termination_sent = _enforce_cancellation_deadline(
                self._process,
                elapsed=monotonic() - started,
                termination_sent=termination_sent,
                emit_termination=lambda: self._emit(
                    self._event("research_execution_child_termination_requested")
                ),
            )
            try:
                self._process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                continue
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
    def __init__(
        self,
        data_mount: Path,
        *,
        execution_memory_bytes: int = 1536 * 1024**2,
    ) -> None:
        if execution_memory_bytes <= 0:
            raise ValueError("Research execution memory must be positive")
        self._data_mount = data_mount.resolve()
        self._execution_memory_bytes = execution_memory_bytes

    def execute(
        self,
        request: ResearchExecutionRequest,
        *,
        emit: ExecutionEvent,
        cancel_requested: Callable[[], bool],
    ) -> SupervisedResearchExecution:
        oom_kill_count_before = _cgroup_oom_kill_count()
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
                        "resume_from": (
                            None
                            if request.resume_from is None
                            else {
                                "completed_chunk_ordinal": (
                                    request.resume_from.completed_chunk_ordinal
                                ),
                                "boundary_session": request.resume_from.boundary_session,
                                "completed_warmup_sessions": (
                                    request.resume_from.completed_warmup_sessions
                                ),
                                "completed_research_sessions": (
                                    request.resume_from.completed_research_sessions
                                ),
                                "continuation": dict(request.resume_from.continuation),
                                "final_values": (
                                    None
                                    if request.resume_from.final_values is None
                                    else dict(request.resume_from.final_values)
                                ),
                            }
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.flush()
            try:
                response = _read_message(
                    process,
                    request,
                    emit=emit,
                    cancel_requested=cancel_requested,
                    oom_kill_count_before=oom_kill_count_before,
                )
            except ResearchExecutionCancelled:
                process.wait(timeout=1)
                raise
            except ResearchExecutionResourceExhausted:
                process.wait(timeout=5)
                raise
            except ResearchExecutionError as error:
                process.wait(timeout=5)
                raise ResearchExecutionError(f"{error}{_child_stderr_detail(process)}") from error
            chunk = _chunk_from_response(
                response,
                execution_memory_bytes=self._execution_memory_bytes,
            )
            emit(
                {
                    "event": "research_execution_chunk_received",
                    "resource_type": "ResearchRun",
                    "resource_id": request.run_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                    "chunk_ordinal": chunk["ordinal"],
                    "boundary_session": chunk["boundary_session"],
                    "reused_checkpoint": chunk["reused_checkpoint"],
                    "child_peak_rss_bytes": _peak_rss_bytes(response),
                    "child_chunk_seconds": _chunk_seconds(response),
                    "child_data_read_seconds": _chunk_phase_seconds(
                        response, "child_data_read_seconds"
                    ),
                    "child_calculation_seconds": _chunk_phase_seconds(
                        response, "child_calculation_seconds"
                    ),
                    "child_calculation_phase_seconds": _calculation_phase_seconds(response),
                    "data_io": _data_io(response),
                }
            )
            return SupervisedResearchExecution(
                process,
                request,
                chunk,
                emit,
                self._execution_memory_bytes,
                oom_kill_count_before,
            )
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


def execute_request_chunks(
    value: Mapping[str, object],
    *,
    cancel_requested: Callable[[], bool],
) -> Iterator[dict[str, object]]:
    try:
        if value.get("schema_version") != "research-child-request-v1":
            raise ResearchExecutionInputInvalid("Research child request is incompatible")
        data_mount = Path(str(value["data_mount"]))
        generation_id = str(value["data_generation_id"])
        immutable_input = ImmutableRunInput.model_validate(value["immutable_input"])
        resume_from = _resume_from_request(value.get("resume_from"), immutable_input)
        _require_not_cancelled(cancel_requested)
        yield from _calculate_chunks(
            data_mount,
            generation_id,
            immutable_input,
            resume_from=resume_from,
            cancel_requested=cancel_requested,
        )
    except ResearchExecutionCancelled as error:
        yield {"status": "cancelled", "category": "cancelled", "message": str(error)}
    except ResearchExecutionInsufficientWarmup as error:
        yield {
            "status": "failed",
            "category": "insufficient_warmup",
            "message": str(error),
        }
    except (ResearchExecutionInputInvalid, GenerationStoreError) as error:
        yield {
            "status": "failed",
            "category": "invalid_input",
            "message": str(error),
        }
    except KernelRunError as error:
        yield {"status": "failed", "category": "calculation", "message": str(error)}
    except MemoryError:
        yield {
            "status": "failed",
            "category": "resource_exhausted",
            "message": "Research execution exceeded its memory limit",
        }


def _calculate_chunks(
    data_mount: Path,
    generation_id: str,
    immutable_input: ImmutableRunInput,
    *,
    resume_from: ResearchExecutionResume | None,
    cancel_requested: Callable[[], bool],
) -> Iterator[dict[str, object]]:
    _require_not_cancelled(cancel_requested)
    store = MountedGenerationStore(data_mount)
    admission = store.open_admission(generation_id)
    _require_not_cancelled(cancel_requested)
    start_session, end_session = _selected_research_period(
        immutable_input,
        research_sessions=list(admission.research_calendar),
        available_field_ids=frozenset(admission.generation.field_availability),
    )
    calendar = list(admission.research_calendar)
    plan = immutable_input.execution_plan
    planned_sessions = tuple(session.isoformat() for session in plan.calculation_sessions)
    start_index = calendar.index(start_session)
    warmup_start = start_index - plan.research_session_offset
    if (
        warmup_start < 0
        or tuple(calendar[warmup_start : calendar.index(end_session) + 1]) != planned_sessions
    ):
        raise ResearchExecutionInsufficientWarmup(
            "frozen Research Chunk plan does not match selected Data Generation"
        )
    continuation = (
        empty_research_continuation() if resume_from is None else dict(resume_from.continuation)
    )
    completed_ordinal = 0 if resume_from is None else resume_from.completed_chunk_ordinal
    if completed_ordinal == len(plan.chunks):
        assert resume_from is not None and resume_from.final_values is not None
        yield {
            "status": "chunk_succeeded",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_chunk_seconds": 0.0,
            "child_data_read_seconds": 0.0,
            "child_calculation_seconds": 0.0,
            "child_calculation_phase_seconds": {
                "input": 0.0,
                "alpha_and_pending": 0.0,
                "factor": 0.0,
                "strategy": 0.0,
                "finalize": 0.0,
            },
            "chunk": {
                "ordinal": completed_ordinal,
                "boundary_session": resume_from.boundary_session,
                "phase": "research",
                "completed_warmup_sessions": resume_from.completed_warmup_sessions,
                "completed_research_sessions": resume_from.completed_research_sessions,
                "continuation": continuation,
                "strategy_daily_observations": [],
                "final_values": dict(resume_from.final_values),
                "final": True,
                "reused_checkpoint": True,
            },
        }
        return
    rolling_context = None
    for chunk in plan.chunks[completed_ordinal:]:
        chunk_started = monotonic()
        data_read_seconds = 0.0
        calculation_seconds = 0.0
        calculation_phase_seconds = {
            "input": 0.0,
            "alpha_and_pending": 0.0,
            "factor": 0.0,
            "strategy": 0.0,
            "finalize": 0.0,
        }
        _require_not_cancelled(cancel_requested)
        chunk_sessions = tuple(
            session
            for session in planned_sessions
            if chunk.first_session.isoformat() <= session <= chunk.last_session.isoformat()
        )
        research_sessions = tuple(
            session for session in chunk_sessions if start_session <= session <= end_session
        )
        final_chunk = chunk.ordinal == len(plan.chunks)
        observations: tuple[dict[str, object], ...] = ()
        final_values: dict[str, object] | None = None
        if research_sessions:
            fact_instrument_ids = _continuation_instrument_ids(continuation)
            if rolling_context is not None:
                fact_instrument_ids |= frozenset(rolling_context.instruments)
            first_research_index = calendar.index(research_sessions[0])
            context_session_count = max(
                immutable_input.alpha_admission.effective_lookback,
                21,
                2,
            )
            context_start = max(
                0,
                first_research_index - context_session_count,
            )
            context_sessions = calendar[context_start : calendar.index(research_sessions[-1]) + 1]
            retained_count = 0 if rolling_context is None else len(rolling_context.sessions)
            if (
                rolling_context is not None
                and tuple(context_sessions[:retained_count]) == rolling_context.sessions
            ):
                data_read_started = monotonic()
                fresh_data = store.read_columnar_slice(
                    generation_id,
                    sessions=context_sessions[retained_count:],
                    universe_name=immutable_input.universe,
                    neutralization=immutable_input.neutralization,
                    field_bindings=immutable_input.field_bindings,
                    fact_instrument_ids=fact_instrument_ids,
                )
                data_read_seconds = monotonic() - data_read_started
                research_data = rolling_context.append_sessions(fresh_data)
            else:
                data_read_started = monotonic()
                research_data = store.read_columnar_slice(
                    generation_id,
                    sessions=context_sessions,
                    universe_name=immutable_input.universe,
                    neutralization=immutable_input.neutralization,
                    field_bindings=immutable_input.field_bindings,
                    fact_instrument_ids=fact_instrument_ids,
                )
                data_read_seconds = monotonic() - data_read_started
            calculation_started = monotonic()
            input_started = monotonic()
            run_input = _kernel_input(
                immutable_input,
                research_data,
                research_start_session=start_session,
                research_end_session=end_session,
            )
            input_seconds = monotonic() - input_started
            calculation = execute_research_chunk(
                run_input=run_input,
                research_data=research_data,
                research_sessions=research_sessions,
                final_chunk=final_chunk,
                continuation=continuation,
                cancellation_check=lambda: _require_not_cancelled(cancel_requested),
            )
            calculation_seconds = monotonic() - calculation_started
            calculation_phase_seconds = {
                "input": input_seconds,
                **calculation.phase_seconds,
            }
            continuation = calculation.continuation
            observations = calculation.strategy_daily_observations
            final_values = calculation.final_values
            rolling_context = research_data.slice_sessions(
                tuple(context_sessions[-context_session_count:])
            )
        else:
            lookback = immutable_input.alpha_admission.effective_lookback
            continuation["rolling_tail_sessions"] = (
                list(chunk_sessions[-lookback:]) if lookback else []
            )
        yield {
            "status": "chunk_succeeded",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_chunk_seconds": monotonic() - chunk_started,
            "child_data_read_seconds": data_read_seconds,
            "child_calculation_seconds": calculation_seconds,
            "child_calculation_phase_seconds": calculation_phase_seconds,
            "chunk": {
                "ordinal": chunk.ordinal,
                "boundary_session": chunk.last_session.isoformat(),
                "phase": "research" if research_sessions else "warmup",
                "completed_warmup_sessions": min(
                    plan.research_session_offset,
                    chunk.ordinal * plan.chunk_session_count,
                ),
                "completed_research_sessions": int(
                    continuation["completed_research_session_count"]
                ),
                "continuation": continuation,
                "strategy_daily_observations": list(observations),
                "final_values": final_values,
                "final": final_chunk,
                "reused_checkpoint": False,
            },
        }


def _continuation_instrument_ids(
    continuation: Mapping[str, object],
) -> frozenset[str]:
    strategy = continuation.get("strategy_state")
    if not isinstance(strategy, Mapping):
        return frozenset()
    positions = strategy.get("positions")
    if not isinstance(positions, list):
        raise ResearchExecutionInputInvalid("Research Strategy continuation is invalid")
    return frozenset(
        str(position["instrument_id"])
        for position in positions
        if isinstance(position, Mapping) and "instrument_id" in position
    )


def _resume_from_request(
    value: object,
    immutable_input: ImmutableRunInput,
) -> ResearchExecutionResume | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ResearchExecutionInputInvalid("Research resume boundary is invalid")
    continuation = value.get("continuation")
    final_values = value.get("final_values")
    if not isinstance(continuation, Mapping) or (
        final_values is not None and not isinstance(final_values, Mapping)
    ):
        raise ResearchExecutionInputInvalid("Research resume payload is invalid")
    try:
        ordinal = int(value["completed_chunk_ordinal"])
        boundary = str(value["boundary_session"])
        completed_warmup = int(value["completed_warmup_sessions"])
        completed_research = int(value["completed_research_sessions"])
        chunk = immutable_input.execution_plan.chunks[ordinal - 1]
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise ResearchExecutionInputInvalid("Research resume boundary is invalid") from error
    if (
        ordinal < 1
        or boundary != chunk.last_session.isoformat()
        or completed_warmup < 0
        or completed_research < 0
        or (ordinal == len(immutable_input.execution_plan.chunks)) != (final_values is not None)
    ):
        raise ResearchExecutionInputInvalid("Research resume boundary is incompatible")
    return ResearchExecutionResume(
        completed_chunk_ordinal=ordinal,
        boundary_session=boundary,
        completed_warmup_sessions=completed_warmup,
        completed_research_sessions=completed_research,
        continuation=dict(continuation),
        final_values=None if final_values is None else dict(final_values),
    )


def _selected_research_period(
    immutable_input: ImmutableRunInput,
    *,
    research_sessions: list[str],
    available_field_ids: frozenset[str],
) -> tuple[str, str]:
    if not research_sessions:
        raise ResearchExecutionInputInvalid("selected Data Generation has no Research Sessions")
    sessions = [str(session) for session in research_sessions]
    requested_start = immutable_input.requested_start_date.isoformat()
    requested_end = immutable_input.requested_end_date.isoformat()
    if requested_start < sessions[0] or requested_end > sessions[-1]:
        raise ResearchExecutionInputInvalid("requested Research Period is outside Dataset Coverage")
    selected = [session for session in sessions if requested_start <= session <= requested_end]
    if not selected:
        raise ResearchExecutionInputInvalid("requested dates contain no Research Session")
    if set(immutable_input.field_bindings) - available_field_ids:
        raise ResearchExecutionInputInvalid("selected Data Generation lacks a frozen field")
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
    if os.environ.get("THESISTRACE_QUALIFICATION_COLD_DATA_READS") == "1":
        environment["THESISTRACE_QUALIFICATION_COLD_DATA_READS"] = "1"
    return environment


def _read_message(
    process: subprocess.Popen[str],
    request: ResearchExecutionRequest,
    *,
    emit: ExecutionEvent,
    cancel_requested: Callable[[], bool],
    oom_kill_count_before: int | None,
) -> dict[str, object]:
    stream = process.stdout
    if stream is None:
        raise ResearchExecutionError("Research execution child has no output pipe")
    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    cancellation_started: float | None = None
    termination_sent = False
    try:
        while True:
            now = monotonic()
            if cancellation_started is None and cancel_requested():
                cancellation_started = now
                assert process.stdin is not None
                process.stdin.write('{"command":"cancel"}\n')
                process.stdin.flush()
                emit(
                    {
                        "event": "research_execution_child_cancel_requested",
                        "resource_type": "ResearchRun",
                        "resource_id": request.run_id,
                        "attempt_id": request.attempt_id,
                        "child_pid": process.pid,
                    }
                )
            if cancellation_started is not None:
                termination_sent = _enforce_cancellation_deadline(
                    process,
                    elapsed=now - cancellation_started,
                    termination_sent=termination_sent,
                    emit_termination=lambda: emit(
                        {
                            "event": "research_execution_child_termination_requested",
                            "resource_type": "ResearchRun",
                            "resource_id": request.run_id,
                            "attempt_id": request.attempt_id,
                            "child_pid": process.pid,
                        }
                    ),
                )
            if selector.select(timeout=0.05):
                line = stream.readline(_MAX_PROTOCOL_LINE_BYTES + 1)
                if line:
                    break
            if process.poll() is not None:
                if cancellation_started is not None:
                    raise ResearchExecutionCancelled("Research execution was cancelled")
                if _is_confirmed_cgroup_oom(process, oom_kill_count_before):
                    raise ResearchExecutionResourceExhausted(
                        "Research execution child exceeded its cgroup memory limit"
                    )
                raise ResearchExecutionError("Research execution child exited without a response")
    finally:
        selector.close()
    if cancellation_started is not None:
        raise ResearchExecutionCancelled("Research execution was cancelled")
    if len(line.encode()) > _MAX_PROTOCOL_LINE_BYTES or not line.endswith("\n"):
        raise ResearchExecutionError("Research execution child response exceeds its bound")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ResearchExecutionError("Research execution child response is invalid")
    return value


def _chunk_from_response(
    response: Mapping[str, object],
    *,
    execution_memory_bytes: int,
) -> dict[str, object]:
    if response.get("status") != "chunk_succeeded":
        category = response.get("category")
        message = str(response.get("message", "Research execution child failed"))
        if category == "cancelled":
            raise ResearchExecutionCancelled(message)
        if category == "insufficient_warmup":
            raise ResearchExecutionInsufficientWarmup(message)
        if category == "invalid_input":
            raise ResearchExecutionInputInvalid(message)
        if category == "calculation":
            raise ResearchExecutionCalculationFailed(message)
        if category == "resource_exhausted":
            raise ResearchExecutionResourceExhausted(message)
        raise ResearchExecutionError(message)
    chunk = response.get("chunk")
    if not isinstance(chunk, dict):
        raise ResearchExecutionError("Research execution child returned no Chunk")
    required = {
        "ordinal",
        "boundary_session",
        "phase",
        "completed_warmup_sessions",
        "completed_research_sessions",
        "continuation",
        "strategy_daily_observations",
        "final_values",
        "final",
        "reused_checkpoint",
    }
    if set(chunk) != required:
        raise ResearchExecutionError("Research execution child returned an invalid Chunk")
    if _peak_rss_bytes(response) > execution_memory_bytes:
        raise ResearchExecutionResourceExhausted(
            "Research execution child exceeded its execution memory budget"
        )
    return chunk


def _cgroup_oom_kill_count() -> int | None:
    for path in (
        Path("/sys/fs/cgroup/memory.events.local"),
        Path("/sys/fs/cgroup/memory.events"),
    ):
        try:
            values = dict(
                line.split(maxsplit=1) for line in path.read_text(encoding="utf-8").splitlines()
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


def _is_confirmed_cgroup_oom(
    process: subprocess.Popen[str],
    oom_kill_count_before: int | None,
) -> bool:
    if process.returncode not in {-signal.SIGKILL, 128 + signal.SIGKILL}:
        return False
    oom_kill_count_after = _cgroup_oom_kill_count()
    return (
        oom_kill_count_before is not None
        and oom_kill_count_after is not None
        and oom_kill_count_after > oom_kill_count_before
    )


def _peak_rss_bytes(response: Mapping[str, object]) -> int:
    value = response.get("child_peak_rss_bytes")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ResearchExecutionError("Research execution child memory evidence is invalid")
    return value


def _chunk_seconds(response: Mapping[str, object]) -> float:
    value = response.get("child_chunk_seconds")
    if not isinstance(value, (float, int)) or isinstance(value, bool) or value < 0:
        raise ResearchExecutionError("Research execution child timing evidence is invalid")
    return float(value)


def _chunk_phase_seconds(response: Mapping[str, object], field: str) -> float:
    value = response.get(field)
    if not isinstance(value, (float, int)) or isinstance(value, bool) or value < 0:
        raise ResearchExecutionError("Research execution child timing evidence is invalid")
    return float(value)


def _calculation_phase_seconds(response: Mapping[str, object]) -> dict[str, float]:
    value = response.get("child_calculation_phase_seconds")
    required = {"input", "alpha_and_pending", "factor", "strategy", "finalize"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ResearchExecutionError("Research execution child timing evidence is invalid")
    result = {name: _nonnegative_seconds(value[name]) for name in required}
    if sum(result.values()) > _chunk_phase_seconds(response, "child_calculation_seconds"):
        raise ResearchExecutionError("Research execution child timing evidence is invalid")
    return result


def _nonnegative_seconds(value: object) -> float:
    if not isinstance(value, (float, int)) or isinstance(value, bool) or value < 0:
        raise ResearchExecutionError("Research execution child timing evidence is invalid")
    return float(value)


def _data_io(response: Mapping[str, object]) -> dict[str, int]:
    value = response.get("data_io")
    required = {
        "manifest_opens",
        "parquet_object_opens",
        "raw_financial_batch_opens",
        "market_parquet_scans",
        "financial_parquet_scans",
        "bytes_read",
        "rows_scanned",
        "columns_scanned",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ResearchExecutionError("Research execution child I/O evidence is invalid")
    result: dict[str, int] = {}
    for key in required:
        item = value[key]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ResearchExecutionError("Research execution child I/O evidence is invalid")
        result[key] = item
    return result


def _current_process_peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _require_not_cancelled(cancel_requested: Callable[[], bool]) -> None:
    if cancel_requested():
        raise ResearchExecutionCancelled("Research execution was cancelled")


def _enforce_cancellation_deadline(
    process: subprocess.Popen[str],
    *,
    elapsed: float,
    termination_sent: bool,
    emit_termination: Callable[[], None],
) -> bool:
    if process.poll() is not None:
        return termination_sent
    if elapsed >= _CANCEL_CHILD_EXIT_BUDGET_SECONDS:
        process.kill()
        return termination_sent
    if elapsed >= _CANCEL_COOPERATIVE_GRACE_SECONDS and not termination_sent:
        process.terminate()
        emit_termination()
        return True
    return termination_sent


def _child_stderr_detail(process: subprocess.Popen[str]) -> str:
    if process.stderr is None:
        return ""
    stderr = process.stderr.read().strip()
    return f": {stderr}" if stderr else ""

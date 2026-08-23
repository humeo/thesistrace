from __future__ import annotations

import resource
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import numpy as np

from thesistrace.data import GenerationStoreError, MountedGenerationStore
from thesistrace.research_kernel.factor import (
    PreparedColumnarForwardLabels,
    prepare_columnar_forward_labels,
)
from thesistrace.research_kernel.kernel_run import RunInput
from thesistrace.research_kernel.research_chunks import (
    AlphaFactorExecutionBinding,
    empty_research_continuation,
    execute_research_chunk,
)
from thesistrace.research_run.execution import (
    ResearchExecutionCalculationFailed,
    ResearchExecutionError,
    ResearchExecutionInputInvalid,
    ResearchExecutionInsufficientWarmup,
    ResearchExecutionResourceExhausted,
)
from thesistrace.research_run.models import ImmutableRunInput
from thesistrace.research_run.supervised_child import (
    ChildTransportCgroupOom,
    ChildTransportError,
    SupervisedChildTransport,
)
from thesistrace.research_series import ColumnarResearchSeries

ExecutionEvent = Callable[[dict[str, object]], None]


@dataclass(frozen=True)
class FactorBatchExecutionItem:
    ordinal: int
    item_key: str
    run_id: str
    immutable_input: ImmutableRunInput


@dataclass(frozen=True)
class FactorBatchExecutionRequest:
    batch_id: str
    attempt_id: str
    data_generation_id: str
    items: tuple[FactorBatchExecutionItem, ...]


class _SharedFactorResearchData:
    """In-memory views over one Batch-owned columnar Data preparation."""

    def __init__(
        self,
        source: ColumnarResearchSeries,
        *,
        field_ids: tuple[str, ...],
        sessions: tuple[str, ...] | None = None,
        prepared: _SharedFactorResearchData | None = None,
    ) -> None:
        self._source = source
        self.sessions = tuple(source.sessions) if sessions is None else sessions
        if prepared is None:
            self._instrument_axis = tuple(sorted(source.instruments))
            self._instrument_positions = {
                instrument_id: position
                for position, instrument_id in enumerate(self._instrument_axis)
            }
            self._session_positions = {
                session: position for position, session in enumerate(source.sessions)
            }
            self._numeric_fields = source.numeric_field_matrices(
                field_ids,
                self._instrument_axis,
            )
            self._adjusted_opens = source.adjusted_open_matrix(self._instrument_axis)
            self._adjusted_opens_decimal: np.ndarray | None = None
            self._universe_members = {
                session: tuple(source.universe_members[session]) for session in source.sessions
            }
        else:
            self._instrument_axis = prepared._instrument_axis
            self._instrument_positions = prepared._instrument_positions
            self._session_positions = prepared._session_positions
            self._numeric_fields = prepared._numeric_fields
            self._adjusted_opens = prepared._adjusted_opens
            self._adjusted_opens_decimal = prepared._adjusted_opens_decimal
            self._universe_members = prepared._universe_members

    @property
    def instruments(self):
        return self._source.instruments

    @property
    def universe_members(self):
        return self._universe_members

    @property
    def industries(self):
        return self._source.industries

    @property
    def execution_prices(self):
        return self._source.execution_prices

    @property
    def trading_states(self):
        return self._source.trading_states

    @property
    def price_limits(self):
        return self._source.price_limits

    def snapshot(self) -> _SharedFactorResearchData:
        return self

    def slice_sessions(self, sessions: tuple[str, ...]) -> _SharedFactorResearchData:
        if (
            not sessions
            or sessions != tuple(sorted(set(sessions)))
            or any(session not in self.sessions for session in sessions)
        ):
            raise ValueError("Shared Factor Research Sessions are invalid")
        return _SharedFactorResearchData(
            self._source,
            field_ids=(),
            sessions=sessions,
            prepared=self,
        )

    def numeric_field_matrices(
        self,
        field_ids: tuple[str, ...],
        instruments: tuple[str, ...],
    ) -> Mapping[str, np.ndarray]:
        instrument_positions = [
            self._instrument_positions[instrument_id] for instrument_id in instruments
        ]
        session_positions = [self._session_positions[session] for session in self.sessions]
        coordinates = np.ix_(instrument_positions, session_positions)
        return {field_id: self._numeric_fields[field_id][coordinates] for field_id in field_ids}

    def adjusted_open_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        return self._selected_matrix(self._adjusted_opens, instruments)

    def adjusted_open_decimal_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        if self._adjusted_opens_decimal is None:
            self._adjusted_opens_decimal = self._source.adjusted_open_decimal_matrix(
                self._instrument_axis
            )
        return self._selected_matrix(self._adjusted_opens_decimal, instruments)

    def _selected_matrix(
        self,
        matrix: np.ndarray,
        instruments: tuple[str, ...],
    ) -> np.ndarray:
        instrument_positions = [
            self._instrument_positions[instrument_id] for instrument_id in instruments
        ]
        session_positions = [self._session_positions[session] for session in self.sessions]
        return matrix[np.ix_(instrument_positions, session_positions)]


class SupervisedFactorBatchExecution:
    def __init__(
        self,
        transport: SupervisedChildTransport,
        request: FactorBatchExecutionRequest,
        message: dict[str, object],
        *,
        emit: ExecutionEvent,
        execution_memory_bytes: int,
    ) -> None:
        self._transport = transport
        self._process = transport.process
        self._request = request
        self.message = message
        self._emit = emit
        self._execution_memory_bytes = execution_memory_bytes
        self._acknowledged = False
        self._exit_emitted = False

    def advance(
        self,
        command: str,
    ) -> None:
        if command not in {
            "acknowledge_preparation",
            "acknowledge_chunk",
            "acknowledge_item",
        }:
            raise ResearchExecutionError("Factor Batch acknowledgement is invalid")
        self._write_command(command)
        self.message = _read_message(
            self._transport,
            execution_memory_bytes=self._execution_memory_bytes,
        )
        self._emit_message()

    def acknowledge(self) -> None:
        if self._acknowledged:
            raise ResearchExecutionError("Factor Batch child was already acknowledged")
        if self.message.get("status") != "batch_succeeded":
            raise ResearchExecutionError("Factor Batch child is not complete")
        self._write_command("acknowledge_batch")
        assert self._process.stdin is not None
        self._process.stdin.close()
        self._process.wait(timeout=5)
        if self._process.returncode != 0:
            raise ResearchExecutionError(self._child_failure("after acknowledgement"))
        self._acknowledged = True
        self._emit(self._event("research_batch_execution_child_acknowledged"))
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

    def _write_command(self, command: str) -> None:
        self._transport.write({"command": command})

    def _emit_message(self) -> None:
        status = str(self.message.get("status"))
        event = {
            **self._event(f"research_batch_execution_{status}"),
            "child_peak_rss_bytes": _peak_rss_bytes(self.message),
            "data_io": _data_io(self.message),
        }
        for name in (
            "item_ordinal",
            "item_key",
            "run_id",
            "chunk_ordinal",
            "boundary_session",
            "shared_session_count",
            "shared_field_count",
            "max_effective_lookback",
            "child_data_read_seconds",
            "child_chunk_seconds",
            "child_calculation_phase_seconds",
            "category",
            "error_type",
            "message",
            "alpha_factor_task_started",
            "alpha_factor_task_completed",
            "alpha_factor_task_failed",
        ):
            if name in self.message:
                event[name] = self.message[name]
        self._emit(event)

    def _event(self, event: str) -> dict[str, object]:
        return {
            "event": event,
            "resource_type": "ResearchBatch",
            "resource_id": self._request.batch_id,
            "attempt_id": self._request.attempt_id,
            "child_pid": self._process.pid,
        }

    def _emit_exit(self) -> None:
        if self._exit_emitted:
            return
        self._exit_emitted = True
        self._emit(
            {
                **self._event("research_batch_execution_child_exited"),
                "exit_code": self._process.returncode,
                "acknowledged": self._acknowledged,
            }
        )

    def _child_failure(self, stage: str) -> str:
        stderr = ""
        if self._process.stderr is not None:
            stderr = self._process.stderr.read().strip()
        detail = f": {stderr}" if stderr else ""
        return f"Research Batch execution child failed {stage}{detail}"


class SupervisedFactorBatchExecutor:
    def __init__(self, data_mount: Path, *, execution_memory_bytes: int) -> None:
        if execution_memory_bytes <= 0:
            raise ValueError("Research Batch execution memory must be positive")
        self._data_mount = data_mount.resolve()
        self._execution_memory_bytes = execution_memory_bytes

    def execute(
        self,
        request: FactorBatchExecutionRequest,
        *,
        emit: ExecutionEvent,
    ) -> SupervisedFactorBatchExecution:
        transport = SupervisedChildTransport.spawn(
            "thesistrace.entrypoints.batch_research_child"
        )
        process = transport.process
        emit(
            {
                "event": "research_batch_execution_child_started",
                "resource_type": "ResearchBatch",
                "resource_id": request.batch_id,
                "attempt_id": request.attempt_id,
                "child_pid": process.pid,
                "item_count": len(request.items),
            }
        )
        try:
            transport.write(
                {
                    "schema_version": "factor-batch-child-request-v1",
                    "data_mount": str(self._data_mount),
                    "data_generation_id": request.data_generation_id,
                    "items": [
                        {
                            "ordinal": item.ordinal,
                            "item_key": item.item_key,
                            "run_id": item.run_id,
                            "immutable_input": item.immutable_input.canonical_value(),
                        }
                        for item in request.items
                    ],
                }
            )
            message = _read_message(
                transport,
                execution_memory_bytes=self._execution_memory_bytes,
            )
            execution = SupervisedFactorBatchExecution(
                transport,
                request,
                message,
                emit=emit,
                execution_memory_bytes=self._execution_memory_bytes,
            )
            execution._emit_message()
            return execution
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
                    "event": "research_batch_execution_child_exited",
                    "resource_type": "ResearchBatch",
                    "resource_id": request.batch_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                    "exit_code": process.returncode,
                    "acknowledged": False,
                }
            )
            raise


def execute_factor_batch_messages(
    value: Mapping[str, object],
) -> Iterator[dict[str, object]]:
    try:
        if value.get("schema_version") != "factor-batch-child-request-v1":
            raise ResearchExecutionInputInvalid("Factor Batch child request is incompatible")
        data_mount = Path(str(value["data_mount"]))
        generation_id = str(value["data_generation_id"])
        raw_items = value.get("items")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
            raise ResearchExecutionInputInvalid("Factor Batch items are invalid")
        items = tuple(_execution_item(item) for item in raw_items)
        if tuple(item.ordinal for item in items) != tuple(range(1, len(items) + 1)):
            raise ResearchExecutionInputInvalid("Factor Batch item order is invalid")
        store = MountedGenerationStore(data_mount)
        admission = store.open_admission(generation_id)
        calendar = tuple(str(session) for session in admission.research_calendar)
        common = _validate_common_scope(items, generation_id, calendar)
        union_bindings = _union_field_bindings(items)
        shared_sessions = _shared_sessions(items, calendar)
        read_started = monotonic()
        source_data = store.read_columnar_slice(
            generation_id,
            sessions=list(shared_sessions),
            universe_name=common.universe,
            neutralization=common.neutralization,
            field_bindings=union_bindings,
            fact_instrument_ids=frozenset(),
        )
        research_data = _SharedFactorResearchData(
            source_data,
            field_ids=tuple(union_bindings),
        )
        forward_labels = prepare_columnar_forward_labels(
            research_data,
            cancellation_check=lambda: None,
        )
        yield {
            "status": "batch_prepared",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_data_read_seconds": monotonic() - read_started,
            "shared_session_count": len(shared_sessions),
            "shared_field_count": len(union_bindings),
            "max_effective_lookback": max(
                item.immutable_input.alpha_admission.effective_lookback for item in items
            ),
        }
        for item in items:
            try:
                yield from _execute_item_messages(
                    item,
                    generation_id=generation_id,
                    research_data=research_data,
                    forward_labels=forward_labels,
                )
            except MemoryError:
                raise
            except Exception as error:
                yield {
                    "status": "item_failed",
                    "category": "calculation",
                    "message": "Factor item calculation failed.",
                    "error_type": type(error).__name__,
                    "item_ordinal": item.ordinal,
                    "item_key": item.item_key,
                    "run_id": item.run_id,
                    "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
                    "alpha_factor_task_started": True,
                    "alpha_factor_task_failed": True,
                }
        yield {
            "status": "batch_succeeded",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        }
    except MemoryError:
        yield {
            "status": "failed",
            "category": "resource_exhausted",
            "message": "Research Batch execution exceeded its memory limit",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        }
    except (ResearchExecutionInputInvalid, ResearchExecutionInsufficientWarmup) as error:
        yield {
            "status": "failed",
            "category": "invalid_input",
            "message": str(error),
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        }
    except GenerationStoreError as error:
        yield {
            "status": "failed",
            "category": "invalid_input",
            "message": str(error),
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        }


def _execution_item(value: object) -> FactorBatchExecutionItem:
    if not isinstance(value, Mapping):
        raise ResearchExecutionInputInvalid("Factor Batch item is invalid")
    immutable_input = ImmutableRunInput.model_validate(value.get("immutable_input"))
    if immutable_input.research_kind != "factor_evaluation":
        raise ResearchExecutionInputInvalid("Factor Batch item kind is invalid")
    return FactorBatchExecutionItem(
        ordinal=int(value["ordinal"]),
        item_key=str(value["item_key"]),
        run_id=str(value["run_id"]),
        immutable_input=immutable_input,
    )


def _validate_common_scope(
    items: Sequence[FactorBatchExecutionItem],
    generation_id: str,
    calendar: tuple[str, ...],
) -> ImmutableRunInput:
    common = items[0].immutable_input
    common_identity = (
        common.requested_start_date,
        common.requested_end_date,
        common.universe,
        common.neutralization,
        common.numeric_execution_contract,
        common.semantic_versions,
        common.data_admission.generation_manifest_sha256,
    )
    for item in items:
        immutable_input = item.immutable_input
        identity = (
            immutable_input.requested_start_date,
            immutable_input.requested_end_date,
            immutable_input.universe,
            immutable_input.neutralization,
            immutable_input.numeric_execution_contract,
            immutable_input.semantic_versions,
            immutable_input.data_admission.generation_manifest_sha256,
        )
        if identity != common_identity or identity[-1] != generation_id:
            raise ResearchExecutionInputInvalid("Factor Batch scope is inconsistent")
        planned = tuple(
            session.isoformat() for session in immutable_input.execution_plan.calculation_sessions
        )
        if not planned or any(session not in calendar for session in planned):
            raise ResearchExecutionInsufficientWarmup(
                "frozen Factor Batch plan does not match selected Data Generation"
            )
        first = calendar.index(planned[0])
        if calendar[first : first + len(planned)] != planned:
            raise ResearchExecutionInsufficientWarmup(
                "frozen Factor Batch plan does not match selected Data Generation"
            )
    return common


def _union_field_bindings(
    items: Sequence[FactorBatchExecutionItem],
) -> dict[str, str]:
    union: dict[str, str] = {}
    for item in items:
        for field_id, identifier in item.immutable_input.field_bindings.items():
            existing = union.setdefault(field_id, identifier)
            if existing != identifier:
                raise ResearchExecutionInputInvalid(
                    "Factor Batch field binding is inconsistent"
                )
    return dict(sorted(union.items()))


def _shared_sessions(
    items: Sequence[FactorBatchExecutionItem],
    calendar: tuple[str, ...],
) -> tuple[str, ...]:
    first = min(
        item.immutable_input.execution_plan.calculation_sessions[0].isoformat()
        for item in items
    )
    last = max(
        item.immutable_input.execution_plan.calculation_sessions[-1].isoformat()
        for item in items
    )
    return calendar[calendar.index(first) : calendar.index(last) + 1]


def _execute_item_messages(
    item: FactorBatchExecutionItem,
    *,
    generation_id: str,
    research_data,
    forward_labels: PreparedColumnarForwardLabels,
) -> Iterator[dict[str, object]]:
    immutable_input = item.immutable_input
    plan = immutable_input.execution_plan
    research_start = immutable_input.data_admission.first_research_session.isoformat()
    research_end = immutable_input.data_admission.last_research_session.isoformat()
    continuation = empty_research_continuation("factor_evaluation")
    binding: AlphaFactorExecutionBinding | None = None
    for chunk in plan.chunks:
        started = monotonic()
        chunk_sessions = tuple(
            session.isoformat()
            for session in plan.calculation_sessions
            if chunk.first_session <= session <= chunk.last_session
        )
        research_sessions = tuple(
            session for session in chunk_sessions if research_start <= session <= research_end
        )
        final_values: dict[str, object] | None = None
        phase_seconds = {
            "input": 0.0,
            "alpha_and_pending": 0.0,
            "factor": 0.0,
            "strategy": 0.0,
            "finalize": 0.0,
        }
        if research_sessions:
            calendar = tuple(research_data.sessions)
            first_research_index = calendar.index(research_sessions[0])
            context_session_count = max(
                immutable_input.alpha_admission.effective_lookback,
                21,
                2,
            )
            context_start = max(0, first_research_index - context_session_count)
            context_sessions = calendar[
                context_start : calendar.index(research_sessions[-1]) + 1
            ]
            item_data = research_data.slice_sessions(tuple(context_sessions))
            input_started = monotonic()
            run_input = RunInput(
                research_data=item_data,
                alpha_expression=immutable_input.alpha_expression,
                field_bindings=immutable_input.field_bindings,
                effective_alpha_lookback=(
                    immutable_input.alpha_admission.effective_lookback
                ),
                universe=immutable_input.universe,
                neutralization=immutable_input.neutralization,
                research_kind="factor_evaluation",
                strategy=None,
                research_start_session=research_start,
                research_end_session=research_end,
            )
            if binding is None:
                binding = AlphaFactorExecutionBinding.from_run_input(
                    run_input,
                    data_generation_id=generation_id,
                    numeric_execution_contract=immutable_input.numeric_execution_contract,
                    semantic_versions=immutable_input.semantic_versions,
                )
            phase_seconds["input"] = monotonic() - input_started
            calculation = execute_research_chunk(
                run_input=run_input,
                binding=binding,
                research_data=item_data,
                forward_labels=forward_labels,
                research_sessions=research_sessions,
                final_chunk=chunk.ordinal == len(plan.chunks),
                continuation=continuation,
                cancellation_check=lambda: None,
            )
            continuation = calculation.continuation
            final_values = calculation.final_values
            phase_seconds.update(calculation.phase_seconds)
        else:
            lookback = immutable_input.alpha_admission.effective_lookback
            continuation["rolling_tail_sessions"] = (
                list(chunk_sessions[-lookback:]) if lookback else []
            )
        yield {
            "status": "item_chunk_succeeded",
            "item_ordinal": item.ordinal,
            "item_key": item.item_key,
            "run_id": item.run_id,
            "chunk_ordinal": chunk.ordinal,
            "boundary_session": chunk.last_session.isoformat(),
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_chunk_seconds": monotonic() - started,
            "child_data_read_seconds": 0.0,
            "child_calculation_phase_seconds": phase_seconds,
            "alpha_factor_task_started": chunk.ordinal == 1,
            "alpha_factor_task_completed": chunk.ordinal == len(plan.chunks),
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
                "strategy_daily_observations": [],
                "final_values": final_values,
                "final": chunk.ordinal == len(plan.chunks),
                "reused_checkpoint": False,
            },
        }


def _read_message(
    transport: SupervisedChildTransport,
    *,
    execution_memory_bytes: int,
) -> dict[str, object]:
    try:
        message = transport.read()
    except ChildTransportCgroupOom as error:
        raise ResearchExecutionResourceExhausted(
            "Research Batch child exceeded its cgroup memory limit"
        ) from error
    except ChildTransportError as error:
        detail = _child_stderr_detail(transport.process)
        raise ResearchExecutionError(f"{error}{detail}") from error
    peak = _peak_rss_bytes(message)
    _data_io(message)
    if peak > execution_memory_bytes:
        transport.process.kill()
        transport.process.wait(timeout=2)
        raise ResearchExecutionResourceExhausted(
            "Research Batch execution exceeded its memory limit"
        )
    status = message.get("status")
    if status == "failed":
        category = message.get("category")
        if category == "resource_exhausted":
            raise ResearchExecutionResourceExhausted(str(message.get("message")))
        raise ResearchExecutionInputInvalid(str(message.get("message")))
    if status not in {
        "batch_prepared",
        "item_chunk_succeeded",
        "item_failed",
        "batch_succeeded",
    }:
        raise ResearchExecutionError("Factor Batch child response is invalid")
    return message


def _current_process_peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _peak_rss_bytes(message: Mapping[str, object]) -> int:
    value = message.get("child_peak_rss_bytes")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ResearchExecutionError("Research Batch child memory evidence is invalid")
    return value


def _data_io(message: Mapping[str, object]) -> dict[str, int]:
    value = message.get("data_io")
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
        raise ResearchExecutionError("Research Batch child I/O evidence is invalid")
    result: dict[str, int] = {}
    for name in required:
        item = value[name]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ResearchExecutionError("Research Batch child I/O evidence is invalid")
        result[name] = item
    return result


def _child_stderr_detail(process: subprocess.Popen[str]) -> str:
    if process.stderr is None:
        return ""
    stderr = process.stderr.read().strip()
    return f": {stderr}" if stderr else ""


def item_failure_error(message: Mapping[str, object]) -> Exception:
    if message.get("category") == "calculation":
        return ResearchExecutionCalculationFailed("Factor item calculation failed")
    return ResearchExecutionError("Factor item execution failed")

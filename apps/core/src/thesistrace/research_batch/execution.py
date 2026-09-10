from __future__ import annotations

import os
import resource
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

import numpy as np

from thesistrace._memory import release_unused_memory as _release_chunk_memory
from thesistrace.data import GenerationStoreError, MountedGenerationStore
from thesistrace.publication.serialization import parquet_bytes
from thesistrace.research_batch.models import ResearchBatchKind
from thesistrace.research_batch.private_artifact import (
    PrivateAlphaFactorArtifactReader,
    PrivateAlphaFactorArtifactWriter,
    PrivateAlphaFactorChunk,
)
from thesistrace.research_kernel.factor import prepare_columnar_forward_labels
from thesistrace.research_kernel.kernel_run import RunInput, StrategyRunInput
from thesistrace.research_kernel.research_chunks import (
    AlphaFactorChunkOutcome,
    AlphaFactorExecutionBinding,
    empty_alpha_factor_continuation,
    empty_research_continuation,
    empty_strategy_continuation,
    execute_alpha_factor_chunk,
    execute_research_chunk,
    execute_strategy_chunk_from_alpha_factor_outcome,
)
from thesistrace.research_run.execution import (
    ResearchExecutionCalculationFailed,
    ResearchExecutionError,
    ResearchExecutionInputInvalid,
    ResearchExecutionInsufficientWarmup,
    ResearchExecutionResourceExhausted,
)
from thesistrace.research_run.models import ImmutableRunInput
from thesistrace.research_run.result import STRATEGY_DAILY_OBSERVATIONS_CONTRACT
from thesistrace.research_run.supervised_child import (
    ChildTransportCgroupOom,
    ChildTransportError,
    SupervisedChildTransport,
)
from thesistrace.research_series import ColumnarResearchSeries

ExecutionEvent = Callable[[dict[str, object]], None]
CancellationCheck = Callable[[], bool]


class ResearchBatchChildLost(ResearchExecutionError):
    """The supervised child disappeared before its current task was acknowledged."""


@dataclass(frozen=True)
class ResearchBatchExecutionItem:
    ordinal: int
    item_key: str
    run_id: str
    immutable_input: ImmutableRunInput


@dataclass(frozen=True)
class ResearchBatchExecutionRequest:
    batch_kind: ResearchBatchKind
    batch_id: str
    attempt_id: str
    data_generation_id: str
    items: tuple[ResearchBatchExecutionItem, ...]
    private_artifact_path: Path | None = None
    reuse_private_artifact: bool = False


@dataclass(frozen=True)
class _ResearchWindow:
    ordinal: int
    research_sessions: tuple[str, ...]
    final: bool


@dataclass
class _FactorItemState:
    continuation: dict[str, object]
    binding: AlphaFactorExecutionBinding | None = None
    final_values: dict[str, object] | None = None
    error: Exception | None = None
    calculation_seconds: float = 0.0
    phase_seconds: dict[str, float] = field(default_factory=lambda: _empty_phase_seconds())


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


class SupervisedResearchBatchExecution:
    def __init__(
        self,
        transport: SupervisedChildTransport,
        request: ResearchBatchExecutionRequest,
        message: dict[str, object],
        *,
        emit: ExecutionEvent,
        execution_memory_bytes: int,
        cancel_requested: CancellationCheck,
    ) -> None:
        self._transport = transport
        self._process = transport.process
        self._request = request
        self.message = message
        self._emit = emit
        self._execution_memory_bytes = execution_memory_bytes
        self._cancel_requested = cancel_requested
        self._acknowledged = False
        self._exit_emitted = False

    @property
    def child_pid(self) -> int:
        return self._process.pid

    def advance(
        self,
        command: str,
    ) -> None:
        if command not in {
            "acknowledge_ready",
            "acknowledge_preparation",
            "acknowledge_progress",
            "acknowledge_shared",
            "acknowledge_chunk",
            "acknowledge_item",
        }:
            raise ResearchExecutionError("Research Batch acknowledgement is invalid")
        self._write_command(command)
        self.message = _read_message(
            self._transport,
            execution_memory_bytes=self._execution_memory_bytes,
            cancel_requested=self._cancel_requested,
        )
        self._emit_message()

    def acknowledge(self) -> None:
        if self._acknowledged:
            raise ResearchExecutionError("Research Batch child was already acknowledged")
        if self.message.get("status") != "batch_succeeded":
            raise ResearchExecutionError("Research Batch child is not complete")
        self._write_command("acknowledge_batch")
        assert self._process.stdin is not None
        self._process.stdin.close()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise ResearchBatchChildLost(
                "Research Batch child did not exit after acknowledgement"
            ) from error
        if self._process.returncode != 0:
            raise ResearchBatchChildLost(self._child_failure("after acknowledgement"))
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
            "shared_chunk_count",
            "shared_artifact_bytes",
            "shared_artifact_capacity_bytes",
            "private_artifact_reused",
            "private_artifact_sha256",
            "private_artifact_binding_checksum",
            "strategy_task_started",
            "strategy_task_completed",
            "strategy_task_failed",
            "task_role",
            "phase",
            "completed_research_sessions",
            "total_research_sessions",
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


class SupervisedResearchBatchExecutor:
    def __init__(
        self,
        data_mount: Path,
        *,
        attempt_control_directory: Path,
        execution_memory_bytes: int,
    ) -> None:
        if execution_memory_bytes <= 0:
            raise ValueError("Research Batch execution memory must be positive")
        self._data_mount = data_mount.resolve()
        self._attempt_control_directory = attempt_control_directory.resolve()
        self._execution_memory_bytes = execution_memory_bytes

    def attempt_control_path(self, attempt_id: str) -> Path:
        return self._attempt_control_directory / f"{attempt_id}.lock"

    def execute(
        self,
        request: ResearchBatchExecutionRequest,
        *,
        emit: ExecutionEvent,
        cancel_requested: CancellationCheck,
    ) -> SupervisedResearchBatchExecution:
        self._attempt_control_directory.mkdir(parents=True, exist_ok=True)
        control_path = self.attempt_control_path(request.attempt_id)
        transport = SupervisedChildTransport.spawn("thesistrace.entrypoints.batch_research_child")
        process = transport.process
        try:
            transport.write(
                {
                    "schema_version": "research-batch-child-request-v2",
                    "batch_kind": request.batch_kind,
                    "data_mount": str(self._data_mount),
                    "attempt_control_path": str(control_path),
                    "data_generation_id": request.data_generation_id,
                    "batch_id": request.batch_id,
                    "private_artifact_path": (
                        None
                        if request.private_artifact_path is None
                        else str(request.private_artifact_path)
                    ),
                    "reuse_private_artifact": request.reuse_private_artifact,
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
                cancel_requested=cancel_requested,
            )
            if message.get("status") != "child_ready":
                raise ResearchExecutionError("Research Batch child did not become ready")
            emit(
                {
                    "event": "research_batch_execution_child_started",
                    "resource_type": "ResearchBatch",
                    "resource_id": request.batch_id,
                    "attempt_id": request.attempt_id,
                    "child_pid": process.pid,
                    "child_control_path": str(control_path),
                    "item_count": len(request.items),
                }
            )
            execution = SupervisedResearchBatchExecution(
                transport,
                request,
                message,
                emit=emit,
                execution_memory_bytes=self._execution_memory_bytes,
                cancel_requested=cancel_requested,
            )
            execution.advance("acknowledge_ready")
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


def execute_research_batch_messages(
    value: Mapping[str, object],
) -> Iterator[dict[str, object]]:
    try:
        if value.get("schema_version") != "research-batch-child-request-v2":
            raise ResearchExecutionInputInvalid("Research Batch child request is incompatible")
        batch_kind = str(value.get("batch_kind"))
        if batch_kind not in {"factor_evaluation", "strategy_sweep"}:
            raise ResearchExecutionInputInvalid("Research Batch Kind is invalid")
        data_mount = Path(str(value["data_mount"]))
        generation_id = str(value["data_generation_id"])
        batch_id = str(value["batch_id"])
        raw_artifact_path = value.get("private_artifact_path")
        private_artifact_path = None if raw_artifact_path is None else Path(str(raw_artifact_path))
        reuse_private_artifact = value.get("reuse_private_artifact")
        if (
            not batch_id
            or not isinstance(reuse_private_artifact, bool)
            or (batch_kind == "strategy_sweep") != (private_artifact_path is not None)
            or (batch_kind != "strategy_sweep" and reuse_private_artifact)
        ):
            raise ResearchExecutionInputInvalid(
                "Research Batch private artifact request is invalid"
            )
        raw_items = value.get("items")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
            raise ResearchExecutionInputInvalid("Research Batch items are invalid")
        items = tuple(_execution_item(item, batch_kind=batch_kind) for item in raw_items)
        ordinals = tuple(item.ordinal for item in items)
        if any(ordinal <= 0 for ordinal in ordinals) or ordinals != tuple(sorted(set(ordinals))):
            raise ResearchExecutionInputInvalid("Research Batch item order is invalid")
        store = MountedGenerationStore(data_mount)
        admission = store.open_admission(generation_id)
        calendar = tuple(str(session) for session in admission.research_calendar)
        common = _validate_common_scope(items, generation_id, calendar)
        union_bindings = _union_field_bindings(items)
        research_windows = _shared_research_windows(
            common,
            calendar,
        )
        yield {
            "status": "batch_prepared",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_data_read_seconds": 0.0,
            "shared_session_count": sum(
                len(window.research_sessions) for window in research_windows
            ),
            "shared_field_count": len(union_bindings),
            "max_effective_lookback": max(
                item.immutable_input.alpha_admission.effective_lookback for item in items
            ),
        }
        if batch_kind == "strategy_sweep":
            yield from _execute_strategy_sweep_messages(
                items,
                batch_id=batch_id,
                generation_id=generation_id,
                store=store,
                calendar=calendar,
                research_windows=research_windows,
                union_bindings=union_bindings,
                private_artifact_path=private_artifact_path,
                reuse_private_artifact=reuse_private_artifact,
            )
            yield {
                "status": "batch_succeeded",
                "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            }
            return
        yield from _execute_factor_batch_messages(
            items,
            generation_id=generation_id,
            store=store,
            calendar=calendar,
            research_windows=research_windows,
            union_bindings=union_bindings,
        )
        yield {
            "status": "batch_succeeded",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        }
    except (MemoryError, ResearchExecutionResourceExhausted):
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


def _execution_item(
    value: object,
    *,
    batch_kind: str,
) -> ResearchBatchExecutionItem:
    if not isinstance(value, Mapping):
        raise ResearchExecutionInputInvalid("Research Batch item is invalid")
    immutable_input = ImmutableRunInput.model_validate(value.get("immutable_input"))
    expected_kind = (
        "factor_evaluation" if batch_kind == "factor_evaluation" else "strategy_backtest"
    )
    if immutable_input.research_kind != expected_kind:
        raise ResearchExecutionInputInvalid("Research Batch item kind is invalid")
    return ResearchBatchExecutionItem(
        ordinal=int(value["ordinal"]),
        item_key=str(value["item_key"]),
        run_id=str(value["run_id"]),
        immutable_input=immutable_input,
    )


def _validate_common_scope(
    items: Sequence[ResearchBatchExecutionItem],
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
        common.execution_plan.chunk_session_count,
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
            immutable_input.execution_plan.chunk_session_count,
        )
        if identity != common_identity or identity[-2] != generation_id:
            raise ResearchExecutionInputInvalid("Research Batch scope is inconsistent")
        planned = tuple(
            session.isoformat() for session in immutable_input.execution_plan.calculation_sessions
        )
        if not planned or any(session not in calendar for session in planned):
            raise ResearchExecutionInsufficientWarmup(
                "frozen Research Batch plan does not match selected Data Generation"
            )
        first = calendar.index(planned[0])
        if calendar[first : first + len(planned)] != planned:
            raise ResearchExecutionInsufficientWarmup(
                "frozen Research Batch plan does not match selected Data Generation"
            )
    return common


def _union_field_bindings(
    items: Sequence[ResearchBatchExecutionItem],
) -> dict[str, str]:
    union: dict[str, str] = {}
    for item in items:
        for field_id, identifier in item.immutable_input.field_bindings.items():
            existing = union.setdefault(field_id, identifier)
            if existing != identifier:
                raise ResearchExecutionInputInvalid("Research Batch field binding is inconsistent")
    return dict(sorted(union.items()))


def _shared_research_windows(
    immutable_input: ImmutableRunInput,
    calendar: tuple[str, ...],
) -> tuple[_ResearchWindow, ...]:
    first = immutable_input.data_admission.first_research_session.isoformat()
    last = immutable_input.data_admission.last_research_session.isoformat()
    research_sessions = calendar[calendar.index(first) : calendar.index(last) + 1]
    chunk_session_count = immutable_input.execution_plan.chunk_session_count
    windows = tuple(
        _ResearchWindow(
            ordinal=(offset // chunk_session_count) + 1,
            research_sessions=research_sessions[offset : offset + chunk_session_count],
            final=offset + chunk_session_count >= len(research_sessions),
        )
        for offset in range(0, len(research_sessions), chunk_session_count)
    )
    if not windows:
        raise ResearchExecutionInputInvalid("Research Batch research period is empty")
    return windows


def _execute_factor_batch_messages(
    items: Sequence[ResearchBatchExecutionItem],
    *,
    generation_id: str,
    store: MountedGenerationStore,
    calendar: tuple[str, ...],
    research_windows: Sequence[_ResearchWindow],
    union_bindings: Mapping[str, str],
) -> Iterator[dict[str, object]]:
    states = {
        item.ordinal: _FactorItemState(
            continuation=empty_research_continuation("factor_evaluation")
        )
        for item in items
    }
    first_item = items[0]
    yield _task_started_message(first_item, task_role="factor", phase="research")
    max_lookback = max(item.immutable_input.alpha_admission.effective_lookback for item in items)
    total_data_read_seconds = 0.0
    common = first_item.immutable_input
    for window in research_windows:
        chunk_started = monotonic()
        chunk_phase_seconds = _empty_phase_seconds()
        data_read_started = monotonic()
        try:
            research_data = _read_shared_window(
                store,
                generation_id=generation_id,
                calendar=calendar,
                research_sessions=window.research_sessions,
                universe=common.universe,
                neutralization=common.neutralization,
                field_bindings=union_bindings,
                effective_lookback=max_lookback,
                fact_instrument_ids=frozenset(),
            )
            data_read_seconds = monotonic() - data_read_started
            total_data_read_seconds += data_read_seconds
            labels_started = monotonic()
            forward_labels = prepare_columnar_forward_labels(
                research_data,
                cancellation_check=lambda: None,
            )
            # Shared label preparation belongs to the first item only.
            labels_seconds = monotonic() - labels_started
            states[first_item.ordinal].calculation_seconds += labels_seconds
            states[first_item.ordinal].phase_seconds["input"] += labels_seconds
            chunk_phase_seconds["input"] += labels_seconds
        except (MemoryError, ResearchExecutionResourceExhausted):
            raise
        except Exception as error:
            for state in states.values():
                if state.error is None and state.final_values is None:
                    state.error = error
            break

        for item in items:
            state = states[item.ordinal]
            if state.error is not None:
                continue
            calculation_started = monotonic()
            try:
                run_input = _factor_run_input(item.immutable_input, research_data)
                if state.binding is None:
                    state.binding = AlphaFactorExecutionBinding.from_run_input(
                        run_input,
                        data_generation_id=generation_id,
                        numeric_execution_contract=(
                            item.immutable_input.numeric_execution_contract
                        ),
                        semantic_versions=item.immutable_input.semantic_versions,
                    )
                input_seconds = monotonic() - calculation_started
                state.phase_seconds["input"] += input_seconds
                chunk_phase_seconds["input"] += input_seconds
                calculation = execute_research_chunk(
                    run_input=run_input,
                    binding=state.binding,
                    research_data=research_data,
                    forward_labels=forward_labels,
                    research_sessions=window.research_sessions,
                    final_chunk=window.final,
                    continuation=state.continuation,
                    cancellation_check=lambda: None,
                )
                state.continuation = calculation.continuation
                state.final_values = calculation.final_values
                state.calculation_seconds += monotonic() - calculation_started
                for name, seconds in calculation.phase_seconds.items():
                    state.phase_seconds[name] += seconds
                    chunk_phase_seconds[name] += seconds
                del calculation, run_input
            except (MemoryError, ResearchExecutionResourceExhausted):
                raise
            except Exception as error:
                state.error = error

        first_state = states[first_item.ordinal]
        del forward_labels, research_data
        _release_chunk_memory()
        if not window.final and first_state.error is None:
            completed = int(first_state.continuation["completed_research_session_count"])
            yield {
                "status": "item_chunk_succeeded",
                "item_ordinal": first_item.ordinal,
                "item_key": first_item.item_key,
                "run_id": first_item.run_id,
                "chunk_ordinal": window.ordinal,
                "boundary_session": window.research_sessions[-1],
                "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
                "child_chunk_seconds": monotonic() - chunk_started,
                "child_data_read_seconds": data_read_seconds,
                "child_calculation_phase_seconds": chunk_phase_seconds,
                "alpha_factor_task_started": False,
                "alpha_factor_task_completed": False,
                "task_role": "factor",
                "phase": "research",
                "completed_research_sessions": completed,
                "total_research_sessions": (
                    first_item.immutable_input.execution_plan.research_session_count
                ),
                "chunk": {
                    "ordinal": window.ordinal,
                    "boundary_session": window.research_sessions[-1],
                    "phase": "research",
                    "completed_warmup_sessions": (
                        first_item.immutable_input.execution_plan.research_session_offset
                    ),
                    "completed_research_sessions": completed,
                    "continuation": {},
                    "strategy_daily_observations": [],
                    "final_values": None,
                    "final": False,
                    "reused_checkpoint": False,
                },
            }

    for index, item in enumerate(items):
        if index:
            yield _task_started_message(item, task_role="factor", phase="finalizing")
        state = states[item.ordinal]
        if state.error is not None or state.final_values is None:
            error = state.error or ValueError("Factor item outcome is incomplete")
            yield _item_failed_message(item, error, task_role="factor")
            continue
        plan = item.immutable_input.execution_plan
        yield {
            "status": "item_chunk_succeeded",
            "item_ordinal": item.ordinal,
            "item_key": item.item_key,
            "run_id": item.run_id,
            "chunk_ordinal": len(plan.chunks),
            "boundary_session": plan.chunks[-1].last_session.isoformat(),
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_chunk_seconds": state.calculation_seconds,
            "child_data_read_seconds": (
                total_data_read_seconds if item.ordinal == first_item.ordinal else 0.0
            ),
            "child_calculation_phase_seconds": dict(state.phase_seconds),
            "alpha_factor_task_started": False,
            "alpha_factor_task_completed": True,
            "task_role": "factor",
            "phase": "finalizing",
            "completed_research_sessions": plan.research_session_count,
            "total_research_sessions": plan.research_session_count,
            "chunk": {
                "ordinal": len(plan.chunks),
                "boundary_session": plan.chunks[-1].last_session.isoformat(),
                "phase": "research",
                "completed_warmup_sessions": plan.research_session_offset,
                "completed_research_sessions": plan.research_session_count,
                "continuation": state.continuation,
                "strategy_daily_observations": [],
                "final_values": state.final_values,
                "final": True,
                "reused_checkpoint": False,
            },
        }


def _execute_strategy_sweep_messages(
    items: Sequence[ResearchBatchExecutionItem],
    *,
    batch_id: str,
    generation_id: str,
    store: MountedGenerationStore,
    calendar: tuple[str, ...],
    research_windows: Sequence[_ResearchWindow],
    union_bindings: Mapping[str, str],
    private_artifact_path: Path,
    reuse_private_artifact: bool,
) -> Iterator[dict[str, object]]:
    shared_input = items[0].immutable_input
    plan = shared_input.execution_plan
    research_start = shared_input.data_admission.first_research_session.isoformat()
    research_end = shared_input.data_admission.last_research_session.isoformat()
    alpha_continuation = empty_alpha_factor_continuation()
    binding: AlphaFactorExecutionBinding | None = None
    # This is a disk-size guard, not resident-memory admission. Each payload was
    # already created under the child memory limit, so total history may grow the
    # file only by adding bounded frames.
    shared_artifact_capacity_bytes = plan.execution_memory_bytes * len(
        research_windows
    ) + 64 * 1024 * (len(research_windows) + 2)
    final_alpha_continuation: dict[str, object] | None = None
    phase_seconds = _empty_phase_seconds()
    metadata = None
    shared_started = monotonic()
    yield {
        "status": "shared_alpha_factor_started",
        "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        "task_role": "shared_alpha_factor",
        "phase": "research",
        "private_artifact_reused": reuse_private_artifact,
        "alpha_factor_task_started": not reuse_private_artifact,
        "completed_research_sessions": 0,
        "total_research_sessions": plan.research_session_count,
    }
    try:
        _validate_strategy_shared_contract(items)
        if reuse_private_artifact:
            first_window = research_windows[0]
            first_data = _read_shared_window(
                store,
                generation_id=generation_id,
                calendar=calendar,
                research_sessions=first_window.research_sessions,
                universe=shared_input.universe,
                neutralization="none",
                field_bindings={},
                effective_lookback=0,
                fact_instrument_ids=frozenset(),
            )
            binding = AlphaFactorExecutionBinding.from_run_input(
                _strategy_run_input(
                    shared_input,
                    first_data,
                    research_start=research_start,
                    research_end=research_end,
                ),
                data_generation_id=generation_id,
                numeric_execution_contract=shared_input.numeric_execution_contract,
                semantic_versions=shared_input.semantic_versions,
            )
            del first_data
            with PrivateAlphaFactorArtifactReader(
                private_artifact_path,
                expected_batch_id=batch_id,
                expected_binding=binding,
                maximum_chunk_payload_bytes=plan.execution_memory_bytes,
            ) as reader:
                for window, stored in zip(research_windows, reader, strict=True):
                    _require_artifact_window(stored, window)
                    del stored
                    _release_chunk_memory()
                final_alpha_continuation = reader.final_alpha_continuation
                metadata = reader.metadata
        else:
            writer: PrivateAlphaFactorArtifactWriter | None = None
            try:
                for window in research_windows:
                    input_started = monotonic()
                    research_data = _read_shared_window(
                        store,
                        generation_id=generation_id,
                        calendar=calendar,
                        research_sessions=window.research_sessions,
                        universe=shared_input.universe,
                        neutralization=shared_input.neutralization,
                        field_bindings=union_bindings,
                        effective_lookback=(shared_input.alpha_admission.effective_lookback),
                        fact_instrument_ids=frozenset(),
                    )
                    phase_seconds["input"] += monotonic() - input_started
                    forward_labels = prepare_columnar_forward_labels(
                        research_data,
                        cancellation_check=lambda: None,
                    )
                    run_input = _strategy_run_input(
                        shared_input,
                        research_data,
                        research_start=research_start,
                        research_end=research_end,
                    )
                    if binding is None:
                        binding = AlphaFactorExecutionBinding.from_run_input(
                            run_input,
                            data_generation_id=generation_id,
                            numeric_execution_contract=(shared_input.numeric_execution_contract),
                            semantic_versions=shared_input.semantic_versions,
                        )
                        writer = PrivateAlphaFactorArtifactWriter(
                            private_artifact_path,
                            batch_id=batch_id,
                            binding=binding,
                            maximum_chunk_payload_bytes=plan.execution_memory_bytes,
                        )
                    assert writer is not None
                    outcome = execute_alpha_factor_chunk(
                        run_input=run_input,
                        binding=binding,
                        research_data=research_data,
                        forward_labels=forward_labels,
                        research_sessions=window.research_sessions,
                        final_chunk=window.final,
                        continuation=alpha_continuation,
                        cancellation_check=lambda: None,
                    )
                    alpha_continuation = outcome.continuation_snapshot()
                    final_alpha_continuation = alpha_continuation
                    for name in ("alpha_and_pending", "factor", "finalize"):
                        phase_seconds[name] += outcome.phase_seconds[name]
                    outcome_payload = outcome.compact_for_reuse()
                    del outcome
                    writer.append(
                        PrivateAlphaFactorChunk(
                            first_session=window.research_sessions[0],
                            last_session=window.research_sessions[-1],
                            outcome_payload=outcome_payload,
                            completed_research_sessions=int(
                                alpha_continuation["completed_research_session_count"]
                            ),
                            final=window.final,
                        )
                    )
                    del outcome_payload, run_input, forward_labels, research_data
                    _release_chunk_memory()
                    if not window.final:
                        yield {
                            "status": "shared_alpha_factor_chunk_succeeded",
                            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
                            "task_role": "shared_alpha_factor",
                            "phase": "research",
                            "completed_research_sessions": int(
                                alpha_continuation["completed_research_session_count"]
                            ),
                            "total_research_sessions": plan.research_session_count,
                        }
                if final_alpha_continuation is None:
                    raise ResearchExecutionInputInvalid(
                        "Strategy Sweep shared Alpha-and-Factor task is incomplete"
                    )
                assert writer is not None
                metadata = writer.complete(final_alpha_continuation=final_alpha_continuation)
            except Exception:
                if writer is not None:
                    writer.abort()
                raise
        if binding is None or final_alpha_continuation is None or metadata is None:
            raise ResearchExecutionInputInvalid(
                "Strategy Sweep shared Alpha-and-Factor task is incomplete"
            )
        if metadata.chunk_count != len(research_windows):
            raise ResearchExecutionInputInvalid(
                "Strategy Sweep private artifact Chunk count is invalid"
            )
        if metadata.byte_size > shared_artifact_capacity_bytes:
            raise ResearchExecutionResourceExhausted(
                "Strategy Sweep private artifact exceeds its admitted capacity"
            )
        yield {
            "status": "shared_alpha_factor_succeeded",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_chunk_seconds": monotonic() - shared_started,
            "child_data_read_seconds": 0.0,
            "child_calculation_phase_seconds": phase_seconds,
            "shared_chunk_count": metadata.chunk_count,
            "shared_artifact_bytes": metadata.byte_size,
            "shared_artifact_capacity_bytes": shared_artifact_capacity_bytes,
            "private_artifact_path": str(private_artifact_path),
            "private_artifact_sha256": metadata.sha256,
            "private_artifact_reused": reuse_private_artifact,
            "private_artifact_binding": binding.value_snapshot(),
            "private_artifact_binding_checksum": binding.checksum,
            "alpha_factor_task_started": False,
            "alpha_factor_task_completed": True,
            "task_role": "shared_alpha_factor",
            "phase": "finalizing",
            "completed_research_sessions": plan.research_session_count,
            "total_research_sessions": plan.research_session_count,
        }
    except (MemoryError, ResearchExecutionResourceExhausted):
        raise
    except Exception as error:
        yield {
            "status": "shared_alpha_factor_failed",
            "category": "calculation",
            "message": "Shared Alpha-and-Factor calculation failed.",
            "error_type": type(error).__name__,
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "alpha_factor_task_started": False,
            "alpha_factor_task_failed": True,
            "strategy_task_started": False,
        }
        return

    assert binding is not None and final_alpha_continuation is not None
    for item in items:
        yield _task_started_message(item, task_role="strategy", phase="strategy")
        yield from _execute_strategy_item_messages(
            item,
            batch_id=batch_id,
            generation_id=generation_id,
            binding=binding,
            store=store,
            calendar=calendar,
            research_windows=research_windows,
            private_artifact_path=private_artifact_path,
            final_alpha_continuation=final_alpha_continuation,
            research_start=research_start,
            research_end=research_end,
        )


def _validate_strategy_shared_contract(
    items: Sequence[ResearchBatchExecutionItem],
) -> None:
    """Reject any persisted mutation outside the admitted Strategy tuple."""

    shared = items[0].immutable_input.canonical_value()
    shared.pop("strategy")
    for item in items[1:]:
        candidate = item.immutable_input.canonical_value()
        candidate.pop("strategy")
        if candidate != shared:
            raise ResearchExecutionInputInvalid(
                "Strategy Sweep shared Alpha-and-Factor contract is inconsistent"
            )


def _execute_strategy_item_messages(
    item: ResearchBatchExecutionItem,
    *,
    batch_id: str,
    generation_id: str,
    binding: AlphaFactorExecutionBinding,
    store: MountedGenerationStore,
    calendar: tuple[str, ...],
    research_windows: Sequence[_ResearchWindow],
    private_artifact_path: Path,
    final_alpha_continuation: Mapping[str, object],
    research_start: str,
    research_end: str,
) -> Iterator[dict[str, object]]:
    started = monotonic()
    strategy_continuation = empty_strategy_continuation()
    final_values: dict[str, object] | None = None
    data_read_seconds = 0.0
    strategy_seconds = 0.0
    finalize_seconds = 0.0
    try:
        with PrivateAlphaFactorArtifactReader(
            private_artifact_path,
            expected_batch_id=batch_id,
            expected_binding=binding,
            maximum_chunk_payload_bytes=(
                item.immutable_input.execution_plan.execution_memory_bytes
            ),
        ) as reader:
            for window, stored in zip(research_windows, reader, strict=True):
                _require_artifact_window(stored, window)
                data_read_started = monotonic()
                # Scores and Factor state are frozen in the shared artifact.
                # Load only execution facts, retaining the continuation context
                # and held instruments needed across Strategy window boundaries.
                research_data = _read_shared_window(
                    store,
                    generation_id=generation_id,
                    calendar=calendar,
                    research_sessions=window.research_sessions,
                    universe=item.immutable_input.universe,
                    neutralization="none",
                    field_bindings={},
                    effective_lookback=0,
                    fact_instrument_ids=_continuation_instrument_ids(strategy_continuation),
                )
                data_read_seconds += monotonic() - data_read_started
                alpha_factor_outcome = AlphaFactorChunkOutcome.from_compact_for_reuse(
                    stored.outcome_payload,
                    binding=binding,
                )
                run_input = _strategy_run_input(
                    item.immutable_input,
                    research_data,
                    research_start=research_start,
                    research_end=research_end,
                )
                outcome = execute_strategy_chunk_from_alpha_factor_outcome(
                    run_input=run_input,
                    binding=binding,
                    alpha_factor_outcome=alpha_factor_outcome,
                    research_data=research_data,
                    final_chunk=window.final,
                    continuation=strategy_continuation,
                    cancellation_check=lambda: None,
                )
                strategy_continuation = outcome.continuation_snapshot()
                observations = outcome.daily_observations_snapshot()
                final_values = outcome.final_values_snapshot()
                strategy_seconds += outcome.phase_seconds["strategy"]
                finalize_seconds += outcome.phase_seconds["finalize"]
                partition_path = _strategy_partition_path(
                    private_artifact_path,
                    item_ordinal=item.ordinal,
                    chunk_ordinal=window.ordinal,
                )
                _write_strategy_partition(partition_path, observations)
                partition = {
                    "chunk_ordinal": window.ordinal,
                    "path": str(partition_path),
                    "row_count": len(observations),
                    "first_session": observations[0]["session"],
                    "last_session": observations[-1]["session"],
                }
                completed_research_sessions = stored.completed_research_sessions
                del (
                    observations,
                    outcome,
                    run_input,
                    alpha_factor_outcome,
                    research_data,
                    stored,
                )
                _release_chunk_memory()
                yield {
                    "status": "item_strategy_chunk_succeeded",
                    "item_ordinal": item.ordinal,
                    "item_key": item.item_key,
                    "run_id": item.run_id,
                    "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
                    "task_role": "strategy",
                    "phase": "strategy",
                    "completed_research_sessions": completed_research_sessions,
                    "total_research_sessions": (
                        item.immutable_input.execution_plan.research_session_count
                    ),
                    "strategy_partition": partition,
                }
            if reader.final_alpha_continuation != dict(final_alpha_continuation):
                raise ValueError("Strategy Sweep private artifact continuation changed")
        if final_values is None:
            raise ValueError("Final Strategy Sweep outcome is incomplete")
        plan = item.immutable_input.execution_plan
        yield {
            "status": "item_succeeded",
            "item_ordinal": item.ordinal,
            "item_key": item.item_key,
            "run_id": item.run_id,
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_chunk_seconds": monotonic() - started,
            "child_data_read_seconds": data_read_seconds,
            "child_calculation_phase_seconds": {
                "input": 0.0,
                "alpha_and_pending": 0.0,
                "factor": 0.0,
                "strategy": strategy_seconds,
                "finalize": finalize_seconds,
            },
            "alpha_factor_task_started": False,
            "strategy_task_started": False,
            "strategy_task_completed": True,
            "task_role": "strategy",
            "phase": "finalizing",
            "completed_research_sessions": plan.research_session_count,
            "total_research_sessions": plan.research_session_count,
            "chunk": {
                "ordinal": len(plan.chunks),
                "boundary_session": plan.chunks[-1].last_session.isoformat(),
                "phase": "research",
                "completed_warmup_sessions": plan.research_session_offset,
                "completed_research_sessions": int(
                    final_alpha_continuation["completed_research_session_count"]
                ),
                "continuation": {
                    "schema_version": "research-chunk-continuation-v2",
                    "research_kind": "strategy_backtest",
                    **final_alpha_continuation,
                    **strategy_continuation,
                },
                "strategy_daily_observations": [],
                "final_values": final_values,
                "final": True,
                "reused_checkpoint": False,
            },
        }
    except (MemoryError, ResearchExecutionResourceExhausted):
        raise
    except Exception as error:
        yield {
            "status": "item_failed",
            "category": "calculation",
            "message": "Strategy item calculation failed.",
            "error_type": type(error).__name__,
            "item_ordinal": item.ordinal,
            "item_key": item.item_key,
            "run_id": item.run_id,
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "alpha_factor_task_started": False,
            "strategy_task_started": False,
            "strategy_task_failed": True,
        }


def _read_shared_window(
    store: MountedGenerationStore,
    *,
    generation_id: str,
    calendar: tuple[str, ...],
    research_sessions: tuple[str, ...],
    universe: str,
    neutralization: str | None,
    field_bindings: Mapping[str, str],
    effective_lookback: int,
    fact_instrument_ids: frozenset[str],
) -> _SharedFactorResearchData:
    first_index = calendar.index(research_sessions[0])
    context_start = max(0, first_index - max(effective_lookback, 21, 2))
    context_sessions = calendar[context_start : calendar.index(research_sessions[-1]) + 1]
    source = store.read_columnar_slice(
        generation_id,
        sessions=list(context_sessions),
        universe_name=universe,
        neutralization=neutralization,
        field_bindings=field_bindings,
        fact_instrument_ids=fact_instrument_ids,
    )
    return _SharedFactorResearchData(
        source,
        field_ids=tuple(field_bindings),
    )


def _factor_run_input(
    immutable_input: ImmutableRunInput,
    research_data: _SharedFactorResearchData,
) -> RunInput:
    if immutable_input.research_kind != "factor_evaluation":
        raise ResearchExecutionInputInvalid("Factor Batch item input is invalid")
    return RunInput(
        research_data=research_data,
        alpha_expression=immutable_input.alpha_expression,
        field_bindings=immutable_input.field_bindings,
        effective_alpha_lookback=immutable_input.alpha_admission.effective_lookback,
        universe=immutable_input.universe,
        neutralization=immutable_input.neutralization,
        research_kind="factor_evaluation",
        strategy=None,
        research_start_session=(immutable_input.data_admission.first_research_session.isoformat()),
        research_end_session=(immutable_input.data_admission.last_research_session.isoformat()),
    )


def _require_artifact_window(
    stored: PrivateAlphaFactorChunk,
    window: _ResearchWindow,
) -> None:
    if (
        stored.first_session != window.research_sessions[0]
        or stored.last_session != window.research_sessions[-1]
        or stored.final is not window.final
    ):
        raise ResearchExecutionInputInvalid(
            "Strategy Sweep private artifact Chunk boundary is invalid"
        )


def _strategy_partition_path(
    private_artifact_path: Path,
    *,
    item_ordinal: int,
    chunk_ordinal: int,
) -> Path:
    return private_artifact_path.with_name(
        f"{private_artifact_path.name}.strategy-{item_ordinal:03d}-{chunk_ordinal:06d}.parquet"
    )


def _write_strategy_partition(
    path: Path,
    observations: Sequence[Mapping[str, object]],
) -> None:
    if not observations:
        raise ResearchExecutionInputInvalid("Strategy output partition is empty")
    partial = path.with_name(f"{path.name}.partial")
    if path.exists() or partial.exists():
        raise ResearchExecutionInputInvalid("Strategy output partition path is not empty")
    content = parquet_bytes(observations, STRATEGY_DAILY_OBSERVATIONS_CONTRACT)
    try:
        with partial.open("xb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


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


def _empty_phase_seconds() -> dict[str, float]:
    return {
        "input": 0.0,
        "alpha_and_pending": 0.0,
        "factor": 0.0,
        "strategy": 0.0,
        "finalize": 0.0,
    }


def _item_failed_message(
    item: ResearchBatchExecutionItem,
    error: Exception,
    *,
    task_role: str,
) -> dict[str, object]:
    return {
        "status": "item_failed",
        "category": "calculation",
        "message": f"{task_role.title()} item calculation failed.",
        "error_type": type(error).__name__,
        "item_ordinal": item.ordinal,
        "item_key": item.item_key,
        "run_id": item.run_id,
        "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        "alpha_factor_task_started": False,
        "alpha_factor_task_failed": task_role == "factor",
        "strategy_task_started": False,
        "strategy_task_failed": task_role == "strategy",
        "task_role": task_role,
        "phase": "finalizing",
        "completed_research_sessions": 0,
        "total_research_sessions": (item.immutable_input.execution_plan.research_session_count),
    }


def _strategy_run_input(
    immutable_input: ImmutableRunInput,
    research_data: _SharedFactorResearchData,
    *,
    research_start: str,
    research_end: str,
) -> RunInput:
    strategy = immutable_input.strategy
    costs = immutable_input.costs
    if immutable_input.research_kind != "strategy_backtest" or strategy is None or costs is None:
        raise ResearchExecutionInputInvalid("Strategy Sweep item input is incomplete")
    return RunInput(
        research_data=research_data,
        alpha_expression=immutable_input.alpha_expression,
        field_bindings=immutable_input.field_bindings,
        effective_alpha_lookback=immutable_input.alpha_admission.effective_lookback,
        universe=immutable_input.universe,
        neutralization=immutable_input.neutralization,
        research_kind="strategy_backtest",
        strategy=StrategyRunInput(
            holdings_count=int(strategy["holdings_count"]),
            rebalance_interval=int(strategy["rebalance_every_sessions"]),
            initial_cash_cny=str(strategy["initial_cash_cny"]),
            commission_rate_all_in=str(costs["commission_rate_all_in"]),
            commission_min_cny=str(costs["commission_min_cny"]),
            stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
            transfer_fee_rate=str(costs["transfer_fee_rate"]),
        ),
        research_start_session=research_start,
        research_end_session=research_end,
    )


def _read_message(
    transport: SupervisedChildTransport,
    *,
    execution_memory_bytes: int,
    cancel_requested: CancellationCheck,
) -> dict[str, object]:
    try:
        message = transport.read(cancel_requested=cancel_requested)
    except ChildTransportCgroupOom as error:
        raise ResearchExecutionResourceExhausted(
            "Research Batch child exceeded its cgroup memory limit"
        ) from error
    except ChildTransportError as error:
        detail = _child_stderr_detail(transport.process)
        raise ResearchBatchChildLost(f"{error}{detail}") from error
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
        "child_ready",
        "batch_prepared",
        "shared_alpha_factor_started",
        "shared_alpha_factor_chunk_succeeded",
        "shared_alpha_factor_succeeded",
        "shared_alpha_factor_failed",
        "item_succeeded",
        "item_started",
        "item_strategy_chunk_succeeded",
        "item_chunk_succeeded",
        "item_failed",
        "batch_succeeded",
    }:
        raise ResearchExecutionError("Research Batch child response is invalid")
    return message


def _task_started_message(
    item: ResearchBatchExecutionItem,
    *,
    task_role: str,
    phase: str,
) -> dict[str, object]:
    return {
        "status": "item_started",
        "item_ordinal": item.ordinal,
        "item_key": item.item_key,
        "run_id": item.run_id,
        "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        "task_role": task_role,
        "phase": phase,
        "alpha_factor_task_started": task_role == "factor",
        "strategy_task_started": task_role == "strategy",
        "completed_research_sessions": 0,
        "total_research_sessions": item.immutable_input.execution_plan.research_session_count,
    }


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

from __future__ import annotations

import hashlib
import resource
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import numpy as np

from thesistrace.data import GenerationStoreError, MountedGenerationStore
from thesistrace.research_batch.models import ResearchBatchKind
from thesistrace.research_batch.planning import (
    strategy_sweep_encoded_outcome_cell_count,
    strategy_sweep_private_artifact_capacity_bytes,
)
from thesistrace.research_batch.private_artifact import (
    PrivateAlphaFactorChunk,
    decode_private_alpha_factor_artifact,
    encode_private_alpha_factor_artifact,
)
from thesistrace.research_kernel.factor import (
    PreparedColumnarForwardLabels,
    prepare_columnar_forward_labels,
)
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
from thesistrace.research_run.models import ImmutableRunInput, ResearchExecutionChunk
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
class _SharedStrategyChunk:
    research_data: _SharedFactorResearchData
    outcome_payload: bytes
    completed_research_sessions: int
    final: bool


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
                    "schema_version": "research-batch-child-request-v1",
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
        if value.get("schema_version") != "research-batch-child-request-v1":
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
        if batch_kind == "strategy_sweep":
            yield from _execute_strategy_sweep_messages(
                items,
                batch_id=batch_id,
                generation_id=generation_id,
                research_data=research_data,
                forward_labels=forward_labels,
                private_artifact_path=private_artifact_path,
                reuse_private_artifact=reuse_private_artifact,
            )
            yield {
                "status": "batch_succeeded",
                "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            }
            return
        for item in items:
            yield _task_started_message(item, task_role="factor", phase="research")
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


def _shared_sessions(
    items: Sequence[ResearchBatchExecutionItem],
    calendar: tuple[str, ...],
) -> tuple[str, ...]:
    first = min(
        item.immutable_input.execution_plan.calculation_sessions[0].isoformat() for item in items
    )
    last = max(
        item.immutable_input.execution_plan.calculation_sessions[-1].isoformat() for item in items
    )
    return calendar[calendar.index(first) : calendar.index(last) + 1]


def _execute_item_messages(
    item: ResearchBatchExecutionItem,
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
            context_sessions = calendar[context_start : calendar.index(research_sessions[-1]) + 1]
            item_data = research_data.slice_sessions(tuple(context_sessions))
            input_started = monotonic()
            run_input = RunInput(
                research_data=item_data,
                alpha_expression=immutable_input.alpha_expression,
                field_bindings=immutable_input.field_bindings,
                effective_alpha_lookback=(immutable_input.alpha_admission.effective_lookback),
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
            "task_role": "factor",
            "phase": "research" if research_sessions else "warmup",
            "completed_research_sessions": int(continuation["completed_research_session_count"]),
            "total_research_sessions": plan.research_session_count,
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


def _execute_strategy_sweep_messages(
    items: Sequence[ResearchBatchExecutionItem],
    *,
    batch_id: str,
    generation_id: str,
    research_data: _SharedFactorResearchData,
    forward_labels: PreparedColumnarForwardLabels,
    private_artifact_path: Path,
    reuse_private_artifact: bool,
) -> Iterator[dict[str, object]]:
    shared_input = items[0].immutable_input
    plan = shared_input.execution_plan
    research_start = shared_input.data_admission.first_research_session.isoformat()
    research_end = shared_input.data_admission.last_research_session.isoformat()
    alpha_continuation = empty_alpha_factor_continuation()
    binding: AlphaFactorExecutionBinding | None = None
    shared_chunks: list[_SharedStrategyChunk] = []
    shared_artifact_bytes = 0
    shared_artifact_capacity_bytes = strategy_sweep_private_artifact_capacity_bytes(
        encoded_outcome_cell_count=strategy_sweep_encoded_outcome_cell_count(
            research_session_counts=tuple(chunk.research_session_count for chunk in plan.chunks),
            maximum_universe_cardinality=max(
                item.immutable_input.data_admission.universe_instrument_count for item in items
            ),
        ),
        chunk_count=len(plan.chunks),
    )
    final_alpha_continuation: dict[str, object] | None = None
    phase_seconds = {
        "input": 0.0,
        "alpha_and_pending": 0.0,
        "factor": 0.0,
        "strategy": 0.0,
        "finalize": 0.0,
    }
    shared_started = monotonic()
    yield {
        "status": "shared_alpha_factor_started",
        "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
        "task_role": "shared_alpha_factor",
        "phase": "research",
        "completed_research_sessions": 0,
        "total_research_sessions": plan.research_session_count,
    }
    try:
        _validate_strategy_shared_contract(items)
        research_chunks = tuple(
            (chunk, sessions)
            for chunk in plan.chunks
            if (
                sessions := _research_sessions_for_chunk(
                    shared_input,
                    chunk,
                    research_start=research_start,
                    research_end=research_end,
                )
            )
        )
        if not research_chunks:
            raise ResearchExecutionInputInvalid(
                "Strategy Sweep shared Alpha-and-Factor plan is empty"
            )
        _first_chunk, first_sessions = research_chunks[0]
        first_data = _context_data(
            research_data,
            first_sessions,
            effective_lookback=shared_input.alpha_admission.effective_lookback,
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
        if reuse_private_artifact:
            artifact = decode_private_alpha_factor_artifact(
                private_artifact_path.read_bytes(),
                expected_batch_id=batch_id,
                expected_binding=binding,
            )
            if len(artifact.chunks) != len(research_chunks):
                raise ResearchExecutionInputInvalid(
                    "Strategy Sweep private artifact Chunk count is invalid"
                )
            for (_plan_chunk, sessions), stored in zip(
                research_chunks,
                artifact.chunks,
                strict=True,
            ):
                item_data = _context_data(
                    research_data,
                    sessions,
                    effective_lookback=shared_input.alpha_admission.effective_lookback,
                )
                shared_chunks.append(
                    _SharedStrategyChunk(
                        research_data=item_data,
                        outcome_payload=stored.outcome_payload,
                        completed_research_sessions=stored.completed_research_sessions,
                        final=stored.final,
                    )
                )
            final_alpha_continuation = artifact.final_alpha_continuation
            shared_artifact_bytes = len(artifact.content)
            del artifact
        else:
            for chunk, research_sessions in research_chunks:
                item_data = _context_data(
                    research_data,
                    research_sessions,
                    effective_lookback=shared_input.alpha_admission.effective_lookback,
                )
                input_started = monotonic()
                run_input = _strategy_run_input(
                    shared_input,
                    item_data,
                    research_start=research_start,
                    research_end=research_end,
                )
                phase_seconds["input"] += monotonic() - input_started
                final_chunk = chunk == research_chunks[-1][0]
                outcome = execute_alpha_factor_chunk(
                    run_input=run_input,
                    binding=binding,
                    research_data=item_data,
                    forward_labels=forward_labels,
                    research_sessions=research_sessions,
                    final_chunk=final_chunk,
                    continuation=alpha_continuation,
                    cancellation_check=lambda: None,
                )
                alpha_continuation = outcome.continuation_snapshot()
                final_alpha_continuation = alpha_continuation
                for name in ("alpha_and_pending", "factor", "finalize"):
                    phase_seconds[name] += outcome.phase_seconds[name]
                outcome_payload = outcome.compact_for_reuse()
                shared_chunks.append(
                    _SharedStrategyChunk(
                        research_data=item_data,
                        outcome_payload=outcome_payload,
                        completed_research_sessions=int(
                            alpha_continuation["completed_research_session_count"]
                        ),
                        final=final_chunk,
                    )
                )
                del outcome
                if not final_chunk:
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
            if final_alpha_continuation is not None:
                artifact_content = encode_private_alpha_factor_artifact(
                    batch_id=batch_id,
                    binding=binding,
                    chunks=tuple(
                        PrivateAlphaFactorChunk(
                            outcome_payload=chunk.outcome_payload,
                            completed_research_sessions=chunk.completed_research_sessions,
                            final=chunk.final,
                        )
                        for chunk in shared_chunks
                    ),
                    final_alpha_continuation=final_alpha_continuation,
                )
                if len(artifact_content) > shared_artifact_capacity_bytes:
                    raise MemoryError
                private_artifact_path.write_bytes(artifact_content)
                shared_artifact_bytes = len(artifact_content)
        if binding is None or not shared_chunks or not shared_chunks[-1].final:
            raise ResearchExecutionInputInvalid(
                "Strategy Sweep shared Alpha-and-Factor task is incomplete"
            )
        yield {
            "status": "shared_alpha_factor_succeeded",
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "child_chunk_seconds": monotonic() - shared_started,
            "child_data_read_seconds": 0.0,
            "child_calculation_phase_seconds": phase_seconds,
            "shared_chunk_count": len(shared_chunks),
            "shared_artifact_bytes": shared_artifact_bytes,
            "shared_artifact_capacity_bytes": shared_artifact_capacity_bytes,
            "private_artifact_path": str(private_artifact_path),
            "private_artifact_sha256": hashlib.sha256(
                private_artifact_path.read_bytes()
            ).hexdigest(),
            "private_artifact_reused": reuse_private_artifact,
            "private_artifact_binding": binding.value_snapshot(),
            "private_artifact_binding_checksum": binding.checksum,
            "alpha_factor_task_started": True,
            "alpha_factor_task_completed": True,
            "task_role": "shared_alpha_factor",
            "phase": "finalizing",
            "completed_research_sessions": plan.research_session_count,
            "total_research_sessions": plan.research_session_count,
        }
    except MemoryError:
        raise
    except Exception as error:
        yield {
            "status": "shared_alpha_factor_failed",
            "category": "calculation",
            "message": "Shared Alpha-and-Factor calculation failed.",
            "error_type": type(error).__name__,
            "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
            "alpha_factor_task_started": True,
            "alpha_factor_task_failed": True,
            "strategy_task_started": False,
        }
        return

    assert binding is not None and final_alpha_continuation is not None
    for item in items:
        yield _task_started_message(item, task_role="strategy", phase="strategy")
        yield from _execute_strategy_item_messages(
            item,
            binding=binding,
            shared_chunks=shared_chunks,
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
    binding: AlphaFactorExecutionBinding,
    shared_chunks: Sequence[_SharedStrategyChunk],
    final_alpha_continuation: Mapping[str, object],
    research_start: str,
    research_end: str,
) -> Iterator[dict[str, object]]:
    started = monotonic()
    strategy_continuation = empty_strategy_continuation()
    observations: list[dict[str, object]] = []
    final_values: dict[str, object] | None = None
    strategy_seconds = 0.0
    finalize_seconds = 0.0
    try:
        for shared in shared_chunks:
            alpha_factor_outcome = AlphaFactorChunkOutcome.from_compact_for_reuse(
                shared.outcome_payload,
                binding=binding,
            )
            run_input = _strategy_run_input(
                item.immutable_input,
                shared.research_data,
                research_start=research_start,
                research_end=research_end,
            )
            outcome = execute_strategy_chunk_from_alpha_factor_outcome(
                run_input=run_input,
                binding=binding,
                alpha_factor_outcome=alpha_factor_outcome,
                research_data=shared.research_data,
                final_chunk=shared.final,
                continuation=strategy_continuation,
                cancellation_check=lambda: None,
            )
            del alpha_factor_outcome
            strategy_continuation = outcome.continuation_snapshot()
            observations.extend(outcome.daily_observations_snapshot())
            final_values = outcome.final_values_snapshot()
            strategy_seconds += outcome.phase_seconds["strategy"]
            finalize_seconds += outcome.phase_seconds["finalize"]
            if not shared.final:
                yield {
                    "status": "item_strategy_chunk_succeeded",
                    "item_ordinal": item.ordinal,
                    "item_key": item.item_key,
                    "run_id": item.run_id,
                    "child_peak_rss_bytes": _current_process_peak_rss_bytes(),
                    "task_role": "strategy",
                    "phase": "strategy",
                    "completed_research_sessions": shared.completed_research_sessions,
                    "total_research_sessions": (
                        item.immutable_input.execution_plan.research_session_count
                    ),
                }
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
            "child_data_read_seconds": 0.0,
            "child_calculation_phase_seconds": {
                "input": 0.0,
                "alpha_and_pending": 0.0,
                "factor": 0.0,
                "strategy": strategy_seconds,
                "finalize": finalize_seconds,
            },
            "alpha_factor_task_started": False,
            "strategy_task_started": True,
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
                "strategy_daily_observations": observations,
                "final_values": final_values,
                "final": True,
                "reused_checkpoint": False,
            },
        }
    except MemoryError:
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
            "strategy_task_started": True,
            "strategy_task_failed": True,
        }


def _research_sessions_for_chunk(
    immutable_input: ImmutableRunInput,
    chunk: ResearchExecutionChunk,
    *,
    research_start: str,
    research_end: str,
) -> tuple[str, ...]:
    return tuple(
        session.isoformat()
        for session in immutable_input.execution_plan.calculation_sessions
        if chunk.first_session <= session <= chunk.last_session
        and research_start <= session.isoformat() <= research_end
    )


def _context_data(
    research_data: _SharedFactorResearchData,
    research_sessions: tuple[str, ...],
    *,
    effective_lookback: int,
) -> _SharedFactorResearchData:
    calendar = tuple(research_data.sessions)
    first_index = calendar.index(research_sessions[0])
    context_start = max(0, first_index - max(effective_lookback, 21, 2))
    context_sessions = calendar[context_start : calendar.index(research_sessions[-1]) + 1]
    return research_data.slice_sessions(tuple(context_sessions))


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

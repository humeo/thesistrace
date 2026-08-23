from __future__ import annotations

from collections.abc import Sequence

from thesistrace.research_batch.models import ResearchBatchKind
from thesistrace.research_kernel.capacity import SessionCapacityPlan
from thesistrace.research_run.service import PreparedResearchRunAdmission

# The Batch child retains the complete Arrow source, coordinate indexes, dense
# numeric views, Python Decimal execution prices, Universe tuples, and Forward
# Labels while one ordinary bounded chunk is calculated. These deliberately
# conservative per-cell allowances cover both Arrow buffers and Python object
# ownership; the ordinary execution estimate supplies interpreter/process and
# current-chunk working memory.
STRATEGY_SWEEP_PRIVATE_ARTIFACT_COLUMNS = 4
_BINARY64_BYTES = 8
_ARROW_SOURCE_AND_COORDINATE_BYTES = 256
_DECIMAL_OPEN_OBJECT_BYTES = 128
_UNIVERSE_MEMBER_BYTES = 32
_ADJUSTED_OPEN_COLUMNS = 1
_FORWARD_LABEL_COLUMNS = 3
_FORWARD_LABEL_STATE_BYTES = 3
_UNIVERSE_MASK_BYTES = 1
_BATCH_PROCESS_RUNTIME_MARGIN_BYTES = 96 * 1024**2


class ResearchBatchCapacityError(ValueError):
    pass


def validate_research_batch_capacity(
    batch_kind: ResearchBatchKind,
    children: Sequence[PreparedResearchRunAdmission],
) -> SessionCapacityPlan:
    if not children:
        raise ValueError("Research Batch capacity requires child Runs")
    inputs = [child.immutable_input for child in children]
    first = inputs[0]
    execution_memory_bytes = first.execution_plan.execution_memory_bytes
    if any(
        value.execution_plan.execution_memory_bytes != execution_memory_bytes
        or value.data_admission.generation_manifest_sha256
        != first.data_admission.generation_manifest_sha256
        or value.requested_start_date != first.requested_start_date
        or value.requested_end_date != first.requested_end_date
        or value.universe != first.universe
        or value.neutralization != first.neutralization
        for value in inputs[1:]
    ):
        raise ValueError("Research Batch child scope is inconsistent")
    field_ids = {field_id for value in inputs for field_id in value.field_bindings}
    calculation_session_count = max(
        value.data_admission.calculation_session_count for value in inputs
    )
    maximum_universe_cardinality = max(
        value.data_admission.universe_instrument_count for value in inputs
    )
    resident_cell_count = calculation_session_count * maximum_universe_cardinality
    resident_bytes = resident_cell_count * (
        _ARROW_SOURCE_AND_COORDINATE_BYTES
        + _DECIMAL_OPEN_OBJECT_BYTES
        + _UNIVERSE_MEMBER_BYTES
        + _BINARY64_BYTES
        * (len(field_ids) + _ADJUSTED_OPEN_COLUMNS + _FORWARD_LABEL_COLUMNS)
        + _FORWARD_LABEL_STATE_BYTES
        + _UNIVERSE_MASK_BYTES
    )
    ordinary_chunk_peak_bytes = max(
        value.execution_plan.estimated_peak_bytes for value in inputs
    )
    strategy_private_bytes = (
        resident_cell_count
        * _BINARY64_BYTES
        * STRATEGY_SWEEP_PRIVATE_ARTIFACT_COLUMNS
        if batch_kind == "strategy_sweep"
        else 0
    )
    estimated_peak_bytes = (
        ordinary_chunk_peak_bytes
        + _BATCH_PROCESS_RUNTIME_MARGIN_BYTES
        + resident_bytes
        + strategy_private_bytes
    )
    if estimated_peak_bytes > execution_memory_bytes:
        raise ResearchBatchCapacityError(
            "Worker capacity cannot retain the complete shared Batch data and Forward Labels"
        )
    return SessionCapacityPlan(
        session_count=min(
            value.execution_plan.chunk_session_count for value in inputs
        ),
        time_target_exceeded=any(
            value.execution_plan.time_target_exceeded for value in inputs
        ),
        estimated_peak_bytes=estimated_peak_bytes,
        estimated_work=max(
            value.execution_plan.estimated_chunk_work for value in inputs
        ),
    )

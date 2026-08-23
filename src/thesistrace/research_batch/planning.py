from __future__ import annotations

from collections.abc import Sequence

from thesistrace.research_batch.models import ResearchBatchKind
from thesistrace.research_kernel.capacity import (
    SessionCapacityError,
    SessionCapacityPlan,
    plan_session_capacity,
)
from thesistrace.research_run.service import PreparedResearchRunAdmission

# While one Strategy uses the ordinary live-state allowance, a Sweep also retains
# one serialization copy of the shared Alpha, Universe mask, Forward Return, and
# Factor bucket until the private artifact is durably acknowledged.
STRATEGY_SWEEP_PRIVATE_ARTIFACT_COLUMNS = 4


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
    try:
        return plan_session_capacity(
            formula_work=max(value.alpha_admission.formula_work for value in inputs),
            node_count=max(value.alpha_admission.node_count for value in inputs),
            field_count=len(field_ids),
            maximum_universe_cardinality=max(
                value.data_admission.universe_instrument_count for value in inputs
            ),
            effective_lookback=max(
                value.alpha_admission.effective_lookback for value in inputs
            ),
            execution_memory_bytes=execution_memory_bytes,
            additional_live_columns=(
                STRATEGY_SWEEP_PRIVATE_ARTIFACT_COLUMNS
                if batch_kind == "strategy_sweep"
                else 0
            ),
        )
    except SessionCapacityError as error:
        raise ResearchBatchCapacityError(str(error)) from error

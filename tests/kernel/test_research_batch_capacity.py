from datetime import date
from types import SimpleNamespace

import pytest

from thesistrace.research_batch.planning import (
    ResearchBatchCapacityError,
    validate_research_batch_capacity,
)


def test_factor_batch_capacity_accounts_for_union_of_field_bindings() -> None:
    execution_memory_bytes = 512 * 1024**2
    close = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=execution_memory_bytes,
    )
    open_ = _prepared_child(
        field_id="price.open.adjusted",
        execution_memory_bytes=execution_memory_bytes,
    )

    close_plan = validate_research_batch_capacity("factor_evaluation", [close])
    open_plan = validate_research_batch_capacity("factor_evaluation", [open_])
    union_plan = validate_research_batch_capacity(
        "factor_evaluation", [close, open_]
    )

    assert union_plan.estimated_peak_bytes > close_plan.estimated_peak_bytes
    assert union_plan.estimated_peak_bytes > open_plan.estimated_peak_bytes


def test_strategy_sweep_capacity_accounts_for_private_artifact_copy() -> None:
    strategy = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=512 * 1024**2,
    )

    factor = validate_research_batch_capacity("factor_evaluation", [strategy])
    sweep = validate_research_batch_capacity("strategy_sweep", [strategy])

    assert sweep.estimated_peak_bytes > factor.estimated_peak_bytes


def test_factor_batch_capacity_rejects_a_long_shared_resident_slice() -> None:
    child = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=512 * 1024**2,
        calculation_session_count=8_000,
    )

    with pytest.raises(
        ResearchBatchCapacityError,
        match="complete shared Batch data and Forward Labels",
    ):
        validate_research_batch_capacity("factor_evaluation", [child])


def test_factor_batch_capacity_has_a_deterministic_widest_admitted_slice() -> None:
    memory_bytes = 200 * 1024**2
    ordinary_peak_bytes = 95_322_112
    admitted = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=memory_bytes,
        calculation_session_count=58,
        maximum_universe_cardinality=512,
        estimated_peak_bytes=ordinary_peak_bytes,
    )
    one_session_wider = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=memory_bytes,
        calculation_session_count=59,
        maximum_universe_cardinality=512,
        estimated_peak_bytes=ordinary_peak_bytes,
    )

    plan = validate_research_batch_capacity("factor_evaluation", [admitted])

    assert plan.estimated_peak_bytes <= memory_bytes
    with pytest.raises(
        ResearchBatchCapacityError,
        match="complete shared Batch data and Forward Labels",
    ):
        validate_research_batch_capacity("factor_evaluation", [one_session_wider])


def _prepared_child(
    *,
    field_id: str,
    execution_memory_bytes: int,
    calculation_session_count: int = 2,
    maximum_universe_cardinality: int = 3_000,
    estimated_peak_bytes: int = 80 * 1024**2,
) -> SimpleNamespace:
    return SimpleNamespace(
        immutable_input=SimpleNamespace(
            execution_plan=SimpleNamespace(
                execution_memory_bytes=execution_memory_bytes,
                estimated_peak_bytes=estimated_peak_bytes,
                chunk_session_count=4,
                time_target_exceeded=False,
                estimated_chunk_work=100,
            ),
            data_admission=SimpleNamespace(
                generation_manifest_sha256="a" * 64,
                universe_instrument_count=maximum_universe_cardinality,
                calculation_session_count=calculation_session_count,
            ),
            requested_start_date=date(2026, 8, 3),
            requested_end_date=date(2026, 8, 4),
            universe="top3000",
            neutralization="none",
            field_bindings={field_id: object()},
            alpha_admission=SimpleNamespace(
                formula_work=1,
                node_count=1,
                effective_lookback=0,
            ),
        )
    )

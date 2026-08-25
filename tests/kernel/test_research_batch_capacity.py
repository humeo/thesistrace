from datetime import date
from types import SimpleNamespace

import pytest

from thesistrace.research_batch.planning import (
    ResearchBatchCapacityError,
    strategy_sweep_encoded_outcome_cell_count,
    strategy_sweep_private_artifact_capacity_bytes,
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


def test_strategy_sweep_capacity_has_a_deterministic_multi_chunk_boundary() -> None:
    memory_bytes = 512 * 1024**2
    ordinary_peak_bytes = 96 * 1024**2
    maximum_universe_cardinality = 512
    admitted_count = 0
    for session_count in range(1, 2_001):
        child = _prepared_child(
            field_id="price.close.adjusted",
            execution_memory_bytes=memory_bytes,
            calculation_session_count=session_count,
            maximum_universe_cardinality=maximum_universe_cardinality,
            estimated_peak_bytes=ordinary_peak_bytes,
        )
        try:
            validate_research_batch_capacity("strategy_sweep", [child])
        except ResearchBatchCapacityError:
            break
        admitted_count = session_count

    assert admitted_count > 64
    admitted = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=memory_bytes,
        calculation_session_count=admitted_count,
        maximum_universe_cardinality=maximum_universe_cardinality,
        estimated_peak_bytes=ordinary_peak_bytes,
    )
    rejected = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=memory_bytes,
        calculation_session_count=admitted_count + 1,
        maximum_universe_cardinality=maximum_universe_cardinality,
        estimated_peak_bytes=ordinary_peak_bytes,
    )

    plan = validate_research_batch_capacity("strategy_sweep", [admitted])

    assert plan.estimated_peak_bytes <= memory_bytes
    encoded_cell_count = strategy_sweep_encoded_outcome_cell_count(
        research_session_counts=tuple(
            chunk.research_session_count for chunk in admitted.immutable_input.execution_plan.chunks
        ),
        maximum_universe_cardinality=maximum_universe_cardinality,
    )
    assert strategy_sweep_private_artifact_capacity_bytes(
        encoded_outcome_cell_count=encoded_cell_count,
        chunk_count=(admitted_count + 3) // 4,
    ) > 0
    with pytest.raises(ResearchBatchCapacityError):
        validate_research_batch_capacity("strategy_sweep", [rejected])


def test_strategy_sweep_capacity_prices_pending_overlap_for_small_chunks() -> None:
    common = {
        "field_id": "price.close.adjusted",
        "execution_memory_bytes": 1024 * 1024**2,
        "calculation_session_count": 100,
        "maximum_universe_cardinality": 512,
        "estimated_peak_bytes": 96 * 1024**2,
    }
    one_session_chunks = _prepared_child(**common, chunk_session_count=1)
    sixty_four_session_chunks = _prepared_child(**common, chunk_session_count=64)

    small_chunk_plan = validate_research_batch_capacity(
        "strategy_sweep",
        [one_session_chunks],
    )
    large_chunk_plan = validate_research_batch_capacity(
        "strategy_sweep",
        [sixty_four_session_chunks],
    )

    assert small_chunk_plan.estimated_peak_bytes > large_chunk_plan.estimated_peak_bytes


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
    chunk_session_count: int = 4,
) -> SimpleNamespace:
    research_session_counts = tuple(
        min(chunk_session_count, calculation_session_count - start)
        for start in range(0, calculation_session_count, chunk_session_count)
    )
    return SimpleNamespace(
        immutable_input=SimpleNamespace(
            execution_plan=SimpleNamespace(
                execution_memory_bytes=execution_memory_bytes,
                estimated_peak_bytes=estimated_peak_bytes,
                chunk_session_count=chunk_session_count,
                time_target_exceeded=False,
                estimated_chunk_work=100,
                chunks=tuple(
                    SimpleNamespace(research_session_count=count)
                    for count in research_session_counts
                ),
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

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from functools import cache
from types import SimpleNamespace

from thesistrace.research_batch.planning import (
    rechunk_research_execution_plan,
    validate_research_batch_capacity,
)
from thesistrace.research_run.models import ResearchExecutionChunk, ResearchExecutionPlan


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

    close_plan = _validate_research_batch_capacity("factor_evaluation", [close])
    open_plan = _validate_research_batch_capacity("factor_evaluation", [open_])
    union_plan = _validate_research_batch_capacity("factor_evaluation", [close, open_])

    assert union_plan.estimated_peak_bytes > close_plan.estimated_peak_bytes
    assert union_plan.estimated_peak_bytes > open_plan.estimated_peak_bytes


def test_strategy_sweep_capacity_accounts_for_private_artifact_copy() -> None:
    strategy = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=512 * 1024**2,
    )

    factor = _validate_research_batch_capacity("factor_evaluation", [strategy])
    sweep = _validate_research_batch_capacity("strategy_sweep", [strategy])

    assert sweep.estimated_peak_bytes > factor.estimated_peak_bytes


def test_strategy_sweep_capacity_prices_one_streamed_artifact_chunk() -> None:
    short = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=512 * 1024**2,
        calculation_session_count=64,
        maximum_universe_cardinality=512,
        estimated_peak_bytes=96 * 1024**2,
    )
    long = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=512 * 1024**2,
        calculation_session_count=2_000,
        maximum_universe_cardinality=512,
        estimated_peak_bytes=96 * 1024**2,
    )

    short_plan = _validate_research_batch_capacity("strategy_sweep", [short])
    long_plan = _validate_research_batch_capacity("strategy_sweep", [long])

    assert long_plan.estimated_peak_bytes == short_plan.estimated_peak_bytes


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

    small_chunk_plan = _validate_research_batch_capacity(
        "strategy_sweep",
        [one_session_chunks],
    )
    large_chunk_plan = _validate_research_batch_capacity(
        "strategy_sweep",
        [sixty_four_session_chunks],
    )

    assert small_chunk_plan.estimated_peak_bytes < large_chunk_plan.estimated_peak_bytes


def test_factor_batch_capacity_peak_is_bounded_by_chunk_not_total_history() -> None:
    short = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=512 * 1024**2,
        calculation_session_count=64,
    )
    long = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=512 * 1024**2,
        calculation_session_count=8_000,
    )

    short_plan = _validate_research_batch_capacity("factor_evaluation", [short])
    long_plan = _validate_research_batch_capacity("factor_evaluation", [long])

    assert long_plan.estimated_peak_bytes == short_plan.estimated_peak_bytes


def test_factor_batch_capacity_selects_a_smaller_chunk_for_membership_churn() -> None:
    child = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=256 * 1024**2,
        calculation_session_count=200,
        maximum_universe_cardinality=100,
        estimated_peak_bytes=80 * 1024**2,
        chunk_session_count=64,
    )

    plan = _validate_research_batch_capacity(
        "factor_evaluation",
        [child],
        union_cardinality=lambda window: len(window) * 100,
    )

    assert 1 <= plan.session_count < 64
    assert plan.estimated_peak_bytes <= 256 * 1024**2


def test_eleven_year_rotating_top300_never_measures_a_full_history_slice() -> None:
    child = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=1536 * 1024**2,
        calculation_session_count=2_843,
        maximum_universe_cardinality=300,
        estimated_peak_bytes=96 * 1024**2,
        chunk_session_count=64,
    )
    observed_windows: list[tuple[date, ...]] = []
    observed_cardinalities: list[int] = []
    first = date(1999, 1, 1)

    @cache
    def member_mask(session: date) -> int:
        session_ordinal = (session - first).days
        mask = 0
        for member_ordinal in range(300):
            mask |= 1 << ((session_ordinal * 50 + member_ordinal) % 3_631)
        return mask

    def rotating_union(window: tuple[date, ...]) -> int:
        observed_windows.append(window)
        union_mask = 0
        for session in window:
            union_mask |= member_mask(session)
        cardinality = union_mask.bit_count()
        observed_cardinalities.append(cardinality)
        return cardinality

    plan = _validate_research_batch_capacity(
        "factor_evaluation",
        [child],
        union_cardinality=rotating_union,
    )

    assert plan.session_count == 64
    assert observed_windows
    assert max(map(len, observed_windows)) == 64 + 21
    assert all(len(window) < 2_843 for window in observed_windows)
    assert max(observed_cardinalities) == 3_631


def test_batch_capacity_rechunks_the_frozen_child_plan_without_changing_scope() -> None:
    sessions = tuple(date(2026, 8, 1) + timedelta(days=value) for value in range(10))
    original = ResearchExecutionPlan(
        execution_memory_bytes=512 * 1024**2,
        chunk_time_target_seconds=30,
        chunk_session_count=10,
        time_target_exceeded=False,
        estimated_peak_bytes=100,
        estimated_chunk_work=200,
        maximum_universe_cardinality=300,
        calculation_sessions=sessions,
        research_session_offset=3,
        research_session_count=7,
        chunks=(
            ResearchExecutionChunk(
                ordinal=1,
                first_session=sessions[0],
                last_session=sessions[-1],
                session_count=10,
                warmup_session_count=3,
                research_session_count=7,
            ),
        ),
    )

    rechunked = rechunk_research_execution_plan(original, chunk_session_count=3)

    assert rechunked.calculation_sessions == original.calculation_sessions
    assert rechunked.research_session_offset == 3
    assert rechunked.chunk_session_count == 3
    assert tuple(chunk.session_count for chunk in rechunked.chunks) == (3, 3, 3, 1)
    assert tuple(chunk.warmup_session_count for chunk in rechunked.chunks) == (3, 0, 0, 0)
    assert tuple(chunk.research_session_count for chunk in rechunked.chunks) == (0, 3, 3, 1)


def _validate_research_batch_capacity(
    batch_kind: str,
    children: Sequence[SimpleNamespace],
    *,
    union_cardinality: Callable[[tuple[date, ...]], int] | None = None,
):
    maximum = max(
        child.immutable_input.data_admission.universe_instrument_count for child in children
    )
    measure = union_cardinality or (lambda _window: maximum)
    first_research_session = min(child.immutable_input.requested_start_date for child in children)
    calculation_sessions = tuple(
        sorted(
            {
                session
                for child in children
                for session in child.immutable_input.execution_plan.calculation_sessions
            }
        )
    )
    prefix = tuple(
        first_research_session - timedelta(days=ordinal)
        for ordinal in range(21, 0, -1)
        if first_research_session - timedelta(days=ordinal) not in calculation_sessions
    )
    return validate_research_batch_capacity(
        batch_kind,  # type: ignore[arg-type]
        children,  # type: ignore[arg-type]
        research_calendar=prefix + calculation_sessions,
        universe_member_union_cardinalities=lambda _universe, windows: tuple(
            measure(window) for window in windows
        ),
    )


def _prepared_child(
    *,
    field_id: str,
    execution_memory_bytes: int,
    calculation_session_count: int = 2,
    maximum_universe_cardinality: int = 3_000,
    estimated_peak_bytes: int = 80 * 1024**2,
    chunk_session_count: int = 4,
) -> SimpleNamespace:
    first_session = date(2000, 1, 1)
    calculation_sessions = tuple(
        first_session + timedelta(days=ordinal) for ordinal in range(calculation_session_count)
    )
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
                calculation_sessions=calculation_sessions,
                research_session_offset=0,
                research_session_count=calculation_session_count,
                chunks=tuple(
                    SimpleNamespace(
                        ordinal=ordinal,
                        first_session=calculation_sessions[(ordinal - 1) * chunk_session_count],
                        last_session=calculation_sessions[
                            min(ordinal * chunk_session_count, calculation_session_count) - 1
                        ],
                        session_count=count,
                        warmup_session_count=0,
                        research_session_count=count,
                    )
                    for ordinal, count in enumerate(research_session_counts, start=1)
                ),
            ),
            data_admission=SimpleNamespace(
                generation_manifest_sha256="a" * 64,
                universe_instrument_count=maximum_universe_cardinality,
                calculation_session_count=calculation_session_count,
            ),
            requested_start_date=calculation_sessions[0],
            requested_end_date=calculation_sessions[-1],
            universe="top3000",
            neutralization="none",
            strategy={"holdings_count": 10},
            field_bindings={field_id: object()},
            alpha_admission=SimpleNamespace(
                formula_work=1,
                node_count=1,
                effective_lookback=0,
            ),
        )
    )

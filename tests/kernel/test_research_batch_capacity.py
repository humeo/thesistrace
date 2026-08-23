from datetime import date
from types import SimpleNamespace

import pytest

from thesistrace.research_batch.planning import (
    ResearchBatchCapacityError,
    validate_research_batch_capacity,
)


def test_factor_batch_capacity_accounts_for_union_of_field_bindings() -> None:
    execution_memory_bytes = 78_500_000
    close = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=execution_memory_bytes,
    )
    open_ = _prepared_child(
        field_id="price.open.adjusted",
        execution_memory_bytes=execution_memory_bytes,
    )

    validate_research_batch_capacity("factor_evaluation", [close])
    validate_research_batch_capacity("factor_evaluation", [open_])
    with pytest.raises(
        ResearchBatchCapacityError,
        match="cannot fit one complete full-Universe Research Session",
    ):
        validate_research_batch_capacity("factor_evaluation", [close, open_])


def test_strategy_sweep_capacity_accounts_for_private_artifact_copy() -> None:
    strategy = _prepared_child(
        field_id="price.close.adjusted",
        execution_memory_bytes=78_350_000,
    )

    validate_research_batch_capacity("factor_evaluation", [strategy])
    with pytest.raises(
        ResearchBatchCapacityError,
        match="cannot fit one complete full-Universe Research Session",
    ):
        validate_research_batch_capacity("strategy_sweep", [strategy])


def _prepared_child(
    *,
    field_id: str,
    execution_memory_bytes: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        immutable_input=SimpleNamespace(
            execution_plan=SimpleNamespace(
                execution_memory_bytes=execution_memory_bytes,
            ),
            data_admission=SimpleNamespace(
                generation_manifest_sha256="a" * 64,
                universe_instrument_count=3_000,
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

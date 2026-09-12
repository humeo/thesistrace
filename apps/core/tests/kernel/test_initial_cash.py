from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _alpha_matrix, _canonical, _definition

from thesistrace.research_kernel.strategy import run_strategy, run_strategy_with_metric_state


@pytest.mark.parametrize(
    ("cash", "price", "quantity", "fee", "remaining"),
    [
        ("100000", "2000", 0, "0", "100000"),
        ("10000000", "2000", 4900, "3038", "196962"),
        ("100000", "10", 9900, "30.69", "969.31"),
        ("1000", "1", 900, "5.009", "94.991"),
    ],
)
def test_initial_cash_drives_lot_affordability_costs_and_return_baseline(
    cash: str,
    price: str,
    quantity: int,
    fee: str,
    remaining: str,
) -> None:
    data = aligned_market_data(
        _canonical(
            opens={session: {A: price, B: price} for session in SESSIONS},
            universes={session: (A,) for session in SESSIONS},
        ),
        universe="manual",
    )
    matrix = _alpha_matrix({session: ((A, 1),) for session in SESSIONS})
    definition = _definition(rebalance_interval=5)
    definition["strategy"]["initial_cash_cny"] = cash
    full = run_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    compact = run_strategy_with_metric_state(
        data,
        matrix,
        definition,
        origin_session=SESSIONS[0],
    )
    assert full["metrics"]["net_cumulative_return"] == compact["metrics"]["net_cumulative_return"]
    assert compact["metrics"]["transaction_costs"]["ratio"] == pytest.approx(
        float(Decimal(fee) / Decimal(cash))
    )
    assert Decimal(full["daily"][0]["net_nav"]) == Decimal(cash)
    assert sum(p["execution_shares"] for p in full["positions"]) == quantity
    terminal = full["daily"][-1]
    assert Decimal(terminal["net_cash"]) == Decimal(remaining)
    assert Decimal(terminal["cumulative_transaction_cost"]) == Decimal(fee)
    assert Decimal(terminal["net_nav"]) == Decimal(cash) - Decimal(fee)
    assert full["metrics"]["net_cumulative_return"] == pytest.approx(
        -float(Decimal(fee) / Decimal(cash))
    )
    assert all(Decimal(day["net_cash"]) >= 0 for day in full["daily"])
    assert full == run_strategy(data, matrix, definition, origin_session=SESSIONS[0])


@pytest.mark.parametrize(
    "cash",
    [
        "0",
        "-1",
        "NaN",
        "Infinity",
        "1.001",
        "1000000000.01",
        "10000000000000000000000000000000001",
        "",
        100000,
        True,
        None,
    ],
)
def test_strategy_admission_rejects_invalid_initial_cash(cash: object) -> None:
    from pydantic import TypeAdapter, ValidationError

    from thesistrace.research_run.models import ResearchRunAdmissionCommand

    with pytest.raises(ValidationError):
        TypeAdapter(ResearchRunAdmissionCommand).validate_python(
            {
                **_command(),
                "initial_cash_cny": cash,
            }
        )


def test_strategy_requires_explicit_cash_and_factor_rejects_it() -> None:
    from pydantic import TypeAdapter, ValidationError

    from thesistrace.research_run.models import ResearchRunAdmissionCommand

    adapter = TypeAdapter(ResearchRunAdmissionCommand)
    with pytest.raises(ValidationError):
        adapter.validate_python(_command())
    accepted = adapter.validate_python({**_command(), "initial_cash_cny": "00100000.00"})
    assert accepted.initial_cash_cny == "100000"
    factor = {
        key: value
        for key, value in _command().items()
        if key not in ("holdings_count", "rebalance_every_sessions")
    }
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {**factor, "research_kind": "factor_evaluation", "initial_cash_cny": "100000"}
        )


def _command() -> dict[str, object]:
    return {
        "request_id": "cash",
        "folder_id": "folder_default",
        "formula": "close",
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "strategy_backtest",
        "holdings_count": 1,
        "rebalance_every_sessions": 5,
    }


@pytest.mark.parametrize("runner", [run_strategy, run_strategy_with_metric_state])
def test_continuation_keeps_initial_cash_without_reinjecting_it(runner) -> None:
    from thesistrace.research_kernel.strategy import StrategyCalculationError
    from thesistrace.research_series import slice_research_sessions

    data = aligned_market_data(
        _canonical(
            opens={session: {A: "10", B: "10"} for session in SESSIONS},
            universes={session: (A,) for session in SESSIONS},
        ),
        universe="manual",
    )
    matrix = _alpha_matrix({session: ((A, 1),) for session in SESSIONS})
    definition = _definition(rebalance_interval=5)
    definition["strategy"]["initial_cash_cny"] = "100000"
    prefix = runner(
        slice_research_sessions(data, SESSIONS[:2]),
        matrix,
        definition,
        origin_session=SESSIONS[0],
    )
    continued = runner(data, matrix, definition, continuation=prefix)
    complete = runner(data, matrix, definition, origin_session=SESSIONS[0])
    assert continued["daily"] == complete["daily"]
    assert continued["metrics"] == complete["metrics"]
    assert continued["positions"] == complete["positions"]
    assert Decimal(continued["daily"][-1]["net_cash"]) == Decimal("969.31")
    definition["strategy"]["initial_cash_cny"] = "10000000"
    with pytest.raises(StrategyCalculationError, match="baseline"):
        runner(data, matrix, definition, continuation=prefix)


@pytest.mark.parametrize("cash", ["0.01", "1000000000.00"])
def test_admission_accepts_exact_cash_range_boundaries(cash: str) -> None:
    from pydantic import TypeAdapter

    from thesistrace.research_run.models import ResearchRunAdmissionCommand

    accepted = TypeAdapter(ResearchRunAdmissionCommand).validate_python(
        {**_command(), "initial_cash_cny": cash}
    )
    assert Decimal(accepted.initial_cash_cny) == Decimal(cash)


@pytest.mark.parametrize("cash", ["1000000000.01", "10000000000000000000000000000000001"])
def test_kernel_rejects_cash_outside_executable_range(cash: str) -> None:
    from thesistrace.research_kernel.strategy import StrategyCalculationError

    data = aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}), universe="manual"
    )
    definition = _definition(rebalance_interval=5)
    definition["strategy"]["initial_cash_cny"] = cash
    with pytest.raises(StrategyCalculationError):
        run_strategy(
            data,
            _alpha_matrix({session: ((A, 1),) for session in SESSIONS}),
            definition,
            origin_session=SESSIONS[0],
        )

from decimal import Decimal

from thesistrace.research_kernel.factor import factor_day
from thesistrace.research_kernel.numeric import canonical_binary64_bytes, canonical_decimal

EXPECTED_CHECKSUMS = {
    "alpha": "2408e4eb856b85d9fa26261ec25b49cdeb4900c3f99ce863701a5fa9926f72a7",
    "labels": {
        "1": "ae47482d2e9b7d85caba094956d14df635f44321aee989331bd82d159d226de3",
        "5": "1b4d181a5b45b562811abe5a35588fde7b9629605945381df60b4e6b40eabc1c",
        "20": "96373ffe671a19200c90fbafa98ec8dd9fd0299bef7adb836945be1c1a31e8a8",
    },
    "factor": {
        "1": "e6665363300a2fc54d78d1659647f95895d72ad541053b78cc653e851cec03e3",
        "5": "c108d8430db5949afce51e5f17a6f88242a15164b834e5358ebb4517880cc691",
        "20": "ba3006a470cefea9bf194baef1328bc4e3343d9f1c32b8ccd14c96fac43c8b5e",
    },
    # Decision evidence now carries independent allocation and quantity limits.
    # The independently specified financial boundaries below remain unchanged.
    "strategy": "559770f23b6365847fc3748bb31378453fa0841ac260478dccae0cc95210224c",
}


def test_accepted_quantitative_boundaries_are_frozen(
    accepted_calculation_case: dict[str, object],
) -> None:
    matrix = accepted_calculation_case["alpha_matrix"]
    labels = accepted_calculation_case["forward_labels"]
    factor = accepted_calculation_case["factor_evaluation"]
    strategy = accepted_calculation_case["strategy_backtest"]

    assert matrix["checksum"] == EXPECTED_CHECKSUMS["alpha"]
    assert matrix["effective_lookback"] == 20
    assert matrix["sessions"][0]["session"] == "2026-05-29"
    assert matrix["sessions"][0]["values"][:3] == [
        {"instrument_id": "equity:000001.SZ", "value": 0.02444987775061147},
        {"instrument_id": "equity:000003.SZ", "value": 0.023310023310023187},
        {"instrument_id": "equity:000005.SZ", "value": 0.022271714922048824},
    ]
    assert all(
        [row["instrument_id"] for row in session["values"]]
        == sorted(row["instrument_id"] for row in session["values"])
        for session in matrix["sessions"]
    )

    assert labels["report_session_count"] == 44
    assert {
        horizon: labels["horizons"][horizon]["checksum"] for horizon in ("1", "5", "20")
    } == EXPECTED_CHECKSUMS["labels"]
    assert {
        horizon: labels["horizons"][horizon]["sessions"][-1]["unavailable"]
        for horizon in ("1", "5", "20")
    } == {
        "1": {"right_censored_by_research_period_end": 35},
        "5": {"right_censored_by_research_period_end": 35},
        "20": {"right_censored_by_research_period_end": 35},
    }

    assert {
        horizon: factor["horizons"][horizon]["checksum"] for horizon in ("1", "5", "20")
    } == EXPECTED_CHECKSUMS["factor"]
    assert {
        horizon: factor["horizons"][horizon]["summary"]["ic"]["valid_session_count"]
        for horizon in ("1", "5", "20")
    } == {"1": 42, "5": 38, "20": 23}

    # The accepted payload includes retained execution constraints.
    assert strategy["checksum"] == EXPECTED_CHECKSUMS["strategy"]
    assert len(strategy["execution_constraints"]) == 50
    first_constraint = strategy["execution_constraints"][0]
    assert {key: first_constraint[key] for key in (
        "session", "instrument_id", "side", "reason", "unrounded_quantity",
        "legal_quantity", "submitted_quantity", "order_id",
    )} == {
        "session": "2026-06-08", "instrument_id": "equity:000001.SZ", "side": "sell",
        "reason": "below_board_lot", "unrounded_quantity": 82, "legal_quantity": 0,
        "submitted_quantity": 0, "order_id": None,
    }
    assert len(strategy["daily"]) == 44
    assert _daily_boundary(strategy["daily"][0]) == {
        "session": "2026-05-29",
        "gross_nav": "1e+7",
        "net_nav": "1e+7",
        "net_cash": "1e+7",
        "holdings_count": 0,
        "rebalance": False,
        "cycle_type": "open",
    }
    assert _daily_boundary(strategy["daily"][-1]) == {
        "session": "2026-07-29",
        "gross_nav": "9702899e+0",
        "net_nav": "967759052382e-5",
        "net_cash": "92552382e-5",
        "holdings_count": 10,
        "rebalance": False,
        "cycle_type": "open",
    }
    assert [
        {key: order[key] for key in ("instrument_id", "side", "legal_quantity")}
        for order in strategy["orders"][:3]
    ] == [
        {
            "instrument_id": "equity:600000.SH",
            "side": "buy",
            "legal_quantity": 121800,
        },
        {
            "instrument_id": "equity:000001.SZ",
            "side": "buy",
            "legal_quantity": 118900,
        },
        {
            "instrument_id": "equity:600002.SH",
            "side": "buy",
            "legal_quantity": 116100,
        },
    ]
    assert {
        key: strategy["metrics"][key]
        for key in (
            "gross_cumulative_return",
            "net_cumulative_return",
            "annualized_volatility",
            "sharpe",
        )
    } == {
        "gross_cumulative_return": -0.0297101,
        "net_cumulative_return": -0.032240947618,
        "annualized_volatility": 0.11365945883188307,
        "sharpe": -1.6324393725923343,
    }


def test_independent_edge_fixture_freezes_numeric_and_missing_order() -> None:
    assert canonical_decimal(Decimal("123.4500")) == "12345e-2"
    assert canonical_binary64_bytes(-0.0).hex() == "0000000000000000"
    assert factor_day(
        [
            {
                "instrument_id": f"equity:{index:02d}.SH",
                "alpha": float(index // 6),
                "label": float(index // 6),
            }
            for index in range(30)
        ]
    ) == {
        "ic": 1.0,
        "rank_ic": 1.0,
        "correlation_reason": None,
        "quantile_returns": {
            "q1": 0.0,
            "q2": 1.0,
            "q3": 2.0,
            "q4": 3.0,
            "q5": 4.0,
        },
        "quantile_counts": {"q1": 6, "q2": 6, "q3": 6, "q4": 6, "q5": 6},
        "top_bottom_return": 4.0,
        "quantile_reason": None,
    }
def _daily_boundary(observation: dict[str, object]) -> dict[str, object]:
    return {
        key: observation[key]
        for key in (
            "session",
            "gross_nav",
            "net_nav",
            "net_cash",
            "holdings_count",
            "rebalance",
            "cycle_type",
        )
    }

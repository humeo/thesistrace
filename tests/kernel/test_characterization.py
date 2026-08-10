from decimal import Decimal

from thesistrace.research_kernel.factor import factor_day
from thesistrace.research_kernel.numeric import canonical_binary64_bytes, canonical_decimal
from thesistrace.research_kernel.strategy import equal_weight_benchmark_return

EXPECTED_CHECKSUMS = {
    "alpha": "f01531eccc3d83f1965aaabf807515fc4905288b678be90e16e96c571533bcd9",
    "labels": {
        "1": "ecdafbd877477678e9f8109f2ebedc02d652e83b31fe67a183b2cd71fbe23703",
        "5": "779e6534d8c197eeb19e3accd1e4013f357f71e577a3faabdc8f46f642ed0ea2",
        "20": "0a26cfe3b21ccaaf3562f36278ab2e0538dcf1fe3f3a5ecfed22196b863f3df7",
    },
    "factor": {
        "1": "4d4fdb43398436b3ac1b2d9be92f8ef7f65b0e4a4da21b995898da8f9d9a74c6",
        "5": "3a8858ed6144f82cc9317910ec4c8133b9dd441bec4c5d1ceacae2b5197da505",
        "20": "74809f05078de529c6b65d5337572000a70f006f02462916aeaf007f507ec457",
    },
    "strategy": "086d662a6db387761ee55a361a164edfc6e13321c8ac806d2c2b63dc80e6cc0d",
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

    assert strategy["checksum"] == EXPECTED_CHECKSUMS["strategy"]
    assert len(strategy["daily"]) == 44
    assert _daily_boundary(strategy["daily"][0]) == {
        "session": "2026-05-29",
        "gross_nav": "1e+7",
        "net_nav": "1e+7",
        "benchmark_nav": "1e+0",
        "net_cash": "1e+7",
        "holdings_count": 0,
        "rebalance": False,
        "cycle_type": "open",
    }
    assert _daily_boundary(strategy["daily"][-1]) == {
        "session": "2026-07-29",
        "gross_nav": "9702899e+0",
        "net_nav": "967759052382e-5",
        "benchmark_nav": "9822402584754961170254219637e-28",
        "net_cash": "92552382e-5",
        "holdings_count": 10,
        "rebalance": False,
        "cycle_type": "terminal_valuation",
    }
    assert [
        {key: order[key] for key in ("order_id", "instrument_id", "side", "legal_quantity")}
        for order in strategy["orders"][:3]
    ] == [
        {
            "order_id": 0,
            "instrument_id": "equity:600000.SH",
            "side": "buy",
            "legal_quantity": 121800,
        },
        {
            "order_id": 1,
            "instrument_id": "equity:000001.SZ",
            "side": "buy",
            "legal_quantity": 118900,
        },
        {
            "order_id": 2,
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
            "benchmark_cumulative_return",
            "annualized_excess_return",
            "annualized_volatility",
            "sharpe",
        )
    } == {
        "gross_cumulative_return": -0.0297101,
        "net_cumulative_return": -0.032240947618,
        "benchmark_cumulative_return": -0.017759741524503884,
        "annualized_excess_return": -0.0833635130245971,
        "annualized_volatility": 0.11365945883188307,
        "sharpe": -1.6324393725923343,
    }


def test_independent_edge_fixture_freezes_numeric_missing_order_and_benchmark() -> None:
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
        "top_bottom_return": 4.0,
        "quantile_reason": None,
    }
    assert equal_weight_benchmark_return(
        "s0",
        "s1",
        "s2",
        {"s0": ["equity:B.SH", "equity:A.SH", "equity:C.SH"]},
        {
            ("s1", "equity:A.SH"): {"open_adj": "20"},
            ("s2", "equity:A.SH"): {"open_adj": "20"},
            ("s1", "equity:B.SH"): {"open_adj": "10"},
            ("s2", "equity:B.SH"): {"open_adj": "11"},
            ("s1", "equity:C.SH"): {"open_adj": "4"},
        },
        {},
        {
            "equity:A.SH": {"listed_to": ""},
            "equity:B.SH": {"listed_to": ""},
            "equity:C.SH": {"listed_to": "s2"},
        },
    ) == Decimal("-0.3")


def _daily_boundary(observation: dict[str, object]) -> dict[str, object]:
    return {
        key: observation[key]
        for key in (
            "session",
            "gross_nav",
            "net_nav",
            "benchmark_nav",
            "net_cash",
            "holdings_count",
            "rebalance",
            "cycle_type",
        )
    }

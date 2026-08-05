import hashlib
from decimal import Decimal

from thesistrace.factor import factor_day
from thesistrace.numeric import canonical_binary64_bytes, canonical_decimal
from thesistrace.objects import canonical_json_bytes
from thesistrace.strategy import equal_weight_benchmark_return

EXPECTED_CHECKSUMS = {
    "alpha": "c002b936f6e730c3a3e4a98161a4ec1f805beb9d509f96d053cf131c5927be6f",
    "labels": {
        "1": "e88df02d1dde19e1747b24c5e64cfe1b86840b655ed3455cbc9250356be84dd2",
        "5": "cf7fb440780cc7cba49cba09f186f991a7629a2cfdd22cf0110e32408def9003",
        "20": "7e3cc055cee9b504a884f8d451ac8dc73ed3442cff49bb66315ede48c907a6a7",
    },
    "factor": {
        "1": "83f8d777d8c4f89bf5d0169be3cae4062c2d1719a923591001f3604b1159c362",
        "5": "028ac4864245fc1bf372e262be8d27543b6bd260837cea832eec936de44beef7",
        "20": "2058d8355d9c8b02e93c31470e5f69ef92ba7a98de631d79d612b4ed957a16b5",
    },
    "strategy": "11ef9091b14903b3cebb91b888b03a9c8f9aaccf235b76e44c05112b96717433",
}


def test_accepted_quantitative_boundaries_are_frozen(
    accepted_calculation_case: dict[str, object],
) -> None:
    matrix = accepted_calculation_case["alpha_matrix"]
    labels = accepted_calculation_case["forward_labels"]
    factor = accepted_calculation_case["factor_evaluation"]
    strategy = accepted_calculation_case["strategy_backtest"]
    retained = accepted_calculation_case["compact_projection"]

    assert matrix["checksum"] == EXPECTED_CHECKSUMS["alpha"]
    assert matrix["effective_lookback"] == 20
    assert matrix["sessions"][-504]["session"] == "2024-08-23"
    assert matrix["sessions"][-504]["values"][:3] == [
        {"instrument_id": "equity:000001.SZ", "value": -0.013173652694610904},
        {"instrument_id": "equity:000003.SZ", "value": -0.012571428571428678},
        {"instrument_id": "equity:000005.SZ", "value": -0.012021857923497192},
    ]
    assert all(
        [row["instrument_id"] for row in session["values"]]
        == sorted(row["instrument_id"] for row in session["values"])
        for session in matrix["sessions"]
    )

    assert labels["report_session_count"] == 504
    assert {
        horizon: labels["horizons"][horizon]["checksum"] for horizon in ("1", "5", "20")
    } == EXPECTED_CHECKSUMS["labels"]
    assert {
        horizon: labels["horizons"][horizon]["sessions"][-1]["unavailable"]
        for horizon in ("1", "5", "20")
    } == {
        "1": {"right_censored_by_release_end": 35},
        "5": {"right_censored_by_release_end": 35},
        "20": {"right_censored_by_release_end": 35},
    }

    assert {
        horizon: factor["horizons"][horizon]["checksum"] for horizon in ("1", "5", "20")
    } == EXPECTED_CHECKSUMS["factor"]
    assert {
        horizon: factor["horizons"][horizon]["summary"]["ic"]["valid_session_count"]
        for horizon in ("1", "5", "20")
    } == {"1": 502, "5": 498, "20": 483}

    assert strategy["checksum"] == EXPECTED_CHECKSUMS["strategy"]
    assert len(strategy["daily"]) == 504
    assert _daily_boundary(strategy["daily"][0]) == {
        "session": "2024-08-23",
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
        "gross_nav": "96879440930735930735930736e-19",
        "net_nav": "9336960784113593073593073596e-21",
        "benchmark_nav": "1101382289594383888352628991e-27",
        "net_cash": "695784113593073593073596e-21",
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
            "instrument_id": "equity:600034.SH",
            "side": "buy",
            "legal_quantity": 67300,
        },
        {
            "order_id": 1,
            "instrument_id": "equity:000033.SZ",
            "side": "buy",
            "legal_quantity": 68200,
        },
        {
            "order_id": 2,
            "instrument_id": "equity:600032.SH",
            "side": "buy",
            "legal_quantity": 69200,
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
        "gross_cumulative_return": -0.031205590692640693,
        "net_cumulative_return": -0.0663039215886407,
        "benchmark_cumulative_return": 0.10138228959438389,
        "annualized_excess_return": -0.07941812853681218,
        "annualized_volatility": 0.10505935281412912,
        "sharpe": -0.27412571961790205,
    }

    assert sorted(retained) == [
        "diagnostic_summary",
        "execution_aggregates",
        "factor_summary",
        "rebalance_aggregates",
        "strategy_daily_observations",
        "strategy_summary",
        "terminal_positions",
        "terminal_strategy_state",
    ]
    assert (
        hashlib.sha256(canonical_json_bytes(retained)).hexdigest()
        == "cebf53e0c134ab0cdc6762e3f1af3e0cb9ce304d4ddf0ff8c8ae4a6fec6ded39"
    )
    assert {
        key: len(retained[key])
        for key in (
            "strategy_daily_observations",
            "rebalance_aggregates",
            "execution_aggregates",
            "terminal_positions",
        )
    } == {
        "strategy_daily_observations": 504,
        "rebalance_aggregates": 101,
        "execution_aggregates": 57,
        "terminal_positions": 10,
    }
    assert retained["strategy_daily_observations"][0] == {
        "session": "2024-08-23",
        "gross_nav": "1e+7",
        "net_nav": "1e+7",
        "benchmark_nav": "1e+0",
        "net_cash": "1e+7",
        "transaction_cost_cny": "0",
        "holdings_count": 0,
        "maximum_single_name_weight": 0.0,
        "upper_limit_buy_rejections": 0,
        "lower_limit_sell_rejections": 0,
        "suspension_rejections": 0,
    }
    assert retained["strategy_daily_observations"][-1] == {
        "session": "2026-07-29",
        "gross_nav": "96879440930735930735930736e-19",
        "net_nav": "9336960784113593073593073596e-21",
        "benchmark_nav": "1101382289594383888352628991e-27",
        "net_cash": "695784113593073593073596e-21",
        "transaction_cost_cny": "0",
        "holdings_count": 10,
        "maximum_single_name_weight": 0.10012808467511992,
        "upper_limit_buy_rejections": 0,
        "lower_limit_sell_rejections": 0,
        "suspension_rejections": 0,
    }
    assert retained["rebalance_aggregates"][0] == {
        "session": "2024-08-26",
        "signal_session": "2024-08-23",
        "turnover": 0.999661694313196,
        "fill_count": 10,
        "buy_order_count": 10,
        "sell_order_count": 0,
    }
    assert retained["terminal_positions"][:2] == [
        {
            "instrument_id": "equity:000025.SZ",
            "execution_shares": 70800,
            "adjusted_units": "6156521739130434782608695652173913e-29",
            "last_adjusted_price": "150765e-4",
        },
        {
            "instrument_id": "equity:000027.SZ",
            "execution_shares": 69200,
            "adjusted_units": "6017391304347826086956521739130435e-29",
            "last_adjusted_price": "155365e-4",
        },
    ]


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

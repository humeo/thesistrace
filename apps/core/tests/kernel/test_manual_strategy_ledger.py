from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest
from contracts import CLOSE_ADJUSTED, FIELD_BINDINGS
from series import aligned_market_data

from thesistrace.research_kernel import RunInput, StrategyRunInput, run
from thesistrace.research_kernel.alpha import evaluate_alpha_matrix, validate_alpha
from thesistrace.research_kernel.strategy import run_strategy

SESSIONS = ("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08")
A = "equity:600001.SH"
B = "equity:600002.SH"


def test_kernel_transient_ledger_reconciles_every_session_from_the_strategy_transition() -> None:
    canonical = _canonical(
        opens={
            SESSIONS[0]: {A: "10", B: "20"},
            SESSIONS[1]: {A: "30", B: "20"},
            SESSIONS[2]: {A: "30", B: "40"},
            SESSIONS[3]: {A: "35", B: "40"},
        }
    )
    first = _kernel_run(canonical)
    repeated = _kernel_run(canonical)
    ledger = first.strategy_ledger_snapshot()

    assert ledger == repeated.strategy_ledger_snapshot()
    assert first.track_state.output_snapshot() == repeated.track_state.output_snapshot()
    assert [row["session"] for row in ledger] == list(SESSIONS)
    assert ledger[0]["signal"] is None
    assert ledger[1]["signal"]["session"] == SESSIONS[0]
    assert ledger[1]["signal"]["selected_instrument_ids"] == [B]
    assert ledger[1]["intended_orders"] == [
        {
            "instrument_id": B,
            "side": "buy",
            "intended_value": "1e+7",
            "unrounded_quantity": 500000,
            "legal_quantity": 500000,
        }
    ]
    assert [
        (
            order["session"],
            order["instrument_id"],
            order["side"],
            order["legal_quantity"],
        )
        for row in ledger[1:3]
        for order in row["submitted_orders"]
    ] == [
        (SESSIONS[1], B, "buy", 499_800),
        (SESSIONS[2], B, "sell", 499_800),
        (SESSIONS[2], A, "buy", 665_600),
    ]
    assert ledger[2]["signal"]["session"] == SESSIONS[1]
    assert ledger[2]["signal"]["selected_instrument_ids"] == [A]
    assert ledger[-1]["cycle_type"] == "open"
    assert ledger[-1]["signal"]["session"] == SESSIONS[-2]
    assert ledger[-1]["signal"]["selected_instrument_ids"] == [B]

    _assert_ledger_reconciles(ledger)

    assert "strategy_ledger" not in first.track_state.output_snapshot()
    assert "ledger" not in first.track_state.strategy_resume_snapshot()


def test_manual_switch_ledger_reconciles_signal_orders_fills_cash_and_positions() -> None:
    canonical = _canonical(
        opens={
            SESSIONS[0]: {A: "10", B: "20"},
            SESSIONS[1]: {A: "10", B: "20"},
            SESSIONS[2]: {A: "12", B: "20"},
            SESSIONS[3]: {A: "12", B: "22"},
        }
    )
    matrix = _alpha_matrix(
        {
            SESSIONS[0]: ((A, 2), (B, 1)),
            SESSIONS[1]: ((B, 2), (A, 1)),
            SESSIONS[2]: ((B, 2), (A, 1)),
            SESSIONS[3]: ((B, 2), (A, 1)),
        }
    )

    result = _run(canonical, matrix)

    assert _daily_ledger(result) == [
        {
            "session": SESSIONS[0],
            "cycle_type": "open",
            "rebalance": False,
            "gross_cash": Decimal("10000000"),
            "net_cash": Decimal("10000000"),
            "gross_nav": Decimal("10000000"),
            "net_nav": Decimal("10000000"),
            "cost": Decimal("0"),
            "holdings_count": 0,
        },
        {
            "session": SESSIONS[1],
            "cycle_type": "open",
            "rebalance": True,
            "gross_cash": Decimal("4000"),
            "net_cash": Decimal("901.24"),
            "gross_nav": Decimal("10000000"),
            "net_nav": Decimal("9996901.24"),
            "cost": Decimal("3098.76"),
            "holdings_count": 1,
        },
        {
            "session": SESSIONS[2],
            "cycle_type": "open",
            "rebalance": True,
            "gross_cash": Decimal("17200"),
            "net_cash": Decimal("670.708"),
            "gross_nav": Decimal("11999200"),
            "net_nav": Decimal("11982670.708"),
            "cost": Decimal("16529.292"),
            "holdings_count": 1,
        },
        {
            "session": SESSIONS[3],
            "cycle_type": "open",
            "rebalance": True,
            "gross_cash": Decimal("17200"),
            "net_cash": Decimal("670.708"),
            "gross_nav": Decimal("13197400"),
            "net_nav": Decimal("13180870.708"),
            "cost": Decimal("16529.292"),
            "holdings_count": 1,
        },
    ]
    assert _orders(result) == [
        (SESSIONS[1], A, "buy", 1_000_000, 999_600),
        (SESSIONS[2], A, "sell", 999_600, 999_600),
        (SESSIONS[2], B, "buy", 599_805, 599_100),
    ]
    assert _fills(result) == [
        (SESSIONS[1], A, "buy", 999_600, Decimal("10"), Decimal("9996000"), Decimal("3098.76")),
        (SESSIONS[2], A, "sell", 999_600, Decimal("12"), Decimal("11995200"), Decimal("9716.112")),
        (SESSIONS[2], B, "buy", 599_100, Decimal("20"), Decimal("11982000"), Decimal("3714.42")),
    ]
    assert _position_ledger(canonical, matrix) == {
        SESSIONS[0]: (),
        SESSIONS[1]: ((A, 999_600, Decimal("999600")),),
        SESSIONS[2]: ((B, 599_100, Decimal("599100")),),
        SESSIONS[3]: ((B, 599_100, Decimal("599100")),),
    }
    assert all(day["net_cash"] >= 0 for day in _daily_ledger(result))
    assert all(order[4] % 100 == 0 for order in _orders(result))
    assert result["rebalance_events"][0]["signal_session"] == SESSIONS[0]
    assert result["rebalance_events"][0]["session"] == SESSIONS[1]
    assert all(order[0] != SESSIONS[3] for order in _orders(result))
    assert _run(canonical, matrix) == result


def test_manual_small_order_uses_minimum_commission_without_negative_cash() -> None:
    canonical = _canonical(
        opens={
            SESSIONS[0]: {A: "200", B: "200"},
            SESSIONS[1]: {A: "200", B: "200"},
            SESSIONS[2]: {A: ("10", "200.2"), B: ("10", "199.8")},
            SESSIONS[3]: {A: ("10", "200.2"), B: ("10", "199.8")},
        }
    )
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})

    result = _run(canonical, matrix, holdings_count=2)

    assert _daily_ledger(result) == [
        {
            "session": SESSIONS[0],
            "cycle_type": "open",
            "rebalance": False,
            "gross_cash": Decimal("10000000"),
            "net_cash": Decimal("10000000"),
            "gross_nav": Decimal("10000000"),
            "net_nav": Decimal("10000000"),
            "cost": Decimal("0"),
            "holdings_count": 0,
        },
        {
            "session": SESSIONS[1],
            "cycle_type": "open",
            "rebalance": True,
            "gross_cash": Decimal("20000"),
            "net_cash": Decimal("16906.2"),
            "gross_nav": Decimal("10000000"),
            "net_nav": Decimal("9996906.2"),
            "cost": Decimal("3093.8"),
            "holdings_count": 2,
        },
        {
            "session": SESSIONS[2],
            "cycle_type": "open",
            "rebalance": True,
            "gross_cash": Decimal("4000"),
            "net_cash": Decimal("901.04"),
            "gross_nav": Decimal("10000020"),
            "net_nav": Decimal("9996921.04"),
            "cost": Decimal("3098.96"),
            "holdings_count": 2,
        },
        {
            "session": SESSIONS[3],
            "cycle_type": "open",
            "rebalance": True,
            "gross_cash": Decimal("4000"),
            "net_cash": Decimal("901.04"),
            "gross_nav": Decimal("10000020"),
            "net_nav": Decimal("9996921.04"),
            "cost": Decimal("3098.96"),
            "holdings_count": 2,
        },
    ]
    assert _fills(result)[-1] == (
        SESSIONS[2],
        B,
        "buy",
        1_600,
        Decimal("10"),
        Decimal("16000"),
        Decimal("5.16"),
    )
    assert _position_ledger(canonical, matrix, holdings_count=2) == {
        SESSIONS[0]: (),
        SESSIONS[1]: (
            (A, 25_000, Decimal("25000")),
            (B, 24_900, Decimal("24900")),
        ),
        SESSIONS[2]: (
            (A, 25_000, Decimal("25000")),
            (B, 26_500, Decimal("24980.08008008008008008008008")),
        ),
        SESSIONS[3]: (
            (A, 25_000, Decimal("25000")),
            (B, 26_500, Decimal("24980.08008008008008008008008")),
        ),
    }
    assert all(day["net_cash"] >= 0 for day in _daily_ledger(result))

    _, kernel_ledger = _kernel_ledger(canonical, holdings_count=2)
    assert Decimal(str(kernel_ledger[2]["transaction_cost_cny"])) == Decimal("5.16")
    assert Decimal(str(kernel_ledger[2]["net_cash"])) >= 0
    _assert_ledger_reconciles(kernel_ledger)


def test_kernel_ledger_records_star_board_specific_order_quantity() -> None:
    canonical = _canonical(
        opens={session: {A: "30", B: "60"} for session in SESSIONS},
    )
    canonical["instruments"][0]["board"] = "star"
    _set_alpha_closes(
        canonical,
        {session: {A: "2", B: "1"} for session in SESSIONS},
    )

    _, ledger = _kernel_ledger(canonical, selection_interval=20)

    intent = ledger[1]["intended_orders"][0]
    filled_quantity = sum(int(fill["quantity"]) for fill in ledger[1]["fills"])
    assert intent["legal_quantity"] == 333_333
    assert filled_quantity >= 200
    assert filled_quantity % 100 != 0
    _assert_ledger_reconciles(ledger)


def test_kernel_ledger_explains_when_minimum_lot_is_not_affordable() -> None:
    canonical = _canonical(
        opens={session: {A: "100000", B: "200000"} for session in SESSIONS},
    )
    _set_alpha_closes(
        canonical,
        {session: {A: "2", B: "1"} for session in SESSIONS},
    )

    _, ledger = _kernel_ledger(canonical, selection_interval=20)

    assert ledger[1]["intended_orders"] == [
        {
            "instrument_id": A,
            "side": "buy",
            "intended_value": "1e+7",
            "unrounded_quantity": 100,
            "legal_quantity": 100,
        }
    ]
    assert ledger[1]["submitted_orders"] == []
    assert ledger[1]["fills"] == []
    assert ledger[1]["diagnostics"] == [
        {
            "session": SESSIONS[1],
            "instrument_id": A,
            "reason": "insufficient_cash",
            "side": "buy",
            "legal_quantity": 100,
        }
    ]
    assert ledger[1]["net_cash"] == "1e+7"
    _assert_ledger_reconciles(ledger)


def test_manual_rejections_never_create_false_fills_or_discard_a_holding() -> None:
    upper_limit_buy = _canonical(
        opens={session: {A: "10", B: "20"} for session in SESSIONS},
        limit_overrides={(SESSIONS[1], A): ("10", "9")},
    )
    buy_matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})

    rejected_buy = _run(upper_limit_buy, buy_matrix, selection_interval=20)

    assert _orders(rejected_buy) == [(SESSIONS[1], A, "buy", 1_000_000, 999_600)]
    assert _fills(rejected_buy) == []
    assert rejected_buy["rejections"] == [
        {
            "order_id": 0,
            "session": SESSIONS[1],
            "instrument_id": A,
            "side": "buy",
            "quantity": 999_600,
            "intended_value": "1e+7",
            "reason": "upper_limit_buy",
        }
    ]
    assert _position_ledger(upper_limit_buy, buy_matrix, selection_interval=20) == {
        session: () for session in SESSIONS
    }
    assert all(day["net_cash"] == Decimal("10000000") for day in _daily_ledger(rejected_buy))
    _set_alpha_closes(
        upper_limit_buy,
        {session: {A: "2", B: "1"} for session in SESSIONS},
    )
    _, upper_ledger = _kernel_ledger(upper_limit_buy, selection_interval=20)
    assert upper_ledger[1]["fills"] == []
    assert upper_ledger[1]["rejections"][0]["reason"] == "upper_limit_buy"
    _assert_ledger_reconciles(upper_ledger)

    suspended_buy = _canonical(
        opens={
            SESSIONS[0]: {A: "10", B: "20"},
            SESSIONS[1]: {A: None, B: "20"},
            SESSIONS[2]: {A: "10", B: "20"},
            SESSIONS[3]: {A: "10", B: "20"},
        },
        states={(SESSIONS[1], A): "full_session_suspension"},
    )

    rejected_suspension = _run(suspended_buy, buy_matrix, selection_interval=20)

    assert _fills(rejected_suspension) == []
    assert rejected_suspension["rejections"][0]["reason"] == "suspension"
    assert _position_ledger(suspended_buy, buy_matrix, selection_interval=20) == {
        session: () for session in SESSIONS
    }
    _set_alpha_closes(
        suspended_buy,
        {session: {A: "2", B: "1"} for session in SESSIONS},
    )
    _, suspension_ledger = _kernel_ledger(suspended_buy, selection_interval=20)
    assert suspension_ledger[1]["fills"] == []
    assert suspension_ledger[1]["rejections"][0]["reason"] == "suspension"
    _assert_ledger_reconciles(suspension_ledger)

    lower_limit_sell = _canonical(
        opens={
            SESSIONS[0]: {A: "10", B: "20"},
            SESSIONS[1]: {A: "10", B: "20"},
            SESSIONS[2]: {A: "9", B: "20"},
            SESSIONS[3]: {A: "9", B: "20"},
        },
        limit_overrides={(SESSIONS[2], A): ("11", "9")},
    )
    sell_matrix = _alpha_matrix(
        {
            SESSIONS[0]: ((A, 2), (B, 1)),
            SESSIONS[1]: ((B, 2), (A, 1)),
            SESSIONS[2]: ((B, 2), (A, 1)),
            SESSIONS[3]: ((B, 2), (A, 1)),
        }
    )

    rejected_sell = _run(lower_limit_sell, sell_matrix)

    sell_order = next(order for order in _orders(rejected_sell) if order[2] == "sell")
    assert sell_order == (SESSIONS[2], A, "sell", 999_600, 999_600)
    assert all(fill[2] != "sell" for fill in _fills(rejected_sell) if fill[0] == SESSIONS[2])
    assert any(fill[2] == "sell" for fill in _fills(rejected_sell) if fill[0] == SESSIONS[3])
    assert any(item["reason"] == "lower_limit_sell" for item in rejected_sell["rejections"])
    assert _position_ledger(lower_limit_sell, sell_matrix)[SESSIONS[2]] == (
        (A, 999_600, Decimal("999600")),
    )
    _set_alpha_closes(
        lower_limit_sell,
        {
            SESSIONS[0]: {A: "2", B: "1"},
            SESSIONS[1]: {A: "1", B: "2"},
            SESSIONS[2]: {A: "1", B: "2"},
            SESSIONS[3]: {A: "1", B: "2"},
        },
    )
    _, lower_ledger = _kernel_ledger(lower_limit_sell)
    assert any(item["reason"] == "lower_limit_sell" for item in lower_ledger[2]["rejections"])
    assert lower_ledger[2]["fills"] == []
    assert [position["instrument_id"] for position in lower_ledger[2]["positions"]] == [A]
    _assert_ledger_reconciles(lower_ledger)


def test_manual_adjusted_return_keeps_the_position_and_value_continuous() -> None:
    canonical = _canonical(
        opens={
            SESSIONS[0]: {A: "10", B: "20"},
            SESSIONS[1]: {A: "10", B: "20"},
            SESSIONS[2]: {A: ("5", "10"), B: "20"},
            SESSIONS[3]: {A: ("5", "10"), B: "20"},
        }
    )
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})

    result = _run(canonical, matrix, selection_interval=20)
    ledger = _daily_ledger(result)

    assert ledger[1]["net_nav"] == Decimal("9996901.24")
    assert ledger[2]["net_nav"] == ledger[1]["net_nav"]
    assert ledger[3]["net_nav"] == ledger[1]["net_nav"]
    assert _position_ledger(canonical, matrix, selection_interval=20) == {
        SESSIONS[0]: (),
        SESSIONS[1]: ((A, 999_600, Decimal("999600")),),
        SESSIONS[2]: ((A, 999_600, Decimal("999600")),),
        SESSIONS[3]: ((A, 999_600, Decimal("999600")),),
    }
    assert _orders(result) == [(SESSIONS[1], A, "buy", 1_000_000, 999_600)]
    _set_alpha_closes(
        canonical,
        {session: {A: "2", B: "1"} for session in SESSIONS},
    )
    _, kernel_ledger = _kernel_ledger(canonical, selection_interval=20)
    assert kernel_ledger[2]["net_nav"] == kernel_ledger[1]["net_nav"]
    assert kernel_ledger[3]["net_nav"] == kernel_ledger[1]["net_nav"]
    _assert_ledger_reconciles(kernel_ledger)


def test_manual_delisting_writes_off_the_holding_without_a_false_sale() -> None:
    canonical = _canonical(
        opens={
            SESSIONS[0]: {A: "10", B: "20"},
            SESSIONS[1]: {A: "10", B: "20"},
            SESSIONS[2]: {A: None, B: "20"},
            SESSIONS[3]: {A: None, B: "20"},
        },
        universes={
            SESSIONS[0]: (A, B),
            SESSIONS[1]: (A, B),
            SESSIONS[2]: (B,),
            SESSIONS[3]: (B,),
        },
    )
    canonical["instruments"][0]["listed_to"] = SESSIONS[2]
    matrix = _alpha_matrix(
        {
            SESSIONS[0]: ((A, 2), (B, 1)),
            SESSIONS[1]: ((B, 2), (A, 1)),
            SESSIONS[2]: ((B, 2),),
            SESSIONS[3]: ((B, 2),),
        }
    )

    result = _run(canonical, matrix)

    assert {
        "session": SESSIONS[2],
        "instrument_id": A,
        "type": "terminal_delisting_writeoff",
    } in result["daily"][2]["valuation_events"]
    assert all(fill[1] != A or fill[2] != "sell" for fill in _fills(result))
    assert _position_ledger(canonical, matrix)[SESSIONS[2]] == ()
    assert _daily_ledger(result)[2]["net_cash"] == Decimal("901.24")
    assert _daily_ledger(result)[2]["net_nav"] == Decimal("901.24")
    _set_alpha_closes(
        canonical,
        {
            SESSIONS[0]: {A: "2", B: "1"},
            SESSIONS[1]: {A: "1", B: "2"},
            SESSIONS[2]: {B: "2"},
            SESSIONS[3]: {B: "2"},
        },
    )
    _, kernel_ledger = _kernel_ledger(canonical)
    assert {
        "session": SESSIONS[2],
        "instrument_id": A,
        "type": "terminal_delisting_writeoff",
    } in kernel_ledger[2]["valuation_events"]
    assert kernel_ledger[2]["positions"] == []
    _assert_ledger_reconciles(kernel_ledger)


def test_manual_historical_universe_excludes_a_future_stock_and_changes_on_schedule() -> None:
    canonical = _canonical(
        opens={session: {A: "10", B: "20"} for session in SESSIONS},
        universes={
            SESSIONS[0]: (A,),
            SESSIONS[1]: (B,),
            SESSIONS[2]: (B,),
            SESSIONS[3]: (B,),
        },
    )
    canonical["instruments"][1]["listed_from"] = SESSIONS[1]

    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical, universe="manual"),
        compiled_alpha=validate_alpha(CLOSE_ADJUSTED, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )

    assert [row["instrument_id"] for row in matrix["sessions"][0]["values"]] == [A]
    assert [row["instrument_id"] for row in matrix["sessions"][1]["values"]] == [B]
    result = _run(canonical, matrix)
    assert _orders(result) == [
        (SESSIONS[1], A, "buy", 1_000_000, 999_600),
        (SESSIONS[2], A, "sell", 999_600, 999_600),
        (SESSIONS[2], B, "buy", 499_845, 499_200),
    ]
    assert _position_ledger(canonical, matrix)[SESSIONS[2]] == ((B, 499_200, Decimal("499200")),)
    _, kernel_ledger = _kernel_ledger(canonical)
    assert kernel_ledger[1]["signal"]["selected_instrument_ids"] == [A]
    assert kernel_ledger[2]["signal"]["selected_instrument_ids"] == [B]
    assert [position["instrument_id"] for position in kernel_ledger[2]["positions"]] == [B]
    _assert_ledger_reconciles(kernel_ledger)


def _canonical(
    *,
    sessions: tuple[str, ...] = SESSIONS,
    opens: dict[str, dict[str, str | tuple[str, str] | None]],
    states: dict[tuple[str, str], str] | None = None,
    universes: dict[str, tuple[str, ...]] | None = None,
    limit_overrides: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> dict[str, object]:
    selected_states = states or {}
    selected_universes = universes or {session: (A, B) for session in sessions}
    selected_limits = limit_overrides or {}
    prices: list[dict[str, object]] = []
    trading_states: list[dict[str, object]] = []
    price_limits: list[dict[str, object]] = []
    for session in sessions:
        for instrument_id in (A, B):
            state = selected_states.get((session, instrument_id), "normal")
            trading_states.append(
                {"session": session, "instrument_id": instrument_id, "state": state}
            )
            coordinate = opens[session].get(instrument_id)
            if coordinate is None:
                continue
            raw_open, adjusted_open = (
                coordinate if isinstance(coordinate, tuple) else (coordinate, coordinate)
            )
            prices.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "open_raw": raw_open,
                    "open_adj": adjusted_open,
                    "close_adj": adjusted_open,
                    "turnover_cny": "1000",
                }
            )
            upper, lower = selected_limits.get(
                (session, instrument_id),
                (
                    str(Decimal(raw_open) * Decimal("1.1")),
                    str(Decimal(raw_open) * Decimal("0.9")),
                ),
            )
            price_limits.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "upper": upper,
                    "lower": lower,
                }
            )
    return {
        "research_calendar": list(sessions),
        "instruments": [
            {
                "instrument_id": A,
                "board": "main",
                "listed_from": sessions[0],
                "listed_to": "",
            },
            {
                "instrument_id": B,
                "board": "main",
                "listed_from": sessions[0],
                "listed_to": "",
            },
        ],
        "prices": prices,
        "trading_states": trading_states,
        "price_limits": price_limits,
        "liquidity_universes": {
            "manual": [
                {"session": session, "instrument_ids": list(selected_universes[session])}
                for session in sessions
            ]
        },
        "industry_membership": [],
    }


def _alpha_matrix(
    values: dict[str, tuple[tuple[str, int], ...]],
) -> dict[str, object]:
    return {
        "checksum": "manual-alpha-v1",
        "value_store": {
            session: [
                {"instrument_id": instrument_id, "value": value} for instrument_id, value in rows
            ]
            for session, rows in values.items()
        },
    }


def _definition(
    *,
    holdings_count: int = 1,
    selection_interval: int = 1,
) -> dict[str, object]:
    return {
        "universe": "manual",
        "strategy": {"volatility_window": 20, "weighting": "equal_weight",
            "holdings_count": holdings_count,
            "selection_interval": selection_interval,
            "initial_cash_cny": "10000000",
            "exposure_expression": {"kind": "number", "value": 1},
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
    }


def _kernel_run(
    canonical: dict[str, object],
    *,
    holdings_count: int = 1,
    selection_interval: int = 1,
    exposure: float = 1.0,
):
    return run(
        RunInput(
            research_data=aligned_market_data(canonical, universe="manual"),
            alpha_expression=CLOSE_ADJUSTED,
            field_bindings=FIELD_BINDINGS,
            effective_lookback=0,
            universe="manual",
            neutralization="none",
            research_kind="strategy_backtest",
            strategy=StrategyRunInput(
                holdings_count=holdings_count,
                selection_interval=selection_interval,
                initial_cash_cny="10000000",
                exposure_expression_json=json.dumps({"kind": "number", "value": exposure}).encode(),
                commission_rate_all_in="0.0003",
                commission_min_cny="5",
                stamp_duty_sell_rate="0.0005",
                transfer_fee_rate="0.00001",
            ),
            research_start_session=SESSIONS[0],
            research_end_session=SESSIONS[-1],
        )
    )


def _kernel_ledger(
    canonical: dict[str, object],
    *,
    holdings_count: int = 1,
    selection_interval: int = 1,
):
    output = _kernel_run(
        canonical,
        holdings_count=holdings_count,
        selection_interval=selection_interval,
    )
    ledger = output.strategy_ledger_snapshot()
    return output, ledger


def _set_alpha_closes(
    canonical: dict[str, object],
    values: dict[str, dict[str, str]],
) -> None:
    for row in canonical["prices"]:
        session = str(row["session"])
        instrument_id = str(row["instrument_id"])
        if instrument_id in values.get(session, {}):
            row["close_adj"] = values[session][instrument_id]


def _assert_ledger_reconciles(ledger: list[dict[str, object]]) -> None:
    for row in ledger:
        position_value = sum(
            Decimal(str(position["adjusted_units"])) * Decimal(str(position["last_adjusted_price"]))
            for position in row["positions"]
        )
        fill_cost = sum(Decimal(str(fill["cost"])) for fill in row["fills"])
        assert Decimal(str(row["net_cash"])) >= 0
        assert Decimal(str(row["gross_cash"])) + position_value == Decimal(str(row["gross_nav"]))
        assert Decimal(str(row["net_cash"])) + position_value == Decimal(str(row["net_nav"]))
        assert fill_cost == Decimal(str(row["transaction_cost_cny"]))


def _run(
    canonical: dict[str, object],
    matrix: dict[str, object],
    *,
    holdings_count: int = 1,
    selection_interval: int = 1,
) -> dict[str, object]:
    return run_strategy(
        aligned_market_data(copy.deepcopy(canonical), universe="manual"),
        copy.deepcopy(matrix),
        _definition(
            holdings_count=holdings_count,
            selection_interval=selection_interval,
        ),
        origin_session=SESSIONS[0],
    )


def _daily_ledger(result: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "session": str(day["session"]),
            "cycle_type": str(day["cycle_type"]),
            "rebalance": bool(day["rebalance"]),
            "gross_cash": Decimal(str(day["gross_cash"])),
            "net_cash": Decimal(str(day["net_cash"])),
            "gross_nav": Decimal(str(day["gross_nav"])),
            "net_nav": Decimal(str(day["net_nav"])),
            "cost": Decimal(str(day["cumulative_transaction_cost"])),
            "holdings_count": int(day["holdings_count"]),
        }
        for day in result["daily"]
    ]


def _orders(result: dict[str, object]) -> list[tuple[str, str, str, int, int]]:
    return [
        (
            str(order["session"]),
            str(order["instrument_id"]),
            str(order["side"]),
            int(order["unrounded_quantity"]),
            int(order["legal_quantity"]),
        )
        for order in result["orders"]
    ]


def _fills(
    result: dict[str, object],
) -> list[tuple[str, str, str, int, Decimal, Decimal, Decimal]]:
    return [
        (
            str(fill["session"]),
            str(fill["instrument_id"]),
            str(fill["side"]),
            int(fill["quantity"]),
            Decimal(str(fill["raw_open"])),
            Decimal(str(fill["raw_notional"])),
            Decimal(str(fill["cost"])),
        )
        for fill in result["fills"]
    ]


def _position_ledger(
    canonical: dict[str, object],
    matrix: dict[str, object],
    *,
    holdings_count: int = 1,
    selection_interval: int = 1,
) -> dict[str, tuple[tuple[str, int, Decimal], ...]]:
    ledger: dict[str, tuple[tuple[str, int, Decimal], ...]] = {}
    for index, session in enumerate(SESSIONS, start=1):
        prefix = _slice_sessions(canonical, set(SESSIONS[:index]))
        result = _run(
            prefix,
            matrix,
            holdings_count=holdings_count,
            selection_interval=selection_interval,
        )
        ledger[session] = tuple(
            (
                str(position["instrument_id"]),
                int(position["execution_shares"]),
                Decimal(str(position["adjusted_units"])),
            )
            for position in result["positions"]
        )
    return ledger


def _slice_sessions(
    canonical: dict[str, object],
    sessions: set[str],
) -> dict[str, object]:
    sliced = copy.deepcopy(canonical)
    sliced["research_calendar"] = [
        session for session in sliced["research_calendar"] if session in sessions
    ]
    for name in ("prices", "trading_states", "price_limits"):
        sliced[name] = [row for row in sliced[name] if row["session"] in sessions]
    sliced["liquidity_universes"] = {
        name: [row for row in rows if row["session"] in sessions]
        for name, rows in sliced["liquidity_universes"].items()
    }
    return sliced


def test_fixed_exposure_targets_pretrade_equity_before_fees_and_rounding():
    canonical = _canonical(opens={session: {A: "10", B: "20"} for session in SESSIONS})
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition()
    definition["strategy"].update({
        "initial_cash_cny": "100000",
        "exposure_expression": {"kind": "number", "value": 0.7},
    })
    result = run_strategy(
        aligned_market_data(canonical, universe="manual"), matrix, definition,
        origin_session=SESSIONS[0],
    )
    first_buy = next(order for order in result["orders"] if order["side"] == "buy")
    assert first_buy["legal_quantity"] == 7000
    first = result["daily"][1]
    assert Decimal(first["net_cash"]) == Decimal("29978.30")
    assert Decimal(first["net_nav"]) == Decimal("99978.30")
    # Next target still uses total equity, not the remaining ~30k cash.
    assert result["positions"][0]["execution_shares"] >= 6900
    assert len([order for order in result["orders"] if order["side"] == "sell"]) <= 1


def test_zero_exposure_preserves_cash_baseline_and_latest_selection():
    canonical = _canonical(opens={session: {A: "10", B: "20"} for session in SESSIONS})
    matrix = _alpha_matrix({
        SESSIONS[0]: ((A, 2), (B, 1)),
        SESSIONS[1]: ((A, 2), (B, 1)),
        SESSIONS[2]: ((B, 2), (A, 1)),
        SESSIONS[3]: ((A, 2), (B, 1)),
    })
    definition = _definition(selection_interval=2)
    definition["strategy"].update({
        "initial_cash_cny": "100000",
        "exposure_expression": {"kind": "number", "value": 0.0},
    })
    result = run_strategy(
        aligned_market_data(canonical, universe="manual"), matrix, definition,
        origin_session=SESSIONS[0],
    )
    assert result["orders"] == []
    assert result["positions"] == []
    assert [Decimal(row["net_nav"]) for row in result["daily"]] == [Decimal("100000")] * 4
    assert [row["rebalance"] for row in result["daily"]] == [False, True, False, True]
    assert result["target_selection"]["selected_instrument_ids"] == [B]
    assert result["target_selection"]["signal_session"] == SESSIONS[2]
    assert result["metrics"]["maximum_drawdown"]["recovery_session"] is None
    assert result["target_exposure"] == 0.0
    assert result["pending_target"] is None


@pytest.mark.parametrize("exposure", [0.0, 0.7])
@pytest.mark.parametrize("interval", [2, 3])
def test_tracking_checkpoint_restores_retained_selection_and_exposure(exposure, interval):
    from thesistrace.daily_track.checkpoint import (
        project_tracking_checkpoint,
        restore_tracking_checkpoint,
        terminal_strategy_state,
    )
    from thesistrace.daily_track.observation_state import initial_tracking_observation_state

    canonical = _canonical(opens={session: {A: "10", B: "20"} for session in SESSIONS})
    state = _kernel_run(canonical, selection_interval=interval, exposure=exposure).track_state
    checkpoint = project_tracking_checkpoint(
        state, retained_strategy_sessions=SESSIONS[1:],
        prior_observation_state=initial_tracking_observation_state(SESSIONS[0], "10000000"),
    )
    restored = restore_tracking_checkpoint(
        checkpoint, research_data=aligned_market_data(canonical, universe="manual"),
    )
    original = checkpoint["strategy_state"]["terminal"]
    actual = terminal_strategy_state(restored)
    assert actual == original
    assert restored.output_snapshot()["alpha_matrix"]["sessions"] == []
    assert actual["target_exposure"] == exposure
    assert actual["target_selection"]["selected_instrument_ids"] == [B]
    assert (actual["pending_target"] is not None) == (interval == 3)
    assert checkpoint["run_input"]["exposure_expression"] == {"kind": "number", "value": exposure}


@pytest.mark.parametrize("blocked,interval", [(False, 5), (True, 5), (False, 1)])
def test_daily_exposure_uses_proportional_reduction_unless_selection_is_due(blocked, interval):
    from thesistrace.alpha_language import alpha_language

    canonical = _canonical(
        limit_overrides={(SESSIONS[3], A): ('14', '12')} if blocked else None,
        opens={
        SESSIONS[0]: {A: '10', B: '10'},
        SESSIONS[1]: {A: '10', B: '10'},
        SESSIONS[2]: {A: '10', B: '10'},
        SESSIONS[3]: {A: '12', B: '8'},
    })
    _set_alpha_closes(canonical, {
        SESSIONS[0]: {A: '10', B: '10'},
        SESSIONS[1]: {A: '11', B: '11'},
        SESSIONS[2]: {A: '9', B: '9'},
        SESSIONS[3]: {A: '9', B: '9'},
    })
    definition = _definition(holdings_count=2, selection_interval=interval)
    definition['strategy']['initial_cash_cny'] = '100000'
    definition['strategy']['exposure_expression'] = alpha_language.compile(
        'if_else(universe_return() > 0, 1, 0.3)', context='exposure',
    ).expression
    definition['costs'] = dict.fromkeys(definition['costs'], '0')
    ledger = []
    result = run_strategy(
        aligned_market_data(canonical, universe='manual'),
        _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS}),
        definition, origin_session=SESSIONS[1], ledger=ledger,
    )
    assert result['target_selection']['signal_session'] == (
        SESSIONS[1] if interval == 5 else SESSIONS[3]
    )
    assert result['target_exposure'] == 0.3
    assert ledger[0]['submitted_orders'] == []
    assert [(row['side'], row['instrument_id']) for row in ledger[1]['submitted_orders']] == [
        ('buy', A), ('buy', B),
    ]
    assert [(row['instrument_id'], Decimal(row['intended_value']))
            for row in ledger[2]['intended_orders']] == [
                (A, Decimal('42000' if interval == 5 else '45000')),
                (B, Decimal('28000' if interval == 5 else '25000')),
            ]
    assert [(row['instrument_id'], row['execution_shares'])
            for row in ledger[2]['positions']] == (
        [(A, 5000 if blocked else 1500), (B, 1500)] if interval == 5
        else [(A, 1300), (B, 1900)]
    )
    assert Decimal(ledger[2]['net_cash']) == (
        (28000 if blocked else 70000) if interval == 5 else 69200
    )
    _assert_ledger_reconciles(ledger)


@pytest.mark.parametrize('initial,next_value,last_open,expected_shares,expected_cash', [
    (0.3, 0.7, {A: '40', B: '10'}, {A: 1500, B: 4100}, '44000'),
    (0.7, 0.3, {A: '1', B: '1'}, {A: 3500, B: 3500}, '30000'),
    (0.0, 0.7, {A: '10', B: '10'}, {A: 3500, B: 3500}, '30000'),
])
def test_daily_exposure_only_adjustment_respects_direction_and_total_buy_budget(
    initial, next_value, last_open, expected_shares, expected_cash,
):
    from thesistrace.alpha_language import alpha_language

    canonical = _canonical(opens={
        SESSIONS[0]: {A: '10', B: '10'},
        SESSIONS[1]: {A: '10', B: '10'},
        SESSIONS[2]: {A: '10', B: '10'},
        SESSIONS[3]: last_open,
    })
    _set_alpha_closes(canonical, {
        SESSIONS[0]: {A: '10', B: '10'},
        SESSIONS[1]: {A: '11', B: '11'},
        SESSIONS[2]: {A: '9', B: '9'},
        SESSIONS[3]: {A: '9', B: '9'},
    })
    definition = _definition(holdings_count=2, selection_interval=5)
    definition['strategy']['initial_cash_cny'] = '100000'
    definition['strategy']['exposure_expression'] = alpha_language.compile(
        f'if_else(universe_return() > 0, {initial}, {next_value})', context='exposure',
    ).expression
    definition['costs'] = dict.fromkeys(definition['costs'], '0')
    ledger = []
    result = run_strategy(
        aligned_market_data(canonical, universe='manual'),
        _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS}),
        definition, origin_session=SESSIONS[1], ledger=ledger,
    )
    assert result['target_selection']['signal_session'] == SESSIONS[1]
    assert result['pending_target'] is None
    assert {row['instrument_id']: row['execution_shares']
            for row in ledger[-1]['positions']} == expected_shares
    assert Decimal(ledger[-1]['net_cash']) == Decimal(expected_cash)
    assert all(row['side'] == 'buy' for row in ledger[-1]['submitted_orders'])
    if initial > next_value:
        assert ledger[-1]['submitted_orders'] == []
    _assert_ledger_reconciles(ledger)



@pytest.mark.parametrize("blocked", [False, True])
def test_daily_exposure_keeps_new_selection_while_cash_then_restores_without_retry(blocked):
    from thesistrace.alpha_language import alpha_language

    sessions = tuple(f"2026-01-{day:02d}" for day in (5, 6, 7, 8, 9, 12, 13, 14, 15))
    closes = (100, 110, 99, 79.2, 63.36, 50.688, 40.5504, 44.60544, 49.065984)
    canonical = _canonical(
        sessions=sessions, opens={session: {A: '10', B: '10'} for session in sessions},
        limit_overrides={(sessions[4], A): ('11', '10')} if blocked else None,
    )
    _set_alpha_closes(canonical, {
        session: {A: str(close), B: str(close)}
        for session, close in zip(sessions, closes, strict=True)
    })
    definition = _definition(holdings_count=1, selection_interval=5)
    definition['strategy']['initial_cash_cny'] = '100000'
    definition['strategy']['exposure_expression'] = alpha_language.compile(
        'if_else(universe_return() > 0, 1, if_else(universe_return() > -0.15, 0.3, 0))',
        context='exposure',
    ).expression
    definition['costs'] = dict.fromkeys(definition['costs'], '0')
    matrix = _alpha_matrix({
        session: (((A, 2), (B, 1)) if index == 1 else ((B, 2), (A, 1)))
        for index, session in enumerate(sessions)
    })
    ledger = []
    result = run_strategy(
        aligned_market_data(canonical, universe='manual'), matrix, definition,
        origin_session=sessions[1], ledger=ledger,
    )
    assert [(row['session'], order['instrument_id'], order['side'])
            for row in ledger for order in row['submitted_orders']] == [
        (sessions[2], A, 'buy'), (sessions[3], A, 'sell'),
        (sessions[4], A, 'sell'),
        *([(sessions[7], A, 'sell')] if blocked else []),
        (sessions[8], B, 'buy'),
    ]
    assert result['target_selection']['signal_session'] == sessions[6]
    assert result['target_selection']['selected_instrument_ids'] == [B]
    assert result['pending_target'] is None
    assert [row['instrument_id'] for row in result['positions']] == [B]
    assert all(row['positions'] == [] for row in ledger[6:7])
    assert ledger[4]['submitted_orders'] == ledger[5]['submitted_orders'] == []
    if blocked:
        assert ledger[3]['rejections'][0]['reason'] == 'lower_limit_sell'
        assert all(row['positions'][0]['execution_shares'] == 3000 for row in ledger[3:6])
    else:
        assert all(row['positions'] == [] for row in ledger[3:7])
    assert Decimal(ledger[2]['net_cash']) == 70000
    assert Decimal(ledger[3]['net_cash']) == (70000 if blocked else 100000)
    _assert_ledger_reconciles(ledger)


def test_rank_weighted_selection_survives_cash_and_drives_exposure_restore():
    from thesistrace.alpha_language import alpha_language

    canonical = _canonical(opens={session: {A: '10', B: '10'} for session in SESSIONS})
    _set_alpha_closes(canonical, {
        session: {A: close, B: close}
        for session, close in zip(SESSIONS, ('10', '9', '11', '11'), strict=True)
    })
    definition = _definition(holdings_count=2, selection_interval=5)
    definition['strategy']['weighting'] = 'rank_weight'
    definition['strategy']['initial_cash_cny'] = '100000'
    definition['strategy']['exposure_expression'] = alpha_language.compile(
        'if_else(universe_return() > 0, 0.6, 0)', context='exposure',
    ).expression
    definition['costs'] = dict.fromkeys(definition['costs'], '0')
    ledger = []
    result = run_strategy(
        aligned_market_data(canonical, universe='manual'),
        _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS}),
        definition, origin_session=SESSIONS[1], ledger=ledger,
    )
    selection = result['target_selection']
    assert selection['signal_session'] == SESSIONS[1]
    assert selection['relative_weights'] == {A: '2/3', B: '1/3'}
    assert ledger[0]['positions'] == ledger[1]['positions'] == []
    assert [(row['instrument_id'], row['execution_shares']) for row in ledger[2]['positions']] == [
        (A, 4000), (B, 2000),
    ]
    assert Decimal(ledger[2]['net_cash']) == Decimal('40000')
    _assert_ledger_reconciles(ledger)


@pytest.mark.parametrize('future_close', ['10', '999'])
def test_inverse_volatility_targets_use_only_decision_close_history(future_close):
    canonical = _canonical(opens={session: {A: '10', B: '10'} for session in SESSIONS})
    _set_alpha_closes(canonical, {
        SESSIONS[0]: {A: '100', B: '100'},
        SESSIONS[1]: {A: '100', B: '100'},
        SESSIONS[2]: {A: '120', B: '140'},
        SESSIONS[3]: {A: future_close, B: '1'},
    })
    definition = _definition(holdings_count=2, selection_interval=5)
    definition['strategy'].update({
        'weighting': 'inverse_volatility', 'volatility_window': 2,
        'initial_cash_cny': '100000',
        'exposure_expression': {'kind': 'number', 'value': 0.6},
    })
    definition['costs'] = dict.fromkeys(definition['costs'], '0')
    result = run_strategy(
        aligned_market_data(canonical, universe='manual'),
        _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS}),
        definition, origin_session=SESSIONS[2],
    )
    assert result['target_selection']['relative_weights'] == {A: '2/3', B: '1/3'}
    assert {row['instrument_id']: row['execution_shares'] for row in result['positions']} == {
        A: 4000, B: 2000,
    }
    assert Decimal(result['daily'][-1]['net_cash']) == Decimal('40000')


@pytest.mark.parametrize('exposure', [0.0, 1.0])
def test_empty_inverse_selection_keeps_exposure_and_records_eligibility(exposure):
    canonical = _canonical(opens={session: {A: '10', B: '10'} for session in SESSIONS})
    _set_alpha_closes(canonical, {session: {A: '100', B: '100'} for session in SESSIONS})
    definition = _definition(holdings_count=2, selection_interval=5)
    definition['strategy'].update({
        'weighting': 'inverse_volatility', 'volatility_window': 2,
        'initial_cash_cny': '100000',
        'exposure_expression': {'kind': 'number', 'value': exposure},
    })
    result = run_strategy(
        aligned_market_data(canonical, universe='manual'),
        _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS}),
        definition, origin_session=SESSIONS[2],
    )
    assert result['target_selection']['eligibility_exclusions'] == {'zero_volatility': 2}
    assert result['target_selection']['signal_session'] == SESSIONS[2]
    assert result['target_selection']['selected_instrument_ids'] == []
    assert result['target_exposure'] == exposure
    assert result['positions'] == result['orders'] == []
    assert Decimal(result['daily'][-1]['net_cash']) == Decimal('100000')

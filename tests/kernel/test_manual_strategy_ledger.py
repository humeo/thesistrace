from __future__ import annotations

import copy
from decimal import Decimal

from contracts import CLOSE_ADJUSTED, FIELD_BINDINGS

from thesistrace.research_kernel.alpha import evaluate_alpha_matrix
from thesistrace.research_kernel.strategy import run_strategy

SESSIONS = ("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08")
A = "equity:600001.SH"
B = "equity:600002.SH"


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
            "cycle_type": "terminal_valuation",
            "rebalance": False,
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
    matrix = _alpha_matrix(
        {session: ((A, 2), (B, 1)) for session in SESSIONS}
    )

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
            "cycle_type": "terminal_valuation",
            "rebalance": False,
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


def test_manual_rejections_never_create_false_fills_or_discard_a_holding() -> None:
    upper_limit_buy = _canonical(
        opens={session: {A: "10", B: "20"} for session in SESSIONS},
        limit_overrides={(SESSIONS[1], A): ("10", "9")},
    )
    buy_matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})

    rejected_buy = _run(upper_limit_buy, buy_matrix, rebalance_interval=20)

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
    assert _position_ledger(upper_limit_buy, buy_matrix, rebalance_interval=20) == {
        session: () for session in SESSIONS
    }
    assert all(day["net_cash"] == Decimal("10000000") for day in _daily_ledger(rejected_buy))

    suspended_buy = _canonical(
        opens={
            SESSIONS[0]: {A: "10", B: "20"},
            SESSIONS[1]: {A: None, B: "20"},
            SESSIONS[2]: {A: "10", B: "20"},
            SESSIONS[3]: {A: "10", B: "20"},
        },
        states={(SESSIONS[1], A): "full_session_suspension"},
    )

    rejected_suspension = _run(suspended_buy, buy_matrix, rebalance_interval=20)

    assert _fills(rejected_suspension) == []
    assert rejected_suspension["rejections"][0]["reason"] == "suspension"
    assert _position_ledger(suspended_buy, buy_matrix, rebalance_interval=20) == {
        session: () for session in SESSIONS
    }

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
    assert all(fill[2] != "sell" for fill in _fills(rejected_sell))
    assert any(item["reason"] == "lower_limit_sell" for item in rejected_sell["rejections"])
    assert _position_ledger(lower_limit_sell, sell_matrix)[SESSIONS[2]] == (
        (A, 999_600, Decimal("999600")),
    )


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

    result = _run(canonical, matrix, rebalance_interval=20)
    ledger = _daily_ledger(result)

    assert ledger[1]["net_nav"] == Decimal("9996901.24")
    assert ledger[2]["net_nav"] == ledger[1]["net_nav"]
    assert ledger[3]["net_nav"] == ledger[1]["net_nav"]
    assert _position_ledger(canonical, matrix, rebalance_interval=20) == {
        SESSIONS[0]: (),
        SESSIONS[1]: ((A, 999_600, Decimal("999600")),),
        SESSIONS[2]: ((A, 999_600, Decimal("999600")),),
        SESSIONS[3]: ((A, 999_600, Decimal("999600")),),
    }
    assert _orders(result) == [(SESSIONS[1], A, "buy", 1_000_000, 999_600)]


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
        canonical,
        expression=CLOSE_ADJUSTED,
        field_bindings=FIELD_BINDINGS,
        universe_name="manual",
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
    assert _position_ledger(canonical, matrix)[SESSIONS[2]] == (
        (B, 499_200, Decimal("499200")),
    )


def _canonical(
    *,
    opens: dict[str, dict[str, str | tuple[str, str] | None]],
    states: dict[tuple[str, str], str] | None = None,
    universes: dict[str, tuple[str, ...]] | None = None,
    limit_overrides: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> dict[str, object]:
    selected_states = states or {}
    selected_universes = universes or {session: (A, B) for session in SESSIONS}
    selected_limits = limit_overrides or {}
    prices: list[dict[str, object]] = []
    trading_states: list[dict[str, object]] = []
    price_limits: list[dict[str, object]] = []
    for session in SESSIONS:
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
        "research_calendar": list(SESSIONS),
        "instruments": [
            {
                "instrument_id": A,
                "board": "main",
                "listed_from": SESSIONS[0],
                "listed_to": "",
            },
            {
                "instrument_id": B,
                "board": "main",
                "listed_from": SESSIONS[0],
                "listed_to": "",
            },
        ],
        "prices": prices,
        "trading_states": trading_states,
        "price_limits": price_limits,
        "liquidity_universes": {
            "manual": [
                {"session": session, "instrument_ids": list(selected_universes[session])}
                for session in SESSIONS
            ]
        },
        "industry_membership": [],
        "st_designations": [],
    }


def _alpha_matrix(
    values: dict[str, tuple[tuple[str, int], ...]],
) -> dict[str, object]:
    return {
        "checksum": "manual-alpha-v1",
        "value_store": {
            session: [
                {"instrument_id": instrument_id, "value": value}
                for instrument_id, value in rows
            ]
            for session, rows in values.items()
        },
    }


def _definition(
    *,
    holdings_count: int = 1,
    rebalance_interval: int = 1,
) -> dict[str, object]:
    return {
        "universe": "manual",
        "strategy": {
            "holdings_count": holdings_count,
            "rebalance_interval": rebalance_interval,
            "initial_cash_cny": "10000000",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
    }


def _run(
    canonical: dict[str, object],
    matrix: dict[str, object],
    *,
    holdings_count: int = 1,
    rebalance_interval: int = 1,
    terminal_cutoff: bool = True,
) -> dict[str, object]:
    return run_strategy(
        copy.deepcopy(canonical),
        copy.deepcopy(matrix),
        _definition(
            holdings_count=holdings_count,
            rebalance_interval=rebalance_interval,
        ),
        origin_session=SESSIONS[0],
        terminal_cutoff=terminal_cutoff,
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
    rebalance_interval: int = 1,
) -> dict[str, tuple[tuple[str, int, Decimal], ...]]:
    ledger: dict[str, tuple[tuple[str, int, Decimal], ...]] = {}
    for index, session in enumerate(SESSIONS, start=1):
        prefix = _slice_sessions(canonical, set(SESSIONS[:index]))
        result = _run(
            prefix,
            matrix,
            holdings_count=holdings_count,
            rebalance_interval=rebalance_interval,
            terminal_cutoff=index == len(SESSIONS),
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

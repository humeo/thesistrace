from __future__ import annotations

from thesistrace.data.canonical_mapping import liquidity_universes


def test_coverage_start_expands_until_the_twentieth_session() -> None:
    sessions = _sessions(20)
    instrument_ids = ("equity:A.SH", "equity:B.SH")
    turnover_by_instrument = {
        "equity:A.SH": [100] * 20,
        "equity:B.SH": [50, 300, *([0] * 17), 2000],
    }

    universes = liquidity_universes(
        sessions,
        _base_pool(sessions, instrument_ids),
        _prices(sessions, turnover_by_instrument),
        _states(sessions, tuple(turnover_by_instrument)),
    )
    rows = universes["top300"]

    assert rows[0] == {
        "session": sessions[0],
        "instrument_ids": ["equity:A.SH", "equity:B.SH"],
        "status": "available",
    }
    assert rows[1]["instrument_ids"] == ["equity:B.SH", "equity:A.SH"]
    assert rows[18]["instrument_ids"] == ["equity:A.SH", "equity:B.SH"]
    assert rows[19]["instrument_ids"] == ["equity:B.SH", "equity:A.SH"]


def test_instrument_listed_after_coverage_start_gets_no_private_expansion() -> None:
    sessions = _sessions(21)
    instrument_id = "equity:LATE.SH"
    base_pool = [
        {"session": session, "instrument_ids": [] if index == 0 else [instrument_id]}
        for index, session in enumerate(sessions)
    ]
    prices = _prices(sessions[1:], {instrument_id: [1000] * 20})
    states = [
        {
            "session": sessions[0],
            "instrument_id": instrument_id,
            "state": "full_session_suspension",
        },
        *_states(sessions[1:], (instrument_id,)),
    ]

    initial_rows = liquidity_universes(
        sessions[:20],
        base_pool[:20],
        prices[:-1],
        states[:-1],
    )["top300"]
    recomputed_rows = liquidity_universes(sessions, base_pool, prices, states)["top300"]
    before, mature = recomputed_rows[19:]

    assert recomputed_rows[:20] == initial_rows
    assert before["instrument_ids"] == []
    assert mature["instrument_ids"] == [instrument_id]


def test_governed_suspension_and_missing_turnover_have_distinct_semantics() -> None:
    sessions = _sessions(20)
    full = "equity:FULL.SH"
    partial = "equity:PARTIAL.SH"
    missing = "equity:MISSING.SH"
    instrument_ids = (full, partial, missing)
    prices = _prices(
        sessions,
        {
            full: [*([100] * 9), 100000, *([100] * 10)],
            partial: [*([100] * 9), 200, *([100] * 10)],
            missing: [10000] * 20,
        },
    )
    prices = [
        row
        for row in prices
        if not (row["session"] == sessions[9] and row["instrument_id"] == missing)
    ]
    states = _states(sessions, instrument_ids)
    for row in states:
        if row["session"] == sessions[9] and row["instrument_id"] == full:
            row["state"] = "full_session_suspension"
        if row["session"] == sessions[9] and row["instrument_id"] == partial:
            row["state"] = "partial_opening_suspension"

    ranked = liquidity_universes(
        sessions,
        _base_pool(sessions, instrument_ids),
        prices,
        states,
    )["top300"][-1]["instrument_ids"]

    assert ranked == [partial, full]
    assert missing not in ranked


def test_every_top_n_is_a_prefix_of_one_tie_broken_ordering() -> None:
    sessions = _sessions(1)
    instrument_ids = [f"equity:{index:04d}.SH" for index in range(3001, 0, -1)]
    prices = _prices(sessions, {instrument_id: [100] for instrument_id in instrument_ids})
    expected = sorted(instrument_ids)

    universes = liquidity_universes(
        sessions,
        _base_pool(sessions, tuple(instrument_ids)),
        prices,
        _states(sessions, tuple(instrument_ids)),
    )

    for size in (300, 1000, 2000, 3000):
        row = universes[f"top{size}"][0]
        assert row["status"] == "available"
        assert row["instrument_ids"] == expected[:size]


def _sessions(count: int) -> list[str]:
    return [f"2024-01-{ordinal:02d}" for ordinal in range(1, count + 1)]


def _base_pool(sessions: list[str], instrument_ids: tuple[str, ...]) -> list[dict[str, object]]:
    return [{"session": session, "instrument_ids": list(instrument_ids)} for session in sessions]


def _prices(
    sessions: list[str],
    turnover_by_instrument: dict[str, list[int]],
) -> list[dict[str, str]]:
    return [
        {
            "session": session,
            "instrument_id": instrument_id,
            "turnover_cny": str(values[index]),
            "volume_shares": str(10**12 - values[index]),
        }
        for index, session in enumerate(sessions)
        for instrument_id, values in turnover_by_instrument.items()
    ]


def _states(sessions: list[str], instrument_ids: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {"session": session, "instrument_id": instrument_id, "state": "normal"}
        for session in sessions
        for instrument_id in instrument_ids
    ]

from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _alpha_matrix, _canonical, _definition

from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_series import slice_research_sessions


def _scenario():
    data = aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}),
        universe="manual",
    )
    matrix = _alpha_matrix(
        {
            session: ((A if index % 2 == 0 else B, 2), (B if index % 2 == 0 else A, 1))
            for index, session in enumerate(SESSIONS)
        }
    )
    definition = _definition(selection_interval=1)
    definition["strategy"]["initial_cash_cny"] = "100000"
    return data, matrix, definition


def test_last_open_trades_and_resume_is_the_completed_account():
    data, matrix, definition = _scenario()
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    daily = result.finalized["daily"]
    assert daily[0]["holdings_count"] == 0
    assert Decimal(daily[0]["net_nav"]) == Decimal("100000")
    assert daily[-1]["cycle_type"] == "open"
    assert daily[-1]["rebalance"] is True
    assert {
        fill["side"] for fill in result.finalized["fills"] if fill["session"] == SESSIONS[-1]
    } == {"sell", "buy"}
    assert Decimal(daily[-1]["cumulative_transaction_cost"]) > Decimal(
        daily[-2]["cumulative_transaction_cost"]
    )
    assert result.resumable == result.finalized


@pytest.mark.parametrize("cut", [1, 2, 3])
def test_advance_preserves_every_published_day_at_trading_boundaries(cut):
    data, matrix, definition = _scenario()
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:cut]),
        matrix,
        definition,
        origin_session=SESSIONS[0],
    )
    advanced = transition_strategy(
        data,
        matrix,
        definition,
        origin_session=SESSIONS[0],
        continuation=prefix.resumable,
    )
    whole = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    assert advanced.finalized["daily"][:cut] == prefix.finalized["daily"]
    assert advanced.finalized == whole.finalized


def test_next_open_uses_frozen_selection_when_past_alpha_is_unavailable():
    data, matrix, definition = _scenario()
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]),
        matrix,
        definition,
        origin_session=SESSIONS[0],
    )
    future_matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS[2:]})
    advanced = transition_strategy(
        data,
        future_matrix,
        definition,
        origin_session=SESSIONS[0],
        continuation=prefix.resumable,
    )
    assert any(
        fill["session"] == SESSIONS[2] and fill["instrument_id"] == B and fill["side"] == "buy"
        for fill in advanced.finalized["fills"]
    )
    assert advanced.finalized["daily"][:2] == prefix.finalized["daily"]


@pytest.mark.parametrize("weights", [
    {A: "1/2"}, {B: "1"}, {A: "nan"}, {A: "-1"}, {A: 1.0}, {A: "2/2"},
])
def test_resume_rejects_invalid_frozen_weights(weights):
    import copy

    data, matrix, definition = _scenario()
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:1]),
        matrix,
        definition,
        origin_session=SESSIONS[0],
    )
    invalid = copy.deepcopy(prefix.resumable)
    invalid["pending_target"]["allocation"]["relative_weights"] = weights
    with pytest.raises(ValueError, match="(Target weights|Pending target|relative_weights)"):
        transition_strategy(
            data, matrix, definition, origin_session=SESSIONS[0], continuation=invalid
        )


def test_resume_rejects_pending_decision_from_different_contract():
    import copy

    data, matrix, definition = _scenario()
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:1]),
        matrix,
        definition,
        origin_session=SESSIONS[0],
    )
    invalid = copy.deepcopy(prefix.resumable)
    invalid["pending_target"]["contract_checksum"] = "different-contract"
    with pytest.raises(RuntimeError, match="Pending decision differs"):
        transition_strategy(
            data, matrix, definition, origin_session=SESSIONS[0], continuation=invalid
        )

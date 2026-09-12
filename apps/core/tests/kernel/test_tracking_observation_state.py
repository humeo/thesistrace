from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest

from thesistrace.daily_track.observation_state import (
    advance_tracking_observation_state,
    initial_tracking_observation_state,
    tracking_maximum_drawdown,
)
from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT


def test_completed_peak_and_loss_survive_later_advances():
    initial = initial_tracking_observation_state("2026-01-01", "100")
    first = advance_tracking_observation_state(initial, [
        {"session": "2026-01-02", "net_nav": "200"},
    ])
    assert tracking_maximum_drawdown(first, "200") == 0
    with pytest.raises(ValueError, match="completed boundary"):
        advance_tracking_observation_state(first, [
            {"session": "2026-01-02", "net_nav": "100"},
        ])
    fallen = advance_tracking_observation_state(first, [
        {"session": "2026-01-05", "net_nav": "90"},
    ])
    assert tracking_maximum_drawdown(fallen, "90") == Decimal("0.55")
    recovered = advance_tracking_observation_state(fallen, [
        {"session": "2026-01-06", "net_nav": "220"},
    ])
    assert tracking_maximum_drawdown(recovered, "220") == Decimal("0.55")


@pytest.mark.parametrize("trough_index", [7, 777])
def test_multi_day_advances_match_independent_full_history_after_504_sessions(trough_index):
    sessions = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(1001)]
    state = initial_tracking_observation_state(sessions[0], "100")
    history = {sessions[0]: Decimal(100)}
    for start in range(0, 1000, 10):
        rows = []
        for index in range(start + 1, start + 11):
            nav = Decimal(80 if index == trough_index else 100 + index % 11)
            history[sessions[index]] = nav
            rows.append({"session": sessions[index], "net_nav": str(nav)})
        state = advance_tracking_observation_state(state, rows)
        with localcontext(ACCOUNTING_CONTEXT):
            # Independent pairwise peak/trough reference, not the incremental algorithm.
            values = [Decimal(100), *history.values()]
            expected = max(Decimal(1) - value / max(values[:i + 1])
                           for i, value in enumerate(values))
        assert tracking_maximum_drawdown(state, rows[-1]["net_nav"]) == expected


@pytest.mark.parametrize("rows", [[], [{"session": "2026-01-01", "net_nav": "100"}],
    [{"session": "2026-01-01", "net_nav": "0"}],
    [{"session": "2026-01-01", "net_nav": "NaN"}],
])
def test_invalid_or_disconnected_advances_are_rejected(rows):
    state = initial_tracking_observation_state("2026-01-01", "100")
    with pytest.raises(ValueError):
        advance_tracking_observation_state(state, rows)

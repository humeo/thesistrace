"""Author programs produce multiple Close decisions through the shared simulator."""

import numpy as np
import pytest
from test_direct_strategy_execution import inputs
from test_manual_strategy_ledger import SESSIONS, A, B

from thesistrace.research_kernel.program_wire import decode_state
from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_kernel.strategy_program_runtime import PythonStrategyRuntime
from thesistrace.research_series import slice_research_sessions

pytestmark = pytest.mark.bounded_process

SOURCE = """
import numpy as np
from quantgrove import Targets

def compute(data, state):
    prices = data.history("price.close.adjusted", lookback=0)
    chosen = np.zeros(prices.shape, dtype=bool)
    np.put_along_axis(chosen, np.argmax(prices, axis=0)[None, :], True, axis=0)
    state["days"] = state.get("days", 0) + len(data.sessions)
    return Targets.equal_weight(chosen, update=np.ones(len(data.sessions), dtype=bool))
"""


def batch_inputs(source=SOURCE):
    data, definition = inputs()
    definition["strategy"]["program"]["source"] = source
    return data, definition


def test_batch_targets_execute_at_next_open_and_continue_exactly():
    data, definition = batch_inputs()
    whole = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    assert [
        (row["session"], row["instrument_id"], row["side"], row["quantity"])
        for row in whole["fills"]
    ] == [
        (SESSIONS[1], A, "buy", 10000),
        (SESSIONS[2], A, "sell", 10000),
        (SESSIONS[2], B, "buy", 10000),
    ]
    assert whole["decision_state"]["state"]["compute"] == {"days": 4}
    assert whole["pending_target"]["allocation"]["instrument_ids"] == [A]
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), None, definition, origin_session=SESSIONS[0]
    ).resumable
    continued = transition_strategy(
        data, None, definition, origin_session=SESSIONS[0], continuation=prefix
    ).finalized
    # Read diagnostics describe different chunks; economic decisions and state are identical.
    for key in ("daily", "fills", "positions", "pending_target", "decision_state"):
        assert continued[key] == whole[key]


ACCOUNT_SOURCE = """
import numpy as np
from quantgrove import Values, target_weights

def compute(data, state):
    prices = data.history("price.close.adjusted", lookback=0)
    state["last_prices"] = prices[:, -1].copy()
    state["days"] = state.get("days", 0) + len(data.sessions)
    return Values({"close": prices})

def decide(data, account, state):
    assert "last_prices" not in state
    assert data.values["close"].shape == (len(data.instruments),)
    best = data.instruments[int(np.argmax(data.values["close"]))]
    state["days"] = state.get("days", 0) + 1
    if [row["instrument_id"] for row in account.positions] != [best]:
        return target_weights({best: 1})
"""


def test_batched_values_feed_current_account_and_separate_array_state():
    data, definition = batch_inputs(ACCOUNT_SOURCE)
    whole = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    state = decode_state(whole["decision_state"]["state"])
    assert state["decision"] == {"days": 4}
    assert state["compute"]["days"] == 4
    np.testing.assert_array_equal(state["compute"]["last_prices"], [100, 30])
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), None, definition, origin_session=SESSIONS[0]
    ).resumable
    continued = transition_strategy(
        data, None, definition, origin_session=SESSIONS[0], continuation=prefix
    ).finalized
    for key in ("daily", "fills", "positions", "pending_target", "decision_state"):
        assert continued[key] == whole[key]


def test_private_program_session_loads_once_and_exports_state_at_checkpoint():
    runtime = PythonStrategyRuntime()
    source = """
print("program loaded")
def decide(data, account, state):
    state["days"] = state.get("days", 0) + 1
"""
    with runtime.open_session(source) as session:
        first = session.invoke(context={}, state={}, checkpoint=False)
        second = session.invoke(context={}, state={}, checkpoint=True)
        assert first.state == {}
        assert first.diagnostics == "program loaded\n"
        assert second.state == {"days": 2}
        assert second.diagnostics == ""
    with runtime.open_session(source) as restored:
        result = restored.invoke(context={}, state=second.state)
        assert result.state == {"days": 3}
        assert result.diagnostics == "program loaded\n"


def test_batch_common_input_uses_governed_historical_membership():
    source = """
import numpy as np
from quantgrove import Targets

def compute(data, state):
    returns = data.common("universe_return")
    state["returns"] = returns.copy()
    return Targets(np.zeros(data.eligible.shape), update=np.zeros(len(data.sessions), dtype=bool))
"""
    data, definition = batch_inputs(source)
    # Membership on day 2 changes the governed mean: only B's +200% counts.
    data.historical_universe_members[SESSIONS[1]] = (B,)
    whole = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    state = decode_state(whole["decision_state"]["state"])["compute"]
    np.testing.assert_array_equal(state["returns"], [np.nan, 2.0, 0.0, 2.0])


def test_batch_rejects_a_future_dependent_first_target_before_account_progress():
    source = '''
import numpy as np
from quantgrove import Targets

def compute(data, state):
    prices = data.history("price.close.adjusted")
    chosen = np.zeros(prices.shape, dtype=bool)
    chosen[np.argmax(prices[:, -1]), :] = True
    state["uncommitted"] = True
    return Targets.equal_weight(chosen, update=np.ones(len(data.sessions), dtype=bool))
'''
    data, definition = batch_inputs(source)
    # Day 2 chooses B; the full block's last day chooses A. Prefix checking must reject it.
    data.fields['price.close.adjusted'][(SESSIONS[0], A)] = '1'
    from thesistrace.research_kernel.strategy_program_runtime import StrategyProgramError
    with pytest.raises(StrategyProgramError, match='prefix'):
        transition_strategy(data, None, definition, origin_session=SESSIONS[0])


def test_128_date_boundary_matches_64_date_restore_and_daily_append():
    from datetime import date, timedelta

    from series import aligned_market_data
    from test_manual_strategy_ledger import _canonical

    dates = tuple((date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(130))
    data = aligned_market_data(_canonical(
        sessions=dates, opens={day: {A: '10', B: '20'} for day in dates},
    ), universe='manual')
    _, definition = batch_inputs(SOURCE)
    whole = transition_strategy(data, None, definition, origin_session=dates[0]).finalized
    prefix = transition_strategy(slice_research_sessions(data, dates[:64]), None, definition,
                                 origin_session=dates[0]).resumable
    restored = transition_strategy(slice_research_sessions(data, dates[:129]), None, definition,
                                   origin_session=dates[0], continuation=prefix).resumable
    appended = transition_strategy(data, None, definition, origin_session=dates[0],
                                   continuation=restored).finalized
    assert whole['decision_state']['state']['compute'] == {'days': 130}
    for key in ('daily', 'fills', 'positions', 'pending_target', 'decision_state'):
        assert appended[key] == whole[key]


def test_batch_history_coordinates_keep_absent_warmup_dates_empty():
    source = '''
import numpy as np
from quantgrove import Targets

def compute(data, state):
    prices = data.history("price.close.adjusted", lookback=2)
    dates = data.history_sessions("price.close.adjusted", lookback=2)
    assert len(dates) == prices.shape[1]
    assert dates[-len(data.sessions):] == data.sessions
    state["dates"] = list(dates)
    return Targets(np.zeros(data.eligible.shape), update=np.zeros(len(data.sessions), dtype=bool))
'''
    data, definition = batch_inputs(source)
    result = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    assert result["decision_state"]["state"]["compute"]["dates"] == [None, None, *SESSIONS]


def test_native_batch_history_accepts_128_dates_with_252_warmup_beyond_daily_limits():
    from datetime import date, timedelta

    from thesistrace.research_history import HistoryWindow
    from thesistrace.research_kernel.program_wire import array_to_wire

    dates = tuple((date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(380))
    stocks = tuple(f"stock:{i:04d}" for i in range(1400))
    result = PythonStrategyRuntime().invoke(
        '''import numpy as np
from quantgrove import Targets

def compute(data, state):
    prices = data.history("price.close.adjusted", lookback=252)
    assert prices.shape == (1400, 380)
    assert prices[0, 0] == 1 and prices[-1, -1] == 1
    return Targets.equal_weight(data.eligible, update=np.zeros(128, dtype=bool))
''',
        context={
            "session": dates[-1],
            "block": {
                "sessions": list(dates[-128:]), "instruments": list(stocks),
                "session_index": list(range(128)),
                "eligible": array_to_wire(np.ones((1400, 128), dtype=bool)),
            },
        },
        state={}, operation="compute",
        read_history=lambda request: HistoryWindow(dates, stocks, np.ones((1400, 380))),
    )
    assert result.output["kind"] == "targets"
    assert result.history_reads[0]["returned_sessions"] == 380
    assert result.history_reads[0]["response_bytes"] > 4 * 1024 * 1024


@pytest.mark.parametrize("priority", [False, True])
def test_batch_buy_priority_matches_ordered_daily_targets_when_cash_is_limited(priority):
    source = """
import numpy as np
from quantgrove import Targets

def compute(data, state):
    chosen = np.ones(data.eligible.shape, dtype=bool)
    scores = np.tile(np.array([[1.0], [2.0]]), (1, len(data.sessions)))
    return Targets.equal_weight(chosen, update=data.session_index == 0, PRIORITY)
""".replace("PRIORITY", "priority=scores" if priority else "")
    daily_source = """
from quantgrove import target_weights

def decide(data, account, state):
    if data.completed_sessions == 1:
        ordered = list(reversed(data.instruments)) if PRIORITY else list(data.instruments)
        return target_weights({stock: 0.5 for stock in ordered})
""".replace("PRIORITY", str(priority))
    data, definition = batch_inputs(source)
    definition["costs"]["commission_rate_all_in"] = "0.1"
    batch = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    definition["strategy"]["program"]["source"] = daily_source
    daily = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    expected = [B, A] if priority else [A, B]
    assert [row["instrument_id"] for row in batch["fills"][:2]] == expected
    assert [row["quantity"] for row in batch["fills"][:2]] == [5000, 4000]
    for key in ("daily", "positions"):
        assert batch[key] == daily[key]


@pytest.mark.parametrize("expression", ["np.zeros((1, 1))", "np.full(data.eligible.shape, np.nan)"])
def test_batch_rejects_misaligned_or_nonfinite_selected_priority(expression):
    from thesistrace.research_kernel.strategy_program_runtime import StrategyProgramError

    source = """
import numpy as np
from quantgrove import Targets

def compute(data, state):
    return Targets.equal_weight(data.eligible, update=np.ones(len(data.sessions), dtype=bool),
                                priority=EXPRESSION)
""".replace("EXPRESSION", expression)
    data, definition = batch_inputs(source)
    with pytest.raises(StrategyProgramError, match="priority"):
        transition_strategy(data, None, definition, origin_session=SESSIONS[0])


def test_batch_prefix_checks_target_priority_before_account_progress():
    from thesistrace.research_kernel.strategy_program_runtime import StrategyProgramError

    source = """
import numpy as np
from quantgrove import Targets

def compute(data, state):
    prices = data.history("price.close.adjusted")
    return Targets.equal_weight(data.eligible, update=np.ones(len(data.sessions), dtype=bool),
                                priority=np.tile(prices[:, -1:], (1, len(data.sessions))))
"""
    data, definition = batch_inputs(source)
    with pytest.raises(StrategyProgramError, match="prefix"):
        transition_strategy(data, None, definition, origin_session=SESSIONS[0])


def test_sparse_selected_priorities_keep_128_date_targets_within_a_small_wire_budget():
    import json
    from datetime import date, timedelta

    from thesistrace.research_kernel.program_wire import array_to_wire

    dates = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(128)]
    stocks = [f"stock:{i:04d}" for i in range(3000)]
    result = PythonStrategyRuntime().invoke(
        """import numpy as np
from quantgrove import Targets

def compute(data, state):
    selected = np.zeros(data.eligible.shape, dtype=bool)
    selected[-30:] = True
    priority = np.broadcast_to(np.arange(len(data.instruments))[:, None], selected.shape)
    return Targets.equal_weight(selected, priority=priority,
                                update=np.ones(len(data.sessions), dtype=bool))
""",
        context={"session": dates[-1], "block": {
            "sessions": dates, "instruments": stocks, "session_index": list(range(128)),
            "eligible": array_to_wire(np.ones((3000, 128), dtype=bool)),
        }},
        state={}, operation="compute",
    )
    assert len(json.dumps(result.output).encode()) < 600 * 1024


@pytest.mark.parametrize("replacement", ["0", "self.weights.size"])
def test_host_rejects_duplicate_or_outside_selected_priority_indices(replacement):
    from thesistrace.research_kernel.strategy_program_runtime import StrategyProgramError

    source = """
import numpy as np
from quantgrove import Targets, array_to_wire

class ForgedTargets(Targets):
    def _to_wire(self):
        output = super()._to_wire()
        indices = np.arange(self.weights.size, dtype=np.uint32)
        indices[-1] = REPLACEMENT
        output['priority']['indices'] = array_to_wire(indices)
        return output

def compute(data, state):
    return ForgedTargets(np.ones(data.eligible.shape) / len(data.instruments),
                         priority=np.ones(data.eligible.shape),
                         update=np.ones(len(data.sessions), dtype=bool))
""".replace("REPLACEMENT", replacement)
    data, definition = batch_inputs(source)
    with pytest.raises(StrategyProgramError, match="priority"):
        transition_strategy(data, None, definition, origin_session=SESSIONS[0])

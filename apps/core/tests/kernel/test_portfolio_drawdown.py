from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import (
    SESSIONS,
    A,
    B,
    _alpha_matrix,
    _canonical,
    _definition,
    _set_alpha_closes,
)

from thesistrace.research_kernel.strategy import transition_strategy


def test_exact_close_drawdown_threshold_caps_next_open_without_new_portfolio():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "12"}, SESSIONS[2]: {A: "10.8"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "portfolio_drawdown": {
            "drawdown_threshold": 0.1, "maximum_stock_exposure": 0.3, "cooldown_sessions": 2,
        },
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"], fill["session"]) for fill in result["fills"]] == [
        ("buy", 10000, SESSIONS[1]), ("sell", 7000, SESSIONS[3]),
    ]
    observation = result["framework_events"][2]["risk_adjustment"]["observations"][0]
    assert observation["reason"] == "portfolio_drawdown"
    assert Decimal(observation["peak_close_nav_cny"]) == 120000
    assert Decimal(observation["close_risk_nav_cny"]) == 108000
    assert Decimal(observation["drawdown"]) == Decimal("0.1")
    assert result["positions"][0]["execution_shares"] == 3000
    assert Decimal(result["daily"][-1]["net_cash"]) == 70000
    assert [Decimal(row["net_nav"]) for row in result["daily"]] == [100000] * 4


def test_cooldown_waits_for_a_new_portfolio_without_restarting_or_buying_from_old_targets():
    sessions = (*SESSIONS, "2026-01-09", "2026-01-12", "2026-01-13")
    canonical = _canonical(sessions=sessions,
                           opens={session: {A: "10", B: "10"} for session in sessions})
    _set_alpha_closes(canonical, {sessions[1]: {A: "12"}, sessions[2]: {A: "10.8"}})
    definition = _definition(selection_interval=5)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "portfolio_drawdown": {
            "drawdown_threshold": 0.1, "maximum_stock_exposure": 0.3, "cooldown_sessions": 2,
        },
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in sessions})
    from copy import deepcopy

    from thesistrace.research_series import slice_research_sessions

    prefix = transition_strategy(slice_research_sessions(data, sessions[:3]), matrix,
                                 definition, origin_session=sessions[0])
    saved = deepcopy(prefix.resumable)
    result = transition_strategy(data, matrix, definition, origin_session=sessions[0],
                                 continuation=prefix.resumable).finalized
    assert prefix.resumable == saved
    assert result == transition_strategy(data, matrix, definition,
                                         origin_session=sessions[0]).finalized
    assert [(fill["side"], fill["quantity"], fill["session"]) for fill in result["fills"]] == [
        ("buy", 10000, sessions[1]), ("sell", 7000, sessions[3]), ("buy", 7000, sessions[6]),
    ]
    facts = [row["risk_adjustment"]["observations"][0] for row in result["framework_events"]]
    assert [(row["status"], row["completed_cooldown_sessions"]) for row in facts[2:6]] == [
        ("threshold_reached", 0), ("cooldown", 1), ("awaiting_new_portfolio", 2),
        ("new_portfolio_recovery", 3),
    ]
    assert Decimal(facts[5]["peak_close_nav_cny"]) == 100000
    assert facts[5]["cycle_started_session"] == sessions[5]
    assert facts[5]["maximum_stock_exposure"] is None
    assert all(Decimal(row["net_nav"]) == 100000 for row in result["daily"])


def test_drawdown_cap_does_not_raise_a_lower_ordinary_target():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "20"}, SESSIONS[2]: {A: "14"}})
    definition = _definition(selection_interval=1)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["strategy"]["exposure_expression"] = {"kind": "number", "value": 0.2}
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "portfolio_drawdown": {
            "drawdown_threshold": 0.1, "maximum_stock_exposure": 0.3, "cooldown_sessions": 2,
        },
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [("buy", 2000)]
    assert result["positions"][0]["execution_shares"] == 2000
    assert result["framework_events"][2]["risk_adjustment"]["observations"][0]["status"] == (
        "threshold_reached"
    )


@pytest.mark.parametrize("new_sessions", [False, True])
@pytest.mark.parametrize("changes", [
    {"peak_close_nav_cny": "NaN"}, {"peak_close_nav_cny": "Infinity"},
    {"peak_close_nav_cny": "bogus"}, {"peak_close_nav_cny": "-1"},
    {"peak_close_nav_cny": "120000.0"}, {"peak_close_nav_cny": "1"},
    {"cycle_started_session": "2026-02-30"},
    {"cycle_started_session": "2027-01-01"},
    {"triggered_session": None}, {"triggered_session_number": None},
    {"triggered_session_number": 4}, {"triggered_session": "2027-01-01"},
    {"triggered_session": "2025-01-01"},
])
def test_invalid_drawdown_checkpoint_is_rejected_before_open_or_empty_refresh(
    new_sessions, changes,
):
    from thesistrace.research_kernel.strategy import StrategyCalculationError
    from thesistrace.research_series import slice_research_sessions

    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "12"}, SESSIONS[2]: {A: "10.8"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "portfolio_drawdown": {
            "drawdown_threshold": 0.1, "maximum_stock_exposure": 0.3, "cooldown_sessions": 2,
        },
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    prefix_data = slice_research_sessions(data, SESSIONS[:3])
    prefix = transition_strategy(prefix_data, matrix, definition, origin_session=SESSIONS[0])
    prefix.resumable["decision_state"]["module_states"]["risk_management"][
        "portfolio_drawdown"
    ].update(changes)
    with pytest.raises(StrategyCalculationError, match="[Dd]rawdown"):
        transition_strategy(data if new_sessions else prefix_data, matrix, definition,
                            origin_session=SESSIONS[0], continuation=prefix.resumable)


@pytest.mark.bounded_process
@pytest.mark.parametrize("cut,blocked", [(3, False), (4, False), (5, False), (6, False), (7, True)])
def test_drawdown_boundaries_restore_in_fresh_process(tmp_path, cut, blocked):
    import os
    import pickle
    import subprocess
    import sys

    from thesistrace.research_series import slice_research_sessions

    sessions = (*SESSIONS, "2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14")
    canonical = _canonical(
        sessions=sessions, opens={session: {A: "10", B: "10"} for session in sessions},
        limit_overrides={(sessions[6], A): ("10", "8")} if blocked else None,
    )
    _set_alpha_closes(canonical, {sessions[1]: {A: "12"}, sessions[2]: {A: "10.8"}})
    definition = _definition(selection_interval=5)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "portfolio_drawdown": {
            "drawdown_threshold": 0.1, "maximum_stock_exposure": 0.3, "cooldown_sessions": 2,
        },
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in sessions})
    prefix = transition_strategy(slice_research_sessions(data, sessions[:cut]), matrix,
                                 definition, origin_session=sessions[0])
    expected = transition_strategy(data, matrix, definition, origin_session=sessions[0])
    expected_fills = [("buy", 10000), ("sell", 7000)]
    if not blocked:
        expected_fills.append(("buy", 7000))
    assert [(fill["side"], fill["quantity"]) for fill in expected.finalized["fills"]] == (
        expected_fills
    )
    assert expected.finalized["positions"][0]["execution_shares"] == (3000 if blocked else 10000)
    payload = tmp_path / "trusted-test-checkpoint.pkl"
    payload.write_bytes(pickle.dumps((data, matrix, definition, prefix.resumable)))
    output = tmp_path / "restored.pkl"
    code = '''
import pickle, sys
from pathlib import Path
from thesistrace.research_kernel.strategy import transition_strategy
data, matrix, definition, prior = pickle.loads(Path(sys.argv[1]).read_bytes())
result = transition_strategy(data, matrix, definition, origin_session=None, continuation=prior)
Path(sys.argv[2]).write_bytes(pickle.dumps((result.finalized, result.resumable)))
'''
    subprocess.run([sys.executable, "-c", code, str(payload), str(output)], check=True,
                   capture_output=True, timeout=30,
                   env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert pickle.loads(output.read_bytes()) == (expected.finalized, expected.resumable)


def test_exact_cooldown_boundary_releases_without_resetting_main_open_drawdown():
    sessions = (*SESSIONS, "2026-01-09", "2026-01-12", "2026-01-13")
    canonical = _canonical(sessions=sessions,
                           opens={session: {A: "12" if session == sessions[2] else "10", B: "10"}
                                  for session in sessions})
    _set_alpha_closes(canonical, {sessions[1]: {A: "12"}, sessions[2]: {A: "10.8"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "portfolio_drawdown": {
            "drawdown_threshold": 0.1, "maximum_stock_exposure": 0.3, "cooldown_sessions": 2,
        },
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in sessions})
    from copy import deepcopy

    from thesistrace.research_series import slice_research_sessions

    prefix = transition_strategy(slice_research_sessions(data, sessions[:3]), matrix,
                                 definition, origin_session=sessions[0])
    saved = deepcopy(prefix.resumable)
    result = transition_strategy(data, matrix, definition, origin_session=sessions[0],
                                 continuation=prefix.resumable).finalized
    assert prefix.resumable == saved
    assert result == transition_strategy(data, matrix, definition,
                                         origin_session=sessions[0]).finalized
    assert [(fill["side"], fill["quantity"], fill["session"]) for fill in result["fills"]] == [
        ("buy", 10000, sessions[1]), ("sell", 7000, sessions[3]), ("buy", 7000, sessions[5]),
    ]
    facts = [row["risk_adjustment"]["observations"][0] for row in result["framework_events"]]
    assert [(row["status"], row["completed_cooldown_sessions"]) for row in facts[2:5]] == [
        ("threshold_reached", 0), ("cooldown", 1), ("new_portfolio_recovery", 2),
    ]
    assert Decimal(facts[4]["peak_close_nav_cny"]) == 100000
    assert facts[4]["cycle_started_session"] == sessions[4]
    assert facts[4]["maximum_stock_exposure"] is None
    assert [Decimal(row["net_nav"]) for row in result["daily"]] == [
        100000, 100000, 120000, 100000, 100000, 100000, 100000,
    ]
    assert result["metrics"]["maximum_drawdown"]["value"] == pytest.approx(1 / 6)
    assert result["metrics"]["maximum_drawdown"]["recovery_session"] is None

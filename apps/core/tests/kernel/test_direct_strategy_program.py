import copy
import subprocess
import sys
from dataclasses import replace

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _canonical
from test_strategy_program_runtime import strategy

from thesistrace.research_kernel.direct_strategy import (
    DirectStrategy,
    PythonProgram,
    program_context,
    program_history,
)
from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)
from thesistrace.research_series import InstrumentProfile

pytestmark = pytest.mark.bounded_process


def test_target_ratio_validation_bounds_host_work_before_parsing_an_exponent():
    # A program's output is untrusted even after its guest has exited. Enforce
    # a process deadline so a regression in host validation cannot hang tests.
    probe = """
from thesistrace.research_kernel.terminal_state_schema import TargetAllocation
try:
    TargetAllocation(mode='rebalance', instrument_ids=['A'],
                     relative_weights={'A': '1e-10000000'}, exposure=1.0)
except ValueError:
    pass
else:
    raise AssertionError('unbounded noncanonical ratio was accepted')
"""
    subprocess.run([sys.executable, "-c", probe], check=True, timeout=5, capture_output=True)


def data():
    return aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}),
        universe="manual",
    )


def context(dataset, *, session=SESSIONS[1], holdings=None):
    return program_context(
        dataset,
        session=session,
        completed_sessions=2,
        account={"cash_cny": "100000", "positions": holdings or []},
        fills=[],
        rejections=[],
    )


def test_context_and_dynamic_reads_exclude_future_data_and_metadata():
    original = data()
    financial = "financial.income.total_revenue.latest_fy"
    original.fields[financial] = {(day, item): "100" for day in SESSIONS for item in (A, B)}
    altered = copy.deepcopy(original)
    future = "equity:future.SH"
    altered.instruments[future] = InstrumentProfile(board="star", listed_to="2099-01-01")
    altered.instruments[A] = replace(altered.instruments[A], listed_to="2099-01-02")
    for day in SESSIONS[2:]:
        altered.universe_members[day] = (future,)
        altered.fields["price.close.adjusted"][(day, A)] = "999999"
        altered.fields[financial][(day, A)] = "999999"
        altered.industries[(day, A)] = "future-industry"
    before = context(original)
    assert before == context(altered)
    assert "history" not in before
    assert future not in str(before)
    assert all("listed_to" not in row for row in before["candidates"])
    for field in ("price.close.adjusted", financial):
        request = {"field_id": field, "days": 10, "instruments": None}
        first = program_history(original, before)(request)
        second = program_history(altered, context(altered))(request)
        assert first.sessions == second.sessions == tuple(SESSIONS[:2])
        assert first.instruments == second.instruments == (A, B)
        assert first.array.tolist() == second.array.tolist()
    assert first.array.tolist() == [[100, 100], [100, 100]]


@pytest.mark.parametrize(
    "history_request",
    [
        {"field_id": "unknown", "days": 2, "instruments": None},
        {"field_id": "price.close.adjusted", "days": 0, "instruments": None},
        {"field_id": "price.close.adjusted", "days": 254, "instruments": None},
        {"field_id": "price.close.adjusted", "days": True, "instruments": None},
        {"field_id": "price.close.adjusted", "days": 2, "instruments": ["future"]},
        {"field_id": "price.close.adjusted", "days": 2, "instruments": [A, A]},
        {"field_id": "price.close.adjusted", "days": 2, "instruments": None, "as_of": "2099-01-01"},
    ],
)
def test_host_rejects_invalid_reads_without_exposing_data(history_request):
    dataset = data()
    with pytest.raises(ValueError):
        program_history(dataset, context(dataset))(history_request)


def test_cumulative_read_budget_is_enforced_before_allocating_history():
    dataset = data()
    request = {"field_id": "price.close.adjusted", "days": 253, "instruments": None}
    ctx = context(dataset)
    ctx["candidates"] = [{"instrument_id": f"equity:{i:06d}.SH"} for i in range(1100)]
    with pytest.raises(ValueError, match="cell budget"):
        program_history(dataset, ctx)(request)


def test_direct_returns_final_targets_and_restores_only_explicit_state():
    source = strategy(
        "self.state['count'] = self.state.get('count', 0) + 1\n"
        "selected = data.candidates[self.state['count'] % 2]\n"
        "return self.target_weights({selected: 1})"
    )
    runtime = PythonStrategyRuntime()
    program = PythonProgram(source=source)
    first = DirectStrategy(program, runtime=runtime, contract_checksum="a" * 64).decide(
        context(data()),
        previous={},
    )
    assert first.state == {"count": 1}
    assert first.target.decision_session == SESSIONS[1]
    assert first.target.allocation.instrument_ids == [B]
    assert first.target.contract_checksum == "a" * 64
    second = DirectStrategy(program, runtime=runtime, contract_checksum="a" * 64).decide(
        context(data(), session=SESSIONS[2]),
        previous=first.state,
    )
    assert second.state == {"count": 2}
    assert second.target.allocation.instrument_ids == [A]


@pytest.mark.parametrize(
    "output",
    [
        "{'allocation': None, 'position_limits': {}, 'reason': 'empty'}",
        "{'allocation': None, 'position_limits': {'equity:future.SH': 0}, 'reason': 'guessed'}",
        f"{{'allocation': None, 'position_limits': {{{A!r}: 101}}, 'reason': 'increase'}}",
        (f"{{'allocation': None, 'position_limits': {{{A!r}: 0}}, 'reason': 'exit', "
         "'decision_session': '2099-01-01'}"),
    ],
)
def test_host_rejects_forged_empty_unknown_increasing_or_backdated_targets(output):
    source = strategy(
        "from quantgrove import Decision\nself.state['changed'] = True\n"
        + "return Decision("
        + output
        + ")"
    )
    previous = {"unchanged": True}
    with pytest.raises(StrategyProgramError):
        DirectStrategy(
            PythonProgram(source=source),
            runtime=PythonStrategyRuntime(),
            contract_checksum="a" * 64,
        ).decide(
            context(data(), holdings=[{"instrument_id": A, "execution_shares": 100}]),
            previous=previous,
        )
    assert previous == {"unchanged": True}


def test_no_update_keeps_diagnostics_private():
    source = strategy("print('private reason')\nself.state['wait'] = True\nreturn None")
    decision = DirectStrategy(
        PythonProgram(source=source), runtime=PythonStrategyRuntime(), contract_checksum="a" * 64
    ).decide(context(data()), previous={})
    assert decision.target is None
    assert decision.state == {"wait": True}
    assert decision.diagnostics == "private reason\n"


def test_source_only_program_rejects_removed_authoring_fields():
    for old in (
        {"parameters": {}},
        {"data_requirements": {"field_ids": [], "history_sessions": 1}},
    ):
        with pytest.raises(ValueError):
            PythonProgram.model_validate({"source": strategy("return None"), **old})

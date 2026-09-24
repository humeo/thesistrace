import copy
import subprocess
import sys
from dataclasses import replace

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _canonical

from thesistrace.research_kernel.direct_strategy import (
    DirectStrategy,
    ProgramDataRequirements,
    PythonProgram,
    program_context,
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


@pytest.mark.parametrize("number", [float("inf"), 2**53, 1e20])
def test_program_parameters_reject_numbers_that_json_cannot_interoperate_exactly(number):
    with pytest.raises(ValueError):
        PythonProgram(
            source="def decide(context, state, parameters): pass",
            parameters={"threshold": number},
            data_requirements={"field_ids": [], "history_sessions": 1},
        )


def data():
    return aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}),
        universe="manual",
    )


def context(dataset, *, session=SESSIONS[1], holdings=None):
    return program_context(
        dataset,
        ProgramDataRequirements(field_ids=["price.close.adjusted"], history_sessions=2),
        session=session,
        completed_sessions=2,
        account={"cash_cny": "100000", "positions": holdings or []},
        fills=[],
        rejections=[],
    )


def test_program_context_is_close_scoped_and_future_metadata_cannot_change_it():
    original = data()
    financial = "financial.income.total_revenue.latest_fy"
    original.fields[financial] = {(session, item): "100" for session in SESSIONS for item in (A, B)}
    altered = copy.deepcopy(original)
    future = "equity:future.SH"
    altered.instruments[future] = InstrumentProfile(board="star", listed_to="2099-01-01")
    altered.instruments[A] = replace(altered.instruments[A], listed_to="2099-01-02")
    for session in SESSIONS[2:]:
        altered.universe_members[session] = (future,)
        altered.fields["price.close.adjusted"][(session, A)] = "999999"
        altered.fields[financial][(session, A)] = "999999"
        altered.industries[(session, A)] = "future-industry"
    altered.fields["undeclared_financial_field"] = {(SESSIONS[1], A): "123"}
    before = context(original)
    assert before == context(altered)
    assert before["history"]["sessions"] == list(SESSIONS[:2])
    assert set(before["history"]["fields"]) == {"price.close.adjusted"}
    assert before["history"]["instruments"] == [A, B]
    assert all("listed_to" not in row for row in before["candidates"])
    assert future not in str(before)
    requirements = ProgramDataRequirements(
        field_ids=["price.close.adjusted", financial],
        history_sessions=2,
    )

    def declared_context(dataset):
        return program_context(
            dataset,
            requirements,
            session=SESSIONS[1],
            completed_sessions=2,
            account={"positions": []},
            fills=[],
            rejections=[],
        )

    assert declared_context(original) == declared_context(altered)
    assert declared_context(original)["history"]["fields"][financial] == [[100, 100], [100, 100]]


def test_oversized_data_declaration_fails_before_materializing_history():
    dataset = data()
    # Even the shortest numeric JSON encoding cannot fit this shape. Data need
    # not be materialized (or even read) to reject it.
    dataset.universe_members[SESSIONS[1]] = tuple(f"equity:{i:06d}.SH" for i in range(50_000))
    for item in dataset.universe_members[SESSIONS[1]]:
        dataset.instruments[item] = dataset.instruments[A]
    with pytest.raises(ValueError, match="Program history exceeds the input size limit"):
        program_context(
            dataset,
            ProgramDataRequirements(
                field_ids=[f"field.{i}" for i in range(32)],
                history_sessions=2,
            ),
            session=SESSIONS[1],
            completed_sessions=2,
            account={"positions": []},
            fills=[],
            rejections=[],
        )


def test_direct_returns_final_targets_and_only_explicit_state_survives():
    source = """
def decide(context, state, parameters):
    count = state.get('count', 0) + 1
    selected = context['candidates'][count % 2]['instrument_id']
    return {'output': {
        'reason': 'better_candidate',
        'allocation': {'mode': 'rebalance', 'instrument_ids': [selected],
                       'relative_weights': {selected: '1'}, 'exposure': 1.0},
        'position_limits': {},
    }, 'state': {'count': count}}
"""
    runtime = PythonStrategyRuntime()
    program = PythonProgram(
        source=source,
        parameters={},
        data_requirements={
            "field_ids": ["price.close.adjusted"],
            "history_sessions": 2,
        },
    )
    direct = DirectStrategy(program, runtime=runtime, contract_checksum="a" * 64)
    first = direct.decide(context(data()), previous={})
    assert first.state == {"count": 1}
    assert first.target.decision_session == SESSIONS[1]
    assert first.target.allocation.instrument_ids == [B]
    assert first.target.contract_checksum == "a" * 64
    # A reconstructed adapter continues only the explicit state.
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
        "{'allocation': None, 'position_limits': {parameters['held']: 101}, 'reason': 'increase'}",
        "{'allocation': None, 'position_limits': {parameters['held']: 0}, 'reason': 'exit', "
        "'decision_session': '2099-01-01'}",
    ],
)
def test_direct_rejects_empty_unknown_increasing_or_backdated_local_decisions(output):
    source = "def decide(context, state, parameters):\n    return {'output': " + output
    source += ", 'state': {'changed': True}}"
    previous = {"unchanged": True}
    program = PythonProgram(
        source=source,
        parameters={"held": A},
        data_requirements={
            "field_ids": ["price.close.adjusted"],
            "history_sessions": 2,
        },
    )
    with pytest.raises(StrategyProgramError):
        DirectStrategy(program, runtime=PythonStrategyRuntime(), contract_checksum="a" * 64).decide(
            context(data(), holdings=[{"instrument_id": A, "execution_shares": 100}]),
            previous=previous,
        )
    assert previous == {"unchanged": True}


def test_direct_no_update_is_distinct_from_empty_target_and_keeps_diagnostics_private():
    program = PythonProgram(
        source="def decide(context, state, parameters):\n    print('private reason')\n"
        "    return {'output': None, 'state': {'wait': True}}",
        parameters={},
        data_requirements={"field_ids": [], "history_sessions": 1},
    )
    decision = DirectStrategy(
        program,
        runtime=PythonStrategyRuntime(),
        contract_checksum="a" * 64,
    ).decide(context(data()), previous={})
    assert decision.target is None
    assert decision.state == {"wait": True}
    assert decision.diagnostics == "private reason\n"

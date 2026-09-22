from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _canonical

from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_kernel.strategy_program_runtime import PythonStrategyRuntime
from thesistrace.research_series import slice_research_sessions

pytestmark = pytest.mark.bounded_process

SOURCE = """
def decide(context, state, parameters):
    history = context['history']
    prices = history['fields']['price.close.adjusted']
    best = max(range(len(history['instruments'])), key=lambda i: prices[i][-1])
    selected = history['instruments'][best]
    held = [row['instrument_id'] for row in context['account']['positions']]
    output = None
    if held != [selected]:
        output = {
            'reason': 'better_candidate',
            'allocation': {'mode': 'rebalance', 'instrument_ids': [selected],
                           'relative_weights': {selected: '1'}, 'exposure': 1.0},
            'position_limits': {},
        }
    return {'output': output, 'state': {'count': state.get('count', 0) + 1}}
"""


def inputs():
    data = aligned_market_data(
        _canonical(
            opens={
                session: {A: "10", B: "20" if session == SESSIONS[3] else "10"}
                for session in SESSIONS
            }
        ),
        universe="manual",
    )
    for index, session in enumerate(SESSIONS):
        data.fields["price.close.adjusted"][(session, A)] = "20" if index != 3 else "100"
        data.fields["price.close.adjusted"][(session, B)] = "10" if index == 0 else "30"
    definition = {
        "universe": "manual",
        "strategy": {
            "mode": "direct",
            "initial_cash_cny": "100000",
            "program": {
                "source": SOURCE,
                "parameters": {},
                "data_requirements": {"field_ids": ["price.close.adjusted"], "history_sessions": 1},
            },
            "environment": PythonStrategyRuntime().identity(),
        },
        "costs": {
            "commission_rate_all_in": "0",
            "commission_min_cny": "0",
            "stamp_duty_sell_rate": "0",
            "transfer_fee_rate": "0",
        },
    }
    return data, definition


def test_direct_uses_one_shared_account_for_condition_triggered_next_open_execution():
    data, definition = inputs()
    result = transition_strategy(
        data,
        None,
        definition,
        origin_session=SESSIONS[0],
    ).finalized
    assert [
        (row["session"], row["instrument_id"], row["side"], row["quantity"])
        for row in result["fills"]
    ] == [
        (SESSIONS[1], A, "buy", 10000),
        (SESSIONS[2], A, "sell", 10000),
        (SESSIONS[2], B, "buy", 10000),
    ]
    assert [Decimal(row["net_nav"]) for row in result["daily"]] == [
        Decimal("100000"),
        Decimal("100000"),
        Decimal("100000"),
        Decimal("200000"),
    ]
    assert result["decision_state"]["state"] == {"count": 4}
    assert result["pending_target"]["decision_session"] == SESSIONS[3]
    assert result["pending_target"]["allocation"]["instrument_ids"] == [A]
    assert "target_selection" not in result


def test_direct_replays_exactly_from_an_explicit_midrun_boundary():
    data, definition = inputs()
    whole = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]),
        None,
        definition,
        origin_session=SESSIONS[0],
    ).resumable
    continued = transition_strategy(
        data,
        None,
        definition,
        origin_session=SESSIONS[0],
        continuation=prefix,
    ).finalized
    assert continued == whole


def test_direct_public_kernel_input_does_not_invent_an_alpha_formula():
    from thesistrace.daily_track.checkpoint import (
        project_tracking_checkpoint,
        restore_tracking_checkpoint,
    )
    from thesistrace.daily_track.observation_state import (
        TrackingObservationState,
        initial_tracking_observation_state,
    )
    from thesistrace.research_kernel import (
        AdvanceInput,
        DirectStrategyRunInput,
        RunInput,
        advance,
        continuation_snapshot,
        run,
    )
    from thesistrace.research_kernel.serialization import canonical_json_bytes

    data, definition = inputs()
    strategy = definition["strategy"]
    run_input = RunInput(
        research_data=data,
        alpha_expression=None,
        field_bindings={"price.close.adjusted": "close"},
        effective_lookback=0,
        universe="manual",
        neutralization=None,
        research_kind="strategy_backtest",
        strategy=DirectStrategyRunInput(
            program_json=canonical_json_bytes(strategy["program"]),
            environment_json=canonical_json_bytes(strategy["environment"]),
            initial_cash_cny="100000",
            **definition["costs"],
        ),
        research_start_session=SESSIONS[0],
        research_end_session=SESSIONS[-1],
    )
    full_run = run(run_input)
    output = full_run.artifacts_snapshot()
    assert "alpha_matrix" not in output
    assert output["strategy_backtest"]["decision_state"]["state"] == {"count": 4}
    assert Decimal(output["strategy_backtest"]["daily"][-1]["net_nav"]) == Decimal("200000")
    prefix_input = run_input.with_research_data(
        slice_research_sessions(data, SESSIONS[:2]),
        research_end_session=SESSIONS[1],
    )
    prefix = run(prefix_input).track_state
    continued = advance(
        AdvanceInput(
            prior_state=prefix,
            target_research_data=data,
            appended_sessions=list(SESSIONS[2:]),
            continuation=continuation_snapshot(prefix),
            calculation_scope="research_period",
        )
    )
    assert continued.output_snapshot() == output
    initial = initial_tracking_observation_state(SESSIONS[0], "100000")
    checkpoint = project_tracking_checkpoint(
        prefix,
        retained_strategy_sessions=SESSIONS[1:2],
        prior_observation_state=initial,
    )
    restored = restore_tracking_checkpoint(
        checkpoint,
        research_data=slice_research_sessions(data, SESSIONS[:2]),
    )
    recovered = advance(
        AdvanceInput(
            prior_state=restored,
            target_research_data=data,
            appended_sessions=list(SESSIONS[2:]),
            continuation=continuation_snapshot(restored),
            calculation_scope="forward_tracking",
        )
    )
    recovered_checkpoint = project_tracking_checkpoint(
        recovered,
        retained_strategy_sessions=SESSIONS[2:],
        prior_observation_state=TrackingObservationState.model_validate(
            checkpoint["tracking_observation_state"],
        ),
    )
    full_checkpoint = project_tracking_checkpoint(
        full_run.track_state,
        retained_strategy_sessions=SESSIONS[1:],
        prior_observation_state=initial,
    )
    assert (
        recovered_checkpoint["strategy_state"]["terminal"]
        == full_checkpoint["strategy_state"]["terminal"]
    )


@pytest.mark.parametrize("mode", ["direct", "framework"])
def test_python_strategy_columnar_chunks_match_the_public_run_without_alpha_computation(mode):
    from copy import deepcopy

    import numpy as np
    from test_research_chunk_continuation import _ColumnarFixture

    from thesistrace.research_kernel import DirectStrategyRunInput, RunInput, StrategyRunInput, run
    from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES
    from thesistrace.research_kernel.numeric import NUMERIC_CONTRACT_ID
    from thesistrace.research_kernel.research_chunks import (
        AlphaFactorExecutionBinding,
        empty_research_continuation,
        execute_research_chunk,
        validated_research_continuation,
    )
    from thesistrace.research_kernel.serialization import canonical_json_bytes
    from thesistrace.research_run.result import build_result_payload

    data, definition = inputs()
    environment = canonical_json_bytes(definition["strategy"]["environment"])
    common = {"initial_cash_cny": "100000", **definition["costs"]}
    strategy = DirectStrategyRunInput(
        program_json=canonical_json_bytes(definition["strategy"]["program"]),
        environment_json=environment, **common,
    )
    if mode == "framework":
        modules = dict(BUILTIN_FRAMEWORK_MODULES)
        modules["portfolio_construction"] = {
            "kind": "python", "program": definition["strategy"]["program"],
        }
        modules["alpha"] = {"kind": "python", "program": {
            "source": """
def decide(context, state, parameters):
    output = None
    if context['completed_sessions'] == 1:
        output = {'reason': 'two_day_signal', 'signals': [{
            'instrument_id': context['candidates'][0]['instrument_id'],
            'value': 1.0, 'valid_for_sessions': 2}]}
    return {'output': output, 'state': {}}
""",
            "parameters": {}, "data_requirements": {"field_ids": [], "history_sessions": 1},
        }}
        strategy = StrategyRunInput(
            holdings_count=None, selection_interval=None,
            modules_json=canonical_json_bytes(modules),
            environment_json=environment, **common,
        )
    columnar = _ColumnarFixture(
        sessions=data.sessions,
        instruments=data.instruments,
        universe_members=data.universe_members,
        industries=data.industries,
        execution_prices=data.execution_prices,
        trading_states=data.trading_states,
        price_limits=data.price_limits,
        matrices={
            field: np.asarray(
                [
                    [float(values.get((session, item), "nan")) for session in data.sessions]
                    for item in data.instruments
                ]
            )
            for field, values in data.fields.items()
        },
    )
    run_input = RunInput(
        research_data=columnar,
        alpha_expression=None,
        field_bindings={"price.close.adjusted": "close"},
        effective_lookback=0,
        universe="manual",
        neutralization=None,
        research_kind="strategy_backtest",
        strategy=strategy,
        research_start_session=SESSIONS[0],
        research_end_session=SESSIONS[-1],
    )
    binding = AlphaFactorExecutionBinding.from_run_input(
        run_input,
        data_generation_id="manual",
        numeric_execution_contract=NUMERIC_CONTRACT_ID,
        semantic_versions={"kernel": "direct-test"},
    )
    assert binding.value_snapshot()["alpha"] is None
    state = empty_research_continuation("strategy_backtest")
    observations = []
    for start, end in [(0, 2), (2, 4)]:
        # Includes the prior account coordinate; no program sees future sessions.
        chunk = execute_research_chunk(
            run_input=run_input,
            binding=binding,
            research_data=columnar.slice_sessions(SESSIONS[:end]),
            forward_labels=None,
            research_sessions=SESSIONS[start:end],
            final_chunk=end == 4,
            continuation=state,
            cancellation_check=lambda: None,
        )
        state = validated_research_continuation(
            chunk.continuation,
            research_kind="strategy_backtest",
        )
        assert state["alpha_checksum"] is None
        assert state["pending_alpha"] == []
        if mode == "framework" and end == 2:
            for name, value in (
                ("created_session", "2099-01-01"),
                ("created_session", "not-a-session"),
                ("created_session_number", 3),
                ("valid_for_sessions", 1),
            ):
                corrupted = deepcopy(state)
                corrupted["strategy_state"]["decision_state"]["signals"][0][name] = value
                with pytest.raises(ValueError, match="continuation is invalid"):
                    validated_research_continuation(corrupted, research_kind="strategy_backtest")
            corrupted = deepcopy(state)
            corrupted["strategy_state"]["decision_state"]["module_states"]["alpha"] = {
                "oversized": "x" * (300 * 1024),
            }
            with pytest.raises(ValueError, match="continuation is invalid"):
                validated_research_continuation(corrupted, research_kind="strategy_backtest")
        observations.extend(chunk.strategy_daily_observations)
    expected = build_result_payload(
        run(run_input.with_research_data(data)),
        research_kind="strategy_backtest",
    )
    assert list(observations) == expected.pop("strategy_daily_observations")
    assert chunk.final_values == expected
    assert chunk.final_values["strategy_summary"]["alpha_checksum"] is None

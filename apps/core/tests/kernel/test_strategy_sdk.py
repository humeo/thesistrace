import numpy as np
import pytest

from thesistrace.research_history import HistoryWindow
from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)

pytestmark = pytest.mark.bounded_process


@pytest.fixture(scope="module")
def runtime():
    return PythonStrategyRuntime()


def test_class_reads_dynamic_history_and_remembers_only_explicit_state(runtime):
    source = """from quantgrove import target_weights

def decide(data, account, state):
    days = 5 + state.get('calls', 0)
    prices = data.close_prices(days)
    state['calls'] = state.get('calls', 0) + 1
    state['last'] = prices['A'][-1]
    state['cash'] = account.cash_cny
    return target_weights({'A': 0.6, 'B': 0.2})
"""
    requests = []

    def read(request):
        requests.append(request)
        return HistoryWindow(("2026-08-03",), ("A",), np.array([[12.0]]))

    context = {"session": "2026-08-03", "account": {"cash_cny": "100", "positions": []}}
    first = runtime.invoke(source, context=context, state={}, read_history=read)
    second = runtime.invoke(source, context=context, state=first.state, read_history=read)
    assert [request["days"] for request in requests] == [5, 6]
    assert second.state == {"calls": 2, "last": 12.0, "cash": "100"}
    assert first.history_reads[0]["requested_sessions"] == 5
    assert first.history_reads[0]["last_session"] == "2026-08-03"
    assert first.output == {
        "reason": "target_weights",
        "position_limits": {},
        "allocation": {
            "mode": "rebalance",
            "instrument_ids": ["A", "B"],
            "relative_weights": {"A": "3/4", "B": "1/4"},
            "exposure": 0.8,
        },
    }


@pytest.mark.parametrize(
    "body, expected",
    [
        ("return None", None),
        ("return target_weights({})", 0.0),
    ],
)
def test_no_update_and_liquidation_remain_distinct(runtime, body, expected):
    source = (
        "from quantgrove import target_weights\ndef decide(data, account, state):\n    "
        + body.replace("self.", "")
    )
    result = runtime.invoke(source, context={}, state={})
    if expected is None:
        assert result.output is None
    else:
        assert result.output["allocation"]["exposure"] == expected
        assert result.output["allocation"]["instrument_ids"] == []


def test_validation_loads_class_inside_sandbox_and_rejects_old_entrypoint(runtime):
    with pytest.raises(StrategyProgramError, match="TypeError"):
        runtime.validate("def decide(data, state): return None")
    with pytest.raises(StrategyProgramError, match="ImportError"):
        runtime.validate("from quantgrove import Strategy\nclass Empty(Strategy): pass")
    runtime.validate("""def decide(data, account, state):
    return None
""")


def test_history_error_has_author_line_and_does_not_mutate_previous_state(runtime):
    state = {"calls": 1}

    def denied(request):
        raise ValueError("Unknown history field")

    with pytest.raises(StrategyProgramError, match="Unknown history field") as caught:
        runtime.invoke(
            """def decide(data, account, state):
    state['calls'] = 99
    data.history('secret', 10)
""",
            context={"session": "2026-08-03"},
            state=state,
            read_history=denied,
        )
    assert state == {"calls": 1}
    assert caught.value.line == 3


def test_state_object_keys_are_not_silently_coerced_to_strings(runtime):
    with pytest.raises(StrategyProgramError, match="string object keys"):
        runtime.invoke(
            "def decide(data, account, state):\n    state[1] = 'invalid'",
            context={}, state={},
        )


def test_history_request_limit_is_enforced_even_when_user_catches_errors(runtime):
    requests = []

    def read(request):
        requests.append(request)
        return HistoryWindow((), (), np.empty((0, 0)))

    source = """def decide(data, account, state):
    for index in range(65):
        try:
            data.close_prices(1)
        except Exception:
            pass
    return None
"""
    with pytest.raises(StrategyProgramError, match="resource or capability"):
        runtime.invoke(source, context={}, state={}, read_history=read)
    assert len(requests) == 64


def test_adding_limits_never_relaxes_an_existing_cap(runtime):
    result = runtime.invoke(
        """from quantgrove import target_weights, with_limits


def decide(data, account, state):
    initial = with_limits(
        target_weights({"A": 0.8}), maximum_shares={"A": 100}, maximum_exposure=0.5
    )
    return with_limits(initial, maximum_shares={"A": 200}, maximum_exposure=0.9)
""",
        context={},
        state={},
    )
    assert result.output["position_limits"] == {"A": 100}
    assert result.output["maximum_stock_exposure"] == 0.5

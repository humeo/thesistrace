import pytest

from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)

pytestmark = pytest.mark.bounded_process


@pytest.fixture(scope="module")
def runtime():
    return PythonStrategyRuntime()


def test_class_reads_dynamic_history_and_remembers_only_explicit_state(runtime):
    source = '''
from quantgrove import Strategy

class Momentum(Strategy):
    def on_close(self, data, account):
        days = 5 + self.state.get("calls", 0)
        prices = data.close_prices(days)
        self.state["calls"] = self.state.get("calls", 0) + 1
        self.state["last"] = prices["A"][-1]
        self.state["cash"] = account.cash_cny
        return self.target_weights({"A": 0.6, "B": 0.2})
'''
    requests = []

    def read(request):
        requests.append(request)
        return {"sessions": ["2026-08-03"], "values": {"A": [12.0]}}

    context = {"session": "2026-08-03", "account": {"cash_cny": "100", "positions": []}}
    first = runtime.invoke(source, context=context, state={}, read_history=read)
    second = runtime.invoke(source, context=context, state=first.state, read_history=read)
    assert [request["days"] for request in requests] == [5, 6]
    assert second.state == {"calls": 2, "last": 12.0, "cash": "100"}
    assert first.history_reads[0]["requested_sessions"] == 5
    assert first.history_reads[0]["last_session"] == "2026-08-03"
    assert first.output == {
        "reason": "target_weights", "position_limits": {},
        "allocation": {"mode": "rebalance", "instrument_ids": ["A", "B"],
                       "relative_weights": {"A": "3/4", "B": "1/4"}, "exposure": 0.8},
    }


@pytest.mark.parametrize("body, expected", [
    ("return None", None),
    ("return self.target_weights({})", 0.0),
])
def test_no_update_and_liquidation_remain_distinct(runtime, body, expected):
    source = "from quantgrove import Strategy\nclass Test(Strategy):\n"
    source += "    def on_close(self, data, account):\n        " + body
    result = runtime.invoke(source, context={}, state={})
    if expected is None:
        assert result.output is None
    else:
        assert result.output["allocation"]["exposure"] == expected
        assert result.output["allocation"]["instrument_ids"] == []


def test_validation_loads_class_inside_sandbox_and_rejects_old_entrypoint(runtime):
    with pytest.raises(StrategyProgramError, match="exactly one"):
        runtime.validate("def decide(context, state, parameters): return None")
    with pytest.raises(StrategyProgramError, match="on_close"):
        runtime.validate("from quantgrove import Strategy\nclass Empty(Strategy): pass")
    runtime.validate("from quantgrove import Strategy\nclass Valid(Strategy):\n"
                     "    def on_close(self, data, account): return None")


def test_history_error_has_author_line_and_does_not_mutate_previous_state(runtime):
    state = {"calls": 1}

    def denied(request):
        raise ValueError("Unknown history field")

    with pytest.raises(StrategyProgramError, match="Unknown history field") as caught:
        runtime.invoke(
            "from quantgrove import Strategy\nclass Test(Strategy):\n"
            "    def on_close(self, data, account):\n"
            "        self.state['calls'] = 99\n"
            "        data.history('secret', 10)\n",
            context={"session": "2026-08-03"}, state=state, read_history=denied,
        )
    assert state == {"calls": 1}
    assert caught.value.line == 5


def test_history_request_limit_is_enforced_even_when_user_catches_errors(runtime):
    requests = []

    def read(request):
        requests.append(request)
        return {"sessions": [], "values": {}}

    source = '''from quantgrove import Strategy
class TooMany(Strategy):
    def on_close(self, data, account):
        for index in range(65):
            try:
                data.close_prices(1)
            except Exception:
                pass
        return None
'''
    with pytest.raises(StrategyProgramError, match="resource or capability"):
        runtime.invoke(source, context={}, state={}, read_history=read)
    assert len(requests) == 64


def test_adding_limits_never_relaxes_an_existing_cap(runtime):
    result = runtime.invoke('''from quantgrove import Strategy
class Caps(Strategy):
    def on_close(self, data, account):
        initial = self.with_limits(self.target_weights({"A": 0.8}),
                                   maximum_shares={"A": 100}, maximum_exposure=0.5)
        return self.with_limits(initial, maximum_shares={"A": 200}, maximum_exposure=0.9)
''', context={}, state={})
    assert result.output["position_limits"] == {"A": 100}
    assert result.output["maximum_stock_exposure"] == 0.5

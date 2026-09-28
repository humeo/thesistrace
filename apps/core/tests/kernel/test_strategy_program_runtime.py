import copy
import textwrap
import time

import pytest

from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)

pytestmark = pytest.mark.bounded_process


def strategy(body):
    return (
        "from quantgrove import Strategy\nclass Test(Strategy):\n"
        "    def on_close(self, data, account):\n" + textwrap.indent(body, "        ")
    )


@pytest.fixture(scope="module")
def runtime():
    return PythonStrategyRuntime()


def test_python_strategy_restores_only_explicit_state_in_a_fresh_guest(runtime):
    source = strategy(
        "self.counter = getattr(self, 'counter', 0) + 1\n"
        "self.state['days'] = self.state.get('days', 0) + 1\n"
        "self.state['counter'] = self.counter\n"
        "self.state['session'] = data.session"
    )
    first = runtime.invoke(source, context={"session": "2026-08-03"}, state={})
    second = runtime.invoke(source, context={"session": "2026-08-04"}, state=first.state)
    assert first.state == {"days": 1, "counter": 1, "session": "2026-08-03"}
    assert second.state == {"days": 2, "counter": 1, "session": "2026-08-04"}


def test_trusted_bootstrap_does_not_consume_the_user_program_wall_budget(monkeypatch):
    from thesistrace.research_kernel import strategy_program_runtime as execution

    runtime = PythonStrategyRuntime()
    clock = [0]

    class StartupPauseTimer:
        def __init__(self, interval, callback):
            self.deadline = clock[0] + interval
            self.callback = callback

        def start(self):
            if clock[0] == 0:
                clock[0] = 4
            if clock[0] >= self.deadline:
                self.callback()

        def cancel(self):
            pass

        def join(self):
            pass

    monkeypatch.setattr(execution.threading, "Timer", StartupPauseTimer)
    result = runtime.invoke(strategy("self.state['ok'] = True"), context={}, state={})
    assert result.state == {"ok": True}


def test_bootstrap_deadline_is_bounded_and_does_not_poison_next_invocation(runtime, monkeypatch):
    from thesistrace.research_kernel import strategy_program_runtime as execution

    source = strategy("return None")
    with monkeypatch.context() as limits:
        limits.setattr(execution, "BOOTSTRAP_WALL_SECONDS", 0.001)
        with pytest.raises(StrategyProgramError, match="bootstrap exceeded its wall time"):
            runtime.invoke(source, context={}, state={})
    assert runtime.invoke(source, context={}, state={}).state == {}


def test_simulated_clock_and_randomness_repeat_in_another_runtime(runtime):
    source = strategy(
        "import datetime, random, time\n"
        "self.state.update(time=datetime.datetime.now(datetime.UTC).isoformat(),\n"
        "                  monotonic=time.monotonic(),\n"
        "                  random=[random.random(), random.SystemRandom().randint(1, 1000000)])"
    )
    first = runtime.invoke(source, context={"session": "2026-08-03"}, state={})
    second = PythonStrategyRuntime().invoke(source, context={"session": "2026-08-03"}, state={})
    assert first == second
    assert first.state["time"] == "2026-08-03T07:00:00+00:00"
    assert first.state["monotonic"] == 0


def test_actual_guest_cannot_read_host_resources_or_open_network(runtime, tmp_path, monkeypatch):
    paths = [tmp_path / name for name in ("host", "dataset", "researcher-b")]
    for path in paths:
        path.write_text("private host sentinel")
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "private-worker-credential-sentinel")
    requested = [str(path) for path in paths] + ["/runtime/lib/python3.14/os.py", "/etc/passwd"]
    source = strategy(
        f"import os\npaths = {requested!r}\n"
        + """
for path in paths:
    try:
        self.state[path] = open(path).read()
    except OSError:
        self.state[path] = "denied"
for name in ("socket", "subprocess", "ctypes"):
    try:
        __import__(name)
        self.state[name] = "available"
    except ImportError:
        self.state[name] = "unavailable"
try:
    open(paths[0], "w").write("changed")
    self.state["write"] = "allowed"
except OSError:
    self.state["write"] = "denied"
try:
    os.write(3, b'thesistrace-python-ready/v1')
    self.state["restart_deadline"] = "allowed"
except OSError:
    self.state["restart_deadline"] = "denied"
self.state["environment"] = dict(os.environ)
"""
    )
    result = runtime.invoke(source, context={}, state={})
    assert {path: result.state[path] for path in requested} == dict.fromkeys(requested, "denied")
    assert result.state["write"] == result.state["restart_deadline"] == "denied"
    assert all(result.state[name] == "unavailable" for name in ("socket", "subprocess", "ctypes"))
    assert result.state["environment"] == {
        "PYTHONHOME": "/runtime",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
    }
    assert all(path.read_text() == "private host sentinel" for path in paths)


@pytest.mark.parametrize(
    "body", ["account.cash_cny = '999999'", "account.positions[0]['shares'] = 9"]
)
def test_account_is_read_only_and_host_values_are_unchanged(runtime, body):
    context = {
        "session": "2026-08-03",
        "account": {"cash_cny": "100", "positions": [{"shares": 1}]},
    }
    original = copy.deepcopy(context)
    with pytest.raises(StrategyProgramError, match="TypeError") as caught:
        runtime.invoke(strategy(body), context=context, state={})
    assert context == original
    assert caught.value.session == "2026-08-03"
    assert caught.value.line == 4


@pytest.mark.parametrize(
    "body",
    [
        "while True:\n    pass",
        ("import os\nwhile True:\n    try: os.write(3, b'thesistrace-python-ready/v1')\n"
         "    except OSError: pass"),
        "bytearray(512 * 1024 * 1024)",
        "__import__('os').write(1, b'x' * (2 * 1024 * 1024))",
        "__import__('time').sleep(3600)",
        "self.state['large'] = 'x' * (300 * 1024)",
    ],
)
def test_resource_failure_is_bounded_and_next_guest_still_completes(runtime, body):
    started = time.monotonic()
    with pytest.raises(StrategyProgramError):
        runtime.invoke(strategy(body), context={}, state={})
    assert time.monotonic() - started < 15
    result = runtime.invoke(strategy("self.state['ok'] = True"), context={}, state={})
    assert result.state == {"ok": True}


@pytest.mark.parametrize(
    "body",
    [
        "return {}",
        "return {'output': None, 'state': {}}",
        "self.state = None",
        "self.state['bad'] = float('nan')",
        "self.state['bad'] = 2**53",
    ],
)
def test_invalid_output_never_becomes_successful_state(runtime, body):
    with pytest.raises(StrategyProgramError):
        runtime.invoke(strategy(body), context={}, state={"retained": 1})


def test_validation_reports_program_and_source_line_and_sandboxes_top_level(runtime):
    with pytest.raises(StrategyProgramError, match="SyntaxError") as caught:
        runtime.validate("class Invalid(\n")
    assert caught.value.line == 1
    assert caught.value.session is None
    assert len(caught.value.program_sha256) == 64
    with pytest.raises(StrategyProgramError, match="FileNotFoundError"):
        runtime.validate("open('/etc/passwd').read()\n" + strategy("return None"))


@pytest.mark.parametrize("diagnostics", ["{}", "'x' * 65537"])
def test_guest_cannot_bypass_host_diagnostics_validation(runtime, diagnostics):
    source = f"""
import json, os
os.write(1, json.dumps({{
    "ok": True, "result": {{"output": None, "state": {{}}}}, "diagnostics": {diagnostics},
}}).encode())
os._exit(0)
"""
    with pytest.raises(StrategyProgramError, match="diagnostics"):
        runtime.invoke(source, context={}, state={})

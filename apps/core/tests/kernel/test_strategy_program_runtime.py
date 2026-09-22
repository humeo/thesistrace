import copy
import textwrap
import time

import pytest

from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)


def test_python_strategy_returns_explicit_state_in_a_fresh_guest():
    runtime = PythonStrategyRuntime()
    source = """
counter = 0

def decide(context, state, parameters):
    global counter
    counter += 1
    return {
        "output": None,
        "state": {"days": state.get("days", 0) + 1, "counter": counter,
                  "session": context["session"], "label": parameters["label"]},
    }
"""
    first = runtime.invoke(
        source, context={"session": "2026-08-03"}, state={}, parameters={"label": "test"},
    )
    second = runtime.invoke(
        source, context={"session": "2026-08-04"}, state=first.state,
        parameters={"label": "test"},
    )
    assert first.output is None
    assert first.state == {
        "days": 1, "counter": 1, "session": "2026-08-03", "label": "test",
    }
    assert second.state == {
        "days": 2, "counter": 1, "session": "2026-08-04", "label": "test",
    }


def test_simulated_clock_and_randomness_repeat_in_another_runtime():
    source = """
import datetime
import random
import time

def decide(context, state, parameters):
    return {"output": {
        "time": datetime.datetime.now(datetime.UTC).isoformat(),
        "monotonic": time.monotonic(),
        "random": [random.random(), random.SystemRandom().randint(1, 1000000)],
    }, "state": {}}
"""
    first = PythonStrategyRuntime().invoke(
        source, context={"session": "2026-08-03"}, state={}, parameters={},
    )
    second = PythonStrategyRuntime().invoke(
        source, context={"session": "2026-08-03"}, state={}, parameters={},
    )
    assert first == second
    assert first.output["time"] == "2026-08-03T07:00:00+00:00"
    assert first.output["monotonic"] == 0


def test_actual_guest_cannot_read_host_resources_credentials_or_open_network(tmp_path, monkeypatch):
    sentinels = [tmp_path / name for name in ("host", "dataset", "researcher-b")]
    for path in sentinels:
        path.write_text("private host sentinel")
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "private-worker-credential-sentinel")
    source = """
import os

def decide(context, state, parameters):
    observed = {}
    for path in parameters["paths"]:
        try:
            observed[path] = open(path).read()
        except OSError:
            observed[path] = "denied"
    for name in ("socket", "subprocess", "ctypes"):
        try:
            __import__(name)
            observed[name] = "available"
        except ImportError:
            observed[name] = "unavailable"
    try:
        open(parameters["paths"][0], "w").write("changed")
        observed["write"] = "allowed"
    except OSError:
        observed["write"] = "denied"
    observed["environment"] = dict(os.environ)
    return {"output": observed, "state": {}}
"""
    paths = [str(path) for path in sentinels] + ["/runtime/lib/python3.14/os.py", "/etc/passwd"]
    result = PythonStrategyRuntime().invoke(
        source, context={"session": "2026-08-03"}, state={}, parameters={"paths": paths},
    )
    assert {path: result.output[path] for path in paths} == dict.fromkeys(paths, "denied")
    assert result.output["write"] == "denied"
    assert all(result.output[name] == "unavailable" for name in ("socket", "subprocess", "ctypes"))
    assert result.output["environment"] == {
        "PYTHONHOME": "/runtime", "PYTHONHASHSEED": "0", "TZ": "UTC",
    }
    assert all(path.read_text() == "private host sentinel" for path in sentinels)


def test_account_context_is_read_only_and_host_values_are_unchanged():
    context = {"session": "2026-08-03", "account": {"cash": "100", "positions": [{"shares": 1}]}}
    original = copy.deepcopy(context)
    source = """
def decide(context, state, parameters):
    context["account"]["cash"] = "999999"
    return {"output": None, "state": {}}
"""
    with pytest.raises(StrategyProgramError, match="TypeError") as caught:
        PythonStrategyRuntime().invoke(source, context=context, state={}, parameters={})
    assert context == original
    assert caught.value.session == "2026-08-03"
    assert caught.value.line == 3


@pytest.mark.parametrize("body", [
    "while True:\n    pass",
    "bytearray(512 * 1024 * 1024)",
    "__import__('os').write(1, b'x' * (2 * 1024 * 1024))",
    "__import__('time').sleep(3600)",
    "return {'output': None, 'state': {'large': 'x' * (300 * 1024)}}",
])
def test_resource_failure_is_bounded_and_the_next_guest_still_completes(body):
    runtime = PythonStrategyRuntime()
    source = "def decide(context, state, parameters):\n" + textwrap.indent(body, "    ")
    started = time.monotonic()
    with pytest.raises(StrategyProgramError):
        runtime.invoke(source, context={"session": "2026-08-03"}, state={}, parameters={})
    assert time.monotonic() - started < 10
    result = runtime.invoke(
        "def decide(context, state, parameters):\n"
        "    return {'output': None, 'state': {'ok': True}}",
        context={"session": "2026-08-04"}, state={}, parameters={},
    )
    assert result.state == {"ok": True}


@pytest.mark.parametrize("returned", [
    "{}", "{'output': None}", "{'output': None, 'state': None}",
    "{'output': None, 'state': {'bad': float('nan')}}",
    "{'output': None, 'state': {}, 'implicit_state': 1}",
])
def test_invalid_output_never_becomes_an_empty_successful_state(returned):
    source = "def decide(context, state, parameters):\n    return " + returned
    with pytest.raises(StrategyProgramError):
        PythonStrategyRuntime().invoke(
            source, context={"session": "2026-08-03"}, state={"retained": 1}, parameters={},
        )


def test_validation_reports_the_program_and_source_line_without_executing_it():
    runtime = PythonStrategyRuntime()
    runtime.validate("raise RuntimeError('validation does not execute source')")
    with pytest.raises(StrategyProgramError, match="SyntaxError") as caught:
        runtime.validate("def decide(context, state, parameters)\n    return {}")
    assert caught.value.line == 1
    assert caught.value.session is None
    assert len(caught.value.program_sha256) == 64


@pytest.mark.parametrize("diagnostics", ["{}", "'x' * 65537"])
def test_guest_cannot_bypass_host_validation_by_writing_its_own_response(diagnostics):
    source = f"""
import json
import os
os.write(1, json.dumps({{
    "ok": True, "result": {{"output": None, "state": {{}}}},
    "diagnostics": {diagnostics},
}}).encode())
os._exit(0)
"""
    with pytest.raises(StrategyProgramError, match="diagnostics"):
        PythonStrategyRuntime().invoke(
            source, context={"session": "2026-08-03"}, state={}, parameters={},
        )

"""Exercise the installed Python guest inside the final Core image."""

import json
import os
import socket
import subprocess
import sys
import tempfile
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from thesistrace.research_kernel.daily_strategy import prepare_daily_strategy
from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)
from thesistrace.research_series import AlignedResearchData

SOURCE = """
import datetime
import os
import random

def decide(context, state, parameters):
    observed = {}
    for path in parameters['paths']:
        try:
            observed[path] = open(path).read()
        except OSError:
            observed[path] = 'denied'
    for name in ('socket', 'subprocess', 'ctypes'):
        try:
            __import__(name)
            observed[name] = 'available'
        except ImportError:
            observed[name] = 'denied'
    try:
        import _socket
        connection = _socket.socket()
        connection.connect(('127.0.0.1', parameters['port']))
        observed['network'] = 'connected'
    except (ImportError, OSError):
        observed['network'] = 'denied'
    try:
        os.write(3, b'thesistrace-python-ready/v1')
        observed['restart_deadline'] = 'allowed'
    except OSError:
        observed['restart_deadline'] = 'denied'
    return {'output': {
        'resources': observed,
        'environment': dict(os.environ),
        'clock': datetime.datetime.now(datetime.UTC).isoformat(),
        'random': [random.random(), random.SystemRandom().randint(1, 1000000)],
    }, 'state': {'count': state['count'] + 1}}
"""


def invoke(runtime, parameters):
    return runtime.invoke(
        SOURCE, context={"session": "2026-08-03"}, state={"count": 1},
        parameters=parameters,
    )


def probe_framework(parameters):
    """Invoke each actual Framework module through the installed policy adapter."""
    session = "2026-08-03"
    data = AlignedResearchData(
        sessions=(session,), instruments={}, fields={}, universe_members={session: ()},
        historical_universe_members={session: ()}, industries={}, execution_prices={},
        trading_states={}, price_limits={},
    )
    source = SOURCE.replace("def decide(", "def observe(") + """
def decide(context, state, parameters):
    observation = observe(context, {'count': 1}, parameters)['output']
    try:
        context['account']['cash_cny'] = '999999'
        observation['account_writable'] = True
    except TypeError:
        observation['account_writable'] = False
    return {'output': None, 'state': observation}
"""
    stages = ["universe_selection", "alpha", "portfolio_construction", "risk_management"]
    definition = {"strategy": {
        "mode": "framework", "environment": PythonStrategyRuntime().identity(),
        "modules": {stage: {"kind": "python", "program": {
            "source": source, "parameters": parameters,
            "data_requirements": {"field_ids": [], "history_sessions": 1},
        }} for stage in stages},
    }}
    account = {"positions": [], "cash_cny": "100000"}

    def decide(value):
        policy = prepare_daily_strategy(data, None, value)
        return policy.decide(session=session, report_index=0, account=account,
                             fills=[], rejections=[], previous=None)

    result = decide(definition)
    for stage in stages:
        observed = result.state["module_states"][stage]
        assert observed["resources"] == dict.fromkeys(
            [*parameters["paths"], "socket", "subprocess", "ctypes", "network",
             "restart_deadline"], "denied",
        )
        assert observed["environment"] == {
            "PYTHONHOME": "/runtime", "PYTHONHASHSEED": "0", "TZ": "UTC",
        }
        assert observed["account_writable"] is False
    assert result.target is None
    assert account == {"positions": [], "cash_cny": "100000"}
    direct = {"strategy": {
        "mode": "direct", "environment": definition["strategy"]["environment"],
        "program": deepcopy(definition["strategy"]["modules"]["portfolio_construction"]["program"]),
    }}
    direct_result = decide(direct)
    for key in ("resources", "environment", "clock", "account_writable"):
        assert direct_result.state["state"][key] == (
            result.state["module_states"]["portfolio_construction"][key]
        )
    failures = {
        "loop": "while True: pass",
        "memory": "bytearray(512 * 1024 * 1024); return {'output': None, 'state': {}}",
        "output": "return {'output': 'x' * (2 * 1024 * 1024), 'state': {}}",
        "state_size": "return {'output': None, 'state': {'large': 'x' * (300 * 1024)}}",
        "exception": "raise ValueError('expected probe failure')",
        "invalid_state": "return {'output': None, 'state': {'invalid': float('nan')}}",
    }
    expected_errors = {
        "loop": ("resource or capability limits", "wall time limit"),
        "memory": ("MemoryError", "resource or capability limits"),
        "output": ("resource or capability limits",),
        "state_size": ("state exceeds 262144 bytes",),
        "exception": ("expected probe failure",),
        "invalid_state": ("Out of range float", "finite JSON values"),
    }
    for mode, valid in (("direct", direct), ("framework", definition)):
        for case, body in failures.items():
            failing = deepcopy(valid)
            program = (failing["strategy"]["program"] if mode == "direct" else
                       failing["strategy"]["modules"]["universe_selection"]["program"])
            program["source"] = "def decide(context, state, parameters):\n    " + body
            try:
                decide(failing)
            except StrategyProgramError as error:
                assert error.session == session
                assert any(reason in str(error) for reason in expected_errors[case]), (case, error)
                if mode == "framework":
                    assert "universe_selection" in str(error)
            else:
                raise AssertionError(f"Unbounded or invalid {mode} program succeeded")
            assert decide(direct) == direct_result
        assert decide(valid) == (direct_result if mode == "direct" else result)
    assert account == {"positions": [], "cash_cny": "100000"}
    return {"stages": stages, "authority_unchanged": True, "bounded_failure_recovered": True,
            "failure_cases": list(failures), "modes": ["direct", "framework"]}


def main():
    runtime = PythonStrategyRuntime()
    if len(sys.argv) > 1:
        print(json.dumps(asdict(invoke(runtime, json.loads(sys.argv[1])))))
        return
    os.environ["THESISTRACE_PRIVATE_SENTINEL"] = "private-worker-sentinel"
    with tempfile.TemporaryDirectory() as temporary, socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        # A connection failure only proves isolation if the host can reach the
        # same live endpoint. Keep it listening throughout guest and replay calls.
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
        sentinel = Path(temporary) / "private-dataset-and-source"
        sentinel.write_text("private-host-content")
        paths = [str(sentinel), "/etc/passwd", "/app/src/thesistrace/__init__.py"]
        parameters = {"paths": paths, "port": port}
        result = invoke(runtime, parameters)
        assert result.output["resources"] == dict.fromkeys(
            [*paths, "socket", "subprocess", "ctypes", "network", "restart_deadline"], "denied",
        )
        assert result.output["environment"] == {
            "PYTHONHOME": "/runtime", "PYTHONHASHSEED": "0", "TZ": "UTC",
        }
        assert result.output["clock"] == "2026-08-03T07:00:00+00:00"
        assert result.state == {"count": 2}
        replay = subprocess.run(
            [sys.executable, __file__, json.dumps(parameters)], check=True,
            text=True, capture_output=True, timeout=20,
        )
        assert json.loads(replay.stdout) == asdict(result)
        try:
            runtime.invoke(
                "def decide(context, state, parameters):\n    while True: pass",
                context={"session": "2026-08-03"}, state={}, parameters={},
            )
        except StrategyProgramError:
            pass
        else:
            raise AssertionError("Unbounded guest execution succeeded")
        assert invoke(runtime, parameters) == result
        framework = probe_framework(parameters)
        assert sentinel.read_text() == "private-host-content"
    print(json.dumps({"status": "passed", "runtime": runtime.identity(), "framework": framework}))


if __name__ == "__main__":
    main()

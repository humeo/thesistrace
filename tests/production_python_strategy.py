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

def observe(context, state, parameters):
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


def program_source(parameters, base="Strategy", *, observation=False):
    callback = (
        "        self.state = observed['state']\n"
        "        return Decision(observed['output'])\n" if observation else
        "        self.state = observed['output']\n"
        "        try:\n"
        "            account.cash_cny = '999999'\n"
        "            self.state['account_writable'] = True\n"
        "        except TypeError:\n"
        "            self.state['account_writable'] = False\n"
        "        return None\n"
    )
    return (f"from quantgrove import {base}, Decision\nCONFIG = {parameters!r}\n"
            + SOURCE + f"\nclass Probe({base}):\n"
            "    def on_close(self, data, account):\n"
            "        observed = observe({}, {'count': 1}, CONFIG)\n" + callback)


def invoke(runtime, parameters):
    return runtime.invoke(
        program_source(parameters, observation=True),
        context={"session": "2026-08-03"}, state={"count": 1},
    )


def probe_framework(parameters):
    """Invoke each actual Framework module through the installed policy adapter."""
    session = "2026-08-03"
    data = AlignedResearchData(
        sessions=(session,), instruments={}, fields={}, universe_members={session: ()},
        historical_universe_members={session: ()}, industries={}, execution_prices={},
        trading_states={}, price_limits={},
    )
    stages = {
        "universe_selection": "UniverseSelection", "alpha": "Alpha",
        "portfolio_construction": "PortfolioConstruction", "risk_management": "RiskManagement",
    }
    definition = {"strategy": {
        "mode": "framework", "environment": PythonStrategyRuntime().identity(),
        "modules": {stage: {"kind": "python", "program": {
            "source": program_source(parameters, base),
        }} for stage, base in stages.items()},
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
        "program": {"source": program_source(parameters)},
    }}
    direct_result = decide(direct)
    for key in ("resources", "environment", "clock", "account_writable"):
        assert direct_result.state["state"][key] == (
            result.state["module_states"]["portfolio_construction"][key]
        )
    failures = {
        "loop": "while True: pass",
        "memory": "bytearray(512 * 1024 * 1024)",
        "output": "__import__('os').write(1, b'x' * (2 * 1024 * 1024))",
        "state_size": "self.state['large'] = 'x' * (300 * 1024)",
        "exception": "raise ValueError('expected probe failure')",
        "invalid_state": "self.state['invalid'] = float('nan')",
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
            base = "Strategy" if mode == "direct" else "UniverseSelection"
            program["source"] = (f"from quantgrove import {base}\nclass Failure({base}):\n"
                                 "    def on_close(self, data, account):\n        " + body)
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
    return {"stages": list(stages), "authority_unchanged": True, "bounded_failure_recovered": True,
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
        assert json.loads(replay.stdout) == json.loads(json.dumps(asdict(result)))
        try:
            runtime.invoke(
                "from quantgrove import Strategy\nclass Loop(Strategy):\n"
                "    def on_close(self, data, account):\n        while True: pass",
                context={"session": "2026-08-03"}, state={},
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

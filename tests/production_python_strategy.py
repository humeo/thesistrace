"""Exercise the installed Python guest inside the final Core image."""

import json
import os
import socket
import subprocess
import sys
import tempfile
from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from thesistrace.research_kernel.batch_program import PreparedProgramBlock
from thesistrace.research_kernel.daily_strategy import prepare_daily_strategy
from thesistrace.research_kernel.direct_strategy import PythonProgram
from thesistrace.research_kernel.program_wire import decode_state
from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)
from thesistrace.research_series import AlignedResearchData

SOURCE = """
import datetime
import os
import random
import numpy as np

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
        'numpy': {
            'version': np.__version__,
            'squares': np.square(np.arange(8, dtype=float)).tolist(),
            'linear_system': np.linalg.solve([[3., 1.], [1., 2.]], [9., 8.]).tolist(),
            'fft': np.fft.fft([1., 2., 3., 4.]).real.tolist(),
            'clock': str(np.datetime64('now')),
            'random': np.random.default_rng().integers(0, 1000000, size=5).tolist(),
            'legacy': np.random.randint(0, 1000000, size=5).tolist(),
        },
    }, 'state': {'count': state['count'] + 1}}
"""


def program_source(parameters, *, observation=False):
    callback = (
        "    state.update(observed['state'])\n"
        "    return Decision(observed['output'])\n" if observation else
        "    state.update(observed['output'])\n"
        "    try:\n"
        "        account.cash_cny = '999999'\n"
        "        state['account_writable'] = True\n"
        "    except TypeError:\n"
        "        state['account_writable'] = False\n"
        "    return None\n"
    )
    return (f"from quantgrove import Decision\nCONFIG = {parameters!r}\n"
            + SOURCE + "\ndef decide(data, account, state):\n"
            "    observed = observe({}, {'count': 1}, CONFIG)\n" + callback)


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
    stages = ("universe_selection", "alpha", "portfolio_construction", "risk_management")
    definition = {"strategy": {
        "mode": "framework", "environment": PythonStrategyRuntime().identity(),
        "modules": {stage: {"kind": "python", "program": {
            "source": program_source(parameters),
        }} for stage in stages},
    }}
    account = {"positions": [], "cash_cny": "100000"}

    def decide(value):
        policy = prepare_daily_strategy(data, None, value)
        return policy.decide(session=session, report_index=0, account=account,
                             fills=[], rejections=[], previous=None)

    result = decide(definition)
    for stage in stages:
        observed = result.state["module_states"][stage]["decision"]
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
        assert direct_result.state["state"]["decision"][key] == (
            result.state["module_states"]["portfolio_construction"]["decision"][key]
        )
    failures = {
        "loop": "while True: pass",
        "memory": "bytearray(512 * 1024 * 1024)",
        "output": "while True: __import__('os').write(1, b'x' * 65536)",
        "numpy_memory": "__import__('numpy').ones(128 * 1024 * 1024, dtype='float64')",
        "state_size": "state['large'] = 'x' * (300 * 1024)",
        "exception": "raise ValueError('expected probe failure')",
        "invalid_state": "state['invalid'] = float('nan')",
    }
    expected_errors = {
        "loop": ("resource or capability limits", "wall time limit"),
        "memory": ("MemoryError", "resource or capability limits"),
        "numpy_memory": ("MemoryError", "resource or capability limits"),
        "output": ("resource or capability limits", "Program output limit exceeded"),
        "state_size": ("state exceeds 262144 bytes",),
        "exception": ("expected probe failure",),
        "invalid_state": ("Out of range float", "finite JSON values"),
    }
    for mode, valid in (("direct", direct), ("framework", definition)):
        for case, body in failures.items():
            failing = deepcopy(valid)
            program = (failing["strategy"]["program"] if mode == "direct" else
                       failing["strategy"]["modules"]["universe_selection"]["program"])
            program["source"] = ("def decide(data, account, state):\n    " + body)
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


def probe_batch():
    """Installed binary transport, 128-date calculation and T=1 state restoration."""
    sessions = tuple((date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(129))
    stock = "equity:600000.SH"
    data = AlignedResearchData(
        sessions=sessions, instruments={},
        fields={"price.close.adjusted": {(day, stock): "10" for day in sessions}},
        universe_members={day: (stock,) for day in sessions},
        historical_universe_members={day: (stock,) for day in sessions},
        industries={}, execution_prices={}, trading_states={}, price_limits={},
    )
    source = '''
import numpy as np
from quantgrove import Targets

def compute(data, state):
    prices = data.history("price.close.adjusted", lookback=1)
    dates = data.history_sessions("price.close.adjusted", lookback=1)
    assert dates[-len(data.sessions):] == data.sessions
    state["days"] = state.get("days", 0) + len(data.sessions)
    state["last"] = prices[:, -1].copy()
    return Targets.equal_weight(
        np.isfinite(prices[:, 1:]), priority=prices[:, 1:],
        update=data.session_index % 5 == 0,
    )
'''
    prepared = PreparedProgramBlock(data, PythonProgram(source=source), PythonStrategyRuntime(),
                                    sessions, 0)
    dates, instruments, output, result = prepared.compute(sessions[0], {}, {"positions": []})
    assert dates == sessions[:128] and instruments == (stock,)
    np.testing.assert_array_equal(output["weights"], np.ones((1, 128), dtype=bool))
    np.testing.assert_array_equal(output["priority"], np.full((1, 128), 10.0))
    np.testing.assert_array_equal(output["update"], np.arange(128) % 5 == 0)
    dates, _, output, result = prepared.compute(sessions[128], result.state, {"positions": []})
    assert dates == sessions[128:] and output["update"].tolist() == [False]
    state = decode_state(result.state)
    assert state["days"] == 129
    np.testing.assert_array_equal(state["last"], [10.0])
    return {"output_dates": 128, "restored_dates": 1, "state_days": state["days"]}


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
        assert result.output["numpy"]["version"] == runtime.identity()["numpy"]
        assert result.output["numpy"]["squares"] == [0, 1, 4, 9, 16, 25, 36, 49]
        assert result.output["numpy"]["linear_system"] == [2, 3]
        assert result.output["numpy"]["fft"] == [10, -2, -2, -2]
        assert result.output["numpy"]["clock"] == "2026-08-03T07:00:00"
        assert result.state == {"count": 2}
        for replay_index in range(30):
            replay = subprocess.run(
                [sys.executable, __file__, json.dumps(parameters)], check=False,
                text=True, capture_output=True, timeout=20,
                env={**os.environ, "PYTHONFAULTHANDLER": "1"},
            )
            if replay.returncode:
                raise RuntimeError(
                    f"Installed guest replay {replay_index} exited {replay.returncode}: "
                    f"{replay.stderr[-65536:]}"
                )
            assert json.loads(replay.stdout) == json.loads(json.dumps(asdict(result)))
        try:
            runtime.invoke(
                "def decide(data, account, state):\n    while True: pass",
                context={"session": "2026-08-03"}, state={},
            )
        except StrategyProgramError:
            pass
        else:
            raise AssertionError("Unbounded guest execution succeeded")
        assert invoke(runtime, parameters) == result
        framework = probe_framework(parameters)
        assert sentinel.read_text() == "private-host-content"
    print(json.dumps({"status": "passed", "runtime": runtime.identity(), "framework": framework,
                      "batch": probe_batch()}))


if __name__ == "__main__":
    main()

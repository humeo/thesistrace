"""Exercise the installed Python guest inside the final Core image."""

import json
import os
import socket
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from thesistrace.research_kernel.strategy_program_runtime import (
    PythonStrategyRuntime,
    StrategyProgramError,
)

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
        assert sentinel.read_text() == "private-host-content"
    print(json.dumps({"status": "passed", "runtime": runtime.identity()}))


if __name__ == "__main__":
    main()

import json
import os
import subprocess
import sys
import time
from itertools import count
from types import SimpleNamespace

import pytest

from thesistrace.research_kernel.python_execution import (
    PreparedPythonEnvironment,
    PythonExecutionTimeout,
)

pytestmark = pytest.mark.bounded_process


def test_output_sessions_finish_before_the_host_interpreter_exits():
    # Native WASIp2 output cleanup can outlive Store.close(). A fresh process
    # must exit normally immediately after its last successful guest call.
    source = """
import json, subprocess, sys
from pathlib import Path
from thesistrace.research_kernel.python_execution import PreparedPythonEnvironment
environment = PreparedPythonEnvironment('print(42)')
assert environment.invoke(b'', clock_time_ns=0) == b'42\\n'
print('completed', flush=True)
"""
    for iteration in range(50):
        child = subprocess.run(
            [sys.executable, "-c", source], capture_output=True, text=True,
            timeout=20, env={**os.environ, "PYTHONFAULTHANDLER": "1"},
        )
        assert child.returncode == 0, (iteration, child.returncode, child.stderr)
        assert child.stdout == "completed\n"


def test_prepared_identity_tracks_the_actual_bootstrap_and_module_sources():
    modules = {"helper": "value = 1"}
    with PreparedPythonEnvironment("import helper\nprint(helper.value)",
                                   module_sources=modules) as first:
        identity = first.identity()
        modules["helper"] = "value = 2"
        assert first.identity() == identity
        assert first.invoke(b"", clock_time_ns=0) == b"1\n"
        with PreparedPythonEnvironment("import helper\nprint(helper.value)",
                                       module_sources=modules) as second:
            assert second.identity() != identity
            assert second.invoke(b"", clock_time_ns=0) == b"2\n"


def test_prepared_python_executes_an_opaque_protocol_and_isolates_module_mutations():
    bootstrap = """
import json, sys, helper
from _thesistrace_execution import ready, read_request
request = json.loads(sys.stdin.buffer.read())
ready()
reply = read_request(request['message'].encode()).decode()
output = {'value': helper.double(request['value']), 'counter': helper.counter, 'reply': reply}
helper.counter += 1
print(json.dumps(output))
"""
    environment = PreparedPythonEnvironment(
        bootstrap,
        module_sources={"helper": "counter = 0\ndef double(value): return value * 2\n"},
    )
    request = json.dumps({"value": 21, "message": "hello"}).encode()
    for _ in range(2):
        result = environment.invoke(request, clock_time_ns=0, read_request=bytes.upper)
        assert json.loads(result) == {"value": 42, "counter": 0, "reply": "HELLO"}
    environment.close()
    environment.close()
    with pytest.raises(ValueError, match="closed"):
        environment.invoke(request, clock_time_ns=0)


def test_controlled_host_reads_do_not_consume_the_python_execution_budget():
    def slow_read(request):
        # Deliberately exceed the real 3-second compute budget inside the
        # platform capability, without spending it in the guest program.
        time.sleep(3.2)
        return request.upper()

    with PreparedPythonEnvironment(
        "from _thesistrace_execution import ready, read_request\n"
        "ready()\nprint(read_request(b'hello').decode())",
    ) as environment:
        assert environment.invoke(b"", clock_time_ns=0, read_request=slow_read) == b"HELLO\n"


def test_repeated_host_reads_cannot_replenish_compute_time(monkeypatch):
    from thesistrace.research_kernel import python_execution as execution

    # Account for a fixed guest interval between clock reads so the cumulative
    # budget assertion does not depend on how fast this machine serves requests.
    ticks = count(step=0.05)
    monkeypatch.setattr(execution, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(execution, "WALL_SECONDS", 0.25)
    with PreparedPythonEnvironment(
        "from _thesistrace_execution import ready, read_request, payload\nready()\n"
        "if payload:\n    for _ in range(10): read_request(b'hello')\n"
        "print('healthy')",
    ) as environment:
        with pytest.raises(PythonExecutionTimeout) as error:
            environment.invoke(b"run", clock_time_ns=0, read_request=bytes.upper)
        assert error.value.phase == "program"
        assert environment.invoke(b"", clock_time_ns=0) == b"healthy\n"


def test_host_read_failure_does_not_poison_a_later_call():
    def rejected_read(_request):
        raise OSError("private host detail")

    with PreparedPythonEnvironment(
        "from _thesistrace_execution import ready, read_request\n"
        "ready()\nprint(read_request(b'hello').decode())",
    ) as environment:
        with pytest.raises(ValueError, match="resource or capability") as error:
            environment.invoke(b"", clock_time_ns=0, read_request=rejected_read)
        assert "private host detail" not in str(error.value)
        assert environment.invoke(b"", clock_time_ns=0, read_request=bytes.upper) == b"HELLO\n"


@pytest.mark.parametrize(
    "body, response",
    [
        ("read_request(b'request')", b"x" * (33 * 1024**2)),
        ("read_request(b'x' * 65537)", b""),
        ("[read_request(b'x') for _ in range(65)]", b""),
        ("[read_request(b'x') for _ in range(9)]", b"x" * (4 * 1024**2)),
        ("ready()", b""),
    ],
    ids=["response_bytes", "request_bytes", "request_count", "total_response_bytes", "readiness"],
)
def test_prepared_python_enforces_capability_limits(body, response):
    with PreparedPythonEnvironment(
        "from _thesistrace_execution import ready, read_request\nready()\n" + body,
    ) as environment:
        with pytest.raises(ValueError, match="resource or capability"):
            environment.invoke(b"", clock_time_ns=0, read_request=lambda _: response)


def test_prepared_libraries_are_available_without_restoring_file_authority():
    with PreparedPythonEnvironment("""
import sys
from _thesistrace_execution import ready
sys.path.clear()
sys.path_importer_cache.clear()
ready()
from statistics import fmean
import numpy as np
print(fmean([1, 2, 3]), np.add([1, 2], [3, 4]).tolist())
try:
    open('/runtime/lib/python3.14/statistics.py').read()
except OSError:
    print('denied')
""") as environment:
        assert environment.invoke(b"", clock_time_ns=0) == b"2.0 [4, 6]\ndenied\n"


def test_prepared_output_handles_short_wasi_writes_and_bounds_total_output():
    with PreparedPythonEnvironment(
        "from _thesistrace_execution import ready, payload\nready()\nprint('数值' * int(payload))",
    ) as environment:
        assert environment.invoke(b"12000", clock_time_ns=0) == ("数值" * 12000 + "\n").encode()
        with pytest.raises(ValueError):
            environment.invoke(b"3000000", clock_time_ns=0)
        assert environment.invoke(b"1", clock_time_ns=0) == "数值\n".encode()


def test_rejected_guests_do_not_delay_collection_inside_a_later_healthy_call():
    import gc

    def collect(_request):
        gc.collect()
        return b'healthy'

    enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(3):
            with PreparedPythonEnvironment(
                'from _thesistrace_execution import ready\nready()\nready()',
            ) as environment:
                try:
                    environment.invoke(b'', clock_time_ns=0)
                except ValueError as error:
                    assert 'resource or capability' in str(error)
                else:
                    pytest.fail('Repeated readiness must be rejected')
        with PreparedPythonEnvironment(
            'from _thesistrace_execution import ready, read_request\n'
            'ready()\nprint(read_request(b"collect").decode())',
        ) as environment:
            assert environment.invoke(b'', clock_time_ns=0, read_request=collect) == b'healthy\n'
    finally:
        if enabled:
            gc.enable()
        gc.collect()

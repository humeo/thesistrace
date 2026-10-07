import json

import pytest

from thesistrace.research_kernel.python_execution import PreparedPythonEnvironment

pytestmark = pytest.mark.bounded_process


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


@pytest.mark.parametrize("body, response", [
    ("read_request(b'request')", b"x" * (5 * 1024**2)),
    ("read_request(b'x' * 65537)", b""),
    ("[read_request(b'x') for _ in range(65)]", b""),
    ("[read_request(b'x') for _ in range(5)]", b"x" * (4 * 1024**2)),
    ("ready()", b""),
])
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
        "from _thesistrace_execution import ready, payload\nready()\n"
        "print('数值' * int(payload))",
    ) as environment:
        assert environment.invoke(b"12000", clock_time_ns=0) == ("数值" * 12000 + "\n").encode()
        with pytest.raises(ValueError):
            environment.invoke(b"200000", clock_time_ns=0)
        assert environment.invoke(b"1", clock_time_ns=0) == "数值\n".encode()

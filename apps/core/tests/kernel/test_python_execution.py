import json
from pathlib import Path

import pytest

from thesistrace.research_kernel.python_execution import PreparedPythonEnvironment

pytestmark = pytest.mark.bounded_process


def test_prepared_identity_tracks_loaded_sources_and_library_limits(tmp_path, monkeypatch):
    from thesistrace.research_kernel import python_execution

    loader = Path(python_execution.__file__).with_name("python_library_guest.py")
    staged_loader = tmp_path / loader.name
    staged_loader.write_bytes(loader.read_bytes())
    monkeypatch.setattr(python_execution, "__file__", str(tmp_path / "python_execution.py"))
    with PreparedPythonEnvironment("print('hello')", ()) as first:
        identity = first.identity()
        staged_loader.write_text(staged_loader.read_text() + "\n# Revised loader\n")
        assert first.identity() == identity
        with PreparedPythonEnvironment("print('hello')", ()) as second:
            assert second.identity() != identity
            assert second.invoke(b"", clock_time_ns=0) == first.invoke(b"", clock_time_ns=0)
        assert identity["library_requests"] == 256
        assert identity["library_request_bytes"] == 200
        assert identity["library_response_bytes"] == 16 * 1024 * 1024


def test_prepared_python_executes_an_opaque_protocol_and_isolates_module_mutations():
    bootstrap = """
import json, os, sys
request = json.loads(sys.stdin.buffer.read())
os.close(0)
os.close(3)
os.write(3, b'thesistrace-python-ready/v1')
import helper
os.write(4, request['message'].encode())
reply = os.pread(4, 1024, 0).decode()
output = {'value': helper.double(request['value']), 'counter': helper.counter, 'reply': reply}
helper.counter += 1
print(json.dumps(output))
"""
    environment = PreparedPythonEnvironment(
        bootstrap, (),
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


def test_prepared_python_rejects_oversized_capability_responses():
    environment = PreparedPythonEnvironment("""
import os
os.close(3)
os.close(0)
os.write(3, b'thesistrace-python-ready/v1')
os.write(4, b'request')
""", ())
    with pytest.raises(ValueError, match="resource or capability"):
        environment.invoke(b"", clock_time_ns=0, read_request=lambda _: b"x" * (5 * 1024**2))


def test_prepared_libraries_load_on_demand_without_restoring_file_authority():
    environment = PreparedPythonEnvironment("""
import os, sys
os.close(3)
os.close(0)
sys.path.clear()
sys.path_importer_cache.clear()
os.write(3, b'thesistrace-python-ready/v1')
from statistics import fmean
print(fmean([1, 2, 3]))
try:
    open('/runtime/lib/python3.14/statistics.py').read()
except OSError:
    print('denied')
""", ("statistics",))
    assert environment.invoke(b"", clock_time_ns=0) == b"2.0\ndenied\n"

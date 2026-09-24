"""The image probe must exercise actual Framework routing, not just a raw guest."""

import runpy
import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.bounded_process


def test_image_probe_checks_each_framework_stage_and_recovers(tmp_path):
    probe = runpy.run_path(str(Path(__file__).resolve().parents[4] /
                              "tests/production_python_strategy.py"))
    sentinel = tmp_path / "private-data"
    sentinel.write_text("private")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
        evidence = probe["probe_framework"]({"paths": [str(sentinel)], "port": port})
    assert evidence == {
        "stages": ["universe_selection", "alpha", "portfolio_construction", "risk_management"],
        "authority_unchanged": True, "bounded_failure_recovered": True,
        "failure_cases": ["loop", "memory", "output", "state_size", "exception", "invalid_state"],
        "modes": ["direct", "framework"],
    }
    assert sentinel.read_text() == "private"

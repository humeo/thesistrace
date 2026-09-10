from __future__ import annotations

import importlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from thesistrace.entrypoints import worker


@pytest.mark.parametrize("release_barrier", (True, False))
def test_cancellation_worker_requires_parent_release_before_advancing(
    monkeypatch: pytest.MonkeyPatch,
    release_barrier: bool,
) -> None:
    benchmark_path = Path(__file__).resolve().parents[2] / "benchmarks"
    monkeypatch.syspath_prepend(str(benchmark_path))
    benchmark = importlib.import_module("long_research_qualification")
    monkeypatch.setattr(
        sys, "argv", ["long_research_qualification.py", "cancel-worker", "--run-id", "run_test"]
    )
    chunk_visible = Event()
    advanced = Event()

    def emit(event: dict[str, object]) -> None:
        if event["event"] == "research_execution_chunk_received":
            chunk_visible.set()

    def process_one_poll(_runtime, _configuration, *, emit) -> None:
        try:
            emit({"event": "research_execution_chunk_received", "run_id": "run_test"})
        except RuntimeError:
            # The production event sink also absorbs callback errors.
            pass
        advanced.set()

    def main(_arguments: list[str]) -> None:
        worker.process_one_poll(None, None, emit=emit)

    monkeypatch.setattr(worker, "process_one_poll", process_one_poll)
    monkeypatch.setattr(worker, "main", main)
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd) as gate_input, os.fdopen(write_fd, "wb") as gate_output:
        monkeypatch.setattr(sys, "stdin", gate_input)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(benchmark.main)
            assert chunk_visible.wait(timeout=5)
            assert not advanced.wait(timeout=0.1)
            if release_barrier:
                gate_output.write(b"release\n")
                gate_output.flush()
                pending.result(timeout=5)
            else:
                gate_output.close()
                with pytest.raises(RuntimeError, match="did not release a ready Worker"):
                    pending.result(timeout=5)
            assert advanced.is_set()

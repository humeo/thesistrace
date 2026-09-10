from __future__ import annotations

import json
import select
import subprocess
import sys

import pytest

_CHILD = """
from thesistrace.entrypoints import research_child

def chunks(request, *, cancel_requested):
    yield {"status": "chunk_succeeded", "chunk": {"final": request["final"]}}
    raise AssertionError("calculation continued after cancellation")

research_child.execute_request_chunks = chunks
research_child.main()
"""


@pytest.mark.parametrize("final_chunk", (False, True))
def test_child_cancels_cleanly_while_waiting_for_chunk_acknowledgement(
    final_chunk: bool,
) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(json.dumps({"final": final_chunk}) + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 5)
        assert ready, "child did not produce its Chunk"
        response = json.loads(process.stdout.readline())
        assert response["status"] == "chunk_succeeded"
        assert response["chunk"]["final"] is final_chunk

        remaining, errors = process.communicate('{"command":"cancel"}\n', timeout=5)

        assert process.returncode == 0, errors
        assert remaining == ""
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

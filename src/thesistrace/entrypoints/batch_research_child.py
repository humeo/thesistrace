from __future__ import annotations

import json
import os
import queue
import sys
from contextlib import nullcontext
from threading import Thread

from thesistrace.data.io_metrics import cold_file_reads, measure_data_io
from thesistrace.research_batch.execution import execute_research_batch_messages


def main() -> None:
    request_line = sys.stdin.readline()
    if not request_line:
        raise SystemExit(64)
    request = json.loads(request_line)
    if not isinstance(request, dict):
        raise SystemExit(64)
    commands: queue.Queue[str] = queue.Queue()

    def watch_supervisor() -> None:
        while True:
            line = sys.stdin.readline()
            if not line:
                os._exit(74)
            value = json.loads(line)
            command = value.get("command") if isinstance(value, dict) else None
            if not isinstance(command, str):
                os._exit(65)
            commands.put(command)
            if command == "acknowledge_batch":
                return

    Thread(target=watch_supervisor, name="batch-research-supervisor-watch", daemon=True).start()
    cold_reads = os.environ.get("THESISTRACE_QUALIFICATION_COLD_DATA_READS") == "1"
    read_context = cold_file_reads() if cold_reads else nullcontext()
    with measure_data_io() as measurement, read_context:
        for response in execute_research_batch_messages(request):
            response["data_io"] = measurement.snapshot()
            print(json.dumps(response, sort_keys=True, separators=(",", ":")), flush=True)
            status = response.get("status")
            if status == "failed":
                raise SystemExit(1)
            expected = _expected_command(response)
            if commands.get() != expected:
                raise SystemExit(65)


def _expected_command(response: dict[str, object]) -> str:
    status = response.get("status")
    if status == "batch_prepared":
        return "acknowledge_preparation"
    if status == "item_failed":
        return "acknowledge_item"
    if status in {"shared_alpha_factor_succeeded", "shared_alpha_factor_failed"}:
        return "acknowledge_shared"
    if status == "item_succeeded":
        return "acknowledge_item"
    if status == "batch_succeeded":
        return "acknowledge_batch"
    if status == "item_chunk_succeeded":
        chunk = response.get("chunk")
        if not isinstance(chunk, dict):
            raise SystemExit(65)
        return "acknowledge_item" if chunk.get("final") is True else "acknowledge_chunk"
    raise SystemExit(65)


if __name__ == "__main__":
    main()

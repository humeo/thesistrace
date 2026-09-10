from __future__ import annotations

import json
import os
import queue
import sys
from contextlib import nullcontext
from threading import Event, Thread

from thesistrace.data.io_metrics import cold_file_reads, measure_data_io
from thesistrace.research_run.execution import execute_request_chunks


def main() -> None:
    request_line = sys.stdin.readline()
    if not request_line:
        raise SystemExit(64)
    request = json.loads(request_line)
    if not isinstance(request, dict):
        raise SystemExit(64)
    commands: queue.Queue[str] = queue.Queue()
    cancellation = Event()

    def watch_supervisor() -> None:
        while True:
            command = sys.stdin.readline()
            if not command:
                os._exit(74)
            value = json.loads(command)
            if value == {"command": "cancel"}:
                cancellation.set()
                commands.put(command)
                return
            commands.put(command)
            if value == {"command": "acknowledge"}:
                return

    Thread(target=watch_supervisor, name="research-supervisor-watch", daemon=True).start()
    cold_reads = os.environ.get("THESISTRACE_QUALIFICATION_COLD_DATA_READS") == "1"
    read_context = cold_file_reads() if cold_reads else nullcontext()
    with measure_data_io() as measurement, read_context:
        for response in execute_request_chunks(request, cancel_requested=cancellation.is_set):
            response["data_io"] = measurement.snapshot()
            print(json.dumps(response, sort_keys=True, separators=(",", ":")), flush=True)
            if response.get("status") == "cancelled":
                raise SystemExit(0)
            if response.get("status") != "chunk_succeeded":
                raise SystemExit(1)
            chunk = response.get("chunk")
            if not isinstance(chunk, dict):
                raise SystemExit(65)
            command = json.loads(commands.get())
            if command == {"command": "cancel"}:
                raise SystemExit(0)
            expected = "acknowledge" if chunk.get("final") is True else "acknowledge_chunk"
            if command != {"command": expected}:
                raise SystemExit(65)


if __name__ == "__main__":
    main()

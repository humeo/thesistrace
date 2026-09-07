from __future__ import annotations

import fcntl
import json
import os
import queue
import sys
from contextlib import nullcontext
from pathlib import Path
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
    control_path_value = request.get("attempt_control_path")
    if not isinstance(control_path_value, str):
        raise SystemExit(64)
    control_path = Path(control_path_value)
    if not control_path.is_absolute() or control_path.parent.name != ".batch-attempts":
        raise SystemExit(64)
    control_file = control_path.open("a+")
    fcntl.flock(control_file.fileno(), fcntl.LOCK_EX)
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
            if command == "cancel":
                os._exit(0)
            commands.put(command)
            if command == "acknowledge_batch":
                return

    Thread(target=watch_supervisor, name="batch-research-supervisor-watch", daemon=True).start()
    cold_reads = os.environ.get("THESISTRACE_QUALIFICATION_COLD_DATA_READS") == "1"
    read_context = cold_file_reads() if cold_reads else nullcontext()
    with measure_data_io() as measurement, read_context:
        print(
            json.dumps(
                {
                    "status": "child_ready",
                    "child_peak_rss_bytes": _current_peak_rss_bytes(),
                    "data_io": measurement.snapshot(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        if commands.get() != "acknowledge_ready":
            raise SystemExit(65)
        for response in execute_research_batch_messages(request):
            response["data_io"] = measurement.snapshot()
            print(json.dumps(response, sort_keys=True, separators=(",", ":")), flush=True)
            status = response.get("status")
            if status == "failed":
                raise SystemExit(1)
            expected = _expected_command(response)
            if commands.get() != expected:
                raise SystemExit(65)


def _current_peak_rss_bytes() -> int:
    import resource

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _expected_command(response: dict[str, object]) -> str:
    status = response.get("status")
    if status == "batch_prepared":
        return "acknowledge_preparation"
    if status in {
        "shared_alpha_factor_started",
        "shared_alpha_factor_chunk_succeeded",
        "item_started",
        "item_strategy_chunk_succeeded",
    }:
        return "acknowledge_progress"
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

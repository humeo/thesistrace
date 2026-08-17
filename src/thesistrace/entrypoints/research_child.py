from __future__ import annotations

import json
import os
import queue
import sys
from threading import Thread

from thesistrace.research_run.execution import execute_request


def main() -> None:
    request_line = sys.stdin.readline()
    if not request_line:
        raise SystemExit(64)
    request = json.loads(request_line)
    if not isinstance(request, dict):
        raise SystemExit(64)
    commands: queue.Queue[str] = queue.Queue(maxsize=1)

    def watch_supervisor() -> None:
        command = sys.stdin.readline()
        if not command:
            os._exit(74)
        commands.put(command)

    Thread(target=watch_supervisor, name="research-supervisor-watch", daemon=True).start()
    response = execute_request(request)
    print(json.dumps(response, sort_keys=True, separators=(",", ":")), flush=True)
    if response.get("status") != "succeeded":
        raise SystemExit(1)
    command = json.loads(commands.get())
    if command != {"command": "acknowledge"}:
        raise SystemExit(65)


if __name__ == "__main__":
    main()

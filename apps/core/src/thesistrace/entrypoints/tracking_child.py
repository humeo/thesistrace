from __future__ import annotations

import json
import os
import queue
import resource
import sys
from threading import Condition, Thread
from time import monotonic

from thesistrace.daily_track.calculation import execute_tracking_target


def main() -> None:
    request_line = sys.stdin.readline()
    if not request_line:
        raise SystemExit(64)
    value = json.loads(request_line)
    if not isinstance(value, dict):
        raise SystemExit(64)
    commands: queue.Queue[str] = queue.Queue()
    watchdog_grace = value.get("watchdog_grace_seconds")
    if not isinstance(watchdog_grace, (int, float)) or watchdog_grace <= 0:
        raise SystemExit(64)
    watchdog = Condition()
    last_heartbeat = monotonic()
    terminal_command_received = False

    def enforce_supervisor_watchdog() -> None:
        nonlocal last_heartbeat
        with watchdog:
            while not terminal_command_received:
                remaining = last_heartbeat + float(watchdog_grace) - monotonic()
                if remaining <= 0:
                    os._exit(75)
                watchdog.wait(timeout=remaining)

    def watch_supervisor() -> None:
        nonlocal last_heartbeat, terminal_command_received
        while True:
            command_line = sys.stdin.readline()
            if not command_line:
                os._exit(74)
            command = json.loads(command_line)
            if command == {"command": "heartbeat"}:
                with watchdog:
                    last_heartbeat = monotonic()
                    watchdog.notify_all()
                continue
            if command == {"command": "cancel"}:
                os._exit(76)
            with watchdog:
                terminal_command_received = True
                watchdog.notify_all()
            commands.put(command_line)
            return

    Thread(target=watch_supervisor, name="tracking-supervisor-watch", daemon=True).start()
    Thread(
        target=enforce_supervisor_watchdog,
        name="tracking-supervisor-watchdog",
        daemon=True,
    ).start()
    try:
        target_sessions = value.get("target_sessions")
        if not isinstance(target_sessions, list) or not target_sessions:
            raise ValueError("Tracking Target sessions are required")
        print(
            json.dumps(
                {
                    "status": "progress",
                    "phase": "calculating",
                    "current_session": target_sessions[0],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        response = execute_tracking_target(value)
        response["child_peak_rss_bytes"] = _peak_rss_bytes()
        print(
            json.dumps(
                {
                    "status": "progress",
                    "phase": "result_ready",
                    "current_session": target_sessions[-1],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "category": type(error).__name__,
                    "message": str(error),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        raise SystemExit(1) from error
    print(json.dumps(response, sort_keys=True, separators=(",", ":")), flush=True)
    if json.loads(commands.get()) != {"command": "acknowledge"}:
        raise SystemExit(65)


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


if __name__ == "__main__":
    main()

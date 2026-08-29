from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

BENCHMARK_START = date(2010, 1, 4)
MARKET_END = date(2026, 8, 5)


def build_replay(source: dict[str, object]) -> dict[str, object]:
    replay = deepcopy(source)
    snapshot = replay["snapshot"]
    assert isinstance(snapshot, dict)
    sessions = _weekdays(BENCHMARK_START, MARKET_END)
    compact_sessions = [session.strftime("%Y%m%d") for session in sessions]
    existing_levels = {
        str(row["trade_date"]): str(row["open"])
        for row in snapshot["benchmark_index_daily"]
    }
    first_level = Decimal(existing_levels[compact_sessions[0]])
    last_level = Decimal(existing_levels[compact_sessions[-1]])
    denominator = Decimal(len(compact_sessions) - 1)
    snapshot["benchmark_index_daily"] = [
        {
            "ts_code": "399300.SZ",
            "trade_date": session,
            "open": existing_levels.get(
                session,
                format(
                    (
                        first_level
                        + (last_level - first_level) * Decimal(index) / denominator
                    ).quantize(Decimal("0.01")),
                    "f",
                ),
            ),
        }
        for index, session in enumerate(compact_sessions)
    ]
    replay["request_start"] = BENCHMARK_START.isoformat()
    replay["request_end"] = MARKET_END.isoformat()
    return replay


def _weekdays(start: date, end: date) -> list[date]:
    sessions: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    replay = build_replay(json.loads(arguments.input.read_text()))
    arguments.output.write_text(
        json.dumps(replay, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

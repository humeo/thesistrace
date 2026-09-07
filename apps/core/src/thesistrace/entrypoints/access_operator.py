from __future__ import annotations

import argparse
import json
import os
import sys
from typing import NoReturn
from uuid import UUID

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import DailyTrackAccessInspector
from thesistrace.entrypoints.schema import verify_core_schema


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        _fail("INVALID_USAGE", 2)


def main(arguments: list[str] | None = None) -> None:
    parser = _SafeArgumentParser(description="ThesisTrace private access inspection")
    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_SafeArgumentParser,
    )
    active_tracks = subcommands.add_parser("active-daily-tracks")
    active_tracks.add_argument("--researcher-id", required=True, type=UUID)
    parsed = parser.parse_args(arguments)

    database_url = os.environ.get("THESISTRACE_DATABASE_URL", "").strip()
    if not database_url:
        _fail("POSTGRESQL_UNAVAILABLE", 4)

    database: PostgresDatabase | None = None
    try:
        database = PostgresDatabase(database_url)
        database.open()
        verify_core_schema(database)
        active_daily_track_count = DailyTrackAccessInspector(database).count_active(
            parsed.researcher_id
        )
    except Exception:
        _fail("POSTGRESQL_UNAVAILABLE", 4)
    finally:
        if database is not None:
            database.close()

    _write_json(
        sys.stdout,
        {
            "active_daily_track_count": active_daily_track_count,
            "researcher_id": str(parsed.researcher_id),
            "status": "inspected",
        },
    )
    _write_json(
        sys.stderr,
        {
            "event": "core_access_inspection_completed",
            "status": "inspected",
        },
    )


def _fail(code: str, exit_code: int) -> NoReturn:
    _write_json(
        sys.stderr,
        {"code": code, "event": "core_access_inspection_failed"},
    )
    raise SystemExit(exit_code)


def _write_json(stream, value: dict[str, object]) -> None:  # type: ignore[no-untyped-def]
    stream.write(f"{json.dumps(value, sort_keys=True, separators=(',', ':'))}\n")


if __name__ == "__main__":
    main()

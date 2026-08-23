from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import NoReturn

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track.diagnostics import (
    DailyTrackDiagnosticNotFound,
    DailyTrackDiagnostics,
)
from thesistrace.research_run.diagnostics import (
    ResearchRunDiagnosticNotFound,
    ResearchRunDiagnostics,
)

_RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        _fail("INVALID_USAGE", 2)


def main(arguments: list[str] | None = None) -> None:
    parser = _SafeArgumentParser(description="ThesisTrace private diagnostics")
    subcommands = parser.add_subparsers(
        dest="resource",
        required=True,
        parser_class=_SafeArgumentParser,
    )
    research_run = subcommands.add_parser("research-run")
    research_run.add_argument("run_id")
    daily_track = subcommands.add_parser("daily-track")
    daily_track.add_argument("track_id")
    parsed = parser.parse_args(arguments)

    resource_id = parsed.run_id if parsed.resource == "research-run" else parsed.track_id
    if _RESOURCE_ID_PATTERN.fullmatch(resource_id) is None:
        _fail("INVALID_USAGE", 2)
    database_url = os.environ.get("THESISTRACE_DATABASE_URL")
    if not database_url:
        _fail("POSTGRESQL_UNAVAILABLE", 4)

    database: PostgresDatabase | None = None
    try:
        database = PostgresDatabase(database_url)
        database.open()
        if parsed.resource == "research-run":
            snapshot = ResearchRunDiagnostics(database).inspect(resource_id)
        else:
            snapshot = DailyTrackDiagnostics(database).inspect(resource_id)
    except ResearchRunDiagnosticNotFound:
        _fail("RESEARCH_RUN_NOT_FOUND", 3)
    except DailyTrackDiagnosticNotFound:
        _fail("DAILY_TRACK_NOT_FOUND", 3)
    except Exception:
        _fail("POSTGRESQL_UNAVAILABLE", 4)
    finally:
        if database is not None:
            database.close()

    print(json.dumps(snapshot, indent=2, sort_keys=True))


def _fail(code: str, exit_code: int) -> NoReturn:
    print(code, file=sys.stderr)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

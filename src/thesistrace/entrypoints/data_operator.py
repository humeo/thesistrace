from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.adapters.tushare_replay import ReplayTushareProvider
from thesistrace.data import (
    BootstrapOutcome,
    DataOperator,
    DataOperatorError,
    DataRefreshError,
    DataRefreshService,
    RefreshOutcome,
)
from thesistrace.entrypoints.migrations import verify_core_migrations


def main(arguments: list[str] | None = None) -> None:
    logging.getLogger("psycopg.pool").disabled = True
    try:
        outcome = _run(arguments)
    except (DataOperatorError, DataRefreshError) as error:
        _failure(error.code)
    except Exception:
        _failure("OPERATOR_FAILURE")
    payload = outcome if isinstance(outcome, dict) else outcome.__dict__
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _run(arguments: list[str] | None = None) -> BootstrapOutcome | RefreshOutcome | dict[str, str]:
    parser = argparse.ArgumentParser(description="ThesisTrace private Data Operator v1")
    subcommands = parser.add_subparsers(dest="command", required=True)
    bootstrap = subcommands.add_parser("bootstrap")
    bootstrap.add_argument("--idempotency-key", required=True)
    bootstrap.add_argument("--as-of", required=True)
    bootstrap.add_argument("--replay", type=Path)
    refresh = subcommands.add_parser("refresh")
    refresh.add_argument("--idempotency-key", required=True)
    refresh.add_argument("--as-of", required=True)
    inspect = subcommands.add_parser("inspect-refresh")
    inspect.add_argument("--idempotency-key", required=True)
    work = subcommands.add_parser("work-refresh")
    work.add_argument("--replay", type=Path)
    parsed = parser.parse_args(arguments)

    transport: HttpTushareTransport | None = None
    database: PostgresDatabase | None = None
    try:
        database_url = _environment("THESISTRACE_DATABASE_URL")
        mount_root = Path(_environment("THESISTRACE_DATA_MOUNT"))
        database = PostgresDatabase(database_url)
        database.open()
        verify_core_migrations(database)
        if parsed.command == "refresh":
            return DataRefreshService(database, mount_root).submit(
                idempotency_key=parsed.idempotency_key,
                as_of=datetime.fromisoformat(parsed.as_of),
            )
        if parsed.command == "inspect-refresh":
            return DataRefreshService(database, mount_root).inspect(parsed.idempotency_key)

        replay = parsed.replay
        if replay is not None:
            provider = ReplayTushareProvider(replay)
        else:
            transport = HttpTushareTransport(
                endpoint=os.environ.get("THESISTRACE_TUSHARE_ENDPOINT", "https://api.tushare.pro")
            )
            provider = TushareAdapter(
                token=_environment("THESISTRACE_TUSHARE_TOKEN"),
                transport=transport,
            )
        source = TushareDataSource(provider=provider)
        if parsed.command == "bootstrap":
            return DataOperator(database, mount_root, source).bootstrap(
                idempotency_key=parsed.idempotency_key,
                as_of=datetime.fromisoformat(parsed.as_of),
            )
        processed = DataRefreshService(database, mount_root).process_next(source)
        return {"status": "processed" if processed else "idle"}
    finally:
        if database is not None:
            database.close()
        if transport is not None:
            transport.close()


def _failure(code: str) -> None:
    print(
        json.dumps({"status": "failed", "code": code}, sort_keys=True),
        file=sys.stderr,
    )
    raise SystemExit(2) from None


def _environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing Data Operator configuration: {name}")
    return value


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.adapters.tushare_replay import ReplayTushareProvider
from thesistrace.data import DataOperator, DataOperatorError
from thesistrace.entrypoints.migrations import verify_core_migrations


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ThesisTrace private Data Operator v1")
    subcommands = parser.add_subparsers(dest="command", required=True)
    bootstrap = subcommands.add_parser("bootstrap")
    bootstrap.add_argument("--idempotency-key", required=True)
    bootstrap.add_argument("--as-of", required=True)
    bootstrap.add_argument("--replay", type=Path)
    parsed = parser.parse_args(arguments)

    transport: HttpTushareTransport | None = None
    database: PostgresDatabase | None = None
    try:
        database_url = _environment("THESISTRACE_DATABASE_URL")
        mount_root = Path(_environment("THESISTRACE_DATA_MOUNT"))
        as_of = datetime.fromisoformat(parsed.as_of)
        if parsed.replay is not None:
            provider = ReplayTushareProvider(parsed.replay)
        else:
            transport = HttpTushareTransport(
                endpoint=os.environ.get("THESISTRACE_TUSHARE_ENDPOINT", "https://api.tushare.pro")
            )
            provider = TushareAdapter(
                token=_environment("THESISTRACE_TUSHARE_TOKEN"),
                transport=transport,
            )
        database = PostgresDatabase(database_url)
        database.open()
        verify_core_migrations(database)
        outcome = DataOperator(
            database,
            mount_root,
            TushareDataSource(provider=provider),
        ).bootstrap(idempotency_key=parsed.idempotency_key, as_of=as_of)
        print(json.dumps(outcome.__dict__, sort_keys=True, separators=(",", ":")))
    except DataOperatorError as error:
        print(
            json.dumps({"status": "failed", "code": error.code}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from error
    except (OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps({"status": "failed", "code": "OPERATOR_FAILURE"}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from error
    finally:
        if database is not None:
            database.close()
        if transport is not None:
            transport.close()


def _environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing Data Operator configuration: {name}")
    return value


if __name__ == "__main__":
    main()

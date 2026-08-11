from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import NoReturn

import boto3

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import (
    HttpTushareTransport,
    TushareAdapter,
    TushareSourceError,
)
from thesistrace.adapters.tushare_replay import ReplayTushareProvider
from thesistrace.data import (
    BootstrapOutcome,
    CollectionOutcome,
    DataCollectionError,
    DataGarbageCollector,
    DataOperator,
    DataOperatorError,
    DataRefreshError,
    DataRefreshService,
    DataSourceError,
    DevelopmentReset,
    DevelopmentResetError,
    DevelopmentResetOutcome,
    RefreshOutcome,
)
from thesistrace.entrypoints.migrations import (
    verify_core_migrations,
    verify_development_reset_migrations,
)

logger = logging.getLogger(__name__)


def main(arguments: list[str] | None = None) -> None:
    logging.getLogger("psycopg.pool").disabled = True
    try:
        outcome = _run(arguments)
    except (
        DataCollectionError,
        DataOperatorError,
        DataRefreshError,
        DevelopmentResetError,
    ) as error:
        _failure(error.code, diagnostic=_failure_diagnostic(error))
    except Exception:
        _failure("OPERATOR_FAILURE")
    payload = outcome if isinstance(outcome, dict) else outcome.__dict__
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _run(
    arguments: list[str] | None = None,
) -> (
    BootstrapOutcome | CollectionOutcome | DevelopmentResetOutcome | RefreshOutcome | dict[str, str]
):
    parser = argparse.ArgumentParser(description="ThesisTrace private Data Operator")
    subcommands = parser.add_subparsers(dest="command", required=True)
    bootstrap = subcommands.add_parser("bootstrap")
    bootstrap.add_argument("--idempotency-key", required=True)
    bootstrap.add_argument("--as-of", required=True)
    bootstrap.add_argument("--start-date", type=date.fromisoformat)
    bootstrap.add_argument("--replay", type=Path)
    refresh = subcommands.add_parser("refresh")
    refresh.add_argument("--idempotency-key", required=True)
    refresh.add_argument("--as-of", required=True)
    inspect = subcommands.add_parser("inspect-refresh")
    inspect.add_argument("--idempotency-key", required=True)
    work = subcommands.add_parser("work-refresh")
    work.add_argument("--replay", type=Path)
    collect = subcommands.add_parser("collect")
    collect.add_argument("--idempotency-key", required=True)
    reset = subcommands.add_parser("development-reset")
    reset.add_argument("--idempotency-key", required=True)
    reset.add_argument("--environment", required=True)
    reset.add_argument("--confirm", required=True)
    parsed = parser.parse_args(arguments)

    if parsed.command == "development-reset":
        configured_environment = _environment("THESISTRACE_DEPLOYMENT_ENV")
        if parsed.environment != configured_environment:
            raise DevelopmentResetError("RESET_ENVIRONMENT_MISMATCH")
        if configured_environment != "development":
            raise DevelopmentResetError("RESET_ENVIRONMENT_REFUSED")

    transport: HttpTushareTransport | None = None
    database: PostgresDatabase | None = None
    try:
        database_url = _environment("THESISTRACE_DATABASE_URL")
        mount_root = Path(_environment("THESISTRACE_DATA_MOUNT"))
        database = PostgresDatabase(database_url)
        database.open()
        if parsed.command == "development-reset":
            verify_development_reset_migrations(database)
        else:
            verify_core_migrations(database)
        if parsed.command == "refresh":
            return DataRefreshService(database, mount_root).submit(
                idempotency_key=parsed.idempotency_key,
                as_of=datetime.fromisoformat(parsed.as_of),
            )
        if parsed.command == "inspect-refresh":
            return DataRefreshService(database, mount_root).inspect(parsed.idempotency_key)
        if parsed.command == "collect":
            return DataGarbageCollector(database, mount_root).collect(
                idempotency_key=parsed.idempotency_key
            )
        if parsed.command == "development-reset":
            s3 = boto3.client(
                "s3",
                endpoint_url=_environment("THESISTRACE_S3_ENDPOINT_URL"),
                aws_access_key_id=_environment("THESISTRACE_S3_ACCESS_KEY_ID"),
                aws_secret_access_key=_environment("THESISTRACE_S3_SECRET_ACCESS_KEY"),
                region_name=os.environ.get("THESISTRACE_S3_REGION", "us-east-1"),
            )
            try:
                return DevelopmentReset(
                    database,
                    s3,
                    bucket=_environment("THESISTRACE_S3_BUCKET"),
                    mount_root=mount_root,
                ).execute(
                    idempotency_key=parsed.idempotency_key,
                    environment_name=parsed.environment,
                    confirmation=parsed.confirm,
                )
            finally:
                s3.close()

        replay = parsed.replay
        live_provider: TushareAdapter | None = None
        if replay is not None:
            provider = ReplayTushareProvider(replay)
        else:
            transport = HttpTushareTransport(
                endpoint=os.environ.get("THESISTRACE_TUSHARE_ENDPOINT", "https://api.tushare.pro")
            )
            live_provider = TushareAdapter(
                token=_environment("THESISTRACE_TUSHARE_TOKEN"),
                transport=transport,
                progress=_progress,
                bootstrap_checkpoint=(
                    mount_root / ".operator" / "tushare-bootstrap-foundation.json"
                    if parsed.command == "bootstrap"
                    else None
                ),
            )
            provider = live_provider
        source = TushareDataSource(provider=provider)
        if parsed.command == "bootstrap":
            outcome = DataOperator(
                database,
                mount_root,
                source,
                progress=lambda event: _progress({"event": "bootstrap_progress", **event}),
            ).bootstrap(
                idempotency_key=parsed.idempotency_key,
                as_of=datetime.fromisoformat(parsed.as_of),
                start_date=parsed.start_date,
            )
            if live_provider is not None:
                try:
                    live_provider.clear_bootstrap_checkpoint()
                except TushareSourceError as error:
                    logger.warning(
                        "Published bootstrap checkpoint cleanup failed",
                        extra={"reason_code": error.reason_code},
                    )
                else:
                    _progress(
                        {
                            "event": "collection_phase",
                            "phase": "bootstrap_checkpoint",
                            "status": "cleared",
                        }
                    )
            return outcome
        processed = DataRefreshService(database, mount_root).process_next(source)
        return {"status": "processed" if processed else "idle"}
    finally:
        if database is not None:
            database.close()
        if transport is not None:
            transport.close()


def _failure(code: str, *, diagnostic: dict[str, object] | None = None) -> NoReturn:
    payload: dict[str, object] = {"status": "failed", "code": code}
    if diagnostic is not None:
        payload["error"] = diagnostic
    print(
        json.dumps(payload, sort_keys=True),
        file=sys.stderr,
    )
    raise SystemExit(2) from None


def _progress(event: dict[str, object]) -> None:
    print(
        json.dumps(event, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


def _failure_diagnostic(error: BaseException) -> dict[str, object] | None:
    current: BaseException | None = error
    data_error: DataSourceError | None = None
    source_error: TushareSourceError | None = None
    while current is not None:
        if isinstance(current, DataSourceError):
            data_error = current
        if isinstance(current, TushareSourceError):
            source_error = current
        current = current.__cause__
    if source_error is None:
        return None
    diagnostic = source_error.diagnostic()
    if data_error is not None:
        diagnostic["category"] = data_error.category
    return diagnostic


def _environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing Data Operator configuration: {name}")
    return value


if __name__ == "__main__":
    main()

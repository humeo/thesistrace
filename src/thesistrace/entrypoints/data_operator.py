from __future__ import annotations

import argparse
import json
import logging
import os
import stat
import sys
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from threading import Event
from typing import NoReturn

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.cninfo_financial_announcements import (
    AkshareCninfoFinancialAnnouncementSource,
)
from thesistrace.adapters.tushare_benchmark import TushareBenchmarkSource
from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_financial import TushareFinancialSource
from thesistrace.adapters.tushare_industry import (
    IndustrySourceError,
    TushareIndustrySource,
)
from thesistrace.adapters.tushare_provider import (
    HttpTushareTransport,
    TushareAdapter,
    TushareSourceError,
)
from thesistrace.adapters.tushare_replay import (
    ReplayTushareProvider,
    ReplayTushareRefreshBundle,
)
from thesistrace.benchmark import validate_independent_benchmark_mount
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
    FinancialCandidateError,
    FinancialCapabilityReport,
    FinancialCollectionContract,
    FinancialCollectionError,
    FinancialCollectionOutcome,
    FinancialCollectionService,
    FinancialDailyRefreshError,
    FinancialDateShard,
    FinancialRefreshError,
    FinancialRefreshService,
    IndustryRefreshError,
    IndustryRefreshService,
    RefreshOutcome,
    probe_financial_capability,
    validate_financial_refresh_request,
    validate_market_refresh_request,
)
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.operational_events import (
    emit_operational_event_data,
    non_blocking_operational_event_sink,
)

_emit_data_operator_event = non_blocking_operational_event_sink(
    emit_operational_event_data,
    component="data_operator",
)


class _UnavailableIndustrySource:
    def collect(self, *, allowed_codes: set[str]) -> NoReturn:
        del allowed_codes
        raise IndustrySourceError("INDUSTRY_SOURCE_UNAVAILABLE")


def main(arguments: list[str] | None = None) -> None:
    logging.getLogger("psycopg.pool").disabled = True
    command = _selected_command(arguments)
    try:
        outcome = _run(arguments)
    except (
        DataCollectionError,
        DataOperatorError,
        DataRefreshError,
    ) as error:
        _failure(
            error.code,
            diagnostic=_failure_diagnostic(error),
            command=command,
        )
    except FinancialCollectionError as error:
        _failure(error.code, diagnostic=error.diagnostic(), command=command)
    except (
        FinancialCandidateError,
        FinancialDailyRefreshError,
        FinancialRefreshError,
    ) as error:
        _failure(str(error), command=command)
    except (IndustryRefreshError, IndustrySourceError) as error:
        _failure(str(error), command=command)
    except Exception:
        _failure("OPERATOR_FAILURE", command=command)
    payload = outcome if isinstance(outcome, dict) else outcome.__dict__
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _run(
    arguments: list[str] | None = None,
) -> (
    BootstrapOutcome
    | CollectionOutcome
    | FinancialCollectionOutcome
    | RefreshOutcome
    | dict[str, object]
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
    worker = subcommands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--replay", action="append", type=Path)
    collect = subcommands.add_parser("collect")
    collect.add_argument("--idempotency-key", required=True)
    financial_probe = subcommands.add_parser("probe-financial")
    financial_probe.add_argument("--reference-instrument", required=True)
    financial_probe.add_argument(
        "--comparison-shard",
        action="append",
        required=True,
        metavar="NAME:START:END",
    )
    financial_collect = subcommands.add_parser("collect-financial")
    financial_collect.add_argument("--idempotency-key", required=True)
    financial_collect.add_argument("--generation-manifest-sha256", required=True)
    financial_collect.add_argument("--capability-report", type=Path, required=True)
    financial_collect.add_argument("--replay", type=Path)
    financial_bootstrap = subcommands.add_parser("bootstrap-financial")
    financial_bootstrap.add_argument("--idempotency-key", required=True)
    financial_bootstrap.add_argument("--generation-manifest-sha256", required=True)
    financial_bootstrap.add_argument("--capability-report", type=Path, required=True)
    financial_bootstrap.add_argument("--observation-through-session", required=True)
    financial_bootstrap.add_argument("--replay", type=Path)
    financial_refresh = subcommands.add_parser("refresh-financial")
    financial_refresh.add_argument("--idempotency-key", required=True)
    financial_refresh.add_argument("--observation-through-session", required=True)
    financial_inspect = subcommands.add_parser("inspect-financial-refresh")
    financial_inspect.add_argument("--idempotency-key", required=True)
    industry_refresh = subcommands.add_parser("refresh-industry")
    industry_refresh.add_argument("--idempotency-key", required=True)
    industry_refresh.add_argument("--observation-through-session", required=True)
    industry_refresh.add_argument("--replay", type=Path)
    industry_inspect = subcommands.add_parser("inspect-industry-refresh")
    industry_inspect.add_argument("--idempotency-key", required=True)
    parsed = parser.parse_args(arguments)

    if parsed.command == "worker" and parsed.once and parsed.replay is None:
        raise DataRefreshError("WORKER_REPLAY_REQUIRED")

    market_request: tuple[str, datetime] | None = None
    financial_request: tuple[str, str] | None = None
    if parsed.command == "refresh":
        market_request = validate_market_refresh_request(
            idempotency_key=parsed.idempotency_key,
            as_of=parsed.as_of,
        )
    elif parsed.command == "refresh-financial":
        financial_request = validate_financial_refresh_request(
            idempotency_key=parsed.idempotency_key,
            observation_through_session=parsed.observation_through_session,
        )

    transport: HttpTushareTransport | None = None
    database: PostgresDatabase | None = None
    try:
        if parsed.command == "probe-financial":
            rate_limit_events: dict[str, list[float]] = {}
            transport, live_provider = _create_live_tushare_provider(
                rate_limit_events=rate_limit_events,
                bootstrap_checkpoint=None,
                operational_progress=_progress,
            )
            report = probe_financial_capability(
                TushareFinancialSource(live_provider),
                reference_instrument=parsed.reference_instrument,
                comparison_shards=tuple(
                    _parse_financial_shard(value) for value in parsed.comparison_shard
                ),
                observed_rate_limit_events=rate_limit_events,
            )
            return report.descriptor()
        database_url = _environment("THESISTRACE_DATABASE_URL")
        mount_root = Path(_environment("THESISTRACE_DATA_MOUNT"))
        try:
            benchmark_mount = validate_independent_benchmark_mount(
                mount_root,
                _environment("THESISTRACE_BENCHMARK_MOUNT"),
            )
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        database = PostgresDatabase(database_url)
        database.open()
        verify_core_schema(database)
        if parsed.command == "refresh":
            assert market_request is not None
            idempotency_key, as_of = market_request
            return DataRefreshService(
                database,
                mount_root,
                benchmark_mount_root=benchmark_mount,
            ).submit(
                idempotency_key=idempotency_key,
                as_of=as_of,
            )
        if parsed.command == "inspect-refresh":
            return DataRefreshService(
                database,
                mount_root,
                benchmark_mount_root=benchmark_mount,
            ).inspect(parsed.idempotency_key)
        if parsed.command == "refresh-financial":
            assert financial_request is not None
            idempotency_key, observation_through_session = financial_request
            return DataRefreshService(
                database,
                mount_root,
                benchmark_mount_root=benchmark_mount,
            ).submit_financial(
                idempotency_key=idempotency_key,
                observation_through_session=observation_through_session,
            )
        if parsed.command == "inspect-industry-refresh":
            return IndustryRefreshService(
                database,
                mount_root,
                _UnavailableIndustrySource(),
            ).inspect(parsed.idempotency_key)
        if parsed.command == "inspect-financial-refresh":
            return DataRefreshService(
                database,
                mount_root,
                benchmark_mount_root=benchmark_mount,
            ).inspect(parsed.idempotency_key)
        if parsed.command == "collect":
            return DataGarbageCollector(database, mount_root).collect(
                idempotency_key=parsed.idempotency_key
            )
        replay = getattr(parsed, "replay", None)
        rate_limit_events: dict[str, list[float]] = {}
        live_provider: TushareAdapter | None = None
        financial_source_window_selector: Callable[[str, str], None] | None = None
        if replay is not None:
            provider = (
                ReplayTushareRefreshBundle(replay)
                if parsed.command == "worker"
                else ReplayTushareProvider(replay)
            )
            financial_source = provider
            financial_announcement_source = provider
            if isinstance(provider, ReplayTushareRefreshBundle):
                financial_source_window_selector = provider.select_financial_window
        else:
            transport, live_provider = _create_live_tushare_provider(
                rate_limit_events=rate_limit_events,
                bootstrap_checkpoint=(
                    mount_root / ".operator" / "tushare-bootstrap-checkpoint.json"
                    if parsed.command == "bootstrap"
                    else None
                ),
                operational_progress=(None if parsed.command == "worker" else _progress),
            )
            provider = live_provider
            financial_source = TushareFinancialSource(live_provider)
            financial_announcement_source = (
                AkshareCninfoFinancialAnnouncementSource()
                if parsed.command == "worker"
                else None
            )
        if parsed.command in {"collect-financial", "bootstrap-financial"}:
            if live_provider is None and replay is None:
                raise FinancialCollectionError("LIVE_FINANCIAL_COLLECTION_REQUIRED")
            report = _load_financial_capability(parsed.capability_report)
            contract = FinancialCollectionContract.from_capability(report)
            if parsed.command == "collect-financial":
                return FinancialCollectionService(
                    database,
                    mount_root,
                    financial_source,
                    progress=_progress,
                ).collect(
                    idempotency_key=parsed.idempotency_key,
                    generation_manifest_sha256=parsed.generation_manifest_sha256,
                    contract=contract,
                )
            outcome = FinancialRefreshService(
                database,
                mount_root,
                financial_source,
                lifecycle_event=_progress,
            ).publish(
                idempotency_key=parsed.idempotency_key,
                generation_manifest_sha256=parsed.generation_manifest_sha256,
                contract=contract,
                prior_candidate_manifest_sha256=None,
                observation_through_session=parsed.observation_through_session,
            )
            return {
                "idempotency_key": outcome.idempotency_key,
                "status": "succeeded",
                "candidate_manifest_sha256": outcome.candidate.manifest_sha256,
                "generation_manifest_sha256": outcome.generation_manifest_sha256,
                "expected_shard_count": outcome.expected_shard_count,
                "completed_shard_count": outcome.completed_shard_count,
                "resumed_shard_count": outcome.resumed_shard_count,
            }
        if parsed.command == "refresh-industry":
            outcome = IndustryRefreshService(
                database,
                mount_root,
                TushareIndustrySource(provider),
                progress=_progress,
            ).publish(
                idempotency_key=parsed.idempotency_key,
                observation_through_session=parsed.observation_through_session,
            )
            return {
                "idempotency_key": outcome.idempotency_key,
                "status": "succeeded",
                "candidate_manifest_sha256": outcome.candidate.manifest_sha256,
                "generation_manifest_sha256": outcome.generation_manifest_sha256,
                "source_lineage_sha256": outcome.source_lineage_sha256,
            }
        source = TushareDataSource(
            provider=provider,
            progress=_progress if parsed.command == "bootstrap" else None,
        )
        if parsed.command == "bootstrap":
            outcome = DataOperator(
                database,
                mount_root,
                source,
                benchmark_mount_root=benchmark_mount,
                benchmark_source=TushareBenchmarkSource(provider),
                progress=lambda event: _progress({"event": "bootstrap_progress", **event}),
            ).bootstrap(
                idempotency_key=parsed.idempotency_key,
                as_of=datetime.fromisoformat(parsed.as_of),
                start_date=parsed.start_date,
            )
            if live_provider is not None:
                try:
                    live_provider.clear_bootstrap_checkpoint()
                except TushareSourceError:
                    _progress(
                        {
                            "event": "bootstrap_checkpoint_cleanup_deferred",
                            "level": "WARNING",
                            "failure_code": "BOOTSTRAP_CHECKPOINT_CLEANUP_FAILED",
                        }
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
        refresh_service = DataRefreshService(
            database,
            mount_root,
            benchmark_mount_root=benchmark_mount,
            lifecycle_event=_progress,
        )
        benchmark_source = TushareBenchmarkSource(provider)
        worker_wait = Event()
        while True:
            try:
                processed = refresh_service.process_next(
                    source,
                    benchmark_source=benchmark_source,
                    financial_announcement_source=financial_announcement_source,
                    financial_source=financial_source,
                    financial_source_window_selector=financial_source_window_selector,
                )
            except DataRefreshError:
                if parsed.once:
                    raise
                worker_wait.wait(5)
                continue
            if parsed.once:
                return {"status": "processed" if processed else "idle"}
            if not processed:
                worker_wait.wait(5)
    finally:
        if database is not None:
            database.close()
        if transport is not None:
            transport.close()


def _failure(
    code: str,
    *,
    diagnostic: Mapping[str, object] | None = None,
    command: str | None = None,
) -> NoReturn:
    payload: dict[str, object] = {"status": "failed", "code": code}
    refresh_command = command == "worker"
    if diagnostic is not None and not refresh_command:
        payload["error"] = diagnostic
    print(
        json.dumps(payload, sort_keys=True),
        file=sys.stdout if refresh_command else sys.stderr,
    )
    raise SystemExit(2) from None


def _selected_command(arguments: list[str] | None) -> str | None:
    selected = sys.argv[1:] if arguments is None else arguments
    return selected[0] if selected else None


def _progress(event: dict[str, object]) -> None:
    _emit_data_operator_event(event)


def _create_live_tushare_provider(
    *,
    rate_limit_events: dict[str, list[float]],
    bootstrap_checkpoint: Path | None,
    operational_progress: Callable[[dict[str, object]], None] | None,
) -> tuple[HttpTushareTransport, TushareAdapter]:
    transport = HttpTushareTransport(
        endpoint=os.environ.get("THESISTRACE_TUSHARE_ENDPOINT", "https://api.tushare.pro")
    )

    def progress(event: dict[str, object]) -> None:
        if event.get("event") == "rate_limited":
            api_name = str(event.get("api_name", ""))
            retry_seconds = event.get("retry_in_seconds")
            if isinstance(retry_seconds, (int, float)):
                rate_limit_events.setdefault(api_name, []).append(float(retry_seconds))
        if operational_progress is not None:
            operational_progress(event)

    try:
        provider = TushareAdapter(
            token=_environment("THESISTRACE_TUSHARE_TOKEN"),
            transport=transport,
            progress=progress,
            bootstrap_checkpoint=bootstrap_checkpoint,
        )
    except Exception:
        transport.close()
        raise
    return transport, provider


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


def _parse_financial_shard(value: str) -> FinancialDateShard:
    parts = value.split(":")
    if len(parts) != 3:
        raise FinancialCollectionError("INVALID_FINANCIAL_DATE_SHARD")
    try:
        return FinancialDateShard(parts[0], parts[1], parts[2])
    except ValueError as error:
        raise FinancialCollectionError("INVALID_FINANCIAL_DATE_SHARD") from error


def _load_financial_capability(path: Path) -> FinancialCapabilityReport:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1024 * 1024:
                raise ValueError
            content = bytearray()
            while chunk := os.read(descriptor, min(64 * 1024, 1024 * 1024 + 1 - len(content))):
                content.extend(chunk)
                if len(content) > 1024 * 1024:
                    raise ValueError
            if len(content) != metadata.st_size:
                raise ValueError
        finally:
            os.close(descriptor)
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError
        return FinancialCapabilityReport.from_descriptor(value)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise FinancialCollectionError("INVALID_FINANCIAL_CAPABILITY_REPORT") from error


if __name__ == "__main__":
    main()

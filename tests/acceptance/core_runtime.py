import atexit
import json
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from uuid import UUID

from fastapi import FastAPI, Request
from pydantic import ValidationError

from thesistrace._postgres import PostgresDatabase
from thesistrace.benchmark import (
    INTERNAL_STRATEGY_METRIC_PATH,
    BenchmarkSnapshotStore,
    InternalAnnualizedExcessRequest,
    StrategyComparisonError,
    StrategyComparisonFacts,
    StrategyComparisonService,
)
from thesistrace.entrypoints.http import create_app as create_core_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core
from thesistrace.researcher import ResearcherIdentity, ResearcherService

TEST_PUBLIC_ORIGIN = "https://core.test"
TEST_RESEARCHER = ResearcherIdentity(
    researcher_id=UUID("018f6f7e-8342-7c9a-a4df-9a86147d2e01"),
    email="researcher@example.test",
    display_label="researcher",
)


class _TestSessionVerifier:
    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        return TEST_RESEARCHER

_INTERNAL_API_LOCK = Lock()
_INTERNAL_API_SERVERS: dict[Path, ThreadingHTTPServer] = {}


class _InternalStrategyMetricServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, benchmark_mount: Path) -> None:
        super().__init__(("127.0.0.1", 0), _InternalStrategyMetricHandler)
        self.comparison = StrategyComparisonService(
            BenchmarkSnapshotStore(benchmark_mount)
        )


class _InternalStrategyMetricHandler(BaseHTTPRequestHandler):
    server: _InternalStrategyMetricServer

    def do_POST(self) -> None:  # noqa: N802
        if self.path != INTERNAL_STRATEGY_METRIC_PATH:
            self._respond(HTTPStatus.NOT_FOUND, {"detail": "Not Found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
            if content_length < 1 or content_length > 4096:
                raise ValueError
            value = json.loads(self.rfile.read(content_length))
            request = InternalAnnualizedExcessRequest.model_validate(value)
            metric = self.server.comparison.annualized_excess_return(
                StrategyComparisonFacts(
                    entry_session=request.entry_session,
                    terminal_session=request.terminal_session,
                    session_interval_count=request.session_interval_count,
                    initial_cash_cny=request.initial_cash_cny,
                    terminal_net_nav=request.terminal_net_nav,
                )
            )
        except StrategyComparisonError as error:
            self._respond(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": str(error)})
            return
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError):
            self._respond(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": "invalid facts"})
            return
        self._respond(HTTPStatus.OK, {"annualized_excess_return": metric})

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def _respond(self, status: HTTPStatus, value: dict[str, object]) -> None:
        content = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def internal_api_origin(settings: CoreSettings) -> str:
    benchmark_mount = Path(settings.benchmark_mount).resolve()
    with _INTERNAL_API_LOCK:
        server = _INTERNAL_API_SERVERS.get(benchmark_mount)
        if server is None:
            server = _InternalStrategyMetricServer(benchmark_mount)
            _INTERNAL_API_SERVERS[benchmark_mount] = server
            Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


def stop_internal_api_servers() -> None:
    with _INTERNAL_API_LOCK:
        servers = tuple(_INTERNAL_API_SERVERS.values())
        _INTERNAL_API_SERVERS.clear()
    for server in servers:
        server.shutdown()
        server.server_close()


atexit.register(stop_internal_api_servers)


def isolated_core_settings(data_mount: Path) -> CoreSettings:
    return replace(
        CoreSettings.from_environment(),
        data_mount=data_mount,
        benchmark_mount=data_mount.parent / f"{data_mount.name}-benchmark-data",
        batch_attempt_control_directory=(
            data_mount.parent
            / f"{data_mount.name}-batch-attempt-control"
            / ".batch-attempts"
        ),
    )


def create_initialized_test_app(settings: CoreSettings | None = None) -> FastAPI:
    selected_settings = settings or CoreSettings.from_environment()
    initialize_core(selected_settings.database_url)
    database = PostgresDatabase(selected_settings.database_url)
    database.open()
    try:
        ResearcherService(database).bootstrap(TEST_RESEARCHER)
    finally:
        database.close()
    app = create_core_app(
        selected_settings,
        auth_verifier=_TestSessionVerifier(),
        public_origin=TEST_PUBLIC_ORIGIN,
    )

    @app.middleware("http")
    async def add_explicit_test_origin(request: Request, call_next):  # type: ignore[no-untyped-def]
        if (
            request.url.path.startswith("/api/")
            and request.method in {"POST", "PATCH", "DELETE"}
            and "origin" not in request.headers
        ):
            request.scope["headers"] = [
                *request.scope["headers"],
                (b"origin", TEST_PUBLIC_ORIGIN.encode("ascii")),
            ]
        return await call_next(request)

    return app


def drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        database.close()

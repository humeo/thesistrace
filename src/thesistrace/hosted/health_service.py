import asyncio
import concurrent.futures
import hashlib
import http.client
import math
import os
import socket
import ssl
import threading
import urllib.request
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from urllib.parse import urlparse

import psycopg
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from psycopg.rows import dict_row
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client

from thesistrace.fixture import build_fixture
from thesistrace.hosted.compute_dispatch import (
    COMPUTE_WORKFLOW_TASK_QUEUE,
    P1_ACTIVITY_TASK_QUEUE,
    P3_ACTIVITY_TASK_QUEUE,
)
from thesistrace.hosted.dataset_publication_workflow import (
    DATASET_PUBLICATION_TASK_QUEUE,
)
from thesistrace.hosted.observability import configure_observability, instrument_http
from thesistrace.numeric import NUMERIC_CONTRACT_ID, binary64_checksum
from thesistrace.objects import canonical_json_bytes
from thesistrace.research_runs import calculate_research

SEMANTIC_REGRESSION_SHA256 = "0a05e478ba56c8cabd38831d01f59c5200c8b93ae8cc2339ccab33f356cd21af"
CORE_SYSTEM_CHECKS = (
    "public_origin",
    "api",
    "identity",
    "database",
    "object_store",
    "temporal",
)


class RoutedHTTPSConnection(http.client.HTTPSConnection):
    """Connect privately while routing TLS as the public Origin host."""

    def __init__(
        self,
        connect_host: str,
        connect_port: int,
        public_host: str,
        **kwargs: object,
    ) -> None:
        super().__init__(public_host, port=connect_port, **kwargs)
        self.connect_host = connect_host

    def connect(self) -> None:
        public_host = self.host
        self.host = self.connect_host
        try:
            http.client.HTTPConnection.connect(self)
        finally:
            self.host = public_host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=public_host)


class HealthSnapshotStore(Protocol):
    def ready(self) -> bool: ...

    def snapshot(self) -> dict[str, object]: ...


class PostgresHealthSnapshotStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def ready(self) -> bool:
        try:
            with psycopg.connect(self.database_url, connect_timeout=2) as connection:
                return connection.execute("SELECT 1").fetchone() == (1,)
        except psycopg.Error:
            return False

    def snapshot(self) -> dict[str, object]:
        with psycopg.connect(
            self.database_url,
            connect_timeout=3,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                "SELECT thesistrace_control.operator_health_snapshot() AS snapshot"
            ).fetchone()
        if row is None or not isinstance(row["snapshot"], dict):
            raise RuntimeError("operator health snapshot is unavailable")
        return dict(row["snapshot"])


@dataclass
class SemanticRegressionState:
    _checks: dict[str, bool] = field(default_factory=dict)
    _observed_at: datetime | None = None
    _running: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> bool:
        with self._lock:
            if self._running or self._observed_at is not None:
                return False
            self._running = True
            return True

    def complete(
        self,
        checks: Mapping[str, bool],
        *,
        observed_at: datetime | None = None,
    ) -> None:
        with self._lock:
            self._checks = {str(name): bool(value) for name, value in checks.items()}
            self._observed_at = observed_at or datetime.now(UTC)
            self._running = False

    def fail(self) -> None:
        self.complete(
            {
                "deterministic_regression": False,
                "numeric_invariants": False,
                "accounting_invariants": False,
                "checksums": False,
                "missingness": False,
            }
        )

    def snapshot(self) -> tuple[dict[str, bool], datetime | None, bool]:
        with self._lock:
            return dict(self._checks), self._observed_at, self._running


@dataclass
class TemporalQueueState:
    _snapshot: dict[str, int | bool] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def complete(self, snapshot: Mapping[str, int | bool]) -> None:
        with self._lock:
            self._snapshot = {str(key): value for key, value in snapshot.items()}

    def fail(self) -> None:
        self.complete({"pollers_ready": False})

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return dict(self._snapshot)


def run_semantic_regression() -> dict[str, bool]:
    _source, canonical = build_fixture()
    definition = {
        "universe": "top300",
        "alpha": {"expression": "pct_change($close_adj, 20)"},
        "neutralization": "industry",
        "strategy": {
            "holdings_count": 30,
            "rebalance_interval": 5,
            "initial_cash_cny": "10000000",
            "execution": "next_open_full_fill",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
        "risk_free_rate": "0",
    }
    artifacts = calculate_research(canonical, definition)
    alpha = artifacts["alpha_matrix"]
    factor = artifacts["factor_evaluation"]
    strategy = artifacts["strategy_backtest"]
    horizons = factor["horizons"]
    summary = {
        "alpha_checksum": alpha["checksum"],
        "strategy_checksum": strategy["checksum"],
        "factor_1_checksum": horizons["1"]["checksum"],
        "factor_5_checksum": horizons["5"]["checksum"],
        "factor_20_checksum": horizons["20"]["checksum"],
        "last_net_nav": strategy["daily"][-1]["net_nav"],
        "daily_count": len(strategy["daily"]),
        "terminal_positions": len(strategy["positions"]),
    }
    regression_digest = hashlib.sha256(canonical_json_bytes(summary)).hexdigest()
    checksums = [
        str(summary["alpha_checksum"]),
        str(summary["strategy_checksum"]),
        str(summary["factor_1_checksum"]),
        str(summary["factor_5_checksum"]),
        str(summary["factor_20_checksum"]),
    ]
    daily = strategy["daily"]
    diagnostics = artifacts["diagnostics"]
    return {
        "deterministic_regression": regression_digest == SEMANTIC_REGRESSION_SHA256,
        "numeric_invariants": (
            NUMERIC_CONTRACT_ID == "thesistrace-numeric-v1"
            and binary64_checksum([-0.0, 1.5])
            == "d209a60368fea73680c325ae1e9a84ee2d544acf4c3bfec789d4f1b50c5b87c9"
            and all(math.isfinite(float(day["net_return"])) for day in daily)
        ),
        "accounting_invariants": (
            len(daily) == 504
            and all(Decimal(str(day["net_cash"])) >= 0 for day in daily)
            and all(int(day["holdings_count"]) <= 30 for day in daily)
            and all(Decimal(str(day["net_nav"])) >= Decimal(str(day["net_cash"])) for day in daily)
        ),
        "checksums": all(len(value) == 64 and value == value.lower() for value in checksums),
        "missingness": (
            isinstance(diagnostics.get("alpha_coverage"), list)
            and len(diagnostics["alpha_coverage"]) == len(canonical["research_calendar"])
            and all(
                isinstance(day.get("coverage_loss"), dict) for day in diagnostics["alpha_coverage"]
            )
        ),
    }


def create_health_app(
    store: HealthSnapshotStore,
    *,
    dependency_status: Callable[[], dict[str, object]],
    semantic_state: SemanticRegressionState | None = None,
    temporal_queue_state: TemporalQueueState | None = None,
    fault_plane: str | None = None,
    run_regression_on_startup: bool = True,
) -> FastAPI:
    if fault_plane not in {None, "system", "data", "quantitative"}:
        raise ValueError("health fault plane must be system, data, or quantitative")
    state = semantic_state or SemanticRegressionState()
    queue_state = temporal_queue_state

    async def execute_regression() -> None:
        if not state.start():
            return
        try:
            state.complete(await asyncio.to_thread(run_semantic_regression))
        except Exception:
            state.fail()

    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI):
        if run_regression_on_startup:
            lifespan_app.state.semantic_regression_task = asyncio.create_task(execute_regression())
        if queue_state is not None:
            lifespan_app.state.temporal_queue_task = asyncio.create_task(
                monitor_temporal_queues(queue_state)
            )
        yield

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    instrument_http(app)

    def views() -> dict[str, dict[str, object]]:
        try:
            snapshot = store.snapshot()
        except Exception:
            snapshot = {"system": {}, "data": {}, "quantitative": {}}
        dependencies = dependency_status()
        if queue_state is not None:
            dependencies["temporal_queues"] = queue_state.snapshot()
        semantic_checks, observed_at, running = state.snapshot()
        if fault_plane == "system":
            dependencies["api"] = False
        elif fault_plane == "data":
            dependencies["tushare"] = False
        elif fault_plane == "quantitative":
            semantic_checks["deterministic_regression"] = False
        system_values = mapping(snapshot.get("system"))
        data_values = mapping(snapshot.get("data"))
        quantitative_values = mapping(snapshot.get("quantitative"))

        system_checks = {name: bool(dependencies.get(name, False)) for name in CORE_SYSTEM_CHECKS}
        system_checks["telemetry"] = bool(dependencies.get("telemetry", False))
        system_checks["trace_export"] = bool(dependencies.get("trace_export", False))
        queue_snapshot = dependencies.get("temporal_queues")
        system_checks["task_queues"] = bool(
            isinstance(queue_snapshot, Mapping) and queue_snapshot.get("pollers_ready", False)
        )
        system_checks["outbox_lag"] = (
            float(system_values.get("outbox_oldest_age_seconds", 0.0)) <= 60.0
        )
        storage_pressure = mapping(dependencies.get("storage_pressure"))
        system_checks["disk_pressure"] = bool(storage_pressure.get("below_warning", False))
        worker_slots_ready = int(dependencies.get("worker_slots_ready", 0))
        system_checks["workflow_capacity"] = worker_slots_ready == 4
        data_checks = {
            "tushare": bool(dependencies.get("tushare", False)),
            "release_freshness": bool(data_values.get("release_present", False))
            and bool(data_values.get("release_session_current", False))
            and float(data_values.get("release_age_seconds", -1.0))
            <= float(
                os.environ.get(
                    "THESISTRACE_RELEASE_FRESHNESS_MAX_SECONDS",
                    "345600",
                )
            ),
            "validation": bool(data_values.get("publication_validation_succeeded", False)),
            "coverage": bool(data_values.get("coverage_valid", False)),
            "schema": bool(data_values.get("schema_valid", False)),
            "lineage": bool(data_values.get("lineage_valid", False)),
            "previous_release_preserved": bool(
                data_values.get("previous_release_preserved", False)
            ),
            "failed_publication": int(data_values.get("failed_publications", 0)) == 0,
        }
        quantitative_checks = dict(semantic_checks)
        quantitative_checks["equivalence"] = (
            quantitative_values.get("equivalence_status") == "succeeded"
        )
        return {
            "system": health_view(
                system_checks,
                {
                    "outbox_pending": system_values.get("outbox_pending", 0),
                    "outbox_oldest_age_seconds": system_values.get(
                        "outbox_oldest_age_seconds", 0.0
                    ),
                    "workflow_running": system_values.get("workflow_running", 0),
                    "workflow_capacity": worker_slots_ready,
                    "outbox_user_pending": system_values.get("task_queue_user_pending", 0),
                    "outbox_data_pending": system_values.get("task_queue_data_pending", 0),
                    "outbox_tracking_pending": system_values.get("task_queue_tracking_pending", 0),
                    "storage_used_ratio": storage_pressure.get("used_ratio", -1.0),
                    **temporal_queue_measurements(dependencies),
                },
            ),
            "data": health_view(
                data_checks,
                {
                    "release_age_seconds": data_values.get("release_age_seconds", -1.0),
                    "failed_publications": data_values.get("failed_publications", 0),
                },
            ),
            "quantitative": health_view(
                quantitative_checks,
                {
                    "regression_running": 1 if running else 0,
                    "regression_age_seconds": (
                        int(max(0.0, (datetime.now(UTC) - observed_at).total_seconds()))
                        if observed_at is not None
                        else -1.0
                    ),
                    "equivalence_age_seconds": quantitative_values.get(
                        "equivalence_age_seconds", -1.0
                    ),
                },
            ),
        }

    @app.get("/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/ready")
    def ready():
        if store.ready():
            return {"status": "ready"}
        return JSONResponse({"status": "not_ready"}, status_code=503)

    @app.get("/health/system")
    def system_health() -> dict[str, object]:
        return views()["system"]

    @app.get("/health/data")
    def data_health() -> dict[str, object]:
        return views()["data"]

    @app.get("/health/quantitative")
    def quantitative_health() -> dict[str, object]:
        return views()["quantitative"]

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return render_prometheus(views())

    return app


def mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def health_view(
    checks: Mapping[str, bool],
    measurements: Mapping[str, object],
) -> dict[str, object]:
    normalized_checks = {str(key): bool(value) for key, value in checks.items()}
    return {
        "status": (
            "available" if normalized_checks and all(normalized_checks.values()) else "degraded"
        ),
        "checks": normalized_checks,
        "measurements": {
            str(key): numeric_measurement(value) for key, value in measurements.items()
        },
    }


def numeric_measurement(value: object) -> int | float:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float) and math.isfinite(float(value)):
        return value
    return -1.0


def render_prometheus(views: Mapping[str, Mapping[str, object]]) -> str:
    lines = [
        "# HELP thesistrace_health_check Bounded health check state.",
        "# TYPE thesistrace_health_check gauge",
    ]
    measurements: list[str] = []
    for view_name in ("system", "data", "quantitative"):
        view = mapping(views.get(view_name))
        checks = mapping(view.get("checks"))
        for check_name in sorted(checks):
            lines.append(
                "thesistrace_health_check"
                f'{{view="{view_name}",check="{check_name}"}} '
                f"{1 if checks[check_name] else 0}"
            )
        for measurement_name, value in sorted(mapping(view.get("measurements")).items()):
            measurements.append(
                "thesistrace_health_measurement"
                f'{{view="{view_name}",measurement="{measurement_name}"}} '
                f"{numeric_measurement(value)}"
            )
    lines.extend(
        [
            "# HELP thesistrace_health_measurement Bounded health measurement.",
            "# TYPE thesistrace_health_measurement gauge",
            *measurements,
        ]
    )
    return "\n".join(lines) + "\n"


def default_dependency_status(store: HealthSnapshotStore) -> dict[str, object]:
    checks: dict[str, Callable[[], object]] = {
        "public_origin": public_origin_available,
        "api": lambda: http_available("http://api:8000/api/v1/live"),
        "identity": lambda: http_available("http://insforge:7130/api/health"),
        "database": store.ready,
        "object_store": lambda: http_available("http://object-store:8010/live"),
        "temporal": lambda: tcp_available("temporal", 7233),
        "telemetry": lambda: http_available("http://otel-collector:13133/"),
        "trace_export": trace_export_available,
        "tushare": tushare_available,
        "worker_slots_ready": worker_slots_ready,
        "storage_pressure": storage_pressure_snapshot,
    }
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(checks),
        thread_name_prefix="health-dependency",
    ) as executor:
        futures = {name: executor.submit(check) for name, check in checks.items()}
        return {name: dependency_result(future) for name, future in futures.items()}


def dependency_result(future: concurrent.futures.Future[object]) -> object:
    try:
        return future.result()
    except Exception:
        return False


def temporal_queue_measurements(
    dependencies: Mapping[str, object],
) -> dict[str, int]:
    snapshot = dependencies.get("temporal_queues")
    if not isinstance(snapshot, Mapping):
        return {
            "task_queue_compute_workflow_backlog": -1,
            "task_queue_compute_p1_backlog": -1,
            "task_queue_compute_p3_backlog": -1,
            "task_queue_data_workflow_backlog": -1,
            "task_queue_data_activity_backlog": -1,
        }
    return {
        str(name): int(value) for name, value in snapshot.items() if str(name).endswith("_backlog")
    }


def public_origin_available() -> bool:
    origin = os.environ.get("THESISTRACE_PUBLIC_ORIGIN")
    if not origin:
        return False
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return False
    connect_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    configured_public_host = os.environ.get("THESISTRACE_PUBLIC_ORIGIN_HOST", "")
    site = urlparse(os.environ.get("THESISTRACE_SITE_ADDRESS", ""))
    public_host = configured_public_host or site.hostname or parsed.hostname
    request_target = f"{parsed.path.rstrip('/')}/api/v1/live"
    connection: http.client.HTTPConnection
    try:
        if parsed.scheme == "https":
            context = (
                ssl._create_unverified_context()
                if os.environ.get("THESISTRACE_PUBLIC_ORIGIN_INSECURE", "").lower()
                in {"1", "true", "yes"}
                else ssl.create_default_context()
            )
            connection = RoutedHTTPSConnection(
                parsed.hostname,
                connect_port,
                public_host,
                timeout=3,
                context=context,
            )
        else:
            connection = http.client.HTTPConnection(
                parsed.hostname,
                connect_port,
                timeout=3,
            )
        connection.request("GET", request_target, headers={"Host": public_host})
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        if "connection" in locals():
            connection.close()


def http_available(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def tcp_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def trace_export_available() -> bool:
    try:
        with urllib.request.urlopen(
            "http://otel-collector:8888/metrics",
            timeout=2,
        ) as response:
            metrics = response.read().decode("utf-8")
    except OSError:
        return False
    for line in metrics.splitlines():
        if line.startswith("otelcol_exporter_queue_size{") and 'exporter="otlp/external"' in line:
            try:
                return float(line.rsplit(" ", 1)[-1]) == 0.0
            except ValueError:
                return False
    return False


def storage_pressure_snapshot() -> dict[str, float | bool]:
    try:
        with urllib.request.urlopen(
            "http://object-store:8010/metrics",
            timeout=2,
        ) as response:
            metrics = response.read().decode("utf-8")
        ratio = next(
            float(line.rsplit(" ", 1)[-1])
            for line in metrics.splitlines()
            if line.startswith("thesistrace_storage_used_ratio ")
        )
        warning_ratio = int(os.environ.get("THESISTRACE_DISK_WARNING_PERCENT", "70")) / 100
        return {
            "below_warning": ratio < warning_ratio,
            "used_ratio": ratio,
        }
    except (OSError, StopIteration, ValueError):
        return {
            "below_warning": False,
            "used_ratio": -1.0,
        }


def worker_slots_ready() -> int:
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="health-worker",
    ) as executor:
        checks = executor.map(
            http_available,
            (
                f"http://compute-worker-{slot}:9100/ready"
                for slot in range(1, 5)
            ),
        )
        return sum(checks)


async def monitor_temporal_queues(state: TemporalQueueState) -> None:
    address = os.environ.get("THESISTRACE_TEMPORAL_ADDRESS", "temporal:7233")
    namespace = os.environ.get("THESISTRACE_TEMPORAL_NAMESPACE", "thesistrace")
    client: Client | None = None
    while True:
        try:
            if client is None:
                client = await asyncio.wait_for(
                    Client.connect(address, namespace=namespace),
                    timeout=3,
                )
            state.complete(
                await asyncio.wait_for(
                    read_temporal_queues(client, namespace=namespace),
                    timeout=3,
                )
            )
        except Exception:
            client = None
            state.fail()
        await asyncio.sleep(15)


async def read_temporal_queues(
    client: Client | None = None,
    *,
    namespace: str | None = None,
) -> dict[str, int | bool]:
    effective_namespace = namespace or os.environ.get(
        "THESISTRACE_TEMPORAL_NAMESPACE",
        "thesistrace",
    )
    if client is None:
        address = os.environ.get("THESISTRACE_TEMPORAL_ADDRESS", "temporal:7233")
        client = await Client.connect(
            address,
            namespace=effective_namespace,
            lazy=True,
        )
    queues = (
        (
            "compute_workflow",
            COMPUTE_WORKFLOW_TASK_QUEUE,
            TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        ),
        ("compute_p1", P1_ACTIVITY_TASK_QUEUE, TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY),
        ("compute_p3", P3_ACTIVITY_TASK_QUEUE, TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY),
        (
            "data_workflow",
            DATASET_PUBLICATION_TASK_QUEUE,
            TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        ),
        (
            "data_activity",
            DATASET_PUBLICATION_TASK_QUEUE,
            TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
        ),
    )

    async def describe(name: str, queue: str, queue_type: int):
        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=effective_namespace,
                task_queue=TaskQueue(name=queue),
                task_queue_type=queue_type,
                report_stats=True,
            ),
            timeout=timedelta(seconds=2),
        )
        return name, int(response.stats.approximate_backlog_count), len(response.pollers)

    described = await asyncio.gather(
        *(describe(name, queue, queue_type) for name, queue, queue_type in queues)
    )
    snapshot: dict[str, int | bool] = {
        f"task_queue_{name}_backlog": backlog for name, backlog, _pollers in described
    }
    snapshot["pollers_ready"] = all(
        pollers > 0 or (name in {"compute_p1", "compute_p3"} and backlog == 0)
        for name, backlog, pollers in described
    )
    return snapshot


def tushare_available() -> bool:
    request = (
        b"CONNECT api.tushare.pro:443 HTTP/1.1\r\n"
        b"Host: api.tushare.pro:443\r\nConnection: close\r\n\r\n"
    )
    try:
        with socket.create_connection(("tushare-egress", 8080), timeout=3) as client:
            client.sendall(request)
            return client.recv(64).startswith(b"HTTP/1.1 200")
    except OSError:
        return False


def main() -> None:
    database_url = os.environ.get("THESISTRACE_DATABASE_URL")
    if not database_url:
        raise RuntimeError("THESISTRACE_DATABASE_URL is required")
    configure_observability("health-service")
    store = PostgresHealthSnapshotStore(database_url)
    queue_state = TemporalQueueState()
    app = create_health_app(
        store,
        dependency_status=lambda: default_dependency_status(store),
        fault_plane=os.environ.get("THESISTRACE_HEALTH_FAULT_PLANE") or None,
        temporal_queue_state=queue_state,
    )
    uvicorn.run(app, host="0.0.0.0", port=8020, log_config=None)

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from subprocess import TimeoutExpired
from threading import Event
from time import monotonic
from types import SimpleNamespace

from fastapi.testclient import TestClient

from thesistrace.benchmark import (
    INTERNAL_STRATEGY_METRIC_PATH,
    StrategyComparisonError,
    StrategyComparisonFacts,
)
from thesistrace.entrypoints import readiness as readiness_module
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.readiness import CoreReadiness

_BLOCKED_READINESS_PROBE = Path(__file__).with_name("fixtures") / "blocked-readiness-probe"


def test_readiness_deadline_includes_probe_process_creation(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    constructor_entered = Event()
    release_constructor = Event()

    class ReadyProbe:
        returncode = 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            raise AssertionError("completed readiness probe must not be killed")

    def blocked_constructor(*args, **kwargs):  # type: ignore[no-untyped-def]
        constructor_entered.set()
        if not release_constructor.wait(timeout=1):
            raise AssertionError("readiness probe constructor was not released")
        return ReadyProbe()

    monkeypatch.setattr(readiness_module.subprocess, "Popen", blocked_constructor)
    readiness = CoreReadiness(
        database_url="private-dsn",
        s3_endpoint_url="private-endpoint",
        s3_access_key_id="private-access-key",
        s3_secret_access_key="private-secret-key",
        s3_bucket="private-bucket",
        s3_region="us-east-1",
        data_mount=tmp_path / "private-mounted-root",
        deadline_seconds=0.05,
    )
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(readiness.snapshot)
    try:
        assert constructor_entered.wait(timeout=1)
        snapshot = future.result(timeout=0.2)
        assert snapshot["status"] == "unavailable"
    finally:
        release_constructor.set()
        future.result(timeout=1)
        executor.shutdown(wait=True)

    deadline = monotonic() + 1
    while True:
        snapshot = readiness.snapshot()
        if snapshot["status"] == "ready":
            break
        if monotonic() >= deadline:
            raise AssertionError(f"readiness did not recover after blocked spawn: {snapshot}")
        Event().wait(0.01)


def test_internal_strategy_metric_endpoint_is_hidden_and_returns_only_the_scalar() -> None:
    class Calculator:
        received: StrategyComparisonFacts | None = None

        def annualized_excess_return(
            self,
            facts: StrategyComparisonFacts,
        ) -> float:
            self.received = facts
            return 0.125

    calculator = Calculator()
    app = create_app(event_sink=lambda _event: None)
    app.state.core_runtime = SimpleNamespace(
        annualized_excess_calculator=calculator
    )
    client = TestClient(app)
    try:
        response = client.post(
            INTERNAL_STRATEGY_METRIC_PATH,
            json={
                "entry_session": "2026-08-03",
                "terminal_session": "2026-08-05",
                "session_interval_count": 2,
                "initial_cash_cny": "10000000",
                "terminal_net_nav": "10100000",
            },
        )

        assert response.status_code == 200
        assert response.json() == {"annualized_excess_return": 0.125}
        assert calculator.received == StrategyComparisonFacts(
            entry_session="2026-08-03",
            terminal_session="2026-08-05",
            session_interval_count=2,
            initial_cash_cny="10000000",
            terminal_net_nav="10100000",
        )
        assert INTERNAL_STRATEGY_METRIC_PATH not in client.get("/openapi.json").json()[
            "paths"
        ]
    finally:
        client.close()


def test_internal_strategy_metric_endpoint_rejects_invalid_domain_facts() -> None:
    class RejectingCalculator:
        def annualized_excess_return(
            self,
            _facts: StrategyComparisonFacts,
        ) -> float:
            raise StrategyComparisonError("Strategy comparison facts are invalid")

    app = create_app(event_sink=lambda _event: None)
    app.state.core_runtime = SimpleNamespace(
        annualized_excess_calculator=RejectingCalculator()
    )

    client = TestClient(app)
    try:
        response = client.post(
            INTERNAL_STRATEGY_METRIC_PATH,
            json={
                "entry_session": "2026-08-03",
                "terminal_session": "2026-08-05",
                "session_interval_count": 2,
                "initial_cash_cny": "10000000",
                "terminal_net_nav": "10100000",
            },
        )
    finally:
        client.close()

    assert response.status_code == 422
    assert response.json() == {"detail": "Strategy comparison facts are invalid"}


def test_readiness_has_one_end_to_end_deadline_for_blocked_probes(
    tmp_path: Path,
) -> None:
    events: list[object] = []
    readiness = CoreReadiness(
        auth_internal_origin="http://auth:8200",
        database_url="private-dsn",
        s3_endpoint_url="private-endpoint",
        s3_access_key_id="private-access-key",
        s3_secret_access_key="private-secret-key",
        s3_bucket="private-bucket",
        s3_region="us-east-1",
        data_mount=tmp_path / "private-mounted-root",
        deadline_seconds=0.25,
        probe_command=("/bin/sh", str(_BLOCKED_READINESS_PROBE)),
    )
    app = create_app(event_sink=events.append)
    app.state.core_runtime = SimpleNamespace(readiness=readiness)

    client = TestClient(app, raise_server_exceptions=True)
    try:
        started = monotonic()
        response = client.get("/health/ready")
        elapsed = monotonic() - started

        assert elapsed < 1
        assert response.status_code == 503
        assert response.json() == {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {"status": "ready", "code": "POSTGRESQL_READY"},
                "rustfs": {"status": "ready", "code": "RUSTFS_READY"},
                "dataset_store": {
                    "status": "unavailable",
                    "code": "DATASET_STORE_UNAVAILABLE",
                },
                "auth": {"status": "ready", "code": "AUTH_READY"},
            },
        }
        assert "private" not in response.text
        assert client.get("/health/live").json() == {"status": "ok"}
        assert events == []
    finally:
        client.close()


def test_readiness_does_not_wait_for_a_probe_that_cannot_be_reaped(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    class UnreapableProbe:
        returncode = None

        def wait(self, timeout: float | None = None) -> int:
            raise TimeoutExpired("unreapable-readiness-probe", timeout)

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        readiness_module.subprocess,
        "Popen",
        lambda *args, **kwargs: UnreapableProbe(),
    )
    readiness = CoreReadiness(
        auth_internal_origin="http://auth:8200",
        database_url="private-dsn",
        s3_endpoint_url="private-endpoint",
        s3_access_key_id="private-access-key",
        s3_secret_access_key="private-secret-key",
        s3_bucket="private-bucket",
        s3_region="us-east-1",
        data_mount=tmp_path / "private-mounted-root",
        deadline_seconds=0.05,
    )
    app = create_app()
    app.state.core_runtime = SimpleNamespace(readiness=readiness)
    client = TestClient(app)

    try:
        started = monotonic()
        response = client.get("/health/ready")

        assert monotonic() - started < 0.5
        assert response.status_code == 503
        assert response.json() == {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {
                    "status": "unavailable",
                    "code": "POSTGRESQL_UNAVAILABLE",
                },
                "rustfs": {"status": "unavailable", "code": "RUSTFS_UNAVAILABLE"},
                "dataset_store": {
                    "status": "unavailable",
                    "code": "DATASET_STORE_UNAVAILABLE",
                },
                "auth": {
                    "status": "unavailable",
                    "code": "AUTH_UNAVAILABLE",
                },
            },
        }
    finally:
        client.close()

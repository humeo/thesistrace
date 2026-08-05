import json
import logging
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from thesistrace.hosted.health_service import (
    HealthSnapshotStore,
    SemanticRegressionState,
    create_health_app,
    http_available,
    public_origin_available,
    render_prometheus,
    run_semantic_regression,
    storage_pressure_snapshot,
    trace_export_available,
)
from thesistrace.hosted.observability import (
    JsonLogFormatter,
    sanitize_text,
)
from thesistrace.hosted.probes import ProcessProbeState, create_probe_app


class StubHealthStore(HealthSnapshotStore):
    def __init__(self) -> None:
        self.available = True

    def ready(self) -> bool:
        return self.available

    def snapshot(self) -> dict[str, object]:
        return {
            "system": {
                "active_jobs": 1,
            },
            "data": {
                "release_present": True,
                "release_age_seconds": 60.0,
                "publication_validation_succeeded": True,
                "release_session_current": True,
                "schema_valid": True,
                "coverage_valid": True,
                "lineage_valid": True,
                "previous_release_preserved": True,
                "failed_publications": 0,
            },
            "quantitative": {
                "equivalence_status": "succeeded",
                "equivalence_age_seconds": 60.0,
            },
        }


def healthy_dependencies() -> dict[str, object]:
    return {
        "public_origin": True,
        "api": True,
        "identity": True,
        "database": True,
        "object_store": True,
        "telemetry": True,
        "trace_export": True,
        "tushare": True,
        "worker_slots_ready": 4,
        "storage_pressure": {
            "below_warning": True,
            "used_ratio": 0.25,
        },
        "backup": {
            "healthy": True,
            "last_attempt_succeeded": True,
            "last_success_age_seconds": 60.0,
        },
    }


def complete_semantic_state() -> SemanticRegressionState:
    state = SemanticRegressionState()
    state.complete(
        {
            "deterministic_regression": True,
            "numeric_invariants": True,
            "accounting_invariants": True,
            "checksums": True,
            "missingness": True,
        },
        observed_at=datetime(2026, 7, 31, tzinfo=UTC),
    )
    return state


def test_process_probe_is_dependency_independent_and_role_specific() -> None:
    state = ProcessProbeState(service="api", slot="api-1")
    with TestClient(create_probe_app(state)) as client:
        assert client.get("/live").status_code == 200
        assert client.get("/ready").status_code == 503

        state.mark_ready()
        assert client.get("/ready").json() == {
            "service": "api",
            "slot": "api-1",
            "status": "ready",
        }
        metrics = client.get("/metrics").text
        assert 'service="api"' in metrics
        assert 'slot="api-1"' in metrics
        assert "thesistrace_service_ready 1" in metrics

        state.mark_not_ready()
        assert client.get("/live").status_code == 200
        assert client.get("/ready").status_code == 503


def test_role_readiness_fails_when_the_role_heartbeat_stalls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = ProcessProbeState(service="api", slot="api-1")
    state.mark_ready()
    _ready, heartbeat_at = state.snapshot()
    monkeypatch.setattr(
        "thesistrace.hosted.probes.time.time",
        lambda: heartbeat_at + 31,
    )
    with TestClient(create_probe_app(state)) as client:
        assert client.get("/live").status_code == 200
        assert client.get("/ready").status_code == 503
        assert "thesistrace_service_ready 0" in client.get("/metrics").text


@pytest.mark.parametrize(
    ("fault_plane", "failed_view", "failed_check"),
    [
        ("system", "system", "api"),
        ("data", "data", "tushare"),
        ("quantitative", "quantitative", "deterministic_regression"),
    ],
)
def test_fault_injection_changes_only_the_selected_health_plane(
    fault_plane: str,
    failed_view: str,
    failed_check: str,
) -> None:
    baseline = create_health_app(
        StubHealthStore(),
        dependency_status=healthy_dependencies,
        semantic_state=complete_semantic_state(),
        fault_plane=None,
        run_regression_on_startup=False,
    )
    injected = create_health_app(
        StubHealthStore(),
        dependency_status=healthy_dependencies,
        semantic_state=complete_semantic_state(),
        fault_plane=fault_plane,
        run_regression_on_startup=False,
    )
    with TestClient(baseline) as healthy, TestClient(injected) as failed:
        assert healthy.get("/ready").status_code == 200
        assert failed.get("/ready").status_code == 200
        for view in ("system", "data", "quantitative"):
            healthy_view = healthy.get(f"/health/{view}").json()
            failed_result = failed.get(f"/health/{view}").json()
            if view == failed_view:
                assert healthy_view["status"] == "available"
                assert failed_result["status"] == "degraded"
                assert failed_result["checks"][failed_check] is False
            else:
                assert failed_result == healthy_view
        metrics = failed.get("/metrics").text
        assert f'view="{failed_view}",check="{failed_check}"}} 0' in metrics


def test_failed_publication_degrades_only_data_and_preserves_pointer_evidence() -> None:
    class FailedPublicationStore(StubHealthStore):
        def snapshot(self) -> dict[str, object]:
            snapshot = super().snapshot()
            data = dict(snapshot["data"])
            data["failed_publications"] = 1
            data["previous_release_preserved"] = True
            snapshot["data"] = data
            return snapshot

    app = create_health_app(
        FailedPublicationStore(),
        dependency_status=healthy_dependencies,
        semantic_state=complete_semantic_state(),
        run_regression_on_startup=False,
    )
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/health/system").json()["status"] == "available"
        assert client.get("/health/quantitative").json()["status"] == "available"
        data = client.get("/health/data").json()
        assert data["status"] == "degraded"
        assert data["checks"]["failed_publication"] is False
        assert data["checks"]["previous_release_preserved"] is True


def test_old_release_degrades_freshness_even_when_publication_matches() -> None:
    class OldReleaseStore(StubHealthStore):
        def snapshot(self) -> dict[str, object]:
            snapshot = super().snapshot()
            data = dict(snapshot["data"])
            data["release_age_seconds"] = 345601
            snapshot["data"] = data
            return snapshot

    app = create_health_app(
        OldReleaseStore(),
        dependency_status=healthy_dependencies,
        semantic_state=complete_semantic_state(),
        run_regression_on_startup=False,
    )
    with TestClient(app) as client:
        data = client.get("/health/data").json()
        assert data["status"] == "degraded"
        assert data["checks"]["release_freshness"] is False


def test_tushare_and_telemetry_failures_do_not_kill_system_readiness() -> None:
    dependencies = healthy_dependencies()
    dependencies["tushare"] = False
    dependencies["telemetry"] = False
    dependencies["trace_export"] = False
    app = create_health_app(
        StubHealthStore(),
        dependency_status=lambda: dependencies,
        semantic_state=complete_semantic_state(),
        run_regression_on_startup=False,
    )
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        system = client.get("/health/system").json()
        data = client.get("/health/data").json()
        assert system["status"] == "degraded"
        assert system["checks"]["telemetry"] is False
        assert system["checks"]["trace_export"] is False
        assert data["status"] == "degraded"
        assert data["checks"]["tushare"] is False


def test_recovery_health_requires_restored_platform_not_external_or_historical_checks(
) -> None:
    dependencies = healthy_dependencies()
    dependencies["public_origin"] = False
    dependencies["trace_export"] = False
    dependencies["tushare"] = False

    class NoHistoricalEvidenceStore(StubHealthStore):
        def snapshot(self) -> dict[str, object]:
            snapshot = super().snapshot()
            data = dict(snapshot["data"])
            data["publication_validation_succeeded"] = False
            snapshot["data"] = data
            quantitative = dict(snapshot["quantitative"])
            quantitative["equivalence_status"] = "not_run"
            snapshot["quantitative"] = quantitative
            return snapshot

    app = create_health_app(
        NoHistoricalEvidenceStore(),
        dependency_status=lambda: dependencies,
        semantic_state=complete_semantic_state(),
        run_regression_on_startup=False,
    )
    with TestClient(app) as client:
        recovery = client.get("/health/recovery").json()

    assert recovery["status"] == "available"
    assert recovery["checks"]["data.schema"] is True
    assert recovery["checks"]["quantitative.deterministic_regression"] is True
    assert "system.public_origin" not in recovery["checks"]
    assert "system.trace_export" not in recovery["checks"]
    assert "system.backup" not in recovery["checks"]
    assert "data.tushare" not in recovery["checks"]
    assert "data.validation" not in recovery["checks"]
    assert "quantitative.equivalence" not in recovery["checks"]


def test_disk_warning_degrades_only_system_health_without_killing_readiness() -> None:
    dependencies = healthy_dependencies()
    dependencies["storage_pressure"] = {
        "below_warning": False,
        "used_ratio": 0.71,
    }
    app = create_health_app(
        StubHealthStore(),
        dependency_status=lambda: dependencies,
        semantic_state=complete_semantic_state(),
        run_regression_on_startup=False,
    )
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        system = client.get("/health/system").json()
        assert system["status"] == "degraded"
        assert system["checks"]["disk_pressure"] is False
        assert system["measurements"]["storage_used_ratio"] == 0.71
        assert client.get("/health/data").json()["status"] == "available"


def test_backup_failure_is_visible_without_blocking_unrelated_readiness() -> None:
    dependencies = healthy_dependencies()
    dependencies["backup"] = {
        "healthy": False,
        "last_attempt_succeeded": False,
        "last_success_age_seconds": 3600.0,
    }
    app = create_health_app(
        StubHealthStore(),
        dependency_status=lambda: dependencies,
        semantic_state=complete_semantic_state(),
        run_regression_on_startup=False,
    )
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        system = client.get("/health/system").json()
        assert system["status"] == "degraded"
        assert system["checks"]["backup"] is False
        assert system["measurements"]["backup_last_success_age_seconds"] == 3600.0
        assert client.get("/health/data").json()["status"] == "available"
        assert client.get("/health/quantitative").json()["status"] == "available"
        assert client.get("/health/quantitative").json()["status"] == "available"


@pytest.mark.parametrize(
    ("queue_size", "expected"),
    [("0", True), ("4", False)],
)
def test_external_trace_backlog_is_visible_without_blocking_readiness(
    monkeypatch: pytest.MonkeyPatch,
    queue_size: str,
    expected: bool,
) -> None:
    payload = (f'otelcol_exporter_queue_size{{exporter="otlp/external"}} {queue_size}\n').encode()
    monkeypatch.setattr(
        "thesistrace.hosted.health_service.urllib.request.urlopen",
        lambda *_args, **_kwargs: BytesIO(payload),
    )
    assert trace_export_available() is expected


def test_storage_pressure_uses_the_configured_warning_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"thesistrace_storage_used_ratio 0.71\n"
    monkeypatch.setenv("THESISTRACE_DISK_WARNING_PERCENT", "70")
    monkeypatch.setattr(
        "thesistrace.hosted.health_service.urllib.request.urlopen",
        lambda *_args, **_kwargs: BytesIO(payload),
    )
    assert storage_pressure_snapshot() == {
        "below_warning": False,
        "used_ratio": 0.71,
    }


def test_http_dependency_requires_exact_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response(BytesIO):
        status = 404

    monkeypatch.setattr(
        "thesistrace.hosted.health_service.urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(b"missing"),
    )
    assert http_available("http://dependency/live") is False


def test_public_origin_uses_public_host_for_tls_and_edge_for_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Response:
        status = 200

    class Connection:
        def __init__(
            self,
            connect_host: str,
            connect_port: int,
            public_host: str,
            **_kwargs: object,
        ) -> None:
            observed["connection"] = (connect_host, connect_port, public_host)

        def request(
            self,
            method: str,
            target: str,
            *,
            headers: dict[str, str],
        ) -> None:
            observed["request"] = (method, target, headers)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN", "https://edge:8443")
    monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN_HOST", "localhost")
    monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN_INSECURE", "true")
    monkeypatch.setattr(
        "thesistrace.hosted.health_service.RoutedHTTPSConnection",
        Connection,
        raising=False,
    )

    assert public_origin_available() is True
    assert observed == {
        "connection": ("edge", 8443, "localhost"),
        "request": ("GET", "/api/v1/live", {"Host": "localhost"}),
        "closed": True,
    }


def test_public_origin_derives_hostname_from_site_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Response:
        status = 200

    class Connection:
        def __init__(
            self,
            connect_host: str,
            connect_port: int,
            public_host: str,
            **_kwargs: object,
        ) -> None:
            observed["connection"] = (connect_host, connect_port, public_host)

        def request(self, *_args: object, **kwargs: object) -> None:
            observed["headers"] = kwargs["headers"]

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN", "https://edge:8443")
    monkeypatch.delenv("THESISTRACE_PUBLIC_ORIGIN_HOST", raising=False)
    monkeypatch.setenv("THESISTRACE_SITE_ADDRESS", "https://research.example:443")
    monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN_INSECURE", "false")
    monkeypatch.setattr(
        "thesistrace.hosted.health_service.RoutedHTTPSConnection",
        Connection,
    )

    assert public_origin_available() is True
    assert observed["connection"] == ("edge", 8443, "research.example")
    assert observed["headers"] == {"Host": "research.example"}


def test_semantic_regression_uses_product_contracts_not_profitability() -> None:
    result = run_semantic_regression()
    assert result == {
        "deterministic_regression": True,
        "numeric_invariants": True,
        "accounting_invariants": True,
        "checksums": True,
        "missingness": True,
    }
    assert "return" not in json.dumps(result).lower()
    assert "sharpe" not in json.dumps(result).lower()


def test_prometheus_projection_is_bounded_and_contains_no_private_identity() -> None:
    views = {
        "system": {
            "status": "available",
            "checks": {"database": True, "telemetry": True},
            "measurements": {"active_jobs": 0},
        },
        "data": {
            "status": "available",
            "checks": {"schema": True, "lineage": True},
            "measurements": {"release_age_seconds": 60.0},
        },
        "quantitative": {
            "status": "available",
            "checks": {"numeric_invariants": True, "equivalence": True},
            "measurements": {"equivalence_age_seconds": 60.0},
        },
    }
    payload = render_prometheus(views)
    assert payload.count("thesistrace_health_check{") == 6
    assert 'view="system",check="database"' in payload
    assert "workspace_" not in payload
    assert "@" not in payload
    assert "$close" not in payload


def test_structured_logs_redact_private_and_secret_values() -> None:
    raw = "workspace_deadbeef user@example.com token=top-secret expression=$close_adj"
    sanitized = sanitize_text(raw)
    assert "workspace_deadbeef" not in sanitized
    assert "user@example.com" not in sanitized
    assert "top-secret" not in sanitized
    assert "$close_adj" not in sanitized
    assert "pct_change" not in sanitized

    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        raw,
        (),
        None,
    )
    payload = json.loads(JsonLogFormatter("api").format(record))
    assert payload["service"] == "api"
    assert payload["level"] == "error"
    assert payload["event"] == sanitized

    for credential in (
        "Authorization: Bearer top-secret",
        "Authorization=Basic dXNlcjpwYXNz",
        '{"authorization":"Bearer top-secret"}',
        'password="two secret words"',
        '{"token":"top-secret"}',
        "TUSHARE_TOKEN=top-secret",
        "THESISTRACE_OBJECT_STORE_TOKEN=top-secret",
        '{"refresh_token":"top-secret"}',
    ):
        redacted = sanitize_text(credential)
        assert "top-secret" not in redacted
        assert "dXNlcjpwYXNz" not in redacted
        assert "two secret words" not in redacted

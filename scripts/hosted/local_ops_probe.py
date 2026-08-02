import json
import time
import urllib.request
from collections.abc import Mapping

EXPECTED_LOCAL_SYSTEM_GAPS = frozenset({"backup", "workflow_capacity"})
TELEMETRY_URLS = {
    "collector": "http://otel-collector:8888/metrics",
    "prometheus": "http://prometheus:9090/-/ready",
    "grafana": "http://grafana:3000/api/health",
}
SENSITIVE_MARKERS = (
    "authorization: bearer",
    "password=",
    "@example.invalid",
    "471025",
    "830614",
)


class LocalOperationalHealthError(RuntimeError):
    pass


def read_url(name: str, url: str) -> bytes:
    try:
        return urllib.request.urlopen(url, timeout=10).read()
    except Exception as error:
        raise LocalOperationalHealthError(
            f"{name} endpoint {url} failed: {type(error).__name__}: {error}"
        ) from error


def validate_local_health_views(
    views: Mapping[str, object],
) -> set[str]:
    required = {"system", "data", "quantitative"}
    if set(views) != required:
        raise LocalOperationalHealthError(
            f"local health planes are incomplete: {sorted(views)}"
        )
    normalized: dict[str, Mapping[str, object]] = {}
    for name in sorted(required):
        view = views[name]
        if not isinstance(view, Mapping):
            raise LocalOperationalHealthError(f"{name} health view is malformed")
        normalized[name] = view

    for name in ("data", "quantitative"):
        if normalized[name].get("status") != "available":
            raise LocalOperationalHealthError(
                f"{name} health is not available: "
                f"{json.dumps(dict(normalized[name]), sort_keys=True)}"
            )

    system = normalized["system"]
    checks = system.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        raise LocalOperationalHealthError("system health checks are malformed")
    unavailable = {str(name) for name, value in checks.items() if value is not True}
    unexpected = unavailable - EXPECTED_LOCAL_SYSTEM_GAPS
    missing_expected = EXPECTED_LOCAL_SYSTEM_GAPS - unavailable
    if unexpected or missing_expected or system.get("status") != "degraded":
        raise LocalOperationalHealthError(
            "local system health has unexpected gaps: "
            f"unavailable={sorted(unavailable)} "
            f"unexpected={sorted(unexpected)} "
            f"missing_expected={sorted(missing_expected)}"
        )
    return unavailable


def probe() -> dict[str, object]:
    telemetry = {
        name: read_url(name, url).decode("utf-8")
        for name, url in TELEMETRY_URLS.items()
    }
    views = {
        name: json.loads(
            read_url(name, "http://127.0.0.1:8020/health/" + name)
        )
        for name in ("system", "data", "quantitative")
    }
    expected_gaps = validate_local_health_views(views)
    serialized = "\n".join(telemetry.values()).casefold()
    leaked = [value for value in SENSITIVE_MARKERS if value in serialized]
    if leaked:
        raise LocalOperationalHealthError(
            f"telemetry contains sensitive markers: {leaked}"
        )
    return {
        "configured_limits": {
            "grafana": {"cpu": 0.25, "memory": "384m", "swap": "disabled"},
            "otel_collector": {"cpu": 0.1, "memory": "256m", "swap": "disabled"},
            "prometheus": {"cpu": 0.1},
        },
        "health_planes": views,
        "local_expected_degraded_checks": sorted(expected_gaps),
        "status": "passed",
        "telemetry_endpoints": sorted(TELEMETRY_URLS),
        "telemetry_redaction": True,
        "production_capacity_claimed": False,
    }


def main() -> None:
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            print(json.dumps(probe(), sort_keys=True))
            return
        except Exception as error:
            last_error = error
            time.sleep(2)
    raise LocalOperationalHealthError(
        "local operational health did not converge: "
        f"{type(last_error).__name__}: {last_error}"
    )


if __name__ == "__main__":
    main()

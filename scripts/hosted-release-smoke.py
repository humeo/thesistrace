import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "scripts" / "hosted-stack"
VERIFY_CODE = "471025"
RESET_CODE = "830614"
LOCAL_CREDENTIALS_FILE = "public-origin-credentials.json"
LOCAL_CONTEXT_FILE = "public-origin-context.json"


class AcceptanceFailure(RuntimeError):
    pass


class AcceptanceProfile(NamedTuple):
    name: str
    actor: str
    compute_services: tuple[str, ...]
    whole_node_recovery: bool
    backup_and_three_health_planes: bool
    invitation_gate_reason: str


def acceptance_profile(name: str) -> AcceptanceProfile:
    if name == "launch":
        return AcceptanceProfile(
            name="launch",
            actor="release-acceptance",
            compute_services=tuple(
                f"compute-worker-{index}" for index in range(1, 5)
            ),
            whole_node_recovery=True,
            backup_and_three_health_planes=True,
            invitation_gate_reason="LAUNCH_QUALIFICATION_REQUIRED",
        )
    if name == "local":
        return AcceptanceProfile(
            name="local",
            actor="local-acceptance",
            compute_services=("compute-worker-1",),
            whole_node_recovery=False,
            backup_and_three_health_planes=False,
            invitation_gate_reason="CAPACITY_QUALIFICATION_REQUIRED",
        )
    raise AcceptanceFailure(f"unknown public-origin acceptance profile: {name}")


def _write_private_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _reject_persisted_tokens(value: object, *, path: str = "context") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if "token" in normalized or normalized == "authorization":
                raise AcceptanceFailure(
                    f"access or session token is forbidden in local {path}"
                )
            _reject_persisted_tokens(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_persisted_tokens(item, path=f"{path}[{index}]")


def write_local_acceptance_context(
    state_dir: Path,
    credentials: dict[str, object],
    product: dict[str, object],
) -> None:
    required_credentials = {"email_a", "password_a", "email_b", "password_b"}
    if set(credentials) != required_credentials or any(
        not isinstance(credentials[name], str) or not credentials[name]
        for name in required_credentials
    ):
        raise AcceptanceFailure("local acceptance credentials are incomplete")
    _reject_persisted_tokens(product)
    resolved = state_dir.resolve()
    _write_private_json(resolved / LOCAL_CREDENTIALS_FILE, credentials)
    _write_private_json(resolved / LOCAL_CONTEXT_FILE, product)


def read_local_acceptance_context(
    state_dir: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        credentials = json.loads((state_dir / LOCAL_CREDENTIALS_FILE).read_text())
        product = json.loads((state_dir / LOCAL_CONTEXT_FILE).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AcceptanceFailure("local acceptance product context is unavailable") from error
    if not isinstance(credentials, dict) or not isinstance(product, dict):
        raise AcceptanceFailure("local acceptance product context is invalid")
    _reject_persisted_tokens(product)
    return credentials, product


def local_acceptance_state_dir() -> Path:
    value = os.environ.get("THESISTRACE_HOST_STATE_DIR")
    if not value:
        raise AcceptanceFailure("THESISTRACE_HOST_STATE_DIR is required")
    return Path(value).resolve()


def read_json_object(response) -> dict[str, object]:
    try:
        payload = json.load(response)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def request(
    origin: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    data = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    context = (
        ssl._create_unverified_context()
        if origin.startswith("https://")
        and os.environ.get("THESISTRACE_SMOKE_INSECURE_TLS") == "1"
        else None
    )
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                f"{origin.rstrip('/')}{path}",
                data=data,
                headers=request_headers,
                method=method,
            ),
            timeout=120,
            context=context,
        ) as response:
            payload = read_json_object(response)
            return response.status, payload
    except urllib.error.HTTPError as error:
        payload = read_json_object(error)
        return error.code, payload


def stack(*arguments: str, expect: int = 0) -> dict[str, object]:
    environment = dict(os.environ)
    environment["THESISTRACE_ACCEPTANCE_MODE"] = "1"
    completed = subprocess.run(
        [str(STACK), *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != expect:
        raise AcceptanceFailure(
            f"operator command failed ({completed.returncode}): "
            f"{' '.join(arguments)}\n{completed.stderr[-2000:]}"
        )
    serialized = f"{completed.stdout}\n{completed.stderr}".strip()
    if not serialized:
        return {}
    for line in reversed(serialized.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def require_status(
    actual: tuple[int, dict[str, object]],
    expected: int | tuple[int, ...],
    label: str,
) -> dict[str, object]:
    accepted = (expected,) if isinstance(expected, int) else expected
    status, payload = actual
    if status not in accepted:
        raise AcceptanceFailure(f"{label}: expected {accepted}, got {status}: {payload}")
    return payload


def require_eventual_status(
    operation: Callable[[], tuple[int, dict[str, object]]],
    expected: int | tuple[int, ...],
    label: str,
    *,
    attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    accepted = (expected,) if isinstance(expected, int) else expected
    last: tuple[int, dict[str, object]] = (0, {})
    for attempt in range(attempts):
        last = operation()
        if last[0] in accepted:
            return last[1]
        if last[0] not in {500, 502, 503, 504}:
            return require_status(last, accepted, label)
        if attempt + 1 < attempts:
            sleeper(2)
    return require_status(last, accepted, label)


def require_resource_id(payload: dict[str, object], label: str) -> str:
    resource_id = payload.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        raise AcceptanceFailure(f"{label}: response is missing resource id: {payload}")
    return resource_id


def poll(
    operation,
    predicate,
    label: str,
    *,
    timeout: float = 900,
    terminal_failure=None,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        status, last = operation()
        if status == 200 and predicate(last):
            return last
        if status == 200 and terminal_failure is not None and terminal_failure(last):
            raise AcceptanceFailure(f"{label} failed before convergence: {last}")
        time.sleep(2)
    raise AcceptanceFailure(f"{label} did not converge: {last}")


def register_user(email: str, password: str, origin: str) -> tuple[str, str]:
    anon_key_payload = require_eventual_status(
        lambda: request(origin, "/api/auth/anon-key"),
        200,
        "public anon key",
    )
    anon_key = anon_key_payload.get("anonKey")
    if not isinstance(anon_key, str) or not anon_key.startswith("anon_"):
        raise AcceptanceFailure("public anon key was missing or malformed")

    registration = require_eventual_status(
        lambda: request(
            origin,
            "/api/auth/users?client_type=server",
            method="POST",
            body={"email": email, "password": password, "name": "Acceptance User"},
            token=anon_key,
        ),
        200,
        "public registration",
    )
    access_token = registration.get("accessToken")
    if not isinstance(access_token, str):
        raise AcceptanceFailure("registration did not return an access token")
    return access_token, anon_key


def login_user(
    email: str,
    password: str,
    origin: str,
    *,
    label: str = "login",
) -> str:
    logged_in = require_eventual_status(
        lambda: request(
            origin,
            "/api/auth/sessions?client_type=server",
            method="POST",
            body={"email": email, "password": password},
        ),
        200,
        label,
    )
    token = logged_in.get("accessToken")
    if not isinstance(token, str):
        raise AcceptanceFailure(f"{label} returned no access token")
    return token


def refresh_access_token(
    current_token: str,
    refresher: Callable[[], str] | None,
    label: str,
) -> str:
    if refresher is None:
        return current_token
    token = refresher()
    if not token:
        raise AcceptanceFailure(f"{label} returned no access token")
    return token


def seed_user(email: str, password: str, origin: str) -> tuple[str, str]:
    stack("acceptance-seed-invitation", email)
    unverified_token, _anon_key = register_user(email, password, origin)
    unverified = require_status(
        request(origin, "/api/v1/session", token=unverified_token),
        403,
        "unverified product rejection",
    )
    if unverified.get("detail", {}).get("reason_code") != "AUTH_EMAIL_UNVERIFIED":
        raise AcceptanceFailure("unverified identity was not classified explicitly")

    stack("acceptance-seed-otp", email, "VERIFY_EMAIL", VERIFY_CODE)
    verified = require_eventual_status(
        lambda: request(
            origin,
            "/api/auth/email/verify?client_type=server",
            method="POST",
            body={"email": email, "otp": VERIFY_CODE},
        ),
        200,
        "public email verification",
    )
    token = verified.get("accessToken")
    if not isinstance(token, str):
        raise AcceptanceFailure("email verification did not return an access token")

    first = require_eventual_status(
        lambda: request(origin, "/api/v1/provision", method="POST", token=token),
        201,
        "first provisioning",
    )
    second = require_eventual_status(
        lambda: request(origin, "/api/v1/provision", method="POST", token=token),
        200,
        "idempotent provisioning",
    )
    if (
        first.get("workspace_id") != second.get("workspace_id")
        or first.get("user_id") != second.get("user_id")
        or second.get("created") is not False
    ):
        raise AcceptanceFailure("provisioning did not preserve exactly one identity")
    session = require_status(
        request(origin, "/api/v1/session", token=token),
        200,
        "provisioned session",
    )
    if session.get("workspace_id") != first.get("workspace_id"):
        raise AcceptanceFailure("session resolved a different Personal Workspace")
    return token, str(first["workspace_id"])


def definition(title: str) -> dict[str, object]:
    return {
        "title": title,
        "hypothesis": "过去 20 日上涨的股票未来收益更高。",
        "dataset_release": "latest",
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


def assert_list_excludes_resource(
    payload: dict[str, object],
    foreign_resource_id: str,
    path: str,
) -> None:
    items = payload.get("items")
    if not isinstance(items, list):
        raise AcceptanceFailure(f"cross-Workspace list is malformed: {path}")
    if any(
        isinstance(item, dict) and item.get("id") == foreign_resource_id
        for item in items
    ):
        raise AcceptanceFailure(
            f"cross-Workspace list disclosed foreign resource: {path}"
        )


def assert_cross_workspace_denial(
    origin: str,
    token: str,
    *,
    foreign_workspace_id: str,
    draft_id: str,
    run_id: str,
    track_id: str,
    advance_id: str,
    suffix: str,
) -> None:
    list_resources = (
        ("/api/v1/research-definitions", draft_id),
        ("/api/v1/research-runs", run_id),
        ("/api/v1/daily-tracks", track_id),
    )
    for path, foreign_resource_id in list_resources:
        payload = require_status(request(origin, path, token=token), 200, path)
        assert_list_excludes_resource(payload, foreign_resource_id, path)

    denied = (
        ("GET", f"/api/v1/research-definitions/{draft_id}", None, None),
        ("PUT", f"/api/v1/research-definitions/{draft_id}", {"title": "stolen"}, None),
        (
            "POST",
            f"/api/v1/research-definitions/{draft_id}/runs",
            None,
            {"Idempotency-Key": f"cross-run-{suffix}"},
        ),
        ("GET", f"/api/v1/research-runs/{run_id}", None, None),
        ("GET", f"/api/v1/research-runs/{run_id}/result", None, None),
        ("POST", f"/api/v1/research-runs/{run_id}/cancel", None, None),
        (
            "POST",
            f"/api/v1/research-runs/{run_id}/rerun",
            None,
            {"Idempotency-Key": f"cross-rerun-{suffix}"},
        ),
        (
            "POST",
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            None,
            {"Idempotency-Key": f"cross-track-{suffix}"},
        ),
        ("GET", f"/api/v1/daily-tracks/{track_id}", None, None),
        ("GET", f"/api/v1/daily-tracks/{track_id}/current", None, None),
        (
            "GET",
            f"/api/v1/daily-tracks/{track_id}/advances/{advance_id}",
            None,
            None,
        ),
        (
            "POST",
            f"/api/v1/daily-tracks/{track_id}/equivalence-requests",
            None,
            {"Idempotency-Key": f"cross-verify-{suffix}"},
        ),
        ("POST", f"/api/v1/daily-tracks/{track_id}/stop", None, None),
        ("DELETE", f"/api/v1/daily-tracks/{track_id}", None, None),
        ("DELETE", f"/api/v1/research-runs/{run_id}", None, None),
    )
    for method, path, body, headers in denied:
        status, payload = request(
            origin,
            path,
            method=method,
            body=body,
            token=token,
            headers=headers,
        )
        if status != 404:
            raise AcceptanceFailure(
                f"cross-Workspace operation disclosed existence: {method} {path}: "
                f"{status} {payload}"
            )

    forged = require_status(
        request(
            origin,
            "/api/v1/research-definitions",
            method="POST",
            body={"title": "forged", "workspace_id": foreign_workspace_id},
            token=token,
        ),
        422,
        "client Workspace forgery",
    )
    if forged.get("detail", {}).get("reason_code") != "CLIENT_WORKSPACE_FORBIDDEN":
        raise AcceptanceFailure("Workspace forgery was not rejected explicitly")


def password_recovery(origin: str, email: str, old_password: str) -> str:
    require_eventual_status(
        lambda: request(
            origin,
            "/api/auth/email/send-reset-password",
            method="POST",
            body={"email": f"unknown-{uuid4().hex}@example.invalid"},
        ),
        202,
        "non-disclosing reset request",
    )
    stack("acceptance-seed-otp", email, "RESET_PASSWORD", RESET_CODE)
    exchanged = require_eventual_status(
        lambda: request(
            origin,
            "/api/auth/email/exchange-reset-password-token",
            method="POST",
            body={"email": email, "code": RESET_CODE},
        ),
        200,
        "reset code exchange",
    )
    reset_token = exchanged.get("token")
    if not isinstance(reset_token, str):
        raise AcceptanceFailure("password recovery did not return a reset token")
    new_password = f"{old_password}-reset"
    require_eventual_status(
        lambda: request(
            origin,
            "/api/auth/email/reset-password",
            method="POST",
            body={"newPassword": new_password, "otp": reset_token},
        ),
        200,
        "password reset",
    )
    return login_user(
        email,
        new_password,
        origin,
        label="login after password reset",
    )


def wait_for_three_health_planes() -> None:
    deadline = time.monotonic() + 180
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = stack("health-check")
            if set(health) == {"system", "data", "quantitative"} and all(
                view.get("status") == "available" for view in health.values()
            ):
                return
        except AcceptanceFailure as error:
            last_error = error
        time.sleep(3)
    raise AcceptanceFailure(f"three health planes did not converge: {last_error}")


def assert_single_resource(
    origin: str,
    token: str,
    path: str,
    resource_id: str,
    label: str,
) -> None:
    payload = require_status(request(origin, path, token=token), 200, label)
    matches = [
        item
        for item in payload.get("items", [])
        if isinstance(item, dict) and item.get("id") == resource_id
    ]
    if len(matches) != 1:
        raise AcceptanceFailure(f"{label} was not published exactly once")


def interrupt_api_rerun(
    origin: str,
    token: str,
    *,
    run_id: str,
    rerun_key: str,
) -> str:
    def attempt_rerun() -> tuple[int, dict[str, object]]:
        try:
            return request(
                origin,
                f"/api/v1/research-runs/{run_id}/rerun",
                method="POST",
                token=token,
                headers={"Idempotency-Key": rerun_key},
            )
        except urllib.error.URLError:
            return 0, {}

    admitted = require_status(
        attempt_rerun(),
        (200, 202),
        "ResearchRun before API interruption",
    )
    recovery_run_id = require_resource_id(
        admitted,
        "ResearchRun before API interruption",
    )

    stack("acceptance-stop-service", "api")
    try:
        interrupted_status, interrupted_payload = attempt_rerun()
    finally:
        stack("acceptance-start-service", "api")
    if interrupted_status != 0 and interrupted_status < 500:
        raise AcceptanceFailure(
            "API request remained available during the explicit interruption: "
            f"{interrupted_status}: {interrupted_payload}"
        )

    poll(
        lambda: request(origin, "/api/v1/session", token=token),
        lambda value: bool(value.get("workspace_id")),
        "API recovery",
    )
    replayed = require_status(
        attempt_rerun(),
        200,
        "idempotent API recovery",
    )
    if require_resource_id(replayed, "idempotent API recovery") != recovery_run_id:
        raise AcceptanceFailure("API recovery created a duplicate ResearchRun")
    return recovery_run_id


def wait_for_publication_status(
    publication_id: str,
    accepted: set[str],
    *,
    timeout: float = 120,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        last = stack("acceptance-publication-status", publication_id)
        if last.get("status") in accepted:
            return last
        time.sleep(0.05)
    raise AcceptanceFailure(
        f"Dataset Publication did not reach {sorted(accepted)}: {last}"
    )


def assert_storage_invariants() -> None:
    index = stack("acceptance-storage-status")
    physical = stack("acceptance-object-status")
    if index.get("unreferenced_object_count") != 0:
        raise AcceptanceFailure(f"authoritative Storage index has orphans: {index}")
    if index.get("stored_object_count") != physical.get("physical_object_count"):
        raise AcceptanceFailure(
            f"physical and authoritative Storage counts differ: {index} {physical}"
        )
    if physical.get("staged_publications") != []:
        raise AcceptanceFailure(f"partial staged artifacts remain: {physical}")


def run_whole_node_recovery(
    origin: str,
    token: str,
    *,
    run_id: str,
    recovery_run_id: str,
    track_id: str,
    suffix: str,
    release_ids_after: set[str],
) -> None:
    stack("maintenance-enter")
    try:
        maintenance_rejection = require_status(
            request(
                origin,
                f"/api/v1/research-runs/{run_id}/rerun",
                method="POST",
                token=token,
                headers={"Idempotency-Key": f"maintenance-rerun-{suffix}"},
            ),
            503,
            "maintenance admission fence",
        )
        if maintenance_rejection.get("detail", {}).get("reason_code") != (
            "MAINTENANCE_MODE"
        ):
            raise AcceptanceFailure("maintenance rejection lost its stable classification")
        stack("acceptance-restart-node")
        poll(
            lambda: request(origin, "/api/v1/session", token=token),
            lambda value: bool(value.get("workspace_id")),
            "node recovery during maintenance",
            timeout=300,
        )
        persisted_maintenance = require_status(
            request(
                origin,
                f"/api/v1/research-runs/{run_id}/rerun",
                method="POST",
                token=token,
                headers={"Idempotency-Key": f"maintenance-recovered-{suffix}"},
            ),
            503,
            "maintenance fence after node recovery",
        )
        if persisted_maintenance.get("detail", {}).get("reason_code") != (
            "MAINTENANCE_MODE"
        ):
            raise AcceptanceFailure("node recovery silently exited maintenance")
        require_status(
            request(origin, f"/api/v1/research-runs/{recovery_run_id}", token=token),
            200,
            "ResearchRun after node recovery",
        )
        require_status(
            request(
                origin,
                f"/api/v1/research-runs/{recovery_run_id}/result?daily_limit=1",
                token=token,
            ),
            200,
            "Research result after node recovery",
        )
        require_status(
            request(
                origin,
                f"/api/v1/daily-tracks/{track_id}/current?limit=1",
                token=token,
            ),
            200,
            "DailyTrack after node recovery",
        )
        recovered_releases = require_status(
            request(origin, "/api/v1/dataset-releases", token=token),
            200,
            "Dataset Releases after node recovery",
        )
        if {
            str(item["id"])
            for item in recovered_releases.get("items", [])
            if isinstance(item, dict)
        } != release_ids_after:
            raise AcceptanceFailure("node recovery changed authoritative Dataset Releases")
        assert_storage_invariants()
    finally:
        stack("maintenance-exit")
    assert_single_resource(
        origin,
        token,
        "/api/v1/research-runs",
        recovery_run_id,
        "ResearchRun after node recovery",
    )


def run_recovery_interruption_matrix(
    origin: str,
    token: str,
    *,
    run_id: str,
    track_id: str,
    suffix: str,
    profile_name: str = "launch",
    token_refresher: Callable[[], str] | None = None,
) -> tuple[dict[str, bool], str]:
    profile = acceptance_profile(profile_name)
    compute_services = profile.compute_services
    for service in compute_services:
        stack("acceptance-stop-service", service)
    stack("acceptance-stop-service", "execution-relay")
    rerun_key = f"recovery-rerun-{suffix}"
    recovery_run_id = interrupt_api_rerun(
        origin,
        token,
        run_id=run_id,
        rerun_key=rerun_key,
    )
    queued = require_status(
        request(origin, f"/api/v1/research-runs/{recovery_run_id}", token=token),
        200,
        "queued ResearchRun while relay is unavailable",
    )
    if queued.get("status") != "queued":
        raise AcceptanceFailure("ResearchRun escaped its durable outbox while relay was down")
    assert_single_resource(
        origin,
        token,
        "/api/v1/research-runs",
        recovery_run_id,
        "outbox ResearchRun",
    )

    stack("acceptance-start-service", "execution-relay")
    token = refresh_access_token(
        token,
        token_refresher,
        "login before Research Activity interruption",
    )
    stack("acceptance-start-interruption", "compute-worker-1")
    deadline = time.monotonic() + 120
    last_run: dict[str, object] = {}
    while time.monotonic() < deadline:
        last_run = require_status(
            request(
                origin,
                f"/api/v1/research-runs/{recovery_run_id}",
                token=token,
            ),
            200,
            "Research Activity interruption target",
        )
        if last_run.get("status") == "running":
            stack("acceptance-kill-service", "compute-worker-1")
            break
        if last_run.get("status") in {"succeeded", "failed", "cancelled"}:
            raise AcceptanceFailure(
                "Research Activity completed before its Worker was interrupted"
            )
        time.sleep(0.05)
    else:
        raise AcceptanceFailure(f"Research Activity was never claimed: {last_run}")

    stack("acceptance-start-service", "compute-worker-1")
    recovered_run = poll(
        lambda: request(
            origin,
            f"/api/v1/research-runs/{recovery_run_id}",
            token=token,
        ),
        lambda value: value.get("status") == "succeeded",
        "interrupted Research Activity recovery",
        timeout=600,
    )
    if recovered_run.get("status") != "succeeded":
        raise AcceptanceFailure("interrupted ResearchRun did not recover")
    run_attempts = recovered_run.get("attempts")
    if not isinstance(run_attempts, list) or len(run_attempts) < 2:
        raise AcceptanceFailure(
            "Research Activity interruption did not produce a second Attempt"
        )
    require_status(
        request(
            origin,
            f"/api/v1/research-runs/{recovery_run_id}/result?daily_limit=1",
            token=token,
        ),
        200,
        "single recovered Research result",
    )
    assert_single_resource(
        origin,
        token,
        "/api/v1/research-runs",
        recovery_run_id,
        "recovered ResearchRun",
    )
    for service in compute_services[1:]:
        stack("acceptance-start-service", service)

    token = refresh_access_token(
        token,
        token_refresher,
        "login after Research Activity interruption",
    )
    releases_before = require_status(
        request(origin, "/api/v1/dataset-releases", token=token),
        200,
        "pre-interruption Dataset Releases",
    )
    release_ids_before = {
        str(item["id"])
        for item in releases_before.get("items", [])
        if isinstance(item, dict)
    }
    stack("acceptance-arm-publication-interruption")
    publication_key = f"recovery-publication-{suffix}"
    publication = stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        profile.actor,
        "--kind",
        "fixture_increment",
        "--new-sessions",
        "20",
        "--idempotency-key",
        publication_key,
    )
    publication_record = publication.get("publication")
    if not isinstance(publication_record, dict):
        raise AcceptanceFailure("Dataset Publication request returned no resource")
    publication_id = str(publication_record["id"])
    repeated_publication = stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        profile.actor,
        "--kind",
        "fixture_increment",
        "--new-sessions",
        "20",
        "--idempotency-key",
        publication_key,
    )
    if (
        repeated_publication.get("created") is not False
        or repeated_publication.get("publication", {}).get("id") != publication_id
    ):
        raise AcceptanceFailure("publication retry created a duplicate request")
    stack("acceptance-interrupt-publication", publication_id)
    stack("acceptance-start-service", "data-worker")
    completed_publication = wait_for_publication_status(
        publication_id,
        {"succeeded", "failed", "cancelled"},
        timeout=600,
    )
    if completed_publication.get("status") != "succeeded":
        raise AcceptanceFailure(
            f"interrupted Dataset Publication did not recover: {completed_publication}"
        )
    if int(completed_publication.get("attempt_count", 0)) < 2:
        raise AcceptanceFailure("publication interruption did not produce a redelivery")
    token = refresh_access_token(
        token,
        token_refresher,
        "login after Dataset Publication interruption",
    )
    releases_after = poll(
        lambda: request(origin, "/api/v1/dataset-releases", token=token),
        lambda value: len(value.get("items", [])) == len(release_ids_before) + 1,
        "single interrupted Dataset Release",
        timeout=600,
    )
    release_ids_after = {
        str(item["id"])
        for item in releases_after.get("items", [])
        if isinstance(item, dict)
    }
    if (
        release_ids_after - release_ids_before
        != {str(completed_publication["result_release_id"])}
    ):
        raise AcceptanceFailure("publication recovery exposed duplicate or partial Releases")
    assert_storage_invariants()

    if profile.whole_node_recovery:
        run_whole_node_recovery(
            origin,
            token,
            run_id=run_id,
            recovery_run_id=recovery_run_id,
            track_id=track_id,
            suffix=suffix,
            release_ids_after=release_ids_after,
        )
    result = {
        "api": True,
        "outbox_relay": True,
        "temporal_worker": True,
        "activity": True,
        "publication": True,
        "no_duplicate_domain_result": True,
        "no_partial_authoritative_artifact": True,
    }
    if profile.whole_node_recovery:
        result.update({"maintenance": True, "node": True})
    return result, recovery_run_id


def _local_origin() -> str:
    origin = os.environ.get("THESISTRACE_HOSTED_ORIGIN")
    if not origin:
        raise AcceptanceFailure("THESISTRACE_HOSTED_ORIGIN is required")
    return origin


def _required_text(value: dict[str, object], name: str) -> str:
    candidate = value.get(name)
    if not isinstance(candidate, str) or not candidate:
        raise AcceptanceFailure(f"local acceptance context has no {name}")
    return candidate


def _local_gate_evidence(gate: str, **values: object) -> dict[str, object]:
    return {
        "status": "passed",
        "schema_version": "hosted-local-public-origin-gate-v1",
        "profile": "local",
        "gate": gate,
        **values,
    }


def _update_local_product_context(**values: object) -> dict[str, object]:
    state_dir = local_acceptance_state_dir()
    credentials, product = read_local_acceptance_context(state_dir)
    product.update(values)
    write_local_acceptance_context(state_dir, credentials, product)
    return product


def _fresh_local_logins() -> tuple[str, str, dict[str, object], dict[str, object]]:
    credentials, product = read_local_acceptance_context(local_acceptance_state_dir())
    origin = _local_origin()
    token_a = login_user(
        _required_text(credentials, "email_a"),
        _required_text(credentials, "password_a"),
        origin,
        label="User A fresh local gate login",
    )
    token_b = login_user(
        _required_text(credentials, "email_b"),
        _required_text(credentials, "password_b"),
        origin,
        label="User B fresh local gate login",
    )
    return token_a, token_b, credentials, product


def _retained_identity_evidence(
    origin: str,
    credentials: dict[str, object],
    product: dict[str, object],
) -> dict[str, object]:
    token_a = login_user(
        _required_text(credentials, "email_a"),
        _required_text(credentials, "password_a"),
        origin,
        label="User A retained product login",
    )
    token_b = login_user(
        _required_text(credentials, "email_b"),
        _required_text(credentials, "password_b"),
        origin,
        label="User B retained product login",
    )
    for label, token, workspace_id in (
        ("User A retained session", token_a, _required_text(product, "workspace_a")),
        ("User B retained session", token_b, _required_text(product, "workspace_b")),
    ):
        session = require_status(request(origin, "/api/v1/session", token=token), 200, label)
        if session.get("workspace_id") != workspace_id:
            raise AcceptanceFailure(f"{label} resolved a different Workspace")
    run_id = _required_text(product, "run_id")
    retained_run = require_status(
        request(origin, f"/api/v1/research-runs/{run_id}", token=token_a),
        200,
        "retained ResearchRun",
    )
    if retained_run.get("status") != "succeeded":
        raise AcceptanceFailure("retained ResearchRun is no longer succeeded")
    require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/result?daily_limit=1&position_limit=1",
            token=token_a,
        ),
        200,
        "retained bounded result",
    )
    require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{_required_text(product, 'track_id')}/current?limit=1",
            token=token_a,
        ),
        200,
        "retained DailyTrack witness",
    )
    require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{_required_text(product, 'track_id')}"
            f"/equivalence-requests/{_required_text(product, 'equivalence_id')}",
            token=token_a,
        ),
        200,
        "retained equivalence witness",
    )
    for kind, resource_id in (
        ("research-runs", _required_text(product, "tombstone_run_id")),
        ("daily-tracks", _required_text(product, "tombstone_track_id")),
    ):
        require_status(
            request(origin, f"/api/v1/{kind}/{resource_id}", token=token_a),
            404,
            f"retained {kind} Tombstone",
        )
    for label, token in (("User A shared release", token_a), ("User B shared release", token_b)):
        releases = require_status(
            request(origin, "/api/v1/dataset-releases", token=token),
            200,
            label,
        )
        if _required_text(product, "release_id") not in {
            str(item.get("id"))
            for item in releases.get("items", [])
            if isinstance(item, dict)
        }:
            raise AcceptanceFailure(f"{label} lost the retained Dataset Release")
    evidence = product.get("identity_evidence")
    if not isinstance(evidence, dict):
        raise AcceptanceFailure("retained identity evidence is unavailable")
    return {**evidence, "reused": True}


def run_local_identity_product() -> dict[str, object]:
    origin = _local_origin()
    state_dir = local_acceptance_state_dir()
    if (state_dir / LOCAL_CREDENTIALS_FILE).exists() or (state_dir / LOCAL_CONTEXT_FILE).exists():
        credentials, product = read_local_acceptance_context(state_dir)
        return _retained_identity_evidence(origin, credentials, product)

    profile = acceptance_profile("local")
    suffix = uuid4().hex
    email_a = f"local-a-{suffix}@example.invalid"
    email_b = f"local-b-{suffix}@example.invalid"
    password_a = f"Local-A-{suffix[:12]}!9"
    password_b = f"Local-B-{suffix[:12]}!9"

    stack("acceptance-assert-clean")
    blocked = stack(
        "operator",
        "invitation",
        "issue",
        "--actor",
        profile.actor,
        "--email",
        f"blocked-{suffix}@example.invalid",
        "--expires-at",
        "2099-01-01T00:00:00Z",
        expect=2,
    )
    if blocked.get("reason_code") != profile.invitation_gate_reason:
        raise AcceptanceFailure(f"closed local invitation gate was not enforced: {blocked}")
    stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        profile.actor,
        "--kind",
        "fixture_bootstrap",
        "--idempotency-key",
        f"local-bootstrap-{suffix}",
    )
    token_a, workspace_a = seed_user(email_a, password_a, origin)
    token_b, workspace_b = seed_user(email_b, password_b, origin)
    token_a = password_recovery(origin, email_a, password_a)
    password_a = f"{password_a}-reset"

    releases_a = poll(
        lambda: request(origin, "/api/v1/dataset-releases", token=token_a),
        lambda value: bool(value.get("items")),
        "shared local Dataset Release",
    )
    releases_b = require_status(
        request(origin, "/api/v1/dataset-releases", token=token_b),
        200,
        "User B shared local Dataset Release",
    )
    if releases_a != releases_b:
        raise AcceptanceFailure("local Users received different shared Release views")
    release_id = str(releases_a["items"][-1]["id"])
    contract_a = require_status(
        request(
            origin,
            f"/api/v1/dataset-releases/{release_id}/data-contract",
            token=token_a,
        ),
        200,
        "User A shared data contract",
    )
    contract_b = require_status(
        request(
            origin,
            f"/api/v1/dataset-releases/{release_id}/data-contract",
            token=token_b,
        ),
        200,
        "User B shared data contract",
    )
    if contract_a != contract_b:
        raise AcceptanceFailure("shared Dataset contract differed by local User")

    draft_a = require_status(
        request(
            origin,
            "/api/v1/research-definitions",
            method="POST",
            body=definition("Local acceptance A"),
            token=token_a,
        ),
        201,
        "User A local draft",
    )
    require_status(
        request(
            origin,
            "/api/v1/research-definitions",
            method="POST",
            body=definition("Local acceptance B"),
            token=token_b,
        ),
        201,
        "User B local draft",
    )
    run_response = require_status(
        request(
            origin,
            f"/api/v1/research-definitions/{draft_a['id']}/runs",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"local-run-{suffix}"},
        ),
        202,
        "local ResearchRun request",
    )
    run_id = str(run_response["run"]["id"])
    run = poll(
        lambda: request(origin, f"/api/v1/research-runs/{run_id}", token=token_a),
        lambda value: value.get("status") == "succeeded",
        "local ResearchRun",
    )
    if "result_manifest_sha256" in run:
        raise AcceptanceFailure("local ResearchRun disclosed its storage identity")
    result = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/result?daily_limit=1&position_limit=1",
            token=token_a,
        ),
        200,
        "local bounded Result Bundle",
    )
    daily = result.get("strategy_backtest", {}).get("daily", [])
    positions = result.get("terminal_strategy_state", {}).get("positions", [])
    if len(daily) > 1 or len(positions) > 1:
        raise AcceptanceFailure("local Result Bundle ignored bounded view limits")

    track = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"local-track-{suffix}"},
        ),
        (200, 201),
        "local DailyTrack activation",
    )
    track_id = str(track["id"])
    initial_release_count = len(releases_a["items"])
    stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        profile.actor,
        "--kind",
        "fixture_increment",
        "--new-sessions",
        "1",
        "--idempotency-key",
        f"local-increment-{suffix}",
    )
    poll(
        lambda: request(origin, "/api/v1/dataset-releases", token=token_a),
        lambda value: len(value.get("items", [])) > initial_release_count,
        "local Dataset Publication increment",
    )
    advanced = poll(
        lambda: request(origin, f"/api/v1/daily-tracks/{track_id}", token=token_a),
        lambda value: any(
            item.get("status") == "succeeded" for item in value.get("advances", [])
        ),
        "local DailyTrack Advance",
        terminal_failure=lambda value: any(
            item.get("status") == "failed" for item in value.get("advances", [])
        ),
    )
    advance_id = str(advanced["advances"][-1]["id"])
    equivalence = require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{track_id}/equivalence-requests",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"local-equivalence-{suffix}"},
        ),
        202,
        "local Batch-Incremental Equivalence request",
    )
    equivalence_id = str(equivalence["id"])
    poll(
        lambda: request(
            origin,
            f"/api/v1/daily-tracks/{track_id}/equivalence-requests/{equivalence_id}",
            token=token_a,
        ),
        lambda value: value.get("status") == "succeeded",
        "local Batch-Incremental Equivalence",
    )
    current = require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{track_id}/current?limit=1",
            token=token_a,
        ),
        200,
        "local bounded DailyTrack view",
    )
    if current.get("window", {}).get("maximum_sessions") != 1:
        raise AcceptanceFailure("local DailyTrack view ignored the requested bound")

    assert_cross_workspace_denial(
        origin,
        token_b,
        foreign_workspace_id=workspace_a,
        draft_id=str(draft_a["id"]),
        run_id=run_id,
        track_id=track_id,
        advance_id=advance_id,
        suffix=suffix,
    )
    stack(
        "operator",
        "quota",
        "override",
        "--actor",
        profile.actor,
        "--workspace-id",
        workspace_a,
        "--max-active-daily-tracks",
        "1",
    )
    quota = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"local-quota-track-{suffix}"},
        ),
        409,
        "local DailyTrack quota",
    )
    if quota.get("detail", {}).get("dimension") != "max_active_daily_tracks":
        raise AcceptanceFailure("local quota rejection lost its bounded dimension")
    require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{track_id}/stop",
            method="POST",
            token=token_a,
        ),
        200,
        "retained local DailyTrack stop",
    )

    tombstone_run = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/rerun",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"local-tombstone-run-{suffix}"},
        ),
        (200, 202),
        "local Tombstone probe run",
    )
    tombstone_run_id = require_resource_id(tombstone_run, "local Tombstone probe run")
    repeated_tombstone_run = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/rerun",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"local-tombstone-run-{suffix}"},
        ),
        (200, 202),
        "idempotent local Tombstone probe rerun",
    )
    if require_resource_id(
        repeated_tombstone_run,
        "idempotent local Tombstone probe rerun",
    ) != tombstone_run_id:
        raise AcceptanceFailure("local rerun idempotency created a duplicate ResearchRun")
    poll(
        lambda: request(
            origin,
            f"/api/v1/research-runs/{tombstone_run_id}",
            token=token_a,
        ),
        lambda value: value.get("status") == "succeeded",
        "local Tombstone probe ResearchRun",
    )
    tombstone_track = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{tombstone_run_id}/daily-tracks",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"local-tombstone-track-{suffix}"},
        ),
        (200, 201),
        "local Tombstone probe DailyTrack",
    )
    tombstone_track_id = str(tombstone_track["id"])
    require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{tombstone_track_id}/stop",
            method="POST",
            token=token_a,
        ),
        200,
        "local Tombstone probe stop",
    )
    require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{tombstone_track_id}",
            method="DELETE",
            token=token_a,
        ),
        202,
        "local DailyTrack Tombstone",
    )
    require_status(
        request(
            origin,
            f"/api/v1/research-runs/{tombstone_run_id}",
            method="DELETE",
            token=token_a,
        ),
        202,
        "local ResearchRun Tombstone",
    )
    for path in (
        f"/api/v1/daily-tracks/{tombstone_track_id}",
        f"/api/v1/research-runs/{tombstone_run_id}",
    ):
        status, _payload = request(origin, path, token=token_a)
        if status != 404:
            raise AcceptanceFailure(f"local deleted resource remained reachable: {path}")
    for path in (
        f"/api/v1/objects/{'a' * 64}",
        "/api/storage/acceptance",
        "/storage/acceptance",
        "/storage/nested/acceptance",
        "/storage/%2e%2e/acceptance",
        "/storage/v1/object/sign/acceptance",
    ):
        status, _payload = request(origin, path, token=token_a)
        if status != 404:
            raise AcceptanceFailure(f"raw or signed local Storage route is reachable: {path}")

    evidence = _local_gate_evidence(
        "identity-product",
        two_users=True,
        personal_workspaces=2,
        shared_release_id=release_id,
        bounded_result=True,
        bounded_time_series=True,
        quota=True,
        tombstones=True,
        deleted_resources_inaccessible=True,
        raw_storage_absent=True,
        equivalence_retained=True,
        cross_workspace_operations=16,
        reused=False,
    )
    write_local_acceptance_context(
        state_dir,
        {
            "email_a": email_a,
            "password_a": password_a,
            "email_b": email_b,
            "password_b": password_b,
        },
        {
            "suffix": suffix,
            "workspace_a": workspace_a,
            "workspace_b": workspace_b,
            "release_id": release_id,
            "draft_a_id": str(draft_a["id"]),
            "run_id": run_id,
            "track_id": track_id,
            "advance_id": advance_id,
            "equivalence_id": equivalence_id,
            "tombstone_run_id": tombstone_run_id,
            "tombstone_track_id": tombstone_track_id,
            "identity_evidence": evidence,
        },
    )
    return evidence


def run_local_api_relay_recovery() -> dict[str, object]:
    origin = _local_origin()
    token_a, _token_b, credentials, product = _fresh_local_logins()
    run_id = _required_text(product, "run_id")
    suffix = _required_text(product, "suffix")
    rerun_key = f"local-api-relay-{suffix}"

    def attempt(token: str) -> tuple[int, dict[str, object]]:
        try:
            return request(
                origin,
                f"/api/v1/research-runs/{run_id}/rerun",
                method="POST",
                token=token,
                headers={"Idempotency-Key": rerun_key},
            )
        except urllib.error.URLError:
            return 0, {}

    for service in ("compute-worker-1", "execution-relay"):
        stack("acceptance-stop-service", service)
    try:
        stack("acceptance-stop-service", "api")
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                unavailable = list(pool.map(lambda _index: attempt(token_a), range(2)))
        finally:
            stack("acceptance-start-service", "api")
        if any(status != 0 and status < 500 for status, _payload in unavailable):
            raise AcceptanceFailure(
                f"API accepted a request while explicitly unavailable: {unavailable}"
            )
        poll(
            lambda: request(origin, "/api/v1/session", token=token_a),
            lambda value: bool(value.get("workspace_id")),
            "local API recovery",
        )
        token_a = login_user(
            _required_text(credentials, "email_a"),
            _required_text(credentials, "password_a"),
            origin,
            label="User A login after local API recovery",
        )
        with ThreadPoolExecutor(max_workers=3) as pool:
            admitted = list(pool.map(lambda _index: attempt(token_a), range(3)))
        accepted = [
            require_status(response, (200, 202), "concurrent idempotent API recovery")
            for response in admitted
        ]
        recovery_ids = {
            require_resource_id(value, "concurrent idempotent API recovery")
            for value in accepted
        }
        if len(recovery_ids) != 1:
            raise AcceptanceFailure("concurrent API recovery created duplicate ResearchRuns")
        recovery_run_id = recovery_ids.pop()
        queued = require_status(
            request(origin, f"/api/v1/research-runs/{recovery_run_id}", token=token_a),
            200,
            "ResearchRun queued behind stopped relay",
        )
        if queued.get("status") != "queued":
            raise AcceptanceFailure("ResearchRun escaped the durable outbox while relay was down")
        assert_single_resource(
            origin,
            token_a,
            "/api/v1/research-runs",
            recovery_run_id,
            "local API/relay ResearchRun",
        )
        stack("acceptance-start-service", "execution-relay")
        stack("acceptance-start-service", "compute-worker-1")
        recovered = poll(
            lambda: request(
                origin,
                f"/api/v1/research-runs/{recovery_run_id}",
                token=token_a,
            ),
            lambda value: value.get("status") == "succeeded",
            "local outbox relay recovery",
            timeout=300,
        )
        attempts = recovered.get("attempts")
        if not isinstance(attempts, list) or len(attempts) != 1:
            raise AcceptanceFailure("API/relay recovery did not execute exactly one Attempt")
        require_status(
            request(
                origin,
                f"/api/v1/research-runs/{recovery_run_id}/result?daily_limit=1",
                token=token_a,
            ),
            200,
            "local API/relay recovered result",
        )
    finally:
        for service in ("api", "execution-relay", "compute-worker-1"):
            stack("acceptance-start-service", service)

    _update_local_product_context(api_relay_run_id=recovery_run_id)
    return _local_gate_evidence(
        "api-relay-recovery",
        api_unavailable=True,
        concurrent_idempotency=True,
        durable_outbox=True,
        exactly_one_workflow=True,
        exactly_one_result=True,
    )


def run_public_origin_acceptance(
    profile_name: str = "launch",
) -> dict[str, object]:
    profile = acceptance_profile(profile_name)
    origin = os.environ.get("THESISTRACE_HOSTED_ORIGIN")
    if not origin:
        raise SystemExit("THESISTRACE_HOSTED_ORIGIN is required")
    suffix = uuid4().hex
    email_a = f"release-a-{suffix}@example.invalid"
    email_b = f"release-b-{suffix}@example.invalid"
    password_a = f"Release-A-{suffix[:12]}!9"
    password_b = f"Release-B-{suffix[:12]}!9"

    stack("acceptance-assert-clean")

    blocked = stack(
        "operator",
        "invitation",
        "issue",
        "--actor",
        profile.actor,
        "--email",
        f"blocked-{suffix}@example.invalid",
        "--expires-at",
        "2099-01-01T00:00:00Z",
        expect=2,
    )
    if blocked.get("reason_code") != profile.invitation_gate_reason:
        raise AcceptanceFailure(
            f"closed invitation gate was not enforced for {profile.name}: {blocked}"
        )

    stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        profile.actor,
        "--kind",
        "fixture_bootstrap",
        "--idempotency-key",
        f"release-bootstrap-{suffix}",
    )
    token_a, workspace_a = seed_user(email_a, password_a, origin)
    token_b, workspace_b = seed_user(email_b, password_b, origin)
    token_a = password_recovery(origin, email_a, password_a)

    releases_a = poll(
        lambda: request(origin, "/api/v1/dataset-releases", token=token_a),
        lambda value: bool(value.get("items")),
        "shared Dataset Release publication",
    )
    releases_b = require_status(
        request(origin, "/api/v1/dataset-releases", token=token_b),
        200,
        "second User Dataset Release view",
    )
    if releases_a != releases_b:
        raise AcceptanceFailure("Users did not receive the same shared Dataset Release view")
    release_id = str(releases_a["items"][-1]["id"])
    contract_a = require_status(
        request(
            origin,
            f"/api/v1/dataset-releases/{release_id}/data-contract",
            token=token_a,
        ),
        200,
        "first shared data contract",
    )
    contract_b = require_status(
        request(
            origin,
            f"/api/v1/dataset-releases/{release_id}/data-contract",
            token=token_b,
        ),
        200,
        "second shared data contract",
    )
    if contract_a != contract_b:
        raise AcceptanceFailure("shared Dataset contract differed by User")

    draft_a = require_status(
        request(
            origin,
            "/api/v1/research-definitions",
            method="POST",
            body=definition("Release boundary A"),
            token=token_a,
        ),
        201,
        "User A draft creation",
    )
    require_status(
        request(
            origin,
            "/api/v1/research-definitions",
            method="POST",
            body=definition("Release boundary B"),
            token=token_b,
        ),
        201,
        "User B draft creation",
    )
    run_response = require_status(
        request(
            origin,
            f"/api/v1/research-definitions/{draft_a['id']}/runs",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"release-run-{suffix}"},
        ),
        202,
        "research run request",
    )
    run_id = str(run_response["run"]["id"])
    run = poll(
        lambda: request(origin, f"/api/v1/research-runs/{run_id}", token=token_a),
        lambda value: value.get("status") == "succeeded",
        "ResearchRun",
    )
    if "result_manifest_sha256" in run:
        raise AcceptanceFailure("hosted ResearchRun disclosed its storage identity")
    result = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/result?daily_limit=1&position_limit=1",
            token=token_a,
        ),
        200,
        "bounded Result Bundle",
    )
    daily = result.get("strategy_backtest", {}).get("daily", [])
    positions = result.get("terminal_strategy_state", {}).get("positions", [])
    if len(daily) > 1 or len(positions) > 1:
        raise AcceptanceFailure("hosted Result Bundle ignored bounded view limits")
    serialized_result = json.dumps(result, sort_keys=True).casefold()
    if any(term in serialized_result for term in ("manifest_sha256", "signed_url")):
        raise AcceptanceFailure("hosted Result Bundle disclosed raw storage metadata")

    track = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"release-track-{suffix}"},
        ),
        (200, 201),
        "DailyTrack activation",
    )
    track_id = str(track["id"])
    initial_release_count = len(releases_a["items"])
    stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        profile.actor,
        "--kind",
        "fixture_increment",
        "--new-sessions",
        "1",
        "--idempotency-key",
        f"release-increment-{suffix}",
    )
    poll(
        lambda: request(origin, "/api/v1/dataset-releases", token=token_a),
        lambda value: len(value.get("items", [])) > initial_release_count,
        "Dataset Publication increment",
    )
    advanced = poll(
        lambda: request(origin, f"/api/v1/daily-tracks/{track_id}", token=token_a),
        lambda value: any(
            item.get("status") == "succeeded" for item in value.get("advances", [])
        ),
        "DailyTrack Advance",
        terminal_failure=lambda value: any(
            item.get("status") == "failed" for item in value.get("advances", [])
        ),
    )
    advance_id = str(advanced["advances"][-1]["id"])

    equivalence = require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{track_id}/equivalence-requests",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"release-equivalence-{suffix}"},
        ),
        202,
        "Batch-Incremental Equivalence request",
    )
    equivalence_id = str(equivalence["id"])
    poll(
        lambda: request(
            origin,
            f"/api/v1/daily-tracks/{track_id}"
            f"/equivalence-requests/{equivalence_id}",
            token=token_a,
        ),
        lambda value: value.get("status") == "succeeded",
        "Batch-Incremental Equivalence",
    )

    current = require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{track_id}/current?limit=1",
            token=token_a,
        ),
        200,
        "bounded DailyTrack time-series view",
    )
    strategy = current.get("strategy")
    window = current.get("window")
    if not isinstance(strategy, dict) or not isinstance(window, dict):
        raise AcceptanceFailure("DailyTrack current view is incomplete")
    for key in ("daily", "rebalance_aggregates", "execution_aggregates"):
        rows = strategy.get(key)
        if not isinstance(rows, list) or len(rows) > 1:
            raise AcceptanceFailure(f"DailyTrack {key} ignored the requested limit")
    if window.get("maximum_sessions") != 1 or window.get("returned_sessions") != 1:
        raise AcceptanceFailure("DailyTrack time-series window is not bounded")
    serialized_current = json.dumps(current, sort_keys=True).casefold()
    if any(term in serialized_current for term in ("manifest_sha256", "signed_url")):
        raise AcceptanceFailure("DailyTrack current view disclosed raw storage metadata")

    interruption_matrix, recovery_run_id = (
        run_recovery_interruption_matrix(
            origin,
            token_a,
            run_id=run_id,
            track_id=track_id,
            suffix=suffix,
            profile_name=profile.name,
            token_refresher=lambda: login_user(
                email_a,
                f"{password_a}-reset",
                origin,
                label="User A login inside recovery matrix",
            ),
        )
    )

    token_a = login_user(
        email_a,
        f"{password_a}-reset",
        origin,
        label="User A login after recovery matrix",
    )
    token_b = login_user(
        email_b,
        password_b,
        origin,
        label="User B login after recovery matrix",
    )
    for label, token, workspace_id in (
        ("User A session after recovery matrix", token_a, workspace_a),
        ("User B session after recovery matrix", token_b, workspace_b),
    ):
        refreshed_session = require_status(
            request(origin, "/api/v1/session", token=token),
            200,
            label,
        )
        if refreshed_session.get("workspace_id") != workspace_id:
            raise AcceptanceFailure(f"{label} resolved a different Workspace")

    assert_cross_workspace_denial(
        origin,
        token_b,
        foreign_workspace_id=workspace_a,
        draft_id=str(draft_a["id"]),
        run_id=run_id,
        track_id=track_id,
        advance_id=advance_id,
        suffix=suffix,
    )
    if profile.backup_and_three_health_planes:
        stack("backup")
        wait_for_three_health_planes()

    stack(
        "operator",
        "quota",
        "override",
        "--actor",
        profile.actor,
        "--workspace-id",
        workspace_a,
        "--max-active-daily-tracks",
        "1",
    )
    quota = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"quota-track-{suffix}"},
        ),
        409,
        "DailyTrack quota",
    )
    if quota.get("detail", {}).get("dimension") != "max_active_daily_tracks":
        raise AcceptanceFailure("quota rejection lost its bounded dimension")

    require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{track_id}/stop",
            method="POST",
            token=token_a,
        ),
        200,
        "DailyTrack stop",
    )
    tombstone_track = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{recovery_run_id}/daily-tracks",
            method="POST",
            token=token_a,
            headers={"Idempotency-Key": f"tombstone-track-{suffix}"},
        ),
        (200, 201),
        "DailyTrack Tombstone probe activation",
    )
    tombstone_track_id = str(tombstone_track["id"])
    require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{tombstone_track_id}/stop",
            method="POST",
            token=token_a,
        ),
        200,
        "DailyTrack Tombstone probe stop",
    )
    track_tombstone = require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{tombstone_track_id}",
            method="DELETE",
            token=token_a,
        ),
        202,
        "DailyTrack Tombstone",
    )
    if track_tombstone.get("resource_kind") != "daily_track":
        raise AcceptanceFailure("DailyTrack deletion returned no Tombstone view")
    run_tombstone = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{recovery_run_id}",
            method="DELETE",
            token=token_a,
        ),
        202,
        "ResearchRun Tombstone",
    )
    if run_tombstone.get("resource_kind") != "research_run":
        raise AcceptanceFailure("ResearchRun deletion returned no Tombstone view")

    for path in (
        f"/api/v1/daily-tracks/{tombstone_track_id}",
        f"/api/v1/daily-tracks/{tombstone_track_id}/current",
        f"/api/v1/research-runs/{recovery_run_id}",
        f"/api/v1/research-runs/{recovery_run_id}/result",
    ):
        status, payload = request(origin, path, token=token_a)
        if status != 404:
            raise AcceptanceFailure(
                f"deleted resource remained reachable: {path}: {status} {payload}"
            )

    for path in (
        f"/api/v1/objects/{'a' * 64}",
        "/api/storage/acceptance",
        "/storage/v1/object/sign/acceptance",
    ):
        status, _payload = request(origin, path, token=token_a)
        if status != 404:
            raise AcceptanceFailure(f"raw or signed Storage route is reachable: {path}")

    return {
        "status": "passed",
        "schema_version": (
            "hosted-public-origin-acceptance-v1"
            if profile.name == "launch"
            else "hosted-local-public-origin-v1"
        ),
        "profile": profile.name,
        "two_users": True,
        "personal_workspaces": 2,
        "shared_release_id": release_id,
        "cross_workspace_operations": 16,
        "bounded_result": True,
        "bounded_time_series": True,
        "quota": True,
        "tombstones": True,
        "deleted_resources_inaccessible": True,
        "raw_storage_absent": True,
        "three_health_planes": profile.backup_and_three_health_planes,
        "interruption_matrix": interruption_matrix,
    }


def main() -> None:
    print(json.dumps(run_public_origin_acceptance("launch"), sort_keys=True))


if __name__ == "__main__":
    main()

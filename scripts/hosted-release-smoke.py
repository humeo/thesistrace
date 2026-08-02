import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "scripts" / "hosted-stack"
VERIFY_CODE = "471025"
RESET_CODE = "830614"


class AcceptanceFailure(RuntimeError):
    pass


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
            payload = json.load(response)
            return response.status, payload
    except urllib.error.HTTPError as error:
        try:
            payload = json.load(error)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
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


def poll(
    operation,
    predicate,
    label: str,
    *,
    timeout: float = 900,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        status, last = operation()
        if status == 200 and predicate(last):
            return last
        time.sleep(2)
    raise AcceptanceFailure(f"{label} did not converge: {last}")


def register_user(email: str, password: str, origin: str) -> tuple[str, str]:
    anon_key_payload = require_status(
        request(origin, "/api/auth/anon-key"),
        200,
        "public anon key",
    )
    anon_key = anon_key_payload.get("anonKey")
    if not isinstance(anon_key, str) or not anon_key.startswith("anon_"):
        raise AcceptanceFailure("public anon key was missing or malformed")

    registration = require_status(
        request(
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
    verified = require_status(
        request(
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

    first = require_status(
        request(origin, "/api/v1/provision", method="POST", token=token),
        201,
        "first provisioning",
    )
    second = require_status(
        request(origin, "/api/v1/provision", method="POST", token=token),
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
    list_paths = (
        "/api/v1/research-definitions",
        "/api/v1/research-runs",
        "/api/v1/daily-tracks",
    )
    for path in list_paths:
        payload = require_status(request(origin, path, token=token), 200, path)
        if payload.get("items"):
            raise AcceptanceFailure(f"cross-Workspace list disclosed data: {path}")

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
    require_status(
        request(
            origin,
            "/api/auth/email/send-reset-password",
            method="POST",
            body={"email": f"unknown-{uuid4().hex}@example.invalid"},
        ),
        202,
        "non-disclosing reset request",
    )
    stack("acceptance-seed-otp", email, "RESET_PASSWORD", RESET_CODE)
    exchanged = require_status(
        request(
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
    require_status(
        request(
            origin,
            "/api/auth/email/reset-password",
            method="POST",
            body={"newPassword": new_password, "otp": reset_token},
        ),
        200,
        "password reset",
    )
    logged_in = require_status(
        request(
            origin,
            "/api/auth/sessions?client_type=server",
            method="POST",
            body={"email": email, "password": new_password},
        ),
        200,
        "login after password reset",
    )
    token = logged_in.get("accessToken")
    if not isinstance(token, str):
        raise AcceptanceFailure("login after password reset returned no token")
    return token


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


def run_recovery_interruption_matrix(
    origin: str,
    token: str,
    *,
    run_id: str,
    track_id: str,
    suffix: str,
) -> dict[str, bool]:
    compute_services = tuple(f"compute-worker-{index}" for index in range(1, 5))
    for service in compute_services:
        stack("acceptance-stop-service", service)
    stack("acceptance-stop-service", "execution-relay")
    rerun_key = f"recovery-rerun-{suffix}"

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

    with ThreadPoolExecutor(max_workers=8) as executor:
        attempts = [executor.submit(attempt_rerun) for _index in range(8)]
        time.sleep(0.01)
        stack("acceptance-stop-service", "api")
        stack("acceptance-start-service", "api")
        api_results = [attempt.result() for attempt in attempts]
    if not any(status == 0 or status >= 500 for status, _payload in api_results):
        raise AcceptanceFailure(
            f"no in-flight API request crossed the interruption: {api_results}"
        )
    poll(
        lambda: request(origin, "/api/v1/session", token=token),
        lambda value: bool(value.get("workspace_id")),
        "API recovery",
    )
    rerun = require_status(
        attempt_rerun(),
        (200, 202),
        "idempotent API recovery",
    )
    recovery_run_id = str(rerun["run"]["id"])
    repeated_rerun = require_status(
        request(
            origin,
            f"/api/v1/research-runs/{run_id}/rerun",
            method="POST",
            token=token,
            headers={"Idempotency-Key": rerun_key},
        ),
        200,
        "idempotent outbox ResearchRun",
    )
    if repeated_rerun.get("run", {}).get("id") != recovery_run_id:
        raise AcceptanceFailure("outbox retry created a duplicate ResearchRun")
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
    stack("acceptance-start-service", "compute-worker-1")
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
            stack("acceptance-stop-service", "compute-worker-1")
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
    stack("acceptance-stop-service", "data-worker")
    publication_key = f"recovery-publication-{suffix}"
    publication = stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        "release-acceptance",
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
        "release-acceptance",
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
    stack("acceptance-start-service", "data-worker")
    publication_running = wait_for_publication_status(
        publication_id,
        {"running", "succeeded", "failed", "cancelled"},
    )
    if publication_running.get("status") != "running":
        raise AcceptanceFailure(
            "Dataset Publication completed before its Data Worker was interrupted"
        )
    stack("acceptance-stop-service", "data-worker")
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
    return {
        "api": True,
        "outbox_relay": True,
        "temporal_worker": True,
        "activity": True,
        "publication": True,
        "maintenance": True,
        "node": True,
        "no_duplicate_domain_result": True,
        "no_partial_authoritative_artifact": True,
    }


def main() -> None:
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
        "release-acceptance",
        "--email",
        f"blocked-{suffix}@example.invalid",
        "--expires-at",
        "2099-01-01T00:00:00Z",
        expect=2,
    )
    if blocked.get("reason_code") != "LAUNCH_QUALIFICATION_REQUIRED":
        raise AcceptanceFailure(f"launch-closed invitation gate was not enforced: {blocked}")

    stack(
        "operator",
        "dataset-publication",
        "request",
        "--actor",
        "release-acceptance",
        "--kind",
        "fixture_bootstrap",
        "--idempotency-key",
        f"release-bootstrap-{suffix}",
    )
    token_a, workspace_a = seed_user(email_a, password_a, origin)
    token_b, _workspace_b = seed_user(email_b, password_b, origin)
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
        "release-acceptance",
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

    interruption_matrix = run_recovery_interruption_matrix(
        origin,
        token_a,
        run_id=run_id,
        track_id=track_id,
        suffix=suffix,
    )

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
    stack("backup")
    wait_for_three_health_planes()

    stack(
        "operator",
        "quota",
        "override",
        "--actor",
        "release-acceptance",
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
    track_tombstone = require_status(
        request(
            origin,
            f"/api/v1/daily-tracks/{track_id}",
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
            f"/api/v1/research-runs/{run_id}",
            method="DELETE",
            token=token_a,
        ),
        202,
        "ResearchRun Tombstone",
    )
    if run_tombstone.get("resource_kind") != "research_run":
        raise AcceptanceFailure("ResearchRun deletion returned no Tombstone view")

    for path in (
        f"/api/v1/daily-tracks/{track_id}",
        f"/api/v1/daily-tracks/{track_id}/current",
        f"/api/v1/research-runs/{run_id}",
        f"/api/v1/research-runs/{run_id}/result",
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

    print(
        json.dumps(
            {
                "status": "passed",
                "schema_version": "hosted-public-origin-acceptance-v1",
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
                "three_health_planes": True,
                "interruption_matrix": interruption_matrix,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from threading import Event
from time import monotonic
from urllib.parse import unquote

import httpx

_INVITATION_TOKEN = re.compile(r"#token=([^\"'<\s]+)")


@dataclass(frozen=True)
class LiveLoginSession:
    cookie: str
    email: str
    researcher_id: str


def create_live_login_session(
    email: str,
    *,
    password: str = "correct-horse-battery-staple",
) -> LiveLoginSession:
    auth_origin, resend_origin, public_origin = _origins()
    with httpx.Client(timeout=5) as client:
        cleared = client.delete(f"{resend_origin}/__test/emails")
        if cleared.status_code != 200:
            raise AssertionError(f"Resend fake clear failed: HTTP {cleared.status_code}")
        run_auth_operator("invite", "--email", email)
        token = _await_invitation_token(client, resend_origin)
        accepted = client.post(
            f"{auth_origin}/api/auth/researcher-invitation/accept",
            headers={
                "origin": public_origin,
                "x-thesistrace-client-ip": "127.0.0.1",
            },
            json={"token": token, "password": password},
        )
    if accepted.status_code != 200:
        raise AssertionError(f"Invitation accept failed: HTTP {accepted.status_code}")
    cookie = _request_cookie(accepted.headers.get_list("set-cookie"))
    if not cookie:
        raise AssertionError("Invitation accept did not establish a Login Session")
    with httpx.Client(timeout=5) as client:
        verified = client.post(
            f"{auth_origin}/internal/session/verify",
            headers={"cookie": cookie},
        )
    if verified.status_code != 200:
        raise AssertionError(f"Session verification failed: HTTP {verified.status_code}")
    body = verified.json()
    researcher_id = body.get("researcher_id") if isinstance(body, dict) else None
    if not isinstance(researcher_id, str):
        raise AssertionError("Session verification returned an invalid Researcher")
    return LiveLoginSession(
        cookie=cookie,
        email=email,
        researcher_id=researcher_id,
    )


def create_private_compose_login_session(email: str) -> LiveLoginSession:
    container = _service_container("auth")
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "node",
            "/test-fixtures/provision-image-smoke-session.mjs",
            email,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"private Compose Session provisioning failed with exit {result.returncode}"
        )
    try:
        body = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            "private Compose Session provisioning returned invalid JSON"
        ) from error
    if not isinstance(body, dict) or set(body) != {"cookie", "researcher_id"}:
        raise AssertionError("private Compose Session provisioning returned invalid fields")
    cookie = body["cookie"]
    researcher_id = body["researcher_id"]
    if not isinstance(cookie, str) or not cookie:
        raise AssertionError("private Compose Session provisioning returned no Cookie")
    if not isinstance(researcher_id, str) or not researcher_id:
        raise AssertionError("private Compose Session provisioning returned no Researcher")
    return LiveLoginSession(cookie=cookie, email=email, researcher_id=researcher_id)


def run_auth_operator(*arguments: str) -> dict[str, object]:
    container = _service_container("auth")
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "node",
            "dist/operator.js",
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(f"Auth operator failed with exit {result.returncode}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise AssertionError("Auth operator returned an invalid result")
    return value


def _origins() -> tuple[str, str, str]:
    values = tuple(
        os.environ.get(name, "").rstrip("/")
        for name in (
            "THESISTRACE_AUTH_INTERNAL_ORIGIN",
            "THESISTRACE_TEST_RESEND_ORIGIN",
            "THESISTRACE_PUBLIC_ORIGIN",
        )
    )
    if not all(values):
        raise RuntimeError("live Auth integration environment is unavailable")
    return values


def _service_container(service: str) -> str:
    project = os.environ.get("THESISTRACE_TEST_PROJECT_NAME", "")
    if not project:
        raise RuntimeError("isolated Test Compose project is unavailable")
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    containers = result.stdout.split()
    if len(containers) != 1:
        raise AssertionError(f"expected one running {service} Test container")
    return containers[0]


def _await_invitation_token(client: httpx.Client, resend_origin: str) -> str:
    deadline = monotonic() + 10
    interval = Event()
    saw_email = False
    while monotonic() < deadline:
        response = client.get(f"{resend_origin}/__test/emails")
        if response.status_code == 200:
            payload = response.json()
            emails = payload.get("emails") if isinstance(payload, dict) else None
            if isinstance(emails, list) and emails:
                saw_email = True
                email = emails[-1]
                html = email.get("html") if isinstance(email, dict) else None
                match = _INVITATION_TOKEN.search(html) if isinstance(html, str) else None
                if match is not None:
                    return unquote(match.group(1))
        interval.wait(0.05)
    if saw_email:
        raise AssertionError("Invitation email contained no valid fragment token")
    raise AssertionError("Invitation email was not delivered")


def _request_cookie(set_cookie_headers: list[str]) -> str:
    values: list[str] = []
    for header in set_cookie_headers:
        name_value = header.split(";", 1)[0].strip()
        if "=" in name_value:
            values.append(name_value)
    return "; ".join(values)

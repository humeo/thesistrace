from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from threading import Event
from time import monotonic, time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

_EMAIL_CODE = re.compile(r"\b[0-9]{6}\b")


@dataclass(frozen=True)
class LiveLoginSession:
    cookie: str
    email: str
    researcher_id: str


def create_live_login_session(email: str) -> LiveLoginSession:
    auth_origin, resend_origin, public_origin = _origins()
    with httpx.Client(timeout=5) as client:
        cleared = client.delete(f"{resend_origin}/__test/emails")
        if cleared.status_code != 200:
            raise AssertionError(f"Resend fake clear failed: HTTP {cleared.status_code}")
        headers = {"origin": public_origin, "x-thesistrace-client-ip": "127.0.0.1"}
        sent = client.post(
            f"{auth_origin}/api/auth/email-otp/send-verification-otp",
            headers=headers,
            json={
                "email": email,
                "type": "sign-in",
                "captcha_token": (
                    f"test-turnstile:{urlsplit(public_origin).hostname}:"
                    f"{int(time() * 1000)}:{uuid4()}"
                ),
            },
        )
        if sent.status_code != 200:
            raise AssertionError(f"Email code delivery failed: HTTP {sent.status_code}")
        otp = _await_email_code(client, resend_origin)
        accepted = client.post(
            f"{auth_origin}/api/auth/sign-in/email-otp",
            headers=headers,
            json={"email": email, "otp": otp},
        )
    if accepted.status_code != 200:
        raise AssertionError(f"Email code sign-in failed: HTTP {accepted.status_code}")
    cookie = _request_cookie(accepted.headers.get_list("set-cookie"))
    if not cookie:
        raise AssertionError("Email code sign-in did not establish a Login Session")
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


def _await_email_code(client: httpx.Client, resend_origin: str) -> str:
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
                text = email.get("text") if isinstance(email, dict) else None
                match = _EMAIL_CODE.search(text) if isinstance(text, str) else None
                if match is not None:
                    return match.group(0)
        interval.wait(0.05)
    if saw_email:
        raise AssertionError("Email contained no valid verification code")
    raise AssertionError("Verification email was not delivered")


def _request_cookie(set_cookie_headers: list[str]) -> str:
    values: list[str] = []
    for header in set_cookie_headers:
        name_value = header.split(";", 1)[0].strip()
        if "=" in name_value:
            values.append(name_value)
    return "; ".join(values)

import json
import os
import ssl
import urllib.error
import urllib.request
from uuid import uuid4

import jwt


def request(
    origin: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
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
                headers=headers,
                method=method,
            ),
            timeout=10,
            context=context,
        ) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            payload = json.load(error)
        except json.JSONDecodeError:
            payload = {}
        return error.code, payload


def main() -> None:
    origin = os.environ.get("THESISTRACE_HOSTED_ORIGIN")
    email = os.environ.get("THESISTRACE_AUTH_SMOKE_EMAIL")
    password = os.environ.get("THESISTRACE_AUTH_SMOKE_PASSWORD")
    if not origin or not email or not password:
        raise SystemExit(
            "THESISTRACE_HOSTED_ORIGIN, THESISTRACE_AUTH_SMOKE_EMAIL, and "
            "THESISTRACE_AUTH_SMOKE_PASSWORD are required"
        )

    anon_status, anon = request(origin, "/api/auth/anon-key")
    if anon_status != 200 or not str(anon.get("anonKey", "")).startswith("anon_"):
        raise SystemExit("public InsForge anon-key bootstrap failed")

    login_status, login = request(
        origin,
        "/api/auth/sessions",
        method="POST",
        body={"email": email, "password": password},
    )
    access_token = login.get("accessToken")
    if login_status != 200 or not isinstance(access_token, str):
        raise SystemExit("public InsForge login failed")

    claims = jwt.decode(
        access_token,
        options={"verify_signature": False},
        algorithms=["RS256"],
    )
    if claims.get("iss") != "insforge" or claims.get("aud") != "thesistrace":
        raise SystemExit("InsForge access token lacks the hosted JWT contract")

    current_status, current = request(
        origin,
        "/api/auth/sessions/current",
        token=access_token,
    )
    if current_status != 200 or current.get("user", {}).get("email") != email:
        raise SystemExit("public InsForge current-session check failed")

    product_status, product = request(
        origin,
        "/api/v1/session",
        token=access_token,
    )
    if product_status != 200 or product.get("product_state") != "non_provisioned":
        raise SystemExit("verified identity did not receive non-provisioned product state")

    recovery_status, _recovery = request(
        origin,
        "/api/auth/email/send-reset-password",
        method="POST",
        body={"email": f"hosted-auth-smoke-{uuid4().hex}@example.invalid"},
    )
    if recovery_status != 202:
        raise SystemExit("public InsForge password-recovery ownership check failed")

    blocked_status, _blocked = request(origin, "/api/auth/config")
    if blocked_status != 404:
        raise SystemExit("non-user InsForge Auth route is publicly reachable")

    print("hosted InsForge authentication smoke passed")


if __name__ == "__main__":
    main()

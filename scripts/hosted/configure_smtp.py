import argparse
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any


class SmtpConfigurationError(RuntimeError):
    pass


Requester = Callable[
    [str, dict[str, object], str | None],
    dict[str, object],
]


def request_json(
    url: str,
    payload: dict[str, object],
    token: str | None = None,
) -> dict[str, object]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    method = "POST" if url.endswith("/admin/sessions") else "PUT"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers=headers,
                method=method,
            ),
            timeout=30,
        ) as response:
            value = json.load(response)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
        raise SmtpConfigurationError(
            f"private InsForge SMTP request failed: {type(error).__name__}"
        ) from error
    if not isinstance(value, dict):
        raise SmtpConfigurationError("private InsForge SMTP response is invalid")
    return value


def _read_secret(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").rstrip("\n")
    except OSError as error:
        raise SmtpConfigurationError(f"cannot read {label}") from error
    if not value:
        raise SmtpConfigurationError(f"{label} is empty")
    return value


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SmtpConfigurationError("SMTP configuration is invalid") from error
    if not isinstance(value, dict):
        raise SmtpConfigurationError("SMTP configuration must be an object")
    required = {
        "enabled",
        "host",
        "port",
        "username",
        "senderEmail",
        "senderName",
        "minIntervalSeconds",
    }
    if set(value) != required or value.get("enabled") is not True:
        raise SmtpConfigurationError(
            "SMTP configuration must contain the enabled production contract"
        )
    if value.get("port") not in {25, 465, 587, 2525}:
        raise SmtpConfigurationError("SMTP port is not supported")
    for name in ("host", "username", "senderEmail", "senderName"):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise SmtpConfigurationError(f"SMTP {name} is required")
    interval = value.get("minIntervalSeconds")
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 0:
        raise SmtpConfigurationError("SMTP minIntervalSeconds is invalid")
    return value


def configure_smtp(
    *,
    config_path: Path,
    smtp_password_path: Path,
    admin_password_path: Path,
    admin_username: str,
    origin: str,
    requester: Requester = request_json,
) -> dict[str, object]:
    config = _read_config(config_path)
    admin_password = _read_secret(admin_password_path, "InsForge admin password")
    smtp_password = _read_secret(smtp_password_path, "SMTP password")
    session = requester(
        f"{origin.rstrip('/')}/api/auth/admin/sessions",
        {"username": admin_username, "password": admin_password},
        None,
    )
    token = session.get("accessToken")
    if not isinstance(token, str) or not token:
        raise SmtpConfigurationError("InsForge admin session returned no token")
    configured = requester(
        f"{origin.rstrip('/')}/api/auth/smtp-config",
        {**config, "password": smtp_password},
        token,
    )
    if (
        configured.get("enabled") is not True
        or configured.get("hasPassword") is not True
        or configured.get("host") != config["host"]
        or configured.get("port") != config["port"]
        or configured.get("senderEmail") != config["senderEmail"]
    ):
        raise SmtpConfigurationError("InsForge did not confirm the SMTP contract")
    return {
        "enabled": True,
        "has_password": True,
        "host": configured["host"],
        "port": configured["port"],
        "sender_email": configured["senderEmail"],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Configure InsForge SMTP through the private control network",
    )
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--smtp-password-file", type=Path, required=True)
    result.add_argument("--admin-password-file", type=Path, required=True)
    result.add_argument("--admin-username", default="admin")
    result.add_argument("--origin", default="http://insforge:7130")
    return result


def main() -> None:
    arguments = parser().parse_args()
    result = configure_smtp(
        config_path=arguments.config,
        smtp_password_path=arguments.smtp_password_file,
        admin_password_path=arguments.admin_password_file,
        admin_username=arguments.admin_username,
        origin=arguments.origin,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except SmtpConfigurationError as error:
        raise SystemExit(str(error)) from error

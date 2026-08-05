#!/usr/bin/env python3
"""Bounded public-origin smoke for the retained Hosted release surface.

Execution recovery belongs to the canonical PostgreSQL workers and is covered
by Core acceptance. This script intentionally checks only the still-retained
public edge and health responses until the remaining Hosted launch machinery
is removed.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request


class AcceptanceFailure(RuntimeError):
    pass


def request_json(origin: str, path: str) -> dict[str, object]:
    request = urllib.request.Request(f"{origin.rstrip('/')}{path}")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AcceptanceFailure(f"public-origin request failed for {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AcceptanceFailure(f"public-origin response is not an object: {path}")
    return payload


def run_public_origin_acceptance() -> dict[str, object]:
    origin = os.environ.get("THESISTRACE_HOSTED_ORIGIN", "").strip()
    if not origin:
        raise AcceptanceFailure("THESISTRACE_HOSTED_ORIGIN is required")
    ready = request_json(origin, "/ready")
    if ready.get("status") not in {"ok", "ready"}:
        raise AcceptanceFailure(f"public origin is not ready: {ready}")
    return {
        "status": "passed",
        "public_origin_ready": True,
    }


def main() -> None:
    print(json.dumps(run_public_origin_acceptance(), sort_keys=True))


if __name__ == "__main__":
    main()

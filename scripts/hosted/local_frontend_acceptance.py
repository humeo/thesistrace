#!/usr/bin/env python3
import hashlib
import json
import os
import re
import ssl
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
STACK = ROOT / "scripts" / "hosted-stack"


class FrontendAcceptanceError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        output = f"{completed.stdout}\n{completed.stderr}"[-8000:]
        raise FrontendAcceptanceError(
            f"frontend command failed ({completed.returncode}): {' '.join(command)}\n{output}"
        )


def fetch(origin: str, path: str) -> bytes:
    context = (
        ssl._create_unverified_context()
        if origin.startswith("https://")
        and os.environ.get("THESISTRACE_SMOKE_INSECURE_TLS") == "1"
        else None
    )
    with urllib.request.urlopen(
        f"{origin.rstrip('/')}{path}", timeout=30, context=context
    ) as response:
        if response.status != 200:
            raise FrontendAcceptanceError(
                f"staged Web asset {path} returned {response.status}"
            )
        return response.read()


def asset_paths(index: bytes) -> tuple[str, ...]:
    decoded = index.decode("utf-8")
    paths = {
        match
        for match in re.findall(r'''(?:src|href)=["'](/assets/[^"']+)["']''', decoded)
    }
    if not paths:
        raise FrontendAcceptanceError("reproducibility build emitted no Web assets")
    return tuple(sorted(paths))


def verify_staged_assets(origin: str) -> dict[str, str]:
    distribution = WEB / "dist"
    local_index = (distribution / "index.html").read_bytes()
    served_index = fetch(origin, "/")
    if served_index != local_index:
        raise FrontendAcceptanceError(
            "served index.html differs from the isolated reproducibility build"
        )
    manifest = {"/": hashlib.sha256(served_index).hexdigest()}
    for asset_path in asset_paths(local_index):
        local_path = distribution / asset_path.removeprefix("/")
        if not local_path.is_file():
            raise FrontendAcceptanceError(f"built Web asset is missing: {asset_path}")
        served = fetch(origin, asset_path)
        local = local_path.read_bytes()
        if served != local:
            raise FrontendAcceptanceError(
                f"served Web asset differs from reproducibility build: {asset_path}"
            )
        manifest[asset_path] = hashlib.sha256(served).hexdigest()
    return manifest


def main() -> None:
    state_value = os.environ.get("THESISTRACE_HOST_STATE_DIR")
    origin = os.environ.get("THESISTRACE_HOSTED_ORIGIN")
    if not state_value or not origin:
        raise FrontendAcceptanceError(
            "THESISTRACE_HOST_STATE_DIR and THESISTRACE_HOSTED_ORIGIN are required"
        )
    state_dir = Path(state_value).resolve()
    release_root = state_dir / "releases"
    current_path = release_root / "current.json"
    try:
        current = json.loads(current_path.read_text())
        bundle_id = str(current["bundle_id"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise FrontendAcceptanceError("the staged Release Bundle is unavailable") from error
    image_lock = release_root / "bundles" / bundle_id / "image-lock.json"
    pointer_before = sha256(current_path)
    lock_before = sha256(image_lock)

    run(["bun", "install", "--frozen-lockfile"], cwd=WEB)
    run(["bun", "run", "typecheck"], cwd=WEB)
    run(["bun", "run", "build"], cwd=WEB)
    assets = verify_staged_assets(origin)
    if sha256(current_path) != pointer_before:
        raise FrontendAcceptanceError("the active Release pointer changed during Web proof")
    if sha256(image_lock) != lock_before:
        raise FrontendAcceptanceError("the immutable image lock changed during Web proof")

    browser_evidence = state_dir / "browser-evidence.json"
    screenshots = state_dir / "browser-screenshots"
    environment = {
        **os.environ,
        "THESISTRACE_HOSTED_STACK": str(STACK),
        "THESISTRACE_HOSTED_BROWSER_EVIDENCE": str(browser_evidence),
        "THESISTRACE_HOSTED_BROWSER_SCREENSHOTS": str(screenshots),
    }
    completed = subprocess.run(
        ["bun", "run", "test:e2e:hosted"],
        cwd=WEB,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        output = f"{completed.stdout}\n{completed.stderr}"[-8000:]
        raise FrontendAcceptanceError(
            f"Hosted browser flow failed ({completed.returncode}):\n{output}"
        )
    try:
        browser = json.loads(browser_evidence.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise FrontendAcceptanceError("Hosted browser evidence is unavailable") from error
    if browser.get("status") != "passed":
        raise FrontendAcceptanceError("Hosted browser evidence did not pass")

    dependency_lock = WEB / "bun.lock"
    payload = {
        "status": "passed",
        "schema_version": "hosted-local-frontend-v1",
        "release_bundle_id": bundle_id,
        "image_lock_sha256": lock_before,
        "dependency_lock_sha256": sha256(dependency_lock),
        "web_asset_manifest": assets,
        "browser_evidence": str(browser_evidence),
        "screenshots": str(screenshots),
        "active_release_mutated": False,
        "fault_injected": False,
        "not_claimed": [
            "cloudflare",
            "external_dns_tls",
            "production_invitation_admission",
            "production_launch",
            "real_smtp_delivery",
        ],
    }
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()

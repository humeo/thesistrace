from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _configure(path: Path, action: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", ROOT / "tooling/config/cli.mjs", action],
        env={**os.environ, "THESISTRACE_ENV_FILE": str(path), **overrides},
        capture_output=True,
        text=True,
        check=False,
    )


def development_environment(path: Path) -> dict[str, str]:
    initialized = _configure(path, "init")
    assert initialized.returncode == 0, initialized.stderr
    source = path.read_text()
    for key, value in {
        "THESISTRACE_TURNSTILE_SITE_KEY": "1x00000000000000000000AA",
        "THESISTRACE_TURNSTILE_SECRET_KEY": "1x0000000000000000000000000000000AA",
        "RESEND_API_KEY": "re_fixture-configuration-only-12345",
        "RESEND_FROM_EMAIL": "ThesisTrace <noreply@fixture.test>",
        "THESISTRACE_TUSHARE_TOKEN": "fixture-configuration-only-12345",
        "THESISTRACE_AGENT_OPENAI_API_KEY": "fixture-model-configuration-only-12345",
    }.items():
        source = source.replace(f"{key}=\n", f"{key}={value}\n")
    path.write_text(source)
    return {**os.environ, "THESISTRACE_ENV_FILE": str(path)}

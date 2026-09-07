from __future__ import annotations

import json
import subprocess
from pathlib import Path

from runtime_configuration_fixtures import _configure, development_environment

ROOT = Path(__file__).resolve().parents[3]


def test_configuration_init_generates_private_local_identity_without_overwriting(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "first.env", tmp_path / "second.env"
    for path in (first, second):
        result = _configure(path, "init")
        assert result.returncode == 0, result.stderr
        assert path.stat().st_mode & 0o777 == 0o600
    original = first.read_bytes()
    values = dict(
        line.split("=", 1)
        for line in original.decode().splitlines()
        if line and not line.startswith("#")
    )
    assert json.loads(values["THESISTRACE_MCP_SIGNING_PRIVATE_JWK"])["d"]
    assert values["THESISTRACE_TUSHARE_TOKEN"] == ""
    assert values["THESISTRACE_AGENT_OPENAI_API_KEY"] == ""
    assert original != second.read_bytes()
    rejected = _configure(first, "init")
    assert rejected.returncode != 0
    assert first.read_bytes() == original
    assert values["BETTER_AUTH_SECRET"] not in rejected.stdout + rejected.stderr


def test_missing_source_credential_stops_development_before_docker(tmp_path: Path) -> None:
    path = tmp_path / "runtime.env"
    environment = development_environment(path)
    path.write_text(
        path.read_text().replace(
            "THESISTRACE_TUSHARE_TOKEN=fixture-configuration-only-12345",
            "THESISTRACE_TUSHARE_TOKEN=",
        )
    )
    marker = tmp_path / "docker-called"
    docker = tmp_path / "docker"
    docker.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    docker.chmod(0o755)
    result = subprocess.run(
        ["node", ROOT / "tooling/dev/runtime.mjs", "development", "up"],
        env={
            **environment,
            "PATH": f"{tmp_path}:{environment['PATH']}",
            "THESISTRACE_TUSHARE_TOKEN": "ambient-must-not-rescue-missing-config",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "THESISTRACE_TUSHARE_TOKEN" in result.stderr
    assert not marker.exists()
    assert "ambient-must-not-rescue" not in result.stderr


def test_development_file_is_authoritative_at_compose_boundary(tmp_path: Path) -> None:
    path = tmp_path / "runtime.env"
    environment = development_environment(path)
    log = tmp_path / "docker.json"
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
        f"Path({str(log)!r}).write_text(json.dumps({{"
        "'args':sys.argv[1:],'token':os.environ.get('THESISTRACE_TUSHARE_TOKEN'),"
        "'origin':os.environ.get('THESISTRACE_PUBLIC_ORIGIN'),"
        "'model':json.loads(os.environ['THESISTRACE_AGENT_MODEL_REGISTRY'])}))\n"
    )
    docker.chmod(0o755)
    result = subprocess.run(
        ["node", ROOT / "tooling/dev/runtime.mjs", "development", "validate"],
        env={
            **environment,
            "PATH": f"{tmp_path}:{environment['PATH']}",
            "THESISTRACE_TUSHARE_TOKEN": "ambient-credential",
            "THESISTRACE_PUBLIC_ORIGIN": "https://wrong.invalid",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(log.read_text())
    assert observed["token"] == "fixture-configuration-only-12345"
    assert observed["origin"] == "http://127.0.0.1:5173"
    assert observed["args"][observed["args"].index("--env-file") + 1] == "/dev/null"
    assert observed["model"] == json.loads(
        (ROOT / "apps/agent/config/model-registry.json").read_text()
    )


def test_configuration_rejects_interpolation_duplicates_and_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "runtime.env"
    development_environment(path)
    valid = path.read_text()
    for extra in (
        "CLI_API_KEY=must-not-be-supported\n",
        "RESEND_API_KEY=must-not-be-duplicated\n",
    ):
        path.write_text(valid + extra)
        result = _configure(path, "check")
        assert result.returncode != 0
        assert "must-not-be" not in result.stdout + result.stderr
    path.write_text(
        valid.replace(
            "THESISTRACE_TUSHARE_TOKEN=fixture-configuration-only-12345",
            "THESISTRACE_TUSHARE_TOKEN=${EXTERNAL_SECRET}",
        )
    )
    result = _configure(path, "check", EXTERNAL_SECRET="sensitive-external-value")
    assert result.returncode != 0
    assert "sensitive-external-value" not in result.stdout + result.stderr
    path.write_text(valid.replace("RESEND_API_KEY=", "RESEND_API_KEY=private#"))
    result = _configure(path, "check")
    assert result.returncode != 0
    assert "private#" not in result.stdout + result.stderr


def test_configuration_template_has_no_private_values() -> None:
    template = (ROOT / ".env.example").read_text()
    values = dict(
        line.split("=", 1) for line in template.splitlines() if line and not line.startswith("#")
    )
    for name in (
        "BETTER_AUTH_SECRET",
        "RESEND_API_KEY",
        "THESISTRACE_TUSHARE_TOKEN",
        "THESISTRACE_OWNER_DATABASE_PASSWORD",
        "THESISTRACE_CORE_DATABASE_PASSWORD",
        "THESISTRACE_AUTH_DATABASE_PASSWORD",
        "THESISTRACE_AGENT_DATABASE_PASSWORD",
        "THESISTRACE_S3_ACCESS_KEY_ID",
        "THESISTRACE_S3_SECRET_ACCESS_KEY",
        "THESISTRACE_MCP_SIGNING_PRIVATE_JWK",
        "THESISTRACE_AGENT_OPENAI_API_KEY",
    ):
        assert values[name] == "", name
    assert not (ROOT / "deploy/core/dev.env").exists()


def test_private_cli_reads_the_same_file_without_ambient_overrides(tmp_path: Path) -> None:
    path = tmp_path / "runtime.env"
    environment = development_environment(path)
    result = subprocess.run(
        [
            "node",
            ROOT / "tooling/config/cli.mjs",
            "run",
            "node",
            "-e",
            "process.exit(process.env.THESISTRACE_TUSHARE_TOKEN === "
            "'fixture-configuration-only-12345' && "
            "JSON.parse(process.env.THESISTRACE_AGENT_MODEL_REGISTRY).models.length > 0 ? 0 : 1)",
        ],
        env={**environment, "THESISTRACE_TUSHARE_TOKEN": "stale-ambient-credential"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_private_configuration_and_templates_have_distinct_git_policies(tmp_path: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", ".env", "local.env", ".env.private", ".env.example"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.splitlines() == [".env", "local.env", ".env.private"]
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert ".env" in dockerignore
    assert "**/*.env" in dockerignore

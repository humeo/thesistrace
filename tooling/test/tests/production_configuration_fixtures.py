from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ["node", ROOT / "tooling/dev/runtime.mjs", "production"]

VALID_ENVIRONMENT = """\
THESISTRACE_ENVIRONMENT=production
THESISTRACE_PUBLIC_ORIGIN=https://research.thesistrace.com
THESISTRACE_RESEND_API_URL=https://api.resend.com
THESISTRACE_AGENT_OPENAI_BASE_URL=https://api.openai.com/v1
THESISTRACE_S3_ACCESS_KEY_ID=StorageAccess_7Qh9tT4Sx2Vk8Lm3
THESISTRACE_S3_SECRET_ACCESS_KEY=StorageSecret_3Nm8qW6Zp5Jc2Rs7
THESISTRACE_OWNER_DATABASE_PASSWORD=OwnerRuntime_7Qh9tT4Sx2Vk8Lm3
THESISTRACE_CORE_DATABASE_PASSWORD=CoreRuntime_3Nm8qW6Zp5Jc2Rs7
THESISTRACE_AUTH_DATABASE_PASSWORD=AuthRuntime_9Fd4vB7Ky2Hg6Px8
THESISTRACE_AGENT_DATABASE_PASSWORD=AgentRuntime_5Jt8mQ3Wx7Lc9Vr4
BETTER_AUTH_SECRET=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
RESEND_API_KEY=re_production_7Kp4mN9vQ2sL6xT8
RESEND_FROM_EMAIL=ThesisTrace <noreply@thesistrace.com>
THESISTRACE_TUSHARE_TOKEN=production-tushare-token-7Kp4mN9vQ2sL6xT8
THESISTRACE_AUTH_IMAGE=ghcr.io/thesistrace/auth:2026-08-29
THESISTRACE_AGENT_IMAGE=ghcr.io/thesistrace/agent:2026-08-29
THESISTRACE_AGENT_BUILD_REVISION=2026-08-29.1
THESISTRACE_AGENT_OPENAI_API_KEY=sk-production-agent-7Kp4mN9vQ2sL6xT8
THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS=600
THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS=660
THESISTRACE_MCP_AGENT_SCOPES=["research:read","research:execute","tracking:read","tracking:execute"]
THESISTRACE_MCP_CLIENT_ID=thesistrace-agent
THESISTRACE_MCP_CLOCK_SKEW_SECONDS=30
THESISTRACE_MCP_DEPLOYMENT_TOOLS=["diagnose_alpha_formula","get_alpha_catalog","get_daily_track","get_daily_track_result","get_research_batch","get_research_context","get_research_run","get_research_run_result","list_daily_tracks","list_research_batches","list_research_runs","refresh_daily_track","retry_daily_track","start_daily_track","submit_research_batch","submit_research_run"]
THESISTRACE_MCP_SIGNING_PRIVATE_JWK={"alg":"EdDSA","crv":"Ed25519","d":"bL6DuMib1dGbVwuY4HVdhFmqF2DwywXfoNQvOcF9DGQ","kid":"research-agent-signing-2026-08","kty":"OKP","use":"sig","x":"ECcLaOhwYA5_r6Ub4y8ZbuuvOSEwsim7Ttg5DXXG0yc"}
THESISTRACE_MCP_VERIFYING_PUBLIC_JWK={"alg":"EdDSA","crv":"Ed25519","kid":"research-agent-signing-2026-08","kty":"OKP","use":"sig","x":"ECcLaOhwYA5_r6Ub4y8ZbuuvOSEwsim7Ttg5DXXG0yc"}
"""


def _run(
    tmp_path: Path,
    environment_file: Path,
    action: str,
    *,
    stat_result: str,
    command: list[str | Path] | None = None,
    docker_program: str | None = None,
    command_log: Path | None = None,
    environment_log: Path | None = None,
    ambient_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # The CLI uses Node's filesystem metadata, not a shell stat subprocess.
    # Only ownership is simulated on non-root developer machines; parsing is real.
    uid, mode = stat_result.split(":")
    prelude = tmp_path / "filesystem-metadata.mjs"
    prelude.write_text(
        "import fs from 'node:fs'; import {syncBuiltinESMExports} from 'node:module';"
        "const original=fs.lstatSync;fs.lstatSync=(...args)=>{const stat=original(...args);"
        f"if(String(args[0])==={json.dumps(str(environment_file))}){{stat.uid={int(uid)};"
        f"stat.mode=(stat.mode & ~0o777)|0o{mode};}}return stat;}};syncBuiltinESMExports();"
    )
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'if [ -n "${PRODUCTION_RUNTIME_ENV_LOG-}" ]; then\n'
        "  printf 'public_origin=%s\\nauth_secret=%s\\ntushare_token=%s\\n' "
        '"${THESISTRACE_PUBLIC_ORIGIN-unset}" '
        '"${BETTER_AUTH_SECRET-unset}" '
        '"${THESISTRACE_TUSHARE_TOKEN-unset}" >>"$PRODUCTION_RUNTIME_ENV_LOG"\n'
        "  printf 'agent_registry=%s\\nagent_provider=%s\\n' "
        '"${THESISTRACE_AGENT_MODEL_REGISTRY-unset}" '
        '"${THESISTRACE_AGENT_OPENAI_API_KEY-unset}" >>"$PRODUCTION_RUNTIME_ENV_LOG"\n'
        "  printf 'mcp_private_key=%s\\n' "
        '"${THESISTRACE_MCP_SIGNING_PRIVATE_JWK-unset}" >>"$PRODUCTION_RUNTIME_ENV_LOG"\n'
        "fi\n"
        'if [ -n "${PRODUCTION_RUNTIME_COMMAND_LOG-}" ]; then\n'
        '  printf \'%s\\n\' "docker $*" >>"$PRODUCTION_RUNTIME_COMMAND_LOG"\n'
        "fi\n"
    )
    if docker_program is not None:
        docker.write_text(docker_program)
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "THESISTRACE_ENV_FILE": str(environment_file),
        "NODE_OPTIONS": f"--import={prelude}",
    }
    if command_log is not None:
        environment["PRODUCTION_RUNTIME_COMMAND_LOG"] = str(command_log)
    if environment_log is not None:
        environment["PRODUCTION_RUNTIME_ENV_LOG"] = str(environment_log)
    if ambient_overrides is not None:
        environment.update(ambient_overrides)
    return subprocess.run(
        command if command is not None else [*SCRIPT, action],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / "tooling" / "test" / "release-gate"


def _environment(tmp_path: Path, *, dirty: bool = False) -> tuple[dict[str, str], Path]:
    command_log = tmp_path / "commands.log"
    git = tmp_path / "git"
    git.write_text(
        """#!/bin/sh
case " $* " in
  *" rev-parse --verify HEAD^{commit} "*)
    printf '%s\n' 0123456789abcdef0123456789abcdef01234567
    ;;
  *" status --porcelain=v1 --untracked-files=normal "*)
    if [ "${FAKE_GIT_DIRTY:-false}" = true ]; then
      printf '%s\n' '?? private-path-canary'
    fi
    ;;
  *) exit 2 ;;
esac
"""
    )
    git.chmod(0o755)
    pnpm = tmp_path / "pnpm"
    pnpm.write_text(
        """#!/bin/sh
printf '%s|cwd=%s|cli=%s|openai=%s|anthropic=%s|google=%s\n' \
  "$*" "$PWD" "${CLI_API_KEY-unset}" "${THESISTRACE_AGENT_OPENAI_API_KEY-unset}" \
  "${THESISTRACE_AGENT_ANTHROPIC_API_KEY-unset}" \
  "${THESISTRACE_AGENT_GOOGLE_API_KEY-unset}" >>"$RELEASE_COMMAND_LOG"
case "$*" in
  check) exit "${FAKE_CHECK_STATUS:-0}" ;;
  test:image-smoke) exit "${FAKE_IMAGE_STATUS:-0}" ;;
  *) exit 2 ;;
esac
"""
    )
    pnpm.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RELEASE_COMMAND_LOG": str(command_log),
        "FAKE_GIT_DIRTY": "true" if dirty else "false",
        "CLI_API_KEY": "private-cli-provider-canary",
        "THESISTRACE_AGENT_OPENAI_API_KEY": "private-openai-provider-canary",
        "THESISTRACE_AGENT_ANTHROPIC_API_KEY": "private-anthropic-provider-canary",
        "THESISTRACE_AGENT_GOOGLE_API_KEY": "private-google-provider-canary",
    }
    return environment, command_log


def test_release_gate_runs_only_deterministic_gates_from_a_clean_commit(
    tmp_path: Path,
) -> None:
    package = json.loads((ROOT / "package.json").read_text())
    assert package["scripts"]["check:release"] == "./tooling/test/release-gate"
    environment, command_log = _environment(tmp_path)

    completed = subprocess.run(
        [GATE],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert command_log.read_text().splitlines() == [
        f"check|cwd={ROOT}|cli=unset|openai=unset|anthropic=unset|google=unset",
        f"test:image-smoke|cwd={ROOT}|cli=unset|openai=unset|anthropic=unset|google=unset",
    ]
    assert '"git_revision":"0123456789abcdef0123456789abcdef01234567"' in (
        completed.stdout
    )
    assert '"real_model_eval":"not_run"' in completed.stdout
    assert '"model_qualification":"pending"' in completed.stdout
    assert "private-" not in completed.stdout + completed.stderr


def test_release_gate_refuses_a_dirty_tree_without_disclosing_paths(
    tmp_path: Path,
) -> None:
    environment, command_log = _environment(tmp_path, dirty=True)

    completed = subprocess.run(
        [GATE],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == (
        '{"code":"RELEASE_WORKTREE_DIRTY","event":"release_gate_failed"}\n'
    )
    assert not command_log.exists()
    assert "private-path-canary" not in completed.stderr


def test_release_gate_stops_before_images_when_the_standard_gate_fails(
    tmp_path: Path,
) -> None:
    environment, command_log = _environment(tmp_path)
    environment["FAKE_CHECK_STATUS"] = "7"

    completed = subprocess.run(
        [GATE],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 7
    assert [line.split("|", maxsplit=1)[0] for line in command_log.read_text().splitlines()] == [
        "check"
    ]
    assert "release_gate_completed" not in completed.stdout

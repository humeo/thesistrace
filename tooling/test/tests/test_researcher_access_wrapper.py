from __future__ import annotations

import json
from pathlib import Path

import pytest
from production_configuration_fixtures import VALID_ENVIRONMENT, _run

ROOT = Path(__file__).resolve().parents[3]
RESEARCHER_ID = "00000000-0000-4000-8000-000000000101"


@pytest.mark.parametrize("rejected_phase", [None, "resolve", "inspect", "deactivate"])
def test_deactivation_composes_auth_identity_and_core_inspection_before_mutation(
    tmp_path: Path, rejected_phase: str | None
) -> None:
    environment = tmp_path / "production.env"
    environment.write_text(VALID_ENVIRONMENT)
    environment.chmod(0o600)
    log = tmp_path / "commands.jsonl"
    docker = f"""#!/usr/bin/env python3
import json, sys
from pathlib import Path
args=sys.argv[1:]
with Path({str(log)!r}).open("a") as stream: stream.write(json.dumps(args)+"\\n")
if "config" in args: raise SystemExit(0)
phase="inspect" if "active-daily-tracks" in args else (
    "resolve" if "resolve" in args else "deactivate")
if phase=={rejected_phase!r}: raise SystemExit(17)
if phase=="inspect":
    print(json.dumps({{"active_daily_track_count":3,"researcher_id":{RESEARCHER_ID!r},"status":"inspected"}}))
else:
    print(json.dumps({{"command":phase,"researcher_id":{RESEARCHER_ID!r},
        "status":"resolved" if phase=="resolve" else "updated"}}))
"""
    completed = _run(
        tmp_path,
        environment,
        "run",
        stat_result="0:600",
        docker_program=docker,
        command=[
            "node",
            ROOT / "tooling/dev/deactivate-researcher.mjs",
            "--email",
            "operator@example.com",
        ],
    )
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert commands[0][-2:] == ["config", "--quiet"]
    assert commands[1][-6:] == [
        "auth",
        "node",
        "dist/operator.js",
        "resolve",
        "--email",
        "operator@example.com",
    ]
    if rejected_phase == "resolve":
        assert len(commands) == 2
    else:
        assert commands[2][-5:] == [
            "api",
            "thesistrace-core-access-inspect",
            "active-daily-tracks",
            "--researcher-id",
            RESEARCHER_ID,
        ]
        if rejected_phase == "inspect":
            assert len(commands) == 3
        else:
            assert commands[3][-6:] == [
                "auth",
                "node",
                "dist/operator.js",
                "deactivate",
                "--researcher-id",
                RESEARCHER_ID,
            ]
    if rejected_phase:
        assert completed.returncode == 17
        assert completed.stdout == ""
    else:
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {
            "active_daily_track_count": 3,
            "command": "deactivate",
            "researcher_id": RESEARCHER_ID,
            "status": "updated",
        }

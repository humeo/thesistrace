from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from live_auth import create_private_compose_login_session, run_auth_operator

_RESEARCHERS = {
    "initial_operator": "image-smoke-initial-operator@example.test",
    "successor_operator": "image-smoke-successor-operator@example.test",
    "revocation_target": "image-smoke-revocation-target@example.test",
}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"provision", "transfer"}:
        raise SystemExit(
            "usage: qualify_operator_image_smoke.py {provision|transfer} SESSION_FILE"
        )
    path = Path(sys.argv[2]).resolve()
    if sys.argv[1] == "provision":
        _provision(path)
    else:
        _transfer(path)


def _provision(path: Path) -> None:
    sessions = {
        role: create_private_compose_login_session(email)
        for role, email in _RESEARCHERS.items()
    }
    initial = sessions["initial_operator"]
    assignment = run_auth_operator(
        "assign-operator", "--researcher-id", initial.researcher_id
    )
    if assignment != {
        "command": "assign-operator",
        "researcher_id": initial.researcher_id,
        "status": "assigned",
    }:
        raise AssertionError("Production Image Operator assignment was not atomic")
    descriptor = {
        role: {
            "cookie": session.cookie,
            "researcher_id": session.researcher_id,
        }
        for role, session in sessions.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor_fd, "w") as destination:
        json.dump(descriptor, destination, sort_keys=True, separators=(",", ":"))
    print(
        json.dumps(
            {
                "assignment": assignment,
                "researcher_ids": {
                    role: session.researcher_id for role, session in sessions.items()
                },
                "status": "provisioned",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _transfer(path: Path) -> None:
    sessions = _read_sessions(path)
    former_id = sessions["initial_operator"]["researcher_id"]
    successor_id = sessions["successor_operator"]["researcher_id"]
    transferred = run_auth_operator(
        "transfer-operator", "--researcher-id", successor_id
    )
    if transferred != {
        "command": "transfer-operator",
        "former_researcher_id": former_id,
        "researcher_id": successor_id,
        "status": "transferred",
    }:
        raise AssertionError("Production Image Operator transfer was not atomic")
    print(json.dumps(transferred, sort_keys=True, separators=(",", ":")))


def _read_sessions(path: Path) -> dict[str, dict[str, str]]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != set(_RESEARCHERS):
        raise RuntimeError("Production Image Operator Sessions are invalid")
    sessions: dict[str, dict[str, str]] = {}
    for role, item in value.items():
        if (
            not isinstance(role, str)
            or not isinstance(item, dict)
            or set(item) != {"cookie", "researcher_id"}
            or not all(isinstance(field, str) and field for field in item.values())
        ):
            raise RuntimeError("Production Image Operator Session is invalid")
        sessions[role] = item
    return sessions


if __name__ == "__main__":
    main()

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.objects import canonical_json_bytes

AUDIT_SUBJECT_TYPES = {
    "backup.target.initialize": "hosted_recovery",
    "backup.create": "hosted_recovery",
    "backup.restore": "hosted_recovery",
    "acceptance.service.interrupt": "hosted_acceptance",
    "acceptance.service.recover": "hosted_acceptance",
    "acceptance.node.restart": "hosted_acceptance",
    "smtp.configure": "smtp_configuration",
}
RECOVERY_AUDIT_ACTIONS = tuple(
    action for action in AUDIT_SUBJECT_TYPES if action.startswith("backup.")
)
OPERATOR_AUDIT_ACTIONS = tuple(AUDIT_SUBJECT_TYPES)
OPERATOR_AUDIT_ID = re.compile(
    r"audit_(?:recovery|acceptance|operator)_[0-9A-Za-z_-]{1,96}"
)


class OperatorAuditError(RuntimeError):
    pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage_operator_audit(
    outbox: Path,
    *,
    event_id: str,
    actor: str,
    action: str,
    outcome: str,
    subject_id: str,
    reason_code: str | None,
) -> Path:
    if (
        OPERATOR_AUDIT_ID.fullmatch(event_id) is None
        or action not in AUDIT_SUBJECT_TYPES
        or outcome not in {"succeeded", "rejected"}
        or not actor.strip()
        or not subject_id
    ):
        raise OperatorAuditError("operator audit identity is invalid")
    parent_existed = outbox.exists()
    outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    outbox.chmod(0o700)
    if not parent_existed:
        _fsync_directory(outbox.parent)
    path = outbox / f"{event_id}.json"
    occurred_at = datetime.now(UTC).isoformat()
    if path.is_file():
        try:
            existing = json.loads(path.read_bytes())
            occurred_at = str(existing["occurred_at"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise OperatorAuditError("operator audit outbox is invalid") from error
    event = {
        "id": event_id,
        "occurred_at": occurred_at,
        "actor": actor,
        "action": action,
        "outcome": outcome,
        "reason_code": reason_code,
        "subject_type": AUDIT_SUBJECT_TYPES[action],
        "subject_id": subject_id,
        "details": {},
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(event))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    path.chmod(0o600)
    _fsync_directory(outbox)
    return path


def flush_operator_audits(outbox: Path, database_url: str) -> int:
    if not outbox.exists():
        return 0
    store = PostgresManagementStore(database_url)
    flushed = 0
    for path in sorted(outbox.glob("audit_*.json")):
        try:
            event = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise OperatorAuditError("operator audit outbox is invalid") from error
        action = event.get("action") if isinstance(event, dict) else None
        if (
            not isinstance(event, dict)
            or OPERATOR_AUDIT_ID.fullmatch(str(event.get("id", ""))) is None
            or action not in AUDIT_SUBJECT_TYPES
            or event.get("outcome") not in {"succeeded", "rejected"}
            or not isinstance(event.get("actor"), str)
            or not event["actor"].strip()
            or event.get("subject_type") != AUDIT_SUBJECT_TYPES[action]
            or not isinstance(event.get("subject_id"), str)
            or not event["subject_id"]
            or event.get("details") != {}
        ):
            raise OperatorAuditError("operator audit outbox is invalid")
        store.append_management_audit_event_idempotent(event)
        path.unlink()
        flushed += 1
    if flushed:
        _fsync_directory(outbox)
    return flushed

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from thesistrace.config import Settings

HOSTED_TUSHARE_SCOPE = "hosted-shared-dataset-releases"


class ManagementStore(Protocol):
    def record_source_authorization(
        self,
        declaration: dict[str, object],
        audit_event: dict[str, object],
    ) -> None: ...

    def append_management_audit_event(self, event: dict[str, object]) -> None: ...

    def latest_source_authorization(self) -> dict[str, object] | None: ...

    def list_management_audit_events(self) -> list[dict[str, object]]: ...


class SourceAuthorizationError(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


class SourceAuthorizationService:
    def __init__(self, store: ManagementStore) -> None:
        self.store = store

    def record(self, *, actor: str, scope: str) -> dict[str, object]:
        occurred_at = datetime.now(UTC).isoformat()
        audit_event_id = f"audit_{uuid4().hex}"
        normalized_actor = actor.strip()
        if not normalized_actor or scope != HOSTED_TUSHARE_SCOPE:
            reason_code = (
                "OPERATOR_ACTOR_REQUIRED"
                if not normalized_actor
                else "SOURCE_AUTHORIZATION_SCOPE_REJECTED"
            )
            self.store.append_management_audit_event(
                {
                    "id": audit_event_id,
                    "occurred_at": occurred_at,
                    "actor": normalized_actor or "unknown",
                    "action": "source_authorization.record",
                    "outcome": "rejected",
                    "reason_code": reason_code,
                    "subject_type": "source_authorization",
                    "subject_id": "tushare",
                    "details": {"source": "tushare"},
                }
            )
            raise SourceAuthorizationError(
                reason_code,
                "the declaration must use the fixed hosted shared-use scope",
            )

        declaration = {
            "id": f"source_auth_{uuid4().hex}",
            "source": "tushare",
            "scope": HOSTED_TUSHARE_SCOPE,
            "actor": normalized_actor,
            "declared_at": occurred_at,
            "audit_event_id": audit_event_id,
        }
        audit_event = {
            "id": audit_event_id,
            "occurred_at": occurred_at,
            "actor": normalized_actor,
            "action": "source_authorization.record",
            "outcome": "succeeded",
            "reason_code": None,
            "subject_type": "source_authorization",
            "subject_id": declaration["id"],
            "details": {
                "source": "tushare",
                "scope": HOSTED_TUSHARE_SCOPE,
                "declaration_id": declaration["id"],
            },
        }
        self.store.record_source_authorization(declaration, audit_event)
        return declaration

    def inspect(self) -> dict[str, object] | None:
        return self.store.latest_source_authorization()

    def is_authorized(self) -> bool:
        declaration = self.inspect()
        return (
            declaration is not None
            and declaration.get("source") == "tushare"
            and declaration.get("scope") == HOSTED_TUSHARE_SCOPE
        )


def build_management_store(
    settings: Settings,
    fallback: ManagementStore,
) -> ManagementStore:
    if not settings.database_url:
        return fallback
    from thesistrace.hosted.management import PostgresManagementStore

    return PostgresManagementStore(settings.database_url)

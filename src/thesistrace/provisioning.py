from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from thesistrace.auth import InsForgeIdentity
from thesistrace.config import Settings
from thesistrace.management import SourceAuthorizationService


@dataclass(frozen=True)
class ProductIdentity:
    user_id: str
    workspace_id: str
    insforge_subject: str
    normalized_email: str


@dataclass(frozen=True)
class ProvisioningResult:
    invitation_id: str
    identity: ProductIdentity
    created: bool


class ProvisioningError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ProvisioningStore(Protocol):
    def issue_invitation(
        self,
        *,
        actor: str,
        normalized_email: str,
        expires_at: datetime,
        now: datetime,
    ) -> dict[str, object]: ...

    def record_invitation_rejection(
        self,
        *,
        actor: str,
        action: str,
        reason_code: str,
        subject_id: str,
        now: datetime,
    ) -> None: ...

    def revoke_invitation(
        self,
        *,
        actor: str,
        invitation_id: str,
        now: datetime,
    ) -> dict[str, object]: ...

    def invitation(self, invitation_id: str) -> dict[str, object] | None: ...

    def provision(
        self,
        *,
        identity: InsForgeIdentity,
        normalized_email: str,
        now: datetime,
    ) -> ProvisioningResult: ...

    def resolve_identity(self, insforge_subject: str) -> ProductIdentity | None: ...


class RegistrationService:
    def __init__(
        self,
        *,
        store: ProvisioningStore,
        source_authorization: SourceAuthorizationService,
    ) -> None:
        self.store = store
        self.source_authorization = source_authorization

    def issue_invitation(
        self,
        *,
        actor: str,
        email: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> dict[str, object]:
        occurred_at = now or datetime.now(UTC)
        normalized_actor = actor.strip()
        try:
            normalized_email = normalize_email(email)
        except ProvisioningError:
            self.store.record_invitation_rejection(
                actor=normalized_actor or "unknown",
                action="registration_invitation.issue",
                reason_code="INVITATION_EMAIL_INVALID",
                subject_id="new",
                now=occurred_at,
            )
            raise
        if not normalized_actor:
            self.store.record_invitation_rejection(
                actor="unknown",
                action="registration_invitation.issue",
                reason_code="OPERATOR_ACTOR_REQUIRED",
                subject_id="new",
                now=occurred_at,
            )
            raise ProvisioningError("OPERATOR_ACTOR_REQUIRED", "operator actor is required")
        if expires_at.tzinfo is None or expires_at <= occurred_at:
            self.store.record_invitation_rejection(
                actor=normalized_actor,
                action="registration_invitation.issue",
                reason_code="INVITATION_EXPIRY_INVALID",
                subject_id="new",
                now=occurred_at,
            )
            raise ProvisioningError(
                "INVITATION_EXPIRY_INVALID",
                "invitation expiry must be an explicit future instant",
            )
        if not self.source_authorization.is_authorized():
            self.store.record_invitation_rejection(
                actor=normalized_actor,
                action="registration_invitation.issue",
                reason_code="SOURCE_AUTHORIZATION_REQUIRED",
                subject_id="new",
                now=occurred_at,
            )
            raise ProvisioningError(
                "SOURCE_AUTHORIZATION_REQUIRED",
                "hosted shared Tushare authorization is required before invitation issuance",
            )
        return self.store.issue_invitation(
            actor=normalized_actor,
            normalized_email=normalized_email,
            expires_at=expires_at,
            now=occurred_at,
        )

    def revoke_invitation(
        self,
        *,
        actor: str,
        invitation_id: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        normalized_actor = actor.strip()
        normalized_id = invitation_id.strip()
        if not normalized_actor or not normalized_id:
            raise ProvisioningError(
                "INVITATION_REVOCATION_INVALID",
                "actor and invitation id are required",
            )
        return self.store.revoke_invitation(
            actor=normalized_actor,
            invitation_id=normalized_id,
            now=now or datetime.now(UTC),
        )

    def invitation(self, invitation_id: str) -> dict[str, object] | None:
        return self.store.invitation(invitation_id.strip())

    def provision(
        self,
        identity: InsForgeIdentity,
        *,
        now: datetime | None = None,
    ) -> ProvisioningResult:
        return self.store.provision(
            identity=identity,
            normalized_email=normalize_email(identity.email),
            now=now or datetime.now(UTC),
        )

    def resolve_identity(self, insforge_subject: str) -> ProductIdentity | None:
        return self.store.resolve_identity(insforge_subject)


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    local, separator, domain = normalized.partition("@")
    if (
        not separator
        or not local
        or not domain
        or "@" in domain
        or any(character.isspace() for character in normalized)
    ):
        raise ProvisioningError("INVITATION_EMAIL_INVALID", "a valid email is required")
    return normalized


def build_registration_service(
    *,
    settings: Settings,
    source_authorization: SourceAuthorizationService,
) -> RegistrationService:
    if not settings.database_url:
        raise RuntimeError("THESISTRACE_DATABASE_URL is required for hosted registration")
    from thesistrace.hosted.provisioning import PostgresProvisioningStore

    return RegistrationService(
        store=PostgresProvisioningStore(
            settings.database_url,
        ),
        source_authorization=source_authorization,
    )

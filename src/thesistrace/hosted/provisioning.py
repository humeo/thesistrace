import json
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from thesistrace.auth import InsForgeIdentity
from thesistrace.provisioning import (
    ProductIdentity,
    ProvisioningError,
    ProvisioningResult,
)


class PostgresProvisioningStore:
    def __init__(
        self,
        database_url: str,
        *,
        before_provisioning_commit: Callable[[], None] | None = None,
    ) -> None:
        self.database_url = database_url
        self.before_provisioning_commit = before_provisioning_commit

    def issue_invitation(
        self,
        *,
        actor: str,
        normalized_email: str,
        expires_at: datetime,
        now: datetime,
    ) -> dict[str, object]:
        invitation_id = f"invite_{uuid4().hex}"
        failure: ProvisioningError | None = None
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"invitation:{normalized_email}",),
            )
            self._expire_issued_for_email(connection, normalized_email, now)
            authorized = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM thesistrace_control.source_authorization_declarations
                    WHERE source = 'tushare'
                      AND intended_scope = 'hosted-shared-dataset-releases'
                )
                """
            ).fetchone()["exists"]
            if not authorized:
                self._insert_audit(
                    connection,
                    actor=actor,
                    action="registration_invitation.issue",
                    outcome="rejected",
                    reason_code="SOURCE_AUTHORIZATION_REQUIRED",
                    subject_id=invitation_id,
                    occurred_at=now,
                    details={"invitation_id": invitation_id},
                )
                failure = ProvisioningError(
                    "SOURCE_AUTHORIZATION_REQUIRED",
                    "hosted shared Tushare authorization is required",
                )
            else:
                existing = connection.execute(
                    """
                    SELECT id
                    FROM thesistrace_control.registration_invitations
                    WHERE normalized_email = %s AND state = 'issued'
                    """,
                    (normalized_email,),
                ).fetchone()
                if existing is not None:
                    self._insert_audit(
                        connection,
                        actor=actor,
                        action="registration_invitation.issue",
                        outcome="rejected",
                        reason_code="INVITATION_ALREADY_ISSUED",
                        subject_id=str(existing["id"]),
                        occurred_at=now,
                        details={"invitation_id": str(existing["id"])},
                    )
                    failure = ProvisioningError(
                        "INVITATION_ALREADY_ISSUED",
                        "an issued invitation already exists for this email",
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO thesistrace_control.registration_invitations (
                            id, normalized_email, state, issued_by, issued_at, expires_at
                        )
                        VALUES (%s, %s, 'issued', %s, %s, %s)
                        """,
                        (invitation_id, normalized_email, actor, now, expires_at),
                    )
                    self._insert_audit(
                        connection,
                        actor=actor,
                        action="registration_invitation.issue",
                        outcome="succeeded",
                        reason_code=None,
                        subject_id=invitation_id,
                        occurred_at=now,
                        details={
                            "invitation_id": invitation_id,
                            "expires_at": expires_at.isoformat(),
                        },
                    )
        if failure is not None:
            raise failure
        invitation = self.invitation(invitation_id)
        assert invitation is not None
        return invitation

    def record_invitation_rejection(
        self,
        *,
        actor: str,
        action: str,
        reason_code: str,
        subject_id: str,
        now: datetime,
    ) -> None:
        with psycopg.connect(self.database_url) as connection:
            self._insert_audit(
                connection,
                actor=actor,
                action=action,
                outcome="rejected",
                reason_code=reason_code,
                subject_id=subject_id,
                occurred_at=now,
                details={"invitation_id": subject_id},
            )

    def revoke_invitation(
        self,
        *,
        actor: str,
        invitation_id: str,
        now: datetime,
    ) -> dict[str, object]:
        failure: ProvisioningError | None = None
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM thesistrace_control.registration_invitations
                WHERE id = %s
                FOR UPDATE
                """,
                (invitation_id,),
            ).fetchone()
            if row is not None and row["state"] == "issued" and row["expires_at"] <= now:
                self._expire_invitation(connection, row, now)
                row["state"] = "expired"
            if row is None or row["state"] != "issued":
                self._insert_audit(
                    connection,
                    actor=actor,
                    action="registration_invitation.revoke",
                    outcome="rejected",
                    reason_code="INVITATION_NOT_REVOCABLE",
                    subject_id=invitation_id,
                    occurred_at=now,
                    details={"invitation_id": invitation_id},
                )
                failure = ProvisioningError(
                    "INVITATION_NOT_REVOCABLE",
                    "invitation is not revocable",
                )
            else:
                connection.execute(
                    """
                    UPDATE thesistrace_control.registration_invitations
                    SET state = 'revoked', revoked_by = %s, revoked_at = %s
                    WHERE id = %s
                    """,
                    (actor, now, invitation_id),
                )
                self._insert_audit(
                    connection,
                    actor=actor,
                    action="registration_invitation.revoke",
                    outcome="succeeded",
                    reason_code=None,
                    subject_id=invitation_id,
                    occurred_at=now,
                    details={"invitation_id": invitation_id},
                )
        if failure is not None:
            raise failure
        invitation = self.invitation(invitation_id)
        assert invitation is not None
        return invitation

    def invitation(self, invitation_id: str) -> dict[str, object] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM thesistrace_control.registration_invitations
                WHERE id = %s
                """,
                (invitation_id,),
            ).fetchone()
        return self._serialize(row)

    def provision(
        self,
        *,
        identity: InsForgeIdentity,
        normalized_email: str,
        now: datetime,
    ) -> ProvisioningResult:
        result: ProvisioningResult | None = None
        failure: ProvisioningError | None = None
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"provision-subject:{identity.subject}",),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"provision-email:{normalized_email}",),
            )
            existing = self._identity_row(connection, identity.subject)
            if existing is not None:
                result = self._idempotent_result(connection, existing)
            else:
                email_owner = connection.execute(
                    """
                    SELECT id
                    FROM thesistrace_control.product_users
                    WHERE normalized_email = %s
                    """,
                    (normalized_email,),
                ).fetchone()
                invitation = connection.execute(
                    """
                    SELECT *
                    FROM thesistrace_control.registration_invitations
                    WHERE normalized_email = %s
                    ORDER BY issued_at DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (normalized_email,),
                ).fetchone()
                if (
                    invitation is not None
                    and invitation["state"] == "issued"
                    and invitation["expires_at"] <= now
                ):
                    self._expire_invitation(connection, invitation, now)
                    invitation["state"] = "expired"
                if email_owner is not None or invitation is None or invitation["state"] != "issued":
                    self._insert_audit(
                        connection,
                        actor=f"insforge:{identity.subject}",
                        action="registration_invitation.consume",
                        outcome="rejected",
                        reason_code="INVITATION_NOT_ELIGIBLE",
                        subject_id=str(invitation["id"]) if invitation else "unmatched",
                        occurred_at=now,
                        details={
                            "invitation_id": str(invitation["id"]) if invitation else "unmatched"
                        },
                    )
                    failure = ProvisioningError(
                        "INVITATION_NOT_ELIGIBLE",
                        "a matching issued invitation is required",
                    )
                else:
                    user_id = f"user_{uuid4().hex}"
                    workspace_id = f"workspace_{uuid4().hex}"
                    connection.execute(
                        """
                        INSERT INTO thesistrace_control.product_users (
                            id, insforge_subject, normalized_email, created_at
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (user_id, identity.subject, normalized_email, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO thesistrace_control.personal_workspaces (
                            id, user_id, created_at
                        )
                        VALUES (%s, %s, %s)
                        """,
                        (workspace_id, user_id, now),
                    )
                    connection.execute(
                        """
                        UPDATE thesistrace_control.registration_invitations
                        SET state = 'consumed',
                            consumed_at = %s,
                            consumed_by_user_id = %s
                        WHERE id = %s AND state = 'issued'
                        """,
                        (now, user_id, invitation["id"]),
                    )
                    self._insert_audit(
                        connection,
                        actor=f"insforge:{identity.subject}",
                        action="registration_invitation.consume",
                        outcome="succeeded",
                        reason_code=None,
                        subject_id=str(invitation["id"]),
                        occurred_at=now,
                        details={
                            "invitation_id": str(invitation["id"]),
                            "user_id": user_id,
                            "workspace_id": workspace_id,
                        },
                    )
                    if self.before_provisioning_commit is not None:
                        self.before_provisioning_commit()
                    result = ProvisioningResult(
                        invitation_id=str(invitation["id"]),
                        identity=ProductIdentity(
                            user_id=user_id,
                            workspace_id=workspace_id,
                            insforge_subject=identity.subject,
                            normalized_email=normalized_email,
                        ),
                        created=True,
                    )
        if failure is not None:
            raise failure
        assert result is not None
        return result

    def resolve_identity(self, insforge_subject: str) -> ProductIdentity | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = self._identity_row(connection, insforge_subject)
        return self._product_identity(row)

    @staticmethod
    def _identity_row(
        connection: psycopg.Connection,
        insforge_subject: str,
    ) -> dict[str, object] | None:
        return connection.execute(
            """
            SELECT
                users.id AS user_id,
                workspaces.id AS workspace_id,
                users.insforge_subject,
                users.normalized_email
            FROM thesistrace_control.product_users AS users
            JOIN thesistrace_control.personal_workspaces AS workspaces
              ON workspaces.user_id = users.id
            WHERE users.insforge_subject = %s
            """,
            (insforge_subject,),
        ).fetchone()

    def _idempotent_result(
        self,
        connection: psycopg.Connection,
        row: dict[str, object],
    ) -> ProvisioningResult:
        invitation = connection.execute(
            """
            SELECT id
            FROM thesistrace_control.registration_invitations
            WHERE consumed_by_user_id = %s
            """,
            (row["user_id"],),
        ).fetchone()
        assert invitation is not None
        identity = self._product_identity(row)
        assert identity is not None
        return ProvisioningResult(
            invitation_id=str(invitation["id"]),
            identity=identity,
            created=False,
        )

    @staticmethod
    def _product_identity(row: dict[str, object] | None) -> ProductIdentity | None:
        if row is None:
            return None
        return ProductIdentity(
            user_id=str(row["user_id"]),
            workspace_id=str(row["workspace_id"]),
            insforge_subject=str(row["insforge_subject"]),
            normalized_email=str(row["normalized_email"]),
        )

    def _expire_issued_for_email(
        self,
        connection: psycopg.Connection,
        normalized_email: str,
        now: datetime,
    ) -> None:
        rows = connection.execute(
            """
            SELECT *
            FROM thesistrace_control.registration_invitations
            WHERE normalized_email = %s
              AND state = 'issued'
              AND expires_at <= %s
            FOR UPDATE
            """,
            (normalized_email, now),
        ).fetchall()
        for row in rows:
            self._expire_invitation(connection, row, now)

    def _expire_invitation(
        self,
        connection: psycopg.Connection,
        invitation: dict[str, object],
        now: datetime,
    ) -> None:
        connection.execute(
            """
            UPDATE thesistrace_control.registration_invitations
            SET state = 'expired'
            WHERE id = %s AND state = 'issued'
            """,
            (invitation["id"],),
        )
        self._insert_audit(
            connection,
            actor="system",
            action="registration_invitation.expire",
            outcome="succeeded",
            reason_code=None,
            subject_id=str(invitation["id"]),
            occurred_at=now,
            details={"invitation_id": str(invitation["id"])},
        )

    @staticmethod
    def _insert_audit(
        connection: psycopg.Connection,
        *,
        actor: str,
        action: str,
        outcome: str,
        reason_code: str | None,
        subject_id: str,
        occurred_at: datetime,
        details: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO thesistrace_control.management_audit_events (
                id, occurred_at, actor, action, outcome, reason_code,
                subject_type, subject_id, details_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'registration_invitation', %s, %s::jsonb)
            """,
            (
                f"audit_{uuid4().hex}",
                occurred_at,
                actor,
                action,
                outcome,
                reason_code,
                subject_id,
                json.dumps(details, sort_keys=True, separators=(",", ":")),
            ),
        )

    @staticmethod
    def _serialize(row: dict[str, object] | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in row.items()
        }

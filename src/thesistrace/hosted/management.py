import json

import psycopg
from psycopg.rows import dict_row


class PostgresManagementStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def record_source_authorization(
        self,
        declaration: dict[str, object],
        audit_event: dict[str, object],
    ) -> None:
        with psycopg.connect(self.database_url) as connection:
            with connection.transaction():
                self._insert_audit_event(connection, audit_event)
                connection.execute(
                    """
                    INSERT INTO thesistrace_control.source_authorization_declarations (
                        id, source, intended_scope, actor, declared_at, audit_event_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        declaration["id"],
                        declaration["source"],
                        declaration["scope"],
                        declaration["actor"],
                        declaration["declared_at"],
                        declaration["audit_event_id"],
                    ),
                )

    def append_management_audit_event(self, event: dict[str, object]) -> None:
        with psycopg.connect(self.database_url) as connection:
            with connection.transaction():
                self._insert_audit_event(connection, event)

    def latest_source_authorization(self) -> dict[str, object] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    source,
                    intended_scope AS scope,
                    actor,
                    declared_at,
                    audit_event_id
                FROM thesistrace_control.source_authorization_declarations
                WHERE source = 'tushare'
                ORDER BY declared_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        return self._serialize_row(row)

    def list_management_audit_events(self) -> list[dict[str, object]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    occurred_at,
                    actor,
                    action,
                    outcome,
                    reason_code,
                    subject_type,
                    subject_id,
                    details_json AS details
                FROM thesistrace_control.management_audit_events
                ORDER BY occurred_at, id
                """
            ).fetchall()
        return [self._serialize_row(row) for row in rows if row is not None]

    def quota_profile(self, workspace_id: str) -> dict[str, int] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT
                    max_active_daily_tracks,
                    max_nonterminal_user_compute_jobs,
                    max_private_storage_bytes
                FROM thesistrace_control.workspace_quota_profiles
                WHERE workspace_id = %s
                """,
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        return {key: int(value) for key, value in row.items()}

    def update_quota_profile(
        self,
        *,
        workspace_id: str,
        overrides: dict[str, int],
        audit_event: dict[str, object],
    ) -> dict[str, int]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                current = connection.execute(
                    """
                    SELECT
                        max_active_daily_tracks,
                        max_nonterminal_user_compute_jobs,
                        max_private_storage_bytes
                    FROM thesistrace_control.workspace_quota_profiles
                    WHERE workspace_id = %s
                    FOR UPDATE
                    """,
                    (workspace_id,),
                ).fetchone()
                if current is None:
                    raise KeyError(workspace_id)
                profile = {key: int(value) for key, value in current.items()}
                profile.update(overrides)
                updated = connection.execute(
                    """
                    UPDATE thesistrace_control.workspace_quota_profiles
                    SET max_active_daily_tracks = %s,
                        max_nonterminal_user_compute_jobs = %s,
                        max_private_storage_bytes = %s,
                        updated_at = %s,
                        updated_by = %s
                    WHERE workspace_id = %s
                    """,
                    (
                        profile["max_active_daily_tracks"],
                        profile["max_nonterminal_user_compute_jobs"],
                        profile["max_private_storage_bytes"],
                        audit_event["occurred_at"],
                        audit_event["actor"],
                        workspace_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise KeyError(workspace_id)
                self._insert_audit_event(connection, audit_event)
        return profile

    @staticmethod
    def _insert_audit_event(
        connection: psycopg.Connection,
        event: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO thesistrace_control.management_audit_events (
                id,
                occurred_at,
                actor,
                action,
                outcome,
                reason_code,
                subject_type,
                subject_id,
                details_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                event["id"],
                event["occurred_at"],
                event["actor"],
                event["action"],
                event["outcome"],
                event["reason_code"],
                event["subject_type"],
                event["subject_id"],
                json.dumps(event["details"], sort_keys=True, separators=(",", ":")),
            ),
        )

    @staticmethod
    def _serialize_row(row: dict[str, object] | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in row.items()
        }

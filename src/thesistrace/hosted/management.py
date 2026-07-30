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

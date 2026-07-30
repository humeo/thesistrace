import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql

from thesistrace.quota import QuotaExceededError
from thesistrace.storage import MetadataStore
from thesistrace.tenancy import service_workspace, verified_subject

HOSTED_DATABASE_ROLES = {
    "api": "thesistrace_api",
    "compute": "thesistrace_compute",
    "data": "thesistrace_data",
}


class HybridRow(dict[str, object]):
    def __getitem__(self, key: str | int) -> object:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def hybrid_row(cursor: psycopg.Cursor[Any]) -> Any:
    columns = [column.name for column in cursor.description or ()]

    def make_row(values: Sequence[object]) -> HybridRow:
        return HybridRow(zip(columns, values, strict=True))

    return make_row


class PostgresConnectionAdapter:
    def __init__(self, connection: psycopg.Connection[HybridRow]) -> None:
        self.connection = connection

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] | None = None,
    ) -> psycopg.Cursor[HybridRow]:
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            return self.connection.execute("SELECT 1")
        return self.connection.execute(
            statement.replace("?", "%s"),
            tuple(parameters or ()),
        )

    def rollback(self) -> None:
        self.connection.rollback()

    def lock_research_run(self, run_id: str) -> HybridRow | None:
        return self.connection.execute(
            """
            SELECT status
            FROM thesistrace_product.research_runs
            WHERE id = %s
            FOR UPDATE
            """,
            (run_id,),
        ).fetchone()


class PostgresControlMetadataStore(MetadataStore):
    def __init__(self, database_url: str, *, database_role: str) -> None:
        if database_role not in HOSTED_DATABASE_ROLES:
            raise ValueError(f"unsupported hosted database role: {database_role}")
        self.database_url = database_url
        self.database_role = database_role

    def initialize(self) -> None:
        return None

    @contextmanager
    def connect(self) -> Iterator[PostgresConnectionAdapter]:
        with psycopg.connect(self.database_url, row_factory=hybrid_row) as connection:
            connection.execute("BEGIN")
            role = HOSTED_DATABASE_ROLES[self.database_role]
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            connection.execute(
                "SET LOCAL search_path = thesistrace_product, public"
            )
            if self.database_role == "api":
                subject = verified_subject()
                if subject is not None:
                    connection.execute(
                        "SELECT thesistrace_control.set_api_identity(%s)",
                        (subject,),
                    )
            elif self.database_role == "compute":
                workspace_id = service_workspace()
                if workspace_id is not None:
                    connection.execute(
                        "SELECT thesistrace_control.set_service_workspace(%s)",
                        (workspace_id,),
                    )
            yield PostgresConnectionAdapter(connection)

    def _enqueue_research_run(
        self,
        connection: PostgresConnectionAdapter,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO execution_outbox
                (id, resource_kind, resource_id, status, created_at)
            VALUES (?, 'research_run', ?, 'pending', ?)
            """,
            (f"outbox_{run_id}", run_id, created_at),
        )

    def _enqueue_research_run_cancellation(
        self,
        connection: PostgresConnectionAdapter,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO execution_outbox
                (id, resource_kind, resource_id, status, created_at)
            VALUES (?, 'research_run_cancel', ?, 'pending', ?)
            ON CONFLICT (workspace_id, resource_kind, resource_id) DO NOTHING
            """,
            (f"cancel_{run_id}", run_id, created_at),
        )

    def _admit_user_compute(
        self,
        connection: PostgresConnectionAdapter,
        *,
        resource_kind: str,
        resource_id: str,
        admitted_at: str,
    ) -> None:
        workspace = connection.execute(
            "SELECT thesistrace_control.current_workspace_id() AS workspace_id"
        ).fetchone()
        if workspace is None or workspace["workspace_id"] is None:
            raise RuntimeError("Personal Workspace context is missing")
        workspace_id = str(workspace["workspace_id"])
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (workspace_id,),
        )
        profile = connection.execute(
            """
            SELECT max_nonterminal_user_compute_jobs
            FROM thesistrace_control.workspace_quota_profiles
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if profile is None:
            raise RuntimeError("Personal Workspace Quota Profile is missing")
        limit = int(profile["max_nonterminal_user_compute_jobs"])
        active = int(
            connection.execute(
                """
                SELECT count(*)
                FROM user_compute_admissions
                WHERE completed_at IS NULL
                """
            ).fetchone()[0]
        )
        if active >= limit:
            raise QuotaExceededError(
                dimension="max_nonterminal_user_compute_jobs",
                limit=limit,
            )
        connection.execute(
            """
            INSERT INTO user_compute_admissions (
                resource_kind,
                resource_id,
                admitted_at
            )
            VALUES (?, ?, ?)
            """,
            (resource_kind, resource_id, admitted_at),
        )

    def _lock_idempotent_admission(
        self,
        connection: PostgresConnectionAdapter,
        *,
        operation: str,
        idempotency_key: str,
    ) -> None:
        workspace = connection.execute(
            "SELECT thesistrace_control.current_workspace_id() AS workspace_id"
        ).fetchone()
        if workspace is None or workspace["workspace_id"] is None:
            raise RuntimeError("Personal Workspace context is missing")
        lock_identity = (
            f"{workspace['workspace_id']}:{operation}:{idempotency_key}"
        )
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (lock_identity,),
        )

    def _complete_user_compute(
        self,
        connection: PostgresConnectionAdapter,
        *,
        resource_kind: str,
        resource_id: str,
        completed_at: str,
    ) -> None:
        connection.execute(
            """
            UPDATE user_compute_admissions
            SET completed_at = COALESCE(completed_at, ?)
            WHERE resource_kind = ?
              AND resource_id = ?
              AND completed_at IS NULL
            """,
            (completed_at, resource_kind, resource_id),
        )

    def _lock_dataset_publication_slot(
        self,
        connection: PostgresConnectionAdapter,
    ) -> None:
        connection.execute(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended('dataset-publication-slot', 0)
            )
            """
        )

    def request_dataset_publication(
        self,
        record: dict[str, object],
        audit_event: dict[str, object] | None,
    ) -> tuple[dict[str, object], bool]:
        if audit_event is not None or record.get("trigger_kind") != "schedule":
            raise PermissionError(
                "Data role can only request validated scheduled publications"
            )
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT publication_id, created
                FROM thesistrace_control.request_scheduled_dataset_publication(
                    ?, ?, ?, ?::jsonb, ?, ?
                )
                """,
                (
                    record["id"],
                    record["request_version"],
                    record["kind"],
                    json.dumps(
                        record["parameters"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    record["idempotency_key"],
                    record["created_at"],
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Scheduled Dataset Publication was not created")
            publication = self._dataset_publication(
                connection,
                str(row["publication_id"]),
            )
            if publication is None:
                raise RuntimeError("Scheduled Dataset Publication disappeared")
            return publication, bool(row["created"])

    def _lock_dataset_publication(
        self,
        connection: PostgresConnectionAdapter,
        publication_id: str,
    ) -> None:
        connection.execute(
            """
            SELECT id
            FROM dataset_publications
            WHERE id = ?
            FOR UPDATE
            """,
            (publication_id,),
        )

    def _lock_dataset_publication_request(
        self,
        connection: PostgresConnectionAdapter,
        idempotency_key: str,
    ) -> None:
        connection.execute(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended('dataset-publication-request:' || ?, 0)
            )
            """,
            (idempotency_key,),
        )

    def source_authorization_is_authorized(self) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT thesistrace_control.hosted_tushare_authorized()
                    AS authorized
                """
            ).fetchone()
        return bool(row and row["authorized"])


__all__ = ["PostgresControlMetadataStore"]

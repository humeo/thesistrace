from collections.abc import Sequence

import psycopg
from psycopg import sql

from thesistrace.hosted.control import hybrid_row


class PostgresExecutionOutbox:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def pending(self, *, limit: int = 25) -> list[dict[str, str]]:
        with psycopg.connect(self.database_url, row_factory=hybrid_row) as connection:
            connection.execute("BEGIN")
            connection.execute(
                sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier("thesistrace_relay"))
            )
            rows = connection.execute(
                """
                SELECT outbox_id, workspace_id, resource_kind, resource_id
                FROM thesistrace_control.pending_execution_outbox(%s)
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "outbox_id": str(row["outbox_id"]),
                "workspace_id": str(row["workspace_id"]),
                "resource_kind": str(row["resource_kind"]),
                "resource_id": str(row["resource_id"]),
            }
            for row in rows
        ]

    def mark_dispatched(self, outbox_id: str) -> bool:
        with psycopg.connect(self.database_url, row_factory=hybrid_row) as connection:
            connection.execute("BEGIN")
            connection.execute(
                sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier("thesistrace_relay"))
            )
            row = connection.execute(
                "SELECT thesistrace_control.mark_execution_dispatched(%s) AS marked",
                (outbox_id,),
            ).fetchone()
        return bool(row and row["marked"])


def require_research_entry(entry: dict[str, str]) -> Sequence[str]:
    if entry["resource_kind"] != "research_run":
        raise ValueError(f"unsupported execution resource: {entry['resource_kind']}")
    return entry["workspace_id"], entry["resource_id"]

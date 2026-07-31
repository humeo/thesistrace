import psycopg
from psycopg import sql

from thesistrace.hosted.control import hybrid_row


class PostgresExecutionOutbox:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def pending(self, *, limit: int = 25) -> list[dict[str, str | None]]:
        with psycopg.connect(self.database_url, row_factory=hybrid_row) as connection:
            connection.execute("BEGIN")
            connection.execute(
                sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier("thesistrace_relay"))
            )
            maintenance = connection.execute(
                "SELECT thesistrace_control.maintenance_enabled()"
            ).fetchone()
            if maintenance is not None and bool(maintenance[0]):
                return []
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
                "workspace_id": (
                    None
                    if row["workspace_id"] is None
                    else str(row["workspace_id"])
                ),
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


def require_research_entry(entry: dict[str, str]) -> tuple[str, str, str]:
    if entry["resource_kind"] not in {
        "research_run",
        "research_run_cancel",
        "tracking_advance",
        "tracking_equivalence",
        "tracking_equivalence_cancel",
        "tracking_generation_rebuild",
        "tracking_generation_rebuild_cancel",
    }:
        raise ValueError(f"unsupported execution resource: {entry['resource_kind']}")
    return entry["resource_kind"], entry["workspace_id"], entry["resource_id"]


def require_execution_entry(
    entry: dict[str, str | None],
) -> tuple[str, str | None, str]:
    resource_kind = str(entry["resource_kind"])
    if resource_kind == "dataset_publication":
        if entry["workspace_id"] is not None:
            raise ValueError("Dataset Publication cannot belong to a Workspace")
        return resource_kind, None, str(entry["resource_id"])
    if resource_kind == "tracking_release":
        if entry["workspace_id"] is not None:
            raise ValueError("Tracking Release fanout cannot belong to a Workspace")
        return resource_kind, None, str(entry["resource_id"])
    if entry["workspace_id"] is None:
        raise ValueError("Workspace execution requires a Workspace")
    research_entry = {
        key: str(entry[key])
        for key in ("resource_kind", "workspace_id", "resource_id")
    }
    return require_research_entry(research_entry)

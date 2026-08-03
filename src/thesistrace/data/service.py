from __future__ import annotations

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.models import DataOverview, ReleaseHistory, ReleaseSummary


class DataService:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def overview(self) -> DataOverview:
        with self._database.transaction() as transaction:
            state = transaction.execute(
                """
                SELECT status, latest_update_outcome
                FROM data.state
                WHERE singleton = 1
                """
            ).fetchone()
            latest_release = transaction.execute(
                """
                SELECT id, predecessor_id
                FROM data.releases
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if state is None:
            raise RuntimeError("Data state is not initialized")
        return DataOverview(
            status=state["status"],
            latest_release=(
                ReleaseSummary.model_validate(latest_release)
                if latest_release is not None
                else None
            ),
            latest_update_outcome=state["latest_update_outcome"],
        )

    def list_releases(self) -> ReleaseHistory:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id, predecessor_id
                FROM data.releases
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return ReleaseHistory(
            items=[ReleaseSummary.model_validate(row) for row in rows],
            next_cursor=None,
        )

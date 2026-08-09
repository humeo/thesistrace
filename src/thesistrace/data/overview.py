from __future__ import annotations

from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.head_store import DatasetHeadPointer, MountedDatasetHeadStore
from thesistrace.data.lifecycle import lock_data_lifecycle
from thesistrace.data.models import DataOverview, DatasetCoverage


class DatasetOverviewService:
    """Read the one current mounted Dataset Head without exposing its identity."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._database = database
        self._heads = MountedDatasetHeadStore(mount_root)
        self._validated_pointer: DatasetHeadPointer | None = None

    def validate_startup(self) -> None:
        self.overview()

    def overview(self) -> DataOverview:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            pointer = self._heads.current_pointer()
            if pointer is None:
                return DataOverview(
                    dataset_coverage=None,
                    data_through_session=None,
                    last_refresh_at=None,
                    readiness=False,
                )
            if pointer != self._validated_pointer:
                self._heads.resolve(pointer)
                self._validated_pointer = pointer
            state = transaction.execute(
                """
                SELECT last_refresh_at
                FROM data.current_dataset_state
                WHERE singleton = 1
                """
            ).fetchone()
            if state is None:
                raise RuntimeError("current Dataset state is not initialized")
            return DataOverview(
                dataset_coverage=DatasetCoverage(
                    start=pointer.dataset_coverage["start"],
                    end=pointer.dataset_coverage["end"],
                ),
                data_through_session=pointer.data_through_session,
                last_refresh_at=state["last_refresh_at"],
                readiness=True,
            )

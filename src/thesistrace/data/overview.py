from __future__ import annotations

from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.head_store import DatasetHeadPointer, MountedDatasetHeadStore
from thesistrace.data.lifecycle import lock_data_lifecycle
from thesistrace.data.models import DataOverview, DatasetCoverage, FinancialCoverage


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
                    market_coverage=None,
                    financial_coverage=None,
                    data_through_session=None,
                    last_market_refresh_at=None,
                    last_financial_refresh_at=None,
                    market_research_readiness=False,
                    financial_research_readiness=False,
                )
            if pointer != self._validated_pointer:
                self._heads.resolve_descriptor(pointer)
                self._validated_pointer = pointer
            descriptor = self._heads.inspect_generation(pointer.generation_manifest_sha256)
            state = transaction.execute(
                """
                SELECT last_market_refresh_at, last_financial_refresh_at
                FROM data.current_dataset_state
                WHERE singleton = 1
                """
            ).fetchone()
            if state is None:
                raise RuntimeError("current Dataset state is not initialized")
            financial = next(
                (
                    family
                    for family in descriptor.families
                    if family.family_id == "equity.financial_pit"
                ),
                None,
            )
            coverage = None if financial is None else financial.dataset_coverage
            return DataOverview(
                market_coverage=DatasetCoverage(
                    start=pointer.dataset_coverage["start"],
                    end=pointer.dataset_coverage["end"],
                ),
                financial_coverage=(
                    None
                    if coverage is None
                    else FinancialCoverage(
                        start=coverage["start"],
                        observation_through_session=coverage[
                            "observation_through_session"
                        ],
                        reconciliation_status=coverage["reconciliation_status"],
                        historical_reconciliation_watermark=coverage[
                            "historical_reconciliation_watermark"
                        ],
                        revision_coverage=coverage["revision_coverage"],
                        seed_policy=coverage["seed_policy"],
                    )
                ),
                data_through_session=pointer.data_through_session,
                last_market_refresh_at=state["last_market_refresh_at"],
                last_financial_refresh_at=state["last_financial_refresh_at"],
                market_research_readiness=True,
                financial_research_readiness=(
                    financial is not None
                    and descriptor.financial_research_readiness is not None
                    and descriptor.financial_research_readiness["status"] == "ready"
                ),
            )

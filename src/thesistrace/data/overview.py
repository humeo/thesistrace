from __future__ import annotations

from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.head_store import DatasetHeadPointer, MountedDatasetHeadStore
from thesistrace.data.lifecycle import lock_data_lifecycle
from thesistrace.data.models import (
    DataOverview,
    DatasetCoverage,
    FinancialCoverage,
    IndustryCoverage,
)


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
                    industry_coverage=None,
                    data_through_session=None,
                    last_market_refresh_at=None,
                    last_financial_refresh_at=None,
                    last_industry_refresh_at=None,
                    industry_refresh_status=None,
                    industry_refresh_failure_code=None,
                    market_research_readiness=False,
                    financial_research_readiness=False,
                    industry_research_readiness=False,
                )
            if pointer != self._validated_pointer:
                self._heads.resolve_descriptor(pointer)
                self._validated_pointer = pointer
            descriptor = self._heads.inspect_generation(pointer.generation_manifest_sha256)
            state = transaction.execute(
                """
                SELECT state.last_market_refresh_at,
                       state.last_financial_refresh_at,
                       state.last_industry_refresh_at,
                       latest.status AS industry_refresh_status,
                       latest.failure_code AS industry_refresh_failure_code
                FROM data.current_dataset_state AS state
                LEFT JOIN LATERAL (
                    SELECT status, failure_code
                    FROM data.industry_refresh_operations
                    ORDER BY created_at DESC, idempotency_key DESC
                    LIMIT 1
                ) AS latest ON true
                WHERE state.singleton = 1
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
            industry = next(
                (
                    family
                    for family in descriptor.families
                    if family.family_id == "equity.industry_membership"
                ),
                None,
            )
            industry_coverage = None if industry is None else industry.dataset_coverage
            market_start = pointer.dataset_coverage["start"]
            market_end = pointer.dataset_coverage["end"]
            return DataOverview(
                market_coverage=DatasetCoverage(
                    start=market_start,
                    end=market_end,
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
                industry_coverage=(
                    None
                    if industry_coverage is None
                    else IndustryCoverage(
                        start=industry_coverage["start"],
                        observation_through_session=industry_coverage["end"],
                    )
                ),
                data_through_session=pointer.data_through_session,
                last_market_refresh_at=state["last_market_refresh_at"],
                last_financial_refresh_at=state["last_financial_refresh_at"],
                last_industry_refresh_at=state["last_industry_refresh_at"],
                industry_refresh_status=state["industry_refresh_status"],
                industry_refresh_failure_code=state["industry_refresh_failure_code"],
                market_research_readiness=True,
                financial_research_readiness=(
                    financial is not None
                    and descriptor.financial_research_readiness is not None
                    and descriptor.financial_research_readiness["status"] == "ready"
                ),
                industry_research_readiness=(
                    industry_coverage is not None
                    and industry_coverage["start"] <= market_start
                    and industry_coverage["end"] >= market_end
                ),
            )

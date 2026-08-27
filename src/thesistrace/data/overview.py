from __future__ import annotations

from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.benchmark import (
    BenchmarkSnapshot,
    BenchmarkSnapshotError,
    BenchmarkSnapshotStore,
    validate_independent_benchmark_mount,
)
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

    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        benchmark_mount_root: Path | str,
    ) -> None:
        self._database = database
        self._heads = MountedDatasetHeadStore(mount_root)
        self._benchmark = BenchmarkSnapshotStore(
            validate_independent_benchmark_mount(mount_root, benchmark_mount_root)
        )
        self._validated_pointer: DatasetHeadPointer | None = None

    def validate_startup(self) -> None:
        self.overview()

    def overview(self) -> DataOverview:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            benchmark = self._read_benchmark()
            pointer = self._heads.current_pointer()
            if pointer is None:
                return DataOverview(
                    market_coverage=None,
                    financial_coverage=None,
                    industry_coverage=None,
                    benchmark_coverage=_benchmark_coverage(benchmark),
                    benchmark_snapshot_sha256=(
                        None if benchmark is None else benchmark.sha256
                    ),
                    benchmark_last_published_at=(
                        None if benchmark is None else benchmark.published_at
                    ),
                    data_through_session=None,
                    last_market_refresh_at=None,
                    last_financial_refresh_at=None,
                    last_industry_refresh_at=None,
                    industry_refresh_status=None,
                    industry_refresh_failure_code=None,
                    market_research_readiness=False,
                    benchmark_research_readiness=False,
                    financial_research_readiness="not_ready",
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
                    else _financial_coverage(coverage)
                ),
                industry_coverage=(
                    None
                    if industry_coverage is None
                    else IndustryCoverage(
                        start=industry_coverage["start"],
                        observation_through_session=industry_coverage["end"],
                    )
                ),
                benchmark_coverage=_benchmark_coverage(benchmark),
                benchmark_snapshot_sha256=(
                    None if benchmark is None else benchmark.sha256
                ),
                benchmark_last_published_at=(
                    None if benchmark is None else benchmark.published_at
                ),
                data_through_session=pointer.data_through_session,
                last_market_refresh_at=state["last_market_refresh_at"],
                last_financial_refresh_at=state["last_financial_refresh_at"],
                last_industry_refresh_at=state["last_industry_refresh_at"],
                industry_refresh_status=state["industry_refresh_status"],
                industry_refresh_failure_code=state["industry_refresh_failure_code"],
                market_research_readiness=True,
                benchmark_research_readiness=(
                    benchmark is not None
                    and benchmark.coverage_end_session >= market_end
                ),
                financial_research_readiness=(
                    "not_ready"
                    if financial is None or descriptor.financial_research_readiness is None
                    else str(descriptor.financial_research_readiness["status"])
                ),
                industry_research_readiness=(
                    industry_coverage is not None
                    and industry_coverage["start"] <= market_start
                    and industry_coverage["end"] >= market_end
                ),
            )

    def _read_benchmark(self) -> BenchmarkSnapshot | None:
        try:
            return self._benchmark.read()
        except (BenchmarkSnapshotError, OSError):
            return None


def _benchmark_coverage(
    snapshot: BenchmarkSnapshot | None,
) -> DatasetCoverage | None:
    if snapshot is None:
        return None
    return DatasetCoverage(
        start=snapshot.coverage_start_session,
        end=snapshot.coverage_end_session,
    )


def _financial_coverage(coverage: dict[str, object]) -> FinancialCoverage:
    kind = coverage.get("kind")
    if kind == "financial-announcement-observation-range":
        return FinancialCoverage(
            start=coverage["start"],
            discovery_baseline_session=coverage["discovery_baseline_session"],
            discovery_attempted_through_session=coverage[
                "discovery_attempted_through_session"
            ],
            discovery_complete_through_session=coverage[
                "discovery_complete_through_session"
            ],
            historical_reconciliation_watermark=coverage[
                "historical_reconciliation_watermark"
            ],
            revision_coverage=coverage["revision_coverage"],
            seed_policy=coverage["seed_policy"],
            readiness_status=coverage["readiness_status"],
            pending_instrument_count=coverage["pending_instrument_count"],
            discovery_gap_count=coverage["discovery_gap_count"],
            earliest_unresolved_date=coverage["earliest_unresolved_date"],
        )
    if kind == "financial-observation-range":
        through = coverage["observation_through_session"]
        return FinancialCoverage(
            start=coverage["start"],
            discovery_baseline_session=through,
            discovery_attempted_through_session=through,
            discovery_complete_through_session=through,
            historical_reconciliation_watermark=coverage[
                "historical_reconciliation_watermark"
            ],
            revision_coverage=coverage["revision_coverage"],
            seed_policy=coverage["seed_policy"],
            readiness_status="ready",
            pending_instrument_count=0,
            discovery_gap_count=0,
            earliest_unresolved_date=None,
        )
    raise RuntimeError("Financial Coverage kind is invalid")

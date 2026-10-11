"""Prepare one complete, retryable Dataset release without publishing its parts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.benchmark import BenchmarkLevelSource, BenchmarkSnapshotUpdater
from thesistrace.data.benchmark_snapshot import (
    BenchmarkSnapshotPreparation,
    PreparedBenchmarkSnapshots,
)
from thesistrace.data.daily_financial_refresh import DailyFinancialRefreshService
from thesistrace.data.financial_collection import FinancialRawSource
from thesistrace.data.financial_disclosures import FinancialDisclosureSource
from thesistrace.data.financial_indicator_source import FinancialIndicatorProvider
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import DatasetHeadPointer
from thesistrace.data.industry_refresh import IndustryRefreshService
from thesistrace.data.industry_source import IndustrySource
from thesistrace.data.source import DataSource, refresh_collection_plan
from thesistrace.data.validation import validate_release_batch


class UnifiedRefreshPreparation:
    def __init__(
        self,
        database: PostgresDatabase,
        root: Path,
        benchmark_root: Path,
        *,
        clock: Callable[[], datetime],
        guard: Callable[[], None],
        checkpoint: Callable[[dict[str, object]], None],
        phase: Callable[[str], AbstractContextManager[None]],
    ) -> None:
        self._database = database
        self._root = root
        self._benchmark_root = benchmark_root
        self._generations = MountedGenerationStore(root)
        self._clock = clock
        self._guard = guard
        self._checkpoint = checkpoint
        self._phase = phase

    def prepare(
        self,
        *,
        key: str,
        attempt: int,
        head: DatasetHeadPointer,
        as_of: datetime,
        saved: dict[str, object],
        source: DataSource,
        benchmark_source: BenchmarkLevelSource,
        disclosure_source: FinancialDisclosureSource,
        financial_source: FinancialRawSource,
        indicator_provider: FinancialIndicatorProvider,
        industry_source: IndustrySource,
        financial_source_window_selector: Callable[[str, str], None] | None = None,
        industry_source_target_selector: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        baseline = head.generation_manifest_sha256
        state = dict(saved)
        # A prepared family can only be reused with the exact base it was built against.
        if (
            state.get("base") != baseline
            or state.get("base_benchmark") != head.benchmark_snapshot_sha256
        ):
            state = {"base": baseline, "base_benchmark": head.benchmark_snapshot_sha256}
            self._save(state)
        predecessor = baseline
        for stage in ("market", "financial", "industry"):
            if stage in state:
                self._generations.validate_refresh_candidate(
                    str(state[stage]), predecessor_manifest_sha256=predecessor,
                )
                predecessor = str(state[stage])
        if "benchmark" in state:
            PreparedBenchmarkSnapshots(self._benchmark_root).read(str(state["benchmark"]))

        if "market" not in state:
            with self._phase("market"):
                base = self._generations.open_refresh_base(baseline)
                plan = refresh_collection_plan(
                    as_of, base.canonical, collection_key=f"refresh:{key}"
                )
                batch = source.collect(plan)
                self._guard()
                validate_release_batch(batch, predecessor_session=head.data_through_session)
                if batch.canonical == base.canonical:
                    state["market"] = baseline
                else:
                    generation = self._generations.materialize_refresh(
                        predecessor_manifest_sha256=baseline,
                        replacement_canonical=batch.canonical,
                        replace_from_session=plan.overlap_start_session,
                        prepared_at=self._clock(),
                        source_name=batch.source_name,
                        source_lineage=batch.source_lineage,
                    )
                    state["market"] = generation.manifest_sha256
                self._save(state)
        market = self._generations.inspect_root(str(state["market"]))
        target = market.data_through_session
        state["target"] = target
        if "benchmark" not in state:
            with self._phase("benchmark"):
                prepared = BenchmarkSnapshotUpdater(
                    BenchmarkSnapshotPreparation(self._benchmark_root, self._root),
                    benchmark_source,
                    clock=self._clock,
                ).update(market.research_sessions)
                state["benchmark"] = prepared.snapshot.sha256
                self._save(state)

        stage_prefix = f"dataset:{hashlib.sha256(key.encode()).hexdigest()}:{attempt}"
        if "financial" not in state:
            with self._phase("financial"):
                state["financial_key"] = f"{stage_prefix}:financial"
                self._save(state)
                prepared = DailyFinancialRefreshService(
                    self._database,
                    self._root,
                    disclosure_source,
                    financial_source,
                    indicator_provider=indicator_provider,
                    clock=self._clock,
                    ownership_guard=self._guard,
                    financial_source_window_selector=financial_source_window_selector,
                ).prepare(
                    idempotency_key=str(state["financial_key"]),
                    source_generation_manifest_sha256=market.manifest_sha256,
                    observation_through_session=target,
                )
                state["financial"] = prepared.generation_manifest_sha256
                self._save(state)
        if "industry" not in state:
            with self._phase("industry"):
                if industry_source_target_selector is not None:
                    industry_source_target_selector(target)
                state["industry_key"] = f"{stage_prefix}:industry"
                self._save(state)
                prepared = IndustryRefreshService(
                    self._database,
                    self._root,
                    industry_source,
                    clock=self._clock,
                    ownership_guard=self._guard,
                ).prepare(
                    idempotency_key=str(state["industry_key"]),
                    source_generation_manifest_sha256=str(state["financial"]),
                    observation_through_session=target,
                )
                state["industry"] = prepared.generation_manifest_sha256
                self._save(state)
        with self._phase("candidate_validation"):
            self._generations.validate_refresh_candidate(
                str(state["industry"]), predecessor_manifest_sha256=baseline,
            )
            self._guard()
        return state

    def _save(self, state: dict[str, object]) -> None:
        self._guard()
        self._checkpoint(dict(state))

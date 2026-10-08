from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from benchmark_support import FixtureBenchmarkSource, benchmark_mount_for_data_mount
from core_runtime import drop_product_schemas
from test_data_refresh import RecordingRefreshSource, UnavailableRefreshSource
from test_financial_collection import (
    ExecutableStatementSource,
    _daily_financial_replay,
    _database,
    _establish_head,
    _executable_contract,
    _financial_generation,
    _initial_candidate,
    _market_generation,
)
from test_industry_refresh import _static_source

from thesistrace.adapters.tushare_financial_indicator import TushareFinancialIndicatorProvider
from thesistrace.adapters.tushare_replay import ReplayTushareRefreshBundle
from thesistrace.benchmark import BenchmarkSnapshotError
from thesistrace.data.benchmark_snapshot import PublishedBenchmarkSnapshots
from thesistrace.data.collection import DataGarbageCollector
from thesistrace.data.daily_financial_refresh import DailyFinancialRefreshService
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import MountedDatasetHeadStore
from thesistrace.data.industry_source import IndustrySourceError
from thesistrace.data.refresh import DataRefreshError, DataRefreshService

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_refresh_state(core_settings):
    drop_product_schemas(core_settings)
    try:
        yield
    finally:
        drop_product_schemas(core_settings)


def test_financial_preparation_uses_unpublished_market_and_does_not_move_head(
    core_settings, tmp_path
):
    database = _database(core_settings)
    key = uuid4().hex
    try:
        market = _market_generation(
            tmp_path,
            sessions=("2010-01-04", "2026-08-07", "2026-08-13", "2026-08-14"),
            second_listed_to="2009-01-01",
        )
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key=f"{key}-prior",
            contract=_executable_contract(),
        )
        source = _financial_generation(tmp_path, market, prior)
        _establish_head(database, tmp_path, source, operation_id=f"{key}-source")
        head = MountedDatasetHeadStore(tmp_path).current_pointer()
        replay = tmp_path / "replay.json"
        replay.write_text(json.dumps(_daily_financial_replay(has_gap=False)))
        provider = ReplayTushareRefreshBundle((replay,))
        from thesistrace.adapters.tushare_financial_indicator import (
            TushareFinancialIndicatorProvider,
        )

        service = DailyFinancialRefreshService(
            database,
            tmp_path,
            disclosure_source=provider,
            financial_source=provider,
            indicator_provider=TushareFinancialIndicatorProvider(provider),
            clock=lambda: NOW,
        )
        prepared = service.prepare(
            idempotency_key=f"{key}-financial",
            source_generation_manifest_sha256=source,
            observation_through_session="2026-08-14",
        )
        assert prepared.generation_manifest_sha256 != source
        assert prepared.complete_through_session == "2026-08-14"
        assert MountedDatasetHeadStore(tmp_path).current_pointer() == head
    finally:
        database.close()


@pytest.mark.parametrize(
    "failed_stage,publication_crash,recovery",
    [
        ("market", False, "retry"),
        ("market", False, "fenced"),
        ("benchmark", False, "retry"),
        ("industry", False, "branch_gc"),
        ("financial", False, "retry"),
        ("industry", False, "retry"),
        ("industry", True, "retry"),
        ("industry", False, "baseline"),
        ("industry", False, "restart"),
    ],
)
def test_one_release_retries_without_exposing_partial_preparation(
    core_settings, tmp_path, failed_stage, publication_crash, recovery, monkeypatch
):
    events: list[dict[str, object]] = []
    database = _database(core_settings)
    key = uuid4().hex
    benchmark_root = benchmark_mount_for_data_mount(tmp_path)
    try:
        market = _market_generation(
            tmp_path,
            sessions=("2010-01-04", "2026-08-07", "2026-08-13", "2026-08-14"),
            second_listed_to="2009-01-01",
        )
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key=f"{key}-prior",
            contract=_executable_contract(),
        )
        original = _financial_generation(tmp_path, market, prior)
        _establish_head(database, tmp_path, original, operation_id=f"{key}-source")
        head = MountedDatasetHeadStore(tmp_path).current_pointer()
        canonical = MountedGenerationStore(tmp_path).open_refresh_base(original).canonical
        replay = tmp_path / "replay.json"
        replay.write_text(json.dumps(_daily_financial_replay(has_gap=failed_stage == "financial")))
        provider = ReplayTushareRefreshBundle((replay,))
        industry, _ = _static_source("2026-08-14")

        class WorkerStopped(BaseException):
            pass

        class BrokenIndustry:
            def collect(self, **_kwargs):
                if recovery == "restart":
                    raise WorkerStopped("injected Worker interruption")
                raise IndustrySourceError("INDUSTRY_SOURCE_UNAVAILABLE")

        class LostLeaseSource(UnavailableRefreshSource):
            def collect(self, plan):
                with database.transaction() as tx:
                    tx.execute(
                        "UPDATE data.refresh_operations "
                        "SET lease_expires_at=now()-interval '1 second' WHERE idempotency_key=%s",
                        (key,),
                    )
                return super().collect(plan)

        class BrokenBenchmark:
            def collect_open_levels(self, **_kwargs):
                raise BenchmarkSnapshotError("BENCHMARK_SOURCE_UNAVAILABLE")

        service = DataRefreshService(
            database,
            tmp_path,
            benchmark_mount_root=benchmark_root,
            clock=lambda: NOW,
            max_attempts=1,
            lifecycle_event=events.append,
        )
        accepted = service.submit_dataset(idempotency_key=key, as_of=NOW)
        assert accepted.status == "accepted"
        assert service.submit_dataset(idempotency_key=key, as_of=NOW) == accepted
        with pytest.raises(DataRefreshError, match="IDEMPOTENCY_KEY_CONFLICT"):
            service.submit_dataset(idempotency_key=key, as_of=NOW - timedelta(hours=1))
        with (
            nullcontext() if recovery == "fenced"
            else pytest.raises(WorkerStopped if recovery == "restart" else DataRefreshError)
        ):
            service.process_next(
                LostLeaseSource() if recovery == "fenced" else UnavailableRefreshSource()
                if failed_stage == "market"
                else RecordingRefreshSource(canonical),
                benchmark_source=(
                    BrokenBenchmark() if failed_stage == "benchmark" else FixtureBenchmarkSource()
                ),
                financial_disclosure_source=provider,
                financial_source=provider,
                indicator_provider=TushareFinancialIndicatorProvider(provider),
                industry_source=BrokenIndustry() if failed_stage == "industry" else industry,
            )
        assert events[0]["event"] == "data_refresh_started"
        assert events[0]["kind"] == "dataset"
        if recovery == "fenced":
            assert events[-1]["event"] == "data_refresh_fenced"
            assert events[-1]["phase"] == "market"
            assert service.inspect(key).status == "running"
            assert MountedDatasetHeadStore(tmp_path).current_pointer() == head
            return
        if recovery != "restart":
            assert events[-1]["event"] == "data_refresh_failed"
            assert events[-1]["phase"] == failed_stage
            assert not any(event["event"] == "data_refresh_succeeded" for event in events)
        if recovery == "restart":
            assert service.inspect(key).status == "running"
            with database.transaction() as tx:
                tx.execute(
                    "UPDATE data.refresh_operations SET lease_expires_at=now()-interval '1 second' "
                    "WHERE idempotency_key=%s",
                    (key,),
                )
            service = DataRefreshService(
                database,
                tmp_path,
                benchmark_mount_root=benchmark_root,
                clock=lambda: NOW,
                max_attempts=1,
                lifecycle_event=events.append,
            )
            assert service.process_next(
                UnavailableRefreshSource(), benchmark_source=FixtureBenchmarkSource()
            )
        failed = service.inspect(key)
        assert failed.status == "failed"
        assert MountedDatasetHeadStore(tmp_path).current_pointer() == head
        assert PublishedBenchmarkSnapshots(benchmark_root, tmp_path).read() is None
        expected = {
            "market": (), "benchmark": (), "financial": ("market",),
            "industry": ("market", "financial"),
        }
        assert failed.completed_stages == expected[failed_stage]

        if recovery == "baseline":
            replacement = MountedGenerationStore(tmp_path).materialize_refresh(
                predecessor_manifest_sha256=original,
                replacement_canonical=canonical,
                replace_from_session="2010-01-04",
                prepared_at=NOW + timedelta(seconds=1),
                source_name="competing-complete-base",
                source_lineage={"fixture": "changed-baseline"},
            )
            assert replacement.manifest_sha256 != original
            heads = MountedDatasetHeadStore(tmp_path)
            with heads.resolved_pointer_candidate(replacement.manifest_sha256) as candidate:
                heads.compare_and_swap_pointer_resolved(
                    expected_generation_manifest_sha256=original,
                    candidate=candidate,
                )
        if failed_stage == "industry" and recovery == "retry" and not publication_crash:
            DataGarbageCollector(database, tmp_path).collect(idempotency_key=key + "-gc")
        if recovery == "branch_gc":
            service.retry(
                source_idempotency_key=key, idempotency_key=key + "-failed-branch",
                kind="dataset", target=NOW.isoformat(),
            )
            with pytest.raises(DataRefreshError):
                service.process_next(
                    UnavailableRefreshSource(), benchmark_source=FixtureBenchmarkSource(),
                    financial_disclosure_source=provider, financial_source=provider,
                    indicator_provider=TushareFinancialIndicatorProvider(provider),
                    industry_source=BrokenIndustry(),
                )
            assert service.inspect(key + "-failed-branch").status == "failed"
        retry_key = key + "-retry"
        service.retry(
            source_idempotency_key=key,
            idempotency_key=retry_key,
            kind="dataset",
            target=NOW.isoformat(),
        )
        with pytest.raises(DataRefreshError, match="REFRESH_NOT_RETRYABLE"):
            service.retry(
                source_idempotency_key=key,
                idempotency_key=key + "-duplicate",
                kind="dataset",
                target=NOW.isoformat(),
            )
        replay.write_text(json.dumps(_daily_financial_replay(has_gap=False)))
        provider = ReplayTushareRefreshBundle((replay,))
        # Recreate the Worker to prove all resumable state is durable.
        service = DataRefreshService(
            database, tmp_path, benchmark_mount_root=benchmark_root, clock=lambda: NOW,
            lifecycle_event=events.append,
        )

        def resume():
            return service.process_next(
                RecordingRefreshSource(canonical)
                if failed_stage == "market" or recovery == "baseline"
                else UnavailableRefreshSource(),
                benchmark_source=FixtureBenchmarkSource(),
                financial_disclosure_source=provider,
                financial_source=provider,
                indicator_provider=TushareFinancialIndicatorProvider(provider),
                industry_source=industry,
            )

        if publication_crash:

            def interrupted(*_args):
                raise RuntimeError("injected completion outage")

            with monkeypatch.context() as patch:
                patch.setattr(service, "_complete_published", interrupted)
                with pytest.raises(DataRefreshError, match="REFRESH_COMPLETION_PENDING"):
                    resume()
            assert service.inspect(retry_key).status == "running"
            service = DataRefreshService(
                database, tmp_path, benchmark_mount_root=benchmark_root, clock=lambda: NOW,
                lifecycle_event=events.append,
            )
            assert service.process_next(
                UnavailableRefreshSource(), benchmark_source=FixtureBenchmarkSource()
            )
        else:
            assert resume()
        assert events[-1]["event"] == "data_refresh_succeeded"
        assert events[-1]["outcome"] == "published"
        phases = {
            event["phase"] for event in events
            if event["event"] == "data_refresh_phase_completed"
        }
        assert {"market", "benchmark", "financial", "industry", "candidate_validation"} <= phases
        assert "publication" in phases
        assert all(event["duration_ms"] >= 0 for event in events if "duration_ms" in event)
        result = service.inspect(retry_key)
        assert result.status == "succeeded"
        assert result.outcome == "published"
        assert result.completed_stages == ("market", "financial", "industry")
        assert service.inspect(key).status == "failed"
        with pytest.raises(DataRefreshError, match="REFRESH_NOT_RETRYABLE"):
            service.retry(
                source_idempotency_key=key,
                idempotency_key=key + "-after-publication",
                kind="dataset",
                target=NOW.isoformat(),
            )
        published = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert published.generation_manifest_sha256 != original
        assert published.benchmark_snapshot_sha256 is not None
        if recovery == "branch_gc":
            with database.transaction() as tx:
                tx.execute(
                    "UPDATE data.refresh_operations SET finished_at=%s WHERE idempotency_key=%s",
                    (NOW - timedelta(days=181), key),
                )
            collector = DataGarbageCollector(
                database, tmp_path, clock=lambda: NOW, receipt_cleanup_limit=1,
            )
            assert collector.collect(idempotency_key=key + "-gc-lineage").deleted_receipt_count == 0
            with pytest.raises(DataRefreshError, match="REFRESH_NOT_RETRYABLE"):
                service.retry(
                    source_idempotency_key=key + "-failed-branch",
                    idempotency_key=key + "-after-gc", kind="dataset", target=NOW.isoformat(),
                )
            assert MountedDatasetHeadStore(tmp_path).current_pointer() == published
            with database.transaction() as tx:
                tx.execute(
                    "UPDATE data.refresh_operations SET finished_at=%s "
                    "WHERE idempotency_key=ANY(%s)",
                    (NOW - timedelta(days=181), [key, retry_key, key + "-failed-branch"]),
                )
            assert collector.collect(idempotency_key=key + "-gc-expired").deleted_receipt_count == 3
            with pytest.raises(DataRefreshError, match="REFRESH_NOT_FOUND"):
                service.inspect(key + "-failed-branch")
        assert (
            PublishedBenchmarkSnapshots(benchmark_root, tmp_path).read().coverage_end_session
            == "2026-08-14"
        )
        with database.transaction() as tx:
            times = tx.execute(
                "SELECT last_market_refresh_at, last_financial_refresh_at, "
                "last_industry_refresh_at "
                "FROM data.current_dataset_state"
            ).fetchone()
        assert (
            times["last_market_refresh_at"]
            == times["last_financial_refresh_at"]
            == times["last_industry_refresh_at"]
        )
    finally:
        with database.transaction() as tx:
            tx.execute(
                "DELETE FROM data.refresh_operations WHERE idempotency_key=ANY(%s)",
                ([key, key + "-retry"],),
            )
        database.close()

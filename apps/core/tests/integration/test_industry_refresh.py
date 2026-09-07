from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from benchmark_support import FixtureBenchmarkSource, benchmark_mount_for_data_mount

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_industry import (
    IndustrySourceError,
    IndustrySourceSnapshot,
    TushareIndustrySource,
)
from thesistrace.adapters.tushare_replay import ReplayTushareProvider
from thesistrace.data import (
    DataGarbageCollector,
    DataRefreshService,
    DatasetLifecycle,
    DatasetOverviewService,
    IndustryRefreshError,
    IndustryRefreshService,
    MountedGenerationStore,
)
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_fixture, build_minimal_canonical_fixture
from thesistrace.publication.serialization import canonical_json_bytes

NOW = datetime(2026, 8, 14, 1, tzinfo=UTC)


def test_shared_worker_publishes_and_then_records_replay_no_change(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market)
        through = MountedGenerationStore(tmp_path).inspect_root(market).data_through_session
        source = TushareIndustrySource(
            ReplayTushareProvider(
                Path(__file__).resolve().parents[4]
                / "tests/fixtures"
                / "tushare-operator-console-market-refresh-replay.json"
            )
        )
        refresh = DataRefreshService(
            database,
            tmp_path,
            benchmark_mount_root=benchmark_mount_for_data_mount(tmp_path),
            clock=lambda: NOW,
        )

        accepted = refresh.submit_industry(
            idempotency_key="shared-industry-published",
            observation_through_session=through,
        )
        assert accepted.status == "accepted"
        assert (
            refresh.process_next(
                object(),  # type: ignore[arg-type]
                benchmark_source=FixtureBenchmarkSource(),
                industry_source=source,
            )
            is True
        )
        published = refresh.inspect("shared-industry-published")
        assert published.status == "succeeded"
        assert published.outcome == "published"
        first_head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert first_head is not None
        assert first_head.generation_manifest_sha256 != market

        no_change_accepted = refresh.submit_industry(
            idempotency_key="shared-industry-no-change",
            observation_through_session=through,
        )
        assert no_change_accepted.status == "accepted"
        assert (
            refresh.process_next(
                object(),  # type: ignore[arg-type]
                benchmark_source=FixtureBenchmarkSource(),
                industry_source=source,
            )
            is True
        )
        no_change = refresh.inspect("shared-industry-no-change")
        assert no_change.status == "succeeded"
        assert no_change.outcome == "no_change"
        second_head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert second_head == first_head
        assert (
            refresh.submit_industry(
                idempotency_key="shared-industry-no-change",
                observation_through_session=through,
            )
            == no_change
        )
    finally:
        database.close()


def _overview_service(
    database: PostgresDatabase,
    mount_root: Path,
) -> DatasetOverviewService:
    return DatasetOverviewService(
        database,
        mount_root,
        benchmark_mount_for_data_mount(mount_root),
    )


class StaticIndustrySource:
    def __init__(self, snapshot: IndustrySourceSnapshot) -> None:
        self.snapshot = snapshot
        self.allowed_codes: set[str] | None = None
        self.calls = 0

    def collect(self, *, allowed_codes: set[str]) -> IndustrySourceSnapshot:
        self.calls += 1
        self.allowed_codes = allowed_codes
        return self.snapshot


class ConflictingIndustrySource:
    def collect(self, *, allowed_codes: set[str]) -> IndustrySourceSnapshot:
        del allowed_codes
        payload = {
            "source": "tushare",
            "source_contract_version": "tushare-industry-v1",
            "memberships": [{"ts_code": "000001.SZ"}],
        }
        lineage = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        raise IndustrySourceError(
            "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
            diagnostic={"instrument_id": "equity:000001.SZ", "overlap_count": 1},
            source_lineage_sha256=lineage,
            raw_payload=payload,
        )


class BlockingIndustrySource(StaticIndustrySource):
    def __init__(
        self,
        snapshot: IndustrySourceSnapshot,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(snapshot)
        self.entered = entered
        self.release = release

    def collect(self, *, allowed_codes: set[str]) -> IndustrySourceSnapshot:
        self.entered.set()
        assert self.release.wait(timeout=10)
        return super().collect(allowed_codes=allowed_codes)


def test_industry_refresh_publishes_only_industry_family(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market)
        through = MountedGenerationStore(tmp_path).inspect_root(market).data_through_session
        source, instrument = _static_source(through)

        service = IndustryRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: NOW,
        )
        outcome = service.publish(
            idempotency_key="industry-success",
            observation_through_session=through,
        )
        repeated = service.publish(
            idempotency_key="industry-success",
            observation_through_session=through,
        )

        current = DatasetLifecycle(database, tmp_path).current_pointer()
        assert current is not None
        assert outcome.generation_manifest_sha256 == current.generation_manifest_sha256
        before = MountedGenerationStore(tmp_path).inspect_root(market)
        after = MountedGenerationStore(tmp_path).inspect_root(current.generation_manifest_sha256)
        assert after.industry_publication_coordinate == outcome.fingerprint
        assert {
            family.family_id: family.manifest_sha256
            for family in after.families
            if family.family_id != "equity.industry_membership"
        } == {family.family_id: family.manifest_sha256 for family in before.families}
        assert source.allowed_codes == {str(instrument["ts_code"])}
        assert source.calls == 1
        assert repeated == outcome
        assert IndustryRefreshService(database, tmp_path, source).inspect(
            "industry-success"
        )["status"] == "succeeded"
        overview = _overview_service(database, tmp_path).overview()
        assert overview.industry_coverage is not None
        assert overview.industry_coverage.model_dump(mode="json") == {
            "start": through,
            "observation_through_session": through,
            "classification_version": "SW2021",
        }
        assert overview.last_industry_refresh_at == NOW
        assert overview.industry_refresh_status == "succeeded"
        assert overview.industry_refresh_failure_code is None
        assert overview.industry_research_readiness is True
    finally:
        database.close()


def test_data_overview_marks_lagging_industry_coverage_stale(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        _source, canonical = build_fixture(session_count=2)
        del canonical["industry_membership"]
        market = MountedGenerationStore(tmp_path).materialize(
            canonical,
            prepared_at=NOW,
            source_name="industry-overview-stale-test",
            source_lineage={"fixture": "market"},
        ).manifest_sha256
        _establish_head(database, tmp_path, market)
        first_session = str(canonical["research_calendar"][0])
        source, _instrument = _static_source(first_session)
        IndustryRefreshService(database, tmp_path, source, clock=lambda: NOW).publish(
            idempotency_key="industry-stale",
            observation_through_session=first_session,
        )

        overview = _overview_service(database, tmp_path).overview()
        assert overview.industry_coverage is not None
        assert overview.industry_coverage.observation_through_session.isoformat() == first_session
        assert overview.industry_refresh_status == "succeeded"
        assert overview.industry_research_readiness is False
    finally:
        database.close()


def test_industry_publication_recovers_after_head_moved_before_completion(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market)
        through = MountedGenerationStore(tmp_path).inspect_root(market).data_through_session
        source, _instrument = _static_source(through)
        interrupted = IndustryRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: NOW,
        )
        monkeypatch.setattr(
            interrupted,
            "_complete_publication",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected completion crash")
            ),
        )

        with pytest.raises(RuntimeError, match="injected completion crash"):
            interrupted.publish(
                idempotency_key="industry-recovery",
                observation_through_session=through,
            )

        moved = DatasetLifecycle(database, tmp_path).current_pointer()
        assert moved is not None
        assert moved.generation_manifest_sha256 != market
        recovered = IndustryRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: NOW,
        ).publish(
            idempotency_key="industry-recovery",
            observation_through_session=through,
        )
        assert recovered.generation_manifest_sha256 == moved.generation_manifest_sha256
        assert source.calls == 1
    finally:
        database.close()


def test_completed_industry_candidate_is_retained_until_publication(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market)
        through = MountedGenerationStore(tmp_path).inspect_root(market).data_through_session
        source, _instrument = _static_source(through)
        interrupted = IndustryRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: NOW,
        )
        monkeypatch.setattr(
            interrupted,
            "_publish_candidate",
            lambda _outcome: (_ for _ in ()).throw(
                RuntimeError("injected pre-publication crash")
            ),
        )

        with pytest.raises(RuntimeError, match="injected pre-publication crash"):
            interrupted.publish(
                idempotency_key="industry-retained-candidate",
                observation_through_session=through,
            )

        operation = interrupted.inspect("industry-retained-candidate")
        candidate = str(operation["candidate_manifest_sha256"])
        DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="collect-with-industry-candidate"
        )
        MountedGenerationStore(tmp_path).open_industry_candidate(candidate)
        recovered = IndustryRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: NOW,
        ).publish(
            idempotency_key="industry-retained-candidate",
            observation_through_session=through,
        )
        assert recovered.candidate.manifest_sha256 == candidate
        assert source.calls == 1
    finally:
        database.close()


def test_overlapping_industry_refresh_fails_without_moving_head(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market)
        through = MountedGenerationStore(tmp_path).inspect_root(market).data_through_session
        service = IndustryRefreshService(
            database,
            tmp_path,
            ConflictingIndustrySource(),
            clock=lambda: NOW,
        )

        with pytest.raises(
            IndustryRefreshError,
            match="OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION",
        ):
            service.publish(
                idempotency_key="industry-overlap",
                observation_through_session=through,
            )

        current = DatasetLifecycle(database, tmp_path).current_pointer()
        assert current is not None
        assert current.generation_manifest_sha256 == market
        operation = service.inspect("industry-overlap")
        assert operation["status"] == "failed"
        assert operation["failure_code"] == (
            "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION"
        )
        assert operation["candidate_manifest_sha256"] is None
        assert operation["source_lineage_sha256"] is not None
        overview = _overview_service(database, tmp_path).overview()
        assert overview.industry_coverage is None
        assert overview.last_industry_refresh_at is None
        assert overview.industry_refresh_status == "failed"
        assert overview.industry_refresh_failure_code == (
            "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION"
        )
        assert overview.industry_research_readiness is False
    finally:
        database.close()


def test_industry_refresh_rejects_a_concurrently_replaced_industry_target(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    publisher_database = PostgresDatabase(core_settings.database_url)
    publisher_database.open()
    entered = threading.Event()
    release = threading.Event()
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market)
        through = MountedGenerationStore(tmp_path).inspect_root(market).data_through_session
        blocked_source, _instrument = _static_source(through)
        blocked = BlockingIndustrySource(blocked_source.snapshot, entered, release)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                IndustryRefreshService(
                    database,
                    tmp_path,
                    blocked,
                    clock=lambda: NOW,
                ).publish,
                idempotency_key="industry-loser",
                observation_through_session=through,
            )
            assert entered.wait(timeout=10)
            winner_source, _instrument = _static_source(through)
            winner = IndustryRefreshService(
                publisher_database,
                tmp_path,
                winner_source,
                clock=lambda: NOW,
            ).publish(
                idempotency_key="industry-winner",
                observation_through_session=through,
            )
            release.set()
            with pytest.raises(IndustryRefreshError, match="INDUSTRY_TARGET_CHANGED"):
                future.result(timeout=10)

        current = DatasetLifecycle(database, tmp_path).current_pointer()
        assert current is not None
        assert current.generation_manifest_sha256 == winner.generation_manifest_sha256
        failed = IndustryRefreshService(
            database,
            tmp_path,
            blocked,
        ).inspect("industry-loser")
        assert failed["status"] == "failed"
        assert failed["failure_code"] == "INDUSTRY_TARGET_CHANGED"
        assert failed["candidate_manifest_sha256"] is None
    finally:
        release.set()
        publisher_database.close()
        database.close()


def test_industry_refresh_recomposes_after_concurrent_unaffected_publication(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    publisher_database = PostgresDatabase(core_settings.database_url)
    publisher_database.open()
    entered = threading.Event()
    release = threading.Event()
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market)
        through = MountedGenerationStore(tmp_path).inspect_root(market).data_through_session
        source, _instrument = _static_source(through)
        blocked = BlockingIndustrySource(source.snapshot, entered, release)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                IndustryRefreshService(
                    database,
                    tmp_path,
                    blocked,
                    clock=lambda: NOW,
                ).publish,
                idempotency_key="industry-after-market",
                observation_through_session=through,
            )
            assert entered.wait(timeout=10)
            canonical = build_minimal_canonical_fixture()
            del canonical["industry_membership"]
            concurrent = MountedGenerationStore(tmp_path).materialize(
                canonical,
                prepared_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
                source_name="concurrent-market-publication",
                source_lineage={"fixture": "concurrent"},
            )
            lifecycle = DatasetLifecycle(publisher_database, tmp_path)
            lifecycle.protect_candidate(
                operation_id="concurrent-market-head",
                generation_manifest_sha256=concurrent.manifest_sha256,
                lease_seconds=60,
            )
            lifecycle.compare_and_swap_head(
                expected_generation_manifest_sha256=market,
                candidate_generation_manifest_sha256=concurrent.manifest_sha256,
                operation_id="concurrent-market-head",
            )
            release.set()
            outcome = future.result(timeout=10)

        published = MountedGenerationStore(tmp_path).inspect_root(
            outcome.generation_manifest_sha256 or ""
        )
        assert {
            family.family_id: family.manifest_sha256
            for family in published.families
            if family.family_id != "equity.industry_membership"
        } == {
            family.family_id: family.manifest_sha256
            for family in concurrent.families
        }
    finally:
        release.set()
        publisher_database.close()
        database.close()


def _market_generation(root: Path) -> str:
    canonical = build_minimal_canonical_fixture()
    del canonical["industry_membership"]
    return MountedGenerationStore(root).materialize(
        canonical,
        prepared_at=NOW,
        source_name="industry-refresh-test",
        source_lineage={"fixture": "market"},
    ).manifest_sha256


def _static_source(through: str) -> tuple[StaticIndustrySource, dict[str, object]]:
    canonical = build_minimal_canonical_fixture()
    instrument = canonical["instruments"][0]
    raw = {
        "l1_code": "801780",
        "l2_code": "801783",
        "l3_code": "851911",
        "ts_code": instrument["ts_code"],
        "in_date": through.replace("-", ""),
        "out_date": "",
        "is_new": "Y",
    }
    payload = {
        "source": "tushare",
        "source_contract_version": "tushare-industry-v1",
        "classification_version": "SW2021",
        "classifications": [],
        "memberships": [raw],
    }
    return (
        StaticIndustrySource(
            IndustrySourceSnapshot(
                memberships=(
                    {
                        "instrument_id": instrument["instrument_id"],
                        "active_from": through,
                        "active_to": "",
                        "sw2021_l1": "801780",
                        "sw2021_l2": "801783",
                        "sw2021_l3": "851911",
                    },
                ),
                raw_classifications=(),
                raw_memberships=(raw,),
                source_lineage_sha256=hashlib.sha256(
                    canonical_json_bytes(payload)
                ).hexdigest(),
            )
        ),
        instrument,
    )


def _establish_head(database: PostgresDatabase, root: Path, generation: str) -> None:
    lifecycle = DatasetLifecycle(database, root)
    lifecycle.protect_candidate(
        operation_id="industry-test-head",
        generation_manifest_sha256=generation,
        lease_seconds=60,
    )
    lifecycle.compare_and_swap_head(
        expected_generation_manifest_sha256=None,
        candidate_generation_manifest_sha256=generation,
        operation_id="industry-test-head",
    )


def _database(settings: CoreSettings) -> PostgresDatabase:
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    with database.transaction() as transaction:
        transaction.execute(
            "TRUNCATE data.refresh_operations, data.industry_refresh_operations, "
            "data.generation_pins, data.generation_candidates"
        )
        transaction.execute(
            "UPDATE data.current_dataset_state SET last_industry_refresh_at = NULL"
        )
    return database

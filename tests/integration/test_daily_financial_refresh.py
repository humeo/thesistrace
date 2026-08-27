from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DataCollectionError, DataGarbageCollector
from thesistrace.data.daily_financial_refresh import (
    DailyFinancialStatementCollector,
    FinancialDailyRefreshStore,
    FinancialPendingInstrument,
    financial_discovery_window,
)
from thesistrace.data.financial_announcements import (
    FINANCIAL_ANNOUNCEMENT_CATEGORIES,
    FinancialAnnouncement,
    FinancialAnnouncementDiscovery,
    FinancialDiscoveryGap,
)
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    FinancialCollectionContract,
    FinancialDateShard,
    FinancialShardCheckpoint,
)
from thesistrace.data.generation_store import HistoricalInstrumentIdentity
from thesistrace.data.source import RawSourceError, RawSourceResponse
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core

FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "revenue",
    "update_flag",
)


def test_running_daily_financial_refresh_fences_garbage_collection(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        FinancialDailyRefreshStore(database).begin(
            idempotency_key="daily-financial-gc-fence",
            source_generation_manifest_sha256="a" * 64,
            prior_financial_manifest_sha256="b" * 64,
            discovery_baseline_session="2026-08-13",
            prior_attempted_through_session="2026-08-13",
            prior_complete_through_session="2026-08-13",
            target_session="2026-08-14",
            started_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
        )

        with pytest.raises(DataCollectionError) as rejected:
            DataGarbageCollector(database, tmp_path).collect(
                idempotency_key="gc-during-daily-financial"
            )

        assert rejected.value.code == "COLLECTION_DATA_WORK_ACTIVE"
    finally:
        database.close()


class _StatementSource:
    def query_raw(
        self,
        api_name: str,
        *,
        params: dict[str, object],
        fields: tuple[str, ...],
    ) -> RawSourceResponse:
        assert fields == FIELDS
        ts_code = str(params["ts_code"])
        if ts_code == "000002.SZ" and api_name == "balancesheet":
            raise RawSourceError("upstream unavailable")
        published_date = "20260818" if api_name == "income" else "20260817"
        return RawSourceResponse(
            fields=FIELDS,
            items=(
                (
                    ts_code,
                    published_date,
                    "",
                    "20260630",
                    "1",
                    "1",
                    "2",
                    "100",
                    "0",
                ),
            ),
        )


def test_targeted_collection_accepts_three_statements_atomically_per_instrument(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        outcome = DailyFinancialStatementCollector(
            database,
            tmp_path,
            _StatementSource(),
            clock=lambda: datetime(2026, 8, 18, 10, tzinfo=UTC),
        ).collect(
            idempotency_key="daily-financial-20260818",
            generation_manifest_sha256="a" * 64,
            contract=_contract(),
            identities=(
                HistoricalInstrumentIdentity("equity:000001.SZ", "000001.SZ"),
                HistoricalInstrumentIdentity("equity:000002.SZ", "000002.SZ"),
            ),
        )

        assert outcome.snapshot.target_count == 3
        assert {item.endpoint for item in outcome.snapshot.shards} == set(FINANCIAL_ENDPOINTS)
        assert {item.instrument_id for item in outcome.snapshot.shards} == {
            "equity:000001.SZ"
        }
        assert outcome.pending == (
            FinancialPendingInstrument(
                instrument_id="equity:000002.SZ",
                ts_code="000002.SZ",
                failure_code="SOURCE_FAILURE",
                failure_endpoint="balancesheet",
            ),
        )
        assert len(tuple((tmp_path / "financial" / "raw").rglob("*.json"))) == 3
    finally:
        database.close()


def test_discovery_store_persists_partial_progress_without_losing_pending_stocks(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    operation_key = "daily-financial-discovery-partial-20260814"
    store = FinancialDailyRefreshStore(database)
    identities = (
        HistoricalInstrumentIdentity("equity:000001.SZ", "000001.SZ"),
        HistoricalInstrumentIdentity("equity:000002.SZ", "000002.SZ"),
    )
    try:
        store.begin(
            idempotency_key=operation_key,
            source_generation_manifest_sha256="a" * 64,
            prior_financial_manifest_sha256="b" * 64,
            discovery_baseline_session="2026-08-13",
            prior_attempted_through_session="2026-08-13",
            prior_complete_through_session="2026-08-13",
            target_session="2026-08-14",
            started_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
        )
        store.record_discovery(
            idempotency_key=operation_key,
            discovery=FinancialAnnouncementDiscovery(
                start_date="2026-08-07",
                end_date="2026-08-14",
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES[:-1],
                announcements=(
                    _announcement("1" * 64, "000001.SZ"),
                    _announcement("2" * 64, "000002.SZ"),
                ),
                gaps=(
                    FinancialDiscoveryGap(
                        category="补充更正",
                        start_date="2026-08-07",
                        end_date="2026-08-14",
                        failure_code="CNINFO_DISCOVERY_UNAVAILABLE",
                    ),
                ),
                source_lineage_sha256="c" * 64,
            ),
            identities=identities,
            recorded_at=datetime(2026, 8, 14, 9, 1, tzinfo=UTC),
        )

        assert store.pending_identities(operation_key) == identities
        store.record_instrument_attempt(
            idempotency_key=operation_key,
            instrument_id="equity:000001.SZ",
            status="accepted",
            matched_announcement_ids=("1" * 64,),
            checkpoints=_accepted_checkpoints("equity:000001.SZ", "000001.SZ"),
            failure_code=None,
            failure_endpoint=None,
            attempted_at=datetime(2026, 8, 14, 9, 2, tzinfo=UTC),
        )
        store.record_instrument_attempt(
            idempotency_key=operation_key,
            instrument_id="equity:000002.SZ",
            status="failed",
            matched_announcement_ids=(),
            checkpoints=(),
            failure_code="SOURCE_FAILURE",
            failure_endpoint="balancesheet",
            attempted_at=datetime(2026, 8, 14, 9, 3, tzinfo=UTC),
        )

        publication = store.publication_state(operation_key)
        assert publication.attempted_through_session == "2026-08-14"
        assert publication.complete_through_session == "2026-08-13"
        assert publication.readiness_status == "ready_with_gaps"
        assert publication.pending_instrument_count == 1
        assert publication.discovery_gap_count == 1
        assert publication.earliest_unresolved_date == "2026-08-14"
        inspection = store.inspect(operation_key)
        assert inspection.status == "running"
        assert inspection.matched_trigger_count == 1
        assert inspection.pending_trigger_count == 1
        assert inspection.failed_instrument_count == 1
    finally:
        _delete_operation(database, operation_key)
        database.close()


def test_failed_pull_stays_pending_but_first_accepted_no_change_closes_trigger(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    store = FinancialDailyRefreshStore(database)
    operation_prefix = "daily-financial-no-structured-change-"
    identity = HistoricalInstrumentIdentity("equity:000001.SZ", "000001.SZ")
    failed_key = f"{operation_prefix}failed"
    accepted_key = f"{operation_prefix}accepted"
    try:
        store.begin(
            idempotency_key=failed_key,
            source_generation_manifest_sha256="1" * 64,
            prior_financial_manifest_sha256="b" * 64,
            discovery_baseline_session="2026-08-13",
            prior_attempted_through_session="2026-08-13",
            prior_complete_through_session="2026-08-13",
            target_session="2026-08-14",
            started_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
        )
        store.record_discovery(
            idempotency_key=failed_key,
            discovery=FinancialAnnouncementDiscovery(
                start_date="2026-08-07",
                end_date="2026-08-14",
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES,
                announcements=(_announcement("3" * 64, "000001.SZ"),),
                gaps=(),
                source_lineage_sha256="4" * 64,
            ),
            identities=(identity,),
            recorded_at=datetime(2026, 8, 14, 9, 1, tzinfo=UTC),
        )
        store.record_instrument_attempt(
            idempotency_key=failed_key,
            instrument_id=identity.instrument_id,
            status="failed",
            matched_announcement_ids=(),
            checkpoints=(),
            failure_code="SOURCE_FAILURE",
            failure_endpoint="income",
            attempted_at=datetime(2026, 8, 14, 9, 2, tzinfo=UTC),
        )

        failed_publication = store.publication_state(failed_key)
        assert failed_publication.readiness_status == "ready_with_pending"
        assert failed_publication.pending_instrument_count == 1
        assert store.inspect(failed_key).checked_no_structured_change_count == 0

        store.begin(
            idempotency_key=accepted_key,
            source_generation_manifest_sha256="2" * 64,
            prior_financial_manifest_sha256="b" * 64,
            discovery_baseline_session="2026-08-13",
            prior_attempted_through_session="2026-08-14",
            prior_complete_through_session="2026-08-14",
            target_session="2026-08-17",
            started_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
        )
        store.record_discovery(
            idempotency_key=accepted_key,
            discovery=FinancialAnnouncementDiscovery(
                start_date="2026-08-08",
                end_date="2026-08-17",
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES,
                announcements=(),
                gaps=(),
                source_lineage_sha256="5" * 64,
            ),
            identities=(identity,),
            recorded_at=datetime(2026, 8, 17, 9, 1, tzinfo=UTC),
        )
        store.record_instrument_attempt(
            idempotency_key=accepted_key,
            instrument_id=identity.instrument_id,
            status="accepted",
            matched_announcement_ids=(),
            checkpoints=_accepted_checkpoints(
                identity.instrument_id,
                identity.ts_code,
            ),
            failure_code=None,
            failure_endpoint=None,
            attempted_at=datetime(2026, 8, 17, 9, 2, tzinfo=UTC),
        )

        accepted_publication = store.publication_state(accepted_key)
        assert accepted_publication.readiness_status == "ready"
        assert accepted_publication.pending_instrument_count == 0
        assert store.inspect(accepted_key).checked_no_structured_change_count == 1
        with database.transaction() as transaction:
            trigger = transaction.execute(
                """
                SELECT status, resolution_code, accepted_no_match_count,
                       last_attempt_operation_key
                FROM data.financial_announcement_triggers
                WHERE announcement_id = %s
                """,
                ("3" * 64,),
            ).fetchone()
        assert trigger is not None
        assert dict(trigger) == {
            "status": "checked_no_structured_change",
            "resolution_code": "checked_no_structured_change",
            "accepted_no_match_count": 5,
            "last_attempt_operation_key": accepted_key,
        }
    finally:
        _delete_operations(database, operation_prefix)
        database.close()


def test_complete_discovery_resolves_prior_gap_and_catches_up_complete_through(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    store = FinancialDailyRefreshStore(database)
    operation_prefix = "daily-financial-resolve-gap-"
    identity = HistoricalInstrumentIdentity("equity:000001.SZ", "000001.SZ")
    try:
        first_key = f"{operation_prefix}20260814"
        store.begin(
            idempotency_key=first_key,
            source_generation_manifest_sha256="d" * 64,
            prior_financial_manifest_sha256="e" * 64,
            discovery_baseline_session="2026-08-13",
            prior_attempted_through_session="2026-08-13",
            prior_complete_through_session="2026-08-13",
            target_session="2026-08-14",
            started_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
        )
        store.record_discovery(
            idempotency_key=first_key,
            discovery=_gap_discovery(end_date="2026-08-14", lineage="f" * 64),
            identities=(identity,),
            recorded_at=datetime(2026, 8, 14, 9, 1, tzinfo=UTC),
        )
        assert store.publication_state(first_key).complete_through_session == "2026-08-13"

        second_key = f"{operation_prefix}20260817"
        store.begin(
            idempotency_key=second_key,
            source_generation_manifest_sha256="1" * 64,
            prior_financial_manifest_sha256="e" * 64,
            discovery_baseline_session="2026-08-13",
            prior_attempted_through_session="2026-08-14",
            prior_complete_through_session="2026-08-13",
            target_session="2026-08-17",
            started_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
        )
        store.record_discovery(
            idempotency_key=second_key,
            discovery=FinancialAnnouncementDiscovery(
                start_date="2026-08-08",
                end_date="2026-08-17",
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES,
                announcements=(),
                gaps=(),
                source_lineage_sha256="2" * 64,
            ),
            identities=(identity,),
            recorded_at=datetime(2026, 8, 17, 9, 1, tzinfo=UTC),
        )

        publication = store.publication_state(second_key)
        assert publication.complete_through_session == "2026-08-17"
        assert publication.discovery_gap_count == 0
        assert publication.readiness_status == "ready"
    finally:
        _delete_operations(database, operation_prefix)
        database.close()


def test_discovery_window_keeps_seven_day_overlap_and_reopens_older_gap() -> None:
    assert financial_discovery_window(
        complete_through_session="2026-08-13",
        target_session="2026-08-14",
        earliest_unresolved_date=None,
    ) == ("2026-08-07", "2026-08-14")
    assert financial_discovery_window(
        complete_through_session="2026-08-13",
        target_session="2026-08-18",
        earliest_unresolved_date="2026-07-01",
    ) == ("2026-07-01", "2026-08-18")


def _contract() -> FinancialCollectionContract:
    return FinancialCollectionContract(
        capability_sha256="b" * 64,
        endpoint_fields=tuple((endpoint, FIELDS) for endpoint in FINANCIAL_ENDPOINTS),
        suspected_truncation_row_counts=tuple(
            (endpoint, None) for endpoint in FINANCIAL_ENDPOINTS
        ),
        shards=(FinancialDateShard("complete-history"),),
    )


def _announcement(announcement_id: str, ts_code: str) -> FinancialAnnouncement:
    return FinancialAnnouncement(
        announcement_id=announcement_id,
        category="半年报",
        ts_code=ts_code,
        name=ts_code,
        title=f"{ts_code} 2026年半年度报告",
        source_published_date="2026-08-14",
        report_period="2026-06-30",
        url=f"https://example.test/{announcement_id}",
    )


def _gap_discovery(*, end_date: str, lineage: str) -> FinancialAnnouncementDiscovery:
    return FinancialAnnouncementDiscovery(
        start_date="2026-08-07",
        end_date=end_date,
        completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES[:-1],
        announcements=(),
        gaps=(
            FinancialDiscoveryGap(
                category="补充更正",
                start_date="2026-08-07",
                end_date=end_date,
                failure_code="CNINFO_DISCOVERY_UNAVAILABLE",
            ),
        ),
        source_lineage_sha256=lineage,
    )


def _accepted_checkpoints(
    instrument_id: str,
    ts_code: str,
) -> tuple[FinancialShardCheckpoint, ...]:
    return tuple(
        FinancialShardCheckpoint(
            ordinal=ordinal,
            endpoint=endpoint,
            instrument_id=instrument_id,
            ts_code=ts_code,
            shard="complete-history",
            status="completed",
            batch_sha256=f"{ordinal + 7:x}" * 64,
            collected_at="2026-08-14T09:02:00+00:00",
            first_observed_at="2026-08-14T09:02:00+00:00",
        )
        for ordinal, endpoint in enumerate(FINANCIAL_ENDPOINTS)
    )


def _database(settings: CoreSettings) -> PostgresDatabase:
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    with database.transaction() as transaction:
        transaction.execute(
            "TRUNCATE data.financial_daily_refresh_operations, "
            "data.financial_raw_batches CASCADE"
        )
        transaction.execute(
            "UPDATE data.current_dataset_state SET last_financial_refresh_at = NULL "
            "WHERE singleton = 1"
        )
    return database


def _delete_operation(database: PostgresDatabase, idempotency_key: str) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            "DELETE FROM data.financial_daily_refresh_operations "
            "WHERE idempotency_key = %s",
            (idempotency_key,),
        )


def _delete_operations(database: PostgresDatabase, idempotency_prefix: str) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            "DELETE FROM data.financial_daily_refresh_operations "
            "WHERE idempotency_key LIKE %s",
            (f"{idempotency_prefix}%",),
        )

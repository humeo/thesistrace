from uuid import uuid4

import pytest

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_financial_indicator import TushareFinancialIndicatorProvider
from thesistrace.data.financial_indicator_collection import FinancialIndicatorCollector
from thesistrace.data.financial_indicator_progress import FinancialIndicatorProgressStore
from thesistrace.entrypoints.schema import initialize_core


@pytest.mark.parametrize("values, pending", [((None,), False), ((2, 2), False), ((2, 3), True)])
def test_indicator_report_presence_requires_one_accepted_version(
    core_settings, tmp_path, values, pending,
):
    from datetime import UTC, datetime

    from thesistrace.data.generation_store import HistoricalInstrumentIdentity
    from thesistrace.data.source import RawSourceResponse

    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    instrument = "report-version-" + uuid4().hex

    class Provider:
        def query_raw(self, api_name, *, params, fields):
            return RawSourceResponse(tuple(fields), tuple(
                tuple({"ts_code": "000001.SZ", "ann_date": "20260828", "end_date": "20260630",
                       "eps": value}.get(field) for field in fields)
                for value in values
            ))

    try:
        result = FinancialIndicatorCollector(
            database, tmp_path, TushareFinancialIndicatorProvider(Provider()),
            clock=lambda: datetime(2026, 8, 29, tzinfo=UTC),
        ).collect(
            collection_key=instrument,
            identity=HistoricalInstrumentIdentity(instrument, "000001.SZ"),
            start_date="20260101", end_date="20260829", checked_through="2026-08-29",
            required_reports=(("2026-06-30", "2026-08-29"),),
        )
        assert result.pending_reports == ((("2026-06-30", "2026-08-29"),) if pending else ())
        assert (
            FinancialIndicatorProgressStore(database).pending(instrument) == result.pending_reports
        )
    finally:
        with database.transaction() as tx:
            tx.execute(
                "DELETE FROM data.financial_report_targets WHERE instrument_id=%s", (instrument,),
            )
            tx.execute(
                "DELETE FROM data.financial_indicator_reconciliation WHERE instrument_id=%s",
                (instrument,),
            )
        database.close()


def test_indicator_pending_survives_unmatched_collection_and_reopens(core_settings):
    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    instrument = "indicator-" + uuid4().hex
    try:
        store = FinancialIndicatorProgressStore(database)
        store.require_report(instrument, report_period="2020-03-31", announced_on="2020-04-20")
        store.require_report(instrument, report_period="2020-03-31", announced_on="2020-04-20")
        store.record_reconciliation(
            instrument,
            checked_through="2020-05-01",
            observed_reports=(),
            observation_sha256="a" * 64,
        )
        reopened = FinancialIndicatorProgressStore(database)
        assert reopened.pending(instrument) == (("2020-03-31", "2020-04-20"),)
        assert reopened.reconciled_through(instrument) == "2020-05-01"
        store.record_reconciliation(
            instrument,
            checked_through="2020-05-02",
            observed_reports=(("2020-03-31", "2020-04-19"),),
            observation_sha256="b" * 64,
        )
        assert reopened.pending(instrument) == ()
        store.record_reconciliation(
            instrument,
            checked_through="2020-05-03",
            observed_reports=(("2020-03-31", "2020-04-20"),),
            observation_sha256="c" * 64,
        )
        assert reopened.pending(instrument) == ()
        store.require_report(instrument, report_period="2020-03-31", announced_on="2020-05-04")
        assert reopened.pending(instrument) == ()
    finally:
        with database.transaction() as tx:
            tx.execute(
                "DELETE FROM data.financial_report_targets WHERE instrument_id=%s",
                (instrument,),
            )
            tx.execute(
                "DELETE FROM data.financial_indicator_reconciliation WHERE instrument_id=%s",
                (instrument,),
            )
        database.close()


def test_indicator_collector_retains_pending_on_failure_and_resolves_saved_response(
    core_settings, tmp_path
):
    from datetime import UTC, datetime

    import pytest

    from thesistrace.adapters.tushare_provider import TushareSourceError
    from thesistrace.data.generation_store import HistoricalInstrumentIdentity
    from thesistrace.data.source import DataSourceError, RawSourceResponse

    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    instrument = "indicator-" + uuid4().hex
    identity = HistoricalInstrumentIdentity(instrument, "000001.SZ")

    class Provider:
        failing = True

        def query_raw(self, api_name, *, params, fields):
            if self.failing:
                raise TushareSourceError("UPSTREAM_UNAVAILABLE", source_code=None)
            row = {"ts_code": "000001.SZ", "end_date": "20200331", "ann_date": "20200420", "eps": 2}
            return RawSourceResponse(
                fields=tuple(fields), items=(tuple(row.get(f) for f in fields),)
            )

    provider = Provider()
    collector = FinancialIndicatorCollector(
        database,
        tmp_path,
        TushareFinancialIndicatorProvider(provider),
        clock=lambda: datetime(2020, 5, 1, tzinfo=UTC),
    )
    request = dict(
        collection_key="collect-" + instrument,
        identity=identity,
        start_date="20190101",
        end_date="20200501",
        checked_through="2020-05-01",
        required_reports=(("2020-03-31", "2020-04-20"),),
    )
    try:
        with pytest.raises(DataSourceError):
            collector.collect(**request)
        progress = FinancialIndicatorProgressStore(database)
        assert progress.pending(instrument) == request["required_reports"]
        assert progress.reconciled_through(instrument) is None
        provider.failing = False
        completed = collector.collect(**request)
        assert completed.pending_reports == ()
        assert len(completed.observation_sha256s) == 1
        provider.failing = True
        assert collector.collect(**request) == completed
    finally:
        with database.transaction() as tx:
            tx.execute(
                "DELETE FROM data.financial_report_targets WHERE instrument_id=%s",
                (instrument,),
            )
            tx.execute(
                "DELETE FROM data.financial_indicator_reconciliation WHERE instrument_id=%s",
                (instrument,),
            )
        database.close()


def test_indicator_requirement_rejects_an_unknown_report_period(core_settings):
    import pytest

    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        with pytest.raises((TypeError, ValueError)):
            FinancialIndicatorProgressStore(database).require_report(
                "invalid-period",
                report_period=None,
                announced_on="2020-04-20",
            )
    finally:
        database.close()


def test_indicator_discovery_targets_commit_atomically_with_announcement_receipt(core_settings):
    from datetime import UTC, datetime

    import pytest

    from thesistrace.data.daily_financial_refresh import (
        FinancialDailyRefreshError,
        FinancialDailyRefreshStore,
    )
    from thesistrace.data.financial_disclosures import (
        FinancialDisclosure,
        FinancialDisclosureDiscovery,
        disclosure_periods,
    )
    from thesistrace.data.generation_store import HistoricalInstrumentIdentity

    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    unique = uuid4().hex
    instrument, key = "atomic-indicator-" + unique, "atomic-discovery-" + unique
    now = datetime(2020, 4, 20, tzinfo=UTC)
    identity = HistoricalInstrumentIdentity(instrument, "000001.SZ")
    announcement = FinancialDisclosure(
        ts_code="000001.SZ",
        report_period=disclosure_periods("2020-04-20", "2020-04-20")[-1],
        actual_date="2020-04-20",
    )
    from dataclasses import replace

    invalid = replace(announcement, ts_code="000002.SZ")
    discovery = FinancialDisclosureDiscovery(
        start_date="2020-04-20",
        end_date="2020-04-20",
        completed_periods=tuple(
            period
            for period in disclosure_periods("2020-04-20", "2020-04-20")
            if period not in {gap.report_period for gap in ()}
        ),
        reports=tuple(
            {
                (report.ts_code, report.report_period): report for report in (announcement, invalid)
            }.values()
        ),
        gaps=(),
        source_lineage_sha256="e" * 64,
    )
    try:
        daily = FinancialDailyRefreshStore(database)
        daily.begin(
            idempotency_key=key,
            source_generation_manifest_sha256="a" * 64,
            prior_financial_manifest_sha256="b" * 64,
            discovery_baseline_session="2020-04-17",
            prior_attempted_through_session="2020-04-17",
            prior_complete_through_session="2020-04-17",
            target_session="2020-04-20",
            started_at=now,
        )
        progress = FinancialIndicatorProgressStore(database)
        with pytest.raises(FinancialDailyRefreshError, match="REPORT_INVALID"):
            daily.record_discovery(
                idempotency_key=key,
                discovery=discovery,
                identities=(identity,),
                recorded_at=now,
            )
        assert progress.pending(instrument) == ()
        valid = replace(discovery, reports=(announcement,))
        for _ in range(2):
            daily.record_discovery(
                idempotency_key=key,
                discovery=valid,
                identities=(identity,),
                recorded_at=now,
            )
        assert progress.pending(instrument) == (("2020-03-31", "2020-04-20"),)
    finally:
        with database.transaction() as tx:
            tx.execute(
                "DELETE FROM data.financial_report_targets WHERE instrument_id=%s",
                (instrument,),
            )
            tx.execute(
                "DELETE FROM data.financial_daily_refresh_operations WHERE idempotency_key=%s",
                (key,),
            )
            tx.execute(
                "DELETE FROM data.financial_announcement_triggers WHERE instrument_id=%s",
                (instrument,),
            )
        database.close()


def test_daily_indicator_dispatch_retries_frozen_work_and_keeps_source_failures(
    core_settings, tmp_path
):
    from datetime import UTC, datetime

    import pytest

    from thesistrace.adapters.tushare_provider import TushareSourceError
    from thesistrace.data.financial_indicator_collection import FinancialIndicatorDailyCollector
    from thesistrace.data.generation_store import HistoricalInstrumentIdentity
    from thesistrace.data.source import RawSourceResponse

    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    prefix = "dispatch-" + uuid4().hex
    identities = tuple(
        HistoricalInstrumentIdentity(prefix + str(n), f"00000{n}.SZ") for n in (1, 2, 3)
    )

    class Provider:
        failing = True

        def query_raw(self, api_name, *, params, fields):
            if self.failing and params["ts_code"] == "000001.SZ":
                raise TushareSourceError("UPSTREAM_UNAVAILABLE", source_code=None)
            row = {"ts_code": params["ts_code"], "end_date": "20200331", "ann_date": "20200420"}
            return RawSourceResponse(
                fields=tuple(fields), items=(tuple(row.get(f) for f in fields),)
            )

    provider = Provider()
    try:
        progress = FinancialIndicatorProgressStore(database)
        progress.require_report(
            identities[0].instrument_id, report_period="2020-03-31", announced_on="2020-04-20"
        )
        collector = FinancialIndicatorDailyCollector(
            database,
            tmp_path,
            TushareFinancialIndicatorProvider(provider),
            reconciliation_limit=1,
            clock=lambda: datetime(2020, 5, 1, tzinfo=UTC),
        )
        result = collector.collect(
            operation_key=prefix,
            identities=identities,
            checked_through="2020-05-01",
            research_session_index=1,
            initial_instrument_ids=(),
        )
        assert len(result.scheduled_instrument_ids) == 2
        assert result.failed_instrument_ids == (identities[0].instrument_id,)
        assert progress.pending(identities[0].instrument_id)
        next_day = collector.collect(
            operation_key=prefix + "-next",
            identities=identities,
            checked_through="2020-05-04",
            research_session_index=2,
            initial_instrument_ids=(),
        )
        assert next_day.scheduled_instrument_ids == (
            identities[0].instrument_id,
            identities[2].instrument_id,
        )
        assert next_day.failed_instrument_ids == (identities[0].instrument_id,)
        with pytest.raises(ValueError, match="scope differs"):
            collector.collect(
                operation_key=prefix,
                identities=identities,
                checked_through="2020-05-04",
                research_session_index=2,
                initial_instrument_ids=(),
            )
        provider.failing = False
        retried = collector.collect(
            operation_key=prefix,
            identities=identities,
            checked_through="2020-05-01",
            research_session_index=1,
            initial_instrument_ids=(),
        )
        assert retried.scheduled_instrument_ids == result.scheduled_instrument_ids
        assert retried.failed_instrument_ids == ()
        assert len(retried.collection_evidence_sha256s) == 2
        assert progress.pending(identities[0].instrument_id) == ()
        provider.failing = True
        assert (
            collector.collect(
                operation_key=prefix,
                identities=identities,
                checked_through="2020-05-01",
                research_session_index=1,
                initial_instrument_ids=(),
            )
            == retried
        )
    finally:
        with database.transaction() as tx:
            tx.execute(
                "DELETE FROM data.financial_report_targets WHERE instrument_id LIKE %s",
                (prefix + "%",),
            )
            tx.execute(
                "DELETE FROM data.financial_indicator_reconciliation WHERE instrument_id LIKE %s",
                (prefix + "%",),
            )
        database.close()

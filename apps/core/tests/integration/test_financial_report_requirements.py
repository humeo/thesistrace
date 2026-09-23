from uuid import uuid4

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.financial_indicator_progress import FinancialIndicatorProgressStore
from thesistrace.entrypoints.schema import initialize_core


def test_report_period_resolves_even_when_supplier_publication_date_differs(core_settings):
    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    instrument = "report-" + uuid4().hex
    try:
        progress = FinancialIndicatorProgressStore(database)
        progress.require_report(instrument, report_period="2026-06-30", announced_on="2026-08-29")
        progress.record_reconciliation(
            instrument,
            checked_through="2026-09-11",
            observed_reports=(("2026-03-31", "2026-04-20"),),
            observation_sha256="a" * 64,
        )
        assert progress.pending(instrument) == (("2026-06-30", "2026-08-29"),)
        progress.record_reconciliation(
            instrument,
            checked_through="2026-09-11",
            observed_reports=(("2026-06-30", "2026-08-28"),),
            observation_sha256="b" * 64,
        )
        assert FinancialIndicatorProgressStore(database).pending(instrument) == ()
    finally:
        database.close()


def test_refresh_retries_missing_report_without_announcements_and_preserves_prior_facts(
    core_settings,
    tmp_path,
):
    import json
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    import pytest
    from test_financial_collection import (
        ExecutableStatementSource,
        FixtureIndicatorProvider,
        _database,
        _establish_head,
        _executable_contract,
        _financial_generation,
        _initial_candidate,
        _market_generation,
        drop_product_schemas,
    )

    from thesistrace.adapters.tushare_financial_indicator import TushareFinancialIndicatorProvider
    from thesistrace.data.daily_financial_refresh import DailyFinancialRefreshService
    from thesistrace.data.financial_candidate import FinancialCandidateStore
    from thesistrace.data.financial_disclosures import (
        FinancialDisclosure,
        FinancialDisclosureDiscovery,
        disclosure_periods,
    )
    from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
    from thesistrace.data.generation_store import MountedGenerationStore
    from thesistrace.data.source import RawSourceResponse

    class Disclosures:
        def discover(self, *, start_date, end_date, allowed_ts_codes):
            return FinancialDisclosureDiscovery(
                start_date,
                end_date,
                disclosure_periods(start_date, end_date),
                (FinancialDisclosure("000001.SZ", "2026-06-30", "2026-08-14"),),
                (),
                "d" * 64,
            )

    class Statements(ExecutableStatementSource):
        half_year_available = False

        def query_raw(self, endpoint, *, params, fields):
            prior = super().query_raw(endpoint, params=params, fields=fields)
            if not self.half_year_available:
                return prior
            updated = list(prior.items[0])
            updated[fields.index("end_date")] = "20260630"
            updated[fields.index("ann_date")] = "20260813"
            updated[fields.index("end_type")] = "2"
            return RawSourceResponse(prior.fields, (*prior.items, tuple(updated)))

    class Indicators(FixtureIndicatorProvider):
        mode = "valid"

        def query_raw(self, endpoint, *, params, fields):
            response = super().query_raw(endpoint, params=params, fields=fields)
            if params["ts_code"] != "000001.SZ":
                return response
            if self.mode == "omitted":
                return RawSourceResponse(response.fields, response.items[:1])
            if self.mode == "conflict":
                conflicting = list(response.items[-1])
                conflicting[fields.index("eps")] = 3
                return RawSourceResponse(response.fields, (*response.items, tuple(conflicting)))
            return response

    drop_product_schemas(core_settings)
    database = _database(core_settings)
    try:
        market = _market_generation(
            tmp_path,
            sessions=("2010-01-04", "2026-08-07", "2026-08-13", "2026-08-14", "2026-08-17"),
        )
        _establish_head(database, tmp_path, market, operation_id="structured-market")
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="structured-prior",
            contract=_executable_contract(),
        )
        generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database, tmp_path, generation, operation_id="structured-seed", expected=market
        )
        source = Statements()
        indicators = Indicators()
        now = datetime(2026, 8, 14, 10, tzinfo=UTC)
        service = DailyFinancialRefreshService(
            database,
            tmp_path,
            Disclosures(),
            source,
            indicator_provider=TushareFinancialIndicatorProvider(indicators),
            clock=lambda: now,
        )
        pending = service.publish(
            idempotency_key="structured-missing",
            observation_through_session="2026-08-14",
        )
        assert pending.status == "succeeded_with_pending"
        assert pending.pending_instrument_count == 1
        assert FinancialIndicatorProgressStore(database).pending("equity:000001.SZ") == ()
        preserved = FinancialCandidateStore(tmp_path).report_inventory(
            pending.candidate.manifest_sha256,
            through="2026-08-14",
        )
        assert ("equity:000001.SZ", "2009-12-31") in preserved["income"]
        assert ("equity:000001.SZ", "2026-06-30") not in preserved["income"]

        source.half_year_available = True
        complete = service.publish(
            idempotency_key="structured-complete",
            observation_through_session="2026-08-14",
        )
        assert complete.status == "succeeded"
        assert complete.pending_instrument_count == 0
        completed_families = [
            document for path in (tmp_path / "manifests").rglob("*.json")
            if (document := json.loads(path.read_bytes())).get("format")
            == "thesistrace-financial-family-candidate"
            and document.get("source_collection", {}).get("idempotency_key")
            == "structured-complete"
        ]
        assert len(completed_families) == 1, (
            "Resolving pending reports must seal one final candidate"
        )
        assert (
            service.publish(
                idempotency_key="structured-complete",
                observation_through_session="2026-08-14",
            )
            == complete
        )
        # Re-observation must retain prior accepted rows when omitted, reopen a
        # conflicting latest state, then resolve after an unambiguous later response.
        for mode, expected_pending in (("omitted", False), ("conflict", True), ("valid", False)):
            indicators.mode = mode
            now += timedelta(minutes=1)
            result = service.publish(
                idempotency_key="structured-indicator-" + mode,
                observation_through_session="2026-08-14",
            )
            assert result.status == ("succeeded_with_pending" if expected_pending else "succeeded")
            assert result.pending_instrument_count == int(expected_pending)
            assert FinancialIndicatorProgressStore(database).pending("equity:000001.SZ") == (
                (("2026-06-30", "2026-08-14"),) if expected_pending else ()
            )
            descriptor = MountedGenerationStore(tmp_path).inspect_root(
                result.generation_manifest_sha256,
            )
            digest = next(family.manifest_sha256 for family in descriptor.families
                          if family.family_id == "equity.financial_indicator")
            manifest = FinancialIndicatorCandidateStore(tmp_path).reopen(digest)
            assert manifest["unresolved_sources"] == (
                {"equity:000001.SZ": "2026-08-14"} if expected_pending else {}
            )

        class InterruptedDisclosures(Disclosures):
            def discover(self, **kwargs):
                discovery = super().discover(**kwargs)
                return replace(discovery, reports=(*discovery.reports, FinancialDisclosure(
                    "000002.SZ", "2025-12-31", "2026-04-20",
                )))

        def interrupt_after_discovery(event):
            if event["phase"] == "discovery" and event["status"] == "completed":
                raise KeyboardInterrupt

        interrupted = DailyFinancialRefreshService(
            database, tmp_path, InterruptedDisclosures(), source,
            indicator_provider=TushareFinancialIndicatorProvider(indicators),
            clock=lambda: now, progress=interrupt_after_discovery,
        )
        with pytest.raises(KeyboardInterrupt):
            interrupted.publish(
                idempotency_key="structured-interrupted", observation_through_session="2026-08-14",
            )
        # The next timetable omits the interrupted refresh's row. Its durable
        # requirement must still appear in both the receipt and immutable candidate.
        now += timedelta(minutes=1)
        result = service.publish(
            idempotency_key="structured-after-interruption",
            observation_through_session="2026-08-14",
        )
        assert result.status == "succeeded_with_pending"
        assert result.pending_instrument_count == 1
        assert FinancialIndicatorProgressStore(database).pending("equity:000002.SZ") == (
            ("2025-12-31", "2026-04-20"),
        )
        descriptor = MountedGenerationStore(tmp_path).inspect_root(
            result.generation_manifest_sha256,
        )
        digest = next(family.manifest_sha256 for family in descriptor.families
                      if family.family_id == "equity.financial_indicator")
        assert FinancialIndicatorCandidateStore(tmp_path).reopen(digest)["unresolved_sources"] == {
            "equity:000002.SZ": "2026-04-20",
        }
        now = datetime(2026, 8, 17, 10, tzinfo=UTC)
        advanced = service.publish(
            idempotency_key="structured-next-session", observation_through_session="2026-08-17",
        )
        assert advanced.pending_instrument_count == 1  # Only the genuinely absent 000002 report.
        inventory = FinancialCandidateStore(tmp_path).report_inventory(
            advanced.candidate.manifest_sha256, through="2026-08-17",
        )
        assert all(("equity:000001.SZ", "2026-06-30") in reports
                   for reports in inventory.values())
        with database.transaction() as tx:
            assert tx.execute(
                """SELECT count(*) n FROM data.financial_report_targets
                   WHERE instrument_id='equity:000001.SZ' AND endpoint<>'fina_indicator'
                     AND resolved_evidence_sha256 IS NULL""",
            ).fetchone()["n"] == 0
            assert (
                tx.execute(
                    "SELECT count(*) n FROM data.financial_announcement_triggers"
                ).fetchone()["n"]
                == 0
            )
    finally:
        database.close()
        drop_product_schemas(core_settings)

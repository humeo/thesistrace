import json
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.adapters.tushare_replay import ReplayTushareProvider
from thesistrace.data import (
    DATA_SOURCE_ERROR_CATEGORIES,
    CanonicalSourceBatch,
    DataSourceError,
)
from thesistrace.data.canonical_mapping import (
    CanonicalMappingError,
    bootstrap_research_calendar,
    research_sessions_after,
)
from thesistrace.data.models import DataOverview
from thesistrace.entrypoints import live_tushare


def test_data_source_contract_has_one_batch_shape_and_bounded_error_categories() -> None:
    assert [field.name for field in fields(CanonicalSourceBatch)] == [
        "source_name",
        "collection_kind",
        "source_lineage",
        "canonical",
        "covered_session_range",
    ]
    assert DATA_SOURCE_ERROR_CATEGORIES == (
        "authorization",
        "invalid_source_data",
        "unavailable",
    )
    for category in DATA_SOURCE_ERROR_CATEGORIES:
        failure = DataSourceError(category, detail_code="RECORDED_CASE")
        assert failure.category == category


def test_data_source_contract_rejects_provider_specific_error_categories() -> None:
    try:
        DataSourceError("tushare_permission", detail_code="MISSING_PERMISSION")
    except ValueError as error:
        assert str(error) == "DataSource error category is invalid"
    else:
        raise AssertionError("provider-specific category was accepted")


def test_data_owns_exchange_calendar_intersection_and_bootstrap_coverage() -> None:
    start = date(2022, 1, 1)
    sse = [(start + timedelta(days=offset)).isoformat() for offset in range(800)]
    szse = sse[20:]

    bootstrap = bootstrap_research_calendar((sse, szse))

    assert bootstrap == szse
    assert research_sessions_after((sse, szse), bootstrap[-2]) == bootstrap[-1:]


def test_data_accepts_any_positive_bootstrap_calendar_and_rejects_no_overlap() -> None:
    assert bootstrap_research_calendar((("2026-08-03",), ("2026-08-03",))) == ["2026-08-03"]
    with pytest.raises(CanonicalMappingError) as failure:
        bootstrap_research_calendar((("2026-08-03",), ("2026-08-04",)))

    assert failure.value.detail_code == "INSUFFICIENT_CALENDAR_COVERAGE"


def test_product_data_contract_has_no_provider_or_collection_modes() -> None:
    forbidden = {"live", "fixture", "bootstrap", "increment"}
    schemas = (DataOverview.model_json_schema(),)

    assert all(word not in str(schema).lower() for schema in schemas for word in forbidden)


def test_live_tushare_gate_is_separate_from_the_default_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = json.loads((Path(__file__).resolve().parents[2] / "package.json").read_text())
    default_gate = package["scripts"]["check"]
    live_gate = package["scripts"]["check:live-tushare"]

    assert "scripts/check_live_tushare.py" not in default_gate
    assert "uv run python scripts/check_live_tushare.py" in live_gate

    replay = ReplayTushareProvider(
        Path(__file__).resolve().parents[1] / "fixtures" / "tushare-bootstrap-replay-v2.json"
    )

    class StubProvider:
        def __init__(self) -> None:
            self.preflight_count = 0
            self.windows: list[tuple[date, date]] = []

        def preflight(self) -> dict[str, object]:
            self.preflight_count += 1
            return {
                "status": "available",
                "source": "tushare",
                "source_contract_version": "tushare-v2",
                "permissions": [
                    {"contract": "price_limit", "api_name": "stk_limit", "status": "available"}
                ],
            }

        def collect_bootstrap_snapshot(
            self,
            *,
            start_date: date,
            completed_through_date: date,
        ) -> dict[str, list[dict[str, object]]]:
            self.windows.append((start_date, completed_through_date))
            return replay.collect_bootstrap_snapshot(
                start_date=start_date,
                completed_through_date=completed_through_date,
            )

    provider = StubProvider()
    live_tushare.main(
        provider=provider,
        as_of=datetime(2026, 8, 3, 10, tzinfo=UTC),
    )

    assert provider.preflight_count == 1
    assert provider.windows == [(date(2025, 8, 3), date(2026, 8, 3))]
    assert json.loads(capsys.readouterr().out) == {
        "status": "passed",
        "provider_preflight": {
            "status": "available",
            "source": "tushare",
            "source_contract_version": "tushare-v2",
            "permissions": [
                {"contract": "price_limit", "api_name": "stk_limit", "status": "available"}
            ],
        },
        "bootstrap_collection": {
            "status": "passed",
            "canonical_schema": "canonical-eod",
            "covered_session_range": ["2026-08-03", "2026-08-03"],
            "research_session_count": 1,
        },
    }


def test_live_tushare_gate_reports_the_exact_failed_permission(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class DeniedProvider:
        def preflight(self) -> dict[str, object]:
            raise TushareSourceError(
                "MISSING_PERMISSION",
                source_code=40203,
                contract="sw2021_membership",
                api_name="index_member_all",
            )

        def collect_bootstrap_snapshot(
            self,
            *,
            start_date: date,
            completed_through_date: date,
        ) -> dict[str, list[dict[str, object]]]:
            raise AssertionError("collection must not run after a failed preflight")

    with pytest.raises(SystemExit) as failure:
        live_tushare.main(
            provider=DeniedProvider(),
            as_of=datetime(2026, 8, 3, 10, tzinfo=UTC),
        )

    assert failure.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "failed",
        "failed_check": "provider_preflight",
        "error": {
            "reason_code": "MISSING_PERMISSION",
            "source_code": 40203,
            "contract": "sw2021_membership",
            "api_name": "index_member_all",
        },
    }


def test_live_tushare_gate_reports_rate_limit_after_successful_preflight(
    capsys: pytest.CaptureFixture[str],
) -> None:
    preflight = {
        "status": "available",
        "source": "tushare",
        "source_contract_version": "tushare-v2",
        "permissions": [
            {"contract": "adjustment", "api_name": "adj_factor", "status": "available"}
        ],
    }

    class BootstrapDeniedProvider:
        def preflight(self) -> dict[str, object]:
            return preflight

        def collect_bootstrap_snapshot(
            self,
            *,
            start_date: date,
            completed_through_date: date,
        ) -> dict[str, list[dict[str, object]]]:
            raise TushareSourceError(
                "UPSTREAM_RATE_LIMITED",
                source_code=40203,
                api_name="adj_factor",
            )

    with pytest.raises(SystemExit) as failure:
        live_tushare.main(
            provider=BootstrapDeniedProvider(),
            as_of=datetime(2026, 8, 3, 10, tzinfo=UTC),
        )

    assert failure.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "failed",
        "failed_check": "bootstrap_collection",
        "provider_preflight": preflight,
        "error": {
            "category": "unavailable",
            "reason_code": "UPSTREAM_RATE_LIMITED",
            "source_code": 40203,
            "api_name": "adj_factor",
        },
    }

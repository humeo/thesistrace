from dataclasses import fields
from datetime import date, timedelta

import pytest

from thesistrace.data import (
    DATA_SOURCE_ERROR_CATEGORIES,
    CanonicalSourceBatch,
    DataSourceError,
)
from thesistrace.data.canonical_mapping import (
    BOOTSTRAP_RESEARCH_SESSION_COUNT,
    CanonicalMappingError,
    bootstrap_research_calendar,
    research_sessions_after,
)
from thesistrace.data.models import (
    DataOverview,
    ReleaseHistory,
    ReleaseSummary,
    UpdateAcceptance,
)
from thesistrace.entrypoints.http import DataUpdateRequest


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

    assert len(bootstrap) == BOOTSTRAP_RESEARCH_SESSION_COUNT
    assert bootstrap == szse[-BOOTSTRAP_RESEARCH_SESSION_COUNT:]
    assert research_sessions_after((sse, szse), bootstrap[-2]) == bootstrap[-1:]


def test_data_rejects_insufficient_exchange_calendar_coverage() -> None:
    with pytest.raises(CanonicalMappingError) as failure:
        bootstrap_research_calendar((("2026-08-03",), ("2026-08-03",)))

    assert failure.value.detail_code == "INSUFFICIENT_CALENDAR_COVERAGE"


def test_product_data_contract_has_no_provider_or_collection_modes() -> None:
    forbidden = {"live", "fixture", "bootstrap", "increment"}
    schemas = (
        DataUpdateRequest.model_json_schema(),
        DataOverview.model_json_schema(),
        ReleaseHistory.model_json_schema(),
        ReleaseSummary.model_json_schema(),
        UpdateAcceptance.model_json_schema(),
    )

    assert DataUpdateRequest.model_fields == {}
    assert all(
        word not in str(schema).lower()
        for schema in schemas
        for word in forbidden
    )


def test_live_tushare_gate_is_separate_from_the_default_gate() -> None:
    makefile = (__import__("pathlib").Path(__file__).resolve().parents[2] / "Makefile").read_text()
    default_gate, live_gate = makefile.split("\ncheck-live-tushare:\n", maxsplit=1)

    assert "scripts/check_live_tushare.py" not in default_gate
    assert "uv run python scripts/check_live_tushare.py" in live_gate

    script = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "scripts"
        / "check_live_tushare.py"
    ).read_text()
    assert '"preflight":' not in script
    assert '"source":' not in script

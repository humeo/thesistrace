from datetime import UTC, datetime

from thesistrace.data.financial_collection import RawFinancialBatchStore
from thesistrace.data.financial_indicator_evidence import (
    FinancialIndicatorObservationStore,
    indicator_versions,
    received_indicator_reports,
)
from thesistrace.data.source import RawSourceResponse


def raw(eps, *, ann_date="20200420"):
    return RawSourceResponse(
        fields=("ts_code", "end_date", "ann_date", "eps", "update_flag"),
        items=(("000001.SZ", "20191231", ann_date, eps, "1"),),
    )


def test_reusable_projector_keeps_each_security_revision_history_independent(tmp_path):
    from thesistrace.data.financial_indicator_evidence import IndicatorVersionProjector

    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    original = store.read(store.save(raw(2), observed_at=datetime(2020, 5, 1, tzinfo=UTC)))
    revision = store.read(store.save(raw(3), observed_at=datetime(2020, 6, 1, tzinfo=UTC)))
    sessions = ["2020-04-21", "2020-06-02"]
    projector = IndicatorVersionProjector(sessions)
    sessions.clear()
    versions = projector.project([original, revision], instrument_ids={"000001.SZ": "stock-1"})
    assert [(v["eps"], v["effective_available_session"]) for v in versions] == [
        (2, "2020-04-21"), (3, "2020-06-02"),
    ]
    independent = projector.project([revision], instrument_ids={"000001.SZ": "stock-2"})
    assert len(independent) == 1
    assert independent[0]["instrument_id"] == "stock-2"
    assert independent[0]["effective_available_session"] == "2020-04-21"


def test_reusable_projector_rejects_noncanonical_calendar():
    import pytest

    from thesistrace.data.financial_indicator_evidence import IndicatorVersionProjector

    for calendar in (("2020-4-21",), ("20200421",), ("2020-02-30",),
                     ("2020-04-21", "2020-04-21"), ("2020-04-22", "2020-04-21")):
        with pytest.raises(ValueError):
            IndicatorVersionProjector(calendar)


def test_receipts_reopen_and_repeated_content_keeps_earliest_observation(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    first = store.save(raw(2), observed_at=datetime(2020, 5, 1, tzinfo=UTC))
    repeated = store.save(raw(2), observed_at=datetime(2020, 6, 1, tzinfo=UTC))
    reopened = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    versions = indicator_versions(
        [reopened.read(repeated), reopened.read(first)],
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-20", "2020-04-21", "2020-05-04", "2020-06-02"),
    )
    assert len(versions) == 1
    assert versions[0]["first_observed_at"] == "2020-05-01T00:00:00+00:00"
    assert versions[0]["effective_available_session"] == "2020-04-21"
    assert versions[0]["eps"] == 2
    assert "source_report_type" not in versions[0]


def test_later_same_announcement_revision_is_not_backdated(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    first = store.read(store.save(raw(2), observed_at=datetime(2020, 5, 1, tzinfo=UTC)))
    later = store.read(store.save(raw(3), observed_at=datetime(2020, 6, 1, tzinfo=UTC)))
    versions = indicator_versions(
        [later, first],
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21", "2020-06-01", "2020-06-02"),
    )
    assert [(v["eps"], v["effective_available_session"]) for v in versions] == [
        (2, "2020-04-21"),
        (3, "2020-06-02"),
    ]


def test_missing_announcement_and_unordered_conflicts_are_quarantined(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    observed = datetime(2020, 5, 1, tzinfo=UTC)
    observations = [
        store.read(store.save(item, observed_at=observed))
        for item in (raw(2), raw(3), raw(4, ann_date=None))
    ]
    versions = indicator_versions(
        observations,
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21", "2020-05-04"),
    )
    assert {v["availability_status"] for v in versions} == {
        "conflicting_observation",
        "missing_announcement",
    }
    assert all(v["effective_available_session"] is None for v in versions)


def test_reverted_value_is_a_new_transition_with_original_content_provenance(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    observations = [
        store.read(store.save(raw(value), observed_at=datetime(2020, month, 1, tzinfo=UTC)))
        for month, value in ((5, 2), (6, 3), (7, 2), (8, 2))
    ]
    versions = indicator_versions(
        observations[::-1],
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21", "2020-06-02", "2020-07-02", "2020-08-03"),
    )
    assert [(v["eps"], v["effective_available_session"]) for v in versions] == [
        (2, "2020-04-21"),
        (3, "2020-06-02"),
        (2, "2020-07-02"),
    ]
    assert versions[2]["first_observed_at"] == "2020-05-01T00:00:00+00:00"
    assert versions[2]["observation_event_at"] == "2020-07-01T00:00:00+00:00"


def test_later_conflict_has_an_effective_missing_transition_and_can_resolve(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    observations = [
        store.read(store.save(raw(value), observed_at=datetime(2020, month, 1, tzinfo=UTC)))
        for month, value in ((5, 2), (6, 2), (6, 3), (7, 3))
    ]
    versions = indicator_versions(
        observations,
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21", "2020-06-02", "2020-07-02"),
    )
    conflicts = [v for v in versions if v["availability_status"] == "conflicting_observation"]
    assert len(conflicts) == 2
    assert {v["state_effective_session"] for v in conflicts} == {"2020-06-02"}
    assert all(v["effective_available_session"] is None for v in conflicts)
    assert versions[-1]["eps"] == 3
    assert versions[-1]["effective_available_session"] == "2020-07-02"

    conflicted = indicator_versions(
        observations[:-1], instrument_ids={"000001.SZ": "stock-1"}, sessions=(),
    )
    assert received_indicator_reports(conflicted, through="2020-07-01") == ()
    resolved = indicator_versions(
        observations, instrument_ids={"000001.SZ": "stock-1"}, sessions=(),
    )
    assert received_indicator_reports(resolved, through="2020-07-01") == (
        ("stock-1", "2019-12-31", "2020-04-20"),
    )


def test_revision_uses_shanghai_observation_date_and_keeps_null(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    original = store.read(store.save(raw(2), observed_at=datetime(2020, 5, 1, tzinfo=UTC)))
    changed = store.read(
        store.save(raw(None), observed_at=datetime(2020, 6, 1, 16, 30, tzinfo=UTC))
    )
    versions = indicator_versions(
        [original, changed],
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21", "2020-06-02", "2020-06-03"),
    )
    assert versions[-1]["eps"] is None
    assert versions[-1]["effective_available_session"] == "2020-06-03"


def test_update_flag_does_not_rank_conflicting_rows(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    response = raw(2)
    response = RawSourceResponse(
        fields=response.fields,
        items=(
            response.items[0],
            ("000001.SZ", "20191231", "20200420", 9, "0"),
        ),
    )
    observation = store.read(store.save(response, observed_at=datetime(2020, 5, 1, tzinfo=UTC)))
    versions = indicator_versions(
        [observation],
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21",),
    )
    assert len(versions) == 2
    assert all(v["availability_status"] == "conflicting_observation" for v in versions)
    assert all(v["effective_available_session"] is None for v in versions)


def test_announcement_before_report_end_is_quarantined(tmp_path):
    store = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    observation = store.read(store.save(
        raw(2, ann_date="20191230"), observed_at=datetime(2020, 5, 1, tzinfo=UTC),
    ))
    versions = indicator_versions(
        [observation], instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2019-12-31", "2020-01-02", "2020-05-04"),
    )
    assert len(versions) == 1
    assert versions[0]["availability_status"] == "invalid_announcement"
    assert versions[0]["state_effective_session"] is None
    assert versions[0]["effective_available_session"] is None

from pathlib import Path

import pytest

from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import CanonicalSourceBatch, CollectionPlan, DataSourceError


def test_fixture_implements_only_the_canonical_collection_contract(
    fixture_bootstrap_batch: CanonicalSourceBatch,
) -> None:
    batch = fixture_bootstrap_batch

    assert batch.collection_kind == "bootstrap"
    assert batch.source_name == "fixture"
    assert len(batch.canonical["research_calendar"]) == 756
    assert batch.canonical["schema_version"] == "canonical-eod-v1"
    assert batch.covered_session_range == (
        batch.canonical["research_calendar"][0],
        batch.canonical["research_calendar"][-1],
    )
    evidence = repr(batch).lower()
    assert "release_id" not in evidence
    assert "manifest" not in evidence
    assert "bucket" not in evidence
    source = (
        Path(__file__).resolve().parents[2] / "src" / "thesistrace" / "adapters" / "fixture_data.py"
    ).read_text()
    for forbidden in ("release", "postgres", "publication", "s3", "research_run", "daily_track"):
        assert forbidden not in source.lower()


def test_fixture_collects_direct_and_wider_incremental_source_gaps(
    fixture_bootstrap_batch: CanonicalSourceBatch,
) -> None:
    root = fixture_bootstrap_batch
    frontier = root.covered_session_range[1]

    direct = FixtureDataSource().collect(CollectionPlan.incremental(frontier))
    wider_source = FixtureDataSource(sessions_after_bootstrap=3)
    catch_up = wider_source.collect(CollectionPlan.incremental(frontier))

    assert len(direct.canonical["research_calendar"]) == 757
    assert len(catch_up.canonical["research_calendar"]) == 759
    assert direct.collection_kind == catch_up.collection_kind == "incremental"
    assert catch_up.source_lineage["source_horizon_sessions_after_bootstrap"] == 3

    intermediate_catch_up = wider_source.collect(
        CollectionPlan.incremental(direct.covered_session_range[1])
    )
    assert len(intermediate_catch_up.canonical["research_calendar"]) == 759
    assert (
        len(intermediate_catch_up.canonical["research_calendar"])
        - len(direct.canonical["research_calendar"])
        == 2
    )

    no_change = FixtureDataSource().collect(
        CollectionPlan.incremental(direct.covered_session_range[1])
    )
    assert len(no_change.canonical["research_calendar"]) == 757
    assert no_change.covered_session_range == direct.covered_session_range


def test_fixture_availability_sequence_advances_deterministically_by_frontier() -> None:
    source = FixtureDataSource(availability_sequence=(1, 2, 3))
    root = source.collect(CollectionPlan.bootstrap())
    observed_counts: list[int] = []
    frontier = root.covered_session_range[1]

    for _ in range(4):
        batch = source.collect(CollectionPlan.incremental(frontier))
        observed_counts.append(len(batch.canonical["research_calendar"]))
        frontier = batch.covered_session_range[1]

    assert observed_counts == [757, 758, 759, 759]


def test_fixture_uses_the_provider_independent_error_contract() -> None:
    with pytest.raises(DataSourceError) as failure:
        FixtureDataSource().collect(CollectionPlan.incremental("2020-01-01"))

    assert failure.value.category == "invalid_source_data"
    assert failure.value.detail_code == "FRONTIER_NOT_RESEARCH_SESSION"


@pytest.mark.parametrize(
    ("kind", "after_session"),
    (
        ("bootstrap", "2026-01-01"),
        ("incremental", None),
        ("unknown", None),
    ),
)
def test_collection_plan_rejects_illegal_states(
    kind: str,
    after_session: str | None,
) -> None:
    with pytest.raises(ValueError, match="CollectionPlan state is invalid"):
        CollectionPlan(kind=kind, after_session=after_session)

from pathlib import Path

import pytest

from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import CollectionPlan


def test_fixture_implements_only_the_canonical_collection_contract() -> None:
    batch = FixtureDataSource().collect(CollectionPlan.bootstrap())

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
        Path(__file__).resolve().parents[2]
        / "src"
        / "thesistrace"
        / "adapters"
        / "fixture_data.py"
    ).read_text()
    for forbidden in ("release", "postgres", "publication", "s3", "research_run", "daily_track"):
        assert forbidden not in source.lower()


def test_fixture_collects_direct_and_wider_incremental_source_gaps() -> None:
    root = FixtureDataSource().collect(CollectionPlan.bootstrap())
    frontier = root.covered_session_range[1]

    direct = FixtureDataSource().collect(CollectionPlan.incremental(frontier))
    catch_up = FixtureDataSource(available_new_sessions=3).collect(
        CollectionPlan.incremental(frontier)
    )

    assert len(direct.canonical["research_calendar"]) == 757
    assert len(catch_up.canonical["research_calendar"]) == 759
    assert direct.collection_kind == catch_up.collection_kind == "incremental"


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

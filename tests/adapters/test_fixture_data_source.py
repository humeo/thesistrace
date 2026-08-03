from pathlib import Path

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

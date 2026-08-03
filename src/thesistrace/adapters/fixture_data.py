from thesistrace.data.source import CanonicalSourceBatch, CollectionPlan
from thesistrace.fixture import build_fixture


class FixtureDataSource:
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        if plan.kind != "bootstrap" or plan.predecessor_id is not None:
            raise ValueError("Fixture bootstrap requires an empty Release history")
        source, canonical = build_fixture()
        calendar = canonical["research_calendar"]
        if not isinstance(calendar, list) or not calendar:
            raise ValueError("Fixture produced no canonical Research Sessions")
        return CanonicalSourceBatch(
            source_name="fixture",
            collection_kind="bootstrap",
            source_lineage={
                "adapter": "fixture-v1",
                "source": source["source"],
                "source_units": source["source_units"],
            },
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )

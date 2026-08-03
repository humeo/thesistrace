import copy
from datetime import date, timedelta

from thesistrace.data.source import CanonicalSourceBatch, CollectionPlan
from thesistrace.fixture import build_fixture


class FixtureDataSource:
    def __init__(self, *, available_new_sessions: int = 1) -> None:
        if not 1 <= available_new_sessions <= 20:
            raise ValueError("Fixture availability must be between 1 and 20 sessions")
        self._available_new_sessions = available_new_sessions

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        if plan.kind not in {"bootstrap", "incremental"}:
            raise ValueError("Fixture collection plan is invalid")
        if plan.kind == "bootstrap" and plan.after_session is not None:
            raise ValueError("Fixture bootstrap requires an empty canonical history")
        source, canonical = build_fixture()
        if plan.kind == "incremental":
            if plan.after_session is None:
                raise ValueError("Fixture incremental collection requires a frontier")
            while str(canonical["research_calendar"][-1]) < plan.after_session:
                _append_session(canonical)
            if str(canonical["research_calendar"][-1]) != plan.after_session:
                raise ValueError("Fixture frontier is not a Research Session")
            for _ in range(self._available_new_sessions):
                _append_session(canonical)
        calendar = canonical["research_calendar"]
        if not isinstance(calendar, list) or not calendar:
            raise ValueError("Fixture produced no canonical Research Sessions")
        return CanonicalSourceBatch(
            source_name="fixture",
            collection_kind=plan.kind,
            source_lineage={
                "adapter": "fixture-v1",
                "after_session": plan.after_session,
                "available_new_sessions": (
                    0 if plan.kind == "bootstrap" else self._available_new_sessions
                ),
                "source": source["source"],
                "source_units": source["source_units"],
            },
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )


def _append_session(canonical: dict[str, object]) -> None:
    calendar = canonical["research_calendar"]
    assert isinstance(calendar, list)
    prior_session = str(calendar[-1])
    candidate = date.fromisoformat(prior_session) + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    new_session = candidate.isoformat()
    calendar.append(new_session)
    for table, session_field in (
        ("prices", "session"),
        ("trading_states", "session"),
        ("price_limits", "session"),
        ("base_pool", "session"),
    ):
        rows = canonical[table]
        assert isinstance(rows, list)
        rows.extend(
            {**copy.deepcopy(row), session_field: new_session}
            for row in list(rows)
            if isinstance(row, dict) and str(row[session_field]) == prior_session
        )
    universes = canonical["liquidity_universes"]
    assert isinstance(universes, dict)
    for rows in universes.values():
        assert isinstance(rows, list)
        prior = next(
            row
            for row in rows
            if isinstance(row, dict) and str(row["session"]) == prior_session
        )
        rows.append({**copy.deepcopy(prior), "session": new_session})

import copy
from datetime import date, timedelta

from thesistrace.data.source import CanonicalSourceBatch, CollectionPlan, DataSourceError
from thesistrace.fixture import build_fixture


class FixtureDataSource:
    def __init__(
        self,
        *,
        sessions_after_bootstrap: int = 1,
        availability_sequence: tuple[int, ...] | None = None,
    ) -> None:
        if not 1 <= sessions_after_bootstrap <= 20:
            raise ValueError("Fixture availability must be between 1 and 20 sessions")
        self._sessions_after_bootstrap = sessions_after_bootstrap
        sequence = availability_sequence or (sessions_after_bootstrap,)
        if (
            not sequence
            or tuple(sorted(set(sequence))) != sequence
            or any(not 1 <= count <= 20 for count in sequence)
        ):
            raise ValueError("Fixture availability sequence must increase within 1..20")
        self._availability_sequence = sequence

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        if plan.kind not in {"bootstrap", "incremental"}:
            raise ValueError("Fixture collection plan is invalid")
        if plan.kind == "bootstrap" and plan.after_session is not None:
            raise ValueError("Fixture bootstrap requires an empty canonical history")
        source, canonical = build_fixture()
        selected_sessions_after_bootstrap = self._sessions_after_bootstrap
        if plan.kind == "incremental":
            if plan.after_session is None:
                raise ValueError("Fixture incremental collection requires a frontier")
            selected_sessions_after_bootstrap = _next_available_session_count(
                plan.after_session,
                self._availability_sequence,
            )
            for _ in range(selected_sessions_after_bootstrap):
                _append_session(canonical)
            if plan.after_session not in canonical["research_calendar"]:
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="FRONTIER_NOT_RESEARCH_SESSION",
                )
        calendar = canonical["research_calendar"]
        if not isinstance(calendar, list) or not calendar:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MISSING_RESEARCH_CALENDAR",
            )
        return CanonicalSourceBatch(
            source_name="fixture",
            collection_kind=plan.kind,
            source_lineage={
                "adapter": "fixture-v1",
                "after_session": plan.after_session,
                "source_horizon_sessions_after_bootstrap": (selected_sessions_after_bootstrap),
                "source": source["source"],
                "source_units": source["source_units"],
            },
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )


def _next_available_session_count(
    after_session: str,
    availability_sequence: tuple[int, ...],
) -> int:
    _source, probe = build_fixture()
    boundaries: dict[int, str] = {}
    for count in range(1, availability_sequence[-1] + 1):
        _append_session(probe)
        calendar = probe["research_calendar"]
        assert isinstance(calendar, list)
        boundaries[count] = str(calendar[-1])
    if after_session not in probe["research_calendar"]:
        raise DataSourceError(
            "invalid_source_data",
            detail_code="FRONTIER_NOT_RESEARCH_SESSION",
        )
    return next(
        (count for count in availability_sequence if boundaries[count] > after_session),
        availability_sequence[-1],
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
            row for row in rows if isinstance(row, dict) and str(row["session"]) == prior_session
        )
        rows.append({**copy.deepcopy(prior), "session": new_session})

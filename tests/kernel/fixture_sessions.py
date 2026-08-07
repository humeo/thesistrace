import copy
from datetime import date, timedelta


def append_fixture_session(
    canonical: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    complete = copy.deepcopy(canonical)
    appended = _append_fixture_session_in_place(complete)
    return complete, appended


def _append_fixture_session_in_place(complete: dict[str, object]) -> dict[str, object]:
    calendar = complete["research_calendar"]
    assert isinstance(calendar, list)
    prior_session = str(calendar[-1])
    candidate = date.fromisoformat(prior_session) + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    new_session = candidate.isoformat()
    calendar.append(new_session)

    appended: dict[str, object] = {
        "schema_version": complete["schema_version"],
        "research_calendar": [new_session],
    }
    for table, session_field in (
        ("prices", "session"),
        ("trading_states", "session"),
        ("price_limits", "session"),
        ("base_pool", "session"),
    ):
        rows = complete[table]
        assert isinstance(rows, list)
        new_rows = [
            {**row, session_field: new_session}
            for row in rows
            if isinstance(row, dict) and str(row[session_field]) == prior_session
        ]
        rows.extend(new_rows)
        appended[table] = copy.deepcopy(new_rows)
    appended["st_designations"] = []

    universes = complete["liquidity_universes"]
    assert isinstance(universes, dict)
    appended_universes: dict[str, object] = {}
    for name, rows in universes.items():
        assert isinstance(rows, list)
        prior = next(
            row for row in rows if isinstance(row, dict) and str(row["session"]) == prior_session
        )
        new_row = {**prior, "session": new_session}
        rows.append(new_row)
        appended_universes[str(name)] = [copy.deepcopy(new_row)]
    appended["liquidity_universes"] = appended_universes
    return appended


def extend_fixture_sessions(
    canonical: dict[str, object],
    *,
    count: int,
) -> tuple[dict[str, object], list[str]]:
    complete = copy.deepcopy(canonical)
    new_sessions: list[str] = []
    for _ in range(count):
        appended = _append_fixture_session_in_place(complete)
        sessions = appended["research_calendar"]
        assert isinstance(sessions, list)
        new_sessions.append(str(sessions[0]))
    return complete, new_sessions

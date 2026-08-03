"""Canonical Research Session slicing shared by Kernel Run and Advance."""

import json
from collections.abc import Mapping, Sequence

from thesistrace.research_kernel.serialization import canonical_json_bytes

SESSION_TABLES = (
    ("prices", "session"),
    ("trading_states", "session"),
    ("price_limits", "session"),
    ("base_pool", "session"),
    ("st_designations", "trade_date"),
)


def canonical_sessions(value: Mapping[str, object], name: str) -> list[str]:
    calendar = value.get("research_calendar")
    if not isinstance(calendar, list):
        raise ValueError(f"{name} Research Sessions are invalid")
    return [str(session) for session in calendar]


def slice_canonical_sessions(
    canonical: dict[str, object],
    sessions: Sequence[str],
) -> dict[str, object]:
    selected_sessions = [str(session) for session in sessions]
    selected = set(selected_sessions)
    sliced = json.loads(canonical_json_bytes(canonical))
    sliced["research_calendar"] = selected_sessions
    for table, session_field in SESSION_TABLES:
        rows = sliced.get(table, [])
        if isinstance(rows, list):
            sliced[table] = [
                row
                for row in rows
                if isinstance(row, dict) and str(row.get(session_field, "")) in selected
            ]
    universes = sliced.get("liquidity_universes")
    if not isinstance(universes, dict):
        raise ValueError("Canonical Liquidity Universes are invalid")
    sliced["liquidity_universes"] = {
        name: [
            row for row in rows if isinstance(row, dict) and str(row.get("session", "")) in selected
        ]
        for name, rows in universes.items()
        if isinstance(rows, list)
    }
    return sliced

"""Pure Research Kernel Advance contract."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from thesistrace.research_kernel.kernel_run import (
    KernelRunError,
    KernelState,
    initial_state,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes

SESSION_TABLES = (
    ("prices", "session"),
    ("trading_states", "session"),
    ("price_limits", "session"),
    ("base_pool", "session"),
    ("st_designations", "trade_date"),
)
STATIC_TABLES = (
    "instruments",
    "adjustment_anchors",
    "industry_membership",
    "field_catalog",
)


@dataclass(frozen=True, init=False)
class AdvanceInput:
    _prior_state: KernelState = field(repr=False)
    _new_canonical_json: bytes = field(repr=False)

    def __init__(
        self,
        *,
        prior_state: KernelState,
        new_canonical_sessions: dict[str, object],
    ) -> None:
        object.__setattr__(self, "_prior_state", prior_state)
        object.__setattr__(
            self,
            "_new_canonical_json",
            canonical_json_bytes(new_canonical_sessions),
        )

    def prior_state(self) -> KernelState:
        return self._prior_state

    def new_canonical_snapshot(self) -> dict[str, object]:
        value = json.loads(self._new_canonical_json)
        if not isinstance(value, dict):
            raise KernelRunError("Advance canonical snapshot is invalid")
        return value


def advance(advance_input: AdvanceInput) -> KernelState:
    prior = advance_input.prior_state()
    canonical = _append_canonical_sessions(
        prior.canonical_snapshot(),
        advance_input.new_canonical_snapshot(),
    )
    return initial_state(
        prior.run_input_with_canonical(canonical),
        origin_session=prior.origin_session,
    )


def _append_canonical_sessions(
    prior: dict[str, object],
    appended: dict[str, object],
) -> dict[str, object]:
    prior_calendar = prior.get("research_calendar")
    appended_calendar = appended.get("research_calendar")
    if not isinstance(prior_calendar, list) or not isinstance(appended_calendar, list):
        raise KernelRunError("Advance requires canonical Research Sessions")
    new_sessions = [str(value) for value in appended_calendar]
    if not new_sessions:
        raise KernelRunError("Advance requires at least one new Research Session")
    if new_sessions != sorted(set(new_sessions)) or new_sessions[0] <= str(prior_calendar[-1]):
        raise KernelRunError("Advance Research Sessions must be new and canonically ordered")
    if appended.get("schema_version", prior.get("schema_version")) != prior.get("schema_version"):
        raise KernelRunError("Advance canonical schema does not match prior state")

    merged = json.loads(canonical_json_bytes(prior))
    merged["research_calendar"] = [*prior_calendar, *new_sessions]
    allowed_sessions = set(new_sessions)
    for table, session_field in SESSION_TABLES:
        rows = appended.get(table, [])
        if not isinstance(rows, list):
            raise KernelRunError(f"Advance canonical table is invalid: {table}")
        if any(
            not isinstance(row, dict) or str(row.get(session_field, "")) not in allowed_sessions
            for row in rows
        ):
            raise KernelRunError(f"Advance {table} contains a non-new session")
        prior_rows = merged.get(table, [])
        if not isinstance(prior_rows, list):
            raise KernelRunError(f"Prior canonical table is invalid: {table}")
        merged[table] = [*prior_rows, *rows]

    prior_universes = merged.get("liquidity_universes")
    appended_universes = appended.get("liquidity_universes")
    if not isinstance(prior_universes, dict) or not isinstance(appended_universes, dict):
        raise KernelRunError("Advance requires canonical Liquidity Universes")
    for name, rows in appended_universes.items():
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or str(row.get("session", "")) not in allowed_sessions
            for row in rows
        ):
            raise KernelRunError("Advance Liquidity Universe contains a non-new session")
        prior_rows = prior_universes.get(name)
        if not isinstance(prior_rows, list):
            raise KernelRunError(f"Advance has no pinned Liquidity Universe: {name}")
        prior_universes[name] = [*prior_rows, *rows]

    for table in STATIC_TABLES:
        replacement = appended.get(table)
        if replacement not in (None, []):
            if not isinstance(replacement, list):
                raise KernelRunError(f"Advance static table is invalid: {table}")
            merged[table] = replacement
    return merged

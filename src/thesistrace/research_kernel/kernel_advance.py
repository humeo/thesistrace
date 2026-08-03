"""Pure Research Kernel Advance contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256

from thesistrace.research_kernel.alpha import (
    alpha_matrix_checksum,
    evaluate_alpha_matrix,
)
from thesistrace.research_kernel.factor import (
    HORIZONS,
    affected_label_sessions,
    build_forward_labels,
    evaluate_factor,
)
from thesistrace.research_kernel.kernel_run import (
    KernelRunError,
    KernelState,
    RunInput,
    calculation_definition,
    compose_output,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy import run_strategy

SESSION_TABLES = (
    ("prices", "session"),
    ("trading_states", "session"),
    ("price_limits", "session"),
    ("base_pool", "session"),
    ("st_designations", "trade_date"),
)
EVOLVING_REFERENCE_TABLES = (
    "instruments",
    "adjustment_anchors",
    "industry_membership",
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
    prior_output = prior.output_snapshot()
    prior_matrix = _mapping(prior_output.get("alpha_matrix"), "prior Alpha Matrix")
    prior_labels = _mapping(prior_output.get("forward_labels"), "prior Labels")
    prior_strategy = _mapping(prior_output.get("strategy_backtest"), "prior Strategy")
    appended = advance_input.new_canonical_snapshot()
    canonical = _append_canonical_sessions(
        prior.canonical_snapshot(),
        appended,
    )
    run_input = prior.run_input_with_canonical(canonical)
    new_sessions = _sessions(appended, "Advance")
    matrix = _advance_alpha(
        run_input,
        canonical,
        prior_matrix,
        new_sessions,
        prior.session_count,
    )
    labels = _advance_labels(canonical, matrix, prior_labels, new_sessions)
    factor = evaluate_factor(labels)
    strategy = run_strategy(
        canonical,
        matrix,
        calculation_definition(run_input),
        origin_session=prior.origin_session,
        terminal_cutoff=False,
        continuation=dict(prior_strategy),
    )
    return KernelState(
        run_input=run_input,
        output=compose_output(matrix, labels, factor, strategy),
        origin_session=prior.origin_session,
    )


def _advance_alpha(
    run_input: RunInput,
    canonical: dict[str, object],
    prior_matrix: Mapping[str, object],
    new_sessions: list[str],
    prior_session_count: int,
) -> dict[str, object]:
    lookback = int(prior_matrix["effective_lookback"])
    calendar = _sessions(canonical, "Canonical")
    window_start = max(0, prior_session_count - lookback)
    window = _slice_canonical(canonical, calendar[window_start:])
    evaluated = evaluate_alpha_matrix(
        window,
        expression=run_input.alpha_expression_snapshot(),
        field_bindings=run_input.field_bindings_snapshot(),
        universe_name=run_input.universe,
        neutralization=run_input.neutralization,
    )
    new_set = set(new_sessions)
    evaluated_sessions = evaluated.get("sessions")
    prior_sessions = prior_matrix.get("sessions")
    if not isinstance(evaluated_sessions, list) or not isinstance(prior_sessions, list):
        raise KernelRunError("Advance Alpha state is invalid")
    appended_sessions = [
        dict(item)
        for item in evaluated_sessions
        if isinstance(item, Mapping) and str(item.get("session")) in new_set
    ]
    if [str(item["session"]) for item in appended_sessions] != new_sessions:
        raise KernelRunError("Advance Alpha calculation did not cover every new session")
    sessions = [dict(item) for item in prior_sessions]
    sessions.extend(appended_sessions)
    return {
        "expression": run_input.alpha_expression_snapshot(),
        "effective_lookback": lookback,
        "neutralization": run_input.neutralization,
        "sessions": sessions,
        "checksum": alpha_matrix_checksum(sessions),
    }


def _advance_labels(
    canonical: dict[str, object],
    matrix: dict[str, object],
    prior_labels: Mapping[str, object],
    new_sessions: list[str],
) -> dict[str, object]:
    calendar = _sessions(canonical, "Canonical")
    selected_sessions = calendar[-504:]
    selected_set = set(selected_sessions)
    prior_horizons = _mapping(prior_labels.get("horizons"), "prior Label horizons")
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        prior_horizon = _mapping(
            prior_horizons.get(str(horizon)),
            f"prior Label horizon {horizon}",
        )
        prior_rows = prior_horizon.get("sessions")
        if not isinstance(prior_rows, list):
            raise KernelRunError("prior Label sessions are invalid")
        affected_sessions = affected_label_sessions(calendar, new_sessions, horizon)
        partial = build_forward_labels(
            canonical,
            matrix,
            signal_sessions=affected_sessions,
            horizons=(horizon,),
        )
        partial_horizon = _mapping(
            _mapping(partial.get("horizons"), "partial Label horizons").get(str(horizon)),
            "partial Label horizon",
        )
        partial_rows = partial_horizon.get("sessions")
        if not isinstance(partial_rows, list):
            raise KernelRunError("partial Label sessions are invalid")
        by_session = {
            str(item["session"]): dict(item)
            for item in prior_rows
            if isinstance(item, Mapping) and str(item.get("session")) in selected_set
        }
        by_session.update(
            {str(item["session"]): dict(item) for item in partial_rows if isinstance(item, Mapping)}
        )
        if set(by_session) != selected_set:
            raise KernelRunError("Advance Label state is incomplete")
        sessions = [by_session[session] for session in selected_sessions]
        payload = {"horizon": horizon, "sessions": sessions}
        horizons[str(horizon)] = {
            **payload,
            "checksum": sha256(canonical_json_bytes(payload)).hexdigest(),
        }
    return {
        "alpha_checksum": matrix["checksum"],
        "report_session_count": len(selected_sessions),
        "horizons": horizons,
    }


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

    supplied_field_catalog = appended.get("field_catalog")
    if supplied_field_catalog not in (None, []) and supplied_field_catalog != prior.get(
        "field_catalog"
    ):
        raise KernelRunError("Advance cannot replace pinned static table: field_catalog")
    for table in EVOLVING_REFERENCE_TABLES:
        supplied = appended.get(table)
        if supplied in (None, []):
            continue
        if not isinstance(supplied, list):
            raise KernelRunError(f"Advance reference table is invalid: {table}")
        merged[table] = supplied
    return merged


def _slice_canonical(
    canonical: dict[str, object],
    sessions: list[str],
) -> dict[str, object]:
    selected = set(sessions)
    sliced = json.loads(canonical_json_bytes(canonical))
    sliced["research_calendar"] = sessions
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
        raise KernelRunError("Canonical Liquidity Universes are invalid")
    sliced["liquidity_universes"] = {
        name: [
            row for row in rows if isinstance(row, dict) and str(row.get("session", "")) in selected
        ]
        for name, rows in universes.items()
        if isinstance(rows, list)
    }
    return sliced


def _sessions(value: Mapping[str, object], name: str) -> list[str]:
    calendar = value.get("research_calendar")
    if not isinstance(calendar, list):
        raise KernelRunError(f"{name} Research Sessions are invalid")
    return [str(session) for session in calendar]


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise KernelRunError(f"{name} is invalid")
    return value

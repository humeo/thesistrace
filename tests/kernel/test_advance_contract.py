import copy
from datetime import date, timedelta

from thesistrace.research_kernel import (
    AdvanceInput,
    RunInput,
    advance,
    initial_state,
)

FIELD_BINDINGS = {
    "price.open.adjusted": "open_adj",
    "price.high.adjusted": "high_adj",
    "price.low.adjusted": "low_adj",
    "price.close.adjusted": "close_adj",
    "market.volume.shares": "volume_shares",
    "market.turnover.cny": "turnover_amount_cny",
}


def test_kernel_advance_matches_the_characterized_state_at_the_same_boundary(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = _append_fixture_session(canonical)
    prior = initial_state(_run_input(canonical, definition))
    prior_output = prior.output_snapshot()
    advance_input = AdvanceInput(
        prior_state=prior,
        new_canonical_sessions=appended,
    )

    appended["research_calendar"] = []
    result = advance(advance_input)
    expected = initial_state(
        _run_input(complete, definition),
        origin_session=prior.origin_session,
    )

    assert result.output_snapshot() == expected.output_snapshot()
    assert result.origin_session == prior.origin_session
    assert result.session_count == prior.session_count + 1
    assert result.boundary_session == complete["research_calendar"][-1]
    assert prior.output_snapshot() == prior_output
    assert prior.session_count == 756
    assert not {
        "run_id",
        "release_id",
        "request_id",
        "transaction",
        "object_key",
        "workspace_id",
        "mode",
    } & set(AdvanceInput.__dataclass_fields__)
    for field_name in AdvanceInput.__dataclass_fields__:
        assert not isinstance(getattr(advance_input, field_name), (dict, list, set))


def _append_fixture_session(
    canonical: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    complete = copy.deepcopy(canonical)
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
    return complete, appended


def _run_input(canonical: object, definition: dict[str, object]) -> RunInput:
    alpha = definition["alpha"]
    strategy = definition["strategy"]
    costs = definition["costs"]
    assert isinstance(canonical, dict)
    assert isinstance(alpha, dict)
    assert isinstance(strategy, dict)
    assert isinstance(costs, dict)
    return RunInput(
        canonical_data=canonical,
        alpha_expression=alpha["expression"],
        field_bindings=FIELD_BINDINGS,
        universe=str(definition["universe"]),
        neutralization=str(definition["neutralization"]),
        holdings_count=int(strategy["holdings_count"]),
        rebalance_interval=int(strategy["rebalance_interval"]),
        initial_cash_cny=str(strategy["initial_cash_cny"]),
        commission_rate_all_in=str(costs["commission_rate_all_in"]),
        commission_min_cny=str(costs["commission_min_cny"]),
        stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(costs["transfer_fee_rate"]),
    )

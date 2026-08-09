from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from thesistrace.data.canonical_mapping import (
    CanonicalMappingError,
    adjusted_price_string,
)

UNIVERSE_NAMES = ("top300", "top1000", "top2000", "top3000")


class GenerationValidationError(ValueError):
    pass


def validate_canonical_generation(canonical: Mapping[str, object]) -> None:
    if canonical.get("schema_version") != "canonical-eod-v1":
        raise GenerationValidationError("Canonical Generation schema is incompatible")
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or not calendar or calendar != sorted(set(calendar)):
        raise GenerationValidationError("Canonical Research Calendar is invalid")
    try:
        parsed_calendar = [date.fromisoformat(str(session)) for session in calendar]
    except ValueError as error:
        raise GenerationValidationError("Canonical Research Calendar is invalid") from error
    if any(session.weekday() >= 5 for session in parsed_calendar):
        raise GenerationValidationError("Canonical Research Calendar is invalid")
    calendar_set = set(map(str, calendar))

    instruments = _rows(canonical, "instruments")
    instrument_ids = [str(row["instrument_id"]) for row in instruments]
    instrument_set = set(instrument_ids)
    if not instrument_ids or len(instrument_ids) != len(instrument_set):
        raise GenerationValidationError("Canonical instrument identities are invalid")
    listed_from_by_instrument: dict[str, date] = {}
    for row in instruments:
        listed_from = _iso_date(row["listed_from"], "Canonical Instrument.listed_from")
        listed_from_by_instrument[str(row["instrument_id"])] = listed_from
        listed_to = row["listed_to"]
        if listed_to and _iso_date(listed_to, "Canonical Instrument.listed_to") < listed_from:
            raise GenerationValidationError("Canonical instrument lifecycle is invalid")

    base_pool = _rows(canonical, "base_pool")
    if [str(row["session"]) for row in base_pool] != list(map(str, calendar)):
        raise GenerationValidationError("Canonical Base Pool coverage is invalid")
    base_positions: set[tuple[str, str]] = set()
    base_by_session: dict[str, set[str]] = {}
    for row in base_pool:
        members = row["instrument_ids"]
        if not isinstance(members, list):
            raise GenerationValidationError("Canonical Base Pool membership is invalid")
        member_ids = [str(value) for value in members]
        if len(member_ids) != len(set(member_ids)) or not set(member_ids) <= instrument_set:
            raise GenerationValidationError("Canonical Base Pool membership is invalid")
        session = str(row["session"])
        base_by_session[session] = set(member_ids)
        base_positions.update((session, instrument_id) for instrument_id in member_ids)

    states = _rows(canonical, "trading_states")
    state_by_position = _unique_positions(states, "session", "Canonical Trading State")
    if set(state_by_position) != base_positions or any(
        row["state"]
        not in {
            "normal",
            "full_session_suspension",
            "partial_opening_suspension",
            "after_open_suspension",
        }
        for row in states
    ):
        raise GenerationValidationError("Canonical Trading State coverage is invalid")

    anchors = _rows(canonical, "adjustment_anchors")
    if {str(row["instrument_id"]) for row in anchors} != instrument_set or len(anchors) != len(
        instrument_set
    ):
        raise GenerationValidationError("Canonical Adjustment Anchor coverage is invalid")
    anchor_by_instrument: dict[str, Decimal] = {}
    for row in anchors:
        anchor_factor = _finite_decimal(row["anchor_factor"], "Canonical Adjustment Anchor.factor")
        instrument_id = str(row["instrument_id"])
        anchor_session = _iso_date(row["anchor_session"], "Canonical Adjustment Anchor.session")
        if (
            anchor_session.weekday() >= 5
            or anchor_session < listed_from_by_instrument[instrument_id]
            or anchor_session > parsed_calendar[-1]
            or anchor_factor <= 0
        ):
            raise GenerationValidationError("Canonical Adjustment Anchor is invalid")
        anchor_by_instrument[instrument_id] = anchor_factor

    prices = _rows(canonical, "prices")
    price_by_position = _unique_positions(prices, "session", "Canonical Price")
    expected_trade_positions = {
        position
        for position, row in state_by_position.items()
        if row["state"] != "full_session_suspension"
    }
    if set(price_by_position) != expected_trade_positions:
        raise GenerationValidationError("Canonical Price coverage is invalid")
    for position, row in price_by_position.items():
        if row["trading_state"] != state_by_position[position]["state"]:
            raise GenerationValidationError("Canonical Price trading state is invalid")
        values = {
            field: _finite_decimal(row[field], f"Canonical Price.{field}")
            for field in (
                "open_raw",
                "high_raw",
                "low_raw",
                "close_raw",
                "pre_close_raw",
                "change_raw",
                "pct_change_raw",
                "volume_shares",
                "turnover_cny",
                "adjustment_factor",
                "adjustment_anchor_factor",
                "open_adj",
                "high_adj",
                "low_adj",
                "close_adj",
            )
        }
        anchor = anchor_by_instrument[position[1]]
        if values["adjustment_anchor_factor"] != anchor:
            raise GenerationValidationError("Canonical Price adjustment anchor is inconsistent")
        try:
            expected_adjusted = {
                field: adjusted_price_string(
                    values[f"{field}_raw"], values["adjustment_factor"], anchor
                )
                for field in ("open", "high", "low", "close")
            }
        except CanonicalMappingError as error:
            raise GenerationValidationError(
                "Canonical Price adjustment factor is invalid"
            ) from error
        if any(row[f"{field}_adj"] != expected for field, expected in expected_adjusted.items()):
            raise GenerationValidationError("Canonical adjusted Price derivation is inconsistent")

    limits = _rows(canonical, "price_limits")
    limit_by_position = _unique_positions(limits, "session", "Canonical Price Limit")
    if set(limit_by_position) != expected_trade_positions:
        raise GenerationValidationError("Canonical Price Limit coverage is invalid")
    for row in limits:
        _finite_decimal(row["upper"], "Canonical Price Limit.upper")
        _finite_decimal(row["lower"], "Canonical Price Limit.lower")

    _validate_universes(canonical, calendar, base_by_session)
    _validate_classification(canonical, calendar_set, instrument_set)


def _validate_universes(
    canonical: Mapping[str, object],
    calendar: list[object],
    base_by_session: Mapping[str, set[str]],
) -> None:
    universes = canonical.get("liquidity_universes")
    if not isinstance(universes, Mapping) or set(universes) != set(UNIVERSE_NAMES):
        raise GenerationValidationError("Canonical Liquidity Universes are invalid")
    universe_members: dict[str, list[list[str]]] = {}
    for name in UNIVERSE_NAMES:
        rows = universes[name]
        if not isinstance(rows, list) or [str(row["session"]) for row in rows] != list(
            map(str, calendar)
        ):
            raise GenerationValidationError("Canonical Liquidity Universe coverage is invalid")
        universe_members[name] = []
        for row in rows:
            members = row["instrument_ids"]
            if (
                not isinstance(members, list)
                or len(members) != len(set(map(str, members)))
                or not set(map(str, members)) <= base_by_session[str(row["session"])]
                or row["status"] != "available"
            ):
                raise GenerationValidationError(
                    "Canonical Liquidity Universe membership is invalid"
                )
            universe_members[name].append([str(value) for value in members])
    for session_index in range(len(calendar)):
        prior: list[str] = []
        for name, maximum_size in zip(UNIVERSE_NAMES, (300, 1000, 2000, 3000), strict=True):
            members = universe_members[name][session_index]
            if len(members) > maximum_size or prior != members[: len(prior)]:
                raise GenerationValidationError("Canonical Liquidity Universe nesting is invalid")
            prior = members


def _validate_classification(
    canonical: Mapping[str, object],
    calendar_set: set[str],
    instrument_set: set[str],
) -> None:
    industries = _rows(canonical, "industry_membership")
    prior_end_by_instrument: dict[str, date] = {}
    for row in industries:
        instrument_id = str(row["instrument_id"])
        active_from = _iso_date(row["active_from"], "Canonical Industry.active_from")
        active_to = (
            _iso_date(row["active_to"], "Canonical Industry.active_to")
            if row["active_to"]
            else date.max
        )
        if (
            instrument_id not in instrument_set
            or active_to < active_from
            or active_from < prior_end_by_instrument.get(instrument_id, date.min)
            or not all(row[field] for field in ("sw2021_l1", "sw2021_l2", "sw2021_l3"))
        ):
            raise GenerationValidationError("Canonical Industry Membership is invalid")
        prior_end_by_instrument[instrument_id] = active_to
    if any(
        str(row["instrument_id"]) not in instrument_set
        or str(row["trade_date"]) not in calendar_set
        for row in _rows(canonical, "st_designations")
    ):
        raise GenerationValidationError("Canonical ST Designation is invalid")
    field_ids = [str(row["field_id"]) for row in _rows(canonical, "field_catalog")]
    if not field_ids or len(field_ids) != len(set(field_ids)):
        raise GenerationValidationError("Canonical Field Catalog is invalid")


def _rows(canonical: Mapping[str, object], name: str) -> list[dict[str, object]]:
    value = canonical.get(name)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise GenerationValidationError(f"Canonical table is invalid: {name}")
    return value


def _unique_positions(
    rows: list[dict[str, object]],
    session_field: str,
    name: str,
) -> dict[tuple[str, str], dict[str, object]]:
    result = {(str(row[session_field]), str(row["instrument_id"])): row for row in rows}
    if len(result) != len(rows):
        raise GenerationValidationError(f"{name} identities are invalid")
    return result


def _finite_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str) or not value:
        raise GenerationValidationError(f"{name} is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise GenerationValidationError(f"{name} is invalid") from error
    if not result.is_finite():
        raise GenerationValidationError(f"{name} is invalid")
    return result


def _iso_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise GenerationValidationError(f"{name} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise GenerationValidationError(f"{name} is invalid") from error


__all__ = ("GenerationValidationError", "UNIVERSE_NAMES", "validate_canonical_generation")

from datetime import date
from decimal import Decimal, InvalidOperation

from thesistrace.data.source import CanonicalSourceBatch
from thesistrace.publication.serialization import canonical_json_bytes

PRICE_VALUE_FIELDS = (
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


def validate_bootstrap_batch(batch: CanonicalSourceBatch) -> None:
    validate_release_batch(batch, predecessor_session=None)


def validate_release_batch(
    batch: CanonicalSourceBatch,
    *,
    predecessor_session: str | None,
) -> None:
    canonical = batch.canonical
    calendar = canonical.get("research_calendar")
    if canonical.get("schema_version") != "canonical-eod-v1":
        raise ValueError("Bootstrap canonical schema is invalid")
    if not isinstance(calendar, list) or not calendar or calendar != sorted(set(calendar)):
        raise ValueError("Bootstrap calendar coverage is invalid")
    if predecessor_session is None:
        if batch.collection_kind != "bootstrap":
            raise ValueError("Bootstrap collection kind is invalid")
    elif (
        batch.collection_kind != "incremental"
        or predecessor_session not in calendar
        or str(calendar[-1]) < predecessor_session
    ):
        raise ValueError("Incremental canonical frontier regressed")
    parsed_calendar = [_date(value, "Research Calendar") for value in calendar]
    if any(value.weekday() >= 5 for value in parsed_calendar):
        raise ValueError("Bootstrap Research Calendar contains a non-trading weekday")
    if batch.covered_session_range != (str(calendar[0]), str(calendar[-1])):
        raise ValueError("Bootstrap calendar coverage is invalid")

    instruments = _required_rows(canonical, "instruments")
    instrument_order = [str(row.get("instrument_id", "")) for row in instruments]
    instrument_ids = set(instrument_order)
    if "" in instrument_ids or len(instrument_ids) != len(instruments):
        raise ValueError("Bootstrap instrument identities are invalid")
    _validate_point_in_time(instruments, instrument_ids, "instruments")

    states = _required_rows(canonical, "trading_states")
    expected_state_count = len(calendar) * len(instrument_order)
    if len(states) != expected_state_count:
        raise ValueError("Bootstrap Trading State coverage is incomplete")
    for ordinal, row in enumerate(states):
        expected = (
            str(calendar[ordinal // len(instrument_order)]),
            instrument_order[ordinal % len(instrument_order)],
        )
        if _position(row) != expected or row.get("state") not in {
            "normal",
            "full_session_suspension",
            "partial_opening_suspension",
            "after_open_suspension",
        }:
            raise ValueError("Bootstrap Trading State coverage is incomplete")

    prices = _required_rows(canonical, "prices")
    limits = _required_rows(canonical, "price_limits")
    expected_trade_count = sum(row["state"] != "full_session_suspension" for row in states)
    if len(prices) != expected_trade_count or len(limits) != expected_trade_count:
        raise ValueError("Bootstrap Price coverage is incomplete")
    price_index = 0
    for state in states:
        if state["state"] == "full_session_suspension":
            continue
        price = prices[price_index]
        limit = limits[price_index]
        expected = _position(state)
        if _position(price) != expected or _position(limit) != expected:
            raise ValueError("Bootstrap Price coverage is incomplete")
        if any(field not in price for field in PRICE_VALUE_FIELDS) or any(
            field not in limit for field in ("upper", "lower")
        ):
            raise ValueError("Bootstrap Price schema is incomplete")
        for field in PRICE_VALUE_FIELDS:
            _decimal(price[field], f"Price.{field}")
        _decimal(limit["upper"], "Price Limit.upper")
        _decimal(limit["lower"], "Price Limit.lower")
        price_index += 1

    base_pool = _required_rows(canonical, "base_pool")
    if [str(row.get("session", "")) for row in base_pool] != calendar or any(
        not isinstance(row.get("instrument_ids"), list)
        or not set(map(str, row["instrument_ids"])) <= instrument_ids
        for row in base_pool
    ):
        raise ValueError("Bootstrap Base Pool coverage is incomplete")

    anchors = _required_rows(canonical, "adjustment_anchors")
    if [str(row.get("instrument_id", "")) for row in anchors] != instrument_order:
        raise ValueError("Bootstrap Adjustment Anchor coverage is incomplete")
    for row in anchors:
        anchor_session = _date(row.get("anchor_session"), "Adjustment Anchor")
        if anchor_session > parsed_calendar[-1]:
            raise ValueError("Bootstrap Adjustment Anchor coverage is incomplete")
        if _decimal(row.get("anchor_factor"), "Adjustment Anchor.factor") <= 0:
            raise ValueError("Bootstrap Adjustment Anchor factor is invalid")

    universes = canonical.get("liquidity_universes")
    if not isinstance(universes, dict) or set(universes) != {
        "top300",
        "top1000",
        "top2000",
        "top3000",
    }:
        raise ValueError("Bootstrap Liquidity Universes are invalid")
    for rows in universes.values():
        if (
            not isinstance(rows, list)
            or [row.get("session") for row in rows if isinstance(row, dict)] != calendar
        ):
            raise ValueError("Bootstrap Liquidity Universe coverage is incomplete")
        if any(
            not isinstance(row, dict)
            or not isinstance(row.get("instrument_ids"), list)
            or not set(map(str, row["instrument_ids"])) <= instrument_ids
            for row in rows
        ):
            raise ValueError("Bootstrap Liquidity Universe coverage is incomplete")

    industries = _required_rows(canonical, "industry_membership")
    _validate_point_in_time(industries, instrument_ids, "industry_membership")
    if any(
        not all(row.get(field) for field in ("sw2021_l1", "sw2021_l2", "sw2021_l3"))
        for row in industries
    ):
        raise ValueError("Bootstrap Industry Membership schema is incomplete")

    fields = _required_rows(canonical, "field_catalog")
    field_ids = [str(field.get("field_id", "")) for field in fields]
    if (
        "" in field_ids
        or len(set(field_ids)) != len(field_ids)
        or any(
            not all(
                key in field
                for key in (
                    "definition",
                    "unit",
                    "time_semantics",
                    "alpha_authorable",
                    "release_available_from",
                )
            )
            for field in fields
        )
    ):
        raise ValueError("Bootstrap Field Catalog schema is invalid")
    canonical_json_bytes(canonical)


def _required_rows(canonical: dict[str, object], table: str) -> list[dict[str, object]]:
    value = canonical.get(table)
    if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Bootstrap canonical table is missing or empty: {table}")
    return value


def _position(row: dict[str, object]) -> tuple[str, str]:
    return str(row.get("session", "")), str(row.get("instrument_id", ""))


def _validate_point_in_time(
    rows: list[dict[str, object]], instrument_ids: set[str], table: str
) -> None:
    for row in rows:
        if str(row.get("instrument_id", "")) not in instrument_ids:
            raise ValueError(f"Bootstrap point-in-time instrument is invalid: {table}")
        start = _date(row.get("listed_from", row.get("active_from")), table)
        raw_end = row.get("listed_to", row.get("active_to", ""))
        if raw_end not in (None, "") and _date(raw_end, table) < start:
            raise ValueError(f"Bootstrap point-in-time interval is invalid: {table}")


def _date(value: object, subject: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"Bootstrap {subject} date is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Bootstrap {subject} date is invalid") from error


def _decimal(value: object, subject: str) -> Decimal:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Bootstrap {subject} numeric value is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Bootstrap {subject} numeric value is invalid") from error
    if not result.is_finite():
        raise ValueError(f"Bootstrap {subject} numeric value is invalid")
    return result

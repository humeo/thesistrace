from datetime import date

from thesistrace.data.source import CanonicalSourceBatch
from thesistrace.publication.serialization import canonical_json_bytes


def validate_bootstrap_batch(batch: CanonicalSourceBatch) -> None:
    canonical = batch.canonical
    calendar = canonical.get("research_calendar")
    if canonical.get("schema_version") != "canonical-eod-v1":
        raise ValueError("Bootstrap canonical schema is invalid")
    if (
        not isinstance(calendar, list)
        or len(calendar) != 756
        or calendar != sorted(set(calendar))
        or batch.covered_session_range != (str(calendar[0]), str(calendar[-1]))
    ):
        raise ValueError("Bootstrap calendar or three-year coverage is invalid")
    if (date.fromisoformat(str(calendar[-1])) - date.fromisoformat(str(calendar[0]))).days < 1000:
        raise ValueError("Bootstrap does not cover three calendar years")

    instruments = canonical.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        raise ValueError("Bootstrap instrument reference is missing")
    instrument_ids = {str(row.get("instrument_id")) for row in instruments if isinstance(row, dict)}
    if len(instrument_ids) != len(instruments):
        raise ValueError("Bootstrap instrument identities are invalid")
    calendar_set = set(calendar)
    prices = _required_rows(canonical, "prices")
    states = _required_rows(canonical, "trading_states")
    limits = _required_rows(canonical, "price_limits")
    base_pool = _required_rows(canonical, "base_pool")
    anchors = _required_rows(canonical, "adjustment_anchors")

    expected_positions = {
        (str(session), instrument_id)
        for session in calendar
        for instrument_id in instrument_ids
    }
    state_positions = _position_keys(states, calendar_set, instrument_ids, "trading_states")
    if state_positions != expected_positions:
        raise ValueError("Bootstrap Trading State coverage is incomplete")
    suspended = {
        (str(row["session"]), str(row["instrument_id"]))
        for row in states
        if row.get("state") == "full_session_suspension"
    }
    price_positions = _position_keys(prices, calendar_set, instrument_ids, "prices")
    limit_positions = _position_keys(limits, calendar_set, instrument_ids, "price_limits")
    if price_positions != expected_positions - suspended or limit_positions != price_positions:
        raise ValueError("Bootstrap Price coverage is incomplete")
    required_price_fields = {
        "open_raw",
        "high_raw",
        "low_raw",
        "close_raw",
        "volume_shares",
        "turnover_cny",
        "adjustment_factor",
        "adjustment_anchor_factor",
        "open_adj",
        "high_adj",
        "low_adj",
        "close_adj",
    }
    if any(not required_price_fields <= set(row) for row in prices):
        raise ValueError("Bootstrap Price schema is incomplete")

    pool_sessions = [str(row.get("session", "")) for row in base_pool]
    if pool_sessions != calendar or any(
        not isinstance(row.get("instrument_ids"), list)
        or not set(map(str, row["instrument_ids"])) <= instrument_ids
        for row in base_pool
    ):
        raise ValueError("Bootstrap Base Pool coverage is incomplete")
    anchor_instruments = {str(row.get("instrument_id", "")) for row in anchors}
    if anchor_instruments != instrument_ids or any(
        row.get("anchor_session") not in calendar_set or "anchor_factor" not in row
        for row in anchors
    ):
        raise ValueError("Bootstrap Adjustment Anchor coverage is incomplete")

    universes = canonical.get("liquidity_universes")
    if not isinstance(universes, dict) or set(universes) != {
        "top300",
        "top1000",
        "top2000",
        "top3000",
    }:
        raise ValueError("Bootstrap Liquidity Universes are invalid")
    if any(
        not isinstance(rows, list)
        or [row.get("session") for row in rows if isinstance(row, dict)] != calendar
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("instrument_ids"), list)
            or not set(map(str, row["instrument_ids"])) <= instrument_ids
            for row in rows
        )
        for rows in universes.values()
    ):
        raise ValueError("Bootstrap Liquidity Universe coverage is incomplete")

    field_catalog = canonical.get("field_catalog")
    if not isinstance(field_catalog, list) or not field_catalog:
        raise ValueError("Bootstrap Field Catalog is missing")
    field_ids = {str(field.get("field_id")) for field in field_catalog if isinstance(field, dict)}
    if len(field_ids) != len(field_catalog):
        raise ValueError("Bootstrap Field Catalog identities are invalid")

    for table in ("instruments", "industry_membership"):
        rows = canonical.get(table)
        if not isinstance(rows, list):
            raise ValueError(f"Bootstrap point-in-time table is invalid: {table}")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Bootstrap point-in-time row is invalid: {table}")
            start = str(row.get("listed_from", row.get("active_from", "")))
            end = str(row.get("listed_to", row.get("active_to", "")))
            if not start or (end and end < start):
                raise ValueError(f"Bootstrap point-in-time interval is invalid: {table}")

    canonical_json_bytes(canonical)


def _required_rows(canonical: dict[str, object], table: str) -> list[dict[str, object]]:
    value = canonical.get(table)
    if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Bootstrap canonical table is missing or empty: {table}")
    return value


def _position_keys(
    rows: list[dict[str, object]],
    calendar: set[object],
    instruments: set[str],
    table: str,
) -> set[tuple[str, str]]:
    keys = {
        (str(row.get("session", "")), str(row.get("instrument_id", "")))
        for row in rows
    }
    if (
        len(keys) != len(rows)
        or any(
            session not in calendar or instrument not in instruments
            for session, instrument in keys
        )
    ):
        raise ValueError(f"Bootstrap {table} identities are invalid")
    return keys

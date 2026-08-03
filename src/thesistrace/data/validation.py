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
    for table, session_field in (
        ("prices", "session"),
        ("trading_states", "session"),
        ("price_limits", "session"),
        ("base_pool", "session"),
    ):
        rows = canonical.get(table)
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or row.get(session_field) not in calendar_set
            for row in rows
        ):
            raise ValueError(f"Bootstrap canonical table is invalid: {table}")

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

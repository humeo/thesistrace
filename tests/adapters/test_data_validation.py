from dataclasses import replace

import pytest

from thesistrace.data import CanonicalSourceBatch
from thesistrace.data.validation import validate_bootstrap_batch


def test_data_rejects_provider_output_that_breaks_canonical_coverage(
    fixture_bootstrap_batch: CanonicalSourceBatch,
) -> None:
    batch = fixture_bootstrap_batch
    invalid = replace(
        batch,
        covered_session_range=(batch.covered_session_range[0], "2099-01-01"),
    )

    with pytest.raises(ValueError, match="calendar coverage"):
        validate_bootstrap_batch(invalid)


@pytest.mark.parametrize(
    "damage",
    [
        "empty_prices",
        "missing_price_field",
        "null_price",
        "missing_limit",
        "null_adjustment_factor",
        "invalid_date",
        "unknown_industry_instrument",
    ],
)
def test_data_rejects_incomplete_required_canonical_tables(
    damage: str,
    fixture_bootstrap_batch: CanonicalSourceBatch,
) -> None:
    batch = fixture_bootstrap_batch
    canonical = dict(batch.canonical)
    if damage == "empty_prices":
        canonical["prices"] = []
    elif damage == "missing_price_field":
        prices = _copied_rows(canonical, "prices")
        prices[0].pop("pre_close_raw")
    elif damage == "null_price":
        _copied_rows(canonical, "prices")[0]["close_adj"] = None
    elif damage == "missing_limit":
        _copied_rows(canonical, "price_limits")[0].pop("upper")
    elif damage == "null_adjustment_factor":
        _copied_rows(canonical, "prices")[0]["adjustment_factor"] = None
    elif damage == "invalid_date":
        _copied_rows(canonical, "instruments")[0]["listed_from"] = "not-a-date"
    else:
        _copied_rows(canonical, "industry_membership")[0]["instrument_id"] = "equity:unknown"

    with pytest.raises(ValueError):
        validate_bootstrap_batch(replace(batch, canonical=canonical))


def _copied_rows(canonical: dict[str, object], table: str) -> list[dict[str, object]]:
    original = canonical[table]
    assert isinstance(original, list)
    rows = list(original)
    first = rows[0]
    assert isinstance(first, dict)
    rows[0] = dict(first)
    canonical[table] = rows
    return rows

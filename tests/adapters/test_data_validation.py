import copy
from dataclasses import replace

import pytest

from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import CollectionPlan
from thesistrace.data.validation import validate_bootstrap_batch


def test_data_rejects_provider_output_that_breaks_canonical_coverage() -> None:
    batch = FixtureDataSource().collect(CollectionPlan.bootstrap())
    invalid = replace(
        batch,
        covered_session_range=(batch.covered_session_range[0], "2099-01-01"),
    )

    with pytest.raises(ValueError, match="calendar or three-year coverage"):
        validate_bootstrap_batch(invalid)


@pytest.mark.parametrize(
    "damage",
    [
        "empty_prices",
        "missing_anchors",
        "missing_price_field",
        "null_price",
        "missing_limit",
        "null_anchor",
        "invalid_date",
        "unknown_industry_instrument",
    ],
)
def test_data_rejects_incomplete_required_canonical_tables(damage: str) -> None:
    batch = FixtureDataSource().collect(CollectionPlan.bootstrap())
    canonical = copy.deepcopy(batch.canonical)
    if damage == "empty_prices":
        canonical["prices"] = []
    elif damage == "missing_anchors":
        canonical.pop("adjustment_anchors")
    elif damage == "missing_price_field":
        prices = canonical["prices"]
        assert isinstance(prices, list)
        prices[0].pop("pre_close_raw")
    elif damage == "null_price":
        canonical["prices"][0]["close_adj"] = None
    elif damage == "missing_limit":
        canonical["price_limits"][0].pop("upper")
    elif damage == "null_anchor":
        canonical["adjustment_anchors"][0]["anchor_factor"] = None
    elif damage == "invalid_date":
        canonical["instruments"][0]["listed_from"] = "not-a-date"
    else:
        canonical["industry_membership"][0]["instrument_id"] = "equity:unknown"

    with pytest.raises(ValueError):
        validate_bootstrap_batch(replace(batch, canonical=canonical))

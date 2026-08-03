from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorableField:
    field_id: str
    evaluation_name: str
    definition: str
    unit: str


AUTHORABLE_FIELDS = (
    AuthorableField(
        "price.open.adjusted",
        "open_adj",
        "fixed-anchor adjusted open",
        "CNY/share",
    ),
    AuthorableField(
        "price.high.adjusted",
        "high_adj",
        "fixed-anchor adjusted high",
        "CNY/share",
    ),
    AuthorableField(
        "price.low.adjusted",
        "low_adj",
        "fixed-anchor adjusted low",
        "CNY/share",
    ),
    AuthorableField(
        "price.close.adjusted",
        "close_adj",
        "fixed-anchor adjusted close",
        "CNY/share",
    ),
    AuthorableField(
        "market.volume.shares",
        "volume_shares",
        "traded share volume",
        "shares",
    ),
    AuthorableField(
        "market.turnover.cny",
        "turnover_amount_cny",
        "turnover amount",
        "CNY",
    ),
)


def authorable_field_bindings() -> dict[str, str]:
    """Return Data-owned stable field IDs bound to Kernel evaluation names."""
    return {field.field_id: field.evaluation_name for field in AUTHORABLE_FIELDS}


def authorable_field_bindings_from_snapshot(value: object) -> dict[str, str]:
    """Resolve frozen Definition bindings, with legacy content as a fallback."""
    if not isinstance(value, list):
        return authorable_field_bindings()
    bindings = {
        str(item["field_id"]): str(item["name"])
        for item in value
        if isinstance(item, Mapping) and "field_id" in item and "name" in item
    }
    return bindings or authorable_field_bindings()

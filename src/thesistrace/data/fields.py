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
        "dynamic front-adjusted open",
        "CNY/share",
    ),
    AuthorableField(
        "price.high.adjusted",
        "high_adj",
        "dynamic front-adjusted high",
        "CNY/share",
    ),
    AuthorableField(
        "price.low.adjusted",
        "low_adj",
        "dynamic front-adjusted low",
        "CNY/share",
    ),
    AuthorableField(
        "price.close.adjusted",
        "close_adj",
        "dynamic front-adjusted close",
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


def authorable_fields() -> tuple[AuthorableField, ...]:
    return AUTHORABLE_FIELDS


def authorable_field_bindings() -> dict[str, str]:
    """Return Data-owned stable field IDs bound to Kernel evaluation names."""
    return {field.field_id: field.evaluation_name for field in AUTHORABLE_FIELDS}

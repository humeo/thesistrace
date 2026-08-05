FIELD_BINDINGS = {
    "price.open.adjusted": "open_adj",
    "price.high.adjusted": "high_adj",
    "price.low.adjusted": "low_adj",
    "price.close.adjusted": "close_adj",
    "market.volume.shares": "volume_shares",
    "market.turnover.cny": "turnover_amount_cny",
}


def field(field_id: str) -> dict[str, object]:
    return {"field_id": field_id}


def literal(value: int | float) -> dict[str, object]:
    return {"literal": value}


def operation(operator_id: str, *operands: dict[str, object]) -> dict[str, object]:
    return {"operator_id": operator_id, "operands": list(operands)}


CLOSE_ADJUSTED = field("price.close.adjusted")
PCT_CHANGE_20 = operation("pct_change", CLOSE_ADJUSTED, literal(20))

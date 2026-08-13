FIELD_BINDINGS = {
    "price.open.adjusted": "open_adj",
    "price.high.adjusted": "high_adj",
    "price.low.adjusted": "low_adj",
    "price.close.adjusted": "close_adj",
    "market.volume.shares": "volume_shares",
    "market.turnover.cny": "turnover_amount_cny",
}


def field(field_id: str) -> dict[str, object]:
    return {"kind": "field", "field_id": field_id}


def literal(value: int | float) -> dict[str, object]:
    return {"kind": "number", "value": value}


def operation(operator_id: str, *operands: dict[str, object]) -> dict[str, object]:
    if operator_id == "negate":
        return {
            "kind": "unary",
            "operator": operator_id,
            "operand": operands[0] if operands else None,
        }
    if operator_id in {"add", "subtract", "multiply", "divide"}:
        return {
            "kind": "binary",
            "operator": operator_id,
            "left": operands[0] if operands else None,
            "right": operands[1] if len(operands) > 1 else None,
        }
    return {"kind": "call", "identifier": operator_id, "arguments": list(operands)}


CLOSE_ADJUSTED = field("price.close.adjusted")
PCT_CHANGE_20 = operation("pct_change", CLOSE_ADJUSTED, literal(20))

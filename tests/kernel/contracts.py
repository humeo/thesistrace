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


def operation(identifier: str, *arguments: dict[str, object]) -> dict[str, object]:
    if identifier == "negate":
        return {
            "kind": "unary",
            "operator": identifier,
            "operand": arguments[0] if arguments else None,
        }
    if identifier in {"add", "subtract", "multiply", "divide"}:
        return {
            "kind": "binary",
            "operator": identifier,
            "left": arguments[0] if arguments else None,
            "right": arguments[1] if len(arguments) > 1 else None,
        }
    return {"kind": "call", "identifier": identifier, "arguments": list(arguments)}


CLOSE_ADJUSTED = field("price.close.adjusted")
PCT_CHANGE_20 = operation("pct_change", CLOSE_ADJUSTED, literal(20))

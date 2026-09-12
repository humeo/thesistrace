from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from thesistrace.research_kernel.industry_catalog import validate_sw2021_l1

CLOSE_FIELD_ID = "price.close.adjusted"
COMMON_INPUTS = MappingProxyType(
    {
        "universe_return": ("equal_weight_return", False),
        "universe_advancing_fraction": ("advancing_fraction", False),
        "industry_return": ("equal_weight_return", True),
        "industry_advancing_fraction": ("advancing_fraction", True),
    }
)
COMMON_INPUT_WORK = 5


def common_reference(identifier: str, arguments: list[object]) -> dict[str, object]:
    if identifier not in COMMON_INPUTS:
        raise ValueError("Unknown common input")
    industry = COMMON_INPUTS[identifier][1]
    if len(arguments) != int(industry):
        raise ValueError("Common input has invalid arity")
    return {
        "kind": "common",
        "identifier": identifier,
        "industry_code": validate_sw2021_l1(arguments[0]) if industry else None,
    }


def validate_common_reference(node: Mapping[str, object]) -> dict[str, object]:
    if set(node) != {"kind", "identifier", "industry_code"} or node["kind"] != "common":
        raise ValueError("Common input node is malformed")
    identifier, code = node["identifier"], node["industry_code"]
    if not isinstance(identifier, str) or identifier not in COMMON_INPUTS:
        raise ValueError("Unknown common input")
    arguments = []
    if COMMON_INPUTS[identifier][1]:
        if not isinstance(code, str) or not code.isascii() or not code.isdigit():
            raise ValueError("Common industry identity is malformed")
        arguments = [int(code)]
    expected = common_reference(identifier, arguments)
    if dict(node) != expected:
        raise ValueError("Common input identity is not canonical")
    return expected


def common_input_references(
    *expressions: Mapping[str, object],
) -> tuple[tuple[str, str | None], ...]:
    """Return distinct, validated common identities from a frozen expression."""
    pending: list[object] = list(expressions)
    references: set[tuple[str, str | None]] = set()
    while pending:
        node = pending.pop()
        if isinstance(node, Mapping):
            if node.get("kind") == "common":
                reference = validate_common_reference(node)
                references.add((reference["identifier"], reference["industry_code"]))
            pending.extend(node.values())
        elif isinstance(node, (list, tuple)):
            pending.extend(node)
    return tuple(sorted(references, key=lambda value: (value[0], value[1] or "")))


def requires_common_industry(*expressions: Mapping[str, object]) -> bool:
    return any(code is not None for _, code in common_input_references(*expressions))

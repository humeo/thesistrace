"""Canonical exact-equality evidence for Research Kernel states."""

from decimal import Decimal

from thesistrace.research_kernel.numeric import (
    canonical_binary64_bytes,
    canonical_decimal,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes


def first_divergence(actual: object, expected: object, path: str = "$") -> str:
    """Return the first canonical path whose type, shape, or value differs."""
    if type(actual) is not type(expected):
        return path
    if isinstance(actual, dict):
        keys = sorted(set(actual) | set(expected))
        for key in keys:
            if key not in actual or key not in expected:
                return f"{path}.{key}"
            divergence = first_divergence(actual[key], expected[key], f"{path}.{key}")
            if divergence:
                return divergence
        return ""
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}.length"
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            divergence = first_divergence(left, right, f"{path}[{index}]")
            if divergence:
                return divergence
        return ""
    return "" if equivalence_bytes(actual) == equivalence_bytes(expected) else path


def equivalence_bytes(value: object) -> bytes:
    """Encode values without weakening binary64 or Decimal equality rules."""

    def normalize(item: object) -> object:
        if isinstance(item, float):
            return {"$binary64": canonical_binary64_bytes(item).hex()}
        if isinstance(item, Decimal):
            return {"$decimal": canonical_decimal(item)}
        if isinstance(item, dict):
            return {
                str(key): normalize(child)
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    return canonical_json_bytes(normalize(value))

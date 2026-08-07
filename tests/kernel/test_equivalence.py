from decimal import Decimal

import pytest

import thesistrace.research_kernel.equivalence as equivalence_module
from thesistrace.research_kernel.equivalence import first_divergence
from thesistrace.research_kernel.numeric import NumericContractError


def test_first_divergence_preserves_canonical_scalar_semantics() -> None:
    assert first_divergence(-0.0, 0.0) == ""
    assert first_divergence(Decimal("1.00"), Decimal("1")) == ""
    assert first_divergence(1.0, 1.5) == "$"
    assert first_divergence(Decimal("1"), Decimal("2")) == "$"
    assert first_divergence(1, True) == "$"
    with pytest.raises(NumericContractError):
        first_divergence(float("nan"), float("nan"))


def test_first_divergence_does_not_serialize_supported_scalar_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_serialization(_value: object) -> bytes:
        raise AssertionError("supported scalar leaves must not use JSON serialization")

    monkeypatch.setattr(equivalence_module, "equivalence_bytes", reject_serialization)

    actual = {"items": [None, True, 7, "value", -0.0, Decimal("1.00")]}
    expected = {"items": [None, True, 7, "value", 0.0, Decimal("1")]}

    assert first_divergence(actual, expected) == ""

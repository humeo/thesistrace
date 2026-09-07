import hashlib
import subprocess
import sys
from decimal import Decimal

import pytest

from thesistrace.research_kernel.numeric import (
    NUMERIC_CONTRACT_ID,
    NumericContractError,
    accounting_divide,
    binary64_checksum,
    canonical_binary64_bytes,
    canonical_decimal,
    canonical_integer,
    require_current_numeric_contract,
)


def test_canonical_integer_and_decimal_encodings_are_minimal() -> None:
    assert NUMERIC_CONTRACT_ID == "thesistrace-numeric-v1"
    assert canonical_integer(0) == "0"
    assert canonical_integer(-120) == "-120"
    assert canonical_decimal(Decimal("0.000")) == "0"
    assert canonical_decimal(Decimal("123.4500")) == "12345e-2"
    assert canonical_decimal(Decimal("1")) == "1e+0"
    assert canonical_decimal(Decimal("-0.0012300")) == "-123e-5"


def test_execution_refuses_a_different_numeric_contract_identity() -> None:
    require_current_numeric_contract(NUMERIC_CONTRACT_ID)

    with pytest.raises(NumericContractError, match="Numeric Execution Contract"):
        require_current_numeric_contract("obsolete-numeric-contract")


def test_accounting_context_is_34_digit_half_even_and_traps_invalid_values() -> None:
    assert accounting_divide(Decimal(1), Decimal(3)) == Decimal(
        "0.3333333333333333333333333333333333"
    )
    with pytest.raises(NumericContractError):
        accounting_divide(Decimal(1), Decimal(0))
    with pytest.raises(NumericContractError):
        canonical_decimal(Decimal("NaN"))
    with pytest.raises(NumericContractError):
        canonical_decimal(Decimal("Infinity"))


def test_binary64_encoding_is_big_endian_and_normalizes_negative_zero() -> None:
    assert canonical_binary64_bytes(-0.0).hex() == "0000000000000000"
    assert canonical_binary64_bytes(1.5).hex() == "3ff8000000000000"
    expected = hashlib.sha256(bytes.fromhex("00000000000000003ff8000000000000")).hexdigest()
    assert binary64_checksum([-0.0, 1.5]) == expected
    with pytest.raises(NumericContractError):
        canonical_binary64_bytes(float("nan"))


def test_binary64_checksum_is_stable_across_processes() -> None:
    script = (
        "from thesistrace.research_kernel.numeric import binary64_checksum;"
        "print(binary64_checksum([-0.0,1.5,-2.25]))"
    )
    first = subprocess.check_output([sys.executable, "-c", script], text=True).strip()
    second = subprocess.check_output([sys.executable, "-c", script], text=True).strip()

    assert first == second == binary64_checksum([-0.0, 1.5, -2.25])

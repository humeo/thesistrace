import hashlib
import math
import struct
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

NUMERIC_CONTRACT_ID = "thesistrace-numeric-v1"

ACCOUNTING_CONTEXT = Context(
    prec=34,
    rounding=ROUND_HALF_EVEN,
    Emin=-6143,
    Emax=6144,
    capitals=1,
    clamp=1,
)
ACCOUNTING_CONTEXT.traps[DivisionByZero] = True
ACCOUNTING_CONTEXT.traps[InvalidOperation] = True
ACCOUNTING_CONTEXT.traps[Overflow] = True


class NumericContractError(ArithmeticError):
    pass


def require_current_numeric_contract(contract_id: object) -> None:
    if contract_id != NUMERIC_CONTRACT_ID:
        raise NumericContractError(
            "Product State Numeric Execution Contract does not match this runtime"
        )


def accounting_divide(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext(ACCOUNTING_CONTEXT):
            result = left / right
    except DecimalException as error:
        raise NumericContractError("invalid accounting division") from error
    return require_finite_decimal(result)


def accounting_add(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext(ACCOUNTING_CONTEXT):
            result = left + right
    except DecimalException as error:
        raise NumericContractError("invalid accounting addition") from error
    return require_finite_decimal(result)


def accounting_subtract(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext(ACCOUNTING_CONTEXT):
            result = left - right
    except DecimalException as error:
        raise NumericContractError("invalid accounting subtraction") from error
    return require_finite_decimal(result)


def accounting_multiply(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext(ACCOUNTING_CONTEXT):
            result = left * right
    except DecimalException as error:
        raise NumericContractError("invalid accounting multiplication") from error
    return require_finite_decimal(result)


def canonical_integer(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NumericContractError("canonical integer requires an exact integer")
    return str(value)


def canonical_decimal(value: Decimal) -> str:
    finite = require_finite_decimal(value)
    if finite.is_zero():
        return "0"
    sign, digits_tuple, exponent = finite.as_tuple()
    digits = list(digits_tuple)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits).lstrip("0")
    if not coefficient:
        return "0"
    prefix = "-" if sign else ""
    exponent_text = f"+{exponent}" if exponent >= 0 else str(exponent)
    return f"{prefix}{coefficient}e{exponent_text}"


def canonical_binary64_bytes(value: float) -> bytes:
    if not math.isfinite(value):
        raise NumericContractError("binary64 value must be finite")
    normalized = 0.0 if value == 0.0 else value
    return struct.pack(">d", normalized)


def binary64_checksum(values: list[float]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(canonical_binary64_bytes(value))
    return digest.hexdigest()


def decimal_to_binary64(value: Decimal) -> float:
    finite = require_finite_decimal(value)
    converted = float(finite)
    if not math.isfinite(converted):
        raise NumericContractError("decimal does not fit binary64")
    return 0.0 if converted == 0.0 else converted


def require_finite_decimal(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise NumericContractError("decimal value must be finite")
    return value

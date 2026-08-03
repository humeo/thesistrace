"""Legacy numeric facade; the calculation contract lives in Research Kernel."""

from thesistrace.research_kernel.numeric import (
    ACCOUNTING_CONTEXT,
    NUMERIC_CONTRACT_ID,
    NumericContractError,
    accounting_add,
    accounting_divide,
    accounting_multiply,
    accounting_subtract,
    binary64_checksum,
    canonical_binary64_bytes,
    canonical_decimal,
    canonical_integer,
    decimal_to_binary64,
    require_finite_decimal,
)

__all__ = [
    "ACCOUNTING_CONTEXT",
    "NUMERIC_CONTRACT_ID",
    "NumericContractError",
    "accounting_add",
    "accounting_divide",
    "accounting_multiply",
    "accounting_subtract",
    "binary64_checksum",
    "canonical_binary64_bytes",
    "canonical_decimal",
    "canonical_integer",
    "decimal_to_binary64",
    "require_finite_decimal",
]

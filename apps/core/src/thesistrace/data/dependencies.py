from __future__ import annotations

from dataclasses import dataclass

from thesistrace.data.fields import FINANCIAL_FIELDS

_FINANCIAL_FIELD_IDS = frozenset(field.field_id for field in FINANCIAL_FIELDS)


@dataclass(frozen=True)
class DataDependencies:
    financial: bool
    industry: bool

    @property
    def required_families(self) -> frozenset[str]:
        return frozenset(
            {
                "market",
                *({"financial"} if self.financial else set()),
                *({"industry"} if self.industry else set()),
            }
        )


def resolve_data_dependencies(
    *,
    field_ids: set[str] | frozenset[str],
    neutralization: str,
) -> DataDependencies:
    if neutralization not in {"none", "industry"}:
        raise ValueError("neutralization is invalid")
    return DataDependencies(
        financial=bool(field_ids & _FINANCIAL_FIELD_IDS),
        industry=neutralization == "industry",
    )


__all__ = ("DataDependencies", "resolve_data_dependencies")

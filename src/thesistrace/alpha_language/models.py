from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ValueType(StrEnum):
    NUMERIC_SERIES = "numeric_series"
    NUMBER = "number"
    WINDOW = "window"


class SourcePosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    offset: int
    line: int
    column: int


class SourceRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: SourcePosition
    end: SourcePosition


class DiagnosticDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "syntax",
        "identifier",
        "callability",
        "arity",
        "value_type",
        "window",
        "literal",
        "resource_limit",
    ]
    expected: str | int | list[str]
    actual: str | int | list[str]


class FormulaDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    severity: Literal["error"] = "error"
    range: SourceRange
    details: DiagnosticDetails | None = None


class FormulaDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    diagnostics: list[FormulaDiagnostic]


class AlphaFieldCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier: Annotated[str, Field(max_length=100)]
    field_id: Annotated[str, Field(max_length=200)]
    value_type: Literal[ValueType.NUMERIC_SERIES] = ValueType.NUMERIC_SERIES
    description: Annotated[str, Field(max_length=384)]
    unit: Annotated[str, Field(max_length=384)]
    family_id: Annotated[str, Field(max_length=384)]
    availability: Annotated[str, Field(max_length=384)]
    report_period_selection: Annotated[str, Field(max_length=384)]
    applicable_company_types: Annotated[
        list[Annotated[str, Field(max_length=64)]], Field(max_length=16)
    ]
    missingness: Annotated[str, Field(max_length=384)]
    example: Annotated[str, Field(max_length=384)]


class BuiltinParameter(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: Annotated[str, Field(max_length=100)]
    value_type: Literal["numeric", "numeric_series", "window"]
    minimum: Annotated[int, Field(ge=-(2**63), lt=2**63)] | None = None
    maximum: Annotated[int, Field(ge=-(2**63), lt=2**63)] | None = None


class BuiltinWorkEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_operations: Annotated[int, Field(ge=0, lt=2**63)]
    per_window_operations: Annotated[int, Field(ge=0, lt=2**63)]


class AlphaBuiltinCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier: Annotated[str, Field(max_length=100)]
    parameters: Annotated[list[BuiltinParameter], Field(max_length=8)]
    result_type: Literal["same_as_first", "numeric_series"]
    description: Annotated[str, Field(max_length=384)]
    examples: Annotated[list[Annotated[str, Field(max_length=384)]], Field(max_length=4)]
    missing_value_behavior: Annotated[str, Field(max_length=384)]
    numeric_behavior: Annotated[str, Field(max_length=384)]
    work_estimate: BuiltinWorkEstimate


class AlphaAuthoringCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    fields: list[AlphaFieldCatalogEntry]
    builtins: list[AlphaBuiltinCatalogEntry]


class CompiledAlpha(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    expression: dict[str, object]
    field_ids_by_identifier: dict[str, str]
    result_type: ValueType
    effective_lookback: int
    node_count: int
    depth: int
    estimated_work: int


class FormulaSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: str

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


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

    identifier: str
    field_id: str
    value_type: Literal[ValueType.NUMERIC_SERIES] = ValueType.NUMERIC_SERIES
    description: str
    unit: str


class BuiltinParameter(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value_type: Literal["numeric", "numeric_series", "window"]
    minimum: int | None = None
    maximum: int | None = None


class BuiltinWorkEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_operations: int
    per_window_operations: int


class AlphaBuiltinCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier: str
    parameters: list[BuiltinParameter]
    result_type: Literal["same_as_first", "numeric_series"]
    description: str
    examples: list[str]
    missing_value_behavior: str
    numeric_behavior: str
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

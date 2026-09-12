from typing import Literal

from pydantic import BaseModel, ConfigDict

from thesistrace.research_batch.models import ResearchBatchKind
from thesistrace.research_run.models import (
    ResearchKind,
    ResearchNeutralization,
    ResearchUniverse,
)


class IntegerRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    minimum: int
    maximum: int


class FormulaAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    maximum_length: int
    maximum_expression_nodes: int
    maximum_expression_depth: int
    maximum_effective_lookback: int
    maximum_estimated_work: int


class InitialCashConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    currency: Literal["CNY"] = "CNY"
    encoding: Literal["decimal_string"] = "decimal_string"
    exclusive_minimum: str = "0"
    maximum: str
    maximum_decimal_places: int = 2
    required: Literal[True] = True


class ExposureAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context: Literal["exposure"] = "exposure"
    mode: Literal["constant_expression"] = "constant_expression"
    default_expression: Literal["1"] = "1"
    minimum: Literal[0] = 0
    maximum: Literal[1] = 1
    data_series_allowed: Literal[False] = False


class ResearchAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_kinds: tuple[ResearchKind, ...]
    universes: tuple[ResearchUniverse, ...]
    neutralizations: tuple[ResearchNeutralization, ...]
    initial_cash_cny: InitialCashConstraints
    holdings_count: IntegerRange
    selection_every_sessions: IntegerRange
    batch_items: IntegerRange
    batch_kinds: tuple[ResearchBatchKind, ...]
    exposure: ExposureAuthoringConstraints
    weighting: tuple[Literal["equal_weight"], ...]
    formula: FormulaAuthoringConstraints

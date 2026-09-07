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


class ResearchAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_kinds: tuple[ResearchKind, ...]
    universes: tuple[ResearchUniverse, ...]
    neutralizations: tuple[ResearchNeutralization, ...]
    holdings_count: IntegerRange
    rebalance_every_sessions: IntegerRange
    batch_items: IntegerRange
    batch_kinds: tuple[ResearchBatchKind, ...]
    formula: FormulaAuthoringConstraints

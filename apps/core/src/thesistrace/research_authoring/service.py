from thesistrace.alpha_language.language import (
    MAX_EFFECTIVE_LOOKBACK,
    MAX_ESTIMATED_WORK,
    MAX_EXPRESSION_DEPTH,
    MAX_EXPRESSION_NODES,
    MAX_FORMULA_LENGTH,
)
from thesistrace.research_authoring.models import (
    FormulaAuthoringConstraints,
    IntegerRange,
    ResearchAuthoringConstraints,
)
from thesistrace.research_batch.models import (
    MAX_RESEARCH_BATCH_ITEMS,
    MIN_RESEARCH_BATCH_ITEMS,
    RESEARCH_BATCH_KINDS,
)
from thesistrace.research_run.models import (
    MAX_HOLDINGS_COUNT,
    MAX_REBALANCE_INTERVAL,
    MIN_HOLDINGS_COUNT,
    MIN_REBALANCE_INTERVAL,
    RESEARCH_KINDS,
    RESEARCH_NEUTRALIZATIONS,
    RESEARCH_UNIVERSES,
)

CURRENT_RESEARCH_AUTHORING_CONSTRAINTS = ResearchAuthoringConstraints(
    research_kinds=RESEARCH_KINDS,
    universes=RESEARCH_UNIVERSES,
    neutralizations=RESEARCH_NEUTRALIZATIONS,
    holdings_count=IntegerRange(
        minimum=MIN_HOLDINGS_COUNT,
        maximum=MAX_HOLDINGS_COUNT,
    ),
    rebalance_every_sessions=IntegerRange(
        minimum=MIN_REBALANCE_INTERVAL,
        maximum=MAX_REBALANCE_INTERVAL,
    ),
    batch_items=IntegerRange(
        minimum=MIN_RESEARCH_BATCH_ITEMS,
        maximum=MAX_RESEARCH_BATCH_ITEMS,
    ),
    batch_kinds=RESEARCH_BATCH_KINDS,
    formula=FormulaAuthoringConstraints(
        maximum_length=MAX_FORMULA_LENGTH,
        maximum_expression_nodes=MAX_EXPRESSION_NODES,
        maximum_expression_depth=MAX_EXPRESSION_DEPTH,
        maximum_effective_lookback=MAX_EFFECTIVE_LOOKBACK,
        maximum_estimated_work=MAX_ESTIMATED_WORK,
    ),
)


class ResearchAuthoringService:
    def constraints(self) -> ResearchAuthoringConstraints:
        return CURRENT_RESEARCH_AUTHORING_CONSTRAINTS

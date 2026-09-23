from thesistrace.alpha_language.language import (
    MAX_EFFECTIVE_LOOKBACK,
    MAX_ESTIMATED_WORK,
    MAX_EXPRESSION_DEPTH,
    MAX_EXPRESSION_NODES,
    MAX_FORMULA_LENGTH,
)
from thesistrace.research_authoring.models import (
    ExposureAuthoringConstraints,
    FormulaAuthoringConstraints,
    FrameworkAuthoringConstraints,
    FrameworkStageConstraints,
    InitialCashConstraints,
    IntegerRange,
    PythonProgramConstraints,
    ResearchAuthoringConstraints,
)
from thesistrace.research_batch.models import (
    MAX_RESEARCH_BATCH_ITEMS,
    MIN_RESEARCH_BATCH_ITEMS,
    RESEARCH_BATCH_KINDS,
)
from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES
from thesistrace.research_kernel.numeric import MAX_INITIAL_CASH_CNY
from thesistrace.research_kernel.strategy_program_assets import PYTHON_VERSION
from thesistrace.research_kernel.strategy_program_guest import AVAILABLE_MODULES
from thesistrace.research_kernel.strategy_program_runtime import (
    BOOTSTRAP_WALL_SECONDS,
    INPUT_BYTES,
    MEMORY_BYTES,
    OUTPUT_BYTES,
    PARAMETER_BYTES,
    SOURCE_BYTES,
    STATE_BYTES,
    WALL_SECONDS,
)
from thesistrace.research_kernel.terminal_state_schema import (
    FRAMEWORK_STATE_BYTES,
    MAX_ACTIVE_SIGNALS,
    MAX_SIGNAL_VALIDITY_SESSIONS,
)
from thesistrace.research_run.models import (
    MAX_HOLDINGS_COUNT,
    MAX_SELECTION_INTERVAL,
    MIN_HOLDINGS_COUNT,
    MIN_SELECTION_INTERVAL,
    RESEARCH_KINDS,
    RESEARCH_NEUTRALIZATIONS,
    RESEARCH_UNIVERSES,
)

CURRENT_RESEARCH_AUTHORING_CONSTRAINTS = ResearchAuthoringConstraints(
    research_kinds=RESEARCH_KINDS,
    strategy_modes=("framework", "direct"),
    python_program=PythonProgramConstraints(
        maximum_source_bytes=SOURCE_BYTES, maximum_parameter_bytes=PARAMETER_BYTES,
        maximum_state_bytes=STATE_BYTES, maximum_input_bytes=INPUT_BYTES,
        maximum_output_bytes=OUTPUT_BYTES, maximum_memory_bytes=MEMORY_BYTES,
        maximum_wall_seconds=WALL_SECONDS,
        maximum_bootstrap_wall_seconds=BOOTSTRAP_WALL_SECONDS, maximum_fields=32,
        history_sessions=IntegerRange(minimum=1, maximum=253),
        python_version=PYTHON_VERSION, modules=AVAILABLE_MODULES,
    ),
    framework=FrameworkAuthoringConstraints(
        stages=tuple(FrameworkStageConstraints(
            stage=stage, builtin_identity=identity, output_contract={
                "universe_selection": (
                    "Return {reason, instrument_ids} to replace selected candidates; "
                    "null retains the prior selection."
                ),
                "alpha": (
                    "Return {reason, signals: [{instrument_id, value, valid_for_sessions}]} "
                    "to update active signals; null retains unexpired signals. "
                    "Validity is in Research Sessions."
                ),
                "portfolio_construction": (
                    "Return a complete Target Decision {reason, allocation, position_limits}, "
                    "or null for NoUpdate. Signals do not execute orders."
                ),
                "risk_management": (
                    "Return null, {mode: limit_positions, reason, position_limits} for local "
                    "caps, or {mode: replace, reason, target} to replace or cancel the proposal."
                ),
            }[stage],
        ) for stage, identity in BUILTIN_FRAMEWORK_MODULES.items()),
        maximum_active_signals=MAX_ACTIVE_SIGNALS,
        signal_validity_sessions=IntegerRange(minimum=1, maximum=MAX_SIGNAL_VALIDITY_SESSIONS),
        maximum_state_bytes=FRAMEWORK_STATE_BYTES,
    ),
    universes=RESEARCH_UNIVERSES,
    neutralizations=RESEARCH_NEUTRALIZATIONS,
    initial_cash_cny=InitialCashConstraints(maximum=str(MAX_INITIAL_CASH_CNY)),
    holdings_count=IntegerRange(
        minimum=MIN_HOLDINGS_COUNT,
        maximum=MAX_HOLDINGS_COUNT,
    ),
    selection_every_sessions=IntegerRange(
        minimum=MIN_SELECTION_INTERVAL,
        maximum=MAX_SELECTION_INTERVAL,
    ),
    batch_items=IntegerRange(
        minimum=MIN_RESEARCH_BATCH_ITEMS,
        maximum=MAX_RESEARCH_BATCH_ITEMS,
    ),
    batch_kinds=RESEARCH_BATCH_KINDS,
    exposure=ExposureAuthoringConstraints(),
    weighting=("equal_weight", "rank_weight", "inverse_volatility"),
    volatility_window=IntegerRange(minimum=1, maximum=252),
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

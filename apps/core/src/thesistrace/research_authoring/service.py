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
from thesistrace.research_authoring.reference import AUTHORING_GUIDE, authoring_reference
from thesistrace.research_authoring.reference_models import (
    AuthoringGuide,
    AuthoringReference,
    AuthoringReferenceQuery,
    AuthoringTopic,
)
from thesistrace.research_batch.models import (
    MAX_RESEARCH_BATCH_ITEMS,
    MIN_RESEARCH_BATCH_ITEMS,
    RESEARCH_BATCH_KINDS,
)
from thesistrace.research_definition import default_simulation_costs
from thesistrace.research_kernel.builtin_framework import (
    BUILTIN_FRAMEWORK_MODULES,
    BuiltinPortfolioModule,
)
from thesistrace.research_kernel.builtin_risk import BuiltinRiskModule
from thesistrace.research_kernel.numeric import MAX_INITIAL_CASH_CNY
from thesistrace.research_kernel.strategy_program_assets import PYTHON_VERSION
from thesistrace.research_kernel.strategy_program_guest import AVAILABLE_MODULES
from thesistrace.research_kernel.strategy_program_runtime import (
    BOOTSTRAP_WALL_SECONDS,
    HISTORY_REQUESTS,
    HISTORY_SESSIONS,
    INPUT_BYTES,
    MEMORY_BYTES,
    OUTPUT_BYTES,
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

DIRECT_SOURCE_TEMPLATE = """import numpy as np
from quantgrove import Targets


def compute(data, state):
    lookback = 60
    close = data.history("price.close.adjusted", lookback=lookback)
    now, before = close[:, lookback:], close[:, :-lookback]
    valid = data.eligible & np.isfinite(now) & np.isfinite(before) & (before > 0)
    scores = np.full(now.shape, -np.inf)
    np.divide(now, before, out=scores, where=valid)
    scores -= 1
    order = np.argsort(-scores, axis=0, kind="stable")[:30]
    selected = np.zeros(scores.shape, dtype=bool)
    np.put_along_axis(selected, order, True, axis=0)
    selected &= valid
    return Targets.equal_weight(
        selected, priority=scores,
        update=(data.session_index % 5 == 0) & selected.any(axis=0)
    )
"""

FRAMEWORK_SOURCE_TEMPLATES = {
    "universe_selection": """from quantgrove import select


def decide(data, account, state):
    return select(data.candidates)
""",
    "alpha": """import numpy as np
from quantgrove import Values, signals


def compute(data, state):
    close = data.history("price.close.adjusted", lookback=60)
    now, before = close[:, 60:], close[:, :-60]
    scores = np.full(now.shape, np.nan)
    valid = data.eligible & np.isfinite(now) & np.isfinite(before) & (before > 0)
    np.divide(now, before, out=scores, where=valid)
    scores -= 1
    return Values({"score": scores})


def decide(data, account, state):
    scores = data.values["score"]
    return signals({stock: float(value) for stock, value in zip(data.instruments, scores)
                    if stock in data.candidates and np.isfinite(value)}, valid_for_sessions=1)
""",
    "portfolio_construction": """from quantgrove import target_weights


def decide(data, account, state):
    scores = {row["instrument_id"]: row["value"] for row in data.framework["signals"]}
    if not scores:
        return None
    best = min(scores, key=lambda stock: (-scores[stock], stock))
    if [row["instrument_id"] for row in account.positions] != [best]:
        return target_weights({best: 1})
    return None
""",
    "risk_management": """from quantgrove import risk_limits


def decide(data, account, state):
    exits = {row["instrument_id"]: 0 for row in account.positions if row["holding_age"] >= 20}
    return risk_limits(exits) if exits else None
""",
}

CURRENT_RESEARCH_AUTHORING_CONSTRAINTS = ResearchAuthoringConstraints(
    research_kinds=RESEARCH_KINDS,
    strategy_modes=("framework", "direct"),
    simulation_cost_defaults=default_simulation_costs(),
    python_program=PythonProgramConstraints(
        source_template=DIRECT_SOURCE_TEMPLATE,
        maximum_source_bytes=SOURCE_BYTES,
        maximum_state_bytes=STATE_BYTES,
        maximum_input_bytes=INPUT_BYTES,
        maximum_output_bytes=OUTPUT_BYTES,
        maximum_memory_bytes=MEMORY_BYTES,
        maximum_wall_seconds=WALL_SECONDS,
        maximum_bootstrap_wall_seconds=BOOTSTRAP_WALL_SECONDS,
        maximum_history_requests=HISTORY_REQUESTS,
        history_sessions=IntegerRange(minimum=1, maximum=HISTORY_SESSIONS),
        python_version=PYTHON_VERSION,
        modules=AVAILABLE_MODULES,
    ),
    framework=FrameworkAuthoringConstraints(
        stages=tuple(
            FrameworkStageConstraints(
                stage=stage,
                builtin_identity=identity,
                source_template=FRAMEWORK_SOURCE_TEMPLATES[stage],
                output_contract={
                    "universe_selection": (
                        "Implement decide. Return select(instruments) to replace "
                        "selected candidates; None retains the prior selection."
                    ),
                    "alpha": (
                        "Implement decide, optionally compute for batch values. Return "
                        "signals({instrument_id: score}, "
                        "valid_for_sessions=2) to update signals; None retains unexpired signals. "
                        "Validity is in Research Sessions."
                    ),
                    "portfolio_construction": (
                        "Implement decide. Return target_weights(weights) "
                        "or None for NoUpdate. Signals do not execute orders."
                    ),
                    "risk_management": (
                        "Implement decide. Return None to pass the current proposal, "
                        "risk_limits(caps) for local caps, or replace(decision) "
                        "to replace the proposal; replace(None) cancels it."
                    ),
                }[stage],
            )
            for stage, identity in BUILTIN_FRAMEWORK_MODULES.items()
        ),
        builtin_risk_schema=BuiltinRiskModule.model_json_schema(),
        builtin_portfolio_schema=BuiltinPortfolioModule.model_json_schema(),
        account_observation=(
            "Direct and Framework programs receive cash_cny, post_open_net_nav_cny, "
            "close_risk_nav_cny and actual positions. Each position includes execution_shares, "
            "adjusted_units, last_adjusted_price (Open), last_close_adjusted_price, "
            "remaining_acquisition_cost_cny, holding_cycle_started_session and holding_age. "
            "Age counts Research Sessions including the first actual buy. Builtin stop loss "
            "compares Close research value to remaining acquisition cost, then caps that "
            "holding at zero for the next Open. Maximum holding sessions requests exit at "
            "the Nth Close. Minimum holding sessions reserves younger positions and slots "
            "during ordinary portfolio changes; risk caps can override retention. "
            "Take-profit tiers require strictly increasing positive profit thresholds "
            "and cumulative "
            "reduction fractions at most one. First trigger freezes the holding baseline; "
            "actual fills advance progress and ordinary additions remain capped until full exit. "
            "no_risk/v1 disables built-in risk."
        ),
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

    def guide(self) -> AuthoringGuide:
        return AUTHORING_GUIDE

    def reference(
        self, topic: AuthoringTopic = "workflow", symbol: str | None = None,
    ) -> AuthoringReference:
        return authoring_reference(AuthoringReferenceQuery(topic=topic, symbol=symbol),
                                   self.constraints()).model_copy(deep=True)

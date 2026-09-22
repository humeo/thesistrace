"""Shared Research definitions, independent of Run and DailyTrack lifecycles."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    model_validator,
)

from thesistrace.alpha_language.language import MAX_FORMULA_LENGTH
from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES
from thesistrace.research_kernel.direct_strategy import PythonProgram
from thesistrace.research_kernel.framework_strategy import FrameworkModules
from thesistrace.research_kernel.kernel_run import DirectStrategyRunInput, StrategyRunInput
from thesistrace.research_kernel.numeric import MAX_INITIAL_CASH_CNY
from thesistrace.research_kernel.portfolio_weighting import PortfolioWeighting, VolatilityWindow
from thesistrace.research_kernel.serialization import canonical_json_bytes

ResearchHypothesis = Annotated[str, Field(strict=True, max_length=1024)]
Formula = Annotated[str, Field(strict=True, max_length=MAX_FORMULA_LENGTH)]
MIN_HOLDINGS_COUNT = 1
MAX_HOLDINGS_COUNT = 100
MIN_SELECTION_INTERVAL = 1
MAX_SELECTION_INTERVAL = 20
def _normalize_initial_cash(value: str) -> str:
    amount = Decimal(value)
    if amount <= 0 or amount > MAX_INITIAL_CASH_CNY:
        raise ValueError("Initial Cash must be positive and at most 1000000000 CNY")
    whole, separator, fraction = format(amount, "f").partition(".")
    fraction = fraction.rstrip("0")
    return whole + ("." + fraction if separator and fraction else "")


InitialCash = Annotated[
    str,
    Field(
        strict=True, pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$",
        description=(
            "CNY decimal string, greater than 0 and at most 1000000000, up to 2 decimal places."
        ),
    ),
    AfterValidator(_normalize_initial_cash),
]


HoldingsCount = Annotated[
    int,
    Field(strict=True, ge=MIN_HOLDINGS_COUNT, le=MAX_HOLDINGS_COUNT),
]
SelectionInterval = Annotated[
    int,
    Field(strict=True, ge=MIN_SELECTION_INTERVAL, le=MAX_SELECTION_INTERVAL),
]
type ResearchKind = Literal["factor_evaluation", "strategy_backtest"]
type ResearchUniverse = Literal["top300", "top1000", "top2000", "top3000"]
type ResearchNeutralization = Literal["none", "industry"]

RESEARCH_KINDS: tuple[ResearchKind, ...] = (
    "factor_evaluation",
    "strategy_backtest",
)
RESEARCH_UNIVERSES: tuple[ResearchUniverse, ...] = (
    "top300",
    "top1000",
    "top2000",
    "top3000",
)
RESEARCH_NEUTRALIZATIONS: tuple[ResearchNeutralization, ...] = (
    "none",
    "industry",
)


def _natural_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise ValueError("natural date must be an ISO YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("natural date must be an ISO YYYY-MM-DD string") from error
    if parsed.isoformat() != value:
        raise ValueError("natural date must be an ISO YYYY-MM-DD string")
    return parsed


NaturalDate = Annotated[date, BeforeValidator(_natural_date)]


class _ResearchSpecBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    hypothesis: ResearchHypothesis | None = None
    start_date: NaturalDate
    end_date: NaturalDate
    universe: ResearchUniverse

    @model_validator(mode="after")
    def validate_research_period(self) -> _ResearchSpecBase:
        if self.start_date > self.end_date:
            raise ValueError("Research end date must not precede start date")
        return self


class FactorEvaluationSpec(_ResearchSpecBase):
    research_kind: Literal["factor_evaluation"]
    formula: Formula
    neutralization: ResearchNeutralization

    @property
    def has_alpha(self) -> bool:
        return True


class FrameworkConfiguration(BaseModel):
    """Active Framework modules and only the settings owned by builtin Portfolio."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    strategy_mode: Literal["framework"] = "framework"
    modules: FrameworkModules = Field(default_factory=lambda: FrameworkModules.model_validate(
        dict(BUILTIN_FRAMEWORK_MODULES),
    ))
    initial_cash_cny: InitialCash
    holdings_count: HoldingsCount | None = None
    selection_every_sessions: SelectionInterval | None = None
    exposure_expression: Formula | None = None
    weighting: PortfolioWeighting | None = None
    volatility_window: VolatilityWindow | None = None

    @model_validator(mode="after")
    def only_active_portfolio_settings(self):
        values = (self.holdings_count, self.selection_every_sessions, self.exposure_expression,
                  self.weighting, self.volatility_window)
        if not self.has_builtin_portfolio:
            if any(value is not None for value in values):
                raise ValueError("Python Portfolio cannot contain builtin Portfolio settings")
        else:
            if self.holdings_count is None or self.selection_every_sessions is None:
                raise ValueError("Builtin Portfolio requires Holdings Count and Selection Interval")
            for name, default in (
                ("exposure_expression", "1"), ("weighting", "equal_weight"),
                ("volatility_window", 20),
            ):
                if getattr(self, name) is None:
                    object.__setattr__(self, name, default)
        return self

    @property
    def has_alpha(self) -> bool:
        return self.modules.alpha == "alpha_formula/v1"

    @property
    def has_builtin_portfolio(self) -> bool:
        return self.modules.portfolio_construction == "periodic_top_n/v1"


class StrategyBacktestSpec(_ResearchSpecBase, FrameworkConfiguration):
    research_kind: Literal["strategy_backtest"]
    formula: Formula | None = None
    neutralization: ResearchNeutralization | None = None

    @model_validator(mode="after")
    def only_active_alpha_settings(self):
        if self.has_alpha:
            if self.formula is None or self.neutralization is None:
                raise ValueError("Builtin Alpha requires a Formula and neutralization")
        elif self.formula is not None or self.neutralization is not None:
            raise ValueError("Python Signal cannot contain builtin Alpha settings")
        return self


class DirectStrategyBacktestSpec(_ResearchSpecBase):
    research_kind: Literal["strategy_backtest"]
    strategy_mode: Literal["direct"]
    initial_cash_cny: InitialCash
    program: PythonProgram

    @property
    def has_alpha(self) -> bool:
        return False


def spec_discriminator(value: object) -> str | None:
    read = value.get if isinstance(value, dict) else lambda name, default=None: getattr(
        value, name, default,
    )
    kind = read("research_kind")
    return (f"{kind}:{read('strategy_mode', 'framework')}"
            if kind == "strategy_backtest" else kind)


type ResearchSpec = Annotated[
    Annotated[FactorEvaluationSpec, Tag("factor_evaluation")]
    | Annotated[StrategyBacktestSpec, Tag("strategy_backtest:framework")]
    | Annotated[DirectStrategyBacktestSpec, Tag("strategy_backtest:direct")],
    Discriminator(spec_discriminator),
]


def kernel_strategy_from_frozen(
    strategy: Mapping[str, object] | None, costs: Mapping[str, str] | None,
) -> StrategyRunInput | DirectStrategyRunInput | None:
    """Translate the accepted definition into the one shared execution contract."""
    if strategy is None:
        return None
    if costs is None:
        raise ValueError("Frozen Strategy requires costs")
    common = {"initial_cash_cny": strategy["initial_cash_cny"], **costs}
    if strategy["kind"] == "direct":
        return DirectStrategyRunInput(
            program_json=canonical_json_bytes(strategy["program"]),
            environment_json=canonical_json_bytes(strategy["environment"]), **common,
        )
    if strategy["kind"] != "framework":
        raise ValueError("Frozen Strategy mode is invalid")
    return StrategyRunInput(
        holdings_count=strategy.get("holdings_count"),
        selection_interval=strategy.get("selection_every_sessions"),
        weighting=strategy.get("weighting"), volatility_window=strategy.get("volatility_window"),
        exposure_expression_json=(canonical_json_bytes(strategy["exposure_expression"])
                                  if "exposure_expression" in strategy else None),
        modules_json=canonical_json_bytes(strategy["modules"]),
        environment_json=(canonical_json_bytes(strategy["environment"])
                          if "environment" in strategy else None), **common,
    )


def authorable_research_input(immutable: Mapping[str, object]) -> dict[str, object]:
    """Project the same frozen configuration for Run reuse and Track provenance."""
    value = {
        "hypothesis": immutable["hypothesis"], "start_date": immutable["requested_start_date"],
        "end_date": immutable["requested_end_date"], "universe": immutable["universe"],
        "research_kind": immutable["research_kind"],
    }
    strategy = immutable.get("strategy")
    if strategy is not None and strategy["kind"] == "direct":
        return {
            **value, "strategy_mode": "direct", "program": deepcopy(strategy["program"]),
            "initial_cash_cny": strategy["initial_cash_cny"],
        }
    if immutable["alpha_expression"] is not None:
        value.update(
            formula=immutable["formula_source"], neutralization=immutable["neutralization"],
        )
    if strategy is not None:
        value.update({
            "strategy_mode": "framework", "initial_cash_cny": strategy["initial_cash_cny"],
            "modules": deepcopy(strategy["modules"]),
        })
        if strategy["modules"]["portfolio_construction"] == "periodic_top_n/v1":
            value.update({
                "holdings_count": strategy["holdings_count"],
                "selection_every_sessions": strategy["selection_every_sessions"],
                "weighting": strategy["weighting"],
                "volatility_window": strategy["volatility_window"],
                "exposure_expression": strategy["exposure_source"],
            })
    return value

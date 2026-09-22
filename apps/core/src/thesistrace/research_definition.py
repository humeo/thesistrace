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
from thesistrace.research_kernel.direct_strategy import PythonProgram
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


class StrategyBacktestSpec(_ResearchSpecBase):
    research_kind: Literal["strategy_backtest"]
    formula: Formula
    neutralization: ResearchNeutralization
    strategy_mode: Literal["framework"] = "framework"
    initial_cash_cny: InitialCash
    holdings_count: HoldingsCount
    selection_every_sessions: SelectionInterval
    exposure_expression: Formula = "1"
    weighting: PortfolioWeighting = "equal_weight"
    volatility_window: VolatilityWindow = 20


class DirectStrategyBacktestSpec(_ResearchSpecBase):
    research_kind: Literal["strategy_backtest"]
    strategy_mode: Literal["direct"]
    initial_cash_cny: InitialCash
    program: PythonProgram


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
        holdings_count=strategy["holdings_count"],
        selection_interval=strategy["selection_every_sessions"],
        weighting=strategy["weighting"], volatility_window=strategy["volatility_window"],
        exposure_expression_json=canonical_json_bytes(strategy["exposure_expression"]), **common,
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
    value.update(formula=immutable["formula_source"], neutralization=immutable["neutralization"])
    if strategy is not None:
        value.update({
            "strategy_mode": "framework", "initial_cash_cny": strategy["initial_cash_cny"],
            "holdings_count": strategy["holdings_count"],
            "selection_every_sessions": strategy["selection_every_sessions"],
            "weighting": strategy["weighting"], "volatility_window": strategy["volatility_window"],
            "exposure_expression": strategy["exposure_source"],
        })
    return value

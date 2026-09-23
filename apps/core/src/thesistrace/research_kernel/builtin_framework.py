"""The form-authored Framework: periodic selection and explicit exposure changes.

All inputs to a decision end at its Close. State is returned explicitly; neither
the schedule nor retained scores belong to the shared Open execution account.
"""

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from thesistrace.research_kernel.common_inputs import CLOSE_FIELD_ID
from thesistrace.research_kernel.exposure import evaluate_exposure_series, require_exposure_value
from thesistrace.research_kernel.portfolio_weighting import (
    PortfolioWeighting,
    inverse_volatility_selection,
    select_portfolio,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.terminal_state_schema import (
    BuiltinPortfolioState,
    PendingTarget,
    TargetAllocation,
    TargetSelection,
)
from thesistrace.research_series import ColumnarResearchSeries

BUILTIN_FRAMEWORK_MODULES = MappingProxyType({
    "universe_selection": "dataset_universe/v1",
    "alpha": "alpha_formula/v1",
    "portfolio_construction": "periodic_top_n/v1",
    "risk_management": "no_risk/v1",
})


class BuiltinPortfolioModule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["periodic_top_n/v1"]
    minimum_holding_sessions: StrictInt = Field(ge=1)


@dataclass(frozen=True)
class BuiltinFrameworkDecision:
    state: BuiltinPortfolioState
    target: PendingTarget | None
    diagnostics: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class BuiltinFramework:
    holdings_count: int
    selection_interval: int
    weighting: PortfolioWeighting
    volatility_window: int
    contract_checksum: str
    minimum_holding_sessions: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.holdings_count <= 100 or not 1 <= self.selection_interval <= 20:
            raise ValueError("invalid Strategy breadth or schedule")

    def decide(
        self,
        *,
        session: str,
        report_index: int,
        alpha_values: Sequence[Mapping[str, object]],
        close_windows: Mapping[str, Sequence[object]],
        exposure_value: object,
        previous: BuiltinPortfolioState | None,
        account: Mapping[str, object] | None = None,
    ) -> BuiltinFrameworkDecision:
        exposure = require_exposure_value(exposure_value, session)
        selection_updated = report_index % self.selection_interval == 0
        selection = previous.selection if previous is not None else None
        diagnostics: tuple[dict[str, object], ...] = ()
        retained = sorted(
            str(position["instrument_id"]) for position in (account["positions"] if account else [])
            if self.minimum_holding_sessions is not None
            and position["holding_age"] < self.minimum_holding_sessions
        )
        if selection_updated:
            eligible = [item for item in alpha_values if item["instrument_id"] not in retained]
            capacity = max(0, self.holdings_count - len(retained))
            exclusions = []
            if self.weighting == "inverse_volatility":
                selected, weights, exclusions = inverse_volatility_selection(
                    eligible, capacity, close_windows, self.volatility_window,
                )
                diagnostics = tuple({
                    "session": session, "reason": "weighting_ineligible",
                    "instrument_id": item["instrument_id"],
                    "eligibility_reason": item["reason"],
                    "volatility_window": self.volatility_window,
                } for item in exclusions)
            else:
                selected, weights = select_portfolio(
                    eligible, capacity, self.weighting,
                )
            selection = TargetSelection(
                signal_session=session,
                selected_instrument_ids=[str(item["instrument_id"]) for item in selected],
                relative_weights=weights,
                eligibility_exclusions=dict(Counter(item["reason"] for item in exclusions)),
                signal_checksum=hashlib.sha256(canonical_json_bytes({
                    "session": session, "values": [dict(item) for item in selected],
                })).hexdigest(),
                contract_checksum=self.contract_checksum,
            )
        if selection is None:
            raise ValueError("Framework decision has no retained Selection")
        target = None
        if selection_updated or previous is None or exposure != previous.exposure:
            reason = "selection" if selection_updated else (
                "reduce" if exposure < previous.exposure else "increase"
            )
            available_weights = {
                item: Fraction(weight) for item, weight in selection.relative_weights.items()
                if item not in retained
            }
            total_weight = sum(available_weights.values(), Fraction())
            allocation_weights = {
                item: str(weight / total_weight) for item, weight in available_weights.items()
            }
            target = PendingTarget(
                decision_session=session,
                execution="next_research_session_open",
                contract_checksum=self.contract_checksum,
                reason=reason,
                allocation=TargetAllocation(
                    mode="rebalance" if selection_updated else reason,
                    instrument_ids=[item for item in selection.selected_instrument_ids
                                    if item not in retained],
                    relative_weights=allocation_weights,
                    exposure=exposure,
                    retained_instrument_ids=retained,
                ),
                position_limits={},
            )
        return BuiltinFrameworkDecision(
            state=BuiltinPortfolioState(selection=selection, exposure=exposure),
            target=target,
            diagnostics=diagnostics,
        )


def alpha_values_by_session(alpha_matrix):
    if alpha_matrix is None:
        return None
    value_store = alpha_matrix.get("value_store")
    return value_store if isinstance(value_store, Mapping) else {
        str(item["session"]): item["values"] for item in alpha_matrix["sessions"]
    }


class PreparedBuiltinPortfolio:
    """The same periodic policy for form-authored and mixed Framework modules."""

    def __init__(self, data, strategy, checksum, *, observe_common=None):
        self._data = data
        self.policy = BuiltinFramework(
            holdings_count=int(strategy["holdings_count"]),
            selection_interval=int(strategy["selection_interval"]),
            weighting=strategy["weighting"], volatility_window=int(strategy["volatility_window"]),
            contract_checksum=checksum,
            minimum_holding_sessions=(
                strategy["modules"]["portfolio_construction"]["minimum_holding_sessions"]
                if isinstance(strategy["modules"]["portfolio_construction"], dict) else None
            ),
        )
        self._exposures = evaluate_exposure_series(
            data, strategy["exposure_expression"], observe_common=observe_common,
        )
        self._closes = None
        if strategy["weighting"] == "inverse_volatility":
            instruments = tuple(sorted(data.instruments))
            if isinstance(data, ColumnarResearchSeries):
                matrix = data.numeric_field_matrices((CLOSE_FIELD_ID,), instruments)[CLOSE_FIELD_ID]
                self._closes = dict(zip(instruments, matrix, strict=True))
            else:
                field = data.fields[CLOSE_FIELD_ID]
                self._closes = {item: [field.get((session, item)) for session in data.sessions]
                                for item in instruments}

    def decide(self, *, session, report_index, alpha_values, previous, account=None):
        state = None
        if previous:
            selection = TargetSelection.model_validate(previous["selection"])
            if selection.contract_checksum != self.policy.contract_checksum:
                raise ValueError("Retained Selection differs from Strategy contract")
            state = BuiltinPortfolioState(
                selection=selection, exposure=require_exposure_value(previous["exposure"], session),
            )
        end = self._data.sessions.index(session) + 1
        close_windows = {} if self._closes is None else {
            str(item["instrument_id"]): self._closes[str(item["instrument_id"])][
                max(0, end - self.policy.volatility_window - 1):end
            ] for item in alpha_values
        }
        return self.policy.decide(
            session=session, report_index=report_index, alpha_values=alpha_values,
            close_windows=close_windows, exposure_value=self._exposures[session], previous=state,
            account=account,
        )

"""The form-authored Framework: periodic selection and explicit exposure changes.

All inputs to a decision end at its Close. State is returned explicitly; neither
the schedule nor retained scores belong to the shared Open execution account.
"""

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from thesistrace.research_kernel.exposure import require_exposure_value
from thesistrace.research_kernel.portfolio_weighting import (
    PortfolioWeighting,
    inverse_volatility_selection,
    select_portfolio,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.terminal_state_schema import (
    PendingTarget,
    TargetAllocation,
    TargetSelection,
)

BUILTIN_FRAMEWORK_MODULES = MappingProxyType({
    "universe_selection": "dataset_universe/v1",
    "alpha": "alpha_formula/v1",
    "portfolio_construction": "periodic_top_n/v1",
    "risk_management": "no_risk/v1",
})


@dataclass(frozen=True)
class BuiltinFrameworkState:
    selection: TargetSelection
    exposure: float


@dataclass(frozen=True)
class BuiltinFrameworkDecision:
    state: BuiltinFrameworkState
    target: PendingTarget | None
    diagnostics: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class BuiltinFramework:
    holdings_count: int
    selection_interval: int
    weighting: PortfolioWeighting
    volatility_window: int
    contract_checksum: str

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
        previous: BuiltinFrameworkState | None,
    ) -> BuiltinFrameworkDecision:
        exposure = require_exposure_value(exposure_value, session)
        selection_updated = report_index % self.selection_interval == 0
        selection = previous.selection if previous is not None else None
        diagnostics: tuple[dict[str, object], ...] = ()
        if selection_updated:
            exclusions = []
            if self.weighting == "inverse_volatility":
                selected, weights, exclusions = inverse_volatility_selection(
                    alpha_values, self.holdings_count, close_windows, self.volatility_window,
                )
                diagnostics = tuple({
                    "session": session, "reason": "weighting_ineligible",
                    "instrument_id": item["instrument_id"],
                    "eligibility_reason": item["reason"],
                    "volatility_window": self.volatility_window,
                } for item in exclusions)
            else:
                selected, weights = select_portfolio(
                    alpha_values, self.holdings_count, self.weighting,
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
            target = PendingTarget(
                decision_session=session,
                execution="next_research_session_open",
                contract_checksum=self.contract_checksum,
                reason=reason,
                allocation=TargetAllocation(
                    mode="rebalance" if selection_updated else reason,
                    instrument_ids=selection.selected_instrument_ids,
                    relative_weights=selection.relative_weights,
                    exposure=exposure,
                ),
                position_limits={},
            )
        return BuiltinFrameworkDecision(
            state=BuiltinFrameworkState(selection=selection, exposure=exposure),
            target=target,
            diagnostics=diagnostics,
        )

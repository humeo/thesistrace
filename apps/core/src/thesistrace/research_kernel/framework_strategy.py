"""Framework decision modules share the same isolated program and account boundary."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from thesistrace.research_kernel.builtin_framework import (
    BUILTIN_FRAMEWORK_MODULES,
    BuiltinPortfolioModule,
    PreparedBuiltinPortfolio,
    alpha_values_by_session,
)
from thesistrace.research_kernel.builtin_risk import BuiltinRiskModule
from thesistrace.research_kernel.direct_strategy import PythonProgram, program_context
from thesistrace.research_kernel.framework_evidence import (
    FormulaEvidence,
    FrameworkEvidence,
    BuiltinRiskEvidence,
    PositionLimitEvidence,
    ReplacementEvidence,
    SignalEvidence,
    UniverseEvidence,
)
from thesistrace.research_kernel.portfolio_drawdown import (
    PortfolioDrawdownState,
    portfolio_drawdown_decision,
)
from thesistrace.research_kernel.strategy_decision import DailyDecision, program_target
from thesistrace.research_kernel.strategy_program_runtime import (
    StrategyProgramError,
    get_strategy_runtime,
)
from thesistrace.research_kernel.take_profit import TakeProfitState, take_profit_decision
from thesistrace.research_kernel.terminal_state_schema import (
    MAX_ACTIVE_SIGNALS,
    MAX_SIGNAL_VALIDITY_SESSIONS,
    FrameworkModulesDecisionState,
    PendingTarget,
)


class PythonModule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["python"]
    program: PythonProgram


class FrameworkModules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    universe_selection: Literal["dataset_universe/v1"] | PythonModule
    alpha: Literal["alpha_formula/v1"] | PythonModule
    portfolio_construction: Literal["periodic_top_n/v1"] | BuiltinPortfolioModule | PythonModule
    risk_management: Literal["no_risk/v1"] | BuiltinRiskModule | PythonModule

    @field_validator("risk_management")
    @classmethod
    def holding_periods_are_consistent(cls, risk, info: ValidationInfo):
        portfolio = info.data.get("portfolio_construction")
        if (isinstance(portfolio, BuiltinPortfolioModule)
                and isinstance(risk, BuiltinRiskModule)
                and risk.maximum_holding_sessions is not None
                and portfolio.minimum_holding_sessions > risk.maximum_holding_sessions):
            raise ValidationError.from_exception_data(cls.__name__, [{
                "type": "value_error", "loc": ("maximum_holding_sessions",),
                "input": risk.maximum_holding_sessions,
                "ctx": {"error": ValueError("Maximum holding sessions must be at least minimum")},
            }])
        return risk

    @property
    def has_builtin_portfolio(self) -> bool:
        return not isinstance(self.portfolio_construction, PythonModule)

    def programs(self) -> dict[str, PythonProgram]:
        return {name: module.program for name in BUILTIN_FRAMEWORK_MODULES
                if isinstance(module := getattr(self, name), PythonModule)}


class ModuleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    reason: Annotated[StrictStr, Field(min_length=1, max_length=512)]


class UniverseUpdate(ModuleOutput):
    instrument_ids: list[StrictStr] = Field(max_length=MAX_ACTIVE_SIGNALS)

    @model_validator(mode="after")
    def unique_instruments(self):
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise ValueError("Universe instruments must be unique")
        return self


class SignalValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    instrument_id: StrictStr
    value: float = Field(allow_inf_nan=False)
    valid_for_sessions: Annotated[StrictInt, Field(ge=1, le=MAX_SIGNAL_VALIDITY_SESSIONS)]


class SignalUpdate(ModuleOutput):
    signals: list[SignalValue] = Field(max_length=MAX_ACTIVE_SIGNALS)

    @model_validator(mode="after")
    def unique_instruments(self):
        ids = [signal.instrument_id for signal in self.signals]
        if len(ids) != len(set(ids)):
            raise ValueError("Signals must have unique instruments")
        return self


class PositionLimitAdjustment(ModuleOutput):
    mode: Literal["limit_positions"]
    position_limits: dict[StrictStr, Annotated[StrictInt, Field(ge=0)]] = Field(min_length=1)


class ReplacementAdjustment(ModuleOutput):
    mode: Literal["replace"]
    target: dict[str, JsonValue] | None


class FrameworkStrategy:
    def __init__(self, data, alpha_matrix, strategy, checksum, *, observe_common=None):
        self._data = data
        self._checksum = checksum
        self._modules = FrameworkModules.model_validate(strategy["modules"])
        self._programs = self._modules.programs()
        self._runtime = get_strategy_runtime()
        if self._programs and strategy["environment"] != self._runtime.identity():
            raise ValueError("Python execution environment differs from its frozen identity")
        if "alpha" not in self._programs and alpha_matrix is None:
            raise ValueError("Builtin Alpha module requires an Alpha matrix")
        self._alpha = alpha_values_by_session(alpha_matrix)
        self._portfolio = (None if "portfolio_construction" in self._programs else
                           PreparedBuiltinPortfolio(
                               data, strategy, checksum, observe_common=observe_common,
                           ))

    def validate_continuation(self, continuation):
        """Validate resumable risk facts before any Open, including empty refreshes."""
        risk = self._modules.risk_management
        if not isinstance(risk, BuiltinRiskModule):
            return
        restored = FrameworkModulesDecisionState.model_validate(continuation["decision_state"])
        if restored.contract_checksum != self._checksum:
            raise ValueError("Framework state differs from the frozen modules")
        risk_state = restored.module_states["risk_management"]
        expected_keys = set()
        if risk.take_profit_tiers:
            expected_keys.add("take_profit_cycles")
        if risk.portfolio_drawdown is not None:
            expected_keys.add("portfolio_drawdown")
        if set(risk_state) != expected_keys:
            raise ValueError("Builtin risk checkpoint differs from configured policies")
        if risk.portfolio_drawdown is not None:
            PortfolioDrawdownState.model_validate(risk_state["portfolio_drawdown"]).validate_boundary(
                session=continuation["daily"][-1]["session"],
                completed_sessions=continuation.get(
                    "report_session_count", len(continuation["daily"]),
                ),
                close_nav=continuation["daily"][-1]["close_risk_nav_cny"],
            )
        if not risk.take_profit_tiers:
            return
        state = TakeProfitState.model_validate({
            "take_profit_cycles": risk_state["take_profit_cycles"],
        })
        positions = {position["instrument_id"]: position for position in continuation["positions"]}
        for item, cycle in state.take_profit_cycles.items():
            position = positions.get(item)
            if (position is None
                    or cycle.highest_triggered_tier >= len(risk.take_profit_tiers)
                    or cycle.holding_cycle_started_session != position[
                        "holding_cycle_started_session"
                    ]
                    or cycle.last_execution_shares != position["execution_shares"]
                    or cycle.last_adjusted_units != position["adjusted_units"]):
                raise ValueError("Take-profit continuation differs from its actual holding cycle")

    def _invoke(self, stage, view, daily, module_states, diagnostics):
        program = self._programs[stage]
        try:
            context = program_context(self._data, program.data_requirements, **daily)
            if stage != "universe_selection":
                selected = set(view["universe"])
                context["candidates"] = [row for row in context["candidates"]
                                         if row["instrument_id"] in selected]
            context["framework"] = view
            result = self._runtime.invoke(
                program.source, context=context, state=module_states[stage],
                parameters=program.parameters,
            )
        except ValueError as error:
            self._fail(stage, daily["session"], error)
        module_states[stage] = result.state
        if result.diagnostics:
            diagnostics.append({
                "session": daily["session"], "reason": "python_diagnostics", "module": stage,
                "program_sha256": program.source_sha256, "text": result.diagnostics,
            })
        return result.output, context

    def _fail(self, stage, session, error):
        raise StrategyProgramError(
            f"{stage}: {error}", source=self._programs[stage].source, session=session,
            line=error.line if isinstance(error, StrategyProgramError) else None,
        ) from error

    def decide(self, *, session, report_index, account, fills, rejections, previous):
        if previous is not None and (
            previous.get("mode") != "framework"
            or previous.get("contract_checksum") != self._checksum
        ):
            raise ValueError("Framework state does not match the frozen modules")
        if previous is not None:
            restored = FrameworkModulesDecisionState.model_validate(previous)
            interval = self._portfolio.policy.selection_interval if self._portfolio else None
            if restored.selection_interval != interval:
                raise ValueError("Framework state differs from its Portfolio module")
            restored.validate_boundary(
                session=self._data.sessions[self._data.sessions.index(session) - 1],
                completed_sessions=report_index,
            )
        module_states = (dict(previous["module_states"]) if previous else
                         {name: {} for name in BUILTIN_FRAMEWORK_MODULES})
        daily = {"session": session, "completed_sessions": report_index + 1,
                 "account": account, "fills": fills, "rejections": rejections}
        diagnostics = []
        view = {
            "universe": list(previous["universe"]) if previous else [],
            "signals": list(previous["signals"]) if previous else [],
            "universe_changed": False, "signals_updated": False,
            "expired_signals": [], "removed_signals": [], "proposal": None,
            "retained_proposal": previous["retained_proposal"] if previous else None,
        }
        universe_evidence = self._universe(view, daily, module_states, diagnostics)
        universe = universe_evidence.instrument_ids
        view["universe_changed"] = universe != view["universe"]
        view["universe"] = universe
        alpha_evidence = self._signals(view, daily, module_states, diagnostics)
        if self._portfolio is None:
            output, context = self._invoke(
                "portfolio_construction", view, daily, module_states, diagnostics,
            )
            try:
                target = program_target(output, context, self._checksum)
            except ValueError as error:
                self._fail("portfolio_construction", session, error)
        else:
            result = self._portfolio.decide(
                session=session, report_index=report_index, alpha_values=view["signals"],
                previous=module_states["portfolio_construction"],
                account=account,
            )
            module_states["portfolio_construction"] = {
                "selection": result.state.selection.model_dump(mode="json"),
                "exposure": result.state.exposure,
            }
            target = result.target
            diagnostics.extend(result.diagnostics)
        proposal = target.model_dump(mode="json") if target else None
        retentions = []
        portfolio_module = self._modules.portfolio_construction
        if (isinstance(portfolio_module, BuiltinPortfolioModule)
                and target is not None and target.allocation is not None):
            retained = set(target.allocation.retained_instrument_ids)
            retentions = [{
                "instrument_id": position["instrument_id"],
                "execution_shares": position["execution_shares"],
                "holding_age": position["holding_age"],
                "minimum_holding_sessions": portfolio_module.minimum_holding_sessions,
            } for position in account["positions"] if position["instrument_id"] in retained]
        view["proposal"] = proposal
        risk_evidence = None
        if "risk_management" in self._programs:
            output, context = self._invoke(
                "risk_management", view, daily, module_states, diagnostics,
            )
            target = self._risk(output, context, target)
            if output is not None:
                risk_evidence = (
                    ReplacementEvidence(mode="replace", reason=output["reason"], target=target)
                    if output["mode"] == "replace" else PositionLimitEvidence.model_validate(output)
                )
        elif isinstance(self._modules.risk_management, BuiltinRiskModule):
            observations = self._modules.risk_management.holding_observations(account)
            risk_limits = {row["instrument_id"]: 0 for row in observations}
            if self._modules.risk_management.take_profit_tiers:
                risk_state, profit_limits, profit_observations = take_profit_decision(
                    tiers=self._modules.risk_management.take_profit_tiers, account=account,
                    previous=({"take_profit_cycles": module_states["risk_management"][
                        "take_profit_cycles"
                    ]} if module_states["risk_management"] else {}), fills=fills,
                )
                module_states["risk_management"].update(risk_state)
                observations.extend(profit_observations)
                for item, maximum in profit_limits.items():
                    risk_limits[item] = min(maximum, risk_limits.get(item, maximum))
            exposure_cap = target.maximum_stock_exposure if target else None
            if self._modules.risk_management.portfolio_drawdown is not None:
                drawdown_state, cap, observation = portfolio_drawdown_decision(
                    policy=self._modules.risk_management.portfolio_drawdown,
                    nav=account["close_risk_nav_cny"], session=session,
                    session_number=report_index + 1, new_proposal=target is not None,
                    previous=module_states["risk_management"].get("portfolio_drawdown"),
                )
                module_states["risk_management"]["portfolio_drawdown"] = drawdown_state
                observations.append(observation)
                if cap is not None:
                    exposure_cap = min(cap, exposure_cap) if exposure_cap is not None else cap
            if observations:
                reason = "+".join(dict.fromkeys(row["reason"] for row in observations))
                limits = dict(target.position_limits) if target else {}
                for item, maximum in risk_limits.items():
                    limits[item] = min(maximum, limits.get(item, maximum))
                if risk_limits or exposure_cap is not None:
                    target = PendingTarget(
                        decision_session=session, execution="next_research_session_open",
                        contract_checksum=self._checksum, reason=reason,
                        allocation=target.allocation if target else None, position_limits=limits,
                        maximum_stock_exposure=exposure_cap,
                    )
                risk_evidence = BuiltinRiskEvidence(
                    reason=reason, position_limits=limits, observations=observations,
                )
        state = {
            "mode": "framework", "contract_checksum": self._checksum,
            "selection_interval": (
                self._portfolio.policy.selection_interval if self._portfolio else None
            ),
            "module_states": module_states, "universe": universe, "signals": view["signals"],
            "retained_proposal": proposal if proposal is not None else (
                previous["retained_proposal"] if previous else None
            ),
        }
        state = FrameworkModulesDecisionState.model_validate(state).model_dump(mode="json")
        return DailyDecision(
            state=state, target=target, diagnostics=tuple(diagnostics),
            framework=FrameworkEvidence(
                modules={name: ("python:" + module.program.source_sha256
                                if isinstance(module, PythonModule) else (
                                    module.kind if isinstance(
                                        module, (BuiltinRiskModule, BuiltinPortfolioModule),
                                    ) else module
                                ))
                         for name in BUILTIN_FRAMEWORK_MODULES
                         for module in (getattr(self._modules, name),)},
                universe=universe_evidence, alpha=alpha_evidence,
                proposal=proposal, risk_adjustment=risk_evidence,
                portfolio_retentions=retentions,
            ),
        )

    def _risk(self, output, context, proposal):
        if output is None:
            return proposal
        try:
            if not isinstance(output, dict):
                raise ValueError("Risk output requires an explicit adjustment mode")
            if output.get("mode") == "replace":
                adjustment = ReplacementAdjustment.model_validate(output)
                return program_target(adjustment.target, context, self._checksum)
            adjustment = PositionLimitAdjustment.model_validate(output)
            # Validate each module's contract before composition; a stricter
            # existing cap must not hide an invalid increase from this module.
            program_target({
                "reason": adjustment.reason, "allocation": None,
                "position_limits": adjustment.position_limits,
            }, context, self._checksum)
            limits = dict(adjustment.position_limits)
            if proposal is not None:
                # These are explicitly compatible caps on the same Close share
                # coordinate. Complete replacement targets are handled above.
                for item, maximum in proposal.position_limits.items():
                    limits[item] = min(maximum, limits.get(item, maximum))
            return program_target({
                "reason": adjustment.reason,
                "allocation": (proposal.allocation.model_dump(mode="json")
                               if proposal is not None and proposal.allocation else None),
                "position_limits": limits,
                "maximum_stock_exposure": (proposal.maximum_stock_exposure
                                           if proposal is not None else None),
            }, context, self._checksum)
        except ValueError as error:
            self._fail("risk_management", context["session"], error)

    def _universe(self, view, daily, module_states, diagnostics):
        available = set(self._data.universe_members[daily["session"]])
        if "universe_selection" not in self._programs:
            return UniverseEvidence(
                instrument_ids=list(self._data.universe_members[daily["session"]]),
                updated=True, reason="dataset_universe",
            )
        output, _ = self._invoke("universe_selection", view, daily, module_states, diagnostics)
        if output is None:
            return UniverseEvidence(
                instrument_ids=[item for item in view["universe"] if item in available],
                updated=False, reason=None,
            )
        try:
            update = UniverseUpdate.model_validate(output)
            if not set(update.instrument_ids) <= available:
                raise ValueError("Universe contains an unavailable current candidate")
            return UniverseEvidence(
                instrument_ids=update.instrument_ids, updated=True, reason=update.reason,
            )
        except ValueError as error:
            self._fail("universe_selection", daily["session"], error)

    def _signals(self, view, daily, module_states, diagnostics):
        session, ordinal = daily["session"], daily["completed_sessions"]
        selected = set(view["universe"])
        expired, removed, active = [], [], []
        for signal in view["signals"]:
            if signal["created_session_number"] + signal["valid_for_sessions"] <= ordinal:
                expired.append(signal["instrument_id"])
            elif signal["instrument_id"] not in selected:
                removed.append(signal["instrument_id"])
            else:
                active.append(signal)
        view.update(signals=active, expired_signals=expired, removed_signals=removed)
        if "alpha" not in self._programs:
            view["signals"] = [{
                "instrument_id": row["instrument_id"], "value": row["value"],
                "created_session": session, "created_session_number": ordinal,
                "valid_for_sessions": 1,
            } for row in self._alpha[session] if row["instrument_id"] in selected]
            view["signals_updated"] = True
            return FormulaEvidence(values=[
                {"instrument_id": row["instrument_id"], "value": row["value"]}
                for row in view["signals"]
            ])
        output, _ = self._invoke("alpha", view, daily, module_states, diagnostics)
        reason = None
        if output is not None:
            try:
                update = SignalUpdate.model_validate(output)
                if any(signal.instrument_id not in selected for signal in update.signals):
                    raise ValueError("Signal instrument must belong to the selected Universe")
                view["signals"] = [{
                    **signal.model_dump(), "created_session": session,
                    "created_session_number": ordinal,
                } for signal in update.signals]
                view["signals_updated"] = True
                reason = update.reason
            except ValueError as error:
                self._fail("alpha", session, error)
        return SignalEvidence(
            signals=view["signals"], updated=view["signals_updated"], reason=reason,
            expired_signals=expired, removed_signals=removed,
        )

"""Prepare one daily decision policy for the shared execution account."""

import hashlib

from thesistrace.research_kernel.builtin_framework import (
    BUILTIN_FRAMEWORK_MODULES,
    PreparedBuiltinPortfolio,
    alpha_values_by_session,
)
from thesistrace.research_kernel.direct_strategy import (
    DirectStrategy,
    PythonProgram,
    program_context,
)
from thesistrace.research_kernel.framework_strategy import FrameworkStrategy
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy_decision import DailyDecision
from thesistrace.research_kernel.strategy_program_runtime import (
    StrategyProgramError,
    get_strategy_runtime,
)


def prepare_daily_strategy(research_data, alpha_matrix, definition, *, observe_common=None):
    checksum = hashlib.sha256(canonical_json_bytes(definition)).hexdigest()
    strategy = definition["strategy"]
    if strategy["mode"] == "framework" and strategy["modules"] == BUILTIN_FRAMEWORK_MODULES:
        return _BuiltinDailyStrategy(
            research_data, alpha_matrix, strategy, checksum, observe_common,
        )
    if strategy["mode"] == "direct":
        return _DirectDailyStrategy(research_data, strategy, checksum)
    if strategy["mode"] == "framework":
        return FrameworkStrategy(
            research_data, alpha_matrix, strategy, checksum, observe_common=observe_common,
        )
    raise ValueError("Unsupported Strategy implementation")


class _BuiltinDailyStrategy:
    def __init__(self, data, alpha_matrix, strategy, checksum, observe_common):
        if alpha_matrix is None:
            raise ValueError("Builtin Framework requires an Alpha matrix")
        self._alpha = alpha_values_by_session(alpha_matrix)
        self._portfolio = PreparedBuiltinPortfolio(
            data, strategy, checksum, observe_common=observe_common,
        )

    def decide(self, *, session, report_index, account, fills, rejections, previous):
        del account, fills, rejections
        if previous is not None:
            if (set(previous) != {"mode", "selection", "exposure", "selection_interval"}
                    or previous["mode"] != "framework"
                    or previous["selection_interval"] != self._portfolio.policy.selection_interval):
                raise ValueError("Framework state does not match the active mode")
        result = self._portfolio.decide(
            session=session, report_index=report_index, alpha_values=self._alpha[session],
            previous=previous,
        )
        return DailyDecision(
            state={"mode": "framework", "selection": result.state.selection.model_dump(mode="json"),
                   "selection_interval": self._portfolio.policy.selection_interval,
                   "exposure": result.state.exposure},
            target=result.target, diagnostics=result.diagnostics,
        )


class _DirectDailyStrategy:
    def __init__(self, data, strategy, checksum):
        self._data = data
        self._program = PythonProgram.model_validate(strategy["program"])
        runtime = get_strategy_runtime()
        if strategy["environment"] != runtime.identity():
            raise ValueError("Python execution environment differs from its frozen identity")
        self._direct = DirectStrategy(self._program, runtime=runtime, contract_checksum=checksum)

    def decide(self, *, session, report_index, account, fills, rejections, previous):
        state = {}
        if previous is not None:
            if (set(previous) != {"mode", "program_sha256", "state"}
                    or previous["mode"] != "direct"
                    or previous["program_sha256"] != self._program.source_sha256):
                raise ValueError("Direct state does not match the frozen program")
            state = previous["state"]
        try:
            context = program_context(
                self._data, self._program.data_requirements, session=session,
                completed_sessions=report_index + 1, account=account,
                fills=fills, rejections=rejections,
            )
        except ValueError as error:
            raise StrategyProgramError(
                str(error), source=self._program.source, session=session,
            ) from error
        result = self._direct.decide(context, previous=state)
        diagnostics = () if not result.diagnostics else ({
            "session": session, "reason": "python_diagnostics",
            "program_sha256": self._program.source_sha256, "text": result.diagnostics,
        },)
        return DailyDecision(
            state={"mode": "direct", "program_sha256": self._program.source_sha256,
                   "state": result.state},
            target=result.target, diagnostics=diagnostics,
        )

"""Prepare one daily decision policy for the shared execution account."""

import hashlib
from fractions import Fraction

import numpy as np

from thesistrace.research_kernel.batch_program import PreparedProgramBlock, current_values
from thesistrace.research_kernel.builtin_framework import (
    BUILTIN_FRAMEWORK_MODULES,
    PreparedBuiltinPortfolio,
    alpha_values_by_session,
)
from thesistrace.research_kernel.direct_strategy import (
    DirectStrategy,
    PythonProgram,
    program_context,
    program_history,
)
from thesistrace.research_kernel.framework_evidence import (
    FormulaEvidence,
    FrameworkEvidence,
    UniverseEvidence,
)
from thesistrace.research_kernel.framework_strategy import FrameworkStrategy
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy_decision import DailyDecision, program_target
from thesistrace.research_kernel.strategy_program_runtime import (
    StrategyProgramError,
    get_strategy_runtime,
)


def prepare_daily_strategy(
    research_data,
    alpha_matrix,
    definition,
    *,
    observe_common=None,
    continuation=None,
    output_sessions=None,
    first_session_index=0,
):
    checksum = hashlib.sha256(canonical_json_bytes(definition)).hexdigest()
    strategy = definition["strategy"]
    if strategy["mode"] == "framework" and strategy["modules"] == BUILTIN_FRAMEWORK_MODULES:
        return _BuiltinDailyStrategy(
            research_data,
            alpha_matrix,
            strategy,
            checksum,
            observe_common,
        )
    if strategy["mode"] == "direct":
        return _DirectDailyStrategy(
            research_data,
            strategy,
            checksum,
            output_sessions or research_data.sessions,
            first_session_index,
            checkpoint_each=output_sessions is None,
        )
    if strategy["mode"] == "framework":
        program = FrameworkStrategy(
            research_data,
            alpha_matrix,
            strategy,
            checksum,
            observe_common=observe_common,
            output_sessions=output_sessions,
            first_session_index=first_session_index,
        )
        if continuation is not None:
            program.validate_continuation(continuation)
        return program
    raise ValueError("Unsupported Strategy implementation")


class _BuiltinDailyStrategy:
    def close(self):
        pass

    def __init__(self, data, alpha_matrix, strategy, checksum, observe_common):
        if alpha_matrix is None:
            raise ValueError("Builtin Framework requires an Alpha matrix")
        self._alpha = alpha_values_by_session(alpha_matrix)
        self._data = data
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
            framework=FrameworkEvidence(
                modules=dict(BUILTIN_FRAMEWORK_MODULES),
                universe=UniverseEvidence(
                    instrument_ids=list(self._data.universe_members[session]),
                    updated=True, reason="dataset_universe",
                ),
                alpha=FormulaEvidence(values=[dict(row) for row in self._alpha[session]]),
                proposal=result.target, risk_adjustment=None,
            ),
        )


class _DirectDailyStrategy:
    def __init__(self, data, strategy, checksum, sessions, first_session_index, *, checkpoint_each):
        self._checkpoint_each = checkpoint_each
        self._data = data
        self._program = PythonProgram.model_validate(strategy["program"])
        runtime = get_strategy_runtime()
        if strategy["environment"] != runtime.identity():
            raise ValueError("Python execution environment differs from its frozen identity")
        self._direct = DirectStrategy(self._program, runtime=runtime, contract_checksum=checksum)
        self._runtime, self._checksum = runtime, checksum
        self._batch = PreparedProgramBlock(
            data, self._program, runtime, sessions, first_session_index
        )
        self._entrypoints = self._batch.entrypoints
        self._sessions = tuple(sessions)
        self._first_index = first_session_index
        self._block = None
        self._execution = (
            runtime.open_session(self._program.source) if self._entrypoints["decide"] else None
        )

    def close(self):
        if self._execution is not None:
            self._execution.close()

    def _compute(self, session, state, account):
        self._block = self._batch.compute(session, state, account)

    def decide(self, *, session, report_index, account, fills, rejections, previous):
        state = {"compute": {}, "decision": {}}
        if previous is not None:
            if (
                set(previous) != {"mode", "program_sha256", "state"}
                or previous["mode"] != "direct"
                or previous["program_sha256"] != self._program.source_sha256
            ):
                raise ValueError("Direct state does not match the frozen program")
            state = previous["state"]
            if type(state) is not dict or set(state) != {"compute", "decision"}:
                raise ValueError("Program state requires separate compute and decision state")
        try:
            context = program_context(
                self._data,
                session=session,
                completed_sessions=report_index + 1,
                account=account,
                fills=fills,
                rejections=rejections,
            )
            context["random_seed"] = self._program.source_sha256
            batch_diagnostics = []
            computed_state = state["compute"]
            target, decision_state, result = None, state["decision"], None
            if self._entrypoints["compute"]:
                if self._block is None or session not in self._block[0]:
                    self._compute(session, state["compute"], account)
                sessions, instruments, output, computed = self._block
                column = sessions.index(session)
                if output["kind"] == "targets":
                    if output["update"][column]:
                        selected = np.flatnonzero(output["weights"][:, column] > 0).tolist()
                        if output["priority"] is not None:
                            selected.sort(key=lambda index: (
                                -output["priority"][index, column].item(), instruments[index],
                            ))
                        weights = {
                            instruments[index]: (
                                Fraction(1, int(output["weights"][:, column].sum()))
                                if output["equal"]
                                else Fraction(str(float(output["weights"][index, column])))
                            )
                            for index in selected
                        }
                        total = sum(weights.values(), Fraction())
                        if total > 1:
                            raise ValueError("Target weights must sum to at most one")
                        target = program_target(
                            {
                                "reason": output["reason"],
                                "position_limits": {},
                                "allocation": {
                                    "mode": "rebalance",
                                    "instrument_ids": list(weights),
                                    "relative_weights": {
                                        stock: str(value / total)
                                        for stock, value in weights.items()
                                    },
                                    "exposure": float(total),
                                },
                            },
                            context,
                            self._checksum,
                        )
                else:
                    # Copy the current column so no ndarray base exposes later dates.
                    current_values(context, output["values"], instruments, column)
                if session == sessions[-1]:
                    computed_state = computed.state
                    batch_diagnostics.extend(
                        {
                            "session": session,
                            "reason": "python_history",
                            "module": "direct",
                            "phase": "compute",
                            "program_sha256": self._program.source_sha256,
                            "request_index": index,
                            **read,
                        }
                        for index, read in enumerate(computed.history_reads, 1)
                    )
                    if computed.diagnostics:
                        batch_diagnostics.append(
                            {
                                "session": session,
                                "reason": "python_diagnostics",
                                "program_sha256": self._program.source_sha256,
                                "text": computed.diagnostics,
                            }
                        )
            if self._entrypoints["decide"]:
                result = self._direct.decide(
                    context,
                    previous=state["decision"],
                    read_history=program_history(self._data, context),
                    execution=self._execution,
                    checkpoint=self._checkpoint_each or session == self._sessions[-1],
                )
                target, decision_state = result.target, result.state
        except StrategyProgramError:
            raise
        except ValueError as error:
            raise StrategyProgramError(
                str(error),
                source=self._program.source,
                session=session,
            ) from error
        diagnostics = (
            ()
            if result is None or not result.diagnostics
            else (
                {
                    "session": session,
                    "reason": "python_diagnostics",
                    "program_sha256": self._program.source_sha256,
                    "text": result.diagnostics,
                },
            )
        )
        diagnostics += tuple(
            {
                "session": session,
                "reason": "python_history",
                "module": "direct",
                "phase": "decide",
                "program_sha256": self._program.source_sha256,
                "request_index": index,
                **read,
            }
            for index, read in enumerate(result.history_reads if result else (), 1)
        )
        return DailyDecision(
            state={
                "mode": "direct",
                "program_sha256": self._program.source_sha256,
                "state": {"compute": computed_state, "decision": decision_state},
            },
            target=target,
            diagnostics=diagnostics + tuple(batch_diagnostics),
        )

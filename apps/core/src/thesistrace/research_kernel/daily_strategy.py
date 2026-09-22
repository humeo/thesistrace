"""Prepare one daily decision policy for the shared execution account."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from thesistrace.research_kernel.builtin_framework import (
    BUILTIN_FRAMEWORK_MODULES,
    BuiltinFramework,
    BuiltinFrameworkState,
)
from thesistrace.research_kernel.common_inputs import CLOSE_FIELD_ID
from thesistrace.research_kernel.direct_strategy import (
    DirectStrategy,
    PythonProgram,
    program_context,
)
from thesistrace.research_kernel.exposure import evaluate_exposure_series, require_exposure_value
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy_program_runtime import (
    StrategyProgramError,
    get_strategy_runtime,
)
from thesistrace.research_kernel.terminal_state_schema import PendingTarget, TargetSelection
from thesistrace.research_series import ColumnarResearchSeries


@dataclass(frozen=True)
class DailyDecision:
    state: dict[str, object]
    target: PendingTarget | None
    diagnostics: tuple[dict[str, object], ...]


def prepare_daily_strategy(research_data, alpha_matrix, definition, *, observe_common=None):
    checksum = hashlib.sha256(canonical_json_bytes(definition)).hexdigest()
    strategy = definition["strategy"]
    if strategy["mode"] == "framework" and strategy["modules"] == BUILTIN_FRAMEWORK_MODULES:
        return _BuiltinDailyStrategy(
            research_data, alpha_matrix, strategy, checksum, observe_common,
        )
    if strategy["mode"] == "direct":
        return _DirectDailyStrategy(research_data, strategy, checksum)
    raise ValueError("Unsupported Strategy implementation")


class _BuiltinDailyStrategy:
    def __init__(self, data, alpha_matrix, strategy, checksum, observe_common):
        if alpha_matrix is None:
            raise ValueError("Builtin Framework requires an Alpha matrix")
        self._data = data
        value_store = alpha_matrix.get("value_store")
        self._alpha = (value_store if isinstance(value_store, Mapping) else {
            str(item["session"]): item["values"] for item in alpha_matrix["sessions"]
        })
        self._framework = BuiltinFramework(
            holdings_count=int(strategy["holdings_count"]),
            selection_interval=int(strategy["selection_interval"]),
            weighting=strategy["weighting"], volatility_window=int(strategy["volatility_window"]),
            contract_checksum=checksum,
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

    def decide(self, *, session, report_index, account, fills, rejections, previous):
        del account, fills, rejections
        state = None
        if previous is not None:
            if (set(previous) != {"mode", "selection", "exposure", "selection_interval"}
                    or previous["mode"] != "framework"
                    or previous["selection_interval"] != self._framework.selection_interval):
                raise ValueError("Framework state does not match the active mode")
            selection = TargetSelection.model_validate(previous["selection"])
            if selection.contract_checksum != self._framework.contract_checksum:
                raise ValueError("Retained Selection differs from Strategy contract")
            state = BuiltinFrameworkState(
                selection, require_exposure_value(previous["exposure"], session),
            )
        end = self._data.sessions.index(session) + 1
        close_windows = {} if self._closes is None else {
            str(item["instrument_id"]): self._closes[str(item["instrument_id"])][
                max(0, end - self._framework.volatility_window - 1):end
            ] for item in self._alpha[session]
        }
        result = self._framework.decide(
            session=session, report_index=report_index, alpha_values=self._alpha[session],
            close_windows=close_windows, exposure_value=self._exposures[session], previous=state,
        )
        return DailyDecision(
            state={"mode": "framework", "selection": result.state.selection.model_dump(mode="json"),
                   "selection_interval": self._framework.selection_interval,
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

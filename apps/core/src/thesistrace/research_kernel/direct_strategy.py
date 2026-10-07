"""Close-scoped Python decisions with no authority over shared execution."""

import hashlib
import math
from dataclasses import dataclass
from typing import Annotated

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    model_validator,
)

from thesistrace.research_history import HistoryWindow
from thesistrace.research_kernel.strategy_decision import program_target
from thesistrace.research_kernel.strategy_program_runtime import (
    HISTORY_CELLS,
    HISTORY_SESSIONS,
    HISTORY_TOTAL_CELLS,
    SOURCE_BYTES,
    PythonStrategyRuntime,
    StrategyProgramError,
)
from thesistrace.research_kernel.terminal_state_schema import PendingTarget
from thesistrace.research_series import (
    AlignedResearchData,
    ColumnarResearchSeries,
    slice_research_sessions,
)


class PythonProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: Annotated[StrictStr, Field(min_length=1, max_length=SOURCE_BYTES)]

    @model_validator(mode="after")
    def source_is_bounded(self):
        if len(self.source.encode()) > SOURCE_BYTES:
            raise ValueError("Program source exceeds 65536 UTF-8 bytes")
        return self

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source.encode()).hexdigest()


def program_context(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    *,
    session: str,
    completed_sessions: int,
    account: dict[str, object],
    fills: list[dict[str, object]],
    rejections: list[dict[str, object]],
) -> dict[str, object]:
    """Materialize current candidates and actual holdings, without history.

    In particular, no slice boundary, future calendar, Dataset identity/path or
    InstrumentProfile.listed_to value crosses the program boundary.
    """
    candidates = research_data.universe_members[session]
    instrument_ids = tuple(sorted(set(candidates) | {
        row["instrument_id"] for row in account["positions"]
    }))
    if not set(instrument_ids) <= research_data.instruments.keys():
        raise ValueError("Program context contains an unknown current instrument")
    return {
        "session": session,
        "completed_sessions": completed_sessions,
        "candidates": [{
            "instrument_id": item,
            "board": research_data.instruments[item].board,
            "industry": research_data.industries.get((session, item)),
        } for item in candidates],
        "account": account,
        "fills": [item for item in fills if item["session"] == session],
        "rejections": [item for item in rejections if item["session"] == session],
    }


def program_history(research_data, context):
    """Bind data authority outside guest-controlled memory for one decision."""
    session = context["session"]
    visible = frozenset(row["instrument_id"] for row in context["candidates"]) | frozenset(
        row["instrument_id"] for row in context["account"]["positions"]
    )
    cells_read = 0

    def read(request):
        nonlocal cells_read
        if type(request) is not dict or set(request) != {"field_id", "days", "instruments"}:
            raise ValueError("History requires field_id, days and instruments")
        field_id, days, instruments = (
            request["field_id"], request["days"], request["instruments"],
        )
        if type(field_id) is not str or not 1 <= len(field_id) <= 200:
            raise ValueError("History field ID is invalid")
        if type(days) is not int or not 1 <= days <= HISTORY_SESSIONS:
            raise ValueError("History days must be an integer between 1 and 253")
        if instruments is None:
            instruments = sorted(visible)
        if (type(instruments) is not list or any(type(item) is not str for item in instruments)
                or len(instruments) != len(set(instruments)) or not set(instruments) <= visible):
            raise ValueError("History instruments must be unique visible candidates or holdings")
        cells_read += len(instruments) * days
        if len(instruments) * days > HISTORY_CELLS or cells_read > HISTORY_TOTAL_CELLS:
            raise ValueError("History cell budget exceeded")
        loader = getattr(research_data, "strategy_history_loader", None)
        if loader is not None:
            result = loader(session, field_id, days, tuple(instruments))
        else:
            end = research_data.sessions.index(session) + 1
            sessions = research_data.sessions[max(0, end - days):end]
            if isinstance(research_data, ColumnarResearchSeries):
                scoped = slice_research_sessions(research_data, sessions)
                matrix = scoped.numeric_field_matrices((field_id,), tuple(instruments))[field_id]
                matrix = np.array(matrix, dtype="<f8", copy=True)
                matrix[matrix == 0] = 0.0
            else:
                if field_id not in research_data.fields:
                    raise ValueError("History field unavailable in the pinned data")
                matrix = np.asarray([
                    [_numeric(research_data.fields[field_id].get((date, item)))
                     for date in sessions]
                    for item in instruments
                ], dtype="<f8").reshape(len(instruments), len(sessions))
            result = HistoryWindow(tuple(sessions), tuple(instruments), matrix)
        return result

    return read


def _numeric(value) -> float | None:
    if value is None:
        return None
    result = float(value)
    if math.isnan(result):
        return None
    if not math.isfinite(result):
        raise ValueError("Program history contains a non-finite field value")
    return 0.0 if result == 0 else result


@dataclass(frozen=True)
class DirectDecision:
    state: dict[str, object]
    target: PendingTarget | None
    diagnostics: str
    history_reads: tuple[dict[str, object], ...] = ()


class DirectStrategy:
    def __init__(
        self, program: PythonProgram, *, runtime: PythonStrategyRuntime, contract_checksum: str,
    ) -> None:
        self._program = program.model_copy(deep=True)
        self._runtime = runtime
        self._contract_checksum = contract_checksum

    def decide(self, context: dict[str, object], *, previous: dict[str, object],
               read_history=None) -> DirectDecision:
        result = self._runtime.invoke(
            self._program.source, context=context, state=previous,
            read_history=read_history,
        )
        try:
            target = program_target(result.output, context, self._contract_checksum)
        except ValueError as error:
            raise StrategyProgramError(
                str(error), source=self._program.source, session=context["session"],
            ) from error
        return DirectDecision(state=result.state, target=target, diagnostics=result.diagnostics,
                              history_reads=result.history_reads)

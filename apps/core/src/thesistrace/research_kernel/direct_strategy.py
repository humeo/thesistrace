"""Close-scoped Python decisions with no authority over shared execution."""

import hashlib
import math
from dataclasses import dataclass
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    model_validator,
)

from thesistrace.research_kernel.strategy_decision import program_target
from thesistrace.research_kernel.strategy_program_runtime import (
    INPUT_BYTES,
    PARAMETER_BYTES,
    SOURCE_BYTES,
    PythonStrategyRuntime,
    StrategyProgramError,
    encode_program_json,
)
from thesistrace.research_kernel.terminal_state_schema import PendingTarget
from thesistrace.research_series import (
    AlignedResearchData,
    ColumnarResearchSeries,
    slice_research_sessions,
)


class ProgramDataRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field_ids: list[Annotated[StrictStr, Field(min_length=1, max_length=200)]] = Field(
        max_length=32,
    )
    history_sessions: Annotated[StrictInt, Field(ge=1, le=253)]

    @model_validator(mode="after")
    def field_ids_are_unique(self):
        if len(self.field_ids) != len(set(self.field_ids)):
            raise ValueError("Program data fields must be unique")
        return self


class PythonProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: Annotated[StrictStr, Field(min_length=1, max_length=SOURCE_BYTES)]
    parameters: dict[str, JsonValue]
    data_requirements: ProgramDataRequirements

    @model_validator(mode="after")
    def source_and_parameters_are_bounded(self):
        if len(self.source.encode()) > SOURCE_BYTES:
            raise ValueError("Program source exceeds 65536 UTF-8 bytes")
        encode_program_json(self.parameters, PARAMETER_BYTES, "parameters")
        return self

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source.encode()).hexdigest()


def program_context(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    requirements: ProgramDataRequirements,
    *,
    session: str,
    completed_sessions: int,
    account: dict[str, object],
    fills: list[dict[str, object]],
    rejections: list[dict[str, object]],
) -> dict[str, object]:
    """Materialize only declared history, current candidates and actual holdings.

    In particular, no slice boundary, future calendar, Dataset identity/path or
    InstrumentProfile.listed_to value crosses the program boundary.
    """
    end = research_data.sessions.index(session) + 1
    if end < requirements.history_sessions:
        raise ValueError("Insufficient declared Python program history")
    sessions = research_data.sessions[end - requirements.history_sessions:end]
    candidates = research_data.universe_members[session]
    instrument_ids = tuple(sorted(set(candidates) | {
        row["instrument_id"] for row in account["positions"]
    }))
    if not set(instrument_ids) <= research_data.instruments.keys():
        raise ValueError("Program context contains an unknown current instrument")
    field_ids = tuple(requirements.field_ids)
    # Every numeric/null JSON cell needs at least a value and separator. Reject
    # impossible inputs before allocating host-side nested lists; the runtime
    # also checks the exact encoded size, including account and explicit state.
    if len(sessions) * len(instrument_ids) * len(field_ids) > INPUT_BYTES // 2:
        raise ValueError("Program history exceeds the input size limit")
    if isinstance(research_data, ColumnarResearchSeries):
        scoped = slice_research_sessions(research_data, sessions)
        matrices = scoped.numeric_field_matrices(field_ids, instrument_ids)
        fields = {
            field_id: [[_numeric(value) for value in row] for row in matrices[field_id]]
            for field_id in field_ids
        }
    else:
        fields = {
            field_id: [[_numeric(research_data.fields[field_id].get((date, item)))
                        for date in sessions] for item in instrument_ids]
            for field_id in field_ids
        }
    return {
        "session": session,
        "completed_sessions": completed_sessions,
        "history": {
            "sessions": list(sessions), "instruments": list(instrument_ids), "fields": fields,
        },
        "candidates": [{
            "instrument_id": item,
            "board": research_data.instruments[item].board,
            "industry": research_data.industries.get((session, item)),
        } for item in candidates],
        "account": account,
        "fills": [item for item in fills if item["session"] == session],
        "rejections": [item for item in rejections if item["session"] == session],
    }


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


class DirectStrategy:
    def __init__(
        self, program: PythonProgram, *, runtime: PythonStrategyRuntime, contract_checksum: str,
    ) -> None:
        self._program = program.model_copy(deep=True)
        self._runtime = runtime
        self._contract_checksum = contract_checksum

    def decide(self, context: dict[str, object], *, previous: dict[str, object]) -> DirectDecision:
        result = self._runtime.invoke(
            self._program.source, context=context, state=previous,
            parameters=self._program.parameters,
        )
        try:
            target = program_target(result.output, context, self._contract_checksum)
        except ValueError as error:
            raise StrategyProgramError(
                str(error), source=self._program.source, session=context["session"],
            ) from error
        return DirectDecision(state=result.state, target=target, diagnostics=result.diagnostics)

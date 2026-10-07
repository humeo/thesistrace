"""Fresh, bounded Python/WASI invocations with no authority over the host account."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from thesistrace.research_history import encode_history
from thesistrace.research_kernel.python_execution import (
    BOOTSTRAP_WALL_SECONDS,
    FUEL,
    INPUT_BYTES,
    MEMORY_BYTES,
    OUTPUT_BYTES,
    WALL_SECONDS,
    PreparedPythonEnvironment,
)
from thesistrace.research_kernel.python_execution import (
    REQUESTS as HISTORY_REQUESTS,
)
from thesistrace.research_kernel.python_execution import (
    RESPONSE_BYTES as HISTORY_RESPONSE_BYTES,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy_program_assets import (
    ARCHIVE_SHA256,
    NUMPY_VERSION,
    PYTHON_VERSION,
    WASMTIME_VERSION,
)
from thesistrace.research_kernel.strategy_program_guest import (
    AVAILABLE_MODULES,
)

SOURCE_BYTES = 65_536
STATE_BYTES = 256 * 1024
HISTORY_CELLS = 262_144
HISTORY_TOTAL_CELLS = 1_048_576
HISTORY_SESSIONS = 253
DIAGNOSTIC_BYTES = 65_536
MAX_JSON_DEPTH = 32


class StrategyProgramFailure(ValueError):
    """A bounded, owner-visible program diagnostic, including across a child wire."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:512])


class StrategyProgramError(StrategyProgramFailure):
    def __init__(
        self, message: str, *, source: str, session: str | None, line: int | None = None,
        error_type: str = "ProgramError",
    ) -> None:
        self.program_sha256 = hashlib.sha256(
            source.encode(errors="backslashreplace") if isinstance(source, str) else b""
        ).hexdigest()
        self.session = session
        self.line = line
        self.error_type = error_type
        location = f"program {self.program_sha256[:12]}"
        if session is not None:
            location += f" on {session}"
        if line is not None:
            location += f", line {line}"
        super().__init__(f"{location}: {error_type}: {message}")


@dataclass(frozen=True)
class ProgramResult:
    output: object
    state: dict[str, object]
    diagnostics: str
    history_reads: tuple[dict[str, object], ...] = ()


def _check_json(value: object, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("Program JSON nesting exceeds 32 levels")
    if type(value) is str:
        value.encode("utf-8")
        return
    if type(value) in {bool, type(None)}:
        return
    if type(value) is int:
        if abs(value) > 2**53 - 1:
            raise ValueError("Program JSON integers must fit the exact interoperable range")
        return
    if type(value) is float and math.isfinite(value):
        if value.is_integer() and abs(value) > 2**53 - 1:
            raise ValueError("Program JSON integers must fit the exact interoperable range")
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for key, item in value.items():
            key.encode("utf-8")
            _check_json(item, depth + 1)
        return
    if type(value) is list:
        for item in value:
            _check_json(item, depth + 1)
        return
    raise ValueError("Program values must be finite JSON values with string object keys")


def encode_program_json(value: object, limit: int, name: str) -> bytes:
    _check_json(value)
    encoded = canonical_json_bytes(value)
    if len(encoded) > limit:
        raise ValueError(f"Program {name} exceeds {limit} bytes")
    return encoded


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Program output contains duplicate keys")
        result[key] = value
    return result


class PythonStrategyRuntime:
    """Adapt the strategy SDK to the prepared, protocol-neutral Python executor."""

    def __init__(self) -> None:
        bootstrap = Path(__file__).with_name("strategy_program_guest.py").read_text()
        sdk = Path(__file__).with_name("strategy_sdk.py").read_text()
        history_wire = Path(__file__).parent.parent.joinpath("research_history.py").read_text()
        self._execution = PreparedPythonEnvironment(
            bootstrap,
            module_sources={"_history_wire": history_wire, "quantgrove": sdk},
        )

    def identity(self) -> dict[str, object]:
        return {
            "contract": "python-strategy/v4", "python": PYTHON_VERSION, "numpy": NUMPY_VERSION,
            "wasmtime": WASMTIME_VERSION, "archive_sha256": ARCHIVE_SHA256,
            **self._execution.identity(),
            "modules": list(AVAILABLE_MODULES),
            "source_bytes": SOURCE_BYTES,
            "input_bytes": INPUT_BYTES, "output_bytes": OUTPUT_BYTES,
            "state_bytes": STATE_BYTES,
            "history_requests": HISTORY_REQUESTS,
            "history_response_bytes": HISTORY_RESPONSE_BYTES,
            "history_cells": HISTORY_CELLS, "history_total_cells": HISTORY_TOTAL_CELLS,
            "history_sessions": HISTORY_SESSIONS,
            "diagnostic_bytes": DIAGNOSTIC_BYTES,
            "memory_bytes": MEMORY_BYTES, "fuel": FUEL, "wall_seconds": WALL_SECONDS,
            "bootstrap_wall_seconds": BOOTSTRAP_WALL_SECONDS,
            "json_depth": MAX_JSON_DEPTH,
            "clock": "decision_session_15:00_UTC+08:00",
            "random": "sha256_of_canonical_invocation/v1",
            "numpy_random": "sha256_with_numpy_domain/v1",
        }

    def validate(self, source: str, *, entrypoint="Strategy") -> None:
        self._invoke(source, context={}, state={}, operation="validate",
                     entrypoint=entrypoint, read_history=None)

    def invoke(
        self, source: str, *, context: dict[str, object], state: dict[str, object],
        read_history=None, entrypoint="Strategy",
    ) -> ProgramResult:
        return self._invoke(
            source, context=context, state=state, operation="invoke",
            entrypoint=entrypoint, read_history=read_history,
        )

    def _invoke(
        self, source, *, context, state, operation, entrypoint, read_history,
    ) -> ProgramResult:
        session = context.get("session")
        try:
            if not isinstance(source, str) or not source or len(source.encode()) > SOURCE_BYTES:
                raise ValueError("Program source must contain at most 65536 UTF-8 bytes")
            if entrypoint not in {"Strategy", "UniverseSelection", "Alpha",
                                  "PortfolioConstruction", "RiskManagement"}:
                raise ValueError("Unknown strategy entrypoint")
            if type(state) is not dict:
                raise ValueError("Program state must be an explicit JSON object")
            encode_program_json(state, STATE_BYTES, "state")
            payload = encode_program_json({
                "source": source, "context": context, "state": state,
                "entrypoint": entrypoint, "operation": operation,
            }, INPUT_BYTES, "input")
            history_reads = []

            def observed_read(raw):
                try:
                    request = json.loads(raw, object_pairs_hook=_unique_object)
                    _check_json(request)
                    result = read_history(request)
                    encoded = encode_history(result)
                except (ValueError, KeyError, TypeError, UnicodeError) as error:
                    return encode_program_json({"error": str(error)[:4096]}, 8192, "error")
                dates = result.sessions
                history_reads.append({
                    "field_id": request["field_id"], "requested_sessions": request["days"],
                    "returned_sessions": len(dates), "instrument_count": len(result.instruments),
                    "first_session": dates[0] if dates else None,
                    "last_session": dates[-1] if dates else None,
                    "response_bytes": len(encoded),
                })
                return encoded

            clock_time_ns = (
                int(datetime.fromisoformat(session).replace(hour=7, tzinfo=UTC).timestamp())
                * 1_000_000_000 if session is not None else 0
            )
            raw = self._execution.invoke(
                payload, clock_time_ns=clock_time_ns,
                read_request=observed_read if read_history else None,
            )
            result = json.loads(raw, object_pairs_hook=_unique_object)
            _check_json(result)
            if type(result) is not dict or type(result.get("ok")) is not bool:
                raise ValueError("Program returned an invalid response")
            if not result["ok"]:
                error = result.get("error")
                if (set(result) != {"ok", "error"} or type(error) is not dict
                        or set(error) != {"type", "message", "line"}
                        or type(error["type"]) is not str or len(error["type"]) > 256
                        or type(error["message"]) is not str or len(error["message"]) > 4096
                        or (error["line"] is not None and (
                            type(error["line"]) is not int or error["line"] < 1
                        ))):
                    raise ValueError("Program returned an invalid error response")
                raise StrategyProgramError(
                    error["message"], source=source, session=session,
                    line=error["line"], error_type=error["type"],
                )
            if set(result) != {"ok", "result", "diagnostics"}:
                raise ValueError("Program returned an invalid response")
            diagnostics = result["diagnostics"]
            if (type(diagnostics) is not str
                    or len(diagnostics.encode()) > DIAGNOSTIC_BYTES):
                raise ValueError("Program diagnostics must be a string of at most 65536 bytes")
            returned = result["result"]
            if type(returned) is not dict or set(returned) != {"output", "state"}:
                raise ValueError("Program must return exactly output and state")
            if type(returned["state"]) is not dict:
                raise ValueError("Program must return an explicit JSON object state")
            encode_program_json(returned["state"], STATE_BYTES, "state")
            return ProgramResult(returned["output"], returned["state"], diagnostics,
                                 tuple(history_reads))
        except StrategyProgramError:
            raise
        except (ValueError, KeyError, TypeError, RecursionError, UnicodeError) as error:
            raise StrategyProgramError(str(error), source=source, session=session,
                                       error_type=type(error).__name__) from error



@lru_cache(maxsize=1)
def get_strategy_runtime() -> PythonStrategyRuntime:
    """Share only the verified library and compiled Wasm, never a Python guest."""
    return PythonStrategyRuntime()

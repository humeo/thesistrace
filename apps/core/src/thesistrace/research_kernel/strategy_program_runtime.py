"""Fresh, bounded Python/WASI invocations with no authority over the host account."""

import hashlib
import importlib.metadata
import json
import math
import struct
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import wasmtime

from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy_program_assets import (
    ARCHIVE_SHA256,
    PYTHON_VERSION,
    WASMTIME_VERSION,
    StrategyRuntimeUnavailable,
    runtime_archive_path,
    unpack_runtime,
    verified_archive,
)
from thesistrace.research_kernel.strategy_program_guest import (
    AVAILABLE_MODULES,
    BOOTSTRAP_READY,
    BOOTSTRAP_READY_FD,
)

SOURCE_BYTES = 65_536
INPUT_BYTES = 4 * 1024 * 1024
OUTPUT_BYTES = 1024 * 1024
STATE_BYTES = 256 * 1024
PARAMETER_BYTES = 65_536
DIAGNOSTIC_BYTES = 65_536
MEMORY_BYTES = 128 * 1024 * 1024
FUEL = 16_000_000_000
WALL_SECONDS = 3
BOOTSTRAP_WALL_SECONDS = 10
MAX_JSON_DEPTH = 32


class StrategyProgramFailure(ValueError):
    """A bounded, owner-visible program diagnostic, including across a child wire."""

    def __init__(self, message: str) -> None:
        super().__init__(message[:512])


class StrategyProgramError(StrategyProgramFailure):
    def __init__(
        self, message: str, *, source: str, session: str | None, line: int | None = None,
    ) -> None:
        self.program_sha256 = hashlib.sha256(
            source.encode(errors="backslashreplace") if isinstance(source, str) else b""
        ).hexdigest()
        self.session = session
        self.line = line
        location = f"program {self.program_sha256[:12]}"
        if session is not None:
            location += f" on {session}"
        if line is not None:
            location += f", line {line}"
        super().__init__(f"{location}: {message}")


@dataclass(frozen=True)
class ProgramResult:
    output: object
    state: dict[str, object]
    diagnostics: str


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
    def __init__(self) -> None:
        if importlib.metadata.version("wasmtime") != WASMTIME_VERSION:
            raise StrategyRuntimeUnavailable("Python Strategy requires the pinned Wasmtime version")
        archive = verified_archive(runtime_archive_path())
        self._library = tempfile.TemporaryDirectory(prefix="thesistrace-python-runtime-")
        wasm = unpack_runtime(archive, Path(self._library.name))
        self._bootstrap = Path(__file__).with_name("strategy_program_guest.py").read_text()
        config = wasmtime.Config()
        config.consume_fuel = True
        config.epoch_interruption = True
        config.cranelift_nan_canonicalization = True
        config.wasm_threads = False
        config.wasm_relaxed_simd = False
        self._engine = wasmtime.Engine(config)
        self._module = wasmtime.Module(self._engine, wasm)
        self._lock = threading.Lock()

    def identity(self) -> dict[str, object]:
        return {
            "contract": "python-strategy/v2", "python": PYTHON_VERSION,
            "wasmtime": WASMTIME_VERSION, "archive_sha256": ARCHIVE_SHA256,
            "bootstrap_sha256": hashlib.sha256(self._bootstrap.encode()).hexdigest(),
            "modules": list(AVAILABLE_MODULES), "source_bytes": SOURCE_BYTES,
            "input_bytes": INPUT_BYTES, "output_bytes": OUTPUT_BYTES,
            "state_bytes": STATE_BYTES, "parameter_bytes": PARAMETER_BYTES,
            "diagnostic_bytes": DIAGNOSTIC_BYTES,
            "memory_bytes": MEMORY_BYTES, "fuel": FUEL, "wall_seconds": WALL_SECONDS,
            "bootstrap_wall_seconds": BOOTSTRAP_WALL_SECONDS,
            "json_depth": MAX_JSON_DEPTH,
            "clock": "decision_session_15:00_UTC+08:00",
            "random": "sha256_of_canonical_invocation/v1",
        }

    def validate(self, source: str) -> None:
        self._invoke(source, context={}, state={}, parameters={}, operation="validate")

    def invoke(
        self, source: str, *, context: dict[str, object], state: dict[str, object],
        parameters: dict[str, object],
    ) -> ProgramResult:
        return self._invoke(
            source, context=context, state=state, parameters=parameters, operation="invoke",
        )

    def _invoke(self, source, *, context, state, parameters, operation) -> ProgramResult:
        session = context.get("session")
        try:
            if not isinstance(source, str) or not source or len(source.encode()) > SOURCE_BYTES:
                raise ValueError("Program source must contain at most 65536 UTF-8 bytes")
            if type(state) is not dict or type(parameters) is not dict:
                raise ValueError("Program state and parameters must be explicit JSON objects")
            encode_program_json(state, STATE_BYTES, "state")
            encode_program_json(parameters, PARAMETER_BYTES, "parameters")
            payload = encode_program_json({
                "source": source, "context": context, "state": state,
                "parameters": parameters, "operation": operation,
            }, INPUT_BYTES, "input")
            with self._lock:
                raw = self._run(payload, session)
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
                    f"{error['type']}: {error['message']}", source=source, session=session,
                    line=error["line"],
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
            return ProgramResult(returned["output"], returned["state"], diagnostics)
        except StrategyProgramError:
            raise
        except (ValueError, KeyError, TypeError, RecursionError, UnicodeError) as error:
            raise StrategyProgramError(str(error), source=source, session=session) from error

    def _run(self, payload: bytes, session: str | None) -> bytes:
        store = wasmtime.Store(self._engine)
        store.set_limits(memory_size=MEMORY_BYTES, instances=1, memories=1, tables=1)
        store.set_fuel(FUEL)
        store.set_epoch_deadline(1)
        wasi = wasmtime.WasiConfig()
        wasi.argv = ["python", "-B", "-S", "-c", self._bootstrap]
        wasi.env = [("PYTHONHOME", "/runtime"), ("PYTHONHASHSEED", "0"), ("TZ", "UTC")]
        wasi.preopen_dir(self._library.name, "/runtime", fs_mutable=False)
        stdout, stderr = bytearray(), bytearray()
        # WASI receives only this request file, never an inherited descriptor.
        with tempfile.NamedTemporaryFile() as named_input:
            named_input.write(payload)
            named_input.flush()
            wasi.stdin_file = named_input.name
            store.set_wasi(wasi)
            linker = wasmtime.Linker(self._engine)
            linker.define_wasi()
            linker.allow_shadowing = True
            expired = threading.Event()
            phase = "bootstrap"

            def interrupt():
                expired.set()
                self._engine.increment_epoch()

            timeout = threading.Timer(BOOTSTRAP_WALL_SECONDS, interrupt)

            def start_program():
                nonlocal timeout, phase
                timeout.cancel()
                timeout.join()
                if expired.is_set():
                    raise wasmtime.Trap("Python bootstrap wall time exceeded")
                phase = "program"
                timeout = threading.Timer(WALL_SECONDS, interrupt)
                timeout.daemon = True
                timeout.start()

            self._link_inputs(
                linker, payload, session, stdout, stderr,
                on_ready=start_program,
            )
            timeout.daemon = True
            timeout.start()
            try:
                instance = linker.instantiate(store, self._module)
                instance.exports(store)["_start"](store)
            except wasmtime.ExitTrap as error:
                if error.code != 0:
                    raise ValueError("Python guest exited without a valid result") from error
            except wasmtime.Trap as error:
                message = (f"Python {phase} exceeded its wall time limit" if expired.is_set()
                           else "Python guest exceeded its resource or capability limits")
                raise ValueError(message) from error
            finally:
                timeout.cancel()
                timeout.join()
                store.close()
        if stderr:
            raise ValueError("Python guest could not initialize its frozen environment")
        return bytes(stdout)

    @staticmethod
    def _link_inputs(
        linker, payload, session, stdout, stderr, *, on_ready,
    ) -> None:
        i32, i64 = wasmtime.ValType.i32(), wasmtime.ValType.i64()
        fixed_ns = (
            int(datetime.fromisoformat(session).replace(hour=7, tzinfo=UTC).timestamp())
            * 1_000_000_000
            if session is not None else 0
        )
        seed = hashlib.sha256(payload).digest()
        random_counter = 0
        program_started = False

        def memory(caller, pointer, length):
            value = caller.get("memory")
            if (not isinstance(value, wasmtime.Memory) or pointer < 0 or length < 0
                    or pointer + length > value.data_len(caller)):
                raise wasmtime.Trap("Invalid guest memory range")
            return value

        def clock(caller, clock_id, precision, pointer):
            del precision
            value = fixed_ns if clock_id == 0 else 0
            memory(caller, pointer, 8).write(caller, struct.pack("<Q", value), pointer)
            return 0

        def clock_resolution(caller, clock_id, pointer):
            del clock_id
            memory(caller, pointer, 8).write(caller, struct.pack("<Q", 1), pointer)
            return 0

        def random_bytes(caller, pointer, length):
            nonlocal random_counter
            if not 0 <= length <= OUTPUT_BYTES:
                raise wasmtime.Trap("Random request exceeds the bounded input capability")
            target = memory(caller, pointer, length)
            result = bytearray()
            while len(result) < length:
                result.extend(hashlib.sha256(seed + random_counter.to_bytes(8, "little")).digest())
                random_counter += 1
            target.write(caller, result[:length], pointer)
            return 0

        def write(caller, descriptor, vectors, count, written):
            nonlocal program_started
            if descriptor == BOOTSTRAP_READY_FD and not program_started:
                if count != 1:
                    raise wasmtime.Trap("Invalid bootstrap readiness signal")
                vector_memory = memory(caller, vectors, 8)
                pointer, length = struct.unpack(
                    "<II", vector_memory.read(caller, vectors, vectors + 8),
                )
                if length != len(BOOTSTRAP_READY):
                    raise wasmtime.Trap("Invalid bootstrap readiness signal")
                value = memory(caller, pointer, length)
                if bytes(value.read(caller, pointer, pointer + length)) != BOOTSTRAP_READY:
                    raise wasmtime.Trap("Invalid bootstrap readiness signal")
                # No researcher source runs before the trusted first signal.
                # Once consumed, this descriptor is denied like all file writes;
                # repeating the signal cannot extend the program deadline.
                program_started = True
                on_ready()
                memory(caller, written, 4).write(caller, struct.pack("<I", length), written)
                return 0
            if descriptor not in {1, 2}:
                return 76  # WASI ENOTCAPABLE; guest files never have write authority.
            if not 0 <= count <= 1024:
                raise wasmtime.Trap("Output vector limit exceeded")
            target = stdout if descriptor == 1 else stderr
            vector_memory = memory(caller, vectors, count * 8)
            size = 0
            for offset in range(count):
                entry = vectors + offset * 8
                pointer, length = struct.unpack("<II", vector_memory.read(caller, entry, entry + 8))
                if len(stdout) + len(stderr) + length > OUTPUT_BYTES:
                    raise wasmtime.Trap("Program output limit exceeded")
                value = memory(caller, pointer, length)
                target.extend(value.read(caller, pointer, pointer + length))
                size += length
            memory(caller, written, 4).write(caller, struct.pack("<I", size), written)
            return 0

        def deny_blocking(*_args):
            raise wasmtime.Trap("Blocking and network capabilities are unavailable")

        def define(name, params, callback):
            linker.define_func(
                "wasi_snapshot_preview1", name, wasmtime.FuncType(params, [i32]),
                callback, access_caller=True,
            )

        define("clock_time_get", [i32, i64, i32], clock)
        define("clock_res_get", [i32, i32], clock_resolution)
        define("random_get", [i32, i32], random_bytes)
        define("fd_write", [i32, i32, i32, i32], write)
        define("poll_oneoff", [i32, i32, i32, i32], deny_blocking)


@lru_cache(maxsize=1)
def get_strategy_runtime() -> PythonStrategyRuntime:
    """Share only the verified library and compiled Wasm, never a Python guest."""
    return PythonStrategyRuntime()

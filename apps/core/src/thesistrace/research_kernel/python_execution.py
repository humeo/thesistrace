"""Prepared Python/WASI execution with opaque inputs and bounded host capabilities.

The environment holds verified assets and compiled Wasm only. Every invocation
gets a fresh guest; no application protocol or mutable Python state is retained.
"""

import hashlib
import importlib.metadata
import json
import struct
import tempfile
import threading
from pathlib import Path

import wasmtime

from thesistrace.research_kernel.strategy_program_assets import (
    WASMTIME_VERSION,
    StrategyRuntimeUnavailable,
    runtime_archive_path,
    unpack_runtime,
    verified_archive,
)

BOOTSTRAP_READY_FD = 3
BOOTSTRAP_READY = b"thesistrace-python-ready/v1"

INPUT_BYTES = 4 * 1024 * 1024
OUTPUT_BYTES = 1024 * 1024
REQUESTS = 64
RESPONSE_BYTES = INPUT_BYTES * 4
LIBRARY_REQUESTS = 256
LIBRARY_REQUEST_BYTES = 200
LIBRARY_RESPONSE_BYTES = 16 * 1024 * 1024
MEMORY_BYTES = 128 * 1024 * 1024
FUEL = 16_000_000_000
WALL_SECONDS = 3
BOOTSTRAP_WALL_SECONDS = 10


class PreparedPythonEnvironment:
    def __init__(
        self, bootstrap: str, modules: tuple[str, ...], *,
        module_sources: dict[str, str] | None = None,
    ) -> None:
        if importlib.metadata.version("wasmtime") != WASMTIME_VERSION:
            raise StrategyRuntimeUnavailable("Python Strategy requires the pinned Wasmtime version")
        archive = verified_archive(runtime_archive_path())
        self._library = tempfile.TemporaryDirectory(prefix="thesistrace-python-runtime-")
        wasm = unpack_runtime(archive, Path(self._library.name))
        self._modules = modules
        self._prepare_sources(bootstrap, module_sources or {})
        config = wasmtime.Config()
        config.consume_fuel = True
        config.epoch_interruption = True
        config.cranelift_nan_canonicalization = True
        config.wasm_threads = False
        config.wasm_relaxed_simd = False
        self._engine = wasmtime.Engine(config)
        self._module = wasmtime.Module(self._engine, wasm)
        self._lock = threading.Lock()
        self._closed = False
        self._prepare_library_bytecode()
        root = Path(self._library.name)
        catalog = json.loads((root / "catalog.json").read_text())
        self._library_assets = {
            name.encode(): json.dumps({
                "origin": item["origin"], "package": item["package"],
            }).encode()
            + b"\0" + (root / item["path"].removeprefix("/runtime/")).read_bytes()[16:]
            for name, item in catalog.items()
        }

    def _prepare_sources(self, bootstrap, module_sources):
        """Only trusted protocol code is prepared here; user code stays in input."""
        root = Path(self._library.name)
        self._sources = []
        prefix = ["import sys, types, marshal", "sys.argv = ['-c']"]
        sources = {
            "_prepared_library": Path(__file__).with_name("python_library_guest.py").read_text(),
            **module_sources,
        }
        for index, (name, source) in enumerate(sources.items()):
            source_path = f"/runtime/protocol-{index}.py"
            code_path = f"/runtime/protocol-{index}.code"
            (root / f"protocol-{index}.py").write_text(source)
            self._sources.append((source_path, code_path, f"{name}.py"))
            prefix.extend([
                f"_module = types.ModuleType({name!r})",
                f"sys.modules[{name!r}] = _module",
                f"with open({code_path!r}, 'rb') as _code:\n"
                "    exec(marshal.load(_code), _module.__dict__)",
            ])
        prepared_bootstrap = "\n".join(prefix) + "\n" + bootstrap
        (root / "bootstrap.py").write_text(prepared_bootstrap)
        self._identity = {
            "bootstrap_sha256": hashlib.sha256(prepared_bootstrap.encode()).hexdigest(),
            "prepared_modules_sha256": hashlib.sha256(
                json.dumps(sources, sort_keys=True).encode(),
            ).hexdigest(),
            "library_requests": LIBRARY_REQUESTS,
            "library_request_bytes": LIBRARY_REQUEST_BYTES,
            "library_response_bytes": LIBRARY_RESPONSE_BYTES,
        }

    def identity(self) -> dict[str, object]:
        """Identify the trusted sources actually prepared, not later disk contents."""
        return {**self._identity, "modules": list(self._modules)}

    def _prepare_library_bytecode(self) -> None:
        """Compile pinned library sources once, without retaining any guest state.

        Only this trusted preparation can write the private runtime directory.
        Researcher source never runs here; normal invocations still receive a
        new Store and a read-only directory revoked before their source executes.
        The same pinned interpreter produces and consumes its bytecode.
        """
        with wasmtime.Store(self._engine) as store:
            store.set_limits(memory_size=MEMORY_BYTES, instances=1, memories=1, tables=1)
            store.set_fuel(FUEL)
            store.set_epoch_deadline(1)
            wasi = wasmtime.WasiConfig()
            wasi.argv = [
                "python", "-S", "-c", "import importlib, inspect, traceback, marshal, json, sys\n"
                + f"for name in {self._modules!r}: importlib.import_module(name)\n"
                + "catalog = {name: {'path': module.__cached__, 'origin': module.__file__, "
                + "'package': module.__spec__.submodule_search_locations is not None} "
                + "for name, module in sys.modules.copy().items() "
                + "if getattr(module, '__cached__', '').startswith('/runtime/lib/') }\n"
                + "with open('/runtime/catalog.json', 'w') as stream: json.dump(catalog, stream)\n"
                + "import py_compile\n"
                + f"for source, output, filename in {self._sources!r}:\n"
                + "    with open(source) as stream:\n"
                + "        code = compile(stream.read(), filename, 'exec')\n"
                + "    with open(output, 'wb') as stream: marshal.dump(code, stream)\n"
                + "py_compile.compile('/runtime/bootstrap.py', '/runtime/lib/bootstrap.pyc', "
                + "dfile='<string>', doraise=True)\n",
            ]
            wasi.env = [("PYTHONHOME", "/runtime"), ("PYTHONHASHSEED", "0"), ("TZ", "UTC")]
            wasi.preopen_dir(self._library.name, "/runtime")
            preparation_error = Path(self._library.name) / "preparation.stderr"
            wasi.stderr_file = str(preparation_error)
            store.set_wasi(wasi)
            linker = wasmtime.Linker(self._engine)
            linker.define_wasi()
            timeout = threading.Timer(BOOTSTRAP_WALL_SECONDS, self._engine.increment_epoch)
            timeout.daemon = True
            timeout.start()
            try:
                linker.instantiate(store, self._module).exports(store)["_start"](store)
            except (wasmtime.Trap, wasmtime.ExitTrap) as error:
                detail = preparation_error.read_text(errors="replace")[:4096]
                raise StrategyRuntimeUnavailable(
                    "Python library preparation failed: " + detail,
                ) from error
            finally:
                timeout.cancel()
                timeout.join()

    def invoke(self, payload: bytes, *, clock_time_ns: int, read_request=None) -> bytes:
        if type(payload) is not bytes or len(payload) > INPUT_BYTES:
            raise ValueError("Python input exceeds its byte limit")
        # One engine's epoch interrupt must not expire another invocation.
        with self._lock:
            if self._closed:
                raise ValueError("Python environment is closed")
            return self._invoke(payload, clock_time_ns=clock_time_ns, read_request=read_request)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._library_assets.clear()
                self._module.close()
                self._engine.close()
                self._library.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        self.close()

    def _invoke(self, payload: bytes, *, clock_time_ns: int, read_request) -> bytes:
        store = wasmtime.Store(self._engine)
        store.set_limits(memory_size=MEMORY_BYTES, instances=1, memories=1, tables=1)
        store.set_fuel(FUEL)
        store.set_epoch_deadline(1)
        wasi = wasmtime.WasiConfig()
        wasi.argv = ["python", "-B", "-S", "/runtime/lib/bootstrap.pyc"]
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
                linker, payload, clock_time_ns, stdout, stderr,
                on_ready=start_program,
                read_request=read_request,
                library_assets=self._library_assets,
            )
            timeout.daemon = True
            timeout.start()
            try:
                instance = linker.instantiate(store, self._module)
                instance.exports(store)["_start"](store)
            except wasmtime.ExitTrap as error:
                if error.code != 0:
                    raise ValueError("Python guest exited without a valid result: "
                                     + stderr.decode(errors="replace")[:4096]) from error
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
        linker, payload, clock_time_ns, stdout, stderr, *, on_ready, read_request, library_assets,
    ) -> None:
        i32, i64 = wasmtime.ValType.i32(), wasmtime.ValType.i64()
        fixed_ns = clock_time_ns
        seed = hashlib.sha256(payload).digest()
        random_counter = 0
        program_started = False
        response = bytearray()
        library_response = bytearray()
        library_requests = 0
        library_bytes = 0
        request_count = 0
        read_bytes = 0

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
            nonlocal program_started, request_count, read_bytes, response
            nonlocal library_response, library_requests, library_bytes
            if descriptor == 5:
                library_requests += 1
                if count != 1 or library_response or library_requests > LIBRARY_REQUESTS:
                    raise wasmtime.Trap("Library request capability exceeded")
                vector = memory(caller, vectors, 8)
                pointer, length = struct.unpack("<II", vector.read(caller, vectors, vectors + 8))
                if not 1 <= length <= LIBRARY_REQUEST_BYTES:
                    raise wasmtime.Trap("Library request exceeds size limit")
                value = memory(caller, pointer, length)
                name = bytes(value.read(caller, pointer, pointer + length))
                encoded = library_assets.get(name, b"")
                library_bytes += len(encoded)
                if library_bytes > LIBRARY_RESPONSE_BYTES:
                    raise wasmtime.Trap("Library response limit exceeded")
                library_response = bytearray(encoded)
                memory(caller, written, 4).write(caller, struct.pack("<I", length), written)
                return 0
            if descriptor == 4 and program_started:
                request_count += 1
                if (read_request is None or response
                        or request_count > REQUESTS or count != 1):
                    raise wasmtime.Trap("Host request capability exceeded")
                vector = memory(caller, vectors, 8)
                pointer, length = struct.unpack("<II", vector.read(caller, vectors, vectors + 8))
                if length > 65536:
                    raise wasmtime.Trap("Host request exceeds size limit")
                value = memory(caller, pointer, length)
                raw = bytes(value.read(caller, pointer, pointer + length))
                encoded = read_request(raw)
                if type(encoded) is not bytes or len(encoded) > INPUT_BYTES:
                    raise wasmtime.Trap("RPC response exceeds size limit")
                read_bytes += len(encoded)
                if read_bytes > RESPONSE_BYTES:
                    raise wasmtime.Trap("Cumulative host response limit exceeded")
                response = bytearray(encoded)
                memory(caller, written, 4).write(caller, struct.pack("<I", length), written)
                return 0
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

        def read(caller, descriptor, vectors, count, offset, read_count):
            if (descriptor not in {4, 5} or offset != 0 or not 0 <= count <= 1024
                    or (descriptor == 4 and not program_started)):
                return 76
            pending = response if descriptor == 4 else library_response
            vector = memory(caller, vectors, count * 8)
            size = 0
            for offset in range(count):
                entry = vectors + offset * 8
                pointer, length = struct.unpack("<II", vector.read(caller, entry, entry + 8))
                target = memory(caller, pointer, length)
                chunk = pending[:length]
                target.write(caller, chunk, pointer)
                del pending[:len(chunk)]
                size += len(chunk)
            memory(caller, read_count, 4).write(caller, struct.pack("<I", size), read_count)
            return 0

        def define(name, params, callback):
            linker.define_func(
                "wasi_snapshot_preview1", name, wasmtime.FuncType(params, [i32]),
                callback, access_caller=True,
            )

        define("clock_time_get", [i32, i64, i32], clock)
        define("clock_res_get", [i32, i32], clock_resolution)
        define("random_get", [i32, i32], random_bytes)
        define("fd_write", [i32, i32, i32, i32], write)
        define("fd_pread", [i32, i32, i32, i64, i32], read)
        define("poll_oneoff", [i32, i32, i32, i32], deny_blocking)

"""Prepared Python + NumPy with private execution sessions and bounded capabilities."""

import base64
import hashlib
import importlib.metadata
import json
import threading
from contextlib import ExitStack

import wasmtime
from wasmtime.component import Component, Linker, Record

from thesistrace.research_kernel.strategy_program_assets import (
    WASMTIME_VERSION,
    StrategyRuntimeUnavailable,
    verified_component,
)

INPUT_BYTES = 4 * 1024 * 1024
OUTPUT_BYTES = 16 * 1024 * 1024
REQUEST_BYTES = 65536
REQUESTS = 64
RESPONSE_BYTES = 32 * 1024 * 1024
MEMORY_BYTES = 128 * 1024 * 1024
FUEL = 16_000_000_000
WALL_SECONDS = 3
BOOTSTRAP_WALL_SECONDS = 10


class PreparedPythonEnvironment:
    def __init__(self, bootstrap: str, *, module_sources: dict[str, str] | None = None):
        if importlib.metadata.version("wasmtime") != WASMTIME_VERSION:
            raise StrategyRuntimeUnavailable("Python Strategy requires the pinned Wasmtime version")
        prefix = ["import sys, types"]
        for name, source in (module_sources or {}).items():
            prefix.extend(
                [
                    f"_module = types.ModuleType({name!r})",
                    f"sys.modules[{name!r}] = _module",
                    f'exec(compile({source!r}, {name + ".py"!r}, "exec"), _module.__dict__)',
                ]
            )
        # A private session installs trusted modules once; a fresh session starts clean.
        initialization = "\n".join(prefix[1:])
        import textwrap

        self._bootstrap = (
            "import sys, types\n"
            'if "_thesistrace_modules_ready" not in sys.modules:\n'
            + textwrap.indent(initialization or "pass", "    ")
            + '\n    sys.modules["_thesistrace_modules_ready"] = types.ModuleType("ready")\n'
            + bootstrap
        )
        self._identity = {
            "bootstrap_sha256": hashlib.sha256(self._bootstrap.encode()).hexdigest(),
            "prepared_modules_sha256": hashlib.sha256(
                json.dumps(module_sources or {}, sort_keys=True).encode(),
            ).hexdigest(),
        }
        config = wasmtime.Config()
        config.wasm_component_model = True
        config.wasm_exceptions = True
        config.consume_fuel = True
        config.epoch_interruption = True
        config.cranelift_nan_canonicalization = True
        config.wasm_threads = False
        config.wasm_relaxed_simd = False
        config.memory_init_cow = True
        config.cache = True
        self._engine = wasmtime.Engine(config)
        self._component = Component(self._engine, verified_component())
        self._export = self._component.get_export_index("invoke")
        if self._export is None:
            raise ValueError("Prepared Python component lacks its invoke export")
        self._lock = threading.RLock()
        self._closed = False

    def identity(self):
        return dict(self._identity)

    def invoke(self, payload, *, clock_time_ns, read_request=None):
        with self.open_session() as session:
            return session.invoke(payload, clock_time_ns=clock_time_ns, read_request=read_request)

    def open_session(self):
        """A private guest heap, explicitly owned and closed by one program calculation."""
        return PreparedPythonSession(self)

    def _session_invoke(self, session, payload, *, clock_time_ns, read_request=None):
        if type(payload) is not bytes or len(payload) > INPUT_BYTES:
            raise ValueError("Python input exceeds its byte limit")
        with self._lock:
            if self._closed:
                raise ValueError("Python environment is closed")
            return self._invoke(
                payload, clock_time_ns=clock_time_ns, read_request=read_request, session=session
            )

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._export.close()
                self._component.close()
                self._engine.close()

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        self.close()

    def _invoke(self, payload, *, clock_time_ns, read_request, session):
        stdout, stderr = bytearray(), bytearray()
        expired = threading.Event()
        phase = "bootstrap"
        failure = None

        def interrupt():
            expired.set()
            self._engine.increment_epoch()

        timeout = threading.Timer(BOOTSTRAP_WALL_SECONDS, interrupt)

        def ready(_store):
            nonlocal timeout, phase
            if phase != 'bootstrap':
                raise wasmtime.WasmtimeError('Repeated bootstrap readiness signal')
            timeout.cancel()
            timeout.join()
            if expired.is_set():
                raise wasmtime.WasmtimeError('Python bootstrap wall time exceeded')
            phase = 'program'
            timeout = threading.Timer(WALL_SECONDS, interrupt)
            timeout.daemon = True
            timeout.start()

        def write(target, data):
            nonlocal failure
            if failure is not None:
                return -5
            if len(stdout) + len(stderr) + len(data) > OUTPUT_BYTES:
                failure = 'Program output limit exceeded'
                self._engine.increment_epoch()
                return -5
            target.extend(data)
            return len(data)

        request_count, response_bytes = 0, 0

        def read(_store, encoded):
            nonlocal request_count, response_bytes
            request_count += 1
            if (
                phase != "program"
                or read_request is None
                or request_count > REQUESTS
                or len(encoded) > 4 * ((REQUEST_BYTES + 2) // 3)
            ):
                raise wasmtime.WasmtimeError("Host request capability exceeded")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except ValueError as error:
                raise wasmtime.WasmtimeError("Invalid host request encoding") from error
            if len(raw) > REQUEST_BYTES:
                raise wasmtime.WasmtimeError("Host request exceeds size limit")
            try:
                value = read_request(raw)
            except Exception as error:
                raise wasmtime.WasmtimeError("Host request failed") from error
            if type(value) is not bytes or len(value) > RESPONSE_BYTES:
                raise wasmtime.WasmtimeError("RPC response exceeds size limit")
            response_bytes += len(value)
            if response_bytes > RESPONSE_BYTES:
                raise wasmtime.WasmtimeError("Cumulative host response limit exceeded")
            return base64.b64encode(value).decode("ascii")

        session.callbacks = {
            "ready": ready,
            "read": read,
            "stdout": lambda data: write(stdout, data),
            "stderr": lambda data: write(stderr, data),
        }
        session.inputs.update(payload=payload, clock_time_ns=clock_time_ns, random_counter=0)
        if session.store is None:
            session.store = session.resources.enter_context(wasmtime.Store(self._engine))
            session.linker = session.resources.enter_context(Linker(self._engine))
        store, linker = session.store, session.linker
        if session.instance is None:
            store.set_limits(memory_size=MEMORY_BYTES)
            wasi = wasmtime.WasiConfig()
            wasi.env = [("PYTHONHOME", "/runtime"), ("PYTHONHASHSEED", "0"), ("TZ", "UTC")]
            wasi.argv = ["python", "-c"]
            # No inherited descriptors, environment, preopened directories or network grants.
            wasi.stdout_custom = lambda data: session.callbacks["stdout"](data)
            wasi.stderr_custom = lambda data: session.callbacks["stderr"](data)
            store.set_wasi(wasi)
            linker.add_wasip2()
            linker.allow_shadowing = True
            with linker.root() as root:
                root.add_func("ready", lambda *args: session.callbacks["ready"](*args))
                root.add_func("read-request", lambda *args: session.callbacks["read"](*args))
                self._link_inputs(root, session.inputs)
        store.set_fuel(FUEL)
        store.set_epoch_deadline(1)
        timeout.daemon = True
        timeout.start()
        try:
            if session.instance is None:
                session.instance = linker.instantiate(store, self._component)
            instance = session.instance
            invoke = instance.get_func(store, self._export)
            if invoke is None:
                raise ValueError("Prepared Python component lacks its invoke function")
            invoke(store, self._bootstrap, base64.b64encode(payload).decode("ascii"))
            invoke.post_return(store)
        except wasmtime.ExitTrap as error:
            error.close()
            if error.code != 0:
                raise ValueError("Python guest exited without a valid result") from None
        except (wasmtime.Trap, wasmtime.WasmtimeError) as error:
            message = (
                f"Python {phase} exceeded its wall time limit"
                if expired.is_set()
                else "Python guest exceeded its resource or capability limits"
            )
            # Native errors retain compiled guest resources. Release them outside
            # a future guest callback, where deferred GC can exhaust its deadline.
            error.close()
            raise ValueError(message) from None
        finally:
            timeout.cancel()
            timeout.join()
        if failure is not None:
            raise ValueError(failure)
        if stderr:
            raise ValueError("Python guest could not initialize its frozen environment")
        return bytes(stdout)

    @staticmethod
    def _link_inputs(root, inputs):

        def random_bytes(_store, length):
            if not 0 <= length <= OUTPUT_BYTES:
                raise wasmtime.WasmtimeError("Random request exceeds its byte limit")
            result = bytearray()
            seed = hashlib.sha256(inputs["payload"]).digest()
            while len(result) < length:
                result.extend(
                    hashlib.sha256(seed + inputs["random_counter"].to_bytes(8, "little")).digest()
                )
                inputs["random_counter"] += 1
            return bytes(result[:length])

        def wall(_store):
            value = Record()
            value.seconds, value.nanoseconds = divmod(inputs["clock_time_ns"], 1_000_000_000)
            return value

        def resolution(_store):
            value = Record()
            value.seconds, value.nanoseconds = 0, 1
            return value

        def deny(*_args):
            raise wasmtime.WasmtimeError('Blocking and network capabilities are unavailable')

        # These are the exact interfaces of the verified component. No clock or
        # entropy capability inherits the host's inputs. With no filesystem or
        # socket grants and an empty stdin, only ready in-memory streams remain;
        # rejecting timer subscriptions prevents a blocking sleep or poll timer.
        with root.add_instance("wasi:clocks/wall-clock@0.2.4") as namespace:
            namespace.add_func("now", wall)
            namespace.add_func("resolution", resolution)
        with root.add_instance("wasi:clocks/monotonic-clock@0.2.4") as namespace:
            namespace.add_func("now", lambda _store: 0)
            namespace.add_func("resolution", lambda _store: 1)
            namespace.add_func("subscribe-duration", deny)
            namespace.add_func("subscribe-instant", deny)
        with root.add_instance("wasi:random/random@0.2.4") as namespace:
            namespace.add_func("get-random-bytes", random_bytes)
            namespace.add_func(
                "get-random-u64",
                lambda ctx: int.from_bytes(
                    random_bytes(ctx, 8),
                    "little",
                ),
            )


class PreparedPythonSession:
    """One private execution heap. A failed call poisons and closes the session."""

    def __init__(self, environment):
        self.environment = environment
        self.resources = ExitStack()
        self.store = self.linker = self.instance = None
        self.callbacks = {}
        self.inputs = {}
        self.closed = False

    def invoke(self, payload, *, clock_time_ns, read_request=None):
        with self.environment._lock:
            if self.closed:
                raise ValueError("Python execution session is closed")
            try:
                return self.environment._session_invoke(
                    self,
                    payload,
                    clock_time_ns=clock_time_ns,
                    read_request=read_request,
                )
            except BaseException:
                self.close()
                raise

    def close(self):
        with self.environment._lock:
            if not self.closed:
                self.closed = True
                self.resources.close()
                self.callbacks.clear()
                self.inputs.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        self.close()

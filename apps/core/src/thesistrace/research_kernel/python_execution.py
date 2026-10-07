"""Prepared Python + NumPy with fresh invocation state and bounded host capabilities."""
import base64
import hashlib
import importlib.metadata
import json
import threading

import wasmtime
from wasmtime.component import Component, Linker, Record

from thesistrace.research_kernel.strategy_program_assets import (
    WASMTIME_VERSION,
    StrategyRuntimeUnavailable,
    verified_component,
)

INPUT_BYTES = 4 * 1024 * 1024
OUTPUT_BYTES = 1024 * 1024
REQUEST_BYTES = 65536
REQUESTS = 64
RESPONSE_BYTES = INPUT_BYTES * 4
MEMORY_BYTES = 128 * 1024 * 1024
FUEL = 16_000_000_000
WALL_SECONDS = 3
BOOTSTRAP_WALL_SECONDS = 10


class PreparedPythonEnvironment:
    def __init__(self, bootstrap: str, *, module_sources: dict[str, str] | None = None):
        if importlib.metadata.version("wasmtime") != WASMTIME_VERSION:
            raise StrategyRuntimeUnavailable("Python Strategy requires the pinned Wasmtime version")
        prefix = ['import sys, types']
        for name, source in (module_sources or {}).items():
            prefix.extend([
                f'_module = types.ModuleType({name!r})',
                f'sys.modules[{name!r}] = _module',
                f'exec(compile({source!r}, {name + ".py"!r}, "exec"), _module.__dict__)',
            ])
        self._bootstrap = '\n'.join(prefix) + '\n' + bootstrap
        self._identity = {
            'bootstrap_sha256': hashlib.sha256(self._bootstrap.encode()).hexdigest(),
            'prepared_modules_sha256': hashlib.sha256(
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
        self._export = self._component.get_export_index('invoke')
        if self._export is None:
            raise ValueError('Prepared Python component lacks its invoke export')
        self._lock = threading.Lock()
        self._closed = False

    def identity(self):
        return dict(self._identity)

    def invoke(self, payload, *, clock_time_ns, read_request=None):
        if type(payload) is not bytes or len(payload) > INPUT_BYTES:
            raise ValueError('Python input exceeds its byte limit')
        with self._lock:
            if self._closed:
                raise ValueError('Python environment is closed')
            return self._invoke(payload, clock_time_ns=clock_time_ns, read_request=read_request)

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

    def _invoke(self, payload, *, clock_time_ns, read_request):
        stdout, stderr = bytearray(), bytearray()
        expired = threading.Event()
        phase = 'bootstrap'
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
            if (phase != 'program' or read_request is None or request_count > REQUESTS
                    or len(encoded) > 4 * ((REQUEST_BYTES + 2) // 3)):
                raise wasmtime.WasmtimeError('Host request capability exceeded')
            try:
                raw = base64.b64decode(encoded, validate=True)
            except ValueError as error:
                raise wasmtime.WasmtimeError('Invalid host request encoding') from error
            if len(raw) > REQUEST_BYTES:
                raise wasmtime.WasmtimeError('Host request exceeds size limit')
            try:
                value = read_request(raw)
            except Exception as error:
                raise wasmtime.WasmtimeError('Host request failed') from error
            if type(value) is not bytes or len(value) > INPUT_BYTES:
                raise wasmtime.WasmtimeError('RPC response exceeds size limit')
            response_bytes += len(value)
            if response_bytes > RESPONSE_BYTES:
                raise wasmtime.WasmtimeError('Cumulative host response limit exceeded')
            return base64.b64encode(value).decode('ascii')

        with wasmtime.Store(self._engine) as store, Linker(self._engine) as linker:
            store.set_limits(memory_size=MEMORY_BYTES)
            store.set_fuel(FUEL)
            store.set_epoch_deadline(1)
            wasi = wasmtime.WasiConfig()
            wasi.env = [('PYTHONHOME', '/runtime'), ('PYTHONHASHSEED', '0'), ('TZ', 'UTC')]
            wasi.argv = ['python', '-c']
            # No inherited descriptors, environment, preopened directories or network grants.
            wasi.stdout_custom = lambda data: write(stdout, data)
            wasi.stderr_custom = lambda data: write(stderr, data)
            store.set_wasi(wasi)
            linker.add_wasip2()
            linker.allow_shadowing = True
            with linker.root() as root:
                root.add_func('ready', ready)
                root.add_func('read-request', read)
                self._link_inputs(root, payload, clock_time_ns)
            timeout.daemon = True
            timeout.start()
            try:
                instance = linker.instantiate(store, self._component)
                invoke = instance.get_func(store, self._export)
                if invoke is None:
                    raise ValueError('Prepared Python component lacks its invoke function')
                invoke(store, self._bootstrap, base64.b64encode(payload).decode('ascii'))
                invoke.post_return(store)
            except wasmtime.ExitTrap as error:
                if error.code != 0:
                    raise ValueError('Python guest exited without a valid result') from error
            except (wasmtime.Trap, wasmtime.WasmtimeError) as error:
                message = (f'Python {phase} exceeded its wall time limit' if expired.is_set()
                           else 'Python guest exceeded its resource or capability limits')
                raise ValueError(message) from error
            finally:
                timeout.cancel()
                timeout.join()
        if failure is not None:
            raise ValueError(failure)
        if stderr:
            raise ValueError('Python guest could not initialize its frozen environment')
        return bytes(stdout)

    @staticmethod
    def _link_inputs(root, payload, clock_time_ns):
        seed = hashlib.sha256(payload).digest()
        random_counter = 0

        def random_bytes(_store, length):
            nonlocal random_counter
            if not 0 <= length <= OUTPUT_BYTES:
                raise wasmtime.WasmtimeError('Random request exceeds its byte limit')
            result = bytearray()
            while len(result) < length:
                result.extend(hashlib.sha256(seed + random_counter.to_bytes(8, 'little')).digest())
                random_counter += 1
            return bytes(result[:length])

        def wall(_store):
            value = Record()
            value.seconds, value.nanoseconds = divmod(clock_time_ns, 1_000_000_000)
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
            namespace.add_func("get-random-u64", lambda ctx: int.from_bytes(
                random_bytes(ctx, 8), "little",
            ))

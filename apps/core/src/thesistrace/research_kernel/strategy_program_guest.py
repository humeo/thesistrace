"""Trusted bootstrap whose main function executes only inside the pinned WASI guest."""

import importlib
import io
import json
import os
import sys
import traceback
import types

AVAILABLE_MODULES = (
    "bisect", "calendar", "collections", "copy", "dataclasses", "datetime", "decimal",
    "enum", "fractions", "functools", "heapq", "itertools", "json", "math", "operator",
    "random", "re", "statistics", "string", "time", "typing", "_strptime",
)
BOOTSTRAP_READY_FD = 3
BOOTSTRAP_READY = b"thesistrace-python-ready/v1"


def freeze(value):
    if isinstance(value, dict):
        return types.MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


class Diagnostics(io.TextIOBase):
    def __init__(self):
        self.parts = []
        self.byte_count = 0

    def write(self, text):
        self.byte_count += len(text.encode("utf-8"))
        if self.byte_count > 65_536:
            raise ValueError("Program diagnostics exceed 65536 bytes")
        self.parts.append(text)
        return len(text)


def main():
    for name in AVAILABLE_MODULES:
        importlib.import_module(name)
    request = json.loads(sys.stdin.buffer.read())
    # The only preopened directory contains the pinned standard library. Revoke
    # its descriptor before executing any source, including top-level imports.
    os.close(3)
    os.close(0)
    sys.path.clear()
    sys.path_importer_cache.clear()
    output = sys.stdout
    diagnostics = Diagnostics()
    sys.stdout = diagnostics
    sys.stderr = diagnostics
    # The host accepts this one-time control write only after the trusted
    # bootstrap has revoked its file capabilities and before any user source.
    os.write(BOOTSTRAP_READY_FD, BOOTSTRAP_READY)
    try:
        code = compile(request["source"], "strategy.py", "exec")
        if request["operation"] == "validate":
            result = {"output": None, "state": {}}
        else:
            module = types.ModuleType("strategy")
            sys.modules["strategy"] = module
            exec(code, module.__dict__)
            callback = module.__dict__.get("decide")
            if not callable(callback):
                raise ValueError("Program must define decide(context, state, parameters)")
            result = callback(
                freeze(request["context"]), request["state"], freeze(request["parameters"]),
            )
        encoded = json.dumps(
            {"ok": True, "result": result, "diagnostics": "".join(diagnostics.parts)},
            allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
    except BaseException as error:
        line = error.lineno if isinstance(error, SyntaxError) else None
        for frame in traceback.extract_tb(error.__traceback__):
            if frame.filename == "strategy.py":
                line = frame.lineno
        encoded = json.dumps({
            "ok": False, "error": {
                "type": type(error).__name__, "message": str(error)[:4096], "line": line,
            },
        }, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    output.write(encoded)
    output.flush()


if __name__ == "__main__":
    main()

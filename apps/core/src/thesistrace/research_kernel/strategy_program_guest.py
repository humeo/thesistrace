"""Trusted bootstrap whose main function executes only inside the pinned WASI guest."""

import io
import json
import sys
import types

AVAILABLE_MODULES = (
    "bisect", "calendar", "collections", "copy", "dataclasses", "datetime", "decimal",
    "enum", "fractions", "functools", "heapq", "itertools", "json", "math", "operator",
    "random", "re", "statistics", "string", "time", "typing", "_strptime", "numpy",
)


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
    from _thesistrace_execution import ready

    request = json.loads(sys.stdin.buffer.read())
    sys.path.clear()
    sys.path_importer_cache.clear()
    output = sys.stdout
    diagnostics = Diagnostics()
    sys.stdout = diagnostics
    sys.stderr = diagnostics
    ready()
    try:
        code = compile(request["source"], "strategy.py", "exec")
        sdk = sys.modules["quantgrove"]
        module = types.ModuleType("strategy")
        sys.modules["strategy"] = module
        exec(code, module.__dict__)
        expected = getattr(sdk, request["entrypoint"])
        classes = {value for value in module.__dict__.values()
                   if isinstance(value, type) and value.__module__ == "strategy"
                   and issubclass(value, expected)}
        if len(classes) != 1:
            raise ValueError("Define exactly one " + request["entrypoint"] + " subclass")
        strategy = classes.pop()()
        strategy.state = request["state"]
        if type(strategy).on_close is sdk.Strategy.on_close:
            raise ValueError("Implement on_close(self, data, account)")
        data, account = sdk.Data(request["context"]), sdk.Account(request["context"])
        decision = None
        if request["operation"] == "invoke":
            decision = strategy.on_close(data, account)
            if decision is not None and not isinstance(decision, sdk.Decision):
                raise TypeError("Return None or a decision built by a strategy helper")
        else:
            import inspect

            inspect.signature(strategy.on_close).bind(data, account)
        result = {"output": None if decision is None else decision.value, "state": strategy.state}
        encoded = json.dumps(
            {"ok": True, "result": result, "diagnostics": "".join(diagnostics.parts)},
            allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
    except BaseException as error:
        import traceback

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

"""Trusted bootstrap whose main function executes only inside the pinned WASI guest."""

import io
import json
import sys
import types

AVAILABLE_MODULES = (
    "bisect",
    "calendar",
    "collections",
    "copy",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fractions",
    "functools",
    "heapq",
    "itertools",
    "json",
    "math",
    "operator",
    "random",
    "re",
    "statistics",
    "string",
    "time",
    "typing",
    "_strptime",
    "numpy",
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
    response_stream = sys.stdout
    diagnostics = Diagnostics()
    sys.stdout = diagnostics
    sys.stderr = diagnostics
    ready()
    try:
        import inspect

        from _program_wire import decode_state, encode_state

        sdk = sys.modules["quantgrove"]
        module = sys.modules.get("strategy")
        if module is None:
            code = compile(request["source"], "strategy.py", "exec")
            module = types.ModuleType("strategy")
            sys.modules["strategy"] = module
            exec(code, module.__dict__)
        if request["state"] is not None:
            module.__program_state__ = decode_state(request["state"])
        compute, decide = getattr(module, "compute", None), getattr(module, "decide", None)
        if compute is None and decide is None:
            raise ValueError("Define compute(data, state) and/or decide(data, account, state)")
        for function, arity in ((compute, 2), (decide, 3)):
            if function is not None:
                if not inspect.isfunction(function):
                    raise TypeError("Program entrypoints must be Python functions")
                inspect.signature(function).bind(*([None] * arity))
        state = module.__program_state__
        output = None
        if request["operation"] == "compute":
            if compute is None:
                raise ValueError("Program has no compute entrypoint")
            value = compute(sdk.BatchData(request["context"]), state)
            expected = sdk.Values if decide is not None else sdk.Targets
            if not isinstance(value, expected):
                raise TypeError("compute must return " + expected.__name__)
            output = value._to_wire()
        elif request["operation"] == "invoke":
            if decide is None:
                raise ValueError("Program has no decide entrypoint")
            value = decide(sdk.Data(request["context"]), sdk.Account(request["context"]), state)
            if value is not None and not isinstance(value, sdk.Decision):
                raise TypeError("Return None or a decision built by a strategy helper")
            output = None if value is None else value.value
        else:
            output = {"compute": compute is not None, "decide": decide is not None}
        result = {
            "output": output,
            "state": encode_state(state) if request.get("checkpoint", True) else None,
        }
        encoded = json.dumps(
            {"ok": True, "result": result, "diagnostics": "".join(diagnostics.parts)},
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except BaseException as error:
        import traceback

        line = error.lineno if isinstance(error, SyntaxError) else None
        for frame in traceback.extract_tb(error.__traceback__):
            if frame.filename == "strategy.py":
                line = frame.lineno
        encoded = json.dumps(
            {
                "ok": False,
                "error": {
                    "type": type(error).__name__,
                    "message": str(error)[:4096],
                    "line": line,
                },
            },
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    response_stream.write(encoded)
    response_stream.flush()


if __name__ == "__main__":
    main()

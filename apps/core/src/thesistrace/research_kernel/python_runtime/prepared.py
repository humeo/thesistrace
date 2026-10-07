"""Trusted generic entrypoint frozen into a Python + NumPy WASI component.

Only libraries are initialized in this image. The host creates a fresh component
instance before providing application bootstrap, source, input or explicit state.
"""
import base64
import hashlib
import importlib
import io
import sys
import types

import numpy as np
import wit_world
from wit_world import read_request as _read_request
from wit_world import ready

# Initialize the supported library closure before the image is frozen. These
# imports deliberately have no application input or filesystem capability.
for _name in (
    "bisect", "calendar", "collections", "copy", "dataclasses", "datetime",
    "decimal", "enum", "fractions", "functools", "heapq", "inspect", "itertools",
    "json", "math", "operator", "os", "random", "re", "statistics", "string",
    "time", "traceback", "typing", "_strptime", "numpy.fft", "numpy.linalg",
    "numpy.ma", "numpy.polynomial", "numpy.random", "numpy.rec", "numpy.strings",
):
    importlib.import_module(_name)

# componentize-py clears the build environment and reloads only the host's
# explicitly supplied runtime environment on the first export call.


def read_request(payload: bytes) -> bytes:
    if type(payload) is not bytes:
        raise TypeError('Host request must be bytes')
    return base64.b64decode(_read_request(base64.b64encode(payload).decode('ascii')), validate=True)


class WitWorld(wit_world.WitWorld):
    def invoke(self, bootstrap: str, payload: str) -> None:
        raw = base64.b64decode(payload, validate=True)
        # componentize-py seeds stdlib random once on the first export call.
        # NumPy gets an independent explicit seed and consumes none of that stream.
        seed = hashlib.sha256(b'thesistrace-numpy/v1\0' + raw).digest()
        np.random.seed(np.frombuffer(seed, dtype='<u4'))
        cap = types.ModuleType('_thesistrace_execution')
        cap.payload = raw
        cap.read_request = read_request
        cap.ready = ready
        sys.modules[cap.__name__] = cap
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8')
        # WASI streams may accept only part of a write. BufferedWriter handles
        # that standard IO contract, including large JSON and Unicode results.
        sys.stdout = io.TextIOWrapper(io.BufferedWriter(io.FileIO(1, 'wb', closefd=False)),
                                      encoding='utf-8')
        sys.stderr = io.TextIOWrapper(io.BufferedWriter(io.FileIO(2, 'wb', closefd=False)),
                                      encoding='utf-8')
        sys.__stdout__, sys.__stderr__ = sys.stdout, sys.stderr
        exec(compile(bootstrap, '<string>', 'exec'), {'__name__': '__main__'})
        sys.stdout.flush()
        sys.stderr.flush()

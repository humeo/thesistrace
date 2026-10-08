"""Bounded history arrays shared by the host and the isolated Python SDK.

Axis metadata is one JSON line followed by a standard, non-pickled NPY array.
Only the selected array contents cross the seam, never its backing allocation.
"""

import io
import json
from dataclasses import dataclass

import numpy as np

# The wire accommodates the largest current compute block. The host capability
# applies the smaller decide budgets before materializing or encoding a read.
MAX_BYTES = 32 * 1024 * 1024
MAX_CELLS = 2_097_152
MAX_SESSIONS = 380


@dataclass(frozen=True)
class HistoryWindow:
    sessions: tuple[str, ...]
    instruments: tuple[str, ...]
    array: np.ndarray


def _axes(metadata):
    if type(metadata) is not dict or set(metadata) != {"sessions", "instruments"}:
        raise ValueError("History requires session and instrument axes")
    sessions, instruments = metadata["sessions"], metadata["instruments"]
    for values in (sessions, instruments):
        if (type(values) is not list or any(type(item) is not str for item in values)
                or len(values) != len(set(values))):
            raise ValueError("History axes must contain unique strings")
    if len(sessions) > MAX_SESSIONS or len(sessions) * len(instruments) > MAX_CELLS:
        raise ValueError("History array exceeds its cell budget")
    return tuple(sessions), tuple(instruments)


def _numbers(array, shape):
    if not isinstance(array, np.ndarray) or array.shape != shape or array.dtype != np.dtype("<f8"):
        raise ValueError("History requires a float64 matrix matching its axes")
    finite = array[~np.isnan(array)]
    if np.isinf(finite).any():
        raise ValueError("Program history contains a non-finite field value")
    if ((np.trunc(finite) == finite) & (np.abs(finite) > 2**53 - 1)).any():
        raise ValueError("Program history integers must fit the exact interoperable range")


def encode_history(window: HistoryWindow) -> bytes:
    metadata = {"sessions": list(window.sessions), "instruments": list(window.instruments)}
    sessions, instruments = _axes(metadata)
    _numbers(window.array, (len(instruments), len(sessions)))
    stream = io.BytesIO()
    stream.write(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode())
    stream.write(b"\n")
    np.lib.format.write_array(stream, np.ascontiguousarray(window.array), version=(1, 0),
                              allow_pickle=False)
    encoded = stream.getvalue()
    if len(encoded) > MAX_BYTES:
        raise ValueError("Program history response exceeds its byte limit")
    return encoded


def decode_history(encoded: bytes) -> HistoryWindow:
    if type(encoded) is not bytes or len(encoded) > MAX_BYTES:
        raise ValueError("Program history response exceeds its byte limit")
    stream = io.BytesIO(encoded)
    try:
        metadata = json.loads(stream.readline())
        if type(metadata) is dict and set(metadata) == {"error"}:
            raise ValueError(str(metadata["error"]))
        sessions, instruments = _axes(metadata)
        if np.lib.format.read_magic(stream) != (1, 0):
            raise ValueError("History requires NPY version 1")
        shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(stream)
        if (shape != (len(instruments), len(sessions)) or fortran_order
                or dtype != np.dtype("<f8")):
            raise ValueError("History requires a C-order float64 matrix matching its axes")
        offset = stream.tell()
        if len(encoded) - offset != len(instruments) * len(sessions) * 8:
            raise ValueError("History array length differs from its axes")
        # An immutable bytes owner makes writeability irreversible. A read-only
        # flag on an owning ndarray alone could be re-enabled by user code.
        array = np.frombuffer(encoded, dtype="<f8", offset=offset).reshape(shape)
        _numbers(array, shape)
    except (EOFError, UnicodeError, TypeError, KeyError) as error:
        raise ValueError("Invalid history array") from error
    return HistoryWindow(sessions, instruments, array)

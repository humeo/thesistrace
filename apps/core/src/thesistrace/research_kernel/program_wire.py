"""Bounded, pickle-free numerical values shared by the guest and its Adapter."""

import base64
import io

import numpy as np

ARRAY_KEY = "$quantgrove.npy"
ARRAY_BYTES = 16 * 1024 * 1024


def array_to_wire(value):
    array = np.asarray(value)
    if array.dtype.kind not in "biuf" or array.ndim > 4 or array.nbytes > ARRAY_BYTES:
        raise ValueError("Arrays require bounded boolean, integer or real numeric values")
    stream = io.BytesIO()
    np.save(stream, np.array(array, copy=True, order="C"), allow_pickle=False)
    return {ARRAY_KEY: base64.b64encode(stream.getvalue()).decode("ascii")}


def array_from_wire(value):
    if type(value) is not dict or set(value) != {ARRAY_KEY} or type(value[ARRAY_KEY]) is not str:
        raise ValueError("Invalid numerical array envelope")
    if len(value[ARRAY_KEY]) > 4 * ((ARRAY_BYTES + 16384 + 2) // 3):
        raise ValueError("Array exceeds its byte limit")
    raw = base64.b64decode(value[ARRAY_KEY], validate=True)
    stream = io.BytesIO(raw)
    version = np.lib.format.read_magic(stream)
    if version != (1, 0):
        raise ValueError("Arrays require NPY version 1")
    shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
    if (
        dtype.kind not in "biuf"
        or len(shape) > 4
        or fortran
        or any(type(n) is not int or n < 0 for n in shape)
    ):
        raise ValueError("Invalid numerical array dtype or shape")
    size = 1
    for n in shape:
        size *= n
    if size * dtype.itemsize > ARRAY_BYTES or len(raw) - stream.tell() != size * dtype.itemsize:
        raise ValueError("Array size differs from its envelope")
    return np.frombuffer(raw, dtype=dtype, offset=stream.tell()).reshape(shape)


def encode_state(value):
    if isinstance(value, np.ndarray):
        return array_to_wire(value)
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("State requires string object keys")
        if ARRAY_KEY in value:
            raise ValueError("State keys beginning with the array envelope are reserved")
        return {key: encode_state(item) for key, item in value.items()}
    if type(value) is list:
        return [encode_state(item) for item in value]
    return value


def decode_state(value):
    if type(value) is dict:
        if ARRAY_KEY in value:
            return array_from_wire(value).copy()
        return {key: decode_state(item) for key, item in value.items()}
    if type(value) is list:
        return [decode_state(item) for item in value]
    return value

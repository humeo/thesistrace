from __future__ import annotations

import ctypes
import gc
import sys

import pyarrow as pa


def release_unused_memory() -> None:
    """Return unused Python, Arrow and libc memory after a bounded operation."""
    gc.collect()
    pa.default_memory_pool().release_unused()
    allocator = ctypes.CDLL(None)
    if sys.platform == "darwin":
        pressure_relief = allocator.malloc_zone_pressure_relief
        pressure_relief.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
        pressure_relief.restype = ctypes.c_size_t
        pressure_relief(None, 0)
        return
    if sys.platform.startswith("linux"):
        trim = allocator.malloc_trim
        trim.argtypes = (ctypes.c_size_t,)
        trim.restype = ctypes.c_int
        trim(0)
        return
    raise RuntimeError("Allocator pressure relief is unsupported")

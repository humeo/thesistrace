"""Bounded reuse of verified immutable market projections for Strategy history."""

from collections.abc import Callable
from threading import RLock

import pyarrow as pa
from cachetools import LRUCache

from thesistrace.research_series import HISTORY_PROJECTION_CACHE_BYTES


class HistoryProjectionCache:
    def __init__(self, budget_bytes: int = HISTORY_PROJECTION_CACHE_BYTES) -> None:
        self._cache = LRUCache(
            maxsize=budget_bytes,
            getsizeof=lambda table: table.get_total_buffer_size() + 4096,
        )
        self._lock = RLock()

    @property
    def retained_bytes(self) -> int:
        with self._lock:
            return self._cache.currsize

    def read(
        self,
        object_sha256: str,
        columns: frozenset[str],
        load: Callable[[], pa.Table],
    ) -> pa.Table:
        # Content identity binds the Generation's object; candidates and decision
        # dates are filtered by the caller after retrieving this immutable table.
        key = (object_sha256, columns)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            table = load()
            if self._cache.getsizeof(table) <= self._cache.maxsize:
                self._cache[key] = table
            return table

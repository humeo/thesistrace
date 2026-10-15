"""Bounded reuse of verified immutable projections within a mounted reader."""

from collections.abc import Callable, Hashable
from threading import RLock

import pyarrow as pa
import pyarrow.compute as pc
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
        object_identity: Hashable,
        columns: frozenset[str],
        load: Callable[[], pa.Table],
    ) -> pa.Table:
        # Identity includes content and any declarations validated by the loader.
        # Candidates and decision dates are filtered after retrieving the table.
        with self._lock:
            cached = self._get(object_identity, columns)
            if cached is not None:
                return cached
            table = load()
            self._retain(object_identity, table)
            return table

    def read_instruments(self, identity, columns, instrument_ids, load) -> pa.Table:
        """Reuse complete sparse timelines, loading only securities missing fields.

        The loader returns the frozen family's entire timeline. Callers align it
        to their own dates afterwards; no future row crosses the SDK boundary.
        """
        columns = frozenset(columns)
        with self._lock:
            tables, missing = [], []
            for instrument in sorted(instrument_ids):
                table = self._get((identity, instrument), columns)
                if table is None:
                    missing.append(instrument)
                else:
                    tables.append(table)
            if missing:
                loaded = load(frozenset(missing)).sort_by([("instrument_id", "ascending")])
                groups = pc.run_end_encode(loaded["instrument_id"].combine_chunks())
                bounds, start = {}, 0
                for instrument, end in zip(groups.values.to_pylist(), groups.run_ends.to_pylist(),
                                           strict=True):
                    bounds[instrument] = (start, end)
                    start = end
                if set(bounds) - set(missing):
                    raise ValueError("Sparse history contains an out-of-scope instrument")
                for instrument in missing:
                    start, end = bounds.get(instrument, (0, 0))
                    # take copies the buffers: a single cached security must not
                    # retain the backing table for an entire market.
                    table = loaded.take(pa.array(range(start, end), type=pa.int64()))
                    self._retain((identity, instrument), table)
                    tables.append(table.select(sorted(columns)))
            return pa.concat_tables(tables)

    def _get(self, identity, columns):
        if identity not in self._cache:
            return None
        table = self._cache[identity]
        return table.select(sorted(columns)) if columns <= set(table.column_names) else None

    def _retain(self, identity, table):
        if identity in self._cache:
            previous = self._cache[identity]
            common = set(previous.column_names) & set(table.column_names)
            if previous.num_rows != table.num_rows or any(
                not previous[column].equals(table[column]) for column in common
            ):
                raise ValueError("Immutable history projections have different coordinates")
            for column in previous.column_names:
                if column not in table.column_names:
                    table = table.append_column(column, previous[column])
        if self._cache.getsizeof(table) <= self._cache.maxsize:
            self._cache[identity] = table

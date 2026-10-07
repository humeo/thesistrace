import pyarrow as pa

from thesistrace.data.history_projection import HistoryProjectionCache


def test_history_projection_budget_evicts_entries_and_never_retains_oversized_tables():
    cache = HistoryProjectionCache(budget_bytes=9000)
    for identity in ("first", "second", "third"):
        table = cache.read(identity, frozenset({"close"}), lambda: pa.table({"close": [1.0]}))
        assert table.to_pydict() == {"close": [1.0]}
        assert 0 < cache.retained_bytes <= 9000
    huge = pa.table({"close": range(2000)})
    retained = cache.retained_bytes
    assert cache.read("huge", frozenset({"close"}), lambda: huge).equals(huge)
    assert cache.retained_bytes == retained


def test_history_projection_identity_includes_content_and_selected_fields():
    cache = HistoryProjectionCache()
    close = cache.read("one", frozenset({"close"}), lambda: pa.table({"close": [1.0]}))
    open_ = cache.read("one", frozenset({"open"}), lambda: pa.table({"open": [2.0]}))
    changed = cache.read("two", frozenset({"close"}), lambda: pa.table({"close": [3.0]}))
    assert close.to_pydict() == {"close": [1.0]}
    assert open_.to_pydict() == {"open": [2.0]}
    assert changed.to_pydict() == {"close": [3.0]}

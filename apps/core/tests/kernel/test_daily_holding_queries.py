import pytest
from pydantic import ValidationError


def test_holding_query_requires_explicit_unit_and_bounds_filters():
    from thesistrace.daily_holding_queries import HoldingDetailsQuery

    query = HoldingDetailsQuery(section="daily_holdings", unit_id="run-1", limit=50)
    assert query.limit == 50
    for fields in (
        {"unit_id": ""}, {"limit": 51}, {"limit": True},
        {"start_session": "2026-02-30"},
        {"start_session": "2026-01-06", "end_session": "2026-01-05"},
        {"instrument_id": ""}, {"unsupported": True},
    ):
        with pytest.raises(ValidationError):
            HoldingDetailsQuery(section="daily_holdings", **{"unit_id": "run-1", **fields})
    with pytest.raises(ValidationError):
        HoldingDetailsQuery(section="daily_holdings")


def test_holding_pages_keep_same_session_position_and_empty_coverage():
    import json
    from types import SimpleNamespace

    from thesistrace.daily_holding_evidence import HoldingEvidencePublication
    from thesistrace.daily_holding_queries import HoldingDetailsQuery, read_holding_page
    from thesistrace.publication import JsonPayload
    from thesistrace.publication.serialization import parquet_bytes

    builder = HoldingEvidencePublication()
    rows = [{"session": "2026-01-06", "instrument_id": f"equity:{index:06d}.SH",
             "execution_shares": 100, "adjusted_units": "100", "adjusted_mark": "10",
             "market_value_cny": "1000", "weight": 0.001} for index in range(600)]
    builder.add_segment(["2026-01-05", "2026-01-06"], rows)
    payloads = {}
    for name, payload in builder.finish().items():
        if isinstance(payload, JsonPayload):
            payloads[name] = SimpleNamespace(content=json.dumps(payload.value).encode())
        else:
            payloads[name] = SimpleNamespace(
                content=parquet_bytes(payload.rows, payload.contract),
                media_type="application/vnd.apache.parquet",
                serialization={"format": "canonical-parquet",
                               "writer_contract": payload.contract.descriptor()},
            )

    reads = []

    class Publication:
        def read_selected_in_transaction(self, transaction, reference, names):
            reads.append(names)
            return SimpleNamespace(payloads={name: payloads[name] for name in names})

    publication = Publication()
    query = HoldingDetailsQuery(section="daily_holdings", unit_id="run-1", limit=50)
    coverage, first, cursor = read_holding_page(publication, None, None, query)
    _, second, _ = read_holding_page(publication, None, None, query, after=cursor)
    assert first + second == rows[:100]
    assert coverage.session_count == 2
    assert len(reads) == 4  # Each page reads its descriptor and one bounded partition.
    reads.clear()
    coverage, empty, cursor = read_holding_page(
        publication, None, None,
        query.model_copy(update={"end_session": "2026-01-05"}),
    )
    assert empty == [] and cursor is None
    assert coverage.session_count == 1
    assert reads == [frozenset({"daily_holdings"})]
    _, last, cursor = read_holding_page(
        publication, None, None,
        query.model_copy(update={"instrument_id": rows[-1]["instrument_id"]}),
    )
    assert last == rows[-1:] and cursor is None


def test_holding_no_match_and_sparse_pages_bound_storage_reads_without_losing_progress():
    import json
    from types import SimpleNamespace

    from thesistrace.daily_holding_evidence import HoldingEvidencePublication
    from thesistrace.daily_holding_queries import HoldingDetailsQuery, read_holding_page
    from thesistrace.publication import JsonPayload
    from thesistrace.publication.serialization import parquet_bytes

    sessions = [f"2026-01-{day:02d}" for day in range(1, 19)]
    rows = [{"session": session, "instrument_id": f"equity:{index:06d}.SH",
             "execution_shares": 100, "adjusted_units": "100", "adjusted_mark": "10",
             "market_value_cny": "1000", "weight": 0.001}
            for session in sessions for index in range(300)]
    builder = HoldingEvidencePublication()
    builder.add_segment(sessions, rows)
    payloads = {}
    for name, payload in builder.finish().items():
        payloads[name] = SimpleNamespace(
            content=json.dumps(payload.value).encode() if isinstance(payload, JsonPayload)
            else parquet_bytes(payload.rows, payload.contract),
            media_type="application/vnd.apache.parquet",
            serialization={} if isinstance(payload, JsonPayload) else {
                "format": "canonical-parquet", "writer_contract": payload.contract.descriptor(),
            },
        )
    reads = []

    class Publication:
        def read_selected_in_transaction(self, transaction, reference, names):
            reads.extend(name for name in names if name != "daily_holdings")
            return SimpleNamespace(payloads={name: payloads[name] for name in names})

    for instrument in ("equity:missing", "equity:000299.SH"):
        query = HoldingDetailsQuery(section="daily_holdings", unit_id="unit", limit=50,
                                    instrument_id=instrument)
        cursor, collected = None, []
        for page in range(3):
            reads.clear()
            _, items, next_cursor = read_holding_page(
                Publication(), None, None, query, after=cursor,
            )
            assert len(reads) <= 8
            collected.extend(items)
            if page == 0:
                assert next_cursor is not None
            if next_cursor is None:
                break
            assert next_cursor != cursor
            cursor = next_cursor
        else:
            pytest.fail("bounded scan did not complete")
        assert collected == [row for row in rows if row["instrument_id"] == instrument]

"""Public event filters reject unsupported or ambiguous queries before reading storage."""

import pytest
from pydantic import ValidationError

from thesistrace.strategy_evidence import (
    StrategyAdjustmentsQuery,
    StrategyFillsQuery,
    StrategyTargetsQuery,
)


def test_event_queries_bound_dates_filters_and_page_size() -> None:
    query = StrategyFillsQuery(
        section="strategy_fills",
        start_session="2026-01-05",
        end_session="2026-01-06",
        target_id="target_abc",
        instrument_id="equity:600001.SH",
        limit=50,
    )
    assert query.limit == 50
    assert query.filters()["target_id"] == "target_abc"
    assert "limit" not in query.filters()
    assert "cursor" not in query.filters()
    for fields in (
        {"limit": 51},
        {"limit": True},
        {"limit": 0},
        {"start_session": "2026-02-30"},
        {"start_session": "2026-01-06", "end_session": "2026-01-05"},
        {"instrument_id": ""},
        {"unexpected_filter": "value"},
    ):
        with pytest.raises(ValidationError):
            StrategyFillsQuery(section="strategy_fills", **fields)


def test_event_filters_are_specific_to_the_section() -> None:
    with pytest.raises(ValidationError):
        StrategyAdjustmentsQuery(section="strategy_adjustments", target_id="target_abc")
    with pytest.raises(ValidationError):
        StrategyTargetsQuery(section="strategy_targets", order_id="order_abc")
    query = StrategyTargetsQuery(section="strategy_targets", target_id="target_abc")
    assert query.filters()["target_id"] == "target_abc"


def test_large_direct_target_survives_worker_wire_publication_and_complete_record_page():
    import json

    from thesistrace.strategy_event_wire import EventMessageAssembler, strategy_event_messages
    from thesistrace.strategy_evidence import (
        StrategyEventPageRead,
        StrategyEvidenceSource,
        read_strategy_event_partition,
        strategy_event_payload,
        strategy_event_response,
        validated_event_rows,
    )

    instruments = [f"equity:{i:06d}.SH" for i in range(1000)]
    target = {
        "target_id": "target_" + "a" * 64, "decision_session": "2026-08-03",
        "contract_checksum": "b" * 64, "reason": "diversified_candidates",
        "execution": "next_research_session_open", "position_limits": {},
        "allocation": {
            "mode": "rebalance", "instrument_ids": instruments,
            "relative_weights": dict.fromkeys(instruments, "1/1000"), "exposure": 1.0,
        },
    }
    assert 32 * 1024 < len(json.dumps(target)) < 1024 * 1024
    message = {"strategy_events": {"strategy_targets": [target] * 200}}
    assembler = EventMessageAssembler()
    restored = None
    for frame in strategy_event_messages(message):
        assert len(json.dumps(frame).encode()) < 16 * 1024 * 1024
        restored = assembler.accept(frame)
    assert restored == message
    assert validated_event_rows("strategy_targets", [target]) == [target]
    from thesistrace.publication.serialization import parquet_bytes
    payload = strategy_event_payload("strategy_targets", [target])
    assert read_strategy_event_partition(
        "strategy_targets", parquet_bytes(payload.rows, payload.contract),
    ) == [target]
    page = strategy_event_response(
        StrategyTargetsQuery(section="strategy_targets"),
        StrategyEventPageRead(status="recorded", rows=[target]),
        source=StrategyEvidenceSource(kind="research_run", id="run", snapshot_id="c" * 64),
        encode_cursor=lambda value: value,
    )
    assert page.rows[0].model_dump(mode="json") == target
    assert page.next_cursor is None


def test_event_reader_skips_old_partitions_and_keeps_same_session_rows() -> None:
    from thesistrace.strategy_evidence import read_strategy_event_page

    publication, reference, rows = _publication()
    query = StrategyTargetsQuery(section="strategy_targets", limit=2)
    first = read_strategy_event_page(publication, reference, query=query)
    second = read_strategy_event_page(publication, reference, query=query, after=first.next_after)
    assert first.rows + second.rows == rows[:4]
    assert first.status == "recorded"
    assert len(publication.reads) == 4  # Descriptor and one bounded partition per page.
    publication.reads.clear()
    filtered = read_strategy_event_page(
        publication,
        reference,
        query=StrategyTargetsQuery(
            section="strategy_targets",
            target_id=rows[-1]["target_id"],
            start_session="2026-01-06",
            limit=50,
        ),
    )
    assert filtered.rows == rows[-1:]
    assert filtered.next_after is None
    assert publication.reads == [
        frozenset({"strategy_targets"}),
        frozenset({"strategy_targets.part-000001"}),
    ]


def test_event_reader_distinguishes_empty_absent_and_corrupt_evidence() -> None:
    from thesistrace.strategy_evidence import read_strategy_event_page

    publication, reference, _rows = _publication()
    empty = read_strategy_event_page(
        publication,
        reference,
        query=StrategyAdjustmentsQuery(section="strategy_adjustments"),
    )
    assert empty.status == "recorded" and empty.rows == [] and empty.next_after is None
    del publication.payloads["strategy_targets"]
    with pytest.raises(ValueError, match="incomplete"):
        read_strategy_event_page(
            publication,
            reference,
            query=StrategyTargetsQuery(section="strategy_targets"),
        )
    publication.payloads.clear()
    missing = read_strategy_event_page(
        publication,
        reference,
        query=StrategyTargetsQuery(section="strategy_targets"),
    )
    assert missing.status == "not_recorded" and missing.rows == [] and missing.next_after is None


def test_execution_constraint_queries_page_and_preserve_unrecorded_history() -> None:
    from thesistrace.strategy_evidence import (
        StrategyExecutionConstraintsQuery,
        read_strategy_event_page,
    )

    rows = [{
        "constraint_id": f"constraint_{index}", "target_id": f"target_{index:064x}",
        "decision_session": "2026-01-05", "session": "2026-01-06",
        "instrument_id": f"equity:60000{index}.SH", "side": "buy", "mode": "rebalance",
        "decision_reason": "selection",
        "reason": "below_board_lot", "intended_value": "500", "unrounded_quantity": 50,
        "legal_quantity": 0, "submitted_quantity": 0, "available_cash_cny": "500",
        "order_id": None,
    } for index in range(2)]
    publication, reference, _ = _publication(constraints=rows)
    query = StrategyExecutionConstraintsQuery(section="strategy_execution_constraints", limit=1)
    first = read_strategy_event_page(publication, reference, query=query)
    second = read_strategy_event_page(publication, reference, query=query, after=first.next_after)
    assert first.rows + second.rows == rows
    assert first.next_after is not None and second.next_after is None
    filtered = read_strategy_event_page(publication, reference, query=query.model_copy(update={
        "target_id": rows[1]["target_id"], "instrument_id": rows[1]["instrument_id"],
    }))
    assert filtered.rows == rows[1:]
    for name in list(publication.payloads):
        if name.startswith("strategy_execution_constraints"):
            del publication.payloads[name]
    missing = read_strategy_event_page(publication, reference, query=query)
    assert missing.status == "not_recorded" and missing.rows == []
    assert read_strategy_event_page(publication, reference, query=StrategyTargetsQuery(
        section="strategy_targets", limit=1,
    )).status == "recorded"
    # An absent descriptor alongside retained parts is corruption, not unrecorded history.
    publication.payloads["strategy_execution_constraints.part-000000"] = object()
    with pytest.raises(ValueError, match="incomplete"):
        read_strategy_event_page(publication, reference, query=query)


def _publication(*, constraints=None):
    import json

    from thesistrace.publication import JsonPayload, PublishedRef, VerifiedBundle, VerifiedPayload
    from thesistrace.publication.serialization import parquet_bytes
    from thesistrace.strategy_evidence import StrategyEvidencePublication, strategy_event_payload

    rows = [
        {
            "target_id": f"target_{index:064x}",
            "decision_session": session,
            "contract_checksum": "b" * 64,
            "reason": "selection",
            "execution": "next_research_session_open",
            "allocation": {
                "mode": "rebalance", "instrument_ids": ["equity:600001.SH"],
                "relative_weights": {"equity:600001.SH": "1"}, "exposure": 1.0,
            },
            "position_limits": {},
        }
        for index, session in enumerate(["2026-01-05"] * 512 + ["2026-01-06"])
    ]
    builder = StrategyEvidencePublication()
    if constraints:
        builder.add("strategy_execution_constraints", strategy_event_payload(
            "strategy_execution_constraints", constraints,
        ), constraints)
    for part in (rows[:512], rows[512:]):
        builder.add("strategy_targets", strategy_event_payload("strategy_targets", part), part)
    payloads = {}
    for name, payload in builder.finish().items():
        if isinstance(payload, JsonPayload):
            content, media, serialization = (
                json.dumps(payload.value).encode(),
                "application/json",
                {},
            )
        else:
            content, media = (
                parquet_bytes(payload.rows, payload.contract),
                "application/vnd.apache.parquet",
            )
            serialization = {
                "format": "canonical-parquet",
                "writer_contract": payload.contract.descriptor(),
            }
        payloads[name] = VerifiedPayload(
            content=content, media_type=media, serialization=serialization
        )
    reference = PublishedRef(kind="research.result", manifest_sha256="c" * 64, provenance={})

    class RecordedPublication:
        def __init__(self):
            self.payloads = payloads
            self.reads = []

        def payload_names(self, published_ref):
            assert published_ref == reference
            return frozenset(self.payloads)

        def read_selected(self, published_ref, names):
            assert published_ref == reference
            self.reads.append(names)
            return VerifiedBundle(
                kind=reference.kind,
                manifest_sha256=reference.manifest_sha256,
                provenance={},
                payloads={name: self.payloads[name] for name in names},
            )

    return RecordedPublication(), reference, rows

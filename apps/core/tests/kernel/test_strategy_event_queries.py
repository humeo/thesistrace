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


def _publication():
    import json

    from thesistrace.publication import JsonPayload, PublishedRef, VerifiedBundle, VerifiedPayload
    from thesistrace.publication.serialization import parquet_bytes
    from thesistrace.strategy_evidence import StrategyEvidencePublication, strategy_event_payload

    rows = [
        {
            "target_id": f"target_{index:064x}",
            "decision_session": session,
            "signal_session": session,
            "selected_instrument_ids": ["equity:600001.SH"],
            "relative_weights": {"equity:600001.SH": "1"},
            "eligibility_exclusions": {},
            "signal_checksum": "a" * 64,
            "contract_checksum": "b" * 64,
            "mode": "selection",
            "execution": "next_research_session_open",
            "exposure": 1.0,
        }
        for index, session in enumerate(["2026-01-05"] * 512 + ["2026-01-06"])
    ]
    builder = StrategyEvidencePublication()
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

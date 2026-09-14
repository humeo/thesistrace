from datetime import UTC, datetime

import pytest

from thesistrace.data.financial_indicator_evidence import FinancialIndicatorCheckpoint
from thesistrace.data.financial_indicator_source import (
    FINANCIAL_INDICATOR_SOURCE_FIELDS,
    FinancialIndicatorSource,
)
from thesistrace.data.source import RawSourceResponse


class Provider:
    def __init__(self, eps):
        self.eps = eps

    def query_raw(self, api_name, *, params, fields):
        if self.eps is None:
            raise AssertionError("Persisted request must not reach the provider")
        row = {
            "ts_code": params["ts_code"],
            "end_date": "20200331",
            "ann_date": "20200420",
            "eps": self.eps,
        }
        return RawSourceResponse(fields=tuple(fields), items=(tuple(row.get(f) for f in fields),))


def collect(checkpoint):
    return list(
        FinancialIndicatorSource(checkpoint).collect_report_range(
            ts_code="000001.SZ",
            start_date="20200101",
            end_date="20200630",
        )
    )


def test_completed_request_reopens_offline_but_new_operation_observes_again(tmp_path):
    first = FinancialIndicatorCheckpoint(
        tmp_path,
        collection_key="refresh-1",
        provider=Provider(2),
        clock=lambda: datetime(2020, 5, 1, tzinfo=UTC),
    )
    assert collect(first)[0].complete
    original = first.observations()
    reopened = FinancialIndicatorCheckpoint(
        tmp_path, collection_key="refresh-1", provider=Provider(None)
    )
    assert collect(reopened)[0].response.items == collect(first)[0].response.items
    assert reopened.observations() == original
    changed = FinancialIndicatorCheckpoint(
        tmp_path,
        collection_key="refresh-2",
        provider=Provider(3),
        clock=lambda: datetime(2020, 6, 1, tzinfo=UTC),
    )
    collect(changed)
    assert changed.observations()[0]["observed_at"] == "2020-06-01T00:00:00+00:00"
    assert changed.observations()[0]["items"] != original[0]["items"]


def test_interrupted_capped_request_replays_parent_then_completes_children(tmp_path):
    class SplitProvider:
        def query_raw(self, api_name, *, params, fields):
            row = {"ts_code": params["ts_code"], "end_date": params["start_date"]}
            count = (
                100
                if params["end_date"] == "20200102" and params["start_date"] == "20200101"
                else 1
            )
            return RawSourceResponse(
                fields=tuple(fields),
                items=tuple(tuple({**row, "eps": n}.get(f) for f in fields) for n in range(count)),
            )

    checkpoint = FinancialIndicatorCheckpoint(
        tmp_path, collection_key="split", provider=SplitProvider()
    )
    iterator = FinancialIndicatorSource(checkpoint).collect_report_range(
        ts_code="000001.SZ",
        start_date="20200101",
        end_date="20200102",
    )
    assert not next(iterator).complete
    iterator.close()
    assert checkpoint.observations() == ()
    from thesistrace.data.generation_store import MountedGenerationStore

    retained = MountedGenerationStore(tmp_path).indicator_checkpoint_referenced_files()
    assert len(retained) == 1  # Capped parents remain evidence for an interrupted request.
    assert retained <= MountedGenerationStore(tmp_path).inventory()
    reopened = FinancialIndicatorCheckpoint(
        tmp_path, collection_key="split", provider=SplitProvider()
    )
    shards = list(
        FinancialIndicatorSource(reopened).collect_report_range(
            ts_code="000001.SZ",
            start_date="20200101",
            end_date="20200102",
        )
    )
    assert sum(s.complete for s in shards) == 2
    assert len(reopened.observations()) == 2


def test_checkpoint_rejects_other_endpoints(tmp_path):
    checkpoint = FinancialIndicatorCheckpoint(tmp_path, collection_key="x", provider=Provider(2))
    with pytest.raises(ValueError):
        checkpoint.query_raw("income", params={}, fields=FINANCIAL_INDICATOR_SOURCE_FIELDS)


def test_completed_collection_evidence_checks_request_coverage_and_retained_rows(tmp_path):
    from thesistrace.data.financial_collection import RawFinancialBatchStore
    from thesistrace.data.financial_indicator_evidence import validate_indicator_collection_evidence
    from thesistrace.publication.serialization import canonical_json_bytes

    checkpoint = FinancialIndicatorCheckpoint(
        tmp_path, collection_key="coverage", provider=Provider(2)
    )
    collect(checkpoint)
    payload = {
        "source": "fina_indicator",
        "collection_key": "coverage",
        "instrument_id": "stock-1",
        "ts_code": "000001.SZ",
        "start_date": "20200101",
        "end_date": "20200630",
        "checked_through": "2020-06-30",
        "completed_requests": checkpoint.completed_requests(),
    }
    store = RawFinancialBatchStore(tmp_path)
    digest = store.store(canonical_json_bytes(payload))
    verified = validate_indicator_collection_evidence(store, digest)
    assert verified["instrument_id"] == "stock-1"
    for altered in (
        {**payload, "end_date": "20200701", "checked_through": "2020-07-01"},
        {**payload, "completed_requests": []},
        {**payload, "ts_code": "000002.SZ"},
        {**payload, "completed_requests": payload["completed_requests"] * 2},
    ):
        invalid = store.store(canonical_json_bytes(altered))
        with pytest.raises(ValueError):
            validate_indicator_collection_evidence(store, invalid)


def test_checkpoint_observations_are_retained_before_collection_completes(tmp_path):
    from thesistrace.data.generation_store import (
        GenerationFileRef,
        GenerationStoreError,
        MountedGenerationStore,
    )

    checkpoint = FinancialIndicatorCheckpoint(
        tmp_path, collection_key="unfinished", provider=Provider(2)
    )
    collect(checkpoint)
    digest = checkpoint.completed_requests()[0]["observation_sha256"]
    generations = MountedGenerationStore(tmp_path)
    assert generations.indicator_checkpoint_referenced_files() == frozenset({
        GenerationFileRef("raw_financial", digest),
    })
    receipt = next((tmp_path / ".operator" / "indicator-requests").glob("*/*/*.json"))
    receipt.write_bytes(b"{}")
    with pytest.raises(GenerationStoreError, match="checkpoint evidence"):
        generations.indicator_checkpoint_referenced_files()

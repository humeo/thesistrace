import hashlib

import pytest

from thesistrace.publication import PublishedRef, StagedPayload, VerifiedBundle, VerifiedPayload
from thesistrace.publication.serialization import canonical_json_bytes, parquet_bytes
from thesistrace.research_kernel.research_chunks import (
    advance_factor_state_from_daily,
    empty_factor_state,
    finalize_factor_state,
)
from thesistrace.research_run.factor_result import (
    factor_daily_payload,
    factor_evidence_publication_payloads,
)


class StoredFactor:
    def __init__(self, case):
        daily = {str(h): case["factor_evaluation"]["horizons"][str(h)]["daily"] for h in (1, 5, 20)}
        self.daily = daily
        self.payloads = {}
        parts = []
        for offset in range(0, len(daily["1"]), 5):
            rows = [row for h in (1, 5, 20) for row in daily[str(h)][offset : offset + 5]]
            payload = factor_daily_payload(rows)
            content = parquet_bytes(payload.rows, payload.contract)
            serialization = {
                "format": "canonical-parquet",
                "writer_contract": payload.contract.descriptor(),
            }
            staged = StagedPayload(
                hashlib.sha256(content).hexdigest(),
                len(content),
                "application/vnd.apache.parquet",
                serialization,
            )
            parts.append((staged, rows))
            self.payloads[f"factor_daily_observations.part-{len(parts) - 1:06d}"] = VerifiedPayload(
                staged.media_type,
                content,
                serialization,
            )
        summary = finalize_factor_state(
            advance_factor_state_from_daily(empty_factor_state(), daily),
            alpha_checksum="a" * 64,
        )
        published = factor_evidence_publication_payloads(parts, summary=summary)
        self.summary = summary
        self.payloads["factor_summary"] = VerifiedPayload(
            "application/json",
            canonical_json_bytes(summary),
            {},
        )
        for name in ("factor_daily_observations", "factor_period_statistics"):
            self.payloads[name] = VerifiedPayload(
                "application/json", canonical_json_bytes(published[name].value), {}
            )
        self.reads = []
        self.ref = PublishedRef("b" * 64, "research.result", {})

    def read_selected(self, ref, names):
        assert ref == self.ref
        self.reads.append(names)
        return VerifiedBundle(
            "research.result",
            self.ref.manifest_sha256,
            {},
            {name: self.payloads[name] for name in names},
        )


def test_factor_daily_pages_filter_before_reading_and_keep_terminal_missing_rows(
    accepted_calculation_case,
):
    from thesistrace.research_run.factor_result import read_factor_daily_page

    stored = StoredFactor(accepted_calculation_case)
    source = stored.daily["5"]
    first, cursor = read_factor_daily_page(
        stored,
        stored.ref,
        horizon=5,
        limit=2,
        start_session=source[5]["session"],
        end_session=source[9]["session"],
    )
    assert first == source[5:7]
    assert cursor == source[6]["session"]
    assert stored.reads == [
        frozenset({"factor_daily_observations"}),
        frozenset({"factor_daily_observations.part-000001"}),
    ]
    second, next_cursor = read_factor_daily_page(
        stored,
        stored.ref,
        horizon=5,
        limit=3,
        start_session=source[5]["session"],
        end_session=source[9]["session"],
        after=cursor,
    )
    assert second == source[7:10]
    assert next_cursor is None
    tail, _ = read_factor_daily_page(
        stored, stored.ref, horizon=20, limit=50, start_session=source[-1]["session"]
    )
    assert tail == stored.daily["20"][-1:]
    assert tail[0]["rank_ic"] is None


def test_factor_pages_reject_invalid_bounds_and_missing_evidence(accepted_calculation_case):
    from thesistrace.research_run.factor_result import read_factor_daily_page

    stored = StoredFactor(accepted_calculation_case)
    for changes in (
        {"limit": 51},
        {"limit": True},
        {"horizon": 2},
        {"start_session": "2026-02-30"},
        {"start_session": "2026-02-01", "end_session": "2026-01-01"},
    ):
        with pytest.raises(ValueError):
            read_factor_daily_page(stored, stored.ref, **{"horizon": 1, **changes})
    assert stored.reads == []
    del stored.payloads["factor_daily_observations"]
    with pytest.raises((ValueError, KeyError)):
        read_factor_daily_page(stored, stored.ref, horizon=1)


def test_factor_summary_reads_only_metadata_and_rejects_missing_daily_directory(
    accepted_calculation_case,
):
    from thesistrace.research_run.factor_result import (
        FACTOR_SUMMARY_PAYLOAD_NAMES,
        read_factor_summary_bundle,
    )

    stored = StoredFactor(accepted_calculation_case)
    bundle = stored.read_selected(stored.ref, FACTOR_SUMMARY_PAYLOAD_NAMES)
    assert read_factor_summary_bundle(bundle) == stored.summary
    assert stored.reads == [FACTOR_SUMMARY_PAYLOAD_NAMES]
    incomplete = VerifiedBundle(
        bundle.kind,
        bundle.manifest_sha256,
        bundle.provenance,
        {"factor_summary": bundle.payloads["factor_summary"]},
    )
    with pytest.raises(ValueError, match="missing"):
        read_factor_summary_bundle(incomplete)


def test_current_factor_bundle_accepts_required_evidence_inventory(accepted_calculation_case):
    from thesistrace.research_run.result import read_result_bundle

    stored = StoredFactor(accepted_calculation_case)
    bundle = stored.read_selected(stored.ref, frozenset(stored.payloads))
    assert (
        read_result_bundle(bundle, research_kind="factor_evaluation")["factor_summary"]
        == stored.summary
    )


def test_period_pages_select_horizon_and_calendar_bucket_without_daily_reads(
    accepted_calculation_case,
):
    from thesistrace.research_run.factor_result import read_factor_period_page

    stored = StoredFactor(accepted_calculation_case)
    first, cursor = read_factor_period_page(
        stored, stored.ref, horizon=1, granularity="month", limit=1
    )
    assert len(first) == 1
    assert first[0]["granularity"] == "month"
    assert first[0]["horizon"] == 1
    assert all(not any(".part-" in name for name in names) for names in stored.reads)
    if cursor is not None:
        second, _ = read_factor_period_page(
            stored, stored.ref, horizon=1, granularity="month", after=cursor
        )
        assert second[0]["period"] > first[0]["period"]
    with pytest.raises(ValueError):
        read_factor_period_page(stored, stored.ref, horizon=1, granularity="week")

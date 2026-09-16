from datetime import UTC, datetime

import pytest

from thesistrace.data.financial_collection import RawFinancialBatchStore
from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
from thesistrace.data.financial_indicator_evidence import FinancialIndicatorObservationStore
from thesistrace.data.financial_indicator_source import FINANCIAL_INDICATOR_SOURCE_FIELDS
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.source import RawSourceResponse
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication.serialization import canonical_json_bytes


@pytest.mark.parametrize("include_future_listings", [False, True])
@pytest.mark.parametrize("listed_from", ["1991-04-03", "2026-08-07"])
def test_generation_composes_indicator_without_changing_original_root(
    tmp_path, include_future_listings, listed_from
):
    market_store = MountedGenerationStore(tmp_path)
    prepared = datetime(2026, 8, 8, tzinfo=UTC)
    fixture = build_minimal_canonical_fixture()
    fixture["instruments"][0]["listed_from"] = listed_from
    if include_future_listings:
        for code, listed_from in (("688801.SH", "2026-09-11"), ("688837.SH", "2026-09-16")):
            fixture["instruments"].append({
                "instrument_id": f"equity:{code}", "ts_code": code,
                "asset_type": "ordinary_a_share", "exchange": "SSE", "board": "star",
                "listed_from": listed_from, "listed_to": "",
            })
    market = market_store.materialize(
        fixture,
        prepared_at=prepared,
        source_name="deterministic-test",
        source_lineage={"test": "indicator"},
    )
    raw_store = RawFinancialBatchStore(tmp_path)
    row = {"ts_code": "000001.SZ", "ann_date": "20260806", "end_date": "20260630", "roe": 15}
    receipt = FinancialIndicatorObservationStore(raw_store).save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple(row.get(field) for field in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ),
        observed_at=prepared,
    )
    evidence = raw_store.store(
        canonical_json_bytes(
            {
                "source": "fina_indicator",
                "collection_key": "generation",
                "instrument_id": "equity:000001.SZ",
                "ts_code": "000001.SZ",
                "start_date": "19900101",
                "end_date": "20260807",
                "checked_through": "2026-08-07",
                "completed_requests": [
                    {
                        "request": {
                            "api_name": "fina_indicator",
                            "params": {
                                "ts_code": "000001.SZ",
                                "start_date": "19900101",
                                "end_date": "20260807",
                            },
                            "fields": list(FINANCIAL_INDICATOR_SOURCE_FIELDS),
                        },
                        "observation_sha256": receipt,
                    }
                ],
            }
        )
    )
    candidate = FinancialIndicatorCandidateStore(tmp_path).build(
        collection_evidence_sha256s=(evidence,),
        instrument_ids={"000001.SZ": "equity:000001.SZ"},
        sessions=("2026-08-07",),
    )
    combined = market_store.compose_with_indicator_candidate(
        market.manifest_sha256, candidate, prepared_at=prepared
    )
    assert "financial.indicator.roe" in combined.field_availability
    assert market_store.inspect_root(market.manifest_sha256) == market
    assert {
        item.ts_code for item in market_store.read_historical_ordinary_a_share_identities(
            combined.manifest_sha256
        )
    } == ({"000001.SZ", "688801.SH", "688837.SH"} if include_future_listings else {"000001.SZ"})
    assert market_store.validate_generation(combined.manifest_sha256) == combined
    result = market_store.read_composite_slice(
        combined.manifest_sha256,
        sessions=["2026-08-07"],
        universe_name="top3000",
        neutralization="none",
        field_bindings={"financial.indicator.roe": "roe"},
    )
    assert result.research_data.fields["financial.indicator.roe"] == {
        ("2026-08-07", "equity:000001.SZ"): 0.15
    }
    columnar = market_store.read_columnar_slice(
        combined.manifest_sha256,
        sessions=["2026-08-07"],
        universe_name="top3000",
        neutralization="none",
        field_bindings={"financial.indicator.roe": "roe"},
        fact_instrument_ids=frozenset({"equity:000001.SZ"}),
    )
    assert (
        dict(columnar.fields["financial.indicator.roe"])
        == result.research_data.fields["financial.indicator.roe"]
    )
    import pytest

    from thesistrace.data.generation_store import GenerationStoreError

    with pytest.raises(GenerationStoreError, match="unavailable"):
        market_store.read_composite_slice(
            market.manifest_sha256,
            sessions=["2026-08-07"],
            universe_name="top3000",
            neutralization="none",
            field_bindings={"financial.indicator.roe": "roe"},
        )
    referenced = market_store.referenced_files(combined.manifest_sha256)
    from thesistrace.data.generation_store import GenerationFileRef

    assert GenerationFileRef("manifest", candidate) in referenced
    assert GenerationFileRef("raw_financial", receipt) in referenced
    assert GenerationFileRef("raw_financial", evidence) in referenced
    assert referenced <= market_store.inventory()

    from thesistrace.data.dependencies import generation_family_coverage
    from thesistrace.data.overview import describe_family_fields

    pending_candidate = FinancialIndicatorCandidateStore(tmp_path).build(
        collection_evidence_sha256s=(evidence,),
        instrument_ids={"000001.SZ": "equity:000001.SZ"},
        sessions=("2026-08-07",),
        unresolved_sources={"equity:000001.SZ": "2026-08-06"},
    )
    pending_generation = market_store.compose_with_indicator_candidate(
        combined.manifest_sha256,
        pending_candidate,
        prepared_at=prepared,
    )
    families = {item.family_id: item for item in describe_family_fields(pending_generation)}
    assert families["equity.financial_indicator"].readiness != "ready"
    assert "equity.financial_indicator" not in generation_family_coverage(pending_generation)
    assert "equity.eod_price" in generation_family_coverage(pending_generation)
    assert "equity.financial_indicator" in generation_family_coverage(combined)

    from thesistrace.data.financial_announcements import FINANCIAL_ANNOUNCEMENT_CATEGORIES

    discovery = raw_store.store(canonical_json_bytes({
        "source": "indicator-announcement-discovery",
        "instrument_ids": {"000001.SZ": "equity:000001.SZ"},
        "source_lineage_sha256": "a" * 64,
        "discovery": {
            "start_date": "2026-08-06", "end_date": "2026-08-07",
            "completed_categories": list(FINANCIAL_ANNOUNCEMENT_CATEGORIES), "gaps": [],
            "announcements": [{
                "ts_code": "000001.SZ", "report_period": "2026-06-30",
                "source_published_date": "2026-08-07",
                "category": FINANCIAL_ANNOUNCEMENT_CATEGORIES[0],
            }],
        },
    }))
    known_pending = FinancialIndicatorCandidateStore(tmp_path).build(
        collection_evidence_sha256s=(evidence,), discovery_evidence_sha256s=(discovery,),
        instrument_ids={"000001.SZ": "equity:000001.SZ"}, sessions=("2026-08-07",),
    )
    with_discovery = market_store.compose_with_indicator_candidate(
        combined.manifest_sha256, known_pending, prepared_at=prepared,
    )
    with pytest.raises(GenerationStoreError, match="discovery"):
        market_store.compose_with_indicator_candidate(
            with_discovery.manifest_sha256, candidate, prepared_at=prepared,
        )

from uuid import UUID

import pytest
from pydantic import BaseModel

from thesistrace.research_agent.pagination import InvalidPageCursor, ResearchAgentPagination


class Item(BaseModel):
    id: str
    text: str


class Page(BaseModel):
    items: list[Item]
    next_cursor: str | None


def test_authenticated_pages_cover_every_complete_utf8_record() -> None:
    pages = ResearchAgentPagination(b"a" * 32)
    items = [Item(id=str(i), text="研究" * 1000) for i in range(21)]
    seen: list[Item] = []
    cursor = None
    while True:
        page = pages.page(
            items,
            identity="researcher-a",
            query={"tool": "folders"},
            cursor=cursor,
            limit=20,
            build=lambda kept, next_cursor: Page(items=kept, next_cursor=next_cursor),
        )
        assert len(page.model_dump_json().encode("utf-8")) <= 32 * 1024
        assert page.items
        seen.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == items


def test_cursor_rejects_identity_query_version_and_tampering_and_survives_recreation() -> None:
    items = [Item(id=str(i), text="fact") for i in range(3)]
    pages = ResearchAgentPagination(b"a" * 32)
    args = dict(
        identity=str(UUID(int=1)),
        query={"tool": "catalog", "identifiers": ["close"]},
        limit=1,
        build=lambda kept, next_cursor: Page(items=kept, next_cursor=next_cursor),
    )
    cursor = pages.page(items, cursor=None, **args).next_cursor
    assert cursor
    assert ResearchAgentPagination(b"a" * 32).page(items, cursor=cursor, **args).items == items[1:2]
    for changes in ({"identity": str(UUID(int=2))}, {"query": {"tool": "folders"}}):
        with pytest.raises(InvalidPageCursor):
            pages.page(items, cursor=cursor, **(args | changes))
    with pytest.raises(InvalidPageCursor):
        pages.page(items + [Item(id="new", text="new")], cursor=cursor, **args)
    with pytest.raises(InvalidPageCursor):
        pages.page(items, cursor=cursor[:-5] + "xxxxx", **args)


def test_catalog_long_fields_are_declared_and_a_maximal_record_remains_readable() -> None:
    from pydantic import ValidationError

    from thesistrace.alpha_language.models import AlphaBuiltinCatalogEntry
    from thesistrace.research_agent.models import AlphaCatalogView

    text = "\U0001f4da" * 384
    payload = {
        "identifier": "a" * 100,
        "description": text,
        "parameters": [
            {
                "name": "\U0001f4da" * 100,
                "value_type": "window",
                "minimum": -(2**63),
                "maximum": 2**63 - 1,
            }
        ]
        * 8,
        "result_type": "numeric_series",
        "examples": [text] * 4,
        "missing_value_behavior": text,
        "numeric_behavior": text,
        "work_estimate": {"base_operations": 2**63 - 1, "per_window_operations": 2**63 - 1},
    }
    item = AlphaBuiltinCatalogEntry.model_validate(payload)
    page = ResearchAgentPagination(b"p" * 32).page(
        [item, item],
        identity="owner",
        query={"tool": "catalog"},
        cursor=None,
        limit=20,
        build=lambda kept, next_cursor: AlphaCatalogView(
            industries=[],
            generation_manifest_sha256=None,
            fields=[],
            builtins=kept,
            unknown_identifiers=["a" * 100] * 50,
            next_cursor=next_cursor,
        ),
    )
    assert page.builtins == [item]
    assert page.next_cursor
    assert len(page.model_dump_json().encode("utf-8")) <= 32 * 1024
    with pytest.raises(ValidationError):
        AlphaBuiltinCatalogEntry.model_validate(payload | {"description": text + "x"})


def test_research_notes_reject_oversize_at_single_and_batch_admission() -> None:
    from pydantic import ValidationError

    from thesistrace.research_batch.models import FactorBatchItem, StrategySweepAlpha
    from thesistrace.research_run.models import FactorEvaluationAdmissionCommand

    single = {
        "research_kind": "factor_evaluation",
        "request_id": "notes-boundary",
        "folder_id": "folder",
        "formula": "close",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "universe": "top300",
        "neutralization": "none",
    }
    for model, values in (
        (FactorEvaluationAdmissionCommand, single),
        (FactorBatchItem, {"item_key": "factor", "formula": "close"}),
        (StrategySweepAlpha, {"formula": "close"}),
    ):
        assert model.model_validate(values | {"hypothesis": "📚" * 1024}).hypothesis == "📚" * 1024
        with pytest.raises(ValidationError):
            model.model_validate(values | {"hypothesis": "📚" * 1025})


def test_complete_provenance_with_maximum_text_preserves_every_character_under_budget() -> None:
    from datetime import date

    from thesistrace.daily_track.models import (
        DailyTrackFrozenResearchInput,
        DailyTrackProvenanceResultSection,
    )
    from thesistrace.research_run.models import ProvenanceResultSection, ResearchRunAuthorableInput

    inputs = dict(
        formula="close #" + "\x01" * 4089,
        hypothesis="\x01" * 1024,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        universe="top300",
        neutralization="none",
        initial_cash_cny="10000000",
        holdings_count=100,
        selection_every_sessions=20,
        exposure_expression="1 #" + "\x01" * 4093,
        weighting="equal_weight", volatility_window=20,
    )
    from thesistrace.alpha_language import alpha_language

    assert alpha_language.diagnose(inputs["formula"]).valid
    assert alpha_language.diagnose(inputs["exposure_expression"], context="exposure").valid
    run = ProvenanceResultSection(
        run_id="run_" + "a" * 20,
        research_kind="strategy_backtest",
        schema_version="1",
        immutable_input_sha256="a" * 64,
        authoring_input=ResearchRunAuthorableInput(**inputs, research_kind="strategy_backtest"),
        data=dict(
            generation_id="generation_" + "a" * 20,
            data_through_session=date(2024, 1, 31),
            financial_research_readiness="ready",
        ),
        execution=dict(calculation_contracts={}, semantic_versions={}),
    )
    track = DailyTrackProvenanceResultSection(
        checkpoint_manifest_sha256="a" * 64,
        track_id="track_" + "a" * 20,
        origin_research_run_id=run.run_id,
        origin_result_checksum_sha256="a" * 64,
        origin_result_schema_version="1",
        immutable_input_sha256="a" * 64,
        frozen_research_input=DailyTrackFrozenResearchInput(**inputs),
        origin_data_through_session=date(2024, 1, 31),
        tracking_strategy_session=date(2024, 2, 1),
        calculation_contracts={
            "numeric_execution_contract": "float64",
            "strategy": {"volatility_window": 20, "weighting": "equal_weight",
                "initial_cash_cny": "10000000", "holdings_count": 100,
                "selection_every_sessions": 20,
            },
            "costs": {
                "commission_rate_all_in": "0.0003",
                "commission_min_cny": "5",
                "stamp_duty_sell_rate": "0.0005",
                "transfer_fee_rate": "0.00001",
            },
            "risk_free_rate": "0.02",
        },
        semantic_versions={"factor": "factor-v1", "strategy": "strategy-v2", "kernel": "kernel-v5"},
    )
    run = run.model_copy(
        update={
            "execution": run.execution.model_copy(
                update={
                    "calculation_contracts": track.calculation_contracts,
                    "semantic_versions": track.semantic_versions,
                }
            )
        }
    )
    import json

    from mcp.types import CallToolResult, JSONRPCResponse, TextContent

    from thesistrace.research_agent.mcp_server import RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES

    # Complete provenance includes both full expressions; its bound is the wire
    # response limit, not the 32KiB target used for paginated observation records.
    for result in (run, track):
        structured = result.model_dump(mode="json")
        envelope = CallToolResult(
            content=[TextContent(type="text", text=json.dumps(
                structured, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
            ))],
            structured_content=structured,
        )
        response = JSONRPCResponse(
            jsonrpc="2.0", id="provenance", result=envelope.model_dump(mode="json", by_alias=True),
        )
        wire_bytes = len(response.model_dump_json(by_alias=True).encode())
        assert wire_bytes < RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
        retained = (result.authoring_input if isinstance(result, ProvenanceResultSection)
                    else result.frozen_research_input)
        assert retained.exposure_expression == inputs["exposure_expression"]
    assert (
        run.authoring_input.hypothesis
        == track.frozen_research_input.hypothesis
        == inputs["hypothesis"]
    )


@pytest.mark.parametrize("kind", ["field", "builtin"])
def test_worst_json_escaping(kind):
    from thesistrace.alpha_language.models import AlphaBuiltinCatalogEntry, AlphaFieldCatalogEntry
    from thesistrace.research_agent.models import AlphaCatalogView

    text = "\x01" * 384
    if kind == "field":
        item = AlphaFieldCatalogEntry(
            identifier="\x01" * 100,
            field_id="\x01" * 200,
            description=text,
            unit="\x01" * 64,
            family_id="\x01" * 128,
            research_category="financial",
            display_name="\x01" * 128,
            research_purpose="\x01" * 64,
            source_unit="\x01" * 64,
            source_endpoint="\x01" * 64,
            source_column="\x01" * 100,
            source_lineage="\x01" * 256,
            reporting_scope="\x01" * 128,
            availability=text,
            report_period_selection=text,
            applicable_company_types=["\x01" * 64] * 16,
            missingness=text,
            example=text,
        )
    else:
        item = AlphaBuiltinCatalogEntry(
            identifier="\x01" * 100,
            description=text,
            parameters=[
                dict(name="\x01" * 100, value_type="window", minimum=-(2**63), maximum=2**63 - 1)
            ]
            * 8,
            result_type="numeric_series",
            examples=[text] * 4,
            missing_value_behavior=text,
            numeric_behavior=text,
            work_estimate=dict(base_operations=2**63 - 1, per_window_operations=2**63 - 1),
        )
    page = ResearchAgentPagination(b"a" * 32).page(
        [item, item],
        identity="owner",
        query={},
        cursor=None,
        limit=20,
        build=lambda kept, cursor: AlphaCatalogView(
            industries=[],
            generation_manifest_sha256=None,
            fields=kept if kind == "field" else [],
            builtins=kept if kind == "builtin" else [],
            unknown_identifiers=["a" * 100] * 50,
            next_cursor=cursor,
        ),
    )
    assert page.next_cursor
    assert len(page.model_dump_json().encode()) <= 32768

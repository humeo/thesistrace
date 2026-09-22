"""Complete stage records survive transport, storage, filtering and bounded pages."""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from thesistrace.daily_track.models import DailyTrackResultSectionInput
from thesistrace.publication.serialization import parquet_bytes
from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES
from thesistrace.research_run.models import ResearchRunResultSectionInput
from thesistrace.strategy_event_wire import EventMessageAssembler, strategy_event_messages
from thesistrace.strategy_evidence import (
    StrategyEventPageRead,
    StrategyEvidenceSource,
    StrategyFrameworkQuery,
    event_matches,
    read_strategy_event_partition,
    strategy_event_payload,
    strategy_event_response,
)


def event(index=0):
    return {
        "decision_id": f"framework_{index}", "decision_session": "2026-09-01",
        "target_id": None,
        "modules": {**BUILTIN_FRAMEWORK_MODULES, "alpha": "python:" + "a" * 64},
        "universe": {"instrument_ids": [], "updated": False, "reason": None},
        "alpha": {"kind": "signals", "signals": [], "updated": False, "reason": None,
                  "expired_signals": ["equity:600001.SH"], "removed_signals": []},
        "proposal": None, "risk_adjustment": None,
    }


def test_framework_no_update_retains_lifecycle_evidence_through_storage_and_filters():
    row = event()
    message = {"status": "completed", "strategy_events": {"strategy_framework": [row]}}
    assembler = EventMessageAssembler()
    restored = None
    for frame in strategy_event_messages(message):
        restored = assembler.accept(frame)
    assert restored == message
    payload = strategy_event_payload("strategy_framework", [row])
    assert read_strategy_event_partition(
        "strategy_framework", parquet_bytes(payload.rows, payload.contract),
    ) == [row]
    assert event_matches(row, "strategy_framework", {"instrument_id": "equity:600001.SH"})
    assert not event_matches(row, "strategy_framework", {"target_id": "some_target"})
    query = {"section": "strategy_framework", "decision_id": "framework_0"}
    assert StrategyFrameworkQuery.model_validate(query).filters()['decision_id'] == 'framework_0'
    for model, key in ((ResearchRunResultSectionInput, "run_id"),
                       (DailyTrackResultSectionInput, "track_id")):
        parsed = TypeAdapter(model).validate_python({**query, key: "id"})
        assert parsed.section == 'strategy_framework'
        with pytest.raises(ValidationError):
            TypeAdapter(model).validate_python({**query, key: "id", "order_id": "invalid"})


def test_large_framework_evidence_remains_a_complete_page_record():
    rows = [event(index) for index in range(10)]
    for row in rows:
        row["universe"]["instrument_ids"] = [f"equity:{i:06d}.SH" for i in range(3000)]
        row["alpha"]["signals"] = [{
            "instrument_id": item, "value": 1.0, "created_session": "2026-09-01",
            "created_session_number": 1, "valid_for_sessions": 252,
        } for item in row["universe"]["instrument_ids"]]
    page = strategy_event_response(
        StrategyFrameworkQuery(section="strategy_framework"),
        StrategyEventPageRead(status="recorded", rows=rows),
        source=StrategyEvidenceSource(kind="research_run", id="run", snapshot_id="c" * 64),
        encode_cursor=lambda value: value,
    )
    returned = page.model_dump(mode="json")["rows"]
    assert 1 < len(returned) < len(rows)
    assert returned == rows[:len(returned)]
    assert json.loads(page.next_cursor)[1] == returned[-1]["decision_id"]
    assert len(page.model_dump_json().encode()) < 8 * 1024 * 1024


def test_cancelled_large_portfolio_records_fit_the_result_publication_budget():
    import random
    from datetime import date, timedelta
    from fractions import Fraction

    from thesistrace.research_run.result import enforce_result_bundle_budget

    generator = random.Random(113)
    instruments = [f"equity:{i:06d}.SH" for i in range(3000)]
    rows = []
    for day in range(10):
        session = (date(2026, 9, 1) + timedelta(days=day)).isoformat()
        numerators = [generator.randrange(10**119, 10**120) for _ in instruments]
        total = sum(numerators)
        proposal = {
            "decision_session": session, "execution": "next_research_session_open",
            "contract_checksum": "c" * 64, "reason": "proposal", "position_limits": {},
            "allocation": {
                "mode": "rebalance", "instrument_ids": instruments, "exposure": 1.0,
                "relative_weights": {item: str(Fraction(value, total))
                                     for item, value in zip(instruments, numerators, strict=True)},
            },
        }
        guest_output = {key: proposal[key] for key in ("reason", "allocation", "position_limits")}
        assert len(json.dumps(guest_output).encode()) < 1024 * 1024
        rows.append({
            **event(day), "decision_session": session,
            "modules": {**BUILTIN_FRAMEWORK_MODULES,
                        "portfolio_construction": "python:" + "a" * 64,
                        "risk_management": "python:" + "b" * 64},
            "universe": {"instrument_ids": instruments, "updated": True,
                         "reason": "dataset_universe"},
            "alpha": {"kind": "formula", "values": [
                {"instrument_id": item, "value": 1.0} for item in instruments
            ]},
            "proposal": proposal,
            "risk_adjustment": {"mode": "replace", "reason": "cancel", "target": None},
        })
    payload = strategy_event_payload("strategy_framework", rows)
    content = parquet_bytes(payload.rows, payload.contract)
    assert read_strategy_event_partition("strategy_framework", content) == rows
    enforce_result_bundle_budget(
        len(content), len(rows), strategy_event_count=len(rows), strategy_target_count=0,
        strategy_framework_count=len(rows),
    )

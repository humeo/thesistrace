from copy import deepcopy
from dataclasses import replace

import pyarrow.parquet as pq
import pytest
from pydantic import TypeAdapter
from test_direct_strategy_admission import direct_spec, service_and_snapshot
from test_research_batch_execution import _batch_request, _completed_chunks

from thesistrace.research_batch.execution import execute_research_batch_messages
from thesistrace.research_kernel.direct_strategy import PythonProgram
from thesistrace.research_kernel.strategy_program_runtime import PythonStrategyRuntime
from thesistrace.research_run.execution import execute_request_chunks
from thesistrace.research_run.models import ResearchSpec
from thesistrace.research_run.service import (
    FIXED_EXECUTION,
    ResearchRunAdmissionRejected,
    _admitted_input,
)

pytestmark = pytest.mark.bounded_process


def test_python_candidate_metadata_requires_industry_at_admission():
    service, snapshot = service_and_snapshot()
    snapshot = replace(snapshot, family_coverage={
        key: value for key, value in snapshot.family_coverage.items()
        if key != "equity.industry_membership"
    })
    spec = TypeAdapter(ResearchSpec).validate_python(direct_spec())
    with pytest.raises(ResearchRunAdmissionRejected) as caught:
        _admitted_input(spec, None, snapshot, execution_memory_bytes=1536 * 1024**2)
    assert [(issue.code, issue.field) for issue in caught.value.issues] == [
        ("INDUSTRY_CALCULATION_OUTSIDE_COVERAGE", "program.source"),
    ]


def test_python_candidate_industries_and_decisions_match_alone_and_in_mixed_batch(tmp_path):
    request = _batch_request(tmp_path, kind="strategy_sweep")
    request["batch_kind"] = "independent_strategies"
    frozen = request["items"][1]["immutable_input"]
    frozen.update(formula_source=None, alpha_expression=None, neutralization=None,
                  field_bindings={"price.close.adjusted": "close"})
    frozen["strategy"] = {
        "kind": "direct", "initial_cash_cny": "10000000",
        "execution": FIXED_EXECUTION,
        "environment": PythonStrategyRuntime().identity(),
        "program": {"source": """from quantgrove import target_weights

def decide(data, account, state):
    details = {row['instrument_id']: row['industry'] for row in data.candidate_details}
    state['industries'] = details
    selected = next((stock for stock, industry in details.items() if industry), None)
    return target_weights({selected: 1.0} if selected else {})
"""},
    }
    frozen["strategy"]["program_sha256"] = PythonProgram.model_validate(
        frozen["strategy"]["program"],
    ).source_sha256
    frozen["expression_admission"]["effective_lookback"] = 0
    solo = {**deepcopy(request), "items": [deepcopy(request["items"][1])],
            "private_artifact_path": str(tmp_path / "single.artifact")}
    single_messages = list(execute_research_batch_messages(solo))
    mixed_messages = list(execute_research_batch_messages(request))
    assert not [m for m in mixed_messages if m["status"] == "item_failed"], [
        str(m) for m in mixed_messages if m["status"] == "item_failed"
    ]
    single = _completed_chunks(single_messages)
    mixed = [m["chunk"] for m in mixed_messages
             if m["status"] == "item_succeeded" and m["item_ordinal"] == 2]
    assert len(single) == len(mixed) == 1, (single_messages, mixed_messages)
    assert single == mixed
    single_rows = [row for m in single_messages if m["status"] == "item_strategy_chunk_succeeded"
                   for row in pq.read_table(m["strategy_partition"]["path"]).to_pylist()]
    mixed_rows = [row for m in mixed_messages
                  if m["status"] == "item_strategy_chunk_succeeded" and m["item_ordinal"] == 2
                  for row in pq.read_table(m["strategy_partition"]["path"]).to_pylist()]
    assert single_rows == mixed_rows
    ordinary_request = {
        "schema_version": "research-child-request-v1", "data_mount": request["data_mount"],
        "data_generation_id": request["data_generation_id"], "immutable_input": frozen,
    }
    ordinary = list(execute_request_chunks(ordinary_request, cancel_requested=lambda: False))
    chunks = [message["chunk"] for message in ordinary if message["status"] == "chunk_succeeded"]
    assert len(chunks) == 2, ordinary
    assert chunks[-1]["continuation"] == single[0]["continuation"]
    assert chunks[-1]["final_values"] == single[0]["final_values"]
    boundary = chunks[0]
    resumed = list(execute_request_chunks({
        **ordinary_request, "resume_from": {
            "completed_chunk_ordinal": boundary["ordinal"],
            **{key: boundary[key] for key in (
                "boundary_session", "completed_warmup_sessions", "completed_research_sessions",
                "continuation", "final_values",
            )},
        },
    }, cancel_requested=lambda: False))
    assert resumed[-1]["chunk"]["continuation"] == chunks[-1]["continuation"]
    assert resumed[-1]["chunk"]["final_values"] == chunks[-1]["final_values"]

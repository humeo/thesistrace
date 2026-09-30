from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256

import pytest
from test_common_input_admission import inputs
from test_common_input_result_contract import observation
from test_research_batch_execution import _batch_request

from thesistrace.publication import JsonPayload, StagedPayload, VerifiedBundle, VerifiedPayload
from thesistrace.publication.serialization import canonical_json_bytes, parquet_bytes
from thesistrace.research_run.evidence import (
    EvidenceScope,
    ResearchCheckpointIntegrityError,
    ResultEvidence,
)
from thesistrace.research_run.execution import execute_request_chunks
from thesistrace.research_run.models import ImmutableRunInput, StrategyBacktestAdmissionCommand
from thesistrace.research_run.result import ResearchResultError
from thesistrace.research_run.service import _admitted_input


class StagedEvidenceStore:
    def __init__(self):
        self.payloads = {}

    def stage(self, payload, *, staging_authority):
        if isinstance(payload, JsonPayload):
            content = canonical_json_bytes(payload.value)
            media_type = "application/json"
            serialization = {"format": "canonical-json"}
        else:
            content = parquet_bytes(payload.rows, payload.contract)
            media_type = "application/vnd.apache.parquet"
            serialization = {
                "format": "canonical-parquet",
                "writer_contract": payload.contract.descriptor(),
            }
        digest = sha256(content).hexdigest()
        self.payloads[digest] = VerifiedPayload(media_type, content, serialization)
        return StagedPayload(digest, len(content), media_type, serialization)

    def bundle(self, references):
        return VerifiedBundle(
            "research.execution-checkpoint",
            "a" * 64,
            {},
            {name: self.payloads[value["sha256"]] for name, value in references.items()},
        )


def test_evidence_scope_keeps_warmup_checkpoint_and_batch_ordinals_distinct():
    command, compiled, snapshot = inputs("close * ts_mean(universe_return(), 3)")
    immutable = _admitted_input(
        command,
        compiled,
        snapshot,
        execution_memory_bytes=1536 * 1024**2,
        max_chunk_sessions=1,
    )
    scope = EvidenceScope(immutable)
    assert [scope.checkpoint_sessions(i) for i in range(1, 5)] == [
        (),
        (),
        (),
        ("2026-08-07",),
    ]
    assert scope.batch_sessions(1) == ("2026-08-07",)
    scope.validate_common([], scope.checkpoint_sessions(1))
    scope.validate_common([observation(session="2026-08-07")], scope.batch_sessions(1))
    with pytest.raises(ResearchResultError):
        scope.validate_common([], scope.checkpoint_sessions(4))
    with pytest.raises(ResearchResultError):
        scope.batch_sessions(2)


@pytest.mark.parametrize("invalid", ("empty", "ordinal", "gap", "count"))
def test_strategy_partition_binding_owns_order_and_exact_admitted_scope(invalid):
    command, compiled, snapshot = inputs("close")
    strategy = StrategyBacktestAdmissionCommand.model_validate({
        **command.model_dump(), "research_kind": "strategy_backtest",
        "initial_cash_cny": "100000", "holdings_count": 10,
        "selection_every_sessions": 5, "weighting": "equal_weight",
        "volatility_window": 20, "exposure_expression": "1",
    })
    immutable = _admitted_input(
        strategy, compiled, snapshot, execution_memory_bytes=1536 * 1024**2,
    )
    evidence = ResultEvidence(immutable)
    payload = StagedPayload("a" * 64, 1, "application/vnd.apache.parquet", {})
    partition = (1, payload, 1, "2026-08-07", "2026-08-07")
    evidence.bind_strategy_partitions([partition])
    invalid_partitions = {
        "empty": [], "ordinal": [(2, *partition[1:])],
        "gap": [(1, payload, 1, "2026-08-06", "2026-08-07")],
        "count": [(1, payload, 2, "2026-08-07", "2026-08-07")],
    }
    with pytest.raises(ResearchResultError):
        evidence.bind_strategy_partitions(invalid_partitions[invalid])


@pytest.mark.parametrize("kind", ("factor_evaluation", "strategy_sweep"))
def test_result_evidence_reconstructs_real_bounded_checkpoints_and_rejects_changed_bytes(
    tmp_path,
    kind,
):
    request = _batch_request(
        tmp_path,
        kind=kind,
        formula="rank(ts_mean(close, 30)) * universe_advancing_fraction()",
    )
    item = request["items"][0]
    immutable = ImmutableRunInput.model_validate(item["immutable_input"])
    evidence = ResultEvidence(immutable)
    store = StagedEvidenceStore()
    with pytest.raises((ResearchCheckpointIntegrityError, ResearchResultError)):
        evidence.finish({}, batch=False)
    for message in execute_request_chunks(
        {
            "schema_version": "research-child-request-v1",
            "data_mount": request["data_mount"],
            "data_generation_id": request["data_generation_id"],
            "immutable_input": item["immutable_input"],
        },
        cancel_requested=lambda: False,
    ):
        chunk = message["chunk"]
        staged = evidence.stage_checkpoint(chunk["ordinal"], chunk, store, staging_authority=None)
        references = {
            name: asdict(value)
            for name, value in {
                **staged.events,
                **staged.holdings,
                **(
                    {"strategy_daily_observations": staged.observation}
                    if staged.observation
                    else {}
                ),
                **({"common_input_observations": staged.common} if staged.common else {}),
                **({"factor_daily_observations": staged.factor} if staged.factor else {}),
            }.items()
        }
        sessions = evidence.scope.checkpoint_sessions(chunk["ordinal"])
        row = {
            "ordinal": chunk["ordinal"],
            "strategy_event_payloads": {
                name: asdict(value) for name, value in staged.events.items()
            },
            "holding_payloads": {name: asdict(value) for name, value in staged.holdings.items()},
            "observation_payload": asdict(staged.observation) if staged.observation else None,
            "common_observation_payload": asdict(staged.common) if staged.common else None,
            "factor_observation_payload": asdict(staged.factor) if staged.factor else None,
            "observation_row_count": len(chunk["strategy_daily_observations"]),
            "observation_first_session": date.fromisoformat(sessions[0]) if sessions else None,
            "observation_last_session": date.fromisoformat(sessions[-1]) if sessions else None,
        }
        bundle = store.bundle(references)
        if references:
            name = next(iter(references))
            damaged = replace(
                bundle,
                payloads={
                    **bundle.payloads,
                    name: replace(bundle.payloads[name], content=b"damaged"),
                },
            )
            with pytest.raises(ResearchCheckpointIntegrityError):
                evidence.append_verified_checkpoint(row, damaged)
        evidence.append_verified_checkpoint(row, bundle)
    assembled = evidence.finish(chunk["final_values"], batch=False)
    assert assembled.sessions == tuple(
        day.isoformat()
        for day in immutable.execution_plan.calculation_sessions[
            immutable.execution_plan.research_session_offset :
        ]
    )
    assert "common_input_observations" in assembled.payloads
    if kind == "factor_evaluation":
        assert assembled.holding_payloads is None
        assert assembled.payloads["factor_summary"].value == chunk["final_values"]["factor_summary"]
    else:
        assert assembled.holding_payloads["daily_holdings"].value["sessions"] == list(
            assembled.sessions
        )
        assert (
            assembled.payloads["strategy_summary"].value
            == chunk["final_values"]["strategy_summary"]
        )

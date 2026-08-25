from __future__ import annotations

import gc
import weakref
from datetime import date
from types import SimpleNamespace

from thesistrace.research_run import execution
from thesistrace.research_run.models import ResearchExecutionChunk


class _ChunkPayload:
    pass


class _KernelInput:
    def __init__(self, payload: _ChunkPayload) -> None:
        self.payload = payload


class _FakeStore:
    payload_ref: weakref.ReferenceType[_ChunkPayload] | None = None

    def __init__(self, _data_mount: object) -> None:
        pass

    def open_admission(self, _generation_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            research_calendar=("2026-08-10", "2026-08-11"),
            generation=SimpleNamespace(field_availability={"close_adj": object()}),
        )

    def read_columnar_slice(self, *_args: object, **_kwargs: object) -> _ChunkPayload:
        payload = _ChunkPayload()
        type(self).payload_ref = weakref.ref(payload)
        return payload


def test_completed_chunk_releases_large_calculation_inputs_before_yield(monkeypatch) -> None:
    chunks = (
        ResearchExecutionChunk(
            ordinal=1,
            first_session=date(2026, 8, 10),
            last_session=date(2026, 8, 10),
            session_count=1,
            warmup_session_count=0,
            research_session_count=1,
        ),
        ResearchExecutionChunk(
            ordinal=2,
            first_session=date(2026, 8, 11),
            last_session=date(2026, 8, 11),
            session_count=1,
            warmup_session_count=0,
            research_session_count=1,
        ),
    )
    immutable_input = SimpleNamespace(
        execution_plan=SimpleNamespace(
            calculation_sessions=(date(2026, 8, 10), date(2026, 8, 11)),
            research_session_offset=0,
            chunks=chunks,
            chunk_session_count=1,
        ),
        alpha_admission=SimpleNamespace(effective_lookback=0),
        numeric_execution_contract="thesistrace-numeric-v1",
        research_kind="strategy_backtest",
        semantic_versions={"kernel": "test-kernel"},
        universe="top3000",
        neutralization="none",
        field_bindings={"close_adj": "close_adj"},
    )

    monkeypatch.setattr(execution, "MountedGenerationStore", _FakeStore)
    monkeypatch.setattr(
        execution,
        "_selected_research_period",
        lambda *_args, **_kwargs: ("2026-08-10", "2026-08-11"),
    )
    monkeypatch.setattr(
        execution,
        "_kernel_input",
        lambda _immutable_input, research_data, **_kwargs: _KernelInput(research_data),
    )
    monkeypatch.setattr(
        execution.AlphaFactorExecutionBinding,
        "from_run_input",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        execution,
        "prepare_columnar_forward_labels",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        execution,
        "execute_research_chunk",
        lambda **_kwargs: SimpleNamespace(
            continuation={"completed_research_session_count": 1},
            strategy_daily_observations=(),
            final_values=None,
            phase_seconds={
                "alpha_and_pending": 0.0,
                "factor": 0.0,
                "strategy": 0.0,
                "finalize": 0.0,
            },
        ),
    )
    monkeypatch.setattr(execution, "_current_process_peak_rss_bytes", lambda: 1)

    responses = execution._calculate_chunks(
        SimpleNamespace(),
        "generation-id",
        immutable_input,
        resume_from=None,
        cancel_requested=lambda: False,
    )
    first_response = next(responses)
    assert first_response["status"] == "chunk_succeeded"
    payload_ref = _FakeStore.payload_ref
    assert payload_ref is not None

    del first_response
    gc.collect()

    assert payload_ref() is None

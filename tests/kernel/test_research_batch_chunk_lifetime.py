from __future__ import annotations

import gc
import weakref
from datetime import date
from types import SimpleNamespace

from thesistrace.research_batch import execution
from thesistrace.research_batch.execution import (
    ResearchBatchExecutionItem,
    _ResearchWindow,
)


class _ChunkPayload:
    pass


def test_factor_batch_prepares_one_shared_chunk_and_releases_it_before_yield(
    monkeypatch,
) -> None:
    windows = (
        _ResearchWindow(1, ("2026-08-10", "2026-08-11"), False),
        _ResearchWindow(2, ("2026-08-12", "2026-08-13"), True),
    )
    plan = SimpleNamespace(
        chunk_session_count=2,
        research_session_count=4,
        research_session_offset=0,
        chunks=(
            SimpleNamespace(last_session=date(2026, 8, 11)),
            SimpleNamespace(last_session=date(2026, 8, 13)),
        ),
    )
    immutable = SimpleNamespace(
        execution_plan=plan,
        data_admission=SimpleNamespace(
            first_research_session=date(2026, 8, 10),
            last_research_session=date(2026, 8, 13),
        ),
        alpha_admission=SimpleNamespace(effective_lookback=3),
        numeric_execution_contract="thesistrace-numeric-v1",
        semantic_versions={"kernel": "test"},
        universe="top300",
        neutralization="none",
    )
    items = tuple(
        ResearchBatchExecutionItem(
            ordinal=ordinal,
            item_key=f"alpha-{ordinal}",
            run_id=f"run-{ordinal}",
            immutable_input=immutable,
        )
        for ordinal in (1, 2)
    )
    reads: list[tuple[str, ...]] = []
    payload_refs: list[weakref.ReferenceType[_ChunkPayload]] = []
    calculation_payload_ids: dict[int, list[int]] = {1: [], 2: []}

    def read_window(_store, *, research_sessions, **_kwargs):
        payload = _ChunkPayload()
        reads.append(tuple(research_sessions))
        payload_refs.append(weakref.ref(payload))
        return payload

    monkeypatch.setattr(execution, "_read_shared_window", read_window)
    monkeypatch.setattr(
        execution,
        "_factor_run_input",
        lambda immutable_input, research_data: SimpleNamespace(
            immutable_input=immutable_input,
            research_data=research_data,
        ),
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

    completed = {1: 0, 2: 0}

    # Give each item a distinct immutable wrapper while sharing the same frozen plan.
    items = tuple(
        ResearchBatchExecutionItem(
            ordinal=item.ordinal,
            item_key=item.item_key,
            run_id=item.run_id,
            immutable_input=SimpleNamespace(**vars(immutable)),
        )
        for item in items
    )
    immutable_by_id = {id(item.immutable_input): item.ordinal for item in items}

    def execute_distinct(*, run_input, research_sessions, final_chunk, **_kwargs):
        ordinal = immutable_by_id[id(run_input.immutable_input)]
        calculation_payload_ids[ordinal].append(id(run_input.research_data))
        completed[ordinal] += len(research_sessions)
        return SimpleNamespace(
            continuation={"completed_research_session_count": completed[ordinal]},
            final_values={"factor_summary": {}} if final_chunk else None,
        )

    monkeypatch.setattr(execution, "execute_research_chunk", execute_distinct)
    monkeypatch.setattr(execution, "_current_process_peak_rss_bytes", lambda: 1)

    responses = execution._execute_factor_batch_messages(
        items,
        generation_id="generation",
        store=object(),
        calendar=("2026-08-01", "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"),
        research_windows=windows,
        union_bindings={"close": "close_adj"},
    )

    assert next(responses)["status"] == "item_started"
    assert reads == []
    first_chunk = next(responses)
    assert first_chunk["status"] == "item_chunk_succeeded", first_chunk
    gc.collect()
    assert payload_refs[0]() is None
    assert reads == [("2026-08-10", "2026-08-11")]
    assert calculation_payload_ids[1][0] == calculation_payload_ids[2][0]

    assert next(responses)["status"] == "item_chunk_succeeded"
    gc.collect()
    assert payload_refs[1]() is None
    assert reads[-1] == ("2026-08-12", "2026-08-13")


def test_shared_window_read_is_bounded_by_chunk_and_continuation_context(
    monkeypatch,
) -> None:
    calendar = tuple(f"2026-08-{ordinal:02d}" for ordinal in range(1, 31))
    observed: dict[str, object] = {}
    source = object()

    class Store:
        def read_columnar_slice(self, generation_id, **kwargs):
            observed["generation_id"] = generation_id
            observed.update(kwargs)
            return source

    monkeypatch.setattr(
        execution,
        "_SharedFactorResearchData",
        lambda source, *, field_ids: (source, field_ids),
    )

    result = execution._read_shared_window(
        Store(),
        generation_id="generation",
        calendar=calendar,
        research_sessions=calendar[24:27],
        universe="top300",
        neutralization="none",
        field_bindings={"price.close.adjusted": "close"},
        effective_lookback=3,
        fact_instrument_ids=frozenset({"equity:held.SZ"}),
    )

    assert result == (source, ("price.close.adjusted",))
    assert observed["generation_id"] == "generation"
    assert observed["sessions"] == list(calendar[3:27])
    assert len(observed["sessions"]) == 21 + 3
    assert observed["fact_instrument_ids"] == frozenset({"equity:held.SZ"})

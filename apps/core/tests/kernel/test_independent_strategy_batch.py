from copy import deepcopy

import pyarrow.parquet as pq
import pytest
from pydantic import TypeAdapter, ValidationError
from test_research_batch_execution import _batch_request, _completed_chunks

from thesistrace.research_batch.execution import execute_research_batch_messages
from thesistrace.research_batch.models import ResearchBatchAdmissionCommand
from thesistrace.research_kernel.serialization import canonical_json_bytes


def independent_command():
    return {
        "request_id": "independent-1",
        "batch_kind": "independent_strategies",
        "start_date": "2026-06-01",
        "end_date": "2026-07-31",
        "universe": "top300",
        "strategies": [
            {
                "item_key": "formula",
                "formula": "rank(close)",
                "neutralization": "industry",
                "initial_cash_cny": "1000000",
                "holdings_count": 10,
                "selection_every_sessions": 5,
            },
            {
                "item_key": "python",
                "strategy_mode": "direct",
                "initial_cash_cny": "1000000",
                "program": {"source": "def decide(data, account, state):\n    return None\n"},
            },
        ],
    }


def test_independent_batch_accepts_each_strategy_definition_and_mode():
    command = TypeAdapter(ResearchBatchAdmissionCommand).validate_python(independent_command())
    assert [item.strategy_mode for item in command.strategies] == ["framework", "direct"]
    assert command.strategies[0].neutralization == "industry"
    assert command.strategies[0].formula == "rank(close)"


@pytest.mark.parametrize(
    "extra",
    [
        {"neutralization": "industry"},
        {"alpha": {"formula": "rank(close)"}},
        {"alphas": ["rank(close)"]},
        {"combinations": "all"},
    ],
)
def test_independent_batch_rejects_shared_alpha_and_automatic_combinations(extra):
    with pytest.raises(ValidationError):
        TypeAdapter(ResearchBatchAdmissionCommand).validate_python(
            {**independent_command(), **extra}
        )


def test_independent_batch_matches_separate_backtests_with_each_neutralization(tmp_path):
    request = _batch_request(tmp_path, kind="strategy_sweep")
    alternative = _batch_request(
        tmp_path,
        kind="strategy_sweep",
        formula="-rank(ts_mean(close, 30)) * universe_advancing_fraction()",
    )
    request["items"][1] = alternative["items"][1]
    request["items"][1]["immutable_input"]["neutralization"] = "none"
    expected = []
    expected_daily = {}
    for item in request["items"]:
        solo = {
            **deepcopy(request),
            "items": [deepcopy(item)],
            "private_artifact_path": str(tmp_path / f"solo-{item['ordinal']}.artifact"),
        }
        messages = list(execute_research_batch_messages(solo))
        expected.extend(_completed_chunks(messages))
        expected_daily[item["ordinal"]] = [
            row
            for message in messages
            if message["status"] == "item_strategy_chunk_succeeded"
            for row in pq.read_table(message["strategy_partition"]["path"]).to_pylist()
        ]
    request.update(
        batch_kind="independent_strategies",
        private_artifact_path=str(tmp_path / "independent.artifact"),
    )
    messages = list(execute_research_batch_messages(request))
    actual = [
        message["chunk"]
        for message in sorted(
            (message for message in messages if message["status"] == "item_succeeded"),
            key=lambda message: message["item_ordinal"],
        )
    ]
    assert len(actual) == len(expected) == 3, messages
    assert canonical_json_bytes(actual) == canonical_json_bytes(expected)
    for item in request["items"]:
        rows = [
            row
            for message in messages
            if message["status"] == "item_strategy_chunk_succeeded"
            and message["item_ordinal"] == item["ordinal"]
            for row in pq.read_table(message["strategy_partition"]["path"]).to_pylist()
        ]
        assert rows == expected_daily[item["ordinal"]]


def test_independent_accounts_fit_the_same_storage_read_budget_as_one_strategy(
    tmp_path, monkeypatch
):
    from thesistrace.data import MountedGenerationStore

    request = _batch_request(tmp_path, kind="strategy_sweep")
    request["batch_kind"] = "independent_strategies"
    read = MountedGenerationStore.read_columnar_slice
    reads = []

    def recorded_read(store, *args, **kwargs):
        reads.append(kwargs)
        return read(store, *args, **kwargs)

    monkeypatch.setattr(MountedGenerationStore, "read_columnar_slice", recorded_read)
    single = {**request, "items": request["items"][:1]}
    assert len(_completed_chunks(list(execute_research_batch_messages(single)))) == 1
    baseline = list(reads)
    reads.clear()
    request["private_artifact_path"] = str(tmp_path / "batch-output")
    messages = list(execute_research_batch_messages(request))
    assert len(_completed_chunks(messages)) == 3, messages
    assert len(reads) == len(baseline) == 2
    for message in messages:
        if message["status"] == "item_succeeded":
            assert (
                sum(message["child_calculation_phase_seconds"].values())
                <= message["child_chunk_seconds"]
            )


def test_independent_batch_isolates_unreadable_industry_dependency(tmp_path, monkeypatch):
    request = _batch_request(tmp_path, kind="strategy_sweep")
    request["batch_kind"] = "independent_strategies"
    request["items"][1]["immutable_input"]["neutralization"] = "none"
    request["items"][2]["immutable_input"]["neutralization"] = "none"
    read = pq.ParquetFile.iter_batches

    def unreadable_industries(parquet, *args, **kwargs):
        if "sw2021_l1" in parquet.schema_arrow.names:
            raise OSError("Industry partition is unavailable")
        return read(parquet, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", unreadable_industries)
    messages = list(execute_research_batch_messages(request))
    assert [m["item_ordinal"] for m in messages if m["status"] == "item_failed"] == [1]
    assert [m["item_ordinal"] for m in messages if m["status"] == "item_succeeded"] == [2, 3]


def test_independent_batch_isolates_unreadable_field_family(tmp_path, monkeypatch):
    from thesistrace.alpha_language import alpha_language

    request = _batch_request(tmp_path, kind="strategy_sweep", daily_fields=True)
    request["batch_kind"] = "independent_strategies"
    compiled = alpha_language.compile("rank(close)")
    for item in request["items"][1:]:
        item["immutable_input"].update(
            formula_source=compiled.source, alpha_expression=compiled.expression,
            field_bindings={"price.close.adjusted": "close"},
        )
    read = pq.ParquetFile.iter_batches

    def unreadable_valuation(parquet, *args, **kwargs):
        if "pe" in parquet.schema_arrow.names:
            raise OSError("Valuation partition is unavailable")
        return read(parquet, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", unreadable_valuation)
    messages = list(execute_research_batch_messages(request))
    assert [m["item_ordinal"] for m in messages if m["status"] == "item_failed"] == [1]
    assert [m["item_ordinal"] for m in messages if m["status"] == "item_succeeded"] == [2, 3]


@pytest.mark.parametrize("failing_phase", ["alpha", "strategy"])
def test_failed_item_releases_shared_window_before_next_read(tmp_path, monkeypatch, failing_phase):
    import weakref

    from thesistrace.data import MountedGenerationStore
    from thesistrace.research_batch import execution

    request = _batch_request(tmp_path, kind="strategy_sweep")
    request["batch_kind"] = "independent_strategies"
    # The final Alpha group fails while an earlier group still needs the next window.
    request["items"][2]["immutable_input"]["neutralization"] = "none"
    read = MountedGenerationStore.read_columnar_slice
    previous = []

    def bounded_read(store, *args, **kwargs):
        assert all(reference() is None for reference in previous), "previous window retained"
        data = read(store, *args, **kwargs)
        previous.append(weakref.ref(data))
        return data

    boundary = ("execute_alpha_factor_chunk" if failing_phase == "alpha"
                else "execute_strategy_chunk_from_alpha_factor_outcome")
    execute = getattr(execution, boundary)

    def failing_item(*args, **kwargs):
        if kwargs["run_input"].neutralization == "none":
            raise ValueError("Deterministic item failure")
        return execute(*args, **kwargs)

    monkeypatch.setattr(MountedGenerationStore, "read_columnar_slice", bounded_read)
    monkeypatch.setattr(execution, boundary, failing_item)
    messages = list(execute_research_batch_messages(request))
    assert [m["item_ordinal"] for m in messages if m["status"] == "item_failed"] == [3]
    assert [m["item_ordinal"] for m in messages if m["status"] == "item_succeeded"] == [1, 2]
    assert len(previous) == 2


def test_independent_strategy_common_history_is_not_truncated_to_the_shared_chunk(
    tmp_path, monkeypatch,
):
    from thesistrace.research_batch import execution
    from thesistrace.research_kernel.direct_strategy import program_history

    request = _batch_request(tmp_path, kind="strategy_sweep")
    request["batch_kind"] = "independent_strategies"
    execute = execution.execute_strategy_chunk_from_alpha_factor_outcome
    observed = []

    def consume_common_history(*args, **kwargs):
        data = kwargs["research_data"]
        history = program_history(data, {
            "session": data.sessions[-1], "candidates": [], "account": {"positions": []},
        })({"field_id": "common.universe_return", "days": 60, "instruments": None})
        observed.append(len(history.sessions))
        return execute(*args, **kwargs)

    monkeypatch.setattr(execution, "execute_strategy_chunk_from_alpha_factor_outcome",
                        consume_common_history)
    messages = list(execute_research_batch_messages(request))
    assert len(_completed_chunks(messages)) == 3, messages
    assert observed == [60] * 6

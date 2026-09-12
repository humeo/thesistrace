import pytest

from thesistrace.research_kernel.factor import factor_values


def test_daily_factor_group_counts_and_correlations_are_independently_checkable():
    scores = list(range(30))
    labels = [0.01 * (index + 1) for index in range(30)]
    daily = factor_values(scores, labels)
    assert daily["rank_ic"] == pytest.approx(1)
    assert daily["ic"] == pytest.approx(1)
    assert daily["quantile_counts"] == {f"q{group}": 6 for group in range(1, 6)}
    assert daily["quantile_returns"] == pytest.approx(
        {
            "q1": 0.035,
            "q2": 0.095,
            "q3": 0.155,
            "q4": 0.215,
            "q5": 0.275,
        }
    )
    assert daily["top_bottom_return"] == pytest.approx(0.24)
    reverse = factor_values(scores, list(reversed(labels)))
    assert reverse["rank_ic"] == pytest.approx(-1)


def test_tied_scores_keep_one_group_and_empty_groups_remain_missing():
    daily = factor_values([1.0] * 30, [0.1] * 30)
    assert daily["quantile_counts"] == {"q1": 0, "q2": 0, "q3": 30, "q4": 0, "q5": 0}
    assert daily["quantile_returns"] == {"q1": None, "q2": None, "q3": 0.1, "q4": None, "q5": None}
    assert daily["rank_ic"] is None
    assert daily["top_bottom_return"] is None
    assert daily["correlation_reason"] == "constant_array"


def test_small_sample_does_not_invent_group_evidence():
    daily = factor_values([1.0, 2.0], [0.1, 0.2])
    assert daily["quantile_counts"] == {f"q{group}": 0 for group in range(1, 6)}
    assert all(value is None for value in daily["quantile_returns"].values())
    assert daily["quantile_reason"] == "sample_insufficient"


def test_factor_evidence_censors_at_requested_end_even_when_later_prices_exist(
    accepted_calculation_case,
):
    from contracts import FIELD_BINDINGS, PCT_CHANGE_20

    from thesistrace.research_kernel import RunInput, run

    data = accepted_calculation_case["research_data"]
    sessions = data.sessions[20:25]
    assert data.sessions[-1] > sessions[-1]
    result = run(
        RunInput(
            research_data=data,
            alpha_expression=PCT_CHANGE_20,
            field_bindings=FIELD_BINDINGS,
            effective_alpha_lookback=20,
            universe="top300",
            neutralization="none",
            research_kind="factor_evaluation",
            strategy=None,
            research_start_session=sessions[0],
            research_end_session=sessions[-1],
        )
    )
    factor = result.artifacts_snapshot()["factor_evaluation"]
    for horizon in (1, 5, 20):
        daily = factor["horizons"][str(horizon)]["daily"]
        assert [row["session"] for row in daily] == list(sessions)
        cutoff = max(0, len(sessions) - horizon - 1)
        for row in daily[cutoff:]:
            assert row["label_status"] == "right_censored_by_research_period_end"
            assert row["label_exit_session"] is None
            assert row["sample_count"] == 0
            assert row["label_exclusions"] == {
                "right_censored_by_research_period_end": row["alpha_sample_count"],
            }
            assert row["ic"] is None
            assert row["rank_ic"] is None
        for row in daily[:cutoff]:
            assert row["label_status"] == "within_research_period"
            assert row["label_exit_session"] <= sessions[-1]


def test_daily_evidence_rejects_fabricated_sample_counts_and_censoring(accepted_calculation_case):
    from pydantic import ValidationError

    from thesistrace.research_kernel.factor_evidence import FactorDailyObservation

    row = accepted_calculation_case["factor_evaluation"]["horizons"]["1"]["daily"][0]
    FactorDailyObservation.model_validate(row)
    for changed in (
        {"sample_count": row["sample_count"] + 1},
        {"label_status": "right_censored_by_research_period_end"},
        {"quantile_counts": {"q1": 0}},
        {"ic": float("nan")},
    ):
        with pytest.raises(ValidationError):
            FactorDailyObservation.model_validate({**row, **changed})


def test_factor_daily_partition_preserves_nulls_counts_and_rejects_bad_evidence(
    accepted_calculation_case,
):
    from thesistrace.publication.serialization import parquet_bytes
    from thesistrace.research_run.factor_result import (
        factor_daily_payload,
        read_factor_daily_partition,
    )

    source = accepted_calculation_case["factor_evaluation"]["horizons"]["1"]["daily"]
    rows = [source[0], source[-1]]
    payload = factor_daily_payload(rows)
    encoded = parquet_bytes(payload.rows, contract=payload.contract)
    assert read_factor_daily_partition(encoded) == rows
    assert encoded == parquet_bytes(payload.rows, contract=payload.contract)
    with pytest.raises(ValueError):
        factor_daily_payload([rows[0], rows[0]])
    with pytest.raises(ValueError):
        factor_daily_payload([{**rows[0], "alpha_sample_count": -1}])


def test_factor_chunk_resolution_covers_matured_signals_then_censored_tail_once():
    from thesistrace.research_kernel.factor_evidence import factor_resolution_coordinates

    sessions = ("2026-01-28", "2026-01-29", "2026-01-30", "2026-02-02")
    first = factor_resolution_coordinates(sessions, before=0, after=3, final=False)
    assert first == [(1, "2026-01-28")]
    final = factor_resolution_coordinates(sessions, before=3, after=4, final=True)
    assert final == [
        (1, "2026-01-29"),
        (1, "2026-01-30"),
        (1, "2026-02-02"),
        *[(5, day) for day in sessions],
        *[(20, day) for day in sessions],
    ]
    assert len(set(first + final)) == 12
    assert factor_resolution_coordinates(sessions, before=0, after=0, final=False) == []
    with pytest.raises(ValueError):
        factor_resolution_coordinates(sessions, before=0, after=3, final=True)


def test_factor_partition_all_missing_metrics_remain_valid(accepted_calculation_case):
    from thesistrace.publication.serialization import parquet_bytes
    from thesistrace.research_run.factor_result import (
        factor_daily_payload,
        read_factor_daily_partition,
    )

    row = accepted_calculation_case["factor_evaluation"]["horizons"]["20"]["daily"][-1]
    assert row["rank_ic"] is None
    assert all(value is None for value in row["quantile_returns"].values())
    payload = factor_daily_payload([row])
    assert read_factor_daily_partition(parquet_bytes(payload.rows, payload.contract)) == [row]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_nullable_parquet_still_rejects_actual_non_finite_metrics(invalid):
    import pyarrow as pa

    from thesistrace.publication.serialization import (
        ParquetContractError,
        ParquetWriterContract,
        parquet_table_bytes,
    )

    contract = ParquetWriterContract(
        name="test-nullable-factor-metric",
        version=1,
        schema=pa.schema(
            [pa.field("session", pa.string(), nullable=False), pa.field("ic", pa.float64())]
        ),
        sort_keys=("session",),
    )
    table = pa.Table.from_pylist(
        [
            {"session": "2026-01-01", "ic": None},
            {"session": "2026-01-02", "ic": invalid},
        ],
        schema=contract.schema,
    )
    with pytest.raises(ParquetContractError, match="non-finite"):
        parquet_table_bytes(table, contract)


def test_final_factor_publication_retains_daily_evidence_and_checks_summary(
    accepted_calculation_case,
):
    from thesistrace.publication import StagedPayload
    from thesistrace.research_kernel.research_chunks import (
        advance_factor_state_from_daily,
        empty_factor_state,
        finalize_factor_state,
    )
    from thesistrace.research_run.factor_result import (
        FACTOR_DAILY_CONTRACT,
        factor_evidence_publication_payloads,
    )

    horizons = accepted_calculation_case["factor_evaluation"]["horizons"]
    daily = {str(h): horizons[str(h)]["daily"] for h in (1, 5, 20)}
    summary = finalize_factor_state(
        advance_factor_state_from_daily(empty_factor_state(), daily),
        alpha_checksum="a" * 64,
    )
    rows = [row for h in (1, 5, 20) for row in daily[str(h)]]
    staged = StagedPayload(
        sha256="b" * 64,
        byte_size=123,
        media_type="application/vnd.apache.parquet",
        serialization={
            "format": "canonical-parquet",
            "writer_contract": FACTOR_DAILY_CONTRACT.descriptor(),
        },
    )
    payloads = factor_evidence_publication_payloads([(staged, rows)], summary=summary)
    assert payloads["factor_daily_observations.part-000000"] is staged
    descriptor = payloads["factor_daily_observations"].value
    assert descriptor["partitions"][0]["row_count"] == len(rows)
    periods = payloads["factor_period_statistics"].value
    full = next(row for row in periods if row["horizon"] == 1 and row["granularity"] == "all")
    assert full["summary"] == summary["horizons"]["1"]["summary"]
    with pytest.raises(ValueError, match="summary"):
        factor_evidence_publication_payloads([(staged, rows[1:])], summary=summary)
    with pytest.raises(ValueError):
        factor_evidence_publication_payloads([], summary=summary)

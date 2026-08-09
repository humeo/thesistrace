import pytest

from thesistrace.publication import ParquetRowsPayload, VerifiedBundle, VerifiedPayload
from thesistrace.publication.serialization import canonical_json_bytes, parquet_bytes
from thesistrace.research_run.result import (
    STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
    ResearchResultError,
    enforce_result_bundle_budget,
    read_result_bundle,
    result_bundle_byte_budget,
    result_publication_payloads,
)


@pytest.mark.parametrize(
    ("session_count", "expected_budget"),
    [
        (1, 1_048_576),
        (504, 1_048_576),
        (505, 2_097_152),
        (1008, 2_097_152),
        (1009, 3_145_728),
    ],
)
def test_result_bundle_budget_accepts_the_limit_and_rejects_one_more_byte(
    session_count: int,
    expected_budget: int,
) -> None:
    assert result_bundle_byte_budget(session_count) == expected_budget
    assert enforce_result_bundle_budget(expected_budget, session_count) == expected_budget
    with pytest.raises(ResearchResultError, match="exceeds session-scaled byte budget"):
        enforce_result_bundle_budget(expected_budget + 1, session_count)


@pytest.mark.parametrize("session_count", [0, -1, True])
def test_result_bundle_budget_rejects_non_positive_session_counts(
    session_count: int,
) -> None:
    with pytest.raises(ResearchResultError, match="positive Research Period"):
        result_bundle_byte_budget(session_count)


def test_four_value_result_codec_is_deterministic_and_reopens_parquet_rows() -> None:
    result = _legal_result()
    first = result_publication_payloads(result)
    second = result_publication_payloads(result)
    first_daily = first["strategy_daily_observations"]
    second_daily = second["strategy_daily_observations"]
    assert isinstance(first_daily, ParquetRowsPayload)
    assert isinstance(second_daily, ParquetRowsPayload)
    first_bytes = parquet_bytes(first_daily.rows, first_daily.contract)
    second_bytes = parquet_bytes(second_daily.rows, second_daily.contract)
    assert first_bytes == second_bytes

    bundle = VerifiedBundle(
        kind="research.result",
        manifest_sha256="0" * 64,
        provenance={"run_id": "run-1"},
        payloads={
            "factor_summary": _json_payload(result["factor_summary"]),
            "strategy_summary": _json_payload(result["strategy_summary"]),
            "strategy_daily_observations": VerifiedPayload(
                media_type="application/vnd.apache.parquet",
                content=first_bytes,
                serialization={
                    "format": "canonical-parquet",
                    "writer_contract": STRATEGY_DAILY_OBSERVATIONS_CONTRACT.descriptor(),
                },
            ),
            "terminal_strategy_state": _json_payload(result["terminal_strategy_state"]),
        },
    )

    assert read_result_bundle(bundle) == result


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "alpha_matrix",
        "forward_labels",
        "strategy_ledger",
        "orders",
        "fills",
        "position_history",
    ],
)
def test_four_value_result_codec_rejects_nested_transient_values(
    forbidden_key: str,
) -> None:
    result = _legal_result()
    result["strategy_summary"][forbidden_key] = []

    with pytest.raises(ResearchResultError, match="transient value"):
        result_publication_payloads(result)


def _json_payload(value: object) -> VerifiedPayload:
    return VerifiedPayload(
        media_type="application/json",
        content=canonical_json_bytes(value),
        serialization={"format": "canonical-json", "version": 1},
    )


def _legal_result() -> dict[str, object]:
    return {
        "factor_summary": {"horizons": {}},
        "strategy_summary": {"metrics": {}, "benchmark": {"universe": "manual"}},
        "strategy_daily_observations": [
            {
                "session": "2024-01-02",
                "gross_nav": "1e+7",
                "net_nav": "1e+7",
                "benchmark_nav": "1",
                "net_cash": "1e+7",
                "transaction_cost_cny": "0",
                "holdings_count": 0,
                "maximum_single_name_weight": 0.0,
                "upper_limit_buy_rejections": 0,
                "lower_limit_sell_rejections": 0,
                "suspension_rejections": 0,
            }
        ],
        "terminal_strategy_state": {"session": "2024-01-02", "positions": []},
    }

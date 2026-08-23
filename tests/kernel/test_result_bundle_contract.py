import copy

import pytest

from thesistrace.publication import JsonPayload, ParquetRowsPayload, VerifiedBundle, VerifiedPayload
from thesistrace.publication.serialization import canonical_json_bytes, parquet_bytes
from thesistrace.research_run.result import (
    LAST_DAILY_OBSERVATION_KEYS,
    METRIC_STATE_KEYS,
    RESULT_DAILY_PARTITION_PREFIX,
    STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
    STRATEGY_METRIC_KEYS,
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
    first = result_publication_payloads(result, research_kind="strategy_backtest")
    second = result_publication_payloads(result, research_kind="strategy_backtest")
    part_name = f"{RESULT_DAILY_PARTITION_PREFIX}000000"
    first_daily = first[part_name]
    second_daily = second[part_name]
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
            "strategy_daily_observations": _json_payload(
                first["strategy_daily_observations"].value
            ),
            part_name: VerifiedPayload(
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

    assert read_result_bundle(bundle, research_kind="strategy_backtest") == result


def test_factor_evaluation_result_codec_requires_exactly_factor_summary() -> None:
    factor_result = {"factor_summary": _legal_result()["factor_summary"]}
    payloads = result_publication_payloads(
        factor_result,
        research_kind="factor_evaluation",
    )

    assert set(payloads) == {"factor_summary"}
    assert (
        read_result_bundle(
            _verified_bundle(payloads),
            research_kind="factor_evaluation",
        )
        == factor_result
    )

    with pytest.raises(ResearchResultError, match="only Factor Summary"):
        result_publication_payloads(
            _legal_result(),
            research_kind="factor_evaluation",
        )

    verified = _verified_bundle(payloads)
    with pytest.raises(ResearchResultError, match="only Factor Summary"):
        read_result_bundle(
            VerifiedBundle(
                kind=verified.kind,
                manifest_sha256=verified.manifest_sha256,
                provenance=verified.provenance,
                payloads={
                    **verified.payloads,
                    "strategy_summary": _json_payload({}),
                },
            ),
            research_kind="factor_evaluation",
        )


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "alpha_matrix",
        "forward_labels",
        "strategy_ledger",
        "orders",
        "fills",
        "position_history",
        "rejections",
        "rebalance_events",
        "diagnostics",
    ],
)
def test_four_value_result_codec_rejects_nested_transient_values(
    forbidden_key: str,
) -> None:
    result = _legal_result()
    result["strategy_summary"][forbidden_key] = []

    with pytest.raises(ResearchResultError, match="durable schema"):
        result_publication_payloads(result, research_kind="strategy_backtest")


@pytest.mark.parametrize(
    ("path", "hidden_value"),
    [
        (("strategy_summary", "alpha_checksum"), {"fills": []}),
        (
            ("strategy_summary", "metrics", "annualized_excess_return"),
            [{"orders": []}],
        ),
        (("strategy_daily_observations", 0, "gross_nav"), {"diagnostics": []}),
        (("terminal_strategy_state", "gross_cash"), [{"rebalance_events": []}]),
    ],
)
def test_scalar_fields_cannot_hide_nested_execution_evidence(
    path: tuple[str | int, ...],
    hidden_value: object,
) -> None:
    result = _legal_result()
    cursor: object = result
    for component in path[:-1]:
        cursor = cursor[component]
    cursor[path[-1]] = hidden_value

    with pytest.raises(ResearchResultError, match="invalid durable type"):
        result_publication_payloads(result, research_kind="strategy_backtest")


def test_daily_observations_are_partitioned_at_stable_504_session_boundaries() -> None:
    result = _legal_result()
    original = result["strategy_daily_observations"][0]
    result["strategy_daily_observations"] = [
        {**original, "session": f"{index:06d}"} for index in range(505)
    ]

    payloads = result_publication_payloads(result, research_kind="strategy_backtest")

    first = payloads[f"{RESULT_DAILY_PARTITION_PREFIX}000000"]
    second = payloads[f"{RESULT_DAILY_PARTITION_PREFIX}000001"]
    assert isinstance(first, ParquetRowsPayload)
    assert isinstance(second, ParquetRowsPayload)
    assert len(first.rows) == 504
    assert len(second.rows) == 1
    assert payloads["strategy_daily_observations"].value["partitions"] == [
        {
            "name": f"{RESULT_DAILY_PARTITION_PREFIX}000000",
            "row_count": 504,
            "first_session": "000000",
            "last_session": "000503",
        },
        {
            "name": f"{RESULT_DAILY_PARTITION_PREFIX}000001",
            "row_count": 1,
            "first_session": "000504",
            "last_session": "000504",
        },
    ]
    assert (
        read_result_bundle(
            _verified_bundle(payloads), research_kind="strategy_backtest"
        )
        == result
    )


def _json_payload(value: object) -> VerifiedPayload:
    return VerifiedPayload(
        media_type="application/json",
        content=canonical_json_bytes(value),
        serialization={"format": "canonical-json", "version": 1},
    )


def _verified_bundle(
    payloads: dict[str, JsonPayload | ParquetRowsPayload],
) -> VerifiedBundle:
    verified: dict[str, VerifiedPayload] = {}
    for name, payload in payloads.items():
        if isinstance(payload, JsonPayload):
            verified[name] = _json_payload(payload.value)
        else:
            verified[name] = VerifiedPayload(
                media_type="application/vnd.apache.parquet",
                content=parquet_bytes(payload.rows, payload.contract),
                serialization={
                    "format": "canonical-parquet",
                    "writer_contract": payload.contract.descriptor(),
                },
            )
    return VerifiedBundle(
        kind="research.result",
        manifest_sha256="0" * 64,
        provenance={"run_id": "run-partitioned"},
        payloads=verified,
    )


def _legal_result() -> dict[str, object]:
    correlation = {
        "icir": None,
        "mean": None,
        "positive_fraction": None,
        "sample_deviation": None,
        "valid_session_count": 0,
    }
    horizons = {
        str(horizon): {
            "horizon": horizon,
            "alpha_checksum": "a" * 64,
            "label_checksum": "b" * 64,
            "source_checksum": "c" * 64,
            "summary": {
                "ic": copy.deepcopy(correlation),
                "quantile_returns": {name: None for name in ("q1", "q2", "q3", "q4", "q5")},
                "rank_ic": copy.deepcopy(correlation),
                "top_bottom_return": None,
            },
            "coverage": {
                "signal_session_count": 1,
                "ic_valid_session_count": 0,
                "rank_ic_valid_session_count": 0,
                "quantile_valid_session_count": 0,
            },
        }
        for horizon in (1, 5, 20)
    }
    metrics = {name: None for name in STRATEGY_METRIC_KEYS}
    metrics.update(
        {
            "cash_ratio": {
                "ending": 1.0,
                "maximum": {"session": "2024-01-02", "value": 1.0},
                "mean": 1.0,
            },
            "holdings_count": {"ending": 0, "maximum": 0, "mean": 0.0, "minimum": 0},
            "market_rejections": {"lower_limit_sell": 0, "suspension": 0, "upper_limit_buy": 0},
            "maximum_drawdown": {
                "peak_session": "2024-01-02",
                "recovery_session": None,
                "trough_session": "2024-01-02",
                "unrecovered": False,
                "value": 0.0,
            },
            "maximum_single_name_weight": {
                "ending": 0.0,
                "period_maximum": {"session": "2024-01-02", "value": 0.0},
            },
            "transaction_costs": {"cumulative_amount": 0.0, "ratio": 0.0, "return_drag": 0.0},
            "turnover": {"annualized": None, "average_rebalance": None},
        }
    )
    last_daily = {name: 0 for name in LAST_DAILY_OBSERVATION_KEYS}
    last_daily.update(
        {
            "benchmark_nav": "1",
            "cumulative_transaction_cost": "0",
            "cycle_type": "terminal_valuation",
            "execution_rounding_residual": "0",
            "gross_cash": "1e+7",
            "gross_nav": "1e+7",
            "net_cash": "1e+7",
            "net_nav": "1e+7",
            "pre_trade_gross_nav": "1e+7",
            "pre_trade_net_nav": "1e+7",
            "rebalance": False,
            "session": "2024-01-02",
            "valuation_events": [],
        }
    )
    metric_state = {name: 0 for name in METRIC_STATE_KEYS}
    metric_state.update(
        {
            "contract": "strategy-metric-state-v1",
            "first_gross_nav": "1e+7",
            "first_net_nav": "1e+7",
            "first_benchmark_nav": "1",
            "peak_net_nav": "1e+7",
            "peak_session": "2024-01-02",
            "worst_drawdown": "0",
            "worst_peak_nav": "1e+7",
            "worst_peak_session": "2024-01-02",
            "worst_trough_session": "2024-01-02",
            "worst_recovery_session": None,
            "weight_maximum_session": "2024-01-02",
            "cash_maximum_session": "2024-01-02",
            "last_gross_nav": "1e+7",
            "last_net_nav": "1e+7",
            "last_benchmark_nav": "1",
            "last_session": "2024-01-02",
            "cumulative_cost": "0",
        }
    )
    return {
        "factor_summary": {"horizons": horizons},
        "strategy_summary": {
            "alpha_checksum": "a" * 64,
            "initial_cash_cny": "1e+7",
            "source_checksum": "c" * 64,
            "metrics": metrics,
            "benchmark": {
                "universe": "manual",
                "methodology": "selected_universe_equal_weight",
            },
        },
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
        "terminal_strategy_state": {
            "session": "2024-01-02",
            "gross_cash": "1e+7",
            "net_cash": "1e+7",
            "gross_nav": "1e+7",
            "net_nav": "1e+7",
            "benchmark_nav": "1",
            "cumulative_transaction_cost": "0",
            "positions": [],
            "rebalance_phase": {
                "origin_session": "2024-01-02",
                "report_session_count": 1,
                "rebalance_interval": 1,
                "completed_intervals": 0,
            },
            "pending_signal": None,
            "last_daily_observation": last_daily,
            "metric_state": metric_state,
        },
    }

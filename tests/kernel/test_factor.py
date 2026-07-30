import math

from thesistrace.alpha import evaluate_alpha_matrix
from thesistrace.factor import (
    build_forward_labels,
    evaluate_factor,
    factor_day,
)
from thesistrace.fixture import build_fixture


def test_forward_labels_use_next_open_timing_and_fixed_report_limits() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        canonical,
        expression="$close_adj",
        universe_name="top300",
        neutralization="none",
    )
    labels = build_forward_labels(canonical, matrix)

    assert labels["alpha_checksum"] == matrix["checksum"]
    assert set(labels["horizons"]) == {"1", "5", "20"}
    assert sum(bool(day["samples"]) for day in labels["horizons"]["1"]["sessions"]) == 502
    assert sum(bool(day["samples"]) for day in labels["horizons"]["5"]["sessions"]) == 498
    assert sum(bool(day["samples"]) for day in labels["horizons"]["20"]["sessions"]) == 483

    first = labels["horizons"]["5"]["sessions"][0]
    sample = first["samples"][0]
    signal_index = canonical["research_calendar"].index(first["session"])
    entry_session = canonical["research_calendar"][signal_index + 1]
    exit_session = canonical["research_calendar"][signal_index + 6]
    prices = {(row["session"], row["instrument_id"]): row for row in canonical["prices"]}
    expected = (
        float(prices[(exit_session, sample["instrument_id"])]["open_adj"])
        / float(prices[(entry_session, sample["instrument_id"])]["open_adj"])
        - 1
    )
    assert sample["label"] == expected
    assert first["signal_session"] == first["session"]

    last = labels["horizons"]["20"]["sessions"][-1]
    assert last["samples"] == []
    assert last["unavailable"]["right_censored"] == len(last["alpha_values"])


def test_factor_day_handles_small_samples_constants_ties_and_missing() -> None:
    small = [{"instrument_id": f"x{i}", "alpha": float(i), "label": float(i)} for i in range(29)]
    assert factor_day(small)["correlation_reason"] == "sample_insufficient"
    assert factor_day(small)["ic"] is None

    constant = [{"instrument_id": f"x{i}", "alpha": 1.0, "label": float(i)} for i in range(30)]
    assert factor_day(constant)["correlation_reason"] == "constant_array"
    assert factor_day(constant)["rank_ic"] is None

    tied = [
        {
            "instrument_id": f"x{i:02d}",
            "alpha": float(i // 6),
            "label": float(i // 6),
        }
        for i in range(30)
    ]
    result = factor_day(tied)
    assert math.isclose(result["rank_ic"], 1.0)
    assert result["quantile_returns"] == {
        "q1": 0.0,
        "q2": 1.0,
        "q3": 2.0,
        "q4": 3.0,
        "q5": 4.0,
    }
    assert result["top_bottom_return"] == 4.0


def test_labels_distinguish_terminal_delisting_from_suspended_exit() -> None:
    sessions = [f"2026-07-0{day}" for day in range(1, 6)]
    canonical = {
        "research_calendar": sessions,
        "instruments": [
            {"instrument_id": "equity:X.SH", "listed_to": "2026-07-03"},
            {"instrument_id": "equity:Y.SH", "listed_to": ""},
        ],
        "prices": [
            {
                "session": "2026-07-02",
                "instrument_id": instrument_id,
                "open_adj": "10",
            }
            for instrument_id in ("equity:X.SH", "equity:Y.SH")
        ],
        "trading_states": [
            {
                "session": "2026-07-03",
                "instrument_id": "equity:Y.SH",
                "state": "full_session_suspension",
            }
        ],
    }
    matrix = {
        "checksum": "alpha",
        "sessions": [
            {
                "session": session,
                "values": [
                    {"instrument_id": "equity:X.SH", "value": 1.0},
                    {"instrument_id": "equity:Y.SH", "value": 2.0},
                ],
            }
            for session in sessions
        ],
    }

    labels = build_forward_labels(canonical, matrix, report_sessions=5)
    first = labels["horizons"]["1"]["sessions"][0]

    assert first["samples"] == [{"instrument_id": "equity:X.SH", "alpha": 1.0, "label": -1.0}]
    assert first["unavailable"] == {"confirmed_open_unavailable": 1}


def test_complete_factor_evaluation_is_deterministic_for_all_horizons() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        canonical,
        expression="pct_change($close_adj, 20)",
        universe_name="top300",
        neutralization="none",
    )
    labels = build_forward_labels(canonical, matrix)
    evaluation = evaluate_factor(labels)
    repeated = evaluate_factor(labels)

    assert evaluation == repeated
    assert set(evaluation["horizons"]) == {"1", "5", "20"}
    for horizon in ("1", "5", "20"):
        result = evaluation["horizons"][horizon]
        assert len(result["daily"]) == 504
        assert len(result["checksum"]) == 64
        assert result["summary"]["rank_ic"]["valid_session_count"] > 0
        assert result["summary"]["ic"]["valid_session_count"] > 0

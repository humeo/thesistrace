import math

import pytest

from thesistrace.alpha import (
    AlphaValidationError,
    evaluate_alpha_matrix,
    evaluate_series,
    validate_alpha,
)
from thesistrace.fixture import build_fixture


def test_alpha_validation_accepts_only_the_closed_bounded_language() -> None:
    parsed = validate_alpha("ts_mean(pct_change($close_adj, 5), 20) + abs($volume_shares)")
    assert parsed.field_names == ("close_adj", "volume_shares")
    assert parsed.effective_lookback == 24

    cases = [
        ("$close_raw", "FIELD_NOT_AUTHORABLE"),
        ("lag($close_adj, 0)", "WINDOW_OUT_OF_RANGE"),
        ("lag($close_adj, 253)", "WINDOW_OUT_OF_RANGE"),
        ("lag($close_adj, 1 + 1)", "WINDOW_NOT_INTEGER_LITERAL"),
        ("ts_mean(pct_change($close_adj, 5), 250)", "LOOKBACK_EXCEEDS_LIMIT"),
        ("__import__('os')", "FUNCTION_NOT_ALLOWED"),
        ("$close_adj > 1", "SYNTAX_NOT_ALLOWED"),
    ]
    for expression, reason_code in cases:
        with pytest.raises(AlphaValidationError) as captured:
            validate_alpha(expression)
        assert reason_code in {issue.reason_code for issue in captured.value.issues}


def test_legacy_alpha_reports_independent_field_and_window_failures() -> None:
    with pytest.raises(AlphaValidationError) as captured:
        validate_alpha("lag($close_raw, 0)")

    assert {item.reason_code for item in captured.value.issues} == {
        "FIELD_NOT_AUTHORABLE",
        "WINDOW_OUT_OF_RANGE",
    }


def test_alpha_evaluation_uses_strict_missing_and_fixed_float64_semantics() -> None:
    values = {
        "close_adj": [1.0, 2.0, None, 4.0, 8.0],
        "volume_shares": [10.0] * 5,
    }
    assert evaluate_series("pct_change($close_adj, 1)", values) == [
        None,
        1.0,
        None,
        None,
        1.0,
    ]
    assert evaluate_series("ts_mean($close_adj, 2)", values) == [
        None,
        1.5,
        None,
        None,
        6.0,
    ]
    assert evaluate_series("ts_std($close_adj, 1)", values) == [0.0, 0.0, None, 0.0, 0.0]
    assert evaluate_series("sign(-$close_adj)", values) == [-1.0, -1.0, None, -1.0, -1.0]
    assert evaluate_series("log($close_adj - 4)", values) == [
        None,
        None,
        None,
        None,
        math.log(4.0),
    ]
    assert evaluate_series("$close_adj / ($close_adj - $close_adj)", values) == [None] * 5
    assert evaluate_series("1", {}) == [1.0]


def test_alpha_matrix_is_deterministic_and_industry_neutralization_is_group_demean() -> None:
    _, canonical = build_fixture()
    expression = "pct_change($close_adj, 1)"

    raw = evaluate_alpha_matrix(
        canonical,
        expression=expression,
        universe_name="top300",
        neutralization="none",
    )
    repeated = evaluate_alpha_matrix(
        canonical,
        expression=expression,
        universe_name="top300",
        neutralization="none",
    )
    assert raw["checksum"] == repeated["checksum"]
    assert raw["sessions"] == repeated["sessions"]
    assert raw["effective_lookback"] == 1
    assert raw["sessions"][0]["values"] == []
    assert raw["sessions"][19]["values"]
    assert [row["instrument_id"] for row in raw["sessions"][19]["values"]] == sorted(
        row["instrument_id"] for row in raw["sessions"][19]["values"]
    )

    constant = evaluate_alpha_matrix(
        canonical,
        expression="1",
        universe_name="top300",
        neutralization="none",
    )
    assert len(constant["sessions"]) == len(canonical["research_calendar"])
    assert constant["sessions"][0]["values"] == []
    assert {row["value"] for row in constant["sessions"][19]["values"]} == {1.0}

    neutralized = evaluate_alpha_matrix(
        canonical,
        expression=expression,
        universe_name="top300",
        neutralization="industry",
    )
    industry_by_instrument = {
        item["instrument_id"]: item["sw2021_l1"] for item in canonical["industry_membership"]
    }
    for session in neutralized["sessions"][30:35]:
        groups: dict[str, list[float]] = {}
        for row in session["values"]:
            groups.setdefault(industry_by_instrument[row["instrument_id"]], []).append(row["value"])
        assert all(abs(math.fsum(values)) < 1e-12 for values in groups.values())

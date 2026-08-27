from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesistrace.benchmark import (
    BenchmarkLevel,
    BenchmarkSnapshotStore,
    StrategyComparisonError,
    StrategyComparisonFacts,
    StrategyComparisonService,
    strategy_comparison_summary,
)


def _service(tmp_path: Path) -> StrategyComparisonService:
    store = BenchmarkSnapshotStore(tmp_path)
    store.publish(
        (
            BenchmarkLevel("2010-01-04", "3500"),
            BenchmarkLevel("2026-08-03", "4000"),
            BenchmarkLevel("2026-08-04", "4040"),
            BenchmarkLevel("2026-08-05", "4080"),
        ),
        published_at=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    return StrategyComparisonService(store)


def test_comparison_uses_entry_initial_cash_and_same_open_interval(tmp_path: Path) -> None:
    service = _service(tmp_path)
    facts = StrategyComparisonFacts(
        entry_session="2026-08-03",
        terminal_session="2026-08-05",
        session_interval_count=2,
        initial_cash_cny="10000000",
        terminal_net_nav="10100000",
    )

    comparison = service.comparison(
        facts,
        (
            {"session": "2026-08-03", "net_nav": "9990000"},
            {"session": "2026-08-04", "net_nav": "10000000"},
            {"session": "2026-08-05", "net_nav": "10100000"},
        ),
    )

    assert comparison["status"] == "available"
    assert comparison["entry"] == {
        "session": "2026-08-03",
        "benchmark_open_level": "4000",
        "initial_cash_cny": "10000000",
    }
    assert comparison["curves"][0] == pytest.approx(
        {
            "session": "2026-08-03",
            "net_strategy_return": -0.001,
            "benchmark_relative_return": 0.0,
            "net_excess_nav": 0.999,
            "net_excess_return": -0.001,
        }
    )
    assert comparison["curves"][-1] == pytest.approx(
        {
            "session": "2026-08-05",
            "net_strategy_return": 0.01,
            "benchmark_relative_return": 0.02,
            "net_excess_nav": 1.01 / 1.02,
            "net_excess_return": (1.01 / 1.02) - 1,
        }
    )
    metrics = comparison["metrics"]
    assert metrics["net_strategy_cumulative_return"] == pytest.approx(0.01)
    assert metrics["benchmark_cumulative_return"] == pytest.approx(0.02)
    assert metrics["annualized_excess_return"] == pytest.approx(
        (1.01 / 1.02) ** (252 / 2) - 1
    )
    assert service.annualized_excess_return(facts) == pytest.approx(
        metrics["annualized_excess_return"]
    )


def test_bounded_curves_keep_seed_entry_baseline(tmp_path: Path) -> None:
    service = _service(tmp_path)

    comparison = service.comparison(
        StrategyComparisonFacts(
            entry_session="2026-08-03",
            terminal_session="2026-08-05",
            session_interval_count=2,
            initial_cash_cny="10000000",
            terminal_net_nav="10100000",
        ),
        (
            {"session": "2026-08-04", "net_nav": "10000000"},
            {"session": "2026-08-05", "net_nav": "10100000"},
        ),
    )

    assert comparison["curves"][-1]["net_strategy_return"] == pytest.approx(0.01)
    assert comparison["curves"][-1]["benchmark_relative_return"] == pytest.approx(0.02)


def test_missing_or_damaged_snapshot_is_unavailable_without_strategy_fallback(
    tmp_path: Path,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    service = StrategyComparisonService(store)
    facts = StrategyComparisonFacts(
        entry_session="2026-08-03",
        terminal_session="2026-08-05",
        session_interval_count=2,
        initial_cash_cny="10000000",
        terminal_net_nav="10100000",
    )
    observations = (
        {"session": "2026-08-03", "net_nav": "9990000"},
        {"session": "2026-08-04", "net_nav": "10000000"},
        {"session": "2026-08-05", "net_nav": "10100000"},
    )

    assert service.annualized_excess_return(facts) is None
    assert service.comparison(facts, observations) == {
        "status": "unavailable",
        "reason": "benchmark_snapshot_unavailable",
    }

    store.path.write_text("not-json")
    assert service.annualized_excess_return(facts) is None
    assert service.comparison(facts, observations)["status"] == "unavailable"


def test_snapshot_coverage_gap_is_unavailable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    facts = StrategyComparisonFacts(
        entry_session="2026-08-03",
        terminal_session="2026-08-06",
        session_interval_count=3,
        initial_cash_cny="10000000",
        terminal_net_nav="10100000",
    )
    observations = (
        {"session": "2026-08-03", "net_nav": "9990000"},
        {"session": "2026-08-04", "net_nav": "10000000"},
        {"session": "2026-08-05", "net_nav": "10050000"},
        {"session": "2026-08-06", "net_nav": "10100000"},
    )

    assert service.annualized_excess_return(facts) is None
    assert service.comparison(facts, observations)["status"] == "unavailable"


def test_interior_snapshot_gap_is_unavailable_for_scalar_and_bounded_curve(
    tmp_path: Path,
) -> None:
    store = BenchmarkSnapshotStore(tmp_path)
    store.publish(
        (
            BenchmarkLevel("2010-01-04", "3500"),
            BenchmarkLevel("2026-08-03", "4000"),
            BenchmarkLevel("2026-08-05", "4080"),
        ),
        published_at=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    service = StrategyComparisonService(store)
    facts = StrategyComparisonFacts(
        entry_session="2026-08-03",
        terminal_session="2026-08-05",
        session_interval_count=2,
        initial_cash_cny="10000000",
        terminal_net_nav="10100000",
    )

    assert service.annualized_excess_return(facts) is None
    assert service.comparison(
        facts,
        ({"session": "2026-08-05", "net_nav": "10100000"},),
    ) == {
        "status": "unavailable",
        "reason": "benchmark_snapshot_unavailable",
    }


def test_invalid_strategy_facts_are_not_reported_as_snapshot_unavailability(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    with pytest.raises(StrategyComparisonError, match="facts are invalid"):
        service.annualized_excess_return(
            StrategyComparisonFacts(
                entry_session="2026-08-05",
                terminal_session="2026-08-03",
                session_interval_count=2,
                initial_cash_cny="10000000",
                terminal_net_nav="10100000",
            )
        )


def test_terminal_strategy_fact_must_match_the_final_observation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    facts = StrategyComparisonFacts(
        entry_session="2026-08-03",
        terminal_session="2026-08-05",
        session_interval_count=2,
        initial_cash_cny="10000000",
        terminal_net_nav="10100000",
    )

    with pytest.raises(StrategyComparisonError, match="observations are invalid"):
        service.comparison(
            facts,
            (
                {"session": "2026-08-03", "net_nav": "9990000"},
                {"session": "2026-08-05", "net_nav": "10000000"},
            ),
        )


def test_strategy_comparison_summary_removes_only_the_unbounded_curves(
    tmp_path: Path,
) -> None:
    comparison = _service(tmp_path).comparison(
        StrategyComparisonFacts(
            entry_session="2026-08-03",
            terminal_session="2026-08-05",
            session_interval_count=2,
            initial_cash_cny="10000000",
            terminal_net_nav="10100000",
        ),
        (
            {"session": "2026-08-03", "net_nav": "9990000"},
            {"session": "2026-08-04", "net_nav": "10000000"},
            {"session": "2026-08-05", "net_nav": "10100000"},
        ),
    )

    summary = strategy_comparison_summary(comparison)

    assert set(summary) == {"status", "benchmark", "entry", "terminal", "metrics"}
    assert "curves" not in summary


def test_strategy_comparison_summary_preserves_unavailable_contract() -> None:
    assert strategy_comparison_summary(
        {
            "status": "unavailable",
            "reason": "benchmark_snapshot_unavailable",
        }
    ) == {
        "status": "unavailable",
        "reason": "benchmark_snapshot_unavailable",
    }

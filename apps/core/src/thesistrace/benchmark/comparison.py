from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from thesistrace.benchmark.snapshot import (
    BENCHMARK_COORDINATE,
    BENCHMARK_DISPLAY_NAME,
    BENCHMARK_ID,
    BENCHMARK_KIND,
    BENCHMARK_TS_CODE,
    BenchmarkSnapshot,
    BenchmarkSnapshotError,
    BenchmarkSnapshotStore,
)

BENCHMARK_SNAPSHOT_UNAVAILABLE_REASON = "benchmark_snapshot_unavailable"


class StrategyComparisonError(ValueError):
    pass


class _BenchmarkCoverageUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class StrategyComparisonFacts:
    entry_session: str
    terminal_session: str
    session_interval_count: int
    initial_cash_cny: str
    terminal_net_nav: str


class StrategyComparisonService:
    def __init__(self, store: BenchmarkSnapshotStore) -> None:
        self._store = store

    def annualized_excess_return(
        self,
        facts: StrategyComparisonFacts,
    ) -> float | None:
        validated = _validate_facts(facts)
        snapshot = self._read_snapshot()
        if snapshot is None:
            return None
        try:
            values = _comparison_values(snapshot, validated)
        except _BenchmarkCoverageUnavailable:
            return None
        return values["annualized_excess_return"]

    def comparison(
        self,
        facts: StrategyComparisonFacts,
        observations: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        validated = _validate_facts(facts)
        strategy_observations = _validate_observations(
            observations,
            facts=validated,
        )
        snapshot = self._read_snapshot()
        if snapshot is None:
            return _unavailable()
        try:
            values = _comparison_values(snapshot, validated)
            level_by_session = snapshot.level_by_session
            entry_level = _required_level(level_by_session, validated.entry_session)
            curves = []
            for session, net_nav in strategy_observations:
                if session < validated.entry_session:
                    continue
                benchmark_level = _required_level(level_by_session, session)
                strategy_growth = net_nav / validated.initial_cash
                benchmark_growth = benchmark_level / entry_level
                net_excess_nav = strategy_growth / benchmark_growth
                curves.append(
                    {
                        "session": session,
                        "net_strategy_return": float(strategy_growth - 1),
                        "benchmark_relative_return": float(benchmark_growth - 1),
                        "net_excess_nav": float(net_excess_nav),
                        "net_excess_return": float(net_excess_nav - 1),
                    }
                )
            if not curves:
                raise StrategyComparisonError("Strategy comparison has no Entry observations")
        except _BenchmarkCoverageUnavailable:
            return _unavailable()
        return {
            "status": "available",
            "benchmark": {
                "id": BENCHMARK_ID,
                "display_name": BENCHMARK_DISPLAY_NAME,
                "ts_code": BENCHMARK_TS_CODE,
                "kind": BENCHMARK_KIND,
                "coordinate": BENCHMARK_COORDINATE,
                "snapshot_sha256": snapshot.sha256,
                "coverage": {
                    "start_session": snapshot.coverage_start_session,
                    "end_session": snapshot.coverage_end_session,
                },
                "published_at": snapshot.published_at,
            },
            "entry": {
                "session": validated.entry_session,
                "benchmark_open_level": str(entry_level),
                "initial_cash_cny": str(validated.initial_cash),
            },
            "terminal": {
                "session": validated.terminal_session,
                "benchmark_open_level": str(
                    _required_level(level_by_session, validated.terminal_session)
                ),
                "net_nav": str(validated.terminal_net_nav),
            },
            "metrics": values,
            "curves": curves,
        }

    def _read_snapshot(self) -> BenchmarkSnapshot | None:
        try:
            return self._store.read()
        except (BenchmarkSnapshotError, OSError):
            return None


@dataclass(frozen=True)
class _ValidatedFacts:
    entry_session: str
    terminal_session: str
    session_interval_count: int
    initial_cash: Decimal
    terminal_net_nav: Decimal


def _validate_facts(facts: StrategyComparisonFacts) -> _ValidatedFacts:
    try:
        entry = date.fromisoformat(facts.entry_session).isoformat()
        terminal = date.fromisoformat(facts.terminal_session).isoformat()
        initial_cash = Decimal(facts.initial_cash_cny)
        terminal_net_nav = Decimal(facts.terminal_net_nav)
    except (InvalidOperation, ValueError) as error:
        raise StrategyComparisonError("Strategy comparison facts are invalid") from error
    if (
        entry != facts.entry_session
        or terminal != facts.terminal_session
        or terminal < entry
        or isinstance(facts.session_interval_count, bool)
        or not isinstance(facts.session_interval_count, int)
        or facts.session_interval_count < 0
        or not initial_cash.is_finite()
        or initial_cash <= 0
        or not terminal_net_nav.is_finite()
        or terminal_net_nav <= 0
    ):
        raise StrategyComparisonError("Strategy comparison facts are invalid")
    return _ValidatedFacts(
        entry_session=entry,
        terminal_session=terminal,
        session_interval_count=facts.session_interval_count,
        initial_cash=initial_cash,
        terminal_net_nav=terminal_net_nav,
    )


def _validate_observations(
    observations: Sequence[Mapping[str, object]],
    *,
    facts: _ValidatedFacts,
) -> tuple[tuple[str, Decimal], ...]:
    validated: list[tuple[str, Decimal]] = []
    try:
        for value in observations:
            session = date.fromisoformat(str(value["session"])).isoformat()
            net_nav = Decimal(str(value["net_nav"]))
            if (
                session != value["session"]
                or not net_nav.is_finite()
                or net_nav <= 0
                or session > facts.terminal_session
            ):
                raise StrategyComparisonError("Strategy observations are invalid")
            validated.append((session, net_nav))
    except (InvalidOperation, KeyError, ValueError) as error:
        if isinstance(error, StrategyComparisonError):
            raise
        raise StrategyComparisonError("Strategy observations are invalid") from error
    sessions = [session for session, _net_nav in validated]
    entry_index = sessions.index(facts.entry_session) if facts.entry_session in sessions else None
    if (
        not sessions
        or sessions != sorted(set(sessions))
        or sessions[-1] != facts.terminal_session
        or validated[-1][1] != facts.terminal_net_nav
        or (
            entry_index is not None
            and len(sessions) - entry_index - 1 != facts.session_interval_count
        )
        or not any(session >= facts.entry_session for session in sessions)
    ):
        raise StrategyComparisonError("Strategy observations are invalid")
    return tuple(validated)


def _comparison_values(
    snapshot: BenchmarkSnapshot,
    facts: _ValidatedFacts,
) -> dict[str, float | None]:
    level_by_session = snapshot.level_by_session
    entry_level = _required_level(level_by_session, facts.entry_session)
    terminal_level = _required_level(level_by_session, facts.terminal_session)
    sessions = [level.session for level in snapshot.levels]
    try:
        intervals = sessions.index(facts.terminal_session) - sessions.index(facts.entry_session)
    except ValueError as error:
        raise _BenchmarkCoverageUnavailable from error
    if intervals < 0 or intervals != facts.session_interval_count:
        raise _BenchmarkCoverageUnavailable
    strategy_growth = facts.terminal_net_nav / facts.initial_cash
    benchmark_growth = terminal_level / entry_level
    excess_growth = strategy_growth / benchmark_growth
    return {
        "net_strategy_cumulative_return": float(strategy_growth - 1),
        "benchmark_cumulative_return": float(benchmark_growth - 1),
        "net_strategy_cagr": _annualized(strategy_growth, intervals),
        "benchmark_cagr": _annualized(benchmark_growth, intervals),
        "annualized_excess_return": _annualized(excess_growth, intervals),
    }


def _required_level(levels: Mapping[str, str], session: str) -> Decimal:
    value = levels.get(session)
    if value is None:
        raise _BenchmarkCoverageUnavailable
    try:
        level = Decimal(value)
    except InvalidOperation as error:
        raise _BenchmarkCoverageUnavailable from error
    if not level.is_finite() or level <= 0:
        raise _BenchmarkCoverageUnavailable
    return level


def _annualized(growth: Decimal, intervals: int) -> float | None:
    if intervals == 0:
        return None
    value = math.pow(float(growth), 252 / intervals) - 1
    if not math.isfinite(value):
        raise StrategyComparisonError("Strategy comparison annualization is non-finite")
    return value


def _unavailable() -> dict[str, str]:
    return {
        "status": "unavailable",
        "reason": BENCHMARK_SNAPSHOT_UNAVAILABLE_REASON,
    }


def strategy_comparison_summary(
    comparison: Mapping[str, object],
) -> dict[str, object]:
    status = comparison.get("status")
    if status == "unavailable":
        if comparison.get("reason") != BENCHMARK_SNAPSHOT_UNAVAILABLE_REASON:
            raise StrategyComparisonError("Strategy comparison unavailable reason is invalid")
        return _unavailable()
    if status != "available":
        raise StrategyComparisonError("Strategy comparison status is invalid")
    required = ("benchmark", "entry", "terminal", "metrics")
    if any(not isinstance(comparison.get(name), Mapping) for name in required):
        raise StrategyComparisonError("Strategy comparison summary is invalid")
    return {
        "status": "available",
        **{name: dict(comparison[name]) for name in required},
    }


__all__ = (
    "BENCHMARK_SNAPSHOT_UNAVAILABLE_REASON",
    "StrategyComparisonError",
    "StrategyComparisonFacts",
    "StrategyComparisonService",
    "strategy_comparison_summary",
)

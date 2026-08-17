from datetime import date, timedelta

from thesistrace.daily_track.planning import plan_tracking_advance


def _sessions(count: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(count))


def test_tracking_target_freezes_the_largest_safe_range_capped_at_63() -> None:
    plan = plan_tracking_advance(
        unpublished_sessions=_sessions(70),
        formula_work=1,
        node_count=1,
        field_count=1,
        maximum_universe_cardinality=1,
        effective_lookback=0,
        execution_memory_bytes=1536 * 1024**2,
    )

    assert plan.target_sessions == _sessions(63)
    assert plan.capacity_blocked is False
    assert plan.time_target_exceeded is False


def test_tracking_target_uses_one_session_when_only_the_time_target_is_exceeded() -> None:
    plan = plan_tracking_advance(
        unpublished_sessions=_sessions(3),
        formula_work=20_000_000,
        node_count=1,
        field_count=1,
        maximum_universe_cardinality=1,
        effective_lookback=0,
        execution_memory_bytes=1536 * 1024**2,
    )

    assert plan.target_sessions == _sessions(1)
    assert plan.capacity_blocked is False
    assert plan.time_target_exceeded is True


def test_tracking_target_freezes_one_blocked_session_when_memory_cannot_fit() -> None:
    plan = plan_tracking_advance(
        unpublished_sessions=_sessions(3),
        formula_work=1,
        node_count=1,
        field_count=1,
        maximum_universe_cardinality=3000,
        effective_lookback=252,
        execution_memory_bytes=1,
    )

    assert plan.target_sessions == _sessions(1)
    assert plan.capacity_blocked is True
    assert plan.time_target_exceeded is False

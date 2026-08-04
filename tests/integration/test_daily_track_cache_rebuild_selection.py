from thesistrace.daily_track.service import _select_rebuild_steps


def test_multi_session_release_is_trimmed_to_525_actual_sessions() -> None:
    calendar = [_session(index) for index in range(601)]
    rows = [
        {
            "target_release_id": "release-1",
            "predecessor_release_id": "seed",
            "strategy_session": calendar[-1],
        }
    ]

    steps, use_seed = _select_rebuild_steps(
        rows,
        head_calendar=calendar,
        seed_release_id="seed",
        seed_session=calendar[0],
    )

    assert use_seed is False
    assert len(steps) == 1
    assert steps[0][1] == calendar[-525:]


def test_long_chain_selects_525_sessions_without_origin_replay() -> None:
    calendar = [_session(index) for index in range(527)]
    rows = [
        {
            "target_release_id": f"release-{index}",
            "predecessor_release_id": "seed" if index == 1 else f"release-{index - 1}",
            "strategy_session": calendar[index],
        }
        for index in range(526, 0, -1)
    ]

    steps, use_seed = _select_rebuild_steps(
        rows,
        head_calendar=calendar,
        seed_release_id="seed",
        seed_session=calendar[0],
    )

    assert use_seed is False
    assert len(steps) == 525
    assert [session for _row, sessions in steps for session in sessions] == calendar[-525:]


def test_short_chain_starts_from_fixed_seed_continuation() -> None:
    calendar = [_session(index) for index in range(5)]
    rows = [
        {
            "target_release_id": "release-2",
            "predecessor_release_id": "release-1",
            "strategy_session": calendar[4],
        },
        {
            "target_release_id": "release-1",
            "predecessor_release_id": "seed",
            "strategy_session": calendar[2],
        },
    ]

    steps, use_seed = _select_rebuild_steps(
        rows,
        head_calendar=calendar,
        seed_release_id="seed",
        seed_session=calendar[0],
    )

    assert use_seed is True
    assert [session for _row, sessions in steps for session in sessions] == calendar[1:]


def _session(index: int) -> str:
    return f"session-{index:04d}"

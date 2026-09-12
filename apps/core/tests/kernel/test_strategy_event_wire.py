import json

import pytest

from thesistrace.strategy_event_wire import EventMessageAssembler, strategy_event_messages


def test_event_transport_keeps_large_segments_in_bounded_frames():
    # A complete segment can exceed the old 16 MiB single-line contract.
    events = {"strategy_fills": [{"fill_id": str(i), "evidence": "x" * 1024} for i in range(17000)]}
    message = {"status": "chunk_succeeded", "chunk": {"ordinal": 1, "strategy_events": events}}
    assembler = EventMessageAssembler()
    largest_frame = 0
    result = None
    for frame in strategy_event_messages(message):
        wire = json.dumps(frame).encode()
        largest_frame = max(largest_frame, len(wire))
        result = assembler.accept(json.loads(wire))
    assert largest_frame < 1024 * 1024
    assert result == message
    assert message["chunk"]["strategy_events"] == events


def test_event_transport_requires_order_and_complete_counts():
    frames = list(
        strategy_event_messages(
            {
                "strategy_events": {
                    "strategy_orders": [{"order_id": "one"}],
                }
            }
        )
    )
    assembler = EventMessageAssembler()
    assert assembler.accept(frames[0]) is None
    with pytest.raises(ValueError, match="order"):
        assembler.accept(frames[0])
    with pytest.raises(ValueError, match="count"):
        EventMessageAssembler().accept(frames[-1])
    with pytest.raises(ValueError, match="incomplete"):
        assembler.accept({"status": "failed"})


def test_event_transport_preserves_empty_and_non_event_messages():
    for message in (
        {"status": "ready"},
        {"strategy_events": {}},
        {"strategy_events": {"strategy_targets": []}},
    ):
        assembler = EventMessageAssembler()
        result = None
        for frame in strategy_event_messages(message):
            result = assembler.accept(frame)
        assert result == message


def test_supervised_child_transfers_an_oversize_segment_with_frame_acknowledgments():
    import subprocess
    import sys
    from time import monotonic

    from thesistrace.research_run.supervised_child import SupervisedChildTransport

    script = """
import json, sys
from thesistrace.strategy_event_wire import print_strategy_event_message
rows = [{"fill_id": str(i), "evidence": "x" * 1024} for i in range(17000)]
print_strategy_event_message(
    {"status": "succeeded", "strategy_events": {"strategy_fills": rows}},
    acknowledge=lambda: json.loads(sys.stdin.readline()),
)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    transport = SupervisedChildTransport(child, None)
    deadline = monotonic() + 10
    try:
        message = transport.read(cancel_requested=lambda: monotonic() > deadline)
        assert child.wait(timeout=5) == 0
        rows = message["strategy_events"]["strategy_fills"]
        assert len(rows) == 17000
        assert rows[0] == {"fill_id": "0", "evidence": "x" * 1024}
        assert rows[-1] == {"fill_id": "16999", "evidence": "x" * 1024}
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


def test_tracking_reader_consumes_coalesced_progress_and_result_without_waiting_for_more_io():
    import subprocess
    import sys
    from threading import Event
    from time import monotonic
    from types import SimpleNamespace

    from thesistrace.daily_track.execution import _read_message

    messages = [
        {"status": "progress", "phase": "result_ready", "current_session": "2026-01-05"},
        {"status": "succeeded", "strategy_event_counts": {}},
    ]
    encoded = "\n".join(json.dumps(value) for value in messages) + "\n"
    script = f"import sys; sys.stdout.write({encoded!r}); sys.stdout.flush(); sys.stdin.readline()"
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = monotonic() + 1
    try:
        result = _read_message(
            child,
            request=SimpleNamespace(
                target_sessions=("2026-01-05",), track_id="track", attempt_id="a"
            ),
            emit=lambda _event: None,
            authority_lost=Event(),
            stop_requested=lambda: monotonic() > deadline,
            acknowledge_event_frame=lambda: None,
        )
        assert result == {"status": "succeeded", "strategy_events": {}}
    finally:
        child.kill()
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


def test_tracking_child_keeps_watchdog_and_commands_active_across_multiple_event_frames():
    import subprocess
    import sys
    from threading import Event
    from time import monotonic
    from types import SimpleNamespace

    from thesistrace.daily_track.execution import _ChildHeartbeat, _read_message

    script = """
from thesistrace.entrypoints import tracking_child
tracking_child.execute_tracking_target = lambda request: {
    "status": "succeeded", "strategy_events": {
        "strategy_orders": [{"order_id": str(i)} for i in range(513)]
    }
}
tracking_child.main()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child.stdin.write(
        json.dumps(
            {
                "watchdog_grace_seconds": 2,
                "target_sessions": ["2026-01-05"],
            }
        )
        + "\n"
    )
    child.stdin.flush()
    authority_lost = Event()
    heartbeat = _ChildHeartbeat(child, grace_seconds=2, authority_lost=authority_lost)
    deadline = monotonic() + 5
    try:
        result = _read_message(
            child,
            request=SimpleNamespace(
                target_sessions=("2026-01-05",),
                track_id="track",
                attempt_id="a",
            ),
            emit=lambda _event: None,
            authority_lost=authority_lost,
            stop_requested=lambda: monotonic() > deadline,
            acknowledge_event_frame=heartbeat.acknowledge_event_frame,
        )
        assert len(result["strategy_events"]["strategy_orders"]) == 513
        heartbeat.acknowledge()
        assert child.wait(timeout=5) == 0
    finally:
        heartbeat.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


def test_holding_rows_are_framed_separately_from_permanent_events():
    from thesistrace.strategy_event_wire import EventMessageAssembler, strategy_event_messages

    message = {
        "status": "chunk_succeeded",
        "chunk": {
            "strategy_events": {"strategy_targets": []},
            "holding_sessions": ["2026-01-05", "2026-01-06"],
            "holding_observations": [
                {"session": "2026-01-06", "instrument_id": str(index)}
                for index in range(1100)
            ],
        },
    }
    frames = list(strategy_event_messages(message))
    assert len(frames) == 4
    assert all(frame["section"] == "holding_observations" for frame in frames[:-1])
    assert "holding_observations" not in frames[-1]["chunk"]
    assembler = EventMessageAssembler()
    for frame in frames[:-1]:
        assert assembler.accept(frame) is None
    assert assembler.accept(frames[-1]) == message

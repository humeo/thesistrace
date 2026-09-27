import json

import pytest

from thesistrace.strategy_event_wire import EventMessageAssembler, strategy_event_messages


def test_large_chunk_crosses_64_mib_without_changing_its_commit_boundary():
    from thesistrace.research_kernel.strategy_event_limits import MAX_FRAMEWORK_RECORD_BYTES

    row = {"evidence": "x" * (MAX_FRAMEWORK_RECORD_BYTES - 100)}
    events = {"strategy_framework": [row] * 18}
    message = {"status": "chunk_succeeded", "chunk": {"ordinal": 1, "strategy_events": events}}
    assembler = EventMessageAssembler(max_event_bytes=128 * 1024**2)
    for frame in strategy_event_messages(message):
        result = assembler.accept(frame)
        if frame["status"] == "strategy_event_frame":
            assert result is None
    assert result["chunk"]["ordinal"] == 1
    rows = result["chunk"]["strategy_events"]["strategy_framework"]
    assert len(rows) == 18
    assert rows[0] == rows[-1] == row


def test_event_budget_is_per_chunk_and_incomplete_or_oversize_data_is_not_returned():
    message = {"strategy_events": {"strategy_orders": [{"order_id": "one"}]}}
    frames = list(strategy_event_messages(message))
    assembler = EventMessageAssembler(max_event_bytes=20)
    completed = []
    for _ in range(2):
        assert assembler.accept(frames[0]) is None
        completed.append(assembler.accept(frames[-1]))
    assert completed == [message, message]
    assert EventMessageAssembler(max_event_bytes=18).accept(frames[0]) is None
    with pytest.raises(ValueError, match="budget"):
        EventMessageAssembler(max_event_bytes=17).accept(frames[0])


def test_event_transport_keeps_large_segments_in_bounded_frames():
    # A complete segment can exceed the old 16 MiB single-line contract.
    events = {"strategy_fills": [{"fill_id": str(i), "evidence": "x" * 1024} for i in range(17000)]}
    message = {"status": "chunk_succeeded", "chunk": {"ordinal": 1, "strategy_events": events}}
    assembler = EventMessageAssembler(max_event_bytes=128 * 1024**2)
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
    assembler = EventMessageAssembler(max_event_bytes=128 * 1024**2)
    assert assembler.accept(frames[0]) is None
    with pytest.raises(ValueError, match="order"):
        assembler.accept(frames[0])
    with pytest.raises(ValueError, match="count"):
        EventMessageAssembler(max_event_bytes=128 * 1024**2).accept(frames[-1])
    with pytest.raises(ValueError, match="incomplete"):
        assembler.accept({"status": "failed"})


def test_event_transport_preserves_empty_and_non_event_messages():
    for message in (
        {"status": "ready"},
        {"strategy_events": {}},
        {"strategy_events": {"strategy_targets": []}},
    ):
        assembler = EventMessageAssembler(max_event_bytes=128 * 1024**2)
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
        message = transport.read(
            max_event_bytes=128 * 1024**2, cancel_requested=lambda: monotonic() > deadline,
        )
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
            execution_memory_bytes=128 * 1024**2,
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
            execution_memory_bytes=128 * 1024**2,
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
    assembler = EventMessageAssembler(max_event_bytes=128 * 1024**2)
    for frame in frames[:-1]:
        assert assembler.accept(frame) is None
    assert assembler.accept(frames[-1]) == message


def test_large_target_frames_are_byte_bounded_and_ordinary_records_remain_small():
    from thesistrace.strategy_event_wire import (
        MAX_EVENT_FRAME_BYTES,
        MAX_EVENT_RECORD_BYTES,
        MAX_TARGET_RECORD_BYTES,
    )

    target = {"allocation": "x" * (MAX_TARGET_RECORD_BYTES - len('{"allocation":""}'))}
    frames = list(strategy_event_messages({"strategy_events": {"strategy_targets": [target] * 5}}))
    assert [len(frame["rows"]) for frame in frames[:-1]] == [4, 1]
    assembler = EventMessageAssembler(max_event_bytes=128 * 1024**2)
    with pytest.raises(ValueError, match="frame exceeds"):
        assembler.accept({
            "status": "strategy_event_frame", "section": "strategy_targets", "offset": 0,
            "rows": [target] * 5,
        })
    assert len(json.dumps(frames[0], separators=(",", ":"))) < MAX_EVENT_FRAME_BYTES + 1024
    for section, row in (
        ("strategy_targets", {"allocation": target["allocation"] + "x"}),
        ("strategy_fills", {"evidence": "x" * MAX_EVENT_RECORD_BYTES}),
    ):
        with pytest.raises(ValueError, match="record exceeds"):
            list(strategy_event_messages({"strategy_events": {section: [row]}}))

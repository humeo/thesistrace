"""Bounded event frames within one acknowledged execution segment."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping

EVENT_FRAME_ROWS = 512
MAX_EVENT_RECORD_BYTES = 24 * 1024
MAX_EVENT_SEGMENT_BYTES = 64 * 1024 * 1024
_EVENT_SECTIONS = frozenset(
    {
        "strategy_targets",
        "strategy_orders",
        "strategy_child_orders",
        "strategy_fills",
        "strategy_adjustments",
    }
)

_FRAME_SECTIONS = _EVENT_SECTIONS | {"holding_observations"}


def _container(message: Mapping) -> Mapping:
    chunk = message.get("chunk")
    return chunk if isinstance(chunk, Mapping) else message


def _replace_events(message: Mapping, key: str, value: object) -> dict:
    container = {
        name: item
        for name, item in _container(message).items()
        if name not in {"strategy_events", "strategy_event_counts", "holding_observations"}
    }
    if key == "strategy_events" and "holding_observations" in value:
        value = dict(value)
        container["holding_observations"] = value.pop("holding_observations")
    container[key] = value
    return (
        {**message, "chunk": container} if isinstance(message.get("chunk"), Mapping) else container
    )


def _row_bytes(rows: list) -> int:
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Strategy event row must be an object")
        size = len(json.dumps(row, separators=(",", ":")).encode())
        if size > MAX_EVENT_RECORD_BYTES:
            raise ValueError("Strategy event record exceeds its transport and page bound")
        total += size
    return total


def strategy_event_messages(message: Mapping) -> Iterator[dict]:
    """Send small row frames followed by the original acknowledgment boundary."""
    container = _container(message)
    if "strategy_events" not in container:
        yield dict(message)
        return
    events = container["strategy_events"]
    if not isinstance(events, dict) or not set(events) <= _EVENT_SECTIONS:
        raise ValueError("Strategy event sections are invalid")
    events = dict(events)
    if "holding_observations" in container:
        events["holding_observations"] = container["holding_observations"]
    counts = {}
    total = 0
    for section, rows in events.items():
        if not isinstance(rows, list):
            raise ValueError("Strategy event rows are invalid")
        counts[section] = len(rows)
        for start in range(0, len(rows), EVENT_FRAME_ROWS):
            selected = rows[start : start + EVENT_FRAME_ROWS]
            total += _row_bytes(selected)
            if total > MAX_EVENT_SEGMENT_BYTES:
                raise ValueError("Strategy event segment exceeds its transport capacity")
            yield {
                "status": "strategy_event_frame",
                "section": section,
                "offset": start,
                "rows": selected,
            }
    yield _replace_events(message, "strategy_event_counts", counts)


class EventMessageAssembler:
    """Retain at most one bounded segment; incomplete frames are never published."""

    def __init__(self) -> None:
        self._rows: dict[str, list] = {}
        self._bytes = 0

    def accept(self, message: dict) -> dict | None:
        if message.get("status") == "strategy_event_frame":
            if set(message) != {"status", "section", "offset", "rows"}:
                raise ValueError("Strategy event frame is invalid")
            section, offset, rows = message["section"], message["offset"], message["rows"]
            if not isinstance(section, str) or section not in _FRAME_SECTIONS:
                raise ValueError("Strategy event frame section is invalid")
            if not isinstance(rows, list) or not 1 <= len(rows) <= EVENT_FRAME_ROWS:
                raise ValueError("Strategy event frame size is invalid")
            existing = self._rows.setdefault(section, [])
            if type(offset) is not int or offset != len(existing):
                raise ValueError("Strategy event frame order is invalid")
            self._bytes += _row_bytes(rows)
            if self._bytes > MAX_EVENT_SEGMENT_BYTES:
                raise ValueError("Strategy event segment exceeds its transport capacity")
            existing.extend(rows)
            return None
        counts = _container(message).get("strategy_event_counts")
        if counts is None:
            if self._rows:
                raise ValueError("Strategy event segment is incomplete")
            if {"strategy_events", "holding_observations"} & _container(message).keys():
                raise ValueError("Strategy events require framed transport")
            return message
        if (
            not isinstance(counts, dict)
            or not set(counts) <= _FRAME_SECTIONS
            or not set(self._rows) <= set(counts)
            or any(
                type(count) is not int or count < 0 or count != len(self._rows.get(section, []))
                for section, count in counts.items()
            )
        ):
            raise ValueError("Strategy event frame count is invalid")
        result = _replace_events(
            message, "strategy_events", {section: self._rows.get(section, []) for section in counts}
        )
        self._rows = {}
        self._bytes = 0
        return result


def print_strategy_event_message(
    message: Mapping,
    *,
    acknowledge: Callable[[], Mapping],
) -> None:
    for frame in strategy_event_messages(message):
        print(json.dumps(frame, sort_keys=True, separators=(",", ":")), flush=True)
        if frame.get("status") == "strategy_event_frame":
            command = acknowledge()
            if command == {"command": "cancel"}:
                raise SystemExit(0)
            if command != {"command": "acknowledge_event_frame"}:
                raise ValueError("Strategy event frame acknowledgment is invalid")

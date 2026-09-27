"""Byte-bounded frames and spooled event rows within one commit boundary."""

from __future__ import annotations

import json
from bisect import bisect_right
from collections.abc import Callable, Iterator, Mapping, Sequence
from tempfile import SpooledTemporaryFile
from weakref import finalize

from thesistrace.research_kernel.strategy_event_limits import (
    EVENT_FRAME_ROWS,
    MAX_EVENT_FRAME_BYTES,
    MAX_EVENT_RECORD_BYTES,
    MAX_FRAMEWORK_RECORD_BYTES,
    MAX_TARGET_RECORD_BYTES,
)

_EVENT_SECTIONS = frozenset(
    {
        "strategy_targets",
        "strategy_orders",
        "strategy_child_orders",
        "strategy_fills",
        "strategy_adjustments",
        "strategy_execution_constraints",
        "strategy_framework",
    }
)

_FRAME_SECTIONS = _EVENT_SECTIONS | {"holding_observations"}


class EventByteBudgetExceeded(ValueError):
    pass


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


def event_record_byte_limit(section: str) -> int:
    if section == "strategy_framework":
        return MAX_FRAMEWORK_RECORD_BYTES
    return MAX_TARGET_RECORD_BYTES if section == "strategy_targets" else MAX_EVENT_RECORD_BYTES


def _row_bytes(rows: list, section: str) -> int:
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Strategy event row must be an object")
        size = len(json.dumps(row, separators=(",", ":")).encode())
        if size > event_record_byte_limit(section):
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
    for section, rows in events.items():
        if not isinstance(rows, list):
            raise ValueError("Strategy event rows are invalid")
        counts[section] = len(rows)
        selected, start, frame_bytes = [], 0, 0
        for row in rows:
            size = _row_bytes([row], section)
            if selected and (
                len(selected) == EVENT_FRAME_ROWS or frame_bytes + size > MAX_EVENT_FRAME_BYTES
            ):
                yield {
                    "status": "strategy_event_frame", "section": section,
                    "offset": start, "rows": selected,
                }
                start += len(selected)
                selected, frame_bytes = [], 0
            selected.append(row)
            frame_bytes += size
        if selected:
            yield {
                "status": "strategy_event_frame", "section": section,
                "offset": start, "rows": selected,
            }
    yield _replace_events(message, "strategy_event_counts", counts)


class _EventStorage:
    """One shared spool per Chunk; returned row views own its lifetime."""

    def __init__(self) -> None:
        self.file = SpooledTemporaryFile(max_size=MAX_EVENT_FRAME_BYTES, mode="w+b")
        finalize(self, self.file.close)


class _EventRows(Sequence[dict]):
    """Read only the frames needed by a consumer's bounded partition."""

    def __init__(self, storage: _EventStorage) -> None:
        self._storage = storage
        self._frames: list[tuple[int, int]] = []
        self._starts: list[int] = []
        self._count = 0

    def append_frame(self, rows: list[dict]) -> None:
        encoded = json.dumps(rows, separators=(",", ":")).encode()
        stream = self._storage.file
        stream.seek(0, 2)
        self._starts.append(self._count)
        self._frames.append((stream.tell(), len(encoded)))
        stream.write(encoded)
        self._count += len(rows)

    def __len__(self) -> int:
        return self._count

    def _range(self, start: int, stop: int) -> Iterator[dict]:
        if start >= stop:
            return
        index = bisect_right(self._starts, start) - 1
        for frame in range(index, len(self._frames)):
            first = self._starts[frame]
            if first >= stop:
                break
            offset, size = self._frames[frame]
            stream = self._storage.file
            stream.seek(offset)
            rows = json.loads(stream.read(size))
            yield from rows[max(0, start - first):stop - first]

    def __iter__(self) -> Iterator[dict]:
        return self._range(0, self._count)

    def __getitem__(self, key: int | slice) -> dict | list[dict]:
        if isinstance(key, slice):
            start, stop, step = key.indices(self._count)
            if step < 0:
                return [self[index] for index in range(start, stop, step)]
            return list(self._range(start, stop))[::step]
        index = key if key >= 0 else key + self._count
        if not 0 <= index < self._count:
            raise IndexError(key)
        return next(self._range(index, index + 1))

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, Sequence) and len(self) == len(other)
                and all(left == right for left, right in zip(self, other, strict=True)))


class EventMessageAssembler:
    """Spool frames under the execution budget; expose only complete Chunk rows."""

    def __init__(self, *, max_event_bytes: int) -> None:
        if type(max_event_bytes) is not int or max_event_bytes < 1:
            raise ValueError("Strategy event budget must be a positive integer")
        self._max_event_bytes = max_event_bytes
        self._storage: _EventStorage | None = None
        self._rows: dict[str, _EventRows] = {}
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
            if self._storage is None:
                self._storage = _EventStorage()
            if section not in self._rows:
                self._rows[section] = _EventRows(self._storage)
            existing = self._rows[section]
            if type(offset) is not int or offset != len(existing):
                raise ValueError("Strategy event frame order is invalid")
            frame_bytes = _row_bytes(rows, section)
            if frame_bytes > MAX_EVENT_FRAME_BYTES:
                raise ValueError("Strategy event frame exceeds its transport capacity")
            self._bytes += frame_bytes
            if self._bytes > self._max_event_bytes:
                raise EventByteBudgetExceeded("Strategy events exceed the execution byte budget")
            existing.append_frame(rows)
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
        self._storage = None
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

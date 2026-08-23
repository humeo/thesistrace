from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import IO, Literal

OperationalLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
OperationalEventWriter = Callable[["OperationalEvent"], None]

_LEVEL_NUMBERS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SAFE_OPERATION_ID_PATTERN = re.compile(
    r"^(?:bootstrap|refresh|financial-refresh):[0-9a-f]{32}$"
)
_SAFE_ENUM_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SAFE_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SAFE_METHOD_PATTERN = re.compile(r"^[A-Z]{3,16}$")
_SAFE_ROUTE_PATTERN = re.compile(r"^/[A-Za-z0-9_./{}:-]{0,255}$")
_SAFE_EXCEPTION_TYPE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")
_ID_FIELDS = frozenset(
    {"operation_id", "run_id", "track_id", "attempt_id", "http_request_id"}
)
_ENUM_FIELDS = frozenset(
    {"worker_role", "phase", "previous_status", "status", "outcome"}
)
_TIMESTAMP_FIELDS = frozenset({"retry_at", "lease_expires_at"})
_STRING_FIELDS = frozenset(
    {
        "operation_id",
        "run_id",
        "track_id",
        "attempt_id",
        "http_request_id",
        "worker_role",
        "phase",
        "previous_status",
        "status",
        "outcome",
        "retry_at",
        "lease_expires_at",
        "failure_code",
        "method",
        "route",
        "exception_type",
    }
)
_INTEGER_FIELDS = frozenset({"attempt_number", "duration_ms", "status_code"})
_MAX_STRING_LENGTH = 512
_MAX_STACK_FRAMES = 20


@dataclass(frozen=True)
class OperationalEvent:
    level: OperationalLevel
    component: str
    event: str
    context: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level not in _LEVEL_NUMBERS:
            raise ValueError(f"unsupported operational event level: {self.level}")
        if _NAME_PATTERN.fullmatch(self.component) is None:
            raise ValueError("operational event component must be lower snake case")
        if _NAME_PATTERN.fullmatch(self.event) is None:
            raise ValueError("operational event name must be lower snake case")
        object.__setattr__(
            self,
            "context",
            MappingProxyType(_allowlisted_context(self.context)),
        )


class OperationalEventSink:
    def __init__(
        self,
        stream: IO[str] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            _OperationalEventFormatter(_utc_now if clock is None else clock)
        )
        self._logger = logging.Logger("thesistrace.operational", level=logging.INFO)
        self._logger.propagate = False
        self._logger.addHandler(handler)

    def __call__(self, event: OperationalEvent) -> None:
        self._logger.log(
            _LEVEL_NUMBERS[event.level],
            event.event,
            extra={"operational_event": event},
        )


def sanitized_exception_context(error: Exception) -> Mapping[str, object]:
    frames: list[dict[str, object]] = []
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        module = _safe_stack_name(frame.f_globals.get("__name__"))
        function = _safe_stack_name(frame.f_code.co_name)
        if module is not None and function is not None:
            frames.append(
                {
                    "module": module,
                    "function": function,
                    "line": traceback.tb_lineno,
                }
            )
        traceback = traceback.tb_next
    return {
        "exception_type": type(error).__name__,
        "stack_frames": frames[-_MAX_STACK_FRAMES:],
    }


class _OperationalEventFormatter(logging.Formatter):
    def __init__(self, clock: Callable[[], datetime]) -> None:
        super().__init__()
        self._clock = clock

    def format(self, record: logging.LogRecord) -> str:
        event = record.operational_event
        payload: dict[str, object] = {
            "timestamp": _utc_timestamp(self._clock()),
            "level": event.level,
            "component": event.component,
            "event": event.event,
        }
        payload.update(_allowlisted_context(event.context))
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _allowlisted_context(context: Mapping[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for name in _STRING_FIELDS:
        value = context.get(name)
        if _is_safe_string(name, value):
            safe[name] = value
    for name in _INTEGER_FIELDS:
        value = context.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe[name] = value
    frames = _safe_stack_frames(context.get("stack_frames"))
    if frames:
        safe["stack_frames"] = frames
    return safe


def _is_safe_string(name: str, value: object) -> bool:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= _MAX_STRING_LENGTH
        or not all(character.isprintable() for character in value)
    ):
        return False
    if name == "operation_id":
        return _SAFE_OPERATION_ID_PATTERN.fullmatch(value) is not None
    if name in _ID_FIELDS:
        return _SAFE_ID_PATTERN.fullmatch(value) is not None
    if name in _ENUM_FIELDS:
        return _SAFE_ENUM_PATTERN.fullmatch(value) is not None
    if name in _TIMESTAMP_FIELDS:
        return _is_utc_rfc3339(value)
    if name == "failure_code":
        return _SAFE_FAILURE_CODE_PATTERN.fullmatch(value) is not None
    if name == "method":
        return _SAFE_METHOD_PATTERN.fullmatch(value) is not None
    if name == "route":
        return value == "unmatched" or _SAFE_ROUTE_PATTERN.fullmatch(value) is not None
    if name == "exception_type":
        return _SAFE_EXCEPTION_TYPE_PATTERN.fullmatch(value) is not None
    return False


def _is_utc_rfc3339(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(parsed)


def _safe_stack_frames(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    frames: list[dict[str, object]] = []
    for candidate in value[-_MAX_STACK_FRAMES:]:
        if not isinstance(candidate, Mapping):
            continue
        module = _safe_stack_name(candidate.get("module"), strip_suffix=".py")
        function = _safe_stack_name(candidate.get("function"))
        line = candidate.get("line")
        if module is None or function is None:
            continue
        if not isinstance(line, int) or isinstance(line, bool) or line <= 0:
            continue
        frames.append({"module": module, "function": function, "line": line})
    return frames


def _safe_stack_name(value: object, *, strip_suffix: str = "") -> str | None:
    if not isinstance(value, str):
        return None
    name = value.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    if strip_suffix and name.endswith(strip_suffix):
        name = name[: -len(strip_suffix)]
    if not name or len(name) > 128:
        return None
    if any(not (character.isalnum() or character in "._<>-") for character in name):
        return None
    return name


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("operational event clock must return an aware datetime")
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(UTC)


_default_sink = OperationalEventSink()


def emit_operational_event(event: OperationalEvent) -> None:
    _default_sink(event)

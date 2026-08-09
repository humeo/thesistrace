from __future__ import annotations

import json
import os
import stat
from datetime import date
from pathlib import Path

from thesistrace.adapters.tushare_provider import TushareSourceError

_REPLAY_MAX_BYTES = 128 * 1024 * 1024


class ReplayTushareProvider:
    def __init__(self, path: Path | str) -> None:
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(Path(path), flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Tushare replay must be a regular file")
            if metadata.st_size > _REPLAY_MAX_BYTES:
                raise ValueError("Tushare replay exceeds its byte bound")
            content = bytearray()
            while chunk := os.read(
                descriptor,
                min(64 * 1024, _REPLAY_MAX_BYTES + 1 - len(content)),
            ):
                content.extend(chunk)
                if len(content) > _REPLAY_MAX_BYTES:
                    raise ValueError("Tushare replay exceeds its byte bound")
            if len(content) != metadata.st_size:
                raise ValueError("Tushare replay changed while reading")
        finally:
            os.close(descriptor)
        if len(content) > _REPLAY_MAX_BYTES:
            raise ValueError("Tushare replay exceeds its byte bound")
        value = json.loads(content)
        if not isinstance(value, dict) or set(value) != {
            "format",
            "version",
            "request_start",
            "request_end",
            "snapshot",
        }:
            raise ValueError("Tushare replay contract is invalid")
        if value["format"] != "thesistrace-tushare-bootstrap-replay" or value["version"] != 1:
            raise ValueError("Tushare replay contract is incompatible")
        snapshot = value["snapshot"]
        if not isinstance(snapshot, dict) or any(
            not isinstance(key, str) or not isinstance(rows, list) for key, rows in snapshot.items()
        ):
            raise ValueError("Tushare replay snapshot is invalid")
        self._request_start = date.fromisoformat(str(value["request_start"]))
        self._request_end = date.fromisoformat(str(value["request_end"]))
        self._snapshot = snapshot

    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]:
        if (start_date, completed_through_date) != (
            self._request_start,
            self._request_end,
        ):
            raise TushareSourceError("REPLAY_WINDOW_MISMATCH", source_code=0)
        return self._snapshot

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        known_ts_codes: set[str],
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]:
        raise TushareSourceError("REPLAY_BOOTSTRAP_ONLY", source_code=0)


__all__ = ("ReplayTushareProvider",)

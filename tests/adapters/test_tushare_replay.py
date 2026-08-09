from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from thesistrace.adapters import tushare_replay
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.adapters.tushare_replay import ReplayTushareProvider


@pytest.mark.parametrize("unsafe_kind", ("symlink", "fifo", "oversized"))
def test_replay_rejects_unsafe_entries_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    replay = tmp_path / "bootstrap-replay.json"
    if unsafe_kind == "symlink":
        target = tmp_path / "target.json"
        target.write_text("{}")
        replay.symlink_to(target)
    elif unsafe_kind == "fifo":
        os.mkfifo(replay)
    else:
        monkeypatch.setattr(tushare_replay, "_REPLAY_MAX_BYTES", 16)
        replay.write_bytes(b"x" * 17)

    with pytest.raises((OSError, ValueError)):
        ReplayTushareProvider(replay)


def test_refresh_replay_is_bound_to_the_recorded_window(tmp_path: Path) -> None:
    replay = tmp_path / "refresh-replay.json"
    replay.write_text(
        json.dumps(
            {
                "format": "thesistrace-tushare-refresh-replay",
                "version": 1,
                "request_start": "2026-08-03",
                "request_end": "2026-08-31",
                "known_ts_codes": ["600000.SH"],
                "snapshot": {"calendar_sse": []},
            }
        )
    )
    provider = ReplayTushareProvider(replay)

    assert provider.collect_incremental_snapshot(
        last_session="2026-08-03",
        known_ts_codes={"600000.SH"},
        as_of=date(2026, 8, 31),
    ) == {"calendar_sse": []}
    with pytest.raises(TushareSourceError) as failure:
        provider.collect_incremental_snapshot(
            last_session="2026-08-03",
            known_ts_codes={"000001.SZ"},
            as_of=date(2026, 8, 31),
        )
    assert failure.value.reason_code == "REPLAY_INSTRUMENT_SET_MISMATCH"

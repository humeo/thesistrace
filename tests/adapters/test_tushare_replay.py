from __future__ import annotations

import os
from pathlib import Path

import pytest

from thesistrace.adapters import tushare_replay
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

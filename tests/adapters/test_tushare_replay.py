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
                "version": 2,
                "request_start": "2026-08-03",
                "request_end": "2026-08-31",
                "snapshot": {"calendar_sse": []},
            }
        )
    )
    provider = ReplayTushareProvider(replay)

    assert provider.collect_incremental_snapshot(
        last_session="2026-08-03",
        as_of=date(2026, 8, 31),
    ) == {"calendar_sse": []}
    with pytest.raises(TushareSourceError) as failure:
        provider.collect_incremental_snapshot(
            last_session="2026-08-04",
            as_of=date(2026, 8, 31),
        )
    assert failure.value.reason_code == "REPLAY_WINDOW_MISMATCH"


def test_product_replay_serves_market_and_exact_financial_responses(tmp_path: Path) -> None:
    replay = tmp_path / "product-replay.json"
    replay.write_text(
        json.dumps(
            {
                "format": "thesistrace-tushare-product-replay",
                "version": 1,
                "request_start": "2010-01-04",
                "request_end": "2026-08-05",
                "snapshot": {"calendar_sse": []},
                "financial": {
                    "income": {
                        "000001.SZ": {
                            "fields": ["ts_code", "ann_date", "end_date"],
                            "items": [["000001.SZ", "20260425", "20251231"]],
                        }
                    }
                },
            }
        )
    )
    provider = ReplayTushareProvider(replay)

    assert provider.collect_bootstrap_snapshot(
        start_date=date(2010, 1, 4),
        completed_through_date=date(2026, 8, 5),
    ) == {"calendar_sse": []}
    response = provider.query_raw(
        "income",
        params={"ts_code": "000001.SZ"},
        fields=("ts_code", "ann_date"),
    )
    assert response.fields == ("ts_code", "ann_date", "end_date")
    assert response.items == (("000001.SZ", "20260425", "20251231"),)

    with pytest.raises(TushareSourceError) as failure:
        provider.query_raw(
            "income",
            params={"ts_code": "000002.SZ"},
            fields=("ts_code",),
        )
    assert failure.value.reason_code == "REPLAY_REQUEST_MISMATCH"

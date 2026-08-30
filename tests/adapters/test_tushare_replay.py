from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

import pytest

from thesistrace.adapters import tushare_replay
from thesistrace.adapters.tushare_benchmark import TushareBenchmarkSource
from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import (
    TushareSourceError,
    normalize_tushare_snapshot,
)
from thesistrace.adapters.tushare_replay import (
    ReplayTushareProvider,
    ReplayTushareRefreshBundle,
)
from thesistrace.data.source import refresh_collection_plan


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


def test_operator_console_replay_matches_the_post_publication_head() -> None:
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    product = json.loads(
        (fixture_root / "tushare-financial-product-replay.json").read_text()
    )
    _, initial = normalize_tushare_snapshot(product["snapshot"])
    as_of = datetime.fromisoformat("2026-08-11T18:00:00+08:00")
    first = TushareDataSource(
        provider=ReplayTushareProvider(
            fixture_root / "tushare-financial-market-refresh-replay.json"
        )
    ).collect(refresh_collection_plan(as_of, initial)).canonical
    no_change_plan = refresh_collection_plan(as_of, first)

    assert no_change_plan.overlap_start_session == "2026-07-15"
    repeated = TushareDataSource(
        provider=ReplayTushareProvider(
            fixture_root / "tushare-operator-console-market-refresh-replay.json"
        )
    ).collect(no_change_plan).canonical

    assert repeated == first


def test_refresh_bundle_selects_each_exact_worker_window_and_rejects_duplicates() -> None:
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    financial = fixture_root / "tushare-financial-market-refresh-replay.json"
    console = fixture_root / "tushare-operator-console-market-refresh-replay.json"
    image_smoke = fixture_root / "tushare-image-smoke-market-refresh-replay.json"
    provider = ReplayTushareRefreshBundle((financial, console, image_smoke))

    first = provider.collect_incremental_snapshot(
        last_session="2026-07-09",
        as_of=date(2026, 8, 11),
    )
    second = provider.collect_incremental_snapshot(
        last_session="2026-07-15",
        as_of=date(2026, 8, 11),
    )
    smoke = provider.collect_incremental_snapshot(
        last_session="2026-07-09",
        as_of=date(2026, 8, 5),
    )

    assert first["calendar_sse"]
    assert second["calendar_sse"]
    assert smoke["stock_basic"]
    with pytest.raises(TushareSourceError) as mismatch:
        provider.collect_incremental_snapshot(
            last_session="2026-07-16",
            as_of=date(2026, 8, 11),
        )
    assert mismatch.value.reason_code == "REPLAY_WINDOW_MISMATCH"
    with pytest.raises(ValueError, match="duplicate window"):
        ReplayTushareRefreshBundle((financial, financial))


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


def test_product_replay_serves_benchmark_through_source_neutral_adapter(
    tmp_path: Path,
) -> None:
    replay = tmp_path / "product-replay.json"
    replay.write_text(
        json.dumps(
            {
                "format": "thesistrace-tushare-product-replay",
                "version": 1,
                "request_start": "2010-01-04",
                "request_end": "2010-01-05",
                "snapshot": {
                    "benchmark_index_daily": [
                        {
                            "ts_code": "399300.SZ",
                            "trade_date": "20100105",
                            "open": 3545.19,
                        },
                        {
                            "ts_code": "399300.SZ",
                            "trade_date": "20100104",
                            "open": 3592.47,
                        },
                    ]
                },
                "financial": {},
            }
        )
    )

    levels = TushareBenchmarkSource(ReplayTushareProvider(replay)).collect_open_levels(
        start_session="2010-01-04",
        end_session="2010-01-05",
    )

    assert [(level.session, level.open_level) for level in levels] == [
        ("2010-01-04", "3592.47"),
        ("2010-01-05", "3545.19"),
    ]

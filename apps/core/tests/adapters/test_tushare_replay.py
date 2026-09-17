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
                "version": 3,
                "request_start": "2026-08-03",
                "request_end": "2026-08-31",
                "snapshot": {"calendar_sse": []},
                "financial": {},
                "financial_refresh": None,
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


def test_operator_console_replay_matches_the_post_publication_head(
    tmp_path: Path,
) -> None:
    fixture_root = Path(__file__).resolve().parents[4] / "tests/fixtures"
    product = json.loads((fixture_root / "tushare-financial-product-replay.json").read_text())
    _, initial = normalize_tushare_snapshot(product["snapshot"])
    first_as_of = datetime.fromisoformat("2026-08-11T18:00:00+08:00")
    extension_as_of = datetime.fromisoformat("2026-08-14T18:00:00+08:00")
    first = (
        TushareDataSource(
            checkpoint_root=tmp_path / "daily-basic",
            provider=ReplayTushareProvider(
                fixture_root / "tushare-financial-market-refresh-replay.json"
            ),
        )
        .collect(refresh_collection_plan(first_as_of, initial, collection_key="test-first"))
        .canonical
    )
    extension_plan = refresh_collection_plan(
        extension_as_of, first, collection_key="test-extension"
    )

    assert extension_plan.overlap_start_session == "2026-07-15"
    repeated = (
        TushareDataSource(
            checkpoint_root=tmp_path / "daily-basic",
            provider=ReplayTushareProvider(
                fixture_root / "tushare-operator-console-market-refresh-replay.json"
            ),
        )
        .collect(extension_plan)
        .canonical
    )
    no_change_plan = refresh_collection_plan(
        extension_as_of, repeated, collection_key="test-no-change"
    )
    no_change = (
        TushareDataSource(
            checkpoint_root=tmp_path / "daily-basic",
            provider=ReplayTushareProvider(
                fixture_root / "tushare-operator-console-market-no-change-replay.json"
            ),
        )
        .collect(no_change_plan)
        .canonical
    )

    assert repeated["research_calendar"][-1] == "2026-08-14"
    assert no_change_plan.overlap_start_session == "2026-07-20"
    assert no_change == repeated


def test_refresh_bundle_selects_each_exact_worker_window_and_rejects_duplicates() -> None:
    fixture_root = Path(__file__).resolve().parents[4] / "tests/fixtures"
    financial = fixture_root / "tushare-financial-market-refresh-replay.json"
    console = fixture_root / "tushare-operator-console-market-refresh-replay.json"
    console_no_change = (
        fixture_root / "tushare-operator-console-market-no-change-replay.json"
    )
    image_smoke = fixture_root / "tushare-image-smoke-market-refresh-replay.json"
    provider = ReplayTushareRefreshBundle(
        (financial, console, console_no_change, image_smoke)
    )

    first = provider.collect_incremental_snapshot(
        last_session="2026-07-09",
        as_of=date(2026, 8, 11),
    )
    second = provider.collect_incremental_snapshot(
        last_session="2026-07-15",
        as_of=date(2026, 8, 14),
    )
    no_change = provider.collect_incremental_snapshot(
        last_session="2026-07-20",
        as_of=date(2026, 8, 14),
    )
    smoke = provider.collect_incremental_snapshot(
        last_session="2026-07-09",
        as_of=date(2026, 8, 5),
    )

    assert first["calendar_sse"]
    assert second["calendar_sse"]
    assert no_change["calendar_sse"] == []
    assert smoke["stock_basic"]
    with pytest.raises(TushareSourceError) as mismatch:
        provider.collect_incremental_snapshot(
            last_session="2026-07-16",
            as_of=date(2026, 8, 11),
        )
    assert mismatch.value.reason_code == "REPLAY_WINDOW_MISMATCH"
    with pytest.raises(ValueError, match="duplicate window"):
        ReplayTushareRefreshBundle((financial, financial))

    discovery = provider.discover(
        start_date="2026-08-05",
        end_date="2026-08-14",
        allowed_ts_codes={"000001.SZ"},
    )
    assert discovery.reports == ()
    assert len(discovery.gaps) == 1
    assert discovery.gaps[0].failure_code == "UPSTREAM_UNAVAILABLE"

    resumed = ReplayTushareRefreshBundle(
        (financial, console, console_no_change, image_smoke)
    )
    resumed.select_financial_window("2026-08-05", "2026-08-14")
    with pytest.raises(TushareSourceError) as selected_missing_response:
        resumed.query_raw(
            "income",
            params={"ts_code": "000001.SZ"},
            fields=(
                "ts_code",
                "ann_date",
                "f_ann_date",
                "end_date",
                "report_type",
                "comp_type",
                "end_type",
                "total_revenue",
                "n_income_attr_p",
                "update_flag",
            ),
        )
    assert selected_missing_response.value.reason_code == "REPLAY_REQUEST_MISMATCH"
    with pytest.raises(TushareSourceError) as financial_mismatch:
        resumed.select_financial_window("2026-08-06", "2026-08-14")
    assert financial_mismatch.value.reason_code == "REPLAY_REQUEST_MISMATCH"


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


def test_daily_basic_replay_preserves_nulls_and_exact_request_scope(tmp_path: Path) -> None:
    from thesistrace.adapters.tushare_daily_basic import (
        DAILY_BASIC_SOURCE_FIELDS,
        TushareDailyBasicSource,
    )

    row = dict.fromkeys(DAILY_BASIC_SOURCE_FIELDS)
    row.update(ts_code="000001.SZ", trade_date="20260803", pe="12.5")
    payload = {
        "format": "thesistrace-tushare-refresh-replay", "version": 3,
        "request_start": "2026-08-03", "request_end": "2026-08-04",
        "snapshot": {"daily_basic": [row]}, "financial": {}, "financial_refresh": None,
    }
    replay = tmp_path / "daily-basic.json"
    replay.write_text(json.dumps(payload))
    # After a restart the price checkpoint may skip collect_incremental_snapshot.
    # Selecting the operation window must still bind raw daily requests correctly.
    resumed = ReplayTushareRefreshBundle((replay,))
    resumed.select_market_window(last_session="2026-08-03", as_of=date(2026, 8, 4))
    assert resumed.query_raw(
        "daily_basic", params={"trade_date": "20260803"}, fields=DAILY_BASIC_SOURCE_FIELDS,
    ).items
    provider = ReplayTushareProvider(replay)
    source = TushareDailyBasicSource(provider)
    response = source.collect_session(session="2026-08-03", instrument_codes=("000001.SZ",))
    observed = dict(zip(response.fields, response.items[0], strict=True))
    assert observed["pe"] == "12.5"
    assert observed["pb"] is None
    assert not source.collect_session(
        session="2026-08-04", instrument_codes=("000001.SZ",),
    ).items
    assert not provider.query_raw(
        "daily_basic", params={"trade_date": "20260803", "ts_code": "000002.SZ"},
        fields=DAILY_BASIC_SOURCE_FIELDS,
    ).items
    for params in (
        {"trade_date": "20260805"}, {"trade_date": "2026083"},
        {"trade_date": "20260803", "offset": 0},
    ):
        with pytest.raises(TushareSourceError, match="REPLAY_REQUEST_MISMATCH"):
            provider.query_raw("daily_basic", params=params, fields=DAILY_BASIC_SOURCE_FIELDS)

    # An absent source recording and a malformed recorded column are not empty days.
    for snapshot in ({}, {"daily_basic": [{"ts_code": "000001.SZ"}]}):
        payload["snapshot"] = snapshot
        replay.write_text(json.dumps(payload))
        with pytest.raises(TushareSourceError, match="REPLAY_REQUEST_MISMATCH"):
            ReplayTushareProvider(replay).query_raw(
                "daily_basic", params={"trade_date": "20260803"},
                fields=DAILY_BASIC_SOURCE_FIELDS,
            )


def test_daily_basic_replay_capped_day_resumes_from_raw_receipts(tmp_path: Path) -> None:
    from thesistrace.adapters.tushare_daily_basic import (
        DAILY_BASIC_SOURCE_FIELDS,
        DailyBasicCheckpoint,
        TushareDailyBasicSource,
    )

    codes = tuple(f"{index:06d}.SZ" for index in range(6001))
    rows = []
    for code in codes:
        row = dict.fromkeys(DAILY_BASIC_SOURCE_FIELDS)
        row.update(ts_code=code, trade_date="20260803", pe="15")
        rows.append(row)
    replay = tmp_path / "capped-day.json"
    replay.write_text(json.dumps({
        "format": "thesistrace-tushare-refresh-replay", "version": 3,
        "request_start": "2026-08-03", "request_end": "2026-08-03",
        "snapshot": {"daily_basic": rows}, "financial": {}, "financial_refresh": None,
    }))
    provider = ReplayTushareProvider(replay)
    raw = provider.query_raw(
        "daily_basic", params={"trade_date": "20260803"}, fields=DAILY_BASIC_SOURCE_FIELDS,
    )
    assert len(raw.items) == 6000
    checkpoint = DailyBasicCheckpoint(tmp_path / "receipts", collection_key="refresh:one")
    result = TushareDailyBasicSource(provider).collect_session(
        session="2026-08-03", instrument_codes=codes,
        checkpoint=checkpoint,
    )
    sealed = checkpoint.seal(("2026-08-03",))
    assert checkpoint.verify_evidence(sealed) == ("2026-08-03",)
    assert len(result.items) == 6001
    assert {row[0] for row in result.items} == set(codes)

    # Change the recorded values; reopening the same operation must use its saved observation.
    for row in rows:
        row["pe"] = "99"
    replay.write_text(json.dumps({
        "format": "thesistrace-tushare-refresh-replay", "version": 3,
        "request_start": "2026-08-03", "request_end": "2026-08-03",
        "snapshot": {"daily_basic": rows}, "financial": {}, "financial_refresh": None,
    }))
    resumed = TushareDailyBasicSource(ReplayTushareProvider(replay)).collect_session(
        session="2026-08-03", instrument_codes=codes,
        checkpoint=DailyBasicCheckpoint(tmp_path / "receipts", collection_key="refresh:one"),
    )
    assert resumed == result


def test_indicator_replay_filters_report_period_and_preserves_cap(tmp_path):
    path = tmp_path / "indicator.json"
    rows = [["000001.SZ", f"{year}1231", f"{year + 1}0420", year]
            for year in range(1900, 2026)]
    path.write_text(json.dumps({
        "format": "thesistrace-tushare-product-replay", "version": 1,
        "request_start": "2026-08-07", "request_end": "2026-08-14", "snapshot": {},
        "financial": {"fina_indicator": {"000001.SZ": {
            "fields": ["ts_code", "end_date", "ann_date", "eps"], "items": rows,
        }}},
    }))
    provider = ReplayTushareProvider(path)
    fields = ("ts_code", "end_date", "ann_date", "eps")
    result = provider.query_raw("fina_indicator", params={
        "ts_code": "000001.SZ", "start_date": "20241231", "end_date": "20251231",
    }, fields=fields)
    assert result.items == tuple(tuple(row) for row in rows[-2:])
    capped = provider.query_raw("fina_indicator", params={
        "ts_code": "000001.SZ", "start_date": "19000101", "end_date": "20260814",
    }, fields=fields)
    assert len(capped.items) == 100
    for bounds in [("20250101", "20240101"), ("20260230", "20260301"),
                   ("20250101", "20260815")]:
        with pytest.raises(TushareSourceError, match="REPLAY_REQUEST_MISMATCH"):
            provider.query_raw("fina_indicator", params={
                "ts_code": "000001.SZ", "start_date": bounds[0], "end_date": bounds[1],
            }, fields=fields)

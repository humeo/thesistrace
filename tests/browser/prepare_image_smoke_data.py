from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import boto3
import pyarrow as pa
from botocore.exceptions import ClientError

sys.path.insert(0, "/qualification")
from benchmark_financial_io import build_market_benchmark_stream  # noqa: E402

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.source import (
    CanonicalBootstrapStream,
    CanonicalColumnarSessionPartition,
)
from thesistrace.entrypoints.runtime import CoreSettings

START = "2009-12-07"
END = "2026-08-05"
LAGGED_END = "2026-08-11"
QUALIFICATION_INSTRUMENT_COUNT = 30


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("initial", "lagged", "recovered"),
        nargs="?",
        default="initial",
    )
    mode = parser.parse_args().mode
    settings = CoreSettings.from_environment()
    if mode == "initial":
        _ensure_bucket(settings)
    if mode == "recovered":
        _publish_financial_candidate(settings, LAGGED_END, "recovered")
        return
    end = END if mode == "initial" else LAGGED_END
    sessions = _weekdays(START, end)
    store = MountedGenerationStore(settings.data_mount)
    market = store.materialize_bootstrap_stream(
        _qualification_market_stream(sessions),
        prepared_at=datetime.fromisoformat(f"{end}T10:00:00+00:00"),
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        current = lifecycle.current_pointer()
        if current is None:
            raise RuntimeError("Image Smoke bootstrap Head is unavailable")
        operation_id = f"production-image-smoke-market-head-{mode}"
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=market.manifest_sha256,
            lease_seconds=900,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=current.generation_manifest_sha256,
            candidate_generation_manifest_sha256=market.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    if mode == "lagged":
        print(
            json.dumps(
                {
                    "coverage_start": START,
                    "data_through_session": end,
                    "generation_manifest_sha256": market.manifest_sha256,
                    "mode": mode,
                    "research_session_count": len(sessions),
                },
                sort_keys=True,
            )
        )
        return
    _publish_financial_candidate(settings, end, mode)


def _publish_financial_candidate(settings: CoreSettings, end: str, mode: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        pointer = DatasetLifecycle(database, settings.data_mount).current_pointer()
        if pointer is None:
            raise RuntimeError("Image Smoke Dataset Head is unavailable")
        generation_manifest_sha256 = pointer.generation_manifest_sha256
    finally:
        database.close()
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    replay = _qualification_financial_replay(
        fixture_root / "tushare-financial-product-replay.json"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8") as file:
        json.dump(replay, file, sort_keys=True)
        file.flush()
        completed = subprocess.run(
            [
                "thesistrace-data-operator",
                "refresh-financial",
                "--idempotency-key",
                f"production-image-smoke-financial-publication-{mode}",
                "--generation-manifest-sha256",
                generation_manifest_sha256,
                "--capability-report",
                str(fixture_root / "tushare-financial-capability.json"),
                "--observation-through-session",
                end,
                "--replay",
                file.name,
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Image Smoke Financial Refresh failed: {completed.stderr}")
    outcome = json.loads(completed.stdout)
    print(
        json.dumps(
            {
                "coverage_start": START,
                "data_through_session": end,
                "generation_manifest_sha256": outcome["generation_manifest_sha256"],
                "mode": mode,
                "operator_status": outcome["status"],
            },
            sort_keys=True,
        )
    )


def _ensure_bucket(settings: CoreSettings) -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        try:
            s3.create_bucket(Bucket=settings.s3_bucket)
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code")) not in {
                "BucketAlreadyExists",
                "BucketAlreadyOwnedByYou",
            }:
                raise
    finally:
        s3.close()


def _qualification_market_stream(sessions: list[str]) -> CanonicalBootstrapStream:
    source = build_market_benchmark_stream(
        sessions,
        QUALIFICATION_INSTRUMENT_COUNT,
        QUALIFICATION_INSTRUMENT_COUNT,
        len(sessions),
    )
    session_ordinals = {session: ordinal for ordinal, session in enumerate(sessions)}

    def partitions():
        for partition in source.partitions():
            if not isinstance(partition, CanonicalColumnarSessionPartition):
                raise RuntimeError("Image Smoke market partition must be columnar")
            tables = dict(partition.tables)
            tables["eod_prices"] = _qualification_prices(
                tables["eod_prices"], session_ordinals
            )
            yield CanonicalColumnarSessionPartition(
                sessions=partition.sessions,
                tables=tables,
            )

    return CanonicalBootstrapStream(
        source_name="production-image-qualification-market",
        source_lineage={"profile": "production-image-qualification-v1"},
        static=source.static,
        covered_session_range=source.covered_session_range,
        partitions=partitions,
    )


def _qualification_prices(
    table: pa.Table,
    session_ordinals: dict[str, int],
) -> pa.Table:
    sessions = table["session_date"].combine_chunks().to_pylist()
    instruments = table["instrument_id"].combine_chunks().to_pylist()
    replacements: dict[str, list[Decimal]] = {
        name: []
        for name in (
            "open_raw",
            "high_raw",
            "low_raw",
            "close_raw",
            "pre_close_reference_raw",
            "price_change_raw",
            "pct_change_ratio",
            "open_adj",
            "high_adj",
            "low_adj",
            "close_adj",
        )
    }
    for session, instrument_id in zip(sessions, instruments, strict=True):
        ordinal = session_ordinals[session.isoformat()]
        instrument_ordinal = int(str(instrument_id).split(":", 1)[1].split(".", 1)[0])
        slope = Decimal(QUALIFICATION_INSTRUMENT_COUNT + 1 - instrument_ordinal) / Decimal(
            1000
        )
        previous = Decimal(100 + 10 * instrument_ordinal) + slope * max(ordinal - 1, 0)
        close = Decimal(100 + 10 * instrument_ordinal) + slope * ordinal
        open_value = previous
        high = max(open_value, close) + Decimal("0.0100")
        low = min(open_value, close) - Decimal("0.0100")
        change = close - previous
        ratio = (
            Decimal(0)
            if previous == 0
            else (change / previous).quantize(Decimal("0.00000001"))
        )
        raw_values = {
            "open_raw": open_value,
            "high_raw": high,
            "low_raw": low,
            "close_raw": close,
            "pre_close_reference_raw": previous,
            "price_change_raw": change,
            "pct_change_ratio": ratio,
        }
        for name, value in raw_values.items():
            replacements[name].append(value)
        for name, value in {
            "open_adj": open_value,
            "high_adj": high,
            "low_adj": low,
            "close_adj": close,
        }.items():
            replacements[name].append(value)

    arrays: list[pa.Array] = []
    for field in table.schema:
        if field.name in replacements:
            arrays.append(pa.array(replacements[field.name], type=field.type))
        else:
            arrays.append(table[field.name].combine_chunks())
    return pa.Table.from_arrays(arrays, schema=table.schema)


def _qualification_financial_replay(path: Path) -> dict[str, object]:
    replay = json.loads(path.read_text(encoding="utf-8"))
    financial = replay.get("financial")
    if not isinstance(financial, dict):
        raise RuntimeError("Image Smoke Financial replay is invalid")
    value_fields = {
        "income": ("total_revenue", "n_income_attr_p"),
        "balancesheet": (
            "total_assets",
            "total_liab",
            "total_hldr_eqy_exc_min_int",
        ),
        "cashflow": ("n_cashflow_act",),
    }
    expanded: dict[str, object] = {}
    for endpoint, fields_to_vary in value_fields.items():
        endpoint_replay = financial.get(endpoint)
        if not isinstance(endpoint_replay, dict):
            raise RuntimeError(f"Image Smoke {endpoint} replay is invalid")
        template = endpoint_replay.get("000001.SZ")
        if not isinstance(template, dict):
            raise RuntimeError(f"Image Smoke {endpoint} replay template is unavailable")
        fields = list(template["fields"])
        template_items = template["items"]
        if not isinstance(template_items, list) or len(template_items) != 1:
            raise RuntimeError(f"Image Smoke {endpoint} replay template is invalid")
        instruments: dict[str, object] = {}
        for ordinal in range(1, QUALIFICATION_INSTRUMENT_COUNT + 1):
            ts_code = f"{ordinal:06d}.SZ"
            item = list(template_items[0])
            item[fields.index("ts_code")] = ts_code
            for field_name in fields_to_vary:
                item[fields.index(field_name)] = str(
                    int(str(item[fields.index(field_name)])) * ordinal
                )
            instruments[ts_code] = {"fields": fields, "items": [item]}
        expanded[endpoint] = instruments
    replay["financial"] = expanded
    return replay


def _weekdays(start: str, end: str) -> list[str]:
    cursor = date.fromisoformat(start)
    last = date.fromisoformat(end)
    values: list[str] = []
    while cursor <= last:
        if cursor.weekday() < 5:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


if __name__ == "__main__":
    main()

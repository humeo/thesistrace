from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, "/qualification")
from benchmark_financial_io import build_market_benchmark_stream  # noqa: E402

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings

START = "2009-12-07"
END = "2026-08-05"
LAGGED_END = "2026-08-11"


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
        build_market_benchmark_stream(sessions, 1, 1, len(sessions)),
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
            str(fixture_root / "tushare-financial-product-replay.json"),
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

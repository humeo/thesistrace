from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import boto3

from thesistrace._postgres import PostgresDatabase
from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.canonical_mapping import field_catalog
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture


def publish_current_data(settings: CoreSettings) -> tuple[str, ...]:
    sessions = _weekday_sessions(date(2026, 8, 3), 75)
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (
            BenchmarkLevel("2010-01-04", "3500"),
            *(
                BenchmarkLevel(session, str(4000 + index))
                for index, session in enumerate(sessions)
            ),
        ),
        published_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
    )
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
        except s3.exceptions.BucketAlreadyOwnedByYou:
            pass
    finally:
        s3.close()
    template = build_minimal_canonical_fixture()
    instrument_template = template["instruments"][0]
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    industry = template["industry_membership"][0]
    instruments = []
    instrument_ids = []
    for index in range(1, 52):
        ts_code = f"{index:06d}.SZ"
        instrument_id = f"equity:{ts_code}"
        instrument_ids.append(instrument_id)
        instruments.append(
            {
                **instrument_template,
                "instrument_id": instrument_id,
                "ts_code": ts_code,
            }
        )
    universe = {"instrument_ids": instrument_ids, "status": "available"}
    canonical = {
        **template,
        "field_catalog": [
            next(
                row
                for row in field_catalog(sessions[0])
                if row["field_id"] == "price.close.adjusted"
            )
        ],
        "research_calendar": list(sessions),
        "instruments": instruments,
        "prices": [
            {**price, "instrument_id": instrument_id, "session": session}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "trading_states": [
            {**state, "instrument_id": instrument_id, "session": session}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "price_limits": [
            {**limit, "instrument_id": instrument_id, "session": session}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "base_pool": [
            {"session": session, "instrument_ids": instrument_ids} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
        "industry_membership": [
            {**industry, "instrument_id": instrument_id}
            for instrument_id in instrument_ids
        ],
    }
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        source_name="research-agent-mcp-acceptance",
        source_lineage={"contract": "research-agent-mcp"},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id="research-agent-mcp-head",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="research-agent-mcp-head",
        )
    finally:
        database.close()
    return sessions


def run_research_worker_once(settings: CoreSettings) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            "research",
            "--once",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path.cwd(),
        env={**os.environ, **core_environment(settings)},
    )


def assert_worker_succeeded(completed: subprocess.CompletedProcess[str]) -> None:
    assert completed.returncode == 0, {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4096:],
        "stderr": completed.stderr[-4096:],
    }


def core_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
        "THESISTRACE_BENCHMARK_MOUNT": str(settings.benchmark_mount),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
            settings.batch_attempt_control_directory
        ),
    }


def _weekday_sessions(start: date, count: int) -> tuple[str, ...]:
    sessions: list[str] = []
    cursor = start
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(sessions)

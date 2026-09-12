from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import boto3
from core_runtime import TEST_RESEARCHER, internal_api_origin

from thesistrace._postgres import PostgresDatabase
from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.canonical_mapping import field_catalog
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.researcher import ResearcherService


def publish_current_data(
    settings: CoreSettings, *, daily_fields: bool = False, indicator_fields: bool = False,
) -> tuple[str, ...]:
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
    if daily_fields:
        from thesistrace.data.canonical_mapping import daily_basic_field_catalog
        from thesistrace.data.fields import DAILY_BASIC_FIELDS

        canonical["field_catalog"] = [
            *field_catalog(sessions[0]), *daily_basic_field_catalog(sessions[0]),
        ]
        canonical["daily_basic_sessions"] = [{"session": session} for session in sessions]
        canonical["daily_basic"] = [{
            **dict.fromkeys(field.source_column for field in DAILY_BASIC_FIELDS),
            "session": row["session"], "instrument_id": row["instrument_id"],
            "source_close": "999", "pe": "15", "turnover_rate": "0.025",
        } for row in canonical["prices"]]
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        source_name="research-agent-mcp-acceptance",
        source_lineage={"contract": "research-agent-mcp"},
    )
    if indicator_fields:
        from thesistrace.data.financial_collection import RawFinancialBatchStore
        from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
        from thesistrace.data.financial_indicator_evidence import FinancialIndicatorObservationStore
        from thesistrace.data.financial_indicator_source import (
            FINANCIAL_INDICATOR_SOURCE_FIELDS,
        )
        from thesistrace.data.source import RawSourceResponse
        from thesistrace.publication.serialization import canonical_json_bytes

        raw = RawFinancialBatchStore(settings.data_mount)
        observations = FinancialIndicatorObservationStore(raw)
        collections = []
        identities = {item["ts_code"]: item["instrument_id"] for item in instruments}
        end = sessions[-1].replace("-", "")
        for index, (code, instrument) in enumerate(identities.items(), 1):
            values = {
                "ts_code": code, "end_date": "20260630", "ann_date": "20260802",
                "eps": index / 10, "bps": 10 + index, "current_ratio": 2,
                "roe": 5 + index, "q_roe": 2 + index, "netprofit_yoy": index - 10,
            }
            observation = observations.save(
                RawSourceResponse(
                    fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
                    items=(tuple(values.get(field)
                                 for field in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
                ), observed_at=datetime(2026, 8, 3, tzinfo=UTC),
            )
            collections.append(raw.store(canonical_json_bytes({
                "source": "fina_indicator", "collection_key": f"mcp-indicator-{code}",
                "instrument_id": instrument, "ts_code": code,
                "start_date": "19900101", "end_date": end, "checked_through": sessions[-1],
                "completed_requests": [{
                    "request": {
                        "api_name": "fina_indicator",
                        "params": {"ts_code": code, "start_date": "19900101", "end_date": end},
                        "fields": list(FINANCIAL_INDICATOR_SOURCE_FIELDS),
                    }, "observation_sha256": observation,
                }],
            })))
        candidate = FinancialIndicatorCandidateStore(settings.data_mount).build(
            collection_evidence_sha256s=collections, instrument_ids=identities, sessions=sessions,
        )
        generation = MountedGenerationStore(settings.data_mount).compose_with_indicator_candidate(
            generation.manifest_sha256, candidate,
            prepared_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        ResearcherService(database).bootstrap(TEST_RESEARCHER)
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
        "THESISTRACE_AUTH_INTERNAL_ORIGIN": os.environ["THESISTRACE_AUTH_INTERNAL_ORIGIN"],
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
        "THESISTRACE_BENCHMARK_MOUNT": str(settings.benchmark_mount),
        "THESISTRACE_INTERNAL_API_ORIGIN": internal_api_origin(settings),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
            settings.batch_attempt_control_directory
        ),
        "THESISTRACE_RESEARCH_AGENT_RESEARCHER_ID": str(
            TEST_RESEARCHER.researcher_id
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

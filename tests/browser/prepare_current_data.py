from __future__ import annotations

import json
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture

SESSIONS = (
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
    "2026-08-10",
    "2026-08-11",
)


def main() -> None:
    settings = CoreSettings.from_environment()
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

    canonical = _canonical()
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        source_name="ticket-25-browser-fixture",
        source_lineage={"contract": "prepared-current-data-v1"},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id="ticket-25-browser-head",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="ticket-25-browser-head",
        )
    finally:
        database.close()
    print(
        json.dumps(
            {
                "coverage_start": SESSIONS[0],
                "data_through_session": SESSIONS[-1],
                "generation_manifest_sha256": generation.manifest_sha256,
            },
            sort_keys=True,
        )
    )


def _canonical() -> dict[str, object]:
    template = build_minimal_canonical_fixture()
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "research_calendar": list(SESSIONS),
        "prices": [{**price, "session": session} for session in SESSIONS],
        "trading_states": [{**state, "session": session} for session in SESSIONS],
        "price_limits": [{**limit, "session": session} for session in SESSIONS],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]}
            for session in SESSIONS
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in SESSIONS]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


if __name__ == "__main__":
    main()

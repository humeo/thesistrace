from __future__ import annotations

import json
import subprocess
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings

SESSIONS = (
    "2010-01-04",
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
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

    store = MountedGenerationStore(settings.data_mount)
    database = PostgresDatabase(settings.database_url)
    database.open()
    lifecycle = DatasetLifecycle(database, settings.data_mount)
    current = lifecycle.current_pointer()
    if current is None:
        raise RuntimeError("private Data Operator bootstrap Head is unavailable")
    market = store.inspect_root(current.generation_manifest_sha256)
    if market.data_through_session != SESSIONS[-1]:
        raise RuntimeError("private Data Operator bootstrap coverage is unexpected")
    database.close()
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    completed = subprocess.run(
        [
            "thesistrace-data-operator",
            "refresh-financial",
            "--idempotency-key",
            "financial-release-initial-publication",
            "--generation-manifest-sha256",
            market.manifest_sha256,
            "--capability-report",
            str(fixture_root / "tushare-financial-capability.json"),
            "--observation-through-session",
            SESSIONS[-1],
            "--replay",
            str(fixture_root / "tushare-financial-product-replay.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"initial Financial Refresh failed: {completed.stderr}")
    outcome = json.loads(completed.stdout)
    generation_manifest_sha256 = str(outcome["generation_manifest_sha256"])
    print(
        json.dumps(
            {
                "coverage_start": SESSIONS[0],
                "data_through_session": SESSIONS[-1],
                "generation_manifest_sha256": generation_manifest_sha256,
                "operator_status": outcome["status"],
            },
            sort_keys=True,
        )
    )
if __name__ == "__main__":
    main()

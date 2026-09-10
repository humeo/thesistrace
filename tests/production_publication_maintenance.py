"""Qualify a full page inside the final, resource-limited maintenance image."""

import json
import os
import resource
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import boto3

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.publication import PublicationMaintenance, publication_request_config

assert os.environ["THESISTRACE_ENVIRONMENT"] == "test"
quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
assert int(quota) / int(period) == 0.5
assert int(Path("/sys/fs/cgroup/memory.max").read_text()) == 256 * 1024**2
bucket = "maintenance-qualification-" + uuid4().hex
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["THESISTRACE_S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ["THESISTRACE_S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["THESISTRACE_S3_SECRET_ACCESS_KEY"],
    config=publication_request_config(),
)
database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
database.open()
verify_core_schema(database)
with database.transaction() as tx:
    saved = tx.execute(
        "SELECT * FROM publication.maintenance_state ORDER BY job"
    ).fetchall()
try:
    s3.create_bucket(Bucket=bucket)
    keys = [f"publication/v1/sha256/00/{n:064x}" for n in range(1001)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda key: s3.put_object(Bucket=bucket, Key=key, Body=b"young"), keys
            )
        )
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now(), last_key = '', "
            "cutoff = NULL, sweep_started_at = NULL WHERE job = 'orphan_scan'"
        )
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() + interval '1 day' "
            "WHERE job = 'queued_deletions'"
        )
    result = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert result["listed"] == 1000, result
    assert result["processed"] == 1000, result
    assert result["deleted"] == 0 and result["sweep_completed"] is False, result
    assert (
        PublicationMaintenance(database, s3, bucket=bucket).run_once()["status"]
        == "idle"
    )
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() "
            "WHERE job = 'orphan_scan'"
        )
    resumed = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert resumed["listed"] == 1 and resumed["sweep_completed"] is True, resumed
    print(
        json.dumps(
            {
                "full_page": result,
                "resumed": resumed,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * 1024,
                "memory_limit_bytes": 256 * 1024**2,
                "cpu_limit": 0.5,
            }
        )
    )
finally:
    with database.transaction() as tx:
        for row in saved:
            tx.execute(
                "UPDATE publication.maintenance_state SET next_due_at = %(next_due_at)s, "
                "last_key = %(last_key)s, cutoff = %(cutoff)s, "
                "sweep_started_at = %(sweep_started_at)s, "
                "last_sweep_completed_at = %(last_sweep_completed_at)s, "
                "failure_count = %(failure_count)s, last_error = %(last_error)s "
                "WHERE job = %(job)s",
                row,
            )
    database.close()
    s3.close()
    # The canonical runner removes this test-owned bucket with its owned volume.

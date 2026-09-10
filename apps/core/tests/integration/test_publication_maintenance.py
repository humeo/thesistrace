from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event
from uuid import uuid4

import pytest

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.schema import initialize_core


@pytest.fixture
def maintenance_dependencies(core_settings, rustfs_admin):
    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    with database.transaction() as tx:
        original_objects = [
            r["sha256"] for r in tx.execute("SELECT sha256 FROM publication.objects")
        ]
        original_manifests = [
            r["sha256"] for r in tx.execute("SELECT sha256 FROM publication.manifests")
        ]
    bucket = core_settings.s3_bucket + "-" + uuid4().hex[:8]
    try:
        rustfs_admin.create_bucket(Bucket=bucket)
        with database.transaction() as tx:
            tx.execute(
                "UPDATE publication.maintenance_state SET next_due_at = now(), "
                "last_key = '', cutoff = NULL, sweep_started_at = NULL, "
                "failure_count = 0, last_error = NULL"
            )
        yield database, rustfs_admin, bucket
    finally:
        with database.transaction() as tx:
            tx.execute(
                "DELETE FROM publication.manifest_objects WHERE manifest_sha256 <> ALL(%s)",
                (original_manifests,),
            )
            tx.execute(
                "DELETE FROM publication.manifests WHERE sha256 <> ALL(%s)", (original_manifests,)
            )
            tx.execute(
                "DELETE FROM publication.objects WHERE sha256 <> ALL(%s)", (original_objects,)
            )
        database.close()


def test_empty_store_scan_has_a_durable_cooldown(maintenance_dependencies):
    from thesistrace.publication.maintenance import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    first = PublicationMaintenance(database, s3, bucket=bucket)
    # The two jobs start due: one queue step and one empty-prefix scan.
    steps = [first.run_once(), first.run_once()]
    scan = next(step for step in steps if step["job"] == "orphan_scan")
    assert scan["listed"] == 0
    assert scan["sweep_completed"] is True
    other = PublicationMaintenance(database, s3, bucket=bucket)
    assert other.run_once()["status"] == "idle"
    with database.transaction() as tx:
        row = tx.execute(
            "SELECT next_due_at FROM publication.maintenance_state WHERE job = 'orphan_scan'"
        ).fetchone()
    assert row["next_due_at"] > datetime.now(UTC) + timedelta(minutes=14)


def test_orphan_budget_resumes_after_deleted_cursor_without_skipping(maintenance_dependencies):
    from thesistrace.publication.maintenance import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    keys = []
    for n in range(11):
        content = f"orphan-{n}".encode()
        digest = sha256(content).hexdigest()
        key = f"publication/v1/sha256/{digest[:2]}/{digest}"
        s3.put_object(Bucket=bucket, Key=key, Body=content)
        keys.append(key)
    cutoff = datetime.now(UTC) + timedelta(minutes=5)
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() + interval '1 day' "
            "WHERE job = 'queued_deletions'"
        )
        tx.execute(
            "UPDATE publication.maintenance_state SET cutoff = %s, sweep_started_at = %s "
            "WHERE job = 'orphan_scan'",
            (cutoff, cutoff + timedelta(hours=1)),
        )
    first = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert first["deleted"] == 10
    assert first["sweep_completed"] is False
    assert [x["Key"] for x in s3.list_objects_v2(Bucket=bucket).get("Contents", [])] == [max(keys)]
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() WHERE job = 'orphan_scan'"
        )
    second = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert second["deleted"] == 1
    assert second["sweep_completed"] is True
    assert not s3.list_objects_v2(Bucket=bucket).get("Contents")


def test_failed_scan_backs_off_durably_without_blocking_queued_deletions(maintenance_dependencies):
    from botocore.stub import Stubber

    from thesistrace.publication.maintenance import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    with Stubber(s3) as failures:
        failures.add_client_error("list_objects_v2", service_error_code="AccessDenied")
        result = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert result["job"] == "orphan_scan"
    assert result["status"] == "failed"
    with database.transaction() as tx:
        state = tx.execute(
            "SELECT failure_count, next_due_at FROM publication.maintenance_state "
            "WHERE job = 'orphan_scan'"
        ).fetchone()
    assert state["failure_count"] == 1
    assert state["next_due_at"] > datetime.now(UTC) + timedelta(seconds=55)
    assert (
        PublicationMaintenance(database, s3, bucket=bucket).run_once()["job"] == "queued_deletions"
    )


def test_duplicate_maintenance_process_cannot_scan_while_owner_is_busy(maintenance_dependencies):
    from thesistrace.publication.maintenance import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    started, release = Event(), Event()

    def hold(**_):
        started.set()
        assert release.wait(10)

    s3.meta.events.register("before-call.s3.ListObjectsV2", hold)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(PublicationMaintenance(database, s3, bucket=bucket).run_once)
            try:
                assert started.wait(5)
                assert (
                    PublicationMaintenance(database, s3, bucket=bucket).run_once()["status"]
                    == "busy"
                )
            finally:
                release.set()
            assert future.result(timeout=10)["status"] == "completed"
    finally:
        s3.meta.events.unregister("before-call.s3.ListObjectsV2", hold)


def test_explicit_deletion_queue_is_bounded_and_preserves_referenced_results(
    maintenance_dependencies,
):
    from thesistrace.publication import JsonPayload, Publication
    from thesistrace.publication.maintenance import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    publication = Publication(database, s3, bucket=bucket)
    for n in range(11):
        prepared = publication.prepare(
            kind="maintenance.probe",
            payloads={"summary": JsonPayload({"item": n, "bucket": bucket})},
            provenance={},
        )
        with database.transaction() as tx:
            ref = publication.record(tx, prepared)
            publication.release_manifest_in_transaction(
                tx, ref.manifest_sha256, still_referenced=False
            )
    retained = publication.prepare(
        kind="maintenance.probe",
        payloads={"summary": JsonPayload({"retained": bucket})},
        provenance={},
    )
    with database.transaction() as tx:
        ref = publication.record(tx, retained)
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() + interval '1 day' "
            "WHERE job = 'orphan_scan'"
        )
    first = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert first["deleted"] == 10
    assert len(s3.list_objects_v2(Bucket=bucket).get("Contents", [])) == 2
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() "
            "WHERE job = 'queued_deletions'"
        )
    assert PublicationMaintenance(database, s3, bucket=bucket).run_once()["deleted"] == 1
    assert len(s3.list_objects_v2(Bucket=bucket).get("Contents", [])) == 1
    assert publication.read(ref).kind == "maintenance.probe"


def test_process_failure_does_not_bypass_shared_scan_interval(maintenance_dependencies):
    from thesistrace.publication.maintenance import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies

    def crash(**_):
        raise RuntimeError("injected process failure")

    s3.meta.events.register("before-call.s3.ListObjectsV2", crash)
    try:
        with pytest.raises(RuntimeError, match="injected process failure"):
            PublicationMaintenance(database, s3, bucket=bucket).run_once()
    finally:
        s3.meta.events.unregister("before-call.s3.ListObjectsV2", crash)
    # A replacement may service the other queue, but cannot immediately rescan.
    result = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert result["job"] == "queued_deletions"
    assert PublicationMaintenance(database, s3, bucket=bucket).run_once()["status"] == "idle"


def test_maintenance_command_runs_without_dataset_or_auth_runtime(maintenance_dependencies):
    import json
    import os
    import subprocess
    import sys

    database, s3, bucket = maintenance_dependencies
    result = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.publication_maintenance", "--once"],
        env={
            **os.environ,
            "THESISTRACE_S3_BUCKET": bucket,
            "THESISTRACE_DATA_MOUNT": "/nonexistent-maintenance-dataset",
            "THESISTRACE_AUTH_INTERNAL_ORIGIN": "http://unreachable.invalid",
        },
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert any(
        e["event"] == "publication_maintenance_step" and e["status"] == "completed" for e in events
    )


def _scan_due(database):
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() WHERE job = 'orphan_scan'"
        )
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() + interval '1 day' "
            "WHERE job = 'queued_deletions'"
        )


def test_more_than_one_page_resumes_with_fixed_cutoff_and_protects_young_objects(
    maintenance_dependencies,
):
    from thesistrace.publication import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies

    def put(n):
        digest = sha256(f"{bucket}-{n}".encode()).hexdigest()
        key = f"publication/v1/sha256/{digest[:2]}/{digest}"
        s3.put_object(Bucket=bucket, Key=key, Body=b"young")
        return key

    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = sorted(pool.map(put, range(1001)))
    _scan_due(database)
    first = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert (first["listed"], first["processed"], first["deleted"]) == (1000, 1000, 0)
    assert first["sweep_completed"] is False
    with database.transaction() as tx:
        state = tx.execute(
            "SELECT last_key, cutoff FROM publication.maintenance_state WHERE job = 'orphan_scan'"
        ).fetchone()
    assert state["last_key"] == keys[999]
    # StartAfter remains meaningful even when the previous cursor object is gone.
    s3.delete_object(Bucket=bucket, Key=keys[999])
    _scan_due(database)
    second = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert (second["listed"], second["deleted"], second["sweep_completed"]) == (1, 0, True)
    assert s3.head_object(Bucket=bucket, Key=keys[1000])["ContentLength"] == 5


def test_reuploaded_object_is_rechecked_before_delete(maintenance_dependencies):
    from thesistrace.publication import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    digest = sha256(bucket.encode()).hexdigest()
    key = f"publication/v1/sha256/{digest[:2]}/{digest}"
    s3.put_object(Bucket=bucket, Key=key, Body=b"new-upload")

    def old_listing(parsed, **_):
        # A listing can describe the previous object incarnation. HEAD must protect the new one.
        for item in parsed["Contents"]:
            item["LastModified"] = datetime.now(UTC) - timedelta(hours=2)

    s3.meta.events.register("after-call.s3.ListObjectsV2", old_listing)
    try:
        _scan_due(database)
        result = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    finally:
        s3.meta.events.unregister("after-call.s3.ListObjectsV2", old_listing)
    assert result["deleted"] == 0
    assert s3.get_object(Bucket=bucket, Key=key)["Body"].read() == b"new-upload"


def test_connection_loss_stops_owner_and_replacement_obeys_reservation(maintenance_dependencies):
    from psycopg import OperationalError

    from thesistrace.publication import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    _scan_due(database)

    def disconnect(**_):
        with database.transaction() as tx:
            rows = tx.execute(
                "SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory' "
                "AND objid = hashtext('thesistrace-publication-maintenance')::oid "
                "AND granted"
            ).fetchall()
            assert len(rows) == 1
            tx.execute("SELECT pg_terminate_backend(%s)", (rows[0]["pid"],))

    s3.meta.events.register("before-call.s3.ListObjectsV2", disconnect)
    try:
        with pytest.raises(OperationalError):
            PublicationMaintenance(database, s3, bucket=bucket).run_once()
    finally:
        s3.meta.events.unregister("before-call.s3.ListObjectsV2", disconnect)
    assert PublicationMaintenance(database, s3, bucket=bucket).run_once()["status"] == "idle"


def test_step_budget_expires_after_listing_without_starting_deletions(
    maintenance_dependencies,
    monkeypatch,
):
    from thesistrace.publication import PublicationMaintenance, maintenance

    database, s3, bucket = maintenance_dependencies
    digest = sha256(bucket.encode()).hexdigest()
    key = f"publication/v1/sha256/{digest[:2]}/{digest}"
    s3.put_object(Bucket=bucket, Key=key, Body=b"content")
    clock = [0.0]
    monkeypatch.setattr(maintenance.time, "monotonic", lambda: clock[0])

    def expire(**_):
        clock[0] = 11

    s3.meta.events.register("after-call.s3.ListObjectsV2", expire)
    try:
        _scan_due(database)
        result = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    finally:
        s3.meta.events.unregister("after-call.s3.ListObjectsV2", expire)
    assert result["processed"] == 0
    assert result["sweep_completed"] is False
    with database.transaction() as tx:
        assert (
            tx.execute(
                "SELECT last_key FROM publication.maintenance_state WHERE job = 'orphan_scan'"
            ).fetchone()["last_key"]
            == ""
        )


def test_connection_lost_during_head_does_not_delete_newly_recorded_object(
    maintenance_dependencies,
):
    from psycopg import OperationalError

    from thesistrace.publication import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    digest = sha256(bucket.encode()).hexdigest()
    key = f"publication/v1/sha256/{digest[:2]}/{digest}"
    s3.put_object(Bucket=bucket, Key=key, Body=b"protected")
    _scan_due(database)
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET cutoff = now() + interval '5 minutes', "
            "sweep_started_at = now() WHERE job = 'orphan_scan'"
        )

    def lose_fence(**_):
        with database.transaction() as tx:
            rows = tx.execute(
                "SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory' "
                "AND objid = hashtext('thesistrace-publication-maintenance')::oid "
                "AND granted"
            ).fetchall()
            tx.execute("SELECT pg_terminate_backend(%s)", (rows[0]["pid"],))
        with database.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-publication-mutation'))")
            tx.execute(
                "INSERT INTO publication.objects (sha256, byte_size) VALUES (%s, 9)", (digest,)
            )

    s3.meta.events.register("after-call.s3.HeadObject", lose_fence)
    try:
        with pytest.raises(OperationalError):
            PublicationMaintenance(database, s3, bucket=bucket).run_once()
    finally:
        s3.meta.events.unregister("after-call.s3.HeadObject", lose_fence)
    assert s3.get_object(Bucket=bucket, Key=key)["Body"].read() == b"protected"


@pytest.mark.parametrize("malformation", ["descending", "empty_truncated", "wrong_prefix"])
def test_invalid_listing_is_rejected_and_backs_off(maintenance_dependencies, malformation):
    from thesistrace.publication import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies

    def corrupt(parsed, **_):
        digest = "a" * 64
        key = f"publication/v1/sha256/aa/{digest}"
        parsed["IsTruncated"] = True
        parsed["Contents"] = (
            []
            if malformation == "empty_truncated"
            else [
                {
                    "Key": key if malformation == "descending" else "foreign/key",
                    "LastModified": datetime.now(UTC),
                }
            ]
            * 2
        )

    s3.meta.events.register("after-call.s3.ListObjectsV2", corrupt)
    try:
        _scan_due(database)
        result = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    finally:
        s3.meta.events.unregister("after-call.s3.ListObjectsV2", corrupt)
    assert result["status"] == "failed"
    assert result["failure_code"] == "PUBLICATION_LIST_INVALID"
    assert PublicationMaintenance(database, s3, bucket=bucket).run_once()["status"] == "idle"


def test_killed_process_releases_ownership_without_bypassing_cooldown(maintenance_dependencies):
    import os
    import select
    import subprocess
    import sys

    from thesistrace.publication import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    _scan_due(database)
    program = """
import os
from threading import Event
import boto3
from thesistrace._postgres import PostgresDatabase
from thesistrace.publication import PublicationMaintenance, publication_request_config
s3 = boto3.client('s3', endpoint_url=os.environ['THESISTRACE_S3_ENDPOINT_URL'],
    aws_access_key_id=os.environ['THESISTRACE_S3_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['THESISTRACE_S3_SECRET_ACCESS_KEY'],
    config=publication_request_config())
db = PostgresDatabase(os.environ['THESISTRACE_DATABASE_URL'])
db.open()
def hold(**kwargs):
    print('owner-ready', flush=True)
    Event().wait(30)
s3.meta.events.register('before-call.s3.ListObjectsV2', hold)
PublicationMaintenance(db, s3, bucket=os.environ['THESISTRACE_S3_BUCKET']).run_once()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        env={**os.environ, "THESISTRACE_S3_BUCKET": bucket},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert select.select([process.stdout], [], [], 10)[0]
        assert process.stdout.readline().strip() == "owner-ready"
        assert PublicationMaintenance(database, s3, bucket=bucket).run_once()["status"] == "busy"
        process.kill()
        process.wait(timeout=10)
        assert PublicationMaintenance(database, s3, bucket=bucket).run_once()["status"] == "idle"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_lost_delete_response_does_not_advance_past_unconfirmed_object(maintenance_dependencies):
    from botocore.exceptions import ReadTimeoutError

    from thesistrace.publication import PublicationMaintenance

    database, s3, bucket = maintenance_dependencies
    digest = sha256(bucket.encode()).hexdigest()
    key = f"publication/v1/sha256/{digest[:2]}/{digest}"
    s3.put_object(Bucket=bucket, Key=key, Body=b"orphan")
    _scan_due(database)
    with database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET cutoff = now() + interval '5 minutes', "
            "sweep_started_at = now() WHERE job = 'orphan_scan'"
        )

    def lose_response(**_):
        raise ReadTimeoutError(endpoint_url="http://test-storage")

    s3.meta.events.register("after-call.s3.DeleteObject", lose_response)
    try:
        first = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    finally:
        s3.meta.events.unregister("after-call.s3.DeleteObject", lose_response)
    assert first["status"] == "failed"
    with database.transaction() as tx:
        assert (
            tx.execute(
                "SELECT last_key FROM publication.maintenance_state WHERE job = 'orphan_scan'"
            ).fetchone()["last_key"]
            == ""
        )
    _scan_due(database)
    second = PublicationMaintenance(database, s3, bucket=bucket).run_once()
    assert second["listed"] == 0 and second["sweep_completed"] is True

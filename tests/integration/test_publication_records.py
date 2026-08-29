import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core
from thesistrace.publication import (
    JsonPayload,
    Publication,
    PublicationNotFoundError,
    PublicationUnavailableError,
    PublicationVerificationError,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.publication.service import lock_publication_mutation


@pytest.fixture(autouse=True)
def _initialized_core(core_settings: CoreSettings) -> None:
    initialize_core(core_settings.database_url)


def test_record_joins_the_callers_transaction_and_read_starts_from_commit(
    core_settings: CoreSettings,
) -> None:
    with open_core_runtime(core_settings) as runtime:
        _reset_product_probe(runtime.database)
        prepared = runtime.publication.prepare(
            kind="research.result",
            payloads={"summary": JsonPayload({"annualized_return": 0.12})},
            provenance={"run_id": "run-001", "data_generation_id": "generation-001"},
        )
        assert prepared.payload_sha256s["summary"] not in runtime.publication.find_orphan_sha256s(
            uploaded_before=datetime.now(UTC) - timedelta(minutes=5)
        )

        with runtime.database.transaction() as transaction:
            first = runtime.publication.record(transaction, prepared)
            second = runtime.publication.record(transaction, prepared)
            assert first == second
            transaction.execute(
                """
                INSERT INTO publication_probe.current_bundle (singleton, manifest_sha256)
                VALUES (1, %s)
                """,
                (first.manifest_sha256,),
            )
            with pytest.raises(PublicationNotFoundError):
                runtime.publication.read(first)

        with runtime.database.transaction() as transaction:
            row = transaction.execute(
                "SELECT manifest_sha256 FROM publication_probe.current_bundle WHERE singleton = 1"
            ).fetchone()
            counts = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM publication.manifests) AS manifests,
                    (SELECT count(*) FROM publication.objects) AS objects,
                    (SELECT count(*) FROM publication.manifest_objects) AS links
                """
            ).fetchone()
        assert row == {"manifest_sha256": first.manifest_sha256}
        assert counts == {"manifests": 1, "objects": 1, "links": 1}

        verified = runtime.publication.read(first)
        assert verified.kind == "research.result"
        assert verified.provenance == {
            "run_id": "run-001",
            "data_generation_id": "generation-001",
        }
        assert verified.payloads["summary"].content == canonical_json_bytes(
            {"annualized_return": 0.12}
        )
        assert "key" not in repr(first).lower()


def test_rollback_leaves_an_invisible_orphan_and_preserves_previous_reference(
    core_settings: CoreSettings,
) -> None:
    with open_core_runtime(core_settings) as runtime:
        _reset_product_probe(runtime.database)
        baseline = runtime.publication.prepare(
            kind="publication.probe",
            payloads={"canonical": JsonPayload({"release": 1})},
            provenance={"sequence": 1},
        )
        with runtime.database.transaction() as transaction:
            baseline_ref = runtime.publication.record(transaction, baseline)
            transaction.execute(
                """
                INSERT INTO publication_probe.current_bundle (singleton, manifest_sha256)
                VALUES (1, %s)
                """,
                (baseline_ref.manifest_sha256,),
            )

        candidate = runtime.publication.prepare(
            kind="publication.probe",
            payloads={"canonical": JsonPayload({"release": 2})},
            provenance={"sequence": 2},
        )
        candidate_ref = None
        with pytest.raises(RuntimeError, match="injected rollback"):
            with runtime.database.transaction() as transaction:
                candidate_ref = runtime.publication.record(transaction, candidate)
                transaction.execute(
                    """
                    UPDATE publication_probe.current_bundle
                    SET manifest_sha256 = %s
                    WHERE singleton = 1
                    """,
                    (candidate_ref.manifest_sha256,),
                )
                raise RuntimeError("injected rollback")

        assert candidate_ref is not None
        with runtime.database.transaction() as transaction:
            row = transaction.execute(
                "SELECT manifest_sha256 FROM publication_probe.current_bundle WHERE singleton = 1"
            ).fetchone()
        assert row == {"manifest_sha256": baseline_ref.manifest_sha256}
        with pytest.raises(PublicationNotFoundError):
            runtime.publication.read(candidate_ref)
        assert candidate.payload_sha256s["canonical"] in runtime.publication.find_orphan_sha256s(
            uploaded_before=datetime.now(UTC) + timedelta(minutes=5)
        )
        assert (
            runtime.publication.collect_one_orphan(
                uploaded_before=datetime.now(UTC) - timedelta(minutes=5)
            )
            is False
        )
        cutoff = datetime.now(UTC) + timedelta(minutes=5)
        for _ in range(20):
            if candidate.payload_sha256s["canonical"] not in (
                runtime.publication.find_orphan_sha256s(uploaded_before=cutoff)
            ):
                break
            assert runtime.publication.collect_one_orphan(uploaded_before=cutoff) is True
        assert candidate.payload_sha256s["canonical"] not in (
            runtime.publication.find_orphan_sha256s(uploaded_before=cutoff)
        )
        assert runtime.publication.read(baseline_ref).provenance == {"sequence": 1}


def test_orphan_collection_rechecks_a_new_reference_under_the_mutation_lock(
    core_settings: CoreSettings,
) -> None:
    with open_core_runtime(core_settings) as runtime:
        _reset_product_probe(runtime.database)
        prepared = runtime.publication.prepare(
            kind="publication.probe",
            payloads={"canonical": JsonPayload({"race": "record-before-delete"})},
            provenance={"owner": "new-reference"},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            with runtime.database.transaction() as transaction:
                lock_publication_mutation(transaction)
                collection = pool.submit(
                    runtime.publication.collect_one_orphan,
                    uploaded_before=datetime.now(UTC) + timedelta(minutes=5),
                )
                published = runtime.publication.record(transaction, prepared)
            collection.result(timeout=10)

        verified = runtime.publication.read(published)
        assert verified.provenance == {"owner": "new-reference"}


def test_orphan_collection_fails_closed_when_the_bucket_is_missing(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    database = PostgresDatabase(core_settings.database_url)
    publication = Publication(
        database,
        rustfs_admin,
        bucket=f"{core_settings.s3_bucket}-missing",
    )

    with pytest.raises(PublicationUnavailableError):
        publication.collect_one_orphan(uploaded_before=datetime.now(UTC) + timedelta(minutes=5))


def test_release_collects_only_after_the_last_manifest_reference(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    shared_payload = {"shared": "immutable"}
    expected = canonical_json_bytes(shared_payload)
    with open_core_runtime(core_settings) as runtime:
        first = runtime.publication.prepare(
            kind="publication.probe",
            payloads={"canonical": JsonPayload(shared_payload)},
            provenance={"owner": "first"},
        )
        second = runtime.publication.prepare(
            kind="publication.probe",
            payloads={"canonical": JsonPayload(shared_payload)},
            provenance={"owner": "second"},
        )
        shared_sha256 = first.payload_sha256s["canonical"]
        assert second.payload_sha256s["canonical"] == shared_sha256
        with runtime.database.transaction() as transaction:
            first_ref = runtime.publication.record(transaction, first)
            second_ref = runtime.publication.record(transaction, second)

        object_key = _find_key_with_content(
            rustfs_admin,
            core_settings.s3_bucket,
            expected,
        )
        with runtime.database.transaction() as transaction:
            runtime.publication.release_manifest_in_transaction(
                transaction,
                first_ref.manifest_sha256,
                still_referenced=False,
            )
        assert runtime.publication.collect_one_pending_deletion() is False
        assert runtime.publication.read(second_ref).provenance == {"owner": "second"}
        assert (
            rustfs_admin.head_object(
                Bucket=core_settings.s3_bucket,
                Key=object_key,
            )["ResponseMetadata"]["HTTPStatusCode"]
            == 200
        )

        with runtime.database.transaction() as transaction:
            runtime.publication.release_manifest_in_transaction(
                transaction,
                second_ref.manifest_sha256,
                still_referenced=False,
            )
        assert runtime.publication.collect_one_pending_deletion() is True
        assert runtime.publication.collect_one_pending_deletion() is False
        with runtime.database.transaction() as transaction:
            counts = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM publication.manifests
                     WHERE sha256 = ANY(%s)) AS manifests,
                    (SELECT count(*) FROM publication.objects
                     WHERE sha256 = %s) AS objects,
                    (SELECT count(*) FROM publication.object_deletions
                     WHERE object_sha256 = %s) AS pending
                """,
                (
                    [first_ref.manifest_sha256, second_ref.manifest_sha256],
                    shared_sha256,
                    shared_sha256,
                ),
            ).fetchone()
        assert counts == {"manifests": 0, "objects": 0, "pending": 0}
        with pytest.raises(ClientError) as deleted:
            rustfs_admin.head_object(
                Bucket=core_settings.s3_bucket,
                Key=object_key,
            )
        assert deleted.value.response["Error"]["Code"] in {"404", "NoSuchKey"}


def test_failed_object_deletion_remains_durable_until_worker_retry(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    _reset_core_schemas(core_settings)
    payload = {"delete": "after-recovery"}
    expected = canonical_json_bytes(payload)
    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="publication.probe",
            payloads={"canonical": JsonPayload(payload)},
            provenance={"owner": "deletion-recovery"},
        )
        object_sha256 = prepared.payload_sha256s["canonical"]
        with runtime.database.transaction() as transaction:
            published = runtime.publication.record(transaction, prepared)
            runtime.publication.release_manifest_in_transaction(
                transaction,
                published.manifest_sha256,
                still_referenced=False,
            )

        object_key = _find_key_with_content(
            rustfs_admin,
            core_settings.s3_bucket,
            expected,
        )
        unreachable_s3 = boto3.client(
            "s3",
            endpoint_url="http://127.0.0.1:1",
            aws_access_key_id=core_settings.s3_access_key_id,
            aws_secret_access_key=core_settings.s3_secret_access_key,
            region_name=core_settings.s3_region,
            config=Config(
                connect_timeout=0.1,
                read_timeout=0.1,
                retries={"max_attempts": 0},
            ),
        )
        try:
            failing = Publication(
                runtime.database,
                unreachable_s3,
                bucket=core_settings.s3_bucket,
            )
            with pytest.raises(PublicationUnavailableError):
                failing.collect_one_pending_deletion()
        finally:
            unreachable_s3.close()

        with runtime.database.transaction() as transaction:
            retained = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM publication.objects
                     WHERE sha256 = %s) AS objects,
                    (SELECT count(*) FROM publication.object_deletions
                     WHERE object_sha256 = %s) AS pending
                """,
                (object_sha256, object_sha256),
            ).fetchone()
        assert retained == {"objects": 1, "pending": 1}
        assert (
            rustfs_admin.head_object(
                Bucket=core_settings.s3_bucket,
                Key=object_key,
            )["ResponseMetadata"]["HTTPStatusCode"]
            == 200
        )

    completed = subprocess.run(
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
        env={
            **os.environ,
            "THESISTRACE_INTERNAL_API_ORIGIN": "http://127.0.0.1:1",
        },
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    with open_core_runtime(core_settings) as runtime:
        with runtime.database.transaction() as transaction:
            collected = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM publication.objects
                     WHERE sha256 = %s) AS objects,
                    (SELECT count(*) FROM publication.object_deletions
                     WHERE object_sha256 = %s) AS pending
                """,
                (object_sha256, object_sha256),
            ).fetchone()
    assert collected == {"objects": 0, "pending": 0}
    with pytest.raises(ClientError) as deleted:
        rustfs_admin.head_object(
            Bucket=core_settings.s3_bucket,
            Key=object_key,
        )
    assert deleted.value.response["Error"]["Code"] in {"404", "NoSuchKey"}


def test_committed_read_rejects_corrupt_object_before_returning_a_bundle(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    expected = canonical_json_bytes({"committed": True})
    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="tracking.checkpoint",
            payloads={"state": JsonPayload({"committed": True})},
            provenance={"track_id": "track-001"},
        )
        with runtime.database.transaction() as transaction:
            published = runtime.publication.record(transaction, prepared)

        target_key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket, expected)
        rustfs_admin.put_object(
            Bucket=core_settings.s3_bucket,
            Key=target_key,
            Body=b"!" * len(expected),
        )
        with pytest.raises(PublicationVerificationError):
            runtime.publication.read(published)


def test_committed_read_rejects_corrupt_postgres_manifest_metadata(
    core_settings: CoreSettings,
) -> None:
    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="metadata.integrity",
            payloads={"state": JsonPayload({"metadata_integrity": True})},
            provenance={"ticket": 6},
        )
        with runtime.database.transaction() as transaction:
            published = runtime.publication.record(transaction, prepared)
        with runtime.database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE publication.manifests
                SET schema_version = 999
                WHERE sha256 = %s
                """,
                (published.manifest_sha256,),
            )

        with pytest.raises(PublicationVerificationError, match="schema record"):
            runtime.publication.read(published)


def _reset_product_probe(database: object) -> None:
    with database.transaction() as transaction:
        transaction.execute("DROP SCHEMA IF EXISTS publication_probe CASCADE")
        transaction.execute("CREATE SCHEMA publication_probe")
        transaction.execute(
            """
            CREATE TABLE publication_probe.current_bundle (
                singleton smallint PRIMARY KEY CHECK (singleton = 1),
                manifest_sha256 text NOT NULL
            )
            """
        )


def _reset_core_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        database.close()
    initialize_core(settings.database_url)


def _find_key_with_content(s3: BaseClient, bucket: str, expected: bytes) -> str:
    response = s3.list_objects_v2(Bucket=bucket)
    for item in response.get("Contents", []):
        key = item["Key"]
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        if body == expected:
            return str(key)
    raise AssertionError("test object was not uploaded")

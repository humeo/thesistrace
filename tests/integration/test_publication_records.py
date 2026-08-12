from datetime import UTC, datetime, timedelta

import pytest
from botocore.client import BaseClient

from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication import (
    JsonPayload,
    PublicationNotFoundError,
    PublicationVerificationError,
)
from thesistrace.publication.serialization import canonical_json_bytes


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
        assert runtime.publication.read(baseline_ref).provenance == {"sequence": 1}


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


def _find_key_with_content(s3: BaseClient, bucket: str, expected: bytes) -> str:
    response = s3.list_objects_v2(Bucket=bucket)
    for item in response.get("Contents", []):
        key = item["Key"]
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        if body == expected:
            return str(key)
    raise AssertionError("test object was not uploaded")

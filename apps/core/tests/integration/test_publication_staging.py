from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication import JsonPayload


def test_reused_object_survives_collection_between_preparation_and_commit(
    core_settings: CoreSettings,
) -> None:
    initialize_core(core_settings.database_url)
    with open_core_runtime(core_settings) as runtime:
        publication = runtime.publication
        payload = JsonPayload({"reused": uuid4().hex})
        old = publication.prepare(
            kind="staging.regression", payloads={"state": payload}, provenance={"owner": "old"},
        )
        with runtime.database.transaction() as transaction:
            old_ref = publication.record(transaction, old)
        with runtime.database.transaction() as transaction:
            publication.release_manifest_in_transaction(
                transaction, old_ref.manifest_sha256, still_referenced=False,
            )
        with publication.staging():
            new = publication.prepare(
                kind="staging.regression", payloads={"state": payload}, provenance={"owner": "new"},
            )
            with runtime.database.transaction() as transaction:
                assert publication.collect_pending_deletion_in_transaction(
                    transaction, object_sha256=old.payload_sha256s["state"],
                ) is None
            with runtime.database.transaction() as transaction:
                new_ref = publication.record(transaction, new)
        assert publication.read(new_ref).provenance == {"owner": "new"}
        with runtime.database.transaction() as transaction:
            publication.release_manifest_in_transaction(
                transaction, new_ref.manifest_sha256, still_referenced=False,
            )
        with runtime.database.transaction() as transaction:
            assert publication.collect_pending_deletion_in_transaction(
                transaction, object_sha256=new.payload_sha256s["state"],
            ) == "deleted"


def test_abandoned_staging_releases_collection_and_allows_concurrent_publishers(
    core_settings: CoreSettings,
) -> None:
    initialize_core(core_settings.database_url)
    with open_core_runtime(core_settings) as runtime:
        publication = runtime.publication
        prepared = publication.prepare(
            kind="staging.abandoned", payloads={"state": JsonPayload(uuid4().hex)},
            provenance={},
        )
        with runtime.database.transaction() as transaction:
            reference = publication.record(transaction, prepared)
        with runtime.database.transaction() as transaction:
            publication.release_manifest_in_transaction(
                transaction, reference.manifest_sha256, still_referenced=False,
            )

        def concurrent_publisher() -> None:
            with publication.staging():
                publication.verify_prepared(prepared)

        with (
            ThreadPoolExecutor(max_workers=1) as workers,
            pytest.raises(ValueError, match="abandon"),
        ):
            with publication.staging():
                workers.submit(concurrent_publisher).result(timeout=5)
                with runtime.database.transaction() as transaction:
                    assert publication.collect_pending_deletion_in_transaction(
                        transaction, object_sha256=prepared.payload_sha256s["state"],
                    ) is None
                raise ValueError("abandon")
        with runtime.database.transaction() as transaction:
            assert publication.collect_pending_deletion_in_transaction(
                transaction, object_sha256=prepared.payload_sha256s["state"],
            ) == "deleted"


def test_lost_staging_session_cannot_publish_after_collection_resumes(
    core_settings: CoreSettings,
) -> None:
    from thesistrace.publication import PublicationUnavailableError

    initialize_core(core_settings.database_url)
    with open_core_runtime(core_settings) as runtime:
        publication = runtime.publication
        with publication.staging():
            prepared = publication.prepare(
                kind="staging.connection-loss", payloads={"state": JsonPayload(uuid4().hex)},
                provenance={},
            )
            with runtime.database.transaction() as transaction:
                sessions = transaction.execute(
                    "SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory' "
                    "AND mode = 'ShareLock' AND granted AND classid = 0 "
                    "AND objid = (hashtext('thesistrace-publication-staging')::bigint & 4294967295)"
                ).fetchall()
                assert len(sessions) == 1
                assert transaction.execute(
                    "SELECT pg_terminate_backend(%s) AS terminated", (sessions[0]["pid"],),
                ).fetchone() == {"terminated": True}
            with pytest.raises(PublicationUnavailableError):
                with runtime.database.transaction() as transaction:
                    publication.record(transaction, prepared)
            with runtime.database.transaction() as transaction:
                assert transaction.execute(
                    "SELECT 1 FROM publication.manifests WHERE sha256 = %s",
                    (prepared.manifest_sha256,),
                ).fetchone() is None

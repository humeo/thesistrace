import json
from dataclasses import replace

import boto3
import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase, apply_migrations
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import CollectionPlan, DataService
from thesistrace.data.migrations import MIGRATIONS as DATA_MIGRATIONS
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.publication import JsonPayload, Publication
from thesistrace.publication.migrations import MIGRATIONS as PUBLICATION_MIGRATIONS


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_later_release_preserves_root_and_orders_release_history() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _request_and_process(settings, "ticket-11-root")
    with open_core_runtime(settings) as runtime:
        root = runtime.data.list_releases().items[0]
        root_canonical = runtime.data.load_canonical(root.id)
        root_metadata = _release_metadata(runtime.database, root.id)
        root_calendar = root_canonical["research_calendar"]
        assert root_metadata["latest_release_id"] == root.id
        assert root_metadata["provenance"]["appended_session_range"] == {
            "start": root_calendar[0],
            "end": root_calendar[-1],
        }
        assert root_metadata["provenance"]["correction_change_set"] == []
    _request_and_process(settings, "ticket-11-direct")

    with open_core_runtime(settings) as runtime:
        releases = runtime.data.list_releases().items
        assert len(releases) == 2
        latest, preserved_root = releases
        assert latest.predecessor_id == root.id
        assert latest.session_count == 757
        assert preserved_root == root
        assert runtime.data.load_canonical(root.id) == root_canonical
        latest_canonical = runtime.data.load_canonical(latest.id)
        latest_calendar = latest_canonical["research_calendar"]
        assert len(latest_calendar) == 757
        latest_metadata = _release_metadata(runtime.database, latest.id)
        assert latest_metadata["latest_release_id"] == latest.id
        assert latest_metadata["provenance"]["appended_session_range"] == {
            "start": latest_calendar[-1],
            "end": latest_calendar[-1],
        }
        assert latest_metadata["provenance"]["correction_change_set"] == []

        with runtime.database.transaction() as transaction:
            transaction.execute(
                "UPDATE data.releases SET created_at = '2099-01-01' WHERE id = %s",
                (root.id,),
            )
            transaction.execute(
                "UPDATE data.releases SET created_at = '2000-01-01' WHERE id = %s",
                (latest.id,),
            )
        assert runtime.data.overview().latest_release == latest
        assert runtime.data.list_releases().items == [latest, root]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_wider_source_gap_is_one_internal_catch_up_release() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _request_and_process(settings, "ticket-11-catch-up-root")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-11-catch-up"},
        )
        assert response.status_code == 202
    with open_core_runtime(settings) as runtime:
        data = DataService(
            runtime.database,
            runtime.publication,
            FixtureDataSource(sessions_after_bootstrap=3),
        )
        assert data.process_next_update()
        releases = data.list_releases().items
        assert len(releases) == 2
        assert releases[0].predecessor_id == releases[1].id
        assert releases[0].session_count == 759
        latest_canonical = data.load_canonical(releases[0].id)
        latest_calendar = latest_canonical["research_calendar"]
        metadata = _release_metadata(runtime.database, releases[0].id)
        assert metadata["latest_release_id"] == releases[0].id
        assert metadata["provenance"]["appended_session_range"] == {
            "start": latest_calendar[-3],
            "end": latest_calendar[-1],
        }
        assert metadata["provenance"]["correction_change_set"] == []


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_existing_v1_release_remains_readable_after_head_migration() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        apply_migrations(database, PUBLICATION_MIGRATIONS)
        apply_migrations(
            database,
            replace(DATA_MIGRATIONS, migrations=DATA_MIGRATIONS.migrations[:2]),
        )
        publication = _publication(database, settings)
        root_batch = FixtureDataSource().collect(CollectionPlan.bootstrap())
        root_provenance = {
            "canonical_contract": "canonical-eod-v1",
            "collection_kind": root_batch.collection_kind,
            "covered_session_range": {
                "start": root_batch.covered_session_range[0],
                "end": root_batch.covered_session_range[1],
            },
            "predecessor_id": None,
            "source_name": root_batch.source_name,
        }
        root_prepared = publication.prepare(
            kind="data.release",
            payloads={"canonical": JsonPayload(root_batch.canonical)},
            provenance=root_provenance,
        )
        root_id = f"dsr_{root_prepared.manifest_sha256[:24]}"
        with database.transaction() as transaction:
            root_published = publication.record(transaction, root_prepared)
            transaction.execute(
                """
                INSERT INTO data.releases (
                    id, predecessor_id, manifest_sha256, source_name,
                    collection_kind, canonical_schema, session_start,
                    session_end, session_count, created_at
                ) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, '2099-01-01')
                """,
                (
                    root_id,
                    root_published.manifest_sha256,
                    root_batch.source_name,
                    root_batch.collection_kind,
                    root_batch.canonical["schema_version"],
                    root_batch.covered_session_range[0],
                    root_batch.covered_session_range[1],
                    len(root_batch.canonical["research_calendar"]),
                ),
            )
        later_batch = FixtureDataSource().collect(
            CollectionPlan.incremental(root_batch.covered_session_range[1])
        )
        later_prepared = publication.prepare(
            kind="data.release",
            payloads={"canonical": JsonPayload(later_batch.canonical)},
            provenance={
                "canonical_contract": "canonical-eod-v1",
                "collection_kind": later_batch.collection_kind,
                "covered_session_range": {
                    "start": later_batch.covered_session_range[0],
                    "end": later_batch.covered_session_range[1],
                },
                "predecessor_id": root_id,
                "source_name": later_batch.source_name,
            },
        )
        later_id = f"dsr_{later_prepared.manifest_sha256[:24]}"
        with database.transaction() as transaction:
            later_published = publication.record(transaction, later_prepared)
            transaction.execute(
                """
                INSERT INTO data.releases (
                    id, predecessor_id, manifest_sha256, source_name,
                    collection_kind, canonical_schema, session_start,
                    session_end, session_count, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '2000-01-01')
                """,
                (
                    later_id,
                    root_id,
                    later_published.manifest_sha256,
                    later_batch.source_name,
                    later_batch.collection_kind,
                    later_batch.canonical["schema_version"],
                    later_batch.covered_session_range[0],
                    later_batch.covered_session_range[1],
                    len(later_batch.canonical["research_calendar"]),
                ),
            )
    finally:
        database.close()

    migrate_core(settings.database_url)
    with open_core_runtime(settings) as runtime:
        assert [release.id for release in runtime.data.list_releases().items] == [
            later_id,
            root_id,
        ]
        assert runtime.data.load_canonical(root_id) == root_batch.canonical
        assert runtime.data.load_canonical(later_id) == later_batch.canonical
        with runtime.database.transaction() as transaction:
            migrated = transaction.execute(
                """
                SELECT release.id, release.provenance_version,
                       state.latest_release_id
                FROM data.releases AS release
                JOIN data.state AS state ON state.singleton = 1
                ORDER BY release.id
                """,
            ).fetchall()
        assert {row["id"]: row["provenance_version"] for row in migrated} == {
            root_id: 1,
            later_id: 1,
        }
        assert {row["latest_release_id"] for row in migrated} == {later_id}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_existing_v2_release_remains_readable_after_compatibility_migration() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        apply_migrations(database, PUBLICATION_MIGRATIONS)
        apply_migrations(
            database,
            replace(DATA_MIGRATIONS, migrations=DATA_MIGRATIONS.migrations[:3]),
        )
        publication = _publication(database, settings)
        batch = FixtureDataSource().collect(CollectionPlan.bootstrap())
        provenance = {
            "canonical_contract": "canonical-eod-v1",
            "collection_kind": batch.collection_kind,
            "covered_session_range": {
                "start": batch.covered_session_range[0],
                "end": batch.covered_session_range[1],
            },
            "appended_session_range": {
                "start": batch.covered_session_range[0],
                "end": batch.covered_session_range[1],
            },
            "correction_change_set": [],
            "predecessor_id": None,
            "source_name": batch.source_name,
        }
        prepared = publication.prepare(
            kind="data.release",
            payloads={"canonical": JsonPayload(batch.canonical)},
            provenance=provenance,
        )
        release_id = f"dsr_{prepared.manifest_sha256[:24]}"
        with database.transaction() as transaction:
            published = publication.record(transaction, prepared)
            transaction.execute(
                """
                INSERT INTO data.releases (
                    id, predecessor_id, manifest_sha256, source_name,
                    collection_kind, canonical_schema, session_start,
                    session_end, session_count, appended_session_start,
                    appended_session_end
                ) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    release_id,
                    published.manifest_sha256,
                    batch.source_name,
                    batch.collection_kind,
                    batch.canonical["schema_version"],
                    batch.covered_session_range[0],
                    batch.covered_session_range[1],
                    len(batch.canonical["research_calendar"]),
                    batch.covered_session_range[0],
                    batch.covered_session_range[1],
                ),
            )
            transaction.execute(
                """
                INSERT INTO data.update_receipts (
                    request_id, request_fingerprint, status, release_id,
                    updated_at
                ) VALUES ('ticket-11-v2-upgrade', 'v2', 'published', %s,
                          clock_timestamp())
                """,
                (release_id,),
            )

        apply_migrations(database, DATA_MIGRATIONS)
        data = DataService(database, publication, FixtureDataSource())
        assert data.load_canonical(release_id) == batch.canonical
        with database.transaction() as transaction:
            migrated = transaction.execute(
                """
                SELECT release.provenance_version, state.latest_release_id
                FROM data.releases AS release
                JOIN data.state AS state ON state.singleton = 1
                WHERE release.id = %s
                """,
                (release_id,),
            ).fetchone()
        assert migrated == {"provenance_version": 2, "latest_release_id": release_id}
    finally:
        database.close()


def _request_and_process(settings: CoreSettings, request_id: str) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": request_id},
        )
        assert response.status_code == 202
    with open_core_runtime(settings) as runtime:
        assert runtime.data.process_next_update()


def _reset_core_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()


def _release_metadata(database: PostgresDatabase, release_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT state.latest_release_id, manifest.manifest_bytes
            FROM data.state AS state
            JOIN data.releases AS release ON release.id = %s
            JOIN publication.manifests AS manifest
              ON manifest.sha256 = release.manifest_sha256
            WHERE state.singleton = 1
            """,
            (release_id,),
        ).fetchone()
    assert row is not None
    manifest = json.loads(bytes(row["manifest_bytes"]))
    return {
        "latest_release_id": row["latest_release_id"],
        "provenance": manifest["provenance"],
    }


def _publication(database: PostgresDatabase, settings: CoreSettings) -> Publication:
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    return Publication(database, s3, bucket=settings.s3_bucket)

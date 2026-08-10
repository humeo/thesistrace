from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import boto3
import pytest

from thesistrace._postgres import (
    MigrationError,
    MigrationPlan,
    PostgresDatabase,
    PostgresTransaction,
    apply_migrations,
)
from thesistrace.entrypoints.migrations import (
    CORE_MIGRATION_PLANS,
    LEGACY_DATASET_RELEASE_DIAGNOSTIC,
    migrate_core,
)
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.publication import JsonPayload, Publication


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_legacy_release_state_blocks_cutover_until_private_reset(
    tmp_path: Path,
) -> None:
    core_settings = CoreSettings.from_environment()
    rustfs_admin = boto3.client(
        "s3",
        endpoint_url=core_settings.s3_endpoint_url,
        aws_access_key_id=core_settings.s3_access_key_id,
        aws_secret_access_key=core_settings.s3_secret_access_key,
        region_name=core_settings.s3_region,
    )
    _drop_product_schemas(core_settings)
    _migrate_pre_contraction(core_settings.database_url)
    mount = tmp_path / "canonical-data"
    mount.mkdir()
    legacy_file = mount / "legacy.parquet"
    legacy_file.write_bytes(b"legacy mounted market data")
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    publication = Publication(database, rustfs_admin, bucket=core_settings.s3_bucket)
    release = publication.prepare(
        kind="data.release",
        payloads={"canonical": JsonPayload({"legacy": True})},
        provenance={"contract": "legacy-release"},
    )
    try:
        with database.transaction() as transaction:
            publication.record(transaction, release)
            _insert_legacy_state(transaction, release.manifest_sha256)

        with pytest.raises(MigrationError, match=LEGACY_DATASET_RELEASE_DIAGNOSTIC):
            migrate_core(core_settings.database_url)
        with pytest.raises(MigrationError, match=LEGACY_DATASET_RELEASE_DIAGNOSTIC):
            with open_core_runtime(replace(core_settings, data_mount=mount)):
                raise AssertionError("legacy-bound runtime started")

        with database.transaction() as transaction:
            assert transaction.execute(
                "SELECT count(*) AS count FROM data.releases"
            ).fetchone() == {"count": 1}
            assert transaction.execute(
                "SELECT count(*) AS count FROM daily_tracks.tracks"
            ).fetchone() == {"count": 1}
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.manifests WHERE sha256 = %s",
                (release.manifest_sha256,),
            ).fetchone() == {"count": 1}
        assert legacy_file.read_bytes() == b"legacy mounted market data"
        rustfs_admin.head_object(
            Bucket=core_settings.s3_bucket,
            Key=_object_key(release.payload_sha256s["canonical"]),
        )

        reset = _run_development_reset(core_settings, mount, key="ticket-24-cutover-reset")
        assert reset.returncode == 0, reset.stderr
        assert json.loads(reset.stdout)["status"] == "succeeded"

        assert migrate_core(core_settings.database_url) == (
            "data.0009_contract_permanent_dataset_release_path",
            "daily_tracks.0010_contract_release_coordinate_storage",
        )
        with database.transaction() as transaction:
            assert _table(transaction, "data.releases") is None
            assert _table(transaction, "data.state") is None
            assert _table(transaction, "data.update_receipts") is None
            assert _table(transaction, "data.update_attempts") is None
            assert _table(transaction, "data.fields") is None
            assert _table(transaction, "daily_tracks.progressions") is None
            assert _table(transaction, "daily_tracks.checkpoints") is None
            assert _table(transaction, "daily_tracks.progression_attempts") is None
            assert _column(transaction, "daily_tracks", "tracks", "current_release_id") is None
            assert (
                _column(transaction, "daily_tracks", "retry_receipts", "target_release_id")
                is None
            )
            assert transaction.execute(
                "SELECT count(*) AS count FROM definitions.records"
            ).fetchone() == {"count": 1}
        assert list(mount.iterdir()) == []
        with open_core_runtime(replace(core_settings, data_mount=mount)) as runtime:
            assert runtime.data_overview.overview().readiness is False
        post_cutover_reset = _run_development_reset(
            core_settings,
            mount,
            key="ticket-24-post-cutover-reset",
        )
        assert post_cutover_reset.returncode == 0, post_cutover_reset.stderr
        assert json.loads(post_cutover_reset.stdout)["status"] == "succeeded"
    finally:
        database.close()
        rustfs_admin.close()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_clean_session_coordinate_state_survives_release_schema_contraction(
) -> None:
    core_settings = CoreSettings.from_environment()
    _drop_product_schemas(core_settings)
    _migrate_pre_contraction(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO definitions.records (id, revision, content)
                VALUES ('definition_current', 1, '{"name":"current"}')
                """
            )
            transaction.execute(
                """
                INSERT INTO research_runs.runs (
                    id, definition_id, definition_revision,
                    requested_start_date, requested_end_date,
                    status, immutable_input
                ) VALUES (
                    'run_current', 'definition_current', 1,
                    '2026-08-07', '2026-08-07', 'succeeded', '{}'
                )
                """
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.tracks (
                    id, status, seed_run_id, origin
                ) VALUES ('track_current', 'active', 'run_current', '{}')
                """
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.session_checkpoints (
                    manifest_sha256, track_id, boundary_session,
                    terminal_strategy_state, data_generation_id, provenance
                ) VALUES (
                    %s, 'track_current', '2026-08-07', '{}', %s, '{}'
                )
                """,
                ("a" * 64, "b" * 64),
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.session_tracking_states (
                    track_id, origin_session, origin_checkpoint_manifest_sha256,
                    current_checkpoint_manifest_sha256
                ) VALUES ('track_current', '2026-08-07', %s, %s)
                """,
                ("a" * 64, "a" * 64),
            )

        migrate_core(core_settings.database_url)

        with database.transaction() as transaction:
            assert transaction.execute(
                "SELECT id, status FROM research_runs.runs"
            ).fetchall() == [{"id": "run_current", "status": "succeeded"}]
            assert transaction.execute(
                "SELECT id, status FROM daily_tracks.tracks"
            ).fetchall() == [{"id": "track_current", "status": "active"}]
            assert transaction.execute(
                "SELECT track_id, boundary_session FROM daily_tracks.session_checkpoints"
            ).fetchall() == [
                {"track_id": "track_current", "boundary_session": _date(2026, 8, 7)}
            ]
            assert _table(transaction, "data.releases") is None
            assert _table(transaction, "daily_tracks.progressions") is None
    finally:
        database.close()


def _migrate_pre_contraction(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        for plan in CORE_MIGRATION_PLANS:
            selected = plan
            if plan.schema in {"data", "daily_tracks"}:
                selected = MigrationPlan(
                    schema=plan.schema,
                    ledger_table=plan.ledger_table,
                    lock_name=plan.lock_name,
                    migrations=plan.migrations[:-1],
                )
            apply_migrations(database, selected)
    finally:
        database.close()


def _insert_legacy_state(
    transaction: PostgresTransaction,
    manifest_sha256: str,
) -> None:
    transaction.execute(
        """
        INSERT INTO definitions.records (id, revision, content)
        VALUES ('definition_kept', 1, '{}')
        """
    )
    transaction.execute(
        "INSERT INTO data.fields (field_id, definition) VALUES ('legacy_field', '{}')"
    )
    transaction.execute(
        """
        INSERT INTO research_runs.runs (
            id, definition_id, definition_revision,
            requested_start_date, requested_end_date,
            status, immutable_input, result_manifest_sha256, result_provenance
        ) VALUES (
            'run_legacy', 'definition_kept', 1,
            '2026-08-07', '2026-08-07', 'succeeded', '{}', %s, '{}'
        )
        """,
        (manifest_sha256,),
    )
    transaction.execute(
        """
        INSERT INTO daily_tracks.tracks (
            id, status, seed_run_id, origin,
            current_release_id, current_strategy_session, head_manifest_sha256
        ) VALUES (
            'track_legacy', 'active', 'run_legacy', '{}',
            'release_legacy', '2026-08-07', %s
        )
        """,
        (manifest_sha256,),
    )
    transaction.execute(
        """
        INSERT INTO data.releases (
            id, predecessor_id, manifest_sha256, source_name, collection_kind,
            canonical_schema, session_start, session_end, session_count,
            appended_session_start, appended_session_end, provenance_version
        ) VALUES (
            'release_legacy', NULL, %s, 'fixture', 'bootstrap',
            'canonical-eod-v1', '2026-08-07', '2026-08-07', 1,
            '2026-08-07', '2026-08-07', 2
        )
        """,
        (manifest_sha256,),
    )
    transaction.execute(
        "UPDATE data.state SET latest_release_id = 'release_legacy' WHERE singleton = 1"
    )


def _run_development_reset(
    settings: CoreSettings,
    mount: Path,
    *,
    key: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            sys.executable,
            "-m",
            "thesistrace.entrypoints.data_operator",
            "development-reset",
            "--idempotency-key",
            key,
            "--environment",
            "development",
            "--confirm",
            "reset:development",
        ),
        env={
            **os.environ,
            "THESISTRACE_DATABASE_URL": settings.database_url,
            "THESISTRACE_DATA_MOUNT": str(mount),
            "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
            "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
            "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
            "THESISTRACE_S3_BUCKET": settings.s3_bucket,
            "THESISTRACE_S3_REGION": settings.s3_region,
            "THESISTRACE_DEPLOYMENT_ENV": "development",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in (
                "daily_tracks",
                "research_runs",
                "definitions",
                "publication",
                "data",
            ):
                transaction.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    finally:
        database.close()


def _table(transaction: PostgresTransaction, name: str) -> object:
    row = transaction.execute("SELECT to_regclass(%s) AS value", (name,)).fetchone()
    assert row is not None
    return row["value"]


def _column(
    transaction: PostgresTransaction,
    schema: str,
    table: str,
    column: str,
) -> object:
    row = transaction.execute(
        """
        SELECT column_name AS value
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (schema, table, column),
    ).fetchone()
    return None if row is None else row["value"]


def _object_key(digest: str) -> str:
    return f"publication/v1/sha256/{digest[:2]}/{digest}"


def _date(year: int, month: int, day: int) -> date:
    return date(year, month, day)

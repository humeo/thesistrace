from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data import DevelopmentReset, DevelopmentResetError
from thesistrace.data import development_reset as reset_module
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.publication import JsonPayload, Publication


def test_private_development_reset_is_guarded_scoped_and_reference_aware(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
    tmp_path: Path,
) -> None:
    _drop_product_schemas(core_settings)
    migrate_core(core_settings.database_url)
    mount = tmp_path / "canonical-data"
    mount.mkdir()
    (mount / "HEAD.json").write_text("legacy-head")
    (mount / "objects").mkdir()
    (mount / "objects" / "legacy.parquet").write_bytes(b"legacy-market-data")
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve me")
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    publication = Publication(database, rustfs_admin, bucket=core_settings.s3_bucket)
    target = publication.prepare(
        kind="development-reset-target",
        payloads={
            "owned": JsonPayload({"owned": "legacy execution"}),
            "shared": JsonPayload({"shared": "preserve"}),
        },
        provenance={"owner": "legacy"},
    )
    retained = publication.prepare(
        kind="unrelated-publication",
        payloads={"shared": JsonPayload({"shared": "preserve"})},
        provenance={"owner": "unrelated"},
    )
    try:
        with database.transaction() as transaction:
            publication.record(transaction, target)
            publication.record(transaction, retained)
            _insert_legacy_state(transaction, target.manifest_sha256)
        shared = target.payload_sha256s["shared"]
        owned = target.payload_sha256s["owned"]
        assert shared == retained.payload_sha256s["shared"]
        environment = _operator_environment(core_settings, mount)

        production = _run_reset(
            environment={**environment, "THESISTRACE_DEPLOYMENT_ENV": "production"},
            environment_name="production",
            confirmation="reset:production",
            key="production-refused",
        )
        mismatch = _run_reset(
            environment={**environment, "THESISTRACE_DEPLOYMENT_ENV": "development"},
            environment_name="development",
            confirmation="reset:wrong",
            key="confirmation-refused",
        )

        assert production.returncode == 2
        assert json.loads(production.stderr) == {
            "status": "failed",
            "code": "RESET_ENVIRONMENT_REFUSED",
        }
        assert mismatch.returncode == 2
        assert json.loads(mismatch.stderr) == {
            "status": "failed",
            "code": "RESET_CONFIRMATION_MISMATCH",
        }
        assert _state_counts(database) == {
            "definitions": 1,
            "runs": 1,
            "tracks": 1,
            "releases": 1,
            "reset_operations": 0,
        }
        assert (mount / "objects" / "legacy.parquet").read_bytes() == b"legacy-market-data"

        accepted = _run_reset(
            environment={**environment, "THESISTRACE_DEPLOYMENT_ENV": "development"},
            environment_name="development",
            confirmation="reset:development",
            key="accepted-development-reset",
        )
        replayed = _run_reset(
            environment={**environment, "THESISTRACE_DEPLOYMENT_ENV": "development"},
            environment_name="development",
            confirmation="reset:development",
            key="accepted-development-reset",
        )

        assert accepted.returncode == 0, accepted.stderr
        assert replayed.returncode == 0, replayed.stderr
        assert json.loads(replayed.stdout) == json.loads(accepted.stdout)
        assert json.loads(accepted.stdout) == {
            "deleted_object_count": 1,
            "deleted_path_count": 3,
            "preserved_object_count": 1,
            "status": "succeeded",
        }
        assert _state_counts(database) == {
            "definitions": 1,
            "runs": 0,
            "tracks": 0,
            "releases": 0,
            "reset_operations": 1,
        }
        with database.transaction() as transaction:
            assert transaction.execute(
                "SELECT count(*) AS count FROM data.fields WHERE field_id = 'field_unrelated'"
            ).fetchone() == {"count": 1}
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.manifests WHERE sha256 = %s",
                (target.manifest_sha256,),
            ).fetchone() == {"count": 0}
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.manifests WHERE sha256 = %s",
                (retained.manifest_sha256,),
            ).fetchone() == {"count": 1}
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.objects WHERE sha256 = %s",
                (shared,),
            ).fetchone() == {"count": 1}
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.objects WHERE sha256 = %s",
                (owned,),
            ).fetchone() == {"count": 0}
        assert _object_exists(rustfs_admin, core_settings.s3_bucket, shared)
        assert not _object_exists(rustfs_admin, core_settings.s3_bucket, owned)
        assert mount.is_dir()
        assert list(mount.iterdir()) == []
        assert outside.read_text() == "preserve me"
    finally:
        database.close()


@pytest.mark.parametrize("unsafe_kind", ("filesystem-root", "broad-root", "workspace", "symlink"))
def test_development_reset_rejects_unsafe_mounts_without_a_plan(
    core_settings: CoreSettings,
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    _drop_product_schemas(core_settings)
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "preserved.txt").write_text("safe")
    if unsafe_kind == "filesystem-root":
        mount = Path("/")
    elif unsafe_kind == "broad-root":
        mount = Path("/private/tmp")
    elif unsafe_kind == "workspace":
        mount = Path(__file__).resolve().parents[2]
    else:
        mount = tmp_path / "mount"
        mount.mkdir()
        (mount / "escape").symlink_to(outside, target_is_directory=True)
    try:
        completed = _run_reset(
            environment={
                **_operator_environment(core_settings, mount),
                "THESISTRACE_DEPLOYMENT_ENV": "development",
            },
            environment_name="development",
            confirmation="reset:development",
            key=f"unsafe-{unsafe_kind}",
        )

        assert completed.returncode == 2
        assert json.loads(completed.stderr) == {
            "status": "failed",
            "code": "RESET_MOUNT_UNSAFE",
        }
        with database.transaction() as transaction:
            assert transaction.execute(
                "SELECT count(*) AS count FROM data.development_reset_operations"
            ).fetchone() == {"count": 0}
        assert (outside / "preserved.txt").read_text() == "safe"
    finally:
        database.close()


@pytest.mark.parametrize("boundary", ("postgres", "rustfs", "mount"))
def test_development_reset_boundary_failures_retry_the_fixed_plan(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    _drop_product_schemas(core_settings)
    migrate_core(core_settings.database_url)
    mount = tmp_path / "canonical-data"
    mount.mkdir()
    (mount / "legacy.bin").write_bytes(b"legacy")
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    publication = Publication(database, rustfs_admin, bucket=core_settings.s3_bucket)
    target = publication.prepare(
        kind="development-reset-fault-target",
        payloads={"owned": JsonPayload({"boundary": boundary})},
        provenance={"boundary": boundary},
    )
    key = f"reset-fault-{boundary}"
    original_delete_relative = reset_module._delete_relative
    try:
        with database.transaction() as transaction:
            publication.record(transaction, target)
            _insert_legacy_state(transaction, target.manifest_sha256)
            if boundary == "postgres":
                transaction.execute(
                    """
                    CREATE FUNCTION data.reject_reset_postgres() RETURNS trigger
                    LANGUAGE plpgsql AS $function$
                    BEGIN
                        IF NEW.postgres_done AND NOT OLD.postgres_done THEN
                            RAISE EXCEPTION 'injected reset PostgreSQL failure';
                        END IF;
                        RETURN NEW;
                    END
                    $function$;
                    CREATE TRIGGER reject_reset_postgres
                    BEFORE UPDATE ON data.development_reset_operations
                    FOR EACH ROW EXECUTE FUNCTION data.reject_reset_postgres();
                    """
                )
        selected_s3: BaseClient | _FailDeleteS3 = rustfs_admin
        if boundary == "rustfs":
            selected_s3 = _FailDeleteS3(rustfs_admin)
        if boundary == "mount":
            monkeypatch.setattr(
                reset_module,
                "_delete_relative",
                lambda *_arguments: (_ for _ in ()).throw(OSError("injected mount failure")),
            )
        service = DevelopmentReset(
            database,
            selected_s3,  # type: ignore[arg-type]
            bucket=core_settings.s3_bucket,
            mount_root=mount,
        )

        expected_code = {
            "postgres": "RESET_POSTGRES_FAILED",
            "rustfs": "RESET_OBJECT_DELETE_FAILED",
            "mount": "RESET_MOUNT_DELETE_FAILED",
        }[boundary]
        with pytest.raises(DevelopmentResetError) as failed:
            service.execute(
                idempotency_key=key,
                environment_name="development",
                confirmation="reset:development",
            )
        assert failed.value.code == expected_code
        before_retry = _reset_plan_counts(database, key)
        assert before_retry["status"] == "failed"

        if boundary == "postgres":
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    DROP TRIGGER reject_reset_postgres
                    ON data.development_reset_operations;
                    DROP FUNCTION data.reject_reset_postgres();
                    """
                )
        if boundary == "mount":
            monkeypatch.setattr(reset_module, "_delete_relative", original_delete_relative)
        recovered = DevelopmentReset(
            database,
            rustfs_admin,
            bucket=core_settings.s3_bucket,
            mount_root=mount,
        ).execute(
            idempotency_key=key,
            environment_name="development",
            confirmation="reset:development",
        )

        assert recovered.status == "succeeded"
        after_retry = _reset_plan_counts(database, key)
        assert after_retry["manifest_targets"] == before_retry["manifest_targets"]
        assert after_retry["object_targets"] == before_retry["object_targets"]
        assert after_retry["path_targets"] == before_retry["path_targets"]
        assert list(mount.iterdir()) == []
        assert _state_counts(database)["runs"] == 0
    finally:
        database.close()


def _insert_legacy_state(transaction: PostgresTransaction, manifest_sha256: str) -> None:
    transaction.execute(
        """
        INSERT INTO definitions.records (id, revision, content)
        VALUES ('definition_preserved', 1, '{"name":"preserved draft"}')
        """
    )
    transaction.execute(
        "INSERT INTO data.fields (field_id, definition) VALUES ('field_unrelated', '{}')"
    )
    transaction.execute(
        """
        INSERT INTO research_runs.runs (
            id, definition_id, definition_revision,
            requested_start_date, requested_end_date,
            status, immutable_input, result_manifest_sha256, result_provenance
        ) VALUES (
            'run_legacy', 'definition_preserved', 1,
            '2026-08-03', '2026-08-03',
            'succeeded', '{}', %s, '{}'
        )
        """,
        (manifest_sha256,),
    )
    transaction.execute(
        """
        INSERT INTO definitions.run_receipts (
            request_id, request_fingerprint, definition_id,
            saved_revision, saved_content, outcome, issues, research_run_id
        ) VALUES (
            'run_receipt_legacy', 'fingerprint', 'definition_preserved',
            1, '{}', 'accepted', '[]', 'run_legacy'
        )
        """
    )
    transaction.execute(
        """
        INSERT INTO daily_tracks.tracks (
            id, status, seed_run_id, origin, current_release_id,
            current_strategy_session, head_manifest_sha256
        ) VALUES (
            'track_legacy', 'active', 'run_legacy', '{}', 'release_legacy',
            '2026-08-03', %s
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
            'legacy', '2026-08-03', '2026-08-03', 1,
            '2026-08-03', '2026-08-03', 2
        )
        """,
        ("a" * 64,),
    )
    transaction.execute(
        "UPDATE data.state SET latest_release_id = 'release_legacy' WHERE singleton = 1"
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


def _state_counts(database: PostgresDatabase) -> dict[str, int]:
    with database.transaction() as transaction:
        return {
            "definitions": int(
                transaction.execute("SELECT count(*) AS count FROM definitions.records").fetchone()[
                    "count"
                ]
            ),
            "runs": int(
                transaction.execute("SELECT count(*) AS count FROM research_runs.runs").fetchone()[
                    "count"
                ]
            ),
            "tracks": int(
                transaction.execute("SELECT count(*) AS count FROM daily_tracks.tracks").fetchone()[
                    "count"
                ]
            ),
            "releases": int(
                transaction.execute("SELECT count(*) AS count FROM data.releases").fetchone()[
                    "count"
                ]
            ),
            "reset_operations": int(
                transaction.execute(
                    "SELECT count(*) AS count FROM data.development_reset_operations"
                ).fetchone()["count"]
            ),
        }


def _reset_plan_counts(database: PostgresDatabase, key: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT operation.status,
                (SELECT count(*) FROM data.development_reset_manifests
                 WHERE idempotency_key = %s) AS manifest_targets,
                (SELECT count(*) FROM data.development_reset_objects
                 WHERE idempotency_key = %s) AS object_targets,
                (SELECT count(*) FROM data.development_reset_paths
                 WHERE idempotency_key = %s) AS path_targets
            FROM data.development_reset_operations AS operation
            WHERE operation.idempotency_key = %s
            """,
            (key, key, key, key),
        ).fetchone()
    assert row is not None
    return dict(row)


def _operator_environment(settings: CoreSettings, mount: Path) -> dict[str, str]:
    return {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_DATA_MOUNT": str(mount),
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
    }


def _run_reset(
    *,
    environment: dict[str, str],
    environment_name: str,
    confirmation: str,
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
            environment_name,
            "--confirm",
            confirmation,
        ),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


class _FailDeleteS3:
    def __init__(self, delegate: BaseClient) -> None:
        self._delegate = delegate

    def head_object(self, **kwargs: object) -> object:
        return self._delegate.head_object(**kwargs)  # type: ignore[arg-type]

    def delete_object(self, **kwargs: object) -> object:
        raise ClientError(
            {"Error": {"Code": "InternalError", "Message": "injected"}},
            "DeleteObject",
        )


def _object_exists(s3: BaseClient, bucket: str, digest: str) -> bool:
    try:
        s3.head_object(
            Bucket=bucket,
            Key=f"publication/v1/sha256/{digest[:2]}/{digest}",
        )
        return True
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise

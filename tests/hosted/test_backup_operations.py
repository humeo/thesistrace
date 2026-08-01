import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesistrace.hosted.backup_operations import (
    BackupOperationError,
    RestoreVerificationError,
    create_recovery_set,
    expire_recovery_sets,
    extract_recovery_set,
    initialize_backup_target,
    perform_backup,
    read_backup_health,
    restore_recovery_set,
    restore_secret_recovery_bundle,
    validate_backup_target,
    verify_authenticated_recovery_selection,
    verify_restored_state,
    write_recovery_exercise,
)
from thesistrace.hosted.release_operations import seal_recovery_bundle


def write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_coordinated_recovery_set_is_encrypted_and_restores_exact_sources(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    write(source / "postgres-data" / "PG_VERSION", b"15\n")
    write(source / "temporal-data" / "PG_VERSION", b"16\n")
    write(
        source / "immutable-objects" / "sha256" / "ab" / "abcdef.json",
        b'{"alpha":1}',
    )
    write(source / "insforge-storage" / "auth" / "avatar", b"private")
    write(source / "release-state" / "current.json", b'{"bundle_id":"bundle-1"}')
    write(
        source / "release-state" / "bundles" / "bundle-1" / "bundle.json",
        b'{"bundle_id":"bundle-1"}',
    )
    write(
        source / "secret-recovery" / "current.recovery",
        b"TTSR1-encrypted-secrets",
    )

    created = create_recovery_set(
        target=tmp_path / "off-node",
        sources={
            "postgres-data": source / "postgres-data",
            "temporal-data": source / "temporal-data",
            "immutable-objects": source / "immutable-objects",
            "insforge-storage": source / "insforge-storage",
            "release-state": source / "release-state",
            "secret-recovery": source / "secret-recovery",
        },
        release_bundle_id="bundle-1",
        passphrase="backup-passphrase-123",
        now=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        workflow_probe_id="recovery-probe-launch-exercise",
    )

    encrypted = created.artifact_path.read_bytes()
    assert b'{"alpha":1}' not in encrypted
    assert b"encrypted-secrets" not in encrypted
    assert created.manifest["status"] == "complete"
    assert created.manifest["release_bundle_id"] == "bundle-1"
    assert created.manifest["workflow_probe_id"] == (
        "recovery-probe-launch-exercise"
    )

    with pytest.raises(BackupOperationError, match="probe ID is invalid"):
        create_recovery_set(
            target=tmp_path / "off-node",
            sources={
                name: source / name
                for name in (
                    "postgres-data",
                    "temporal-data",
                    "immutable-objects",
                    "insforge-storage",
                    "release-state",
                    "secret-recovery",
                )
            },
            release_bundle_id="bundle-1",
            passphrase="backup-passphrase-123",
            workflow_probe_id="unscoped-probe",
        )

    restored = tmp_path / "restored"
    extract_recovery_set(
        manifest_path=created.manifest_path,
        destination=restored,
        passphrase="backup-passphrase-123",
    )

    assert (restored / "volumes/postgres-data/PG_VERSION").read_bytes() == b"15\n"
    assert (restored / "volumes/temporal-data/PG_VERSION").read_bytes() == b"16\n"
    assert (
        restored / "volumes/immutable-objects/sha256/ab/abcdef.json"
    ).read_bytes() == b'{"alpha":1}'
    assert (restored / "volumes/insforge-storage/auth/avatar").read_bytes() == b"private"
    assert (restored / "metadata/release-state/current.json").read_bytes() == (
        b'{"bundle_id":"bundle-1"}'
    )
    assert (restored / "secrets/current.recovery").read_bytes() == (
        b"TTSR1-encrypted-secrets"
    )


def test_backup_target_requires_an_explicit_off_node_contract(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    state = repository / ".hosted"
    repository.mkdir()
    state.mkdir()

    with pytest.raises(BackupOperationError, match="outside the repository"):
        initialize_backup_target(
            state / "backups",
            repository_root=repository,
            state_root=state,
        )

    external = tmp_path / "mounted-off-node"
    external.mkdir()
    with pytest.raises(BackupOperationError, match="not initialized"):
        validate_backup_target(
            external,
            repository_root=repository,
            state_root=state,
        )

    initialize_backup_target(
        external,
        repository_root=repository,
        state_root=state,
    )
    assert validate_backup_target(
        external,
        repository_root=repository,
        state_root=state,
    ) == external.resolve()


def test_failed_backup_is_visible_without_publishing_an_incomplete_set(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "operator" / "backup-status.json"
    target = tmp_path / "off-node"

    with pytest.raises(BackupOperationError, match="incomplete"):
        perform_backup(
            target=target,
            sources={},
            release_bundle_id="bundle-1",
            passphrase="backup-passphrase-123",
            status_path=status_path,
            now=datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
        )

    assert list(target.glob("*.ttsb")) == []
    assert list(target.glob("backup_*.json")) == []
    health = read_backup_health(
        status_path,
        now=datetime(2026, 8, 1, 6, 1, tzinfo=UTC),
    )
    assert health == {
        "healthy": False,
        "last_attempt_succeeded": False,
        "last_success_age_seconds": -1.0,
    }


def test_expiry_removes_only_complete_recovery_sets_older_than_seven_days(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    sources: dict[str, Path] = {}
    for name in (
        "postgres-data",
        "temporal-data",
        "immutable-objects",
        "insforge-storage",
        "release-state",
        "secret-recovery",
    ):
        path = source / name
        write(path / "value", name.encode())
        sources[name] = path
    write(sources["postgres-data"] / "PG_VERSION", b"15\n")
    write(sources["temporal-data"] / "PG_VERSION", b"16\n")
    write(sources["secret-recovery"] / "current.recovery", b"TTSR1-sealed")
    write(sources["release-state"] / "current.json", b'{"bundle_id":"bundle-old"}')
    write(
        sources["release-state"] / "bundles/bundle-old/bundle.json",
        b'{"bundle_id":"bundle-old"}',
    )
    target = tmp_path / "off-node"
    old = create_recovery_set(
        target=target,
        sources=sources,
        release_bundle_id="bundle-old",
        passphrase="backup-passphrase-123",
        now=datetime(2026, 7, 24, 23, 59, tzinfo=UTC),
    )
    write(
        sources["release-state"] / "current.json",
        b'{"bundle_id":"bundle-current"}',
    )
    write(
        sources["release-state"] / "bundles/bundle-current/bundle.json",
        b'{"bundle_id":"bundle-current"}',
    )
    current = create_recovery_set(
        target=target,
        sources=sources,
        release_bundle_id="bundle-current",
        passphrase="backup-passphrase-123",
        now=datetime(2026, 7, 25, 0, 1, tzinfo=UTC),
    )
    unrelated = target / "operator-note.txt"
    unrelated.write_text("keep")

    assert expire_recovery_sets(
        target,
        now=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
    ) == [str(old.manifest["backup_id"])]
    assert not old.manifest_path.exists()
    assert not old.artifact_path.exists()
    assert current.manifest_path.exists()
    assert current.artifact_path.exists()
    assert unrelated.exists()

    stale_on_failed_attempt = create_recovery_set(
        target=target,
        sources=sources,
        release_bundle_id="bundle-current",
        passphrase="backup-passphrase-123",
        now=datetime(2026, 7, 23, 0, 0, tzinfo=UTC),
    )
    (sources["postgres-data"] / "PG_VERSION").unlink()
    with pytest.raises(BackupOperationError, match="incomplete"):
        perform_backup(
            target=target,
            sources=sources,
            release_bundle_id="bundle-current",
            passphrase="backup-passphrase-123",
            status_path=tmp_path / "backup-status.json",
            now=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        )
    assert not stale_on_failed_attempt.manifest_path.exists()
    assert not stale_on_failed_attempt.artifact_path.exists()


def test_restore_rejects_the_wrong_key_without_leaving_partial_plaintext(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    sources: dict[str, Path] = {}
    for name in (
        "postgres-data",
        "temporal-data",
        "immutable-objects",
        "insforge-storage",
        "release-state",
        "secret-recovery",
    ):
        path = source / name
        write(path / "value", name.encode())
        sources[name] = path
    write(sources["postgres-data"] / "PG_VERSION", b"15\n")
    write(sources["temporal-data"] / "PG_VERSION", b"16\n")
    write(sources["secret-recovery"] / "current.recovery", b"TTSR1-sealed")
    write(sources["release-state"] / "current.json", b'{"bundle_id":"bundle-1"}')
    write(
        sources["release-state"] / "bundles/bundle-1/bundle.json",
        b'{"bundle_id":"bundle-1"}',
    )
    created = create_recovery_set(
        target=tmp_path / "off-node",
        sources=sources,
        release_bundle_id="bundle-1",
        passphrase="correct-passphrase-123",
    )
    destination = tmp_path / "plaintext"

    with pytest.raises(BackupOperationError, match="authentication"):
        extract_recovery_set(
            manifest_path=created.manifest_path,
            destination=destination,
            passphrase="incorrect-passphrase",
        )

    assert not destination.exists()


def test_restore_authenticates_the_complete_set_before_erasing_live_volumes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    sources: dict[str, Path] = {}
    for name in (
        "postgres-data",
        "temporal-data",
        "immutable-objects",
        "insforge-storage",
        "release-state",
        "secret-recovery",
    ):
        path = source / name
        path.mkdir(parents=True)
        sources[name] = path
    write(sources["postgres-data"] / "PG_VERSION", b"15\n")
    write(sources["temporal-data"] / "PG_VERSION", b"16\n")
    write(sources["secret-recovery"] / "current.recovery", b"TTSR1-sealed")
    write(sources["release-state"] / "current.json", b'{"bundle_id":"bundle-1"}')
    write(
        sources["release-state"] / "bundles/bundle-1/bundle.json",
        b'{"bundle_id":"bundle-1"}',
    )
    created = create_recovery_set(
        target=tmp_path / "off-node",
        sources=sources,
        release_bundle_id="bundle-1",
        passphrase="correct-passphrase-123",
        workflow_probe_id="recovery-probe-authenticated-metadata",
    )
    restore_root = tmp_path / "restore-root"
    for relative in (
        "volumes/postgres-data",
        "volumes/temporal-data",
        "volumes/immutable-objects",
        "volumes/insforge-storage",
        "metadata/release-state",
        "secrets",
    ):
        write(restore_root / relative / "live", b"preserve on rejected restore")
    working_cache = tmp_path / "working-cache"
    write(working_cache / "live", b"preserve")

    original_manifest = created.manifest_path.read_bytes()
    tampered_manifest = json.loads(original_manifest)
    tampered_manifest["created_at"] = "2026-08-01T05:59:59+00:00"
    created.manifest_path.write_text(json.dumps(tampered_manifest))
    with pytest.raises(BackupOperationError, match="authenticated metadata"):
        restore_recovery_set(
            manifest_path=created.manifest_path,
            restore_root=restore_root,
            working_cache=working_cache,
            passphrase="correct-passphrase-123",
            incident_at=datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
        )
    assert (restore_root / "volumes/postgres-data/live").read_bytes() == (
        b"preserve on rejected restore"
    )
    assert (working_cache / "live").read_bytes() == b"preserve"
    created.manifest_path.write_bytes(original_manifest)

    tampered_manifest = json.loads(original_manifest)
    del tampered_manifest["workflow_probe_id"]
    created.manifest_path.write_text(json.dumps(tampered_manifest))
    with pytest.raises(BackupOperationError, match="authenticated metadata"):
        restore_recovery_set(
            manifest_path=created.manifest_path,
            restore_root=restore_root,
            working_cache=working_cache,
            passphrase="correct-passphrase-123",
        )
    assert (restore_root / "volumes/postgres-data/live").read_bytes() == (
        b"preserve on rejected restore"
    )
    assert (working_cache / "live").read_bytes() == b"preserve"
    created.manifest_path.write_bytes(original_manifest)

    with pytest.raises(BackupOperationError, match="authentication"):
        restore_recovery_set(
            manifest_path=created.manifest_path,
            restore_root=restore_root,
            working_cache=working_cache,
            passphrase="incorrect-passphrase",
        )

    assert (restore_root / "volumes/postgres-data/live").read_bytes() == (
        b"preserve on rejected restore"
    )
    assert (working_cache / "live").read_bytes() == b"preserve"


def test_restore_replaces_authoritative_volumes_and_recovers_secrets_separately(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    sources: dict[str, Path] = {}
    for name in (
        "postgres-data",
        "temporal-data",
        "immutable-objects",
        "insforge-storage",
        "release-state",
    ):
        path = source / name
        write(path / "authoritative", name.encode())
        sources[name] = path
    secret_recovery = source / "secret-recovery"
    seal_recovery_bundle(
        secret_recovery / "current.recovery",
        {
            "postgres_password": "database-secret",
            "api_database_password": "api-secret",
        },
        passphrase="separate-recovery-passphrase",
    )
    sources["secret-recovery"] = secret_recovery
    write(sources["postgres-data"] / "PG_VERSION", b"15\n")
    write(sources["temporal-data"] / "PG_VERSION", b"16\n")
    write(sources["release-state"] / "current.json", b'{"bundle_id":"bundle-1"}')
    configuration_file = (
        sources["release-state"]
        / "bundles/bundle-1/configuration/deploy/hosted/compose.yaml"
    )
    write(configuration_file, b"services: {}\n")
    configuration_file.chmod(0o444)
    write(
        sources["release-state"] / "bundles/bundle-1/bundle.json",
        b'{"bundle_id":"bundle-1",'
        b'"configuration_paths":["deploy/hosted/compose.yaml"],'
        b'"configuration_modes":{"deploy/hosted/compose.yaml":292}}',
    )
    created = create_recovery_set(
        target=tmp_path / "off-node",
        sources=sources,
        release_bundle_id="bundle-1",
        passphrase="backup-passphrase-123",
    )

    restore_root = tmp_path / "restore-root"
    for relative in (
        "volumes/postgres-data",
        "volumes/temporal-data",
        "volumes/immutable-objects",
        "volumes/insforge-storage",
        "metadata/release-state",
        "secrets",
    ):
        write(restore_root / relative / "stale", b"must disappear")
    working_cache = tmp_path / "working-cache"
    write(working_cache / "track" / "state", b"disposable")

    restore_recovery_set(
        manifest_path=created.manifest_path,
        restore_root=restore_root,
        working_cache=working_cache,
        passphrase="backup-passphrase-123",
    )

    assert not list(restore_root.rglob("stale"))
    assert (restore_root / "volumes/postgres-data/authoritative").read_bytes() == (
        b"postgres-data"
    )
    assert not (restore_root / "metadata/recovery-set.json").exists()
    assert (
        restore_root
        / "metadata/release-state/bundles/bundle-1/configuration/deploy/hosted/compose.yaml"
    ).stat().st_mode & 0o777 == 0o444
    assert list(working_cache.iterdir()) == []

    secret_root = tmp_path / "restored-secrets"
    restore_secret_recovery_bundle(
        restore_root / "secrets/current.recovery",
        secret_root=secret_root,
        passphrase="separate-recovery-passphrase",
    )
    assert (secret_root / "postgres_password").read_text() == "database-secret"
    assert (secret_root / "api_database_password").read_text() == "api-secret"
    assert (secret_root / "postgres_password").stat().st_mode & 0o777 == 0o600


def test_restore_gate_uses_tombstones_and_the_object_index_before_reopening(
    tmp_path: Path,
) -> None:
    import hashlib

    objects = tmp_path / "objects"
    payload = b'{"retained":true}'
    digest = hashlib.sha256(payload).hexdigest()
    write(objects / "sha256" / digest[:2] / f"{digest}.json", payload)
    write(objects / "sha256" / "de" / "deleted.json", b"backup-only bytes")

    verified = verify_restored_state(
        object_root=objects,
        snapshot={
            "pending_cleanup_count": 0,
            "tombstone_reference_count": 0,
            "resurrected_resource_count": 0,
            "unreferenced_index_count": 0,
            "rls_missing_count": 0,
            "latest_dataset_release_id": "dsr_latest",
            "objects": [
                {
                    "object_key": f"sha256:{digest}",
                    "sha256": digest,
                    "compressed_bytes": len(payload),
                    "object_kind": "content",
                }
            ],
        },
    )
    assert verified == {
        "latest_dataset_release_id": "dsr_latest",
        "verified_objects": 1,
    }

    with pytest.raises(RestoreVerificationError, match="Tombstone"):
        verify_restored_state(
            object_root=objects,
            snapshot={
                "pending_cleanup_count": 1,
                "tombstone_reference_count": 1,
                "resurrected_resource_count": 0,
                "unreferenced_index_count": 0,
                "rls_missing_count": 0,
                "latest_dataset_release_id": "dsr_latest",
                "objects": [],
            },
        )


def test_restore_gate_requires_the_authenticated_selected_set_within_rpo() -> None:
    selection = {
        "format": "thesistrace-authenticated-recovery-selection-v1",
        "backup_id": "backup_20260801T000000Z_aaaaaaaaaaaa",
        "release_bundle_id": "bundle-1",
        "backup_created_at": "2026-08-01T00:00:00+00:00",
        "incident_at": "2026-08-01T05:59:00+00:00",
        "committed_state_loss_bound_seconds": 21_540,
        "manifest_sha256": "a" * 64,
        "authenticated": True,
    }

    assert verify_authenticated_recovery_selection(
        selection,
        expected_backup_id="backup_20260801T000000Z_aaaaaaaaaaaa",
    ) == {
        "backup_id": "backup_20260801T000000Z_aaaaaaaaaaaa",
        "recovery_set_authenticated": True,
        "committed_state_loss_bound_seconds": 21_540,
        "release_bundle_id": "bundle-1",
        "workflow_probe_id": None,
    }

    with pytest.raises(RestoreVerificationError, match="six-hour RPO"):
        verify_authenticated_recovery_selection(
            {
                **selection,
                "incident_at": "2026-08-01T06:00:01+00:00",
                "committed_state_loss_bound_seconds": 21_601,
            },
            expected_backup_id="backup_20260801T000000Z_aaaaaaaaaaaa",
        )


def test_backup_never_marks_a_partial_coordinated_source_as_complete(
    tmp_path: Path,
) -> None:
    sources: dict[str, Path] = {}
    for name in (
        "postgres-data",
        "temporal-data",
        "immutable-objects",
        "insforge-storage",
        "release-state",
        "secret-recovery",
    ):
        path = tmp_path / "source" / name
        path.mkdir(parents=True)
        sources[name] = path

    with pytest.raises(BackupOperationError, match="coordinated source"):
        create_recovery_set(
            target=tmp_path / "off-node",
            sources=sources,
            release_bundle_id="bundle-1",
            passphrase="backup-passphrase-123",
        )

    assert not list((tmp_path / "off-node").glob("backup_*.json"))


def test_recovery_exercise_records_rpo_detection_and_execution_objectives(
    tmp_path: Path,
) -> None:
    recovery_selection = tmp_path / "selected-recovery-set.json"
    recovery_selection.write_text(
        '{"format":"thesistrace-authenticated-recovery-selection-v1",'
        '"backup_id":"backup_20260801T000000Z_aaaaaaaaaaaa","status":"complete",'
        '"backup_created_at":"2026-08-01T00:00:00+00:00",'
        '"incident_at":"2026-08-01T05:30:00+00:00",'
        '"committed_state_loss_bound_seconds":19800,'
        '"release_bundle_id":"bundle-1",'
        '"workflow_probe_id":"recovery-probe-exercise",'
        '"manifest_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"authenticated":true}'
    )

    evidence_path = write_recovery_exercise(
        recovery_selection_path=recovery_selection,
        evidence_dir=tmp_path / "evidence",
        incident_at=datetime(2026, 8, 1, 5, 30, tzinfo=UTC),
        detected_at=datetime(2026, 8, 2, 5, 0, tzinfo=UTC),
        restore_started_at=datetime(2026, 8, 2, 5, 10, tzinfo=UTC),
        restore_completed_at=datetime(2026, 8, 2, 7, 10, tzinfo=UTC),
        verification={
            "latest_dataset_release_id": "dsr_latest",
            "verified_objects": 42,
            "workflow_recovery_verified": True,
            "workflow_probe_id": "recovery-probe-exercise",
        },
        public_origin_smoke=True,
    )

    evidence = __import__("json").loads(evidence_path.read_text())
    assert evidence["status"] == "passed"
    assert evidence["committed_state_loss_bound_seconds"] == 19800
    assert evidence["detection_seconds"] == 84600
    assert evidence["recovery_execution_seconds"] == 7200
    assert evidence["objectives"] == {
        "committed_state_loss_within_6h": True,
        "detection_within_24h": True,
        "recovery_execution_within_8h": True,
        "public_origin_smoke": True,
        "workflow_recovery": True,
    }

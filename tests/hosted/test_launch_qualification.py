import json
import sqlite3
from pathlib import Path

import pytest

from thesistrace.config import Settings
from thesistrace.launch import (
    LaunchQualificationError,
    LaunchQualificationService,
    launch_attestation,
)
from thesistrace.operator import build_parser, run
from thesistrace.storage import MetadataStore

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_CHECKS = {
    "backend",
    "browser",
    "capacity",
    "coordinated_backup",
    "data_health",
    "direct_origin_security",
    "frontend",
    "full_restore",
    "migrations",
    "postgresql_rls",
    "public_origin",
    "quantitative_health",
    "recovery_matrix",
    "resource_exhaustion_matrix",
    "source_authorization",
    "storage",
    "system_health",
    "temporal_dispatch",
}
ATTESTATION_KEY = b"test-launch-attestation-key-32-bytes"


def passing_evidence(release_bundle_id: str = "release-1") -> dict[str, object]:
    return {
        "schema_version": "hosted-v2-launch-v1",
        "clean_stack": True,
        "release_bundle_id": release_bundle_id,
        "checks": {name: True for name in sorted(REQUIRED_CHECKS)},
        "records": {
            name: {"status": "passed"} for name in sorted(REQUIRED_CHECKS)
        },
    }


def record(
    service: LaunchQualificationService,
    *,
    actor: str,
    release_bundle_id: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    return service.record(
        actor=actor,
        release_bundle_id=release_bundle_id,
        evidence=evidence,
        attestation=launch_attestation(evidence, ATTESTATION_KEY),
        attestation_key=ATTESTATION_KEY,
    )


def test_latest_launch_measurement_is_an_immutable_invitation_gate(
    tmp_path: Path,
) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    service = LaunchQualificationService(store)
    assert service.is_qualified() is False

    with pytest.raises(
        LaunchQualificationError,
        match="not attested",
    ) as forged:
        service.record(
            actor="operator-1",
            release_bundle_id="release-1",
            evidence=passing_evidence(),
            attestation="0" * 64,
            attestation_key=ATTESTATION_KEY,
        )
    assert forged.value.reason_code == (
        "LAUNCH_QUALIFICATION_ATTESTATION_INVALID"
    )

    failing = passing_evidence()
    failing["checks"]["browser"] = False
    recorded_failure = record(
        service,
        actor="operator-1",
        release_bundle_id="release-1",
        evidence=failing,
    )
    assert recorded_failure["status"] == "failed"
    assert recorded_failure["failures"] == ["browser"]
    assert service.is_qualified() is False

    stale = record(
        service,
        actor="operator-1",
        release_bundle_id="release-2",
        evidence=passing_evidence("release-1"),
    )
    assert stale["status"] == "failed"
    assert stale["failures"] == ["release_bundle_id"]

    incomplete = passing_evidence()
    del incomplete["records"]["storage"]
    missing_record = record(
        service,
        actor="operator-1",
        release_bundle_id="release-1",
        evidence=incomplete,
    )
    assert missing_record["status"] == "failed"
    assert missing_record["failures"] == ["record:storage"]

    recorded_pass = record(
        service,
        actor="operator-1",
        release_bundle_id="release-1",
        evidence=passing_evidence(),
    )
    assert recorded_pass["status"] == "passed"
    assert service.is_qualified() is True

    assert LaunchQualificationService(
        store,
        required_release_bundle_id="release-2",
    ).is_qualified() is False
    assert LaunchQualificationService(
        store,
        required_release_bundle_id="release-1",
    ).is_qualified() is True

    with store.connect() as connection:
        try:
            connection.execute(
                "UPDATE launch_qualifications SET status = 'failed' WHERE id = ?",
                (recorded_pass["id"],),
            )
        except sqlite3.IntegrityError as error:
            assert "immutable" in str(error)
        else:
            raise AssertionError("launch qualification was mutable")


def test_operator_can_inspect_but_cannot_fabricate_launch_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["launch-qualification", "record"]
        )
    store = MetadataStore(settings.metadata_path)
    store.initialize()
    recorded = record(
        LaunchQualificationService(store),
        actor="release-acceptance",
        release_bundle_id="release-1",
        evidence=passing_evidence(),
    )

    assert run(
        ["launch-qualification", "inspect"],
        settings=settings,
    ) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["id"] == recorded["id"]


def test_launch_schema_is_immutable_and_private() -> None:
    migration = (
        ROOT
        / "deploy"
        / "hosted"
        / "migrations"
        / "0024_launch_qualification.sql"
    ).read_text()
    assert "launch_qualifications" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "REVOKE ALL" in migration
    assert "GRANT" not in migration

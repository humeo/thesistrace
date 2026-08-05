import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.management import (
    HOSTED_TUSHARE_SCOPE,
    SourceAuthorizationService,
)
from thesistrace.operator import run
from thesistrace.storage import MetadataStore

ROOT = Path(__file__).resolve().parents[2]


class UnavailableTransport:
    def post(self, payload: Mapping[str, object]) -> dict[str, object]:
        del payload
        return {"code": 2002, "msg": "permission denied", "data": None}


def settings_for(tmp_path: Path, *, token: str | None = None) -> Settings:
    return Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        tushare_token=token,
    )


def test_token_alone_does_not_open_live_publication_but_fixture_remains_available(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path, token="credential-must-not-be-audit-data")
    with TestClient(create_app(settings, tushare_transport=UnavailableTransport())) as client:
        blocked = client.post(
            "/api/v1/dataset-releases/bootstrap-live",
            headers={"Idempotency-Key": "live-closed"},
            json={"as_of": "2026-07-31"},
        )
        fixture = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "fixture-open"},
            json={"fixture": "v1"},
        )

    assert blocked.status_code == 409
    assert blocked.json()["detail"] == {
        "reason_code": "SOURCE_AUTHORIZATION_REQUIRED",
        "message": "hosted shared Tushare use requires an accepted Operator declaration",
    }
    assert fixture.status_code == 201


def test_operator_records_and_inspects_a_durable_sanitized_declaration(
    tmp_path: Path,
    capsys,
) -> None:
    settings = settings_for(tmp_path)

    assert (
        run(
            [
                "source-authorization",
                "record",
                "--actor",
                "operator-1",
                "--scope",
                HOSTED_TUSHARE_SCOPE,
            ],
            settings=settings,
        )
        == 0
    )
    recorded = capsys.readouterr().out
    assert "does not validate upstream legal rights" in recorded

    assert run(["source-authorization", "inspect"], settings=settings) == 0
    inspected = capsys.readouterr().out
    assert "operator-1" in inspected
    assert HOSTED_TUSHARE_SCOPE in inspected
    assert "audit_event_id" in inspected

    restarted_store = MetadataStore(settings.metadata_path)
    restarted_store.initialize()
    service = SourceAuthorizationService(restarted_store)
    assert service.is_authorized() is True
    declaration = service.inspect()
    assert declaration is not None
    assert declaration["actor"] == "operator-1"

    serialized_audit = str(restarted_store.list_management_audit_events())
    assert "credential" not in serialized_audit
    assert "token" not in serialized_audit.lower()


def test_rejected_state_change_is_audited_without_a_declaration(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    assert (
        run(
            [
                "source-authorization",
                "record",
                "--actor",
                "operator-1",
                "--scope",
                "credential-super-secret",
            ],
            settings=settings,
        )
        == 2
    )

    store = MetadataStore(settings.metadata_path)
    store.initialize()
    service = SourceAuthorizationService(store)

    assert service.inspect() is None
    events = store.list_management_audit_events()
    assert len(events) == 1
    assert events[0]["outcome"] == "rejected"
    assert events[0]["reason_code"] == "SOURCE_AUTHORIZATION_SCOPE_REJECTED"
    assert "credential-super-secret" not in str(events)
    with pytest.raises(sqlite3.IntegrityError, match="non-deletable"):
        with store.connect() as connection:
            connection.execute("DELETE FROM management_audit_events")


def test_recording_the_declaration_opens_only_the_policy_gate(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, token="configured-token")
    store = MetadataStore(settings.metadata_path)
    store.initialize()
    SourceAuthorizationService(store).record(
        actor="operator-1",
        scope=HOSTED_TUSHARE_SCOPE,
    )

    with TestClient(create_app(settings, tushare_transport=UnavailableTransport())) as client:
        response = client.post(
            "/api/v1/dataset-releases/bootstrap-live",
            headers={"Idempotency-Key": "live-open"},
            json={"as_of": "2026-07-31"},
        )

    assert response.status_code == 424
    assert response.json()["detail"]["reason_code"] == "MISSING_PERMISSION"


def test_source_policy_keeps_its_cli_and_historical_schema() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    stack = (ROOT / "scripts" / "hosted-stack").read_text()
    migration = (
        ROOT / "deploy" / "hosted" / "migrations" / "0002_source_authorization.sql"
    ).read_text()

    assert 'thesistrace-operator = "thesistrace.operator:main"' in project
    assert "thesistrace-operator" in stack
    assert "source_authorization_declarations" in migration
    assert "management_audit_events" in migration
    assert "BEFORE UPDATE OR DELETE" in migration

from __future__ import annotations

import inspect
import json
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from thesistrace._postgres import PostgresDatabase
from thesistrace.research_run.models import (
    OrganizeResearchRunCommand,
    ResearchRunCancelCommand,
    StartTrackingCommand,
)
from thesistrace.research_run.service import (
    PreparedResearchRunAdmission,
    ResearchRunService,
)

RESEARCHER_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_RESEARCHER_ID = UUID("22222222-2222-4222-8222-222222222222")


class _Rows:
    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return []


class _Transaction:
    def __init__(self) -> None:
        self.parameters: tuple[object, ...] | None = None
        self.statements: list[str] = []

    def execute(self, statement: str, parameters: tuple[object, ...]) -> _Rows:
        self.statements.append(statement)
        self.parameters = parameters
        return _Rows()


class _Database:
    def __init__(self) -> None:
        self.transaction_value = _Transaction()
        self.open_count = 0

    @contextmanager
    def transaction(self):  # type: ignore[no-untyped-def]
        self.open_count += 1
        yield self.transaction_value


def _cursor(
    *,
    researcher_id: UUID = RESEARCHER_ID,
    folder_id: str | None = "folder_default",
    research_kind: str | None = "factor_evaluation",
) -> str:
    payload = json.dumps(
        {
            "created_at": datetime(2026, 8, 28, tzinfo=UTC).isoformat(),
            "folder_id": folder_id,
            "id": "run_123",
            "research_kind": research_kind,
            "researcher_id": str(researcher_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return urlsafe_b64encode(payload).decode().rstrip("=")


def test_research_run_browser_service_surface_requires_explicit_researcher() -> None:
    expected = {
        "admit": ("self", "researcher_id", "command"),
        "list": ("self", "researcher_id", "folder_id", "research_kind", "cursor", "limit"),
        "get": ("self", "researcher_id", "run_id"),
        "get_detail": ("self", "researcher_id", "run_id"),
        "organize": ("self", "researcher_id", "run_id", "command"),
        "delete": ("self", "researcher_id", "run_id"),
        "cancel": ("self", "researcher_id", "run_id", "command"),
        "start_tracking": ("self", "researcher_id", "run_id", "command"),
        "prepare_child_admission": ("self", "researcher_id", "command", "dataset"),
    }

    for method_name, parameter_names in expected.items():
        signature = inspect.signature(getattr(ResearchRunService, method_name))
        assert tuple(signature.parameters) == parameter_names

    assert "researcher_id" in PreparedResearchRunAdmission.__annotations__


@pytest.mark.parametrize(
    "cursor,folder_id,research_kind",
    [
        ("not-a-cursor", "folder_default", "factor_evaluation"),
        (f"{_cursor()}!", "folder_default", "factor_evaluation"),
        (_cursor(researcher_id=OTHER_RESEARCHER_ID), "folder_default", "factor_evaluation"),
        (_cursor(folder_id="folder_other"), "folder_default", "factor_evaluation"),
        (_cursor(research_kind="strategy_backtest"), "folder_default", "factor_evaluation"),
    ],
)
def test_list_cursor_rejects_malformed_or_context_mismatched_values_before_query(
    cursor: str,
    folder_id: str,
    research_kind: str,
) -> None:
    database = _Database()
    service = ResearchRunService(cast(PostgresDatabase, database))

    with pytest.raises(ValueError, match="ResearchRun cursor is invalid"):
        service.list(
            RESEARCHER_ID,
            folder_id=folder_id,
            research_kind=research_kind,  # type: ignore[arg-type]
            cursor=cursor,
            limit=20,
        )

    assert database.open_count == 0


def test_list_cursor_allows_limit_change_and_scopes_the_query_to_researcher() -> None:
    database = _Database()
    service = ResearchRunService(cast(PostgresDatabase, database))

    result = service.list(
        RESEARCHER_ID,
        folder_id="folder_default",
        research_kind="factor_evaluation",
        cursor=_cursor(),
        limit=7,
    )

    assert result.items == []
    assert result.next_cursor is None
    assert database.open_count == 1
    assert database.transaction_value.parameters is not None
    assert database.transaction_value.parameters[0] == RESEARCHER_ID


def test_cross_researcher_mutations_stop_before_receipt_or_target_state_checks() -> None:
    database = _Database()
    service = ResearchRunService(
        cast(PostgresDatabase, database),
        publication=object(),  # type: ignore[arg-type]
        activate_track=lambda _transaction, _researcher_id, _origin: None,  # type: ignore[arg-type]
    )

    assert (
        service.organize(
            RESEARCHER_ID,
            "run_owned_elsewhere",
            OrganizeResearchRunCommand(folder_id="folder_missing"),
        )
        is None
    )
    assert len(database.transaction_value.statements) == 1
    assert "research_folders.folders" not in database.transaction_value.statements[0]

    database.transaction_value.statements.clear()
    assert (
        service.cancel(
            RESEARCHER_ID,
            "run_owned_elsewhere",
            ResearchRunCancelCommand(request_id="cancel-cross-owner"),
        )
        is None
    )
    assert len(database.transaction_value.statements) == 2
    assert not any(
        "cancel_receipts" in statement
        for statement in database.transaction_value.statements
    )

    database.transaction_value.statements.clear()
    assert (
        service.start_tracking(
            RESEARCHER_ID,
            "run_owned_elsewhere",
            StartTrackingCommand(request_id="track-cross-owner"),
        )
        is None
    )
    assert len(database.transaction_value.statements) == 1
    assert "start_tracking_receipts" not in database.transaction_value.statements[0]

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from pydantic import TypeAdapter

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.data import DatasetAdmissionSnapshot
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core
from thesistrace.research_run import (
    OrganizeResearchRunCommand,
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionConflict,
    ResearchRunCancelCommand,
    ResearchRunService,
)
from thesistrace.researcher import ResearcherIdentity, ResearcherService

RESEARCHER_A = ResearcherIdentity(
    researcher_id=UUID("20a7ca8d-d1d5-4eb5-beb5-af4cb6f777a1"),
    email="run-alpha@example.com",
    display_label="run-alpha",
)
RESEARCHER_B = ResearcherIdentity(
    researcher_id=UUID("46b12c3e-bc35-49db-8f3b-29c4cdb23146"),
    email="run-beta@example.com",
    display_label="run-beta",
)
ADMISSION = TypeAdapter(ResearchRunAdmissionCommand)


@pytest.fixture
def ownership_database(core_settings: CoreSettings) -> PostgresDatabase:
    _drop_core_schemas(core_settings.database_url)
    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        yield database
    finally:
        database.close()
        _drop_core_schemas(core_settings.database_url)


def test_research_run_service_scopes_resources_receipts_and_cursors(
    ownership_database: PostgresDatabase,
) -> None:
    researchers = ResearcherService(ownership_database)
    researchers.bootstrap(RESEARCHER_A)
    researchers.bootstrap(RESEARCHER_B)
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=date(2026, 8, 5),
        coverage_start=date(2026, 8, 3),
        coverage_end=date(2026, 8, 5),
        research_sessions=(
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
        ),
        available_field_ids=frozenset({"price.close.adjusted"}),
        maximum_universe_cardinality=lambda _universe, _start, _end: 300,
        financial_research_readiness="not_ready",
    )
    service = ResearchRunService(
        ownership_database,
        compile_formula=alpha_language.compile,
        current_dataset=lambda: snapshot,
    )
    shared = _command("shared-request")

    run_a = service.admit(RESEARCHER_A.researcher_id, shared)
    run_b = service.admit(RESEARCHER_B.researcher_id, shared)
    assert run_a.id != run_b.id
    assert service.admit(RESEARCHER_A.researcher_id, shared) == run_a

    with pytest.raises(ResearchRunAdmissionConflict):
        service.admit(
            RESEARCHER_A.researcher_id,
            ADMISSION.validate_python(
                {**shared.model_dump(mode="json"), "name": "Conflicting replay"}
            ),
        )

    run_a_second = service.admit(
        RESEARCHER_A.researcher_id,
        _command("second-alpha-request"),
    )
    assert service.get(RESEARCHER_A.researcher_id, run_a.id) == run_a
    assert service.get(RESEARCHER_A.researcher_id, run_b.id) is None
    assert service.get_detail(RESEARCHER_A.researcher_id, run_b.id) is None
    assert service.organize(
        RESEARCHER_A.researcher_id,
        run_b.id,
        OrganizeResearchRunCommand(name="Hidden"),
    ) is None

    first_page = service.list(RESEARCHER_A.researcher_id, limit=1)
    assert len(first_page.items) == 1
    assert first_page.next_cursor is not None
    second_page = service.list(
        RESEARCHER_A.researcher_id,
        cursor=first_page.next_cursor,
        limit=1,
    )
    assert {first_page.items[0].id, second_page.items[0].id} == {
        run_a.id,
        run_a_second.id,
    }
    with pytest.raises(ValueError, match="ResearchRun cursor is invalid"):
        service.list(
            RESEARCHER_B.researcher_id,
            cursor=first_page.next_cursor,
            limit=1,
        )

    cancelled_a = service.cancel(
        RESEARCHER_A.researcher_id,
        run_a.id,
        ResearchRunCancelCommand(request_id="shared-cancel"),
    )
    cancelled_b = service.cancel(
        RESEARCHER_B.researcher_id,
        run_b.id,
        ResearchRunCancelCommand(request_id="shared-cancel"),
    )
    assert cancelled_a is not None and cancelled_a.run.status == "cancelled"
    assert cancelled_b is not None and cancelled_b.run.status == "cancelled"
    assert service.cancel(
        RESEARCHER_A.researcher_id,
        run_b.id,
        ResearchRunCancelCommand(request_id="cross-owner-cancel"),
    ) is None

    with ownership_database.transaction() as transaction:
        receipt_owners = transaction.execute(
            """
            SELECT researcher_id
            FROM research_runs.admission_requests
            WHERE request_id = 'shared-request'
            ORDER BY researcher_id
            """
        ).fetchall()
        cancel_owners = transaction.execute(
            """
            SELECT researcher_id
            FROM research_runs.cancel_receipts
            WHERE request_id = 'shared-cancel'
            ORDER BY researcher_id
            """
        ).fetchall()
    assert {row["researcher_id"] for row in receipt_owners} == {
        RESEARCHER_A.researcher_id,
        RESEARCHER_B.researcher_id,
    }
    assert {row["researcher_id"] for row in cancel_owners} == {
        RESEARCHER_A.researcher_id,
        RESEARCHER_B.researcher_id,
    }


def _command(request_id: str) -> ResearchRunAdmissionCommand:
    return ADMISSION.validate_python(
        {
            "request_id": request_id,
            "folder_id": "folder_default",
            "name": "Owned Research",
            "formula": "close",
            "hypothesis": None,
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "factor_evaluation",
        }
    )


def _drop_core_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema_name in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
    finally:
        database.close()

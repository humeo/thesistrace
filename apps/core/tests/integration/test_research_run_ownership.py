from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb
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
    ResearchRunMetricFilter,
    ResearchRunService,
)
from thesistrace.researcher import ResearcherIdentity, ResearcherService
from thesistrace.researcher.quota import QuotaPolicy

TEST_QUOTA = QuotaPolicy(timezone="Asia/Shanghai", daily_model_budget_nanodollars=1_000_000_000,
                         daily_run_limit=10, active_daily_track_limit=10)

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
        universe_member_union_cardinalities=lambda _universe, windows: tuple(300 for _ in windows),
        financial_research_readiness="not_ready",
    )
    service = ResearchRunService(
        ownership_database,
        compile_formula=alpha_language.compile,
        current_dataset=lambda: snapshot,
        quota_policy=lambda _rid: TEST_QUOTA,
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

    page = service.list_page(RESEARCHER_A.researcher_id, page=1, page_size=1)
    assert page.total_count == 2
    assert len(page.items) == 1
    last_page = service.list_page(RESEARCHER_A.researcher_id, page=2, page_size=1)
    assert last_page.total_count == 2
    assert {page.items[0].id, last_page.items[0].id} == {run_a.id, run_a_second.id}
    assert service.list_page(RESEARCHER_B.researcher_id).total_count == 1
    empty = service.list_page(RESEARCHER_A.researcher_id, research_kind="strategy_backtest")
    assert empty.total_count == 0
    assert empty.items == []
    assert service.list_page(RESEARCHER_A.researcher_id, folder_id="missing").total_count == 0
    assert service.list_page(RESEARCHER_A.researcher_id, page=3, page_size=1).items == []

    # The older record must move across the page boundary, not merely sort in-page.
    with ownership_database.transaction() as transaction:
        for run, score in ((run_a, 0.8), (run_a_second, 0.2), (run_b, 0.99)):
            transaction.execute(
                "UPDATE research_runs.runs SET key_metrics = %s WHERE id = %s",
                (Jsonb({"research_kind": "factor_evaluation",
                        "one_session_rank_ic": score, "five_session_rank_ic": score,
                        "twenty_session_rank_ic": score}), run.id),
            )
    for key in ("one_session_rank_ic", "five_session_rank_ic", "twenty_session_rank_ic"):
        for direction, expected in (("descending", [run_a.id, run_a_second.id]),
                                    ("ascending", [run_a_second.id, run_a.id])):
            pages = [service.list_page(RESEARCHER_A.researcher_id, page=p, page_size=1,
                                      sort_by=key, sort_direction=direction,
                                      research_kind="factor_evaluation") for p in (1, 2)]
            assert [page.items[0].id for page in pages] == expected
            assert all(page.total_count == 2 for page in pages)
        filtered = service.list_page(
            RESEARCHER_A.researcher_id, page_size=1,
            metric_filters=[ResearchRunMetricFilter(metric=key, operator="gt", value=0.2),
                            ResearchRunMetricFilter(metric=key, operator="lte", value=0.8)],
        )
        assert filtered.total_count == 1
        assert filtered.items[0].id == run_a.id
    with ownership_database.transaction() as transaction:
        transaction.execute("UPDATE research_runs.runs SET key_metrics = NULL WHERE id = %s",
                            (run_a.id,))
    for direction in ("ascending", "descending"):
        page = service.list_page(RESEARCHER_A.researcher_id, sort_by="five_session_rank_ic",
                                 sort_direction=direction)
        assert [item.id for item in page.items] == [run_a_second.id, run_a.id]

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


def test_daily_run_quota_is_atomic_retained_and_operator_exempt(ownership_database):
    from thesistrace.research_run import ResearchRunAdmissionRejected

    ResearcherService(ownership_database).bootstrap(RESEARCHER_A)
    ResearcherService(ownership_database).bootstrap(RESEARCHER_B)
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=date(2026, 8, 5),
        coverage_start=date(2026, 8, 3),
        coverage_end=date(2026, 8, 5),
        research_sessions=(date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)),
        available_field_ids=frozenset({"price.close.adjusted"}),
        maximum_universe_cardinality=lambda _u, _s, _e: 300,
        universe_member_union_cardinalities=lambda _u, windows: tuple(300 for _ in windows),
        financial_research_readiness="not_ready",
    )
    service = ResearchRunService(
        ownership_database,
        compile_formula=alpha_language.compile,
        current_dataset=lambda: snapshot,
        quota_policy=lambda rid: TEST_QUOTA.model_copy(update={
            "daily_run_limit": None if rid == RESEARCHER_B.researcher_id else 3,
        }),
    )
    for index in range(2):
        service.admit(RESEARCHER_A.researcher_id, _command(f"quota-{index}"))

    def submit(index):
        try:
            return service.admit(RESEARCHER_A.researcher_id, _command(f"concurrent-{index}"))
        except ResearchRunAdmissionRejected as error:
            assert error.issues[0].code == "DAILY_RUN_QUOTA_EXCEEDED"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, range(2)))
    assert sum(item is not None for item in outcomes) == 1
    replay = service.admit(RESEARCHER_A.researcher_id, _command("quota-0"))
    service.cancel(
        RESEARCHER_A.researcher_id, replay.id, ResearchRunCancelCommand(request_id="quota-cancel")
    )
    with pytest.raises(ResearchRunAdmissionRejected):
        service.admit(RESEARCHER_A.researcher_id, _command("after-cancel"))
    for index in range(12):
        service.admit(RESEARCHER_B.researcher_id, _command(f"operator-{index}"))
    with ownership_database.transaction() as transaction:
        transaction.execute(
            """UPDATE research_runs.run_ownership
            SET created_at = created_at - interval '1 day' WHERE researcher_id = %s""",
            (RESEARCHER_A.researcher_id,),
        )
    assert service.admit(RESEARCHER_A.researcher_id, _command("next-day")).id


def _drop_core_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema_name in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
    finally:
        database.close()


@pytest.mark.parametrize("sort_by", [
    "annualized_excess_return", "sharpe", "maximum_drawdown",
    "one_session_rank_ic", "five_session_rank_ic", "twenty_session_rank_ic",
])
def test_strategy_metric_sorting_precedes_pagination(ownership_database, sort_by):
    ResearcherService(ownership_database).bootstrap(RESEARCHER_A)
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=date(2026, 8, 5),
        coverage_start=date(2026, 8, 3), coverage_end=date(2026, 8, 5),
        research_sessions=(date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)),
        available_field_ids=frozenset({"price.close.adjusted"}),
        maximum_universe_cardinality=lambda _u, _s, _e: 300,
        universe_member_union_cardinalities=lambda _u, windows: tuple(300 for _ in windows),
        financial_research_readiness="not_ready",
    )
    service = ResearchRunService(ownership_database, compile_formula=alpha_language.compile,
                                current_dataset=lambda: snapshot,
                                quota_policy=lambda _rid: TEST_QUOTA)
    runs = []
    for index, score in enumerate((10.0, 2.0, 2.0, None)):
        command = ADMISSION.validate_python({
            **_command(f"metric-{index}").model_dump(mode="json"),
            "research_kind": "strategy_backtest", "holdings_count": 10,
            "rebalance_every_sessions": 5,
        })
        run = service.admit(RESEARCHER_A.researcher_id, command)
        runs.append(run)
        metrics = None if score is None else Jsonb({
            "research_kind": "strategy_backtest", "annualized_excess_return": score,
            "sharpe": score, "maximum_drawdown": score,
            "one_session_rank_ic": score, "five_session_rank_ic": score,
            "twenty_session_rank_ic": score,
        })
        with ownership_database.transaction() as transaction:
            transaction.execute(
                "UPDATE research_runs.runs SET key_metrics = %s, created_at = %s WHERE id = %s",
                (metrics, "2026-08-06T00:00:00Z", run.id),
            )
    ties = sorted([runs[1].id, runs[2].id])
    for direction, expected in (("descending", [runs[0].id, *ties, runs[3].id]),
                                ("ascending", [*ties, runs[0].id, runs[3].id])):
        pages = [service.list_page(RESEARCHER_A.researcher_id, page=p, page_size=1,
                                  sort_by=sort_by, sort_direction=direction,
                                  research_kind="strategy_backtest", folder_id="folder_default")
                 for p in range(1, 5)]
        assert [page.items[0].id for page in pages] == expected
        assert all(page.total_count == 4 for page in pages)
    matching = service.list_page(
        RESEARCHER_A.researcher_id, page_size=1, sort_by=sort_by,
        metric_filters=[ResearchRunMetricFilter(metric=sort_by, operator="gt", value=2)],
    )
    assert matching.total_count == 1
    assert matching.items[0].id == runs[0].id
    bounded = service.list_page(
        RESEARCHER_A.researcher_id, page_size=1, page=2,
        metric_filters=[ResearchRunMetricFilter(metric=sort_by, operator="gte", value=2),
                        ResearchRunMetricFilter(metric=sort_by, operator="lt", value=10)],
    )
    assert bounded.total_count == 2
    assert len(bounded.items) == 1
    assert bounded.items[0].id in ties

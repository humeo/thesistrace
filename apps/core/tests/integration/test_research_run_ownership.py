from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import UUID

import anyio
import pytest
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.data import DatasetAdmissionSnapshot
from thesistrace.data.models import DatasetCoverage
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
        family_coverage={
            "equity.eod_price": DatasetCoverage(start=date(2026, 8, 3), end=date(2026, 8, 5)),
        },
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
        ADMISSION.validate_python({
            **_command("second-alpha-request").model_dump(mode="json"),
            "name": "中文动量 100%_收益",
            "hypothesis": "检查成交量；Keep Turnover Low! path\\sample",
        }),
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

    # Search happens before paging/counting, includes frozen notes and formulas,
    # treats SQL wildcard characters literally, and retains researcher ownership.
    for search, expected in (
        ("中文动量", {run_a_second.id}),
        ("动量", {run_a_second.id}),
        ("量", {run_a_second.id}),
        ("  TURNOVER  ", {run_a_second.id}),
        ("成交量", {run_a_second.id}),
        ("100%_", {run_a_second.id}),
        ("%", {run_a_second.id}),
        ("_", {run_a_second.id}),
        ("!", {run_a_second.id}),
        ("\\sample", {run_a_second.id}),
        ("%sample", set()),
        ("Low! path", {run_a_second.id}),
        ("收益检查", set()),
        ("Owned", {run_a.id}),
        ("CLOSE", {run_a.id, run_a_second.id}),
        ("   ", {run_a.id, run_a_second.id}),
        ("no matching research", set()),
        ("' OR true --", set()),
    ):
        matches = service.list_page(RESEARCHER_A.researcher_id, search=search)
        assert {item.id for item in matches.items} == expected
        assert matches.total_count == len(expected)
    pages = [service.list_page(RESEARCHER_A.researcher_id, search="close",
                              page=page, page_size=1) for page in (1, 2)]
    assert {page.items[0].id for page in pages} == {run_a.id, run_a_second.id}
    assert all(page.total_count == 2 for page in pages)
    beyond = service.list_page(RESEARCHER_A.researcher_id, search="close", page=3, page_size=1)
    assert beyond.items == [] and beyond.total_count == 2
    assert service.list_page(RESEARCHER_B.researcher_id, search="成交量").total_count == 0
    for filters in ({"folder_id": "missing"}, {"research_kind": "strategy_backtest"}):
        assert service.list_page(RESEARCHER_A.researcher_id, search="动量", **filters).items == []

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
        assert service.list_page(
            RESEARCHER_A.researcher_id, search="动量",
            metric_filters=[ResearchRunMetricFilter(metric=key, operator="gt", value=0.2)],
        ).total_count == 0
    with ownership_database.transaction() as transaction:
        transaction.execute("UPDATE research_runs.runs SET key_metrics = NULL WHERE id = %s",
                            (run_a.id,))
    for direction in ("ascending", "descending"):
        page = service.list_page(RESEARCHER_A.researcher_id, sort_by="five_session_rank_ic",
                                 sort_direction=direction)
        assert [item.id for item in page.items] == [run_a_second.id, run_a.id]

    service.organize(RESEARCHER_A.researcher_id, run_a_second.id,
                     OrganizeResearchRunCommand(name="Renamed Search Target"))
    assert service.list_page(RESEARCHER_A.researcher_id, search="动量").total_count == 0
    renamed = service.list_page(RESEARCHER_A.researcher_id, search="renamed")
    assert [item.id for item in renamed.items] == [run_a_second.id]
    assert service.list_page(RESEARCHER_A.researcher_id, search="成交量").total_count == 1

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
        family_coverage={
            "equity.eod_price": DatasetCoverage(start=date(2026, 8, 3), end=date(2026, 8, 5)),
        },
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
    admitted = service.admit(RESEARCHER_A.researcher_id, _command("after-cancel"))
    with ownership_database.transaction() as tx:
        tx.execute("UPDATE research_runs.runs SET status='running' WHERE id=%s", (admitted.id,))
        tx.execute("UPDATE research_runs.runs SET status='failed' WHERE id=%s", (admitted.id,))
    replacement = service.admit(RESEARCHER_A.researcher_id, _command("after-failure"))
    with ownership_database.transaction() as tx:
        tx.execute("DELETE FROM research_runs.admission_requests WHERE run_id=%s", (admitted.id,))
        tx.execute("DELETE FROM research_runs.runs WHERE id=%s", (admitted.id,))
        tx.execute("UPDATE research_runs.runs SET status='running' WHERE id=%s", (replacement.id,))
    service.cancel(RESEARCHER_A.researcher_id,replacement.id,ResearchRunCancelCommand(request_id="started-cancel"))
    with pytest.raises(ResearchRunAdmissionRejected):
        service.admit(RESEARCHER_A.researcher_id,_command("after-started-cancel"))
    assert service.quota_usage(RESEARCHER_A.researcher_id)['research'] == dict(
        actual=1, reserved=2, remaining=0, limit=3,
    )
    for index in range(12):
        service.admit(RESEARCHER_B.researcher_id, _command(f"operator-{index}"))
    with ownership_database.transaction() as transaction:
        transaction.execute(
            """UPDATE research_runs.run_ownership
            SET created_at = created_at - interval '1 day' WHERE researcher_id = %s""",
            (RESEARCHER_A.researcher_id,),
        )
    assert service.admit(RESEARCHER_A.researcher_id, _command("next-day")).id
    for index in range(2):
        service.admit(RESEARCHER_A.researcher_id, _command(f"today-{index}"))
    old = service.admit(RESEARCHER_A.researcher_id, _command("quota-1"))
    with ownership_database.transaction() as tx:
        tx.execute("UPDATE research_runs.runs SET status='failed' WHERE id=%s", (old.id,))
    with pytest.raises(ResearchRunAdmissionRejected):
        service.admit(RESEARCHER_A.researcher_id, _command("no-new-day-compensation"))


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
])
def test_strategy_metric_sorting_precedes_pagination(ownership_database, sort_by):
    ResearcherService(ownership_database).bootstrap(RESEARCHER_A)
    snapshot = DatasetAdmissionSnapshot(
        family_coverage={
            "equity.eod_price": DatasetCoverage(start=date(2026, 8, 3), end=date(2026, 8, 5)),
        },
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
        command = ADMISSION.validate_python({"volatility_window": 20, "weighting": "equal_weight",
            **_command(f"metric-{index}").model_dump(mode="json"),
            "research_kind": "strategy_backtest", "initial_cash_cny": "10000000",
            "holdings_count": 10,
            "selection_every_sessions": 5,
        })
        run = service.admit(RESEARCHER_A.researcher_id, command)
        runs.append(run)
        metrics = None if score is None else Jsonb({
            "research_kind": "strategy_backtest", "annualized_excess_return": score,
            "sharpe": score, "maximum_drawdown": score,
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


@pytest.fixture
def ranked_records(ownership_database):
    ResearcherService(ownership_database).bootstrap(RESEARCHER_A)
    snapshot = DatasetAdmissionSnapshot(
        family_coverage={
            "equity.eod_price": DatasetCoverage(start=date(2026, 8, 3), end=date(2026, 8, 5)),
        },
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
                                quota_policy=lambda _rid: TEST_QUOTA.model_copy(
                                    update={"daily_run_limit": None}))
    ResearcherService(ownership_database).bootstrap(RESEARCHER_B)
    records = []
    for index in range(65):
        command = ADMISSION.validate_python({
            **_command(f"rank-{index}").model_dump(mode="json"),
            "name": f"低波动 100%_策略 {index:02d}", "research_kind": "strategy_backtest",
            "initial_cash_cny": "10000000", "holdings_count": 10,
            "volatility_window": 20, "weighting": "equal_weight",
            "selection_every_sessions": 5,
        })
        run = service.admit(RESEARCHER_A.researcher_id, command)
        score = 10 - index if index < 64 else None
        records.append(run.id)
        with ownership_database.transaction() as transaction:
            transaction.execute(
                "UPDATE research_runs.runs SET status = 'succeeded', created_at = %s, "
                "key_metrics = %s WHERE id = %s",
                ("2026-08-01T00:00:00Z" if index < 10 else "2026-08-02T00:00:00Z",
                 Jsonb({"research_kind": "strategy_backtest", "sharpe": score,
                        "annualized_excess_return": None if score is None else score / 100,
                        "maximum_drawdown": 0.1}), run.id),
            )
    foreign = service.admit(RESEARCHER_B.researcher_id, command.model_copy(update={
        "request_id": "foreign-rank", "name": "foreign high score",
    }))
    with ownership_database.transaction() as transaction:
        transaction.execute("UPDATE research_runs.runs SET status = 'succeeded', key_metrics = %s "
                            "WHERE id = %s", (Jsonb({"research_kind": "strategy_backtest",
                            "sharpe": 999, "annualized_excess_return": 9,
                            "maximum_drawdown": 0.01}), foreign.id))
    return service, records


def test_owned_global_top_ten_precedes_cursor_and_all_filters(ranked_records):
    service, records = ranked_records
    assert not set(records[:10]) & {run.id for run in service.list(
        RESEARCHER_A.researcher_id, limit=50).items}
    query = dict(research_kind="strategy_backtest", status="succeeded", search="100%_",
                 research_period={"start_date": "2026-08-03", "end_date": "2026-08-04"},
                 universe="top300", sort_by="sharpe", sort_direction="descending")
    # _command's recorded end is used exactly, not inferred from the Dataset Head.
    query["research_period"]["end_date"] = service.get(
        RESEARCHER_A.researcher_id, records[0]).end_date.isoformat()
    first = service.list(RESEARCHER_A.researcher_id, **query, limit=10)
    assert [item.id for item in first.items] == records[:10]
    assert first.total_count == 65 and first.items[0].universe == "top300"
    second = service.list(RESEARCHER_A.researcher_id, **query, cursor=first.next_cursor, limit=7)
    assert [item.id for item in second.items] == records[10:17]
    assert second.total_count == 65
    matching = service.list(RESEARCHER_A.researcher_id, **query, metric_filters=[
        {"metric": "sharpe", "operator": "gte", "value": 1},
        {"metric": "maximum_drawdown", "operator": "lte", "value": 0.2},
    ], limit=10)
    assert [item.id for item in matching.items] == records[:10]
    assert matching.total_count == 10
    assert matching.next_cursor is None
    for change in ({"search": "other"}, {"status": "failed"}, {"universe": "top1000"},
                   {"sort_by": "maximum_drawdown"}, {"sort_direction": "ascending"},
                   {"metric_filters": [{"metric": "sharpe", "operator": "gt", "value": 2}]}):
        with pytest.raises(ValueError, match="cursor is invalid"):
            service.list(RESEARCHER_A.researcher_id, **(query | change), cursor=first.next_cursor)
    with pytest.raises(ValueError, match="cursor is invalid"):
        service.list(RESEARCHER_B.researcher_id, **query, cursor=first.next_cursor)
    assert service.list(RESEARCHER_A.researcher_id, **(query | {"status": "failed"})).items == []
    absent = service.list(RESEARCHER_A.researcher_id, **(query | {"universe": "top1000"}))
    assert absent.total_count == 0


def test_stdio_mcp_discovers_query_schema_and_returns_global_top_ten(ranked_records, tmp_path):
    import os
    import sys
    from pathlib import Path

    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    _, records = ranked_records

    async def exercise():
        with (tmp_path / "mcp-query.stderr.log").open("w+") as errors:
            async with Client(stdio_client(StdioServerParameters(
                command=str(Path(sys.executable).with_name("thesistrace-research-agent-mcp")),
                cwd=Path.cwd(), env={**os.environ,
                    "THESISTRACE_RESEARCH_AGENT_RESEARCHER_ID": str(RESEARCHER_A.researcher_id)},
            ), errlog=errors)) as client:
                inventory = await client.list_tools()
                tool = next(tool for tool in inventory.tools if tool.name == "list_research_runs")
                assert {"search", "metric_filters", "sort_by", "research_period", "status"} <= (
                    set(tool.input_schema["properties"]))
                result = await client.call_tool("list_research_runs", {
                    "research_kind": "strategy_backtest", "status": "succeeded",
                    "sort_by": "sharpe", "sort_direction": "descending", "limit": 10,
                    "metric_filters": [
                        {"metric": "sharpe", "operator": "gte", "value": 1},
                        {"metric": "maximum_drawdown", "operator": "lte", "value": 0.2}],
                })
                assert result.is_error is False
                assert [item["id"] for item in result.structured_content["items"]] == records[:10]
                assert result.structured_content["total_count"] == 10
                invalid = await client.call_tool("list_research_runs", {"sort_by": "sharpe"})
                assert invalid.is_error is True
                assert "research_kind" in invalid.structured_content["issues"][0]["message"]

    anyio.run(exercise)


@pytest.mark.parametrize("direction", ["ascending", "descending"])
def test_metric_cursor_traverses_numeric_values_ties_and_nulls(ranked_records, direction):
    service, records = ranked_records
    found, cursor = [], None
    while True:
        page = service.list(RESEARCHER_A.researcher_id, research_kind="strategy_backtest",
                            sort_by="sharpe", sort_direction=direction, cursor=cursor, limit=7)
        assert page.total_count == 65
        found.extend(item.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    expected = records if direction == "descending" else [*reversed(records[:-1]), records[-1]]
    assert found == expected
    # Drawdown is tied for every record; creation time and ID decide both directions.
    tied = sorted(records, key=lambda rid: (rid in records[:10], rid))
    found, cursor = [], None
    while True:
        page = service.list(RESEARCHER_A.researcher_id, research_kind="strategy_backtest",
                            sort_by="maximum_drawdown", sort_direction=direction,
                            cursor=cursor, limit=7)
        found.extend(item.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert found == tied


def test_tracking_selection_is_persistent_and_cannot_rotate_free_slots(ownership_database):
    from thesistrace.daily_track.quota import TrackingSelectionError, admit_tracking_action

    ResearcherService(ownership_database).bootstrap(RESEARCHER_A)
    rid = RESEARCHER_A.researcher_id
    with ownership_database.transaction() as tx:
        for i in range(3):
            tx.execute("INSERT INTO research_runs.run_ownership(researcher_id,run_id) "
                       "VALUES (%s,%s)", (rid, f"seed-{i}"))
            tx.execute("INSERT INTO "
                       "daily_tracks.tracks(researcher_id,id,status,seed_run_id,origin) "
                       "VALUES (%s,%s,'active',%s,'{}')", (rid, f"track-{i}", f"seed-{i}"))
    with pytest.raises(TrackingSelectionError) as initial:
        with ownership_database.transaction() as tx:
            admit_tracking_action(tx, rid, "track-0", 1)
    assert initial.value.code == "TRACK_SELECTION_REQUIRED"
    with ownership_database.transaction() as tx:
        admit_tracking_action(tx, rid, "track-0", 1, ["track-0"])
    with pytest.raises(TrackingSelectionError):
        with ownership_database.transaction() as tx:
            admit_tracking_action(tx, rid, "track-1", 1, ["track-1"])
    # Already selected work remains possible; stopping must finish before reuse.
    with ownership_database.transaction() as tx:
        admit_tracking_action(tx, rid, "track-0", 1)
        tx.execute("UPDATE daily_tracks.tracks SET status='stopping' WHERE id='track-0'")
    with pytest.raises(TrackingSelectionError):
        with ownership_database.transaction() as tx:
            admit_tracking_action(tx, rid, "track-1", 1)
    with ownership_database.transaction() as tx:
        tx.execute("UPDATE daily_tracks.tracks SET status='stopped' WHERE id='track-0'")
        admit_tracking_action(tx, rid, "track-1", 1)
    # Upgrade adds capacity; it doesn't allow deselecting a still active slot.
    with ownership_database.transaction() as tx:
        admit_tracking_action(tx, rid, "track-2", 3, ["track-1", "track-2"])
        active = tx.execute(
            "SELECT count(*) n FROM daily_tracks.tracks WHERE status='active'"
        ).fetchone()
        assert active["n"] == 2

"""Compare the frozen baseline and current search in an isolated PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import UUID, uuid4
from zipfile import ZipFile

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from thesistrace._postgres import PostgresDatabase, SchemaDefinition, initialize_schemas
from thesistrace._postgres.schema import _fingerprint
from thesistrace.alpha_language import alpha_language
from thesistrace.data import DatasetAdmissionSnapshot
from thesistrace.data.models import DatasetCoverage
from thesistrace.migrations.research_search_0010 import SOURCE, migrate
from thesistrace.research_run import ResearchRunAdmissionCommand, ResearchRunService
from thesistrace.researcher import ResearcherIdentity, ResearcherService
from thesistrace.researcher.quota import QuotaPolicy

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures"
TERMS = ("", "量", "动量", "动量回测", "TURNOVER", "UniqueNeedleForOneUser", "100%_",
         "\\sample!", "close", "no-such-research")


def seed(database, users, runs_per_user):
    researcher = UUID(int=1)
    ResearcherService(database).bootstrap(ResearcherIdentity(
        researcher_id=researcher, email="search-load@example.com", display_label="search load",
    ))
    sessions = tuple(date(2022, 1, 3) + timedelta(days=i) for i in range(1000)
                     if (date(2022, 1, 3) + timedelta(days=i)).weekday() < 5)
    snapshot = DatasetAdmissionSnapshot(
        family_coverage={"equity.eod_price": DatasetCoverage(start=sessions[0], end=sessions[-1])},
        generation_manifest_sha256="a" * 64, data_through_session=sessions[-1],
        coverage_start=sessions[0], coverage_end=sessions[-1], research_sessions=sessions,
        available_field_ids=frozenset({"price.close.adjusted"}),
        maximum_universe_cardinality=lambda *_: 300,
        universe_member_union_cardinalities=lambda _u, windows: tuple(300 for _ in windows),
        financial_research_readiness="not_ready",
    )
    service = ResearchRunService(
        database, compile_formula=alpha_language.compile, current_dataset=lambda: snapshot,
        quota_policy=lambda _: QuotaPolicy(timezone="Asia/Shanghai",
                                          daily_model_budget_nanodollars=1_000_000_000,
                                          daily_run_limit=None, active_daily_track_limit=10),
    )
    template = service.admit(researcher, TypeAdapter(ResearchRunAdmissionCommand).validate_python({
        "request_id": "search-load-template", "folder_id": "folder_default", "name": "Template",
        "formula": "close", "hypothesis": None, "start_date": sessions[0],
        "end_date": sessions[-1], "universe": "top300", "neutralization": "none",
        "research_kind": "factor_evaluation",
    }))
    with database.transaction() as tx:
        value = tx.execute("SELECT immutable_input FROM research_runs.runs WHERE id=%s",
                           (template.id,)).fetchone()["immutable_input"]
        tx.execute("DELETE FROM research_runs.admission_requests WHERE run_id=%s", (template.id,))
        tx.execute("DELETE FROM research_runs.runs WHERE id=%s", (template.id,))
        tx.execute("DELETE FROM research_runs.run_ownership WHERE run_id=%s", (template.id,))
        tx.execute("INSERT INTO researchers.researchers(id) "
                   "SELECT lpad(to_hex(u),32,'0')::uuid FROM generate_series(2,%s) u", (users,))
        tx.execute("INSERT INTO research_folders.folders(researcher_id,id,name,is_default) "
                   "SELECT lpad(to_hex(u),32,'0')::uuid,'folder_default','Default',true "
                   "FROM generate_series(2,%s) u", (users,))
        tx.execute(
            "INSERT INTO research_runs.run_ownership(researcher_id,run_id) "
            "SELECT lpad(to_hex(u),32,'0')::uuid,'load-'||u||'-'||r "
            "FROM generate_series(1,%s) u CROSS JOIN generate_series(1,%s) r",
            (users, runs_per_user),
        )
        tx.execute(
            "INSERT INTO research_runs.runs(researcher_id,id,folder_id,name,"
            "requested_start_date,requested_end_date,status,immutable_input,created_at) "
            "SELECT lpad(to_hex(u),32,'0')::uuid,'load-'||u||'-'||r,'folder_default', "
            "CASE WHEN r %% 20 = 0 THEN '60日动量回测 ' ELSE 'Research ' END || r, "
            "%s,%s,'cancelled',%s::jsonb || jsonb_build_object('hypothesis', "
            "CASE WHEN u=1 AND r=7 THEN 'UniqueNeedleForOneUser' "
            "WHEN r %% 25 = 0 THEN %s ELSE 'Long horizon' END), "
            "timestamptz '2026-01-01' + r * interval '1 second' "
            "FROM generate_series(1,%s) u CROSS JOIN generate_series(1,%s) r",
            (sessions[0], sessions[-1], Jsonb(value), "Keep Turnover Low 100%_ path\\sample!",
             users, runs_per_user),
        )
    # Use realistic planner statistics and a settled visibility map on both versions.
    with database.transaction() as tx:
        tx.execute("ANALYZE research_runs.runs")
        return tx.execute(
            "SELECT count(*) AS rows, avg(pg_column_size(immutable_input))::int AS input_bytes "
            "FROM research_runs.runs"
        ).fetchone()


class RecordedDatabase:
    """Capture the actual public list call, without maintaining a second optimized query."""

    def __init__(self, database):
        self.database = database
        self.query = None

    @contextmanager
    def transaction(self):
        with self.database.transaction() as tx:
            recorder = self

            class Transaction:
                def execute(self, statement, parameters, **options):
                    recorder.query = statement, parameters, options
                    return tx.execute(statement, parameters, **options)

            yield Transaction()


def execute(database, query):
    with database.transaction() as tx:
        rows = tx.execute(query[0], query[1], **query[2]).fetchall()
    return {"total": rows[0]["total_count"],
            "ids": [row["id"] for row in rows if row["id"] is not None]}


def percentiles(samples):
    return {"median_ms": round(median(samples), 3),
            "p95_ms": round(sorted(samples)[math.ceil(len(samples) * .95) - 1], 3)}


def measure(database, queries):
    report = {}
    for term, query in queries.items():
        expected = execute(database, query)
        samples = []
        for _ in range(20):
            start = perf_counter()
            assert execute(database, query) == expected
            samples.append((perf_counter() - start) * 1000)
        with database.transaction() as tx:
            plan = tx.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query[0],
                              query[1], **query[2]).fetchone()["QUERY PLAN"][0]
        report[term] = {**percentiles(samples), **expected, "plan": plan}
        print(json.dumps({"search": term, **percentiles(samples)}, ensure_ascii=False), flush=True)
    return report


def concurrent(database, queries, users, requests=160):
    def request(i):
        # 16 simultaneous callers share the product's default four DB connections.
        user = UUID(int=i % users + 1)
        statement, parameters, options = queries[TERMS[1 + i % (len(TERMS) - 1)]]
        start = perf_counter()
        result = execute(database, (statement, (user, *parameters[1:]), options))
        assert all(run_id.startswith(f"load-{user.int}-") for run_id in result["ids"])
        return (perf_counter() - start) * 1000
    start = perf_counter()
    with ThreadPoolExecutor(max_workers=16) as executor:
        samples = list(executor.map(request, range(requests)))
    return {**percentiles(samples), "requests": requests, "callers": 16,
            "pool_size": 4, "requests_per_second": round(requests / (perf_counter() - start), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--runs-per-user", type=int, default=1000)
    args = parser.parse_args()
    if os.environ.get("THESISTRACE_ENVIRONMENT") != "test":
        parser.error("Use the isolated performance runner")
    if args.users < 2 or args.runs_per_user < 100:
        parser.error("Use at least two users and 100 runs per user")
    params = conninfo_to_dict(os.environ["THESISTRACE_DATABASE_URL"])
    name = "search_performance_" + uuid4().hex
    admin = psycopg.connect(make_conninfo(**params), autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params["dbname"] = name
    database = PostgresDatabase(make_conninfo(**params))
    database.open()
    report = {"users": args.users, "runs_per_user": args.runs_per_user,
              "timing_scope": "local SQL execution, transfer and pool wait; warmed cache"}
    try:
        archive = FIXTURES / "historical-core-schema/execution-timing-target.zip"
        with ZipFile(archive) as zipfile:
            definitions = tuple(SchemaDefinition(n[:-4], zipfile.read(n).decode())
                                for n in zipfile.namelist())
        assert _fingerprint(definitions) == SOURCE
        initialize_schemas(database, definitions)
        report["data"] = seed(database, args.users, args.runs_per_user)
        baseline = (FIXTURES / "research-search-baseline.sql").read_text()
        before = {term: (baseline, (UUID(int=1), None, None, None, None,
                                    term, term, term, term, 20, 0), {}) for term in TERMS}
        print("Measuring baseline", flush=True)
        report["baseline"] = measure(database, before)
        report["baseline_concurrent"] = concurrent(database, before, args.users)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        report["migration"] = migrate(database, apply=True)
        recording = RecordedDatabase(database)
        service = ResearchRunService(recording)
        after = {}
        for term in TERMS:
            service.list_page(UUID(int=1), search=term)
            after[term] = recording.query
        print("Measuring indexed search", flush=True)
        report["optimized"] = measure(database, after)
        report["optimized_concurrent"] = concurrent(database, after, args.users)
        for term in TERMS:
            for field in ("ids", "total"):
                assert report["baseline"][term][field] == report["optimized"][term][field]
        with database.transaction() as tx:
            report["search_index_bytes"] = tx.execute(
                "SELECT pg_relation_size('research_runs.research_runs_search_idx') AS bytes"
            ).fetchone()["bytes"]
        report["results_equal"] = True
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(json.dumps({key: report[key] for key in ("data", "baseline_concurrent",
                         "optimized_concurrent", "results_equal")}, ensure_ascii=False), flush=True)
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


if __name__ == "__main__":
    main()

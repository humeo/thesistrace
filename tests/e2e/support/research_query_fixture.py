"""Explicit isolated query projection fixture; not a performance/backtest oracle."""

import hashlib
import json
import os
import sys

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings


def main():
    if not os.environ.get("THESISTRACE_TEST_PROJECT_NAME", "").startswith("thesistrace-test-"):
        raise RuntimeError("Isolated test identity required")
    request = json.load(sys.stdin)
    database = PostgresDatabase(CoreSettings.from_environment().database_url)
    database.open()
    try:
        with database.transaction() as tx:
            template = tx.execute("SELECT * FROM research_runs.runs WHERE id=%s "
                                  "AND researcher_id=%s AND status='succeeded'",
                                  (request["run_id"], request["researcher_id"])).fetchone()
            if template is None:
                raise RuntimeError("Succeeded owned template required")
            # Fixed metrics deliberately test stored summary selection, units,
            # and numeric ordering. Financial efficacy is outside this fixture.
            expected = []
            expected_rows = []
            for index in range(65):
                run_id = "run_" + hashlib.sha256(
                    f"{request['researcher_id']}:query:{index}".encode()).hexdigest()[:20]
                score = 30 - index if index < 64 else None
                tx.execute("INSERT INTO research_runs.run_ownership(researcher_id,run_id) "
                           "VALUES (%s,%s)", (request["researcher_id"], run_id))
                tx.execute("""INSERT INTO research_runs.runs(
                    researcher_id,id,folder_id,name,requested_start_date,requested_end_date,
                    status,immutable_input,created_at,result_manifest_sha256,result_provenance,
                    key_metrics)
                    VALUES (%s,%s,%s,%s,%s,%s,'succeeded',%s,%s,%s,%s,%s)""",
                    (request["researcher_id"], run_id, template["folder_id"],
                     f"固定策略 {index + 1:02d}", template["requested_start_date"],
                     template["requested_end_date"], Jsonb(template["immutable_input"]),
                     "2026-01-01T00:00:00Z" if index < 10 else "2026-02-01T00:00:00Z",
                     template["result_manifest_sha256"], Jsonb(template["result_provenance"]),
                     Jsonb({"research_kind": "strategy_backtest", "sharpe": score,
                            "annualized_excess_return": None if score is None else score / 100,
                            "maximum_drawdown": 0.1})))
                if index < 10:
                    expected.append(run_id)
                    expected_rows.append({"name": f"固定策略 {index + 1:02d}", "sharpe": score,
                        "annualized_excess_return": score / 100, "maximum_drawdown": 0.1,
                        "start_date": template["requested_start_date"].isoformat(),
                        "end_date": template["requested_end_date"].isoformat()})
            # Keep the real template available for selected detail reads, but
            # it must not displace any of the ten fixed ranking candidates.
            tx.execute("UPDATE research_runs.runs SET key_metrics=%s WHERE id=%s",
                       (Jsonb({"research_kind": "strategy_backtest", "sharpe": -100,
                               "annualized_excess_return": -1, "maximum_drawdown": 0.5}),
                        request["run_id"]))
        print(json.dumps({"expected_ids": expected, "expected_rows": expected_rows,
                          "total_count": 66}))
    finally:
        database.close()


if __name__ == "__main__":
    main()

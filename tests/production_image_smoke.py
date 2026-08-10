from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from threading import Event

import boto3

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.publication import Publication, PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_run.result import read_result_bundle

EXPECTED_OVERVIEW = {
    "dataset_coverage": {"start": "2026-08-03", "end": "2026-08-11"},
    "data_through_session": "2026-08-11",
    "last_refresh_at": None,
    "readiness": True,
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"before", "after"}:
        raise SystemExit("usage: production_image_smoke.py {before|after}")
    api_origin = _required_environment("THESISTRACE_TEST_API_ORIGIN").rstrip("/")
    web_origin = _required_environment("THESISTRACE_TEST_WEB_ORIGIN").rstrip("/")
    state_path = Path(_required_environment("THESISTRACE_TEST_SMOKE_STATE"))
    settings = CoreSettings.from_environment()
    assert "THESISTRACE_TUSHARE_TOKEN" not in os.environ
    _assert_web_image(web_origin)
    if sys.argv[1] == "before":
        result = _before_restart(
            api_origin,
            settings,
            mounted_data_sha256=_directory_sha256(settings.data_mount),
        )
        state_path.write_text(json.dumps(result, sort_keys=True))
    else:
        expected = json.loads(state_path.read_text())
        result = _after_restart(api_origin, settings, expected)
    print(json.dumps(result, sort_keys=True))


def _before_restart(
    api_origin: str,
    settings: CoreSettings,
    *,
    mounted_data_sha256: str,
) -> dict[str, object]:
    assert _request_json(api_origin, "GET", "/api/data") == EXPECTED_OVERVIEW
    accepted = _request_json(
        api_origin,
        "POST",
        "/api/definitions/run",
        {
            "request_id": "production-image-smoke-run",
            "name": "Production Image Smoke Alpha",
            "hypothesis": "Prepared mounted data remains executable offline.",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "alpha": {
                "operator_id": "negate",
                "operands": [{"field_id": "price.close.adjusted"}],
            },
            "universe": "top300",
            "neutralization": "none",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
        },
    )
    assert accepted["outcome"] == "accepted"
    run_id = str(accepted["run"]["id"])
    detail = _wait_for_run(api_origin, run_id)
    durable = _durable_result(settings, run_id)
    return {
        "run_id": run_id,
        "public_result_sha256": hashlib.sha256(canonical_json_bytes(detail)).hexdigest(),
        "result_manifest_sha256": durable["manifest_sha256"],
        "attempt_count": durable["attempt_count"],
        "execution_snapshot": durable["execution_snapshot"],
        "overview": EXPECTED_OVERVIEW,
        "mounted_data_sha256": mounted_data_sha256,
    }


def _after_restart(
    api_origin: str,
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    overview = _request_json(api_origin, "GET", "/api/data")
    assert overview == expected["overview"] == EXPECTED_OVERVIEW
    run_id = str(expected["run_id"])
    detail = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
    assert detail["status"] == "succeeded"
    assert hashlib.sha256(canonical_json_bytes(detail)).hexdigest() == expected[
        "public_result_sha256"
    ]
    durable = _durable_result(settings, run_id)
    assert durable["manifest_sha256"] == expected["result_manifest_sha256"]
    assert durable["attempt_count"] == expected["attempt_count"] == 1
    assert durable["execution_snapshot"] == expected["execution_snapshot"]
    assert _directory_sha256(settings.data_mount) == expected["mounted_data_sha256"]
    return {
        "run_id": run_id,
        "status": detail["status"],
        "result_manifest_sha256": durable["manifest_sha256"],
        "attempt_count": durable["attempt_count"],
        "readiness": overview["readiness"],
    }


def _wait_for_run(api_origin: str, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 60
    last: dict[str, object] | None = None
    poll_interval = Event()
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
        if last["status"] == "succeeded":
            assert set(last["result"]) == {
                "factor",
                "strategy",
                "terminal_strategy_state",
                "provenance",
            }
            assert len(last["result"]["strategy"]["observations"]) == 3
            return last
        if last["status"] in {"failed", "cancelled"}:
            raise AssertionError(last)
        poll_interval.wait(0.1)
    raise AssertionError({"timeout": True, "last_run": last})


def _durable_result(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.result_manifest_sha256, run.result_provenance,
                       to_jsonb(run.*) AS run_snapshot,
                       coalesce((
                           SELECT jsonb_agg(to_jsonb(attempt.*) ORDER BY attempt.ordinal)
                           FROM research_runs.attempts AS attempt
                           WHERE attempt.run_id = run.id
                       ), '[]'::jsonb) AS attempt_snapshots
                FROM research_runs.runs AS run WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        manifest_sha256 = str(row["result_manifest_sha256"])
        provenance = row["result_provenance"]
        bundle = Publication(database, s3, bucket=settings.s3_bucket).read(
            PublishedRef(
                manifest_sha256=manifest_sha256,
                kind="research.result",
                provenance=provenance,
            )
        )
        assert set(read_result_bundle(bundle)) == {
            "factor_summary",
            "strategy_summary",
            "strategy_daily_observations",
            "terminal_strategy_state",
        }
        return {
            "manifest_sha256": manifest_sha256,
            "attempt_count": len(row["attempt_snapshots"]),
            "execution_snapshot": {
                "run": row["run_snapshot"],
                "attempts": row["attempt_snapshots"],
            },
        }
    finally:
        s3.close()
        database.close()


def _request_json(
    api_origin: str,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{api_origin}{path}",
        data=payload,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status < 300
            value = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise AssertionError(
            {"status": error.code, "method": method, "path": path, "body": error.read().decode()}
        ) from error
    assert isinstance(value, dict)
    return value


def _assert_web_image(web_origin: str) -> None:
    with urllib.request.urlopen(f"{web_origin}/data", timeout=5) as response:
        assert response.status == 200
        body = response.read().decode()
    assert '<div id="root"></div>' in body


def _directory_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()

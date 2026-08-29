from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, internal_api_origin, isolated_core_settings
from fastapi.testclient import TestClient
from test_core_research_batch_admission import _factor_command, _publish_current_data

from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_batch_worker_replicas_claim_distinct_fifo_batches_without_blocking_research(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    workers: list[subprocess.Popen[str]] = []
    try:
        with TestClient(create_app(settings)) as client:
            _publish_current_data(settings)
            admitted = [
                client.post(
                    "/api/research-batches",
                    json={
                        **_factor_command(f"batch-fifo-{index}"),
                        "factors": (
                            [
                                {
                                    "item_key": f"oldest-{ordinal}",
                                    "formula": f"close + {ordinal}",
                                }
                                for ordinal in range(1, 4)
                            ]
                            if index == 0
                            else [{"item_key": f"later-{index}", "formula": "close"}]
                        ),
                    },
                ).json()
                for index in range(3)
            ]
            oldest_time = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
            tied_time = datetime(2026, 8, 24, 0, 1, tzinfo=UTC)
            runtime = client.app.state.core_runtime
            with runtime.database.transaction() as transaction:
                transaction.execute(
                    "UPDATE research_batches.batches SET created_at = %s WHERE id = %s",
                    (oldest_time, admitted[0]["id"]),
                )
                transaction.execute(
                    """
                    UPDATE research_batches.batches
                    SET created_at = %s
                    WHERE id = ANY(%s)
                    """,
                    (tied_time, [admitted[1]["id"], admitted[2]["id"]]),
                )
            expected_order = [
                str(admitted[0]["id"]),
                *sorted((str(admitted[1]["id"]), str(admitted[2]["id"]))),
            ]

            claims: list[dict[str, object]] = []
            by_batch: dict[str, subprocess.Popen[str]] = {}
            for expected_batch_id in expected_order:
                worker = _start_claim_barrier_worker(settings, "batch-research")
                workers.append(worker)
                claim = _wait_for_worker_event(worker, "worker_claim")
                claims.append(claim)
                by_batch[str(claim["resource_id"])] = worker
                assert claim["resource_id"] == expected_batch_id
                assert claim["role"] == "batch-research"
                assert claim["resource_type"] == "ResearchBatch"
                assert claim["owner_kind"] == "research_batch_attempt"
                assert claim["owner_id"] == claim["attempt_id"]
                assert claim["claim_order"]["batch_id"] == expected_batch_id

            assert len({str(claim["attempt_id"]) for claim in claims}) == 3
            assert [
                client.get(f"/api/research-batches/{batch_id}").json()["status"]
                for batch_id in expected_order
            ] == ["running", "running", "running"]

            ordinary_response = client.post(
                "/api/research-runs",
                json={
                    "request_id": "batch-fifo-interactive-research",
                    "folder_id": "folder_default",
                    "name": "Interactive while Batches run",
                    "start_date": "2026-08-03",
                    "end_date": "2026-08-04",
                    "universe": "top300",
                    "neutralization": "none",
                    "research_kind": "factor_evaluation",
                    "formula": "close",
                },
            )
            assert ordinary_response.status_code == 202, ordinary_response.text
            ordinary = ordinary_response.json()
            research_worker = _run_worker_once(settings, "research")
            assert research_worker.returncode == 0, research_worker.stderr
            research_events = _stderr_events(research_worker)
            research_claims = [
                event
                for event in research_events
                if event["event"] == "research_run_claimed"
            ]
            assert [event["run_id"] for event in research_claims] == [ordinary["id"]]
            assert client.get(f"/api/research-runs/{ordinary['id']}").json()["status"] == (
                "succeeded"
            )

            idle_research = _run_worker_once(settings, "research")
            assert idle_research.returncode == 0, idle_research.stderr
            assert not [
                event
                for event in _stderr_events(idle_research)
                if event["event"] == "research_run_claimed"
            ]
            stopped = _stderr_events(idle_research)[-1]
            assert stopped["event"] == "worker_stopped"
            assert stopped["component"] == "research_worker"
            assert stopped["worker_role"] == "research"
            assert stopped["slot"] == 1

            idle_batch = _run_worker_once(settings, "batch-research")
            assert idle_batch.returncode == 0, idle_batch.stderr
            assert not [
                event
                for event in _stderr_events(idle_batch)
                if event["event"] == "worker_claim"
            ]

            later_events = _release_claim_barrier_worker(by_batch[expected_order[1]])
            assert client.get(
                f"/api/research-batches/{expected_order[1]}"
            ).json()["status"] == "succeeded"
            assert client.get(
                f"/api/research-batches/{expected_order[0]}"
            ).json()["status"] == "running"

            _release_claim_barrier_worker(by_batch[expected_order[2]])
            oldest_events = _release_claim_barrier_worker(by_batch[expected_order[0]])
            assert [
                client.get(f"/api/research-batches/{batch_id}").json()["status"]
                for batch_id in expected_order
            ] == ["succeeded", "succeeded", "succeeded"]
            assert [
                int(event["item_ordinal"])
                for event in oldest_events
                if event["event"] == "research_batch_execution_item_chunk_succeeded"
                and event["boundary_session"] == "2026-08-04"
            ] == [1, 2, 3]
            for claim, events in (
                (claims[1], later_events),
                (claims[0], oldest_events),
            ):
                exits = [
                    event
                    for event in events
                    if event["event"] == "research_batch_execution_child_exited"
                ]
                assert len(exits) == 1
                assert exits[0]["role"] == "batch-research"
                assert exits[0]["attempt_id"] == claim["attempt_id"]
                assert exits[0]["resource_id"] == claim["resource_id"]
    finally:
        for worker in workers:
            _terminate_worker(worker)


def _worker_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
        "THESISTRACE_INTERNAL_API_ORIGIN": internal_api_origin(settings),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
            settings.batch_attempt_control_directory
        ),
    }


def _start_claim_barrier_worker(
    settings: CoreSettings,
    role: str,
    barrier_event: str = "worker_claim",
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "tests/acceptance/process_worker_with_claim_barrier.py",
            role,
            barrier_event,
        ],
        cwd=ROOT,
        env=_worker_environment(settings),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_worker_event(
    process: subprocess.Popen[str],
    event_name: str,
) -> dict[str, object]:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = monotonic() + 30
    observed: list[dict[str, object]] = []
    try:
        while monotonic() < deadline:
            ready = selector.select(timeout=max(0.0, deadline - monotonic()))
            if not ready:
                break
            line = process.stdout.readline()
            if not line:
                break
            event = json.loads(line)
            observed.append(event)
            if event.get("event") == event_name:
                return event
    finally:
        selector.close()
    stdout, stderr = _terminate_and_collect(process)
    raise AssertionError(
        f"Worker did not emit {event_name}; returncode={process.returncode}; "
        f"observed={observed!r}; stdout={stdout!r}; stderr={stderr!r}"
    )


def _release_claim_barrier_worker(
    process: subprocess.Popen[str],
) -> list[dict[str, object]]:
    assert process.stdin is not None
    process.stdin.write("release\n")
    process.stdin.flush()
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired as error:
        stdout, stderr = _terminate_and_collect(process)
        raise AssertionError(
            "Worker did not exit after barrier release; "
            f"returncode={process.returncode}; stdout={stdout!r}; stderr={stderr!r}"
        ) from error
    assert process.returncode == 0, (
        f"Worker exited {process.returncode}; stdout={stdout!r}; stderr={stderr!r}"
    )
    return [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]


def _terminate_and_collect(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


def _terminate_worker(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    _terminate_and_collect(process)


def _run_worker_once(
    settings: CoreSettings,
    role: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            role,
            "--once",
        ],
        cwd=ROOT,
        env=_worker_environment(settings),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _stderr_events(
    completed: subprocess.CompletedProcess[str],
) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in completed.stderr.splitlines()
        if line.startswith("{")
    ]

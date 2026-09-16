from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from core_runtime import TEST_PUBLIC_ORIGIN, drop_product_schemas, isolated_core_settings
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    ROOT,
    _release_claim_barrier_worker,
    _wait_for_worker_event,
    _worker_environment,
)
from test_core_research_batch_admission import _publish_current_data

from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.researcher import ResearcherIdentity, ResearcherService
from thesistrace.researcher.quota import QuotaPolicy

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="isolated Core runtime required",
)
IDENTITIES = [
    ResearcherIdentity(
        researcher_id=UUID(int=index),
        email=f"fair-{index}@example.test",
        display_label=f"fair-{index}",
    )
    for index in range(1, 4)
]


class _SessionVerifier:
    identity = IDENTITIES[0]

    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        return self.identity


@pytest.fixture
def fair_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[CoreSettings, TestClient, _SessionVerifier]]:
    monkeypatch.setattr(
        "thesistrace.entrypoints.runtime.quota_policy_lookup",
        lambda _origin: (
            lambda _researcher_id: QuotaPolicy(
                timezone="Asia/Shanghai",
                daily_model_budget_nanodollars=None,
                daily_run_limit=None,
                active_daily_track_limit=None,
            )
        ),
    )
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    verifier = _SessionVerifier()
    with TestClient(
        create_app(settings, auth_verifier=verifier, public_origin=TEST_PUBLIC_ORIGIN)
    ) as client:
        for identity in IDENTITIES:
            ResearcherService(client.app.state.core_runtime.database).bootstrap(identity)
        _publish_current_data(settings)
        yield settings, client, verifier


def _admit(client: TestClient, verifier: _SessionVerifier, owner: int, key: str) -> str:
    verifier.identity = IDENTITIES[owner]
    response = client.post(
        "/api/research-runs",
        headers={"origin": TEST_PUBLIC_ORIGIN},
        json={
            "request_id": key,
            "folder_id": "folder_default",
            "name": key,
            "start_date": "2026-08-03",
            "end_date": "2026-08-04",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "factor_evaluation",
            "formula": "close",
        },
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def _start(
    settings: CoreSettings,
    *,
    synchronized: bool = False,
    role: str = "research",
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "apps/core/tests/acceptance/process_worker_with_claim_barrier.py",
            role,
            "research_run_claimed" if role == "research" else "worker_claim",
            *(["--before-claim"] if synchronized else []),
        ],
        cwd=ROOT,
        env=_worker_environment(settings),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _release_start(worker: subprocess.Popen[str]) -> None:
    assert worker.stdin is not None
    worker.stdin.write("start\n")
    worker.stdin.flush()


def _stop_workers(workers: list[subprocess.Popen[str]]) -> None:
    for worker in workers:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=10)


def test_three_simultaneous_workers_give_each_waiting_researcher_one_slot(fair_runtime) -> None:
    settings, client, verifier = fair_runtime
    queues = [
        [_admit(client, verifier, owner, f"{owner}-{i}") for i in range(3)] for owner in range(3)
    ]
    workers = [_start(settings, synchronized=True) for _ in range(3)]
    try:
        for worker in workers:
            _wait_for_worker_event(worker, "ready_to_claim")
        for worker in workers:
            _release_start(worker)
        claims = [_wait_for_worker_event(worker, "research_run_claimed") for worker in workers]
        assert {claim["run_id"] for claim in claims} == {queue[0] for queue in queues}
        for worker in workers:
            _release_claim_barrier_worker(worker)
        for owner, queue in enumerate(queues):
            verifier.identity = IDENTITIES[owner]
            assert client.get(f"/api/research-runs/{queue[0]}").json()["status"] == "succeeded"
    finally:
        _stop_workers(workers)


def test_single_researcher_fills_three_slots_then_newcomer_gets_next(fair_runtime) -> None:
    settings, client, verifier = fair_runtime
    queue = [_admit(client, verifier, 0, f"a-{i}") for i in range(4)]
    workers = []
    try:
        for expected in queue[:3]:
            worker = _start(settings)
            workers.append(worker)
            assert _wait_for_worker_event(worker, "research_run_claimed")["run_id"] == expected
        newcomer = _admit(client, verifier, 1, "b-first")
        _release_claim_barrier_worker(workers[0])
        next_worker = _start(settings)
        workers.append(next_worker)
        assert _wait_for_worker_event(next_worker, "research_run_claimed")["run_id"] == newcomer
        for worker in workers[1:]:
            _release_claim_barrier_worker(worker)
    finally:
        _stop_workers(workers)


class _WorkerStoppedBeforeStart(BaseException):
    pass


def _claim_without_starting(client: TestClient) -> str:
    claimed = []

    def stop(run_id: str, _attempt_id: str) -> None:
        claimed.append(run_id)
        raise _WorkerStoppedBeforeStart

    with pytest.raises(_WorkerStoppedBeforeStart):
        client.app.state.core_runtime.research_runs.process_next(on_claim=stop)
    return claimed[0]


def _history(client: TestClient) -> dict[UUID, int]:
    with client.app.state.core_runtime.database.transaction() as transaction:
        return {
            row["researcher_id"]: row["last_sequence"]
            for row in transaction.execute(
                "SELECT researcher_id, last_sequence FROM researchers.execution_opportunities "
                "WHERE pool = 'research'",
            ).fetchall()
        }


def test_history_survives_result_deletion_and_repeated_initialization(fair_runtime) -> None:
    settings, client, verifier = fair_runtime
    completed = _admit(client, verifier, 0, "a-complete")
    events = []
    assert client.app.state.core_runtime.research_runs.process_next(
        on_execution_event=events.append,
    )
    history = _history(client)
    started = next(event for event in events if event["event"] == "research_attempt_started")
    assert started["pool"] == "research"
    assert started["occupied_slots"] == 0
    assert started["opportunity_sequence"] == history[IDENTITIES[0].researcher_id]
    assert started["queue_wait_seconds"] >= 0
    assert "researcher_id" not in started
    assert initialize_core(settings.database_url) is False
    assert client.get(f"/api/research-runs/{completed}").json()["status"] == "succeeded"
    assert (
        client.delete(
            f"/api/research-runs/{completed}", headers={"origin": TEST_PUBLIC_ORIGIN}
        ).status_code
        == 204
    )
    _admit(client, verifier, 0, "a-after-empty")
    newcomer = _admit(client, verifier, 1, "b-after-a")
    assert initialize_core(settings.database_url) is False
    assert _history(client) == history
    worker = _start(settings)  # a fresh process must still see A's history
    try:
        assert _wait_for_worker_event(worker, "research_run_claimed")["run_id"] == newcomer
        _release_claim_barrier_worker(worker)
    finally:
        _stop_workers([worker])


def test_older_opportunity_precedes_earlier_new_submission(fair_runtime) -> None:
    _, client, verifier = fair_runtime
    for owner in [0, 1]:
        _admit(client, verifier, owner, f"complete-{owner}")
        assert client.app.state.core_runtime.research_runs.process_next()
    _admit(client, verifier, 1, "b-earlier-submission")
    expected = _admit(client, verifier, 0, "a-older-opportunity")
    assert _claim_without_starting(client) == expected


@pytest.mark.parametrize("state", ["running", "cancelling", "expired", "failed"])
def test_effective_occupancy_precedes_history_and_counts_cancellation(fair_runtime, state) -> None:
    _, client, verifier = fair_runtime
    a = _admit(client, verifier, 0, "a-held")
    assert _claim_without_starting(client) == a
    b = _admit(client, verifier, 1, "b-held")
    assert _claim_without_starting(client) == b
    _admit(client, verifier, 0, "a-later")
    with client.app.state.core_runtime.database.transaction() as transaction:
        transaction.execute(
            "UPDATE research_runs.attempts SET lease_expires_at = '2000-01-01' WHERE run_id = %s",
            (b,),
        )
        if state == "expired":
            transaction.execute(
                "UPDATE research_runs.attempts SET lease_expires_at = '2000-01-01' "
                "WHERE run_id = %s",
                (a,),
            )
        if state == "failed":
            transaction.execute(
                "UPDATE research_runs.attempts SET status = 'failed', "
                "failure_reason = 'WorkerLost' WHERE run_id = %s",
                (a,),
            )
    if state == "cancelling":
        verifier.identity = IDENTITIES[0]
        response = client.post(
            f"/api/research-runs/{a}/cancel",
            headers={"origin": TEST_PUBLIC_ORIGIN},
            json={"request_id": "cancel-a"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelling"
    assert _claim_without_starting(client) == (b if state in {"running", "cancelling"} else a)


def test_recovery_retains_user_fifo_but_competes_with_first_time_researcher(fair_runtime) -> None:
    _, client, verifier = fair_runtime
    a = _admit(client, verifier, 0, "a-old")
    _admit(client, verifier, 0, "a-new")
    assert _claim_without_starting(client) == a
    original = _history(client)
    with client.app.state.core_runtime.database.transaction() as transaction:
        transaction.execute(
            "UPDATE research_runs.attempts SET lease_expires_at = '2000-01-01' WHERE run_id = %s",
            (a,),
        )
    b = _admit(client, verifier, 1, "b-first")
    assert _claim_without_starting(client) == b
    assert _claim_without_starting(client) == a
    assert _history(client)[IDENTITIES[0].researcher_id] > original[IDENTITIES[0].researcher_id]


@pytest.mark.parametrize("table", ["research_runs.attempts", "researchers.execution_opportunities"])
def test_authorization_and_history_roll_back_together(fair_runtime, table) -> None:
    from psycopg.errors import RaiseException

    _, client, verifier = fair_runtime
    _admit(client, verifier, 0, "initial-complete")
    assert client.app.state.core_runtime.research_runs.process_next()
    original = _history(client)
    run_id = _admit(client, verifier, 0, "rollback-me")
    database = client.app.state.core_runtime.database
    with database.transaction() as transaction:
        transaction.execute("""
            CREATE FUNCTION researchers.reject_test_claim() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected claim rollback'; END $$
        """)
        transaction.execute(
            f"CREATE TRIGGER reject_test_claim AFTER INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION researchers.reject_test_claim()"
        )
    with pytest.raises(RaiseException, match="injected claim rollback"):
        client.app.state.core_runtime.research_runs.process_next()
    assert _history(client) == original
    assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "queued"
    with database.transaction() as transaction:
        assert (
            transaction.execute(
                "SELECT id FROM research_runs.attempts WHERE run_id = %s", (run_id,)
            ).fetchall()
            == []
        )
        transaction.execute(f"DROP TRIGGER reject_test_claim ON {table}")
    assert _claim_without_starting(client) == run_id
    after = _history(client)
    assert after[IDENTITIES[0].researcher_id] > original[IDENTITIES[0].researcher_id]
    assert client.app.state.core_runtime.research_runs.process_next() is False
    assert _history(client) == after


def test_claim_observes_lease_expiry_after_waiting_for_pool_lock(fair_runtime) -> None:
    from psycopg import connect
    from test_core_current_head_research_run_retry import _wait_for_database_value

    settings, client, verifier = fair_runtime
    a = _admit(client, verifier, 0, "a-old")
    assert _claim_without_starting(client) == a
    b = _admit(client, verifier, 1, "b-old")
    assert _claim_without_starting(client) == b
    workers = []
    try:
        with connect(settings.database_url) as holder:
            holder.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('research_runs.claim_fair', 0))"
            )
            with connect(settings.database_url, autocommit=True) as observer:
                observer.execute(
                    "UPDATE research_runs.attempts SET lease_expires_at = '2000-01-01' "
                    "WHERE run_id = %s",
                    (b,),
                )
                worker = _start(settings)
                workers.append(worker)
                _wait_for_database_value(
                    observer,
                    "SELECT pid FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
                    (holder.info.backend_pid,),
                )
                observer.execute(
                    "UPDATE research_runs.attempts SET lease_expires_at = "
                    "clock_timestamp() + interval '0.1 seconds' WHERE run_id = %s",
                    (a,),
                )
                _wait_for_database_value(
                    observer,
                    "SELECT 1 FROM research_runs.attempts "
                    "WHERE run_id = %s "
                    "AND lease_expires_at < clock_timestamp()",
                    (a,),
                )
            holder.commit()
        assert _wait_for_worker_event(worker, "research_run_claimed")["run_id"] == a
        with client.app.state.core_runtime.database.transaction() as transaction:
            assert transaction.execute(
                "SELECT lease_expires_at > clock_timestamp() AS valid FROM research_runs.attempts "
                "WHERE run_id = %s ORDER BY ordinal DESC LIMIT 1",
                (a,),
            ).fetchone() == {"valid": True}
        _release_claim_barrier_worker(worker)
    finally:
        _stop_workers(workers)


def test_exhausted_candidate_is_cleaned_without_consuming_an_opportunity(fair_runtime) -> None:
    _, client, verifier = fair_runtime
    exhausted = _admit(client, verifier, 0, "a-exhausted")
    database = client.app.state.core_runtime.database
    for _ in range(3):
        assert _claim_without_starting(client) == exhausted
        with database.transaction() as transaction:
            transaction.execute(
                "UPDATE research_runs.attempts SET lease_expires_at = '2000-01-01' "
                "WHERE run_id = %s",
                (exhausted,),
            )
    before = _history(client)[IDENTITIES[0].researcher_id]
    next_run = _admit(client, verifier, 0, "a-next")
    assert _claim_without_starting(client) == next_run
    assert client.get(f"/api/research-runs/{exhausted}").json()["status"] == "failed"
    assert _history(client)[IDENTITIES[0].researcher_id] == before + 1


def test_exhausted_checkpoint_cleanup_does_not_deadlock_another_result(fair_runtime) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from psycopg import connect
    from test_core_current_head_research_run_execution import _run_worker_once
    from test_core_current_head_research_run_retry import _wait_for_database_value

    from thesistrace.data import DatasetLifecycle, MountedGenerationStore
    from thesistrace.research_run.execution import SupervisedResearchExecutor
    from thesistrace.research_run.service import ResearchRunService

    settings, client, verifier = fair_runtime
    runtime = client.app.state.core_runtime
    exhausted = _admit(client, verifier, 0, "checkpoint-to-clean")

    def stop_after_checkpoint(stage: str, _run_id: str) -> None:
        if stage == "checkpoint":
            raise _WorkerStoppedBeforeStart

    processor = ResearchRunService(
        runtime.database,
        dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
        generation_store=MountedGenerationStore(settings.data_mount),
        publication=runtime.publication,
        execution=SupervisedResearchExecutor(settings.data_mount),
        progress=stop_after_checkpoint,
    )
    with pytest.raises(_WorkerStoppedBeforeStart):
        processor.process_next()
    with runtime.database.transaction() as transaction:
        assert (
            transaction.execute(
                "SELECT count(*) AS n FROM research_runs.execution_checkpoints WHERE run_id = %s",
                (exhausted,),
            ).fetchone()["n"]
            > 0
        )
    for _ in range(2):
        with runtime.database.transaction() as transaction:
            transaction.execute(
                "UPDATE research_runs.attempts SET lease_expires_at = '2000-01-01' "
                "WHERE run_id = %s",
                (exhausted,),
            )
        assert _claim_without_starting(client) == exhausted
    completing = _admit(client, verifier, 1, "other-result")
    with connect(settings.database_url, autocommit=True) as barrier:
        barrier.execute("SELECT pg_advisory_lock(24702)")
        barrier.execute("""
            CREATE FUNCTION researchers.block_test_completion() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.status = 'succeeded' THEN PERFORM pg_advisory_xact_lock(24702); END IF;
                RETURN NEW;
            END $$;
            CREATE TRIGGER block_test_completion AFTER UPDATE ON research_runs.attempts
            FOR EACH ROW EXECUTE FUNCTION researchers.block_test_completion()
        """)
        with ThreadPoolExecutor(max_workers=2) as executor:
            publisher = executor.submit(_run_worker_once, settings, "research")
            try:
                publishing_pid = _wait_for_database_value(
                    barrier,
                    "SELECT pid FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
                    (barrier.info.backend_pid,),
                )
                barrier.execute(
                    "UPDATE research_runs.attempts "
                    "SET lease_expires_at = '2000-01-01' WHERE run_id = %s",
                    (exhausted,),
                )
                cleanup = executor.submit(runtime.research_runs.process_next)
                _wait_for_database_value(
                    barrier,
                    "SELECT pid FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
                    (publishing_pid,),
                )
            finally:
                barrier.execute("SELECT pg_advisory_unlock(24702)")
            assert cleanup.result(timeout=20) is False
            result = publisher.result(timeout=20)
            assert result.returncode == 0, result.stderr
        assert client.get(f"/api/research-runs/{completing}").json()["status"] == "succeeded"
        verifier.identity = IDENTITIES[0]
        assert client.get(f"/api/research-runs/{exhausted}").json()["status"] == "failed"


def test_equal_admission_times_use_stable_ids_within_each_researcher(fair_runtime) -> None:
    _, client, verifier = fair_runtime
    queues = [
        [_admit(client, verifier, owner, f"tie-{owner}-{index}") for index in range(2)]
        for owner in range(2)
    ]
    with client.app.state.core_runtime.database.transaction() as transaction:
        transaction.execute("UPDATE research_runs.runs SET created_at = '2026-08-01 00:00:00+00'")
    first = min(queues[0] + queues[1])
    assert _claim_without_starting(client) == first
    other_queue = queues[1] if first in queues[0] else queues[0]
    assert _claim_without_starting(client) == min(other_queue)


def test_batch_children_consume_no_ordinary_opportunity_or_slot(fair_runtime) -> None:
    from test_core_research_batch_admission import _factor_command

    settings, client, verifier = fair_runtime
    response = client.post(
        "/api/research-batches",
        headers={"origin": TEST_PUBLIC_ORIGIN},
        json=_factor_command("batch-not-ordinary"),
    )
    assert response.status_code == 202, response.text
    assert client.app.state.core_runtime.research_runs.process_next() is False
    assert _history(client) == {}
    worker = _start(settings, role="batch-research")
    try:
        _wait_for_worker_event(worker, "worker_claim")
        expected = _admit(client, verifier, 0, "a-with-batch")
        _admit(client, verifier, 1, "b-without-batch")
        assert _claim_without_starting(client) == expected
        assert set(_history(client)) == {IDENTITIES[0].researcher_id}
        _release_claim_barrier_worker(worker)
    finally:
        _stop_workers([worker])

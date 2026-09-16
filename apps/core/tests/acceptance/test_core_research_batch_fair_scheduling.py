from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _release_claim_barrier_worker,
    _wait_for_worker_event,
)
from test_core_research_batch_admission import _factor_command
from test_core_research_fair_scheduling import (
    IDENTITIES,
    TEST_PUBLIC_ORIGIN,
    _release_start,
    _SessionVerifier,
    _start,
    _stop_workers,
)
from test_core_research_fair_scheduling import (
    fair_runtime as _fair_runtime,
)
from test_core_research_fair_scheduling import (
    pytestmark as pytestmark,
)

fair_runtime = _fair_runtime


def _admit_batch(client: TestClient, verifier: _SessionVerifier, owner: int, key: str) -> str:
    verifier.identity = IDENTITIES[owner]
    response = client.post(
        "/api/research-batches", headers={"origin": TEST_PUBLIC_ORIGIN}, json=_factor_command(key)
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def _batch_history(client: TestClient) -> dict[UUID, int]:
    with client.app.state.core_runtime.database.transaction() as transaction:
        return {
            row["researcher_id"]: row["last_sequence"]
            for row in transaction.execute(
                "SELECT researcher_id, last_sequence FROM researchers.execution_opportunities "
                "WHERE pool = 'batch-research'",
            ).fetchall()
        }


def test_two_simultaneous_batch_workers_give_each_researcher_one_slot(fair_runtime) -> None:
    settings, client, verifier = fair_runtime
    queues = [
        [_admit_batch(client, verifier, owner, f"{owner}-{i}") for i in range(2)]
        for owner in range(2)
    ]
    workers = [_start(settings, role="batch-research", synchronized=True) for _ in range(2)]
    try:
        for worker in workers:
            _wait_for_worker_event(worker, "ready_to_claim")
        for worker in workers:
            _release_start(worker)
        claims = [_wait_for_worker_event(worker, "worker_claim") for worker in workers]
        assert {claim["resource_id"] for claim in claims} == {queue[0] for queue in queues}
        for worker in workers:
            _release_claim_barrier_worker(worker)
        for owner, queue in enumerate(queues):
            verifier.identity = IDENTITIES[owner]
            assert client.get(f"/api/research-batches/{queue[0]}").json()["status"] == "succeeded"
    finally:
        _stop_workers(workers)


def test_one_researcher_fills_batch_pool_then_newcomer_gets_next(fair_runtime) -> None:
    settings, client, verifier = fair_runtime
    queue = [_admit_batch(client, verifier, 0, f"a-{i}") for i in range(3)]
    workers = []
    try:
        for expected in queue[:2]:
            worker = _start(settings, role="batch-research")
            workers.append(worker)
            assert _wait_for_worker_event(worker, "worker_claim")["resource_id"] == expected
        newcomer = _admit_batch(client, verifier, 1, "b-first")
        _release_claim_barrier_worker(workers[0])
        worker = _start(settings, role="batch-research")
        workers.append(worker)
        assert _wait_for_worker_event(worker, "worker_claim")["resource_id"] == newcomer
        for worker in workers[1:]:
            _release_claim_barrier_worker(worker)
    finally:
        _stop_workers(workers)


def _processor(settings, client, execution, *, heartbeat_seconds=60):
    from thesistrace.data import DatasetLifecycle
    from thesistrace.research_batch import ResearchBatchService

    runtime = client.app.state.core_runtime
    return ResearchBatchService(
        runtime.database,
        research_runs=runtime.research_runs,
        dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
        publication=runtime.publication,
        attempt_control_directory=settings.batch_attempt_control_directory,
        execution=execution,
        heartbeat_seconds=heartbeat_seconds,
    )


class _StoppedBeforeStart(BaseException):
    pass


class _StopBeforeStartExecutor:
    def execute(self, request, *, emit, cancel_requested):
        self.batch_id = request.batch_id
        raise _StoppedBeforeStart


def _claim_starting(settings, client) -> str:
    execution = _StopBeforeStartExecutor()
    with pytest.raises(_StoppedBeforeStart):
        _processor(settings, client, execution).process_next()
    return execution.batch_id


def test_batch_starting_history_is_atomic_and_recovery_keeps_fifo(fair_runtime) -> None:
    settings, client, verifier = fair_runtime
    a = _admit_batch(client, verifier, 0, "a-old")
    _admit_batch(client, verifier, 0, "a-new")
    assert _claim_starting(settings, client) == a
    original = _batch_history(client)
    with client.app.state.core_runtime.database.transaction() as transaction:
        transaction.execute(
            "UPDATE research_batches.starting_claims "
            "SET lease_expires_at = '2000-01-01' WHERE batch_id = %s",
            (a,),
        )
    b = _admit_batch(client, verifier, 1, "b-first")
    assert _claim_starting(settings, client) == b
    assert _claim_starting(settings, client) == a
    assert (
        _batch_history(client)[IDENTITIES[0].researcher_id] > original[IDENTITIES[0].researcher_id]
    )


@pytest.mark.parametrize(
    "table", ["research_batches.starting_claims", "researchers.execution_opportunities"]
)
def test_batch_claim_and_history_roll_back_together(fair_runtime, table) -> None:
    from psycopg.errors import RaiseException

    settings, client, verifier = fair_runtime
    batch = _admit_batch(client, verifier, 0, "atomic")
    database = client.app.state.core_runtime.database
    with database.transaction() as transaction:
        transaction.execute("""
            CREATE FUNCTION researchers.reject_batch_claim() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected batch rollback'; END $$
        """)
        transaction.execute(
            f"CREATE TRIGGER reject_batch_claim AFTER INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION researchers.reject_batch_claim()"
        )
    with pytest.raises(RaiseException, match="injected batch rollback"):
        client.app.state.core_runtime.research_batches.process_next()
    assert _batch_history(client) == {}
    with database.transaction() as transaction:
        assert (
            transaction.execute("SELECT id FROM research_batches.starting_claims").fetchall() == []
        )
        assert (
            transaction.execute(
                "SELECT id FROM research_runs.runs WHERE status <> %s", ("queued",)
            ).fetchall()
            == []
        )
        transaction.execute(f"DROP TRIGGER reject_batch_claim ON {table}")
    assert _claim_starting(settings, client) == batch


class _ExecutionBarrier:
    def __init__(self, delegate, before_start):
        from threading import Event

        self.delegate = delegate
        self.before_start = before_start
        self.prepared = Event()
        self.release = Event()

    def execute(self, request, *, emit, cancel_requested):
        execution = None
        if not self.before_start:
            execution = self.delegate.execute(request, emit=emit, cancel_requested=cancel_requested)
        self.prepared.set()
        if not self.release.wait(timeout=30):
            if execution is not None:
                execution.close()
            raise TimeoutError("Batch test barrier timed out")
        return execution or self.delegate.execute(
            request, emit=emit, cancel_requested=cancel_requested
        )


@pytest.mark.parametrize("before_start", [True, False], ids=["starting", "running"])
def test_unrecoverable_expired_batch_does_not_block_other_work(fair_runtime, before_start) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from thesistrace.research_batch.execution import SupervisedResearchBatchExecutor

    settings, client, verifier = fair_runtime
    a = _admit_batch(client, verifier, 0, "a-held")
    execution = _ExecutionBarrier(
        SupervisedResearchBatchExecutor(
            settings.data_mount,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution_memory_bytes=client.app.state.core_runtime.research_runs.execution_memory_bytes,
        ),
        before_start,
    )
    service = _processor(settings, client, execution)
    with ThreadPoolExecutor(max_workers=1) as executor:
        old = executor.submit(service.process_next)
        try:
            assert execution.prepared.wait(timeout=10)
            _admit_batch(client, verifier, 1, "b-complete")
            assert client.app.state.core_runtime.research_batches.process_next()
            b = _admit_batch(client, verifier, 1, "b-after-a")
            original = _batch_history(client)
            table = "starting_claims" if before_start else "attempts"
            with client.app.state.core_runtime.database.transaction() as transaction:
                transaction.execute(
                    f"UPDATE research_batches.{table} "
                    "SET lease_expires_at = '2000-01-01' WHERE batch_id = %s",
                    (a,),
                )
            worker = _start(settings, role="batch-research")
            try:
                assert _wait_for_worker_event(worker, "worker_claim")["resource_id"] == b
                assert (
                    _batch_history(client)[IDENTITIES[0].researcher_id]
                    == (original[IDENTITIES[0].researcher_id])
                )
                _release_claim_barrier_worker(worker)
            finally:
                _stop_workers([worker])
        finally:
            execution.release.set()
        assert old.result(timeout=20)
    assert client.app.state.core_runtime.research_batches.process_next()
    verifier.identity = IDENTITIES[0]
    assert client.get(f"/api/research-batches/{a}").json()["status"] == "succeeded"
    assert (
        _batch_history(client)[IDENTITIES[0].researcher_id] > original[IDENTITIES[0].researcher_id]
    )


def _real_executor(settings, client):
    from thesistrace.research_batch.execution import SupervisedResearchBatchExecutor

    return SupervisedResearchBatchExecutor(
        settings.data_mount,
        attempt_control_directory=settings.batch_attempt_control_directory,
        execution_memory_bytes=client.app.state.core_runtime.research_runs.execution_memory_bytes,
    )


@pytest.mark.parametrize("before_start", [True, False], ids=["starting", "running"])
@pytest.mark.parametrize("cancel", [False, True], ids=["active", "cancelling"])
def test_batch_effective_occupancy_counts_one_through_start_and_cancel(
    fair_runtime,
    before_start,
    cancel,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    settings, client, verifier = fair_runtime
    a = _admit_batch(client, verifier, 0, "a-held")
    execution = _ExecutionBarrier(_real_executor(settings, client), before_start)
    with ThreadPoolExecutor(max_workers=1) as executor:
        old = executor.submit(_processor(settings, client, execution).process_next)
        try:
            assert execution.prepared.wait(timeout=10)
            seed = _admit_batch(client, verifier, 1, "b-complete")
            assert client.app.state.core_runtime.research_batches.process_next()
            assert client.get(f"/api/research-batches/{seed}").json()["status"] == "succeeded"
            _admit_batch(client, verifier, 0, "a-next")
            b = _admit_batch(client, verifier, 1, "b-next")
            if cancel:
                verifier.identity = IDENTITIES[0]
                response = client.post(
                    f"/api/research-batches/{a}/cancel",
                    headers={"origin": TEST_PUBLIC_ORIGIN},
                    json={"request_id": "cancel-a"},
                )
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "cancelling"
            assert _claim_starting(settings, client) == b
        finally:
            execution.release.set()
        assert old.result(timeout=20)


def test_batch_history_survives_deletion_and_is_independent_of_ordinary_work(fair_runtime) -> None:
    from test_core_research_fair_scheduling import _admit, _claim_without_starting, _history

    from thesistrace.entrypoints.schema import initialize_core

    settings, client, verifier = fair_runtime
    _admit(client, verifier, 0, "ordinary-a")
    _claim_without_starting(client)
    ordinary_history = _history(client)
    completed = []
    for owner in [0, 1]:
        batch = _admit_batch(client, verifier, owner, f"complete-{owner}")
        completed.append(batch)
        assert client.app.state.core_runtime.research_batches.process_next()
        assert client.get(f"/api/research-batches/{batch}").json()["status"] == "succeeded"
    history = _batch_history(client)
    assert history[IDENTITIES[0].researcher_id] < history[IDENTITIES[1].researcher_id]
    with client.app.state.core_runtime.database.transaction() as transaction:
        # Batch has no public deletion endpoint; verify independent FK lifetime.
        transaction.execute(
            "DELETE FROM research_batches.admission_receipts WHERE batch_id = ANY(%s)",
            (completed,),
        )
        transaction.execute("DELETE FROM research_batches.batches WHERE id = ANY(%s)", (completed,))
    assert initialize_core(settings.database_url) is False
    assert _batch_history(client) == history
    _admit_batch(client, verifier, 1, "b-earlier")
    a = _admit_batch(client, verifier, 0, "a-later-but-older-history")
    c = _admit_batch(client, verifier, 2, "c-first-opportunity")
    assert _claim_starting(settings, client) == c
    assert _claim_starting(settings, client) == a
    assert _history(client) == ordinary_history


def test_ordinary_occupancy_and_history_do_not_change_batch_selection(fair_runtime) -> None:
    from test_core_research_fair_scheduling import _admit, _claim_without_starting, _history

    settings, client, verifier = fair_runtime
    _admit(client, verifier, 0, "ordinary-a-held")
    _claim_without_starting(client)
    original = _history(client)
    a = _admit_batch(client, verifier, 0, "batch-a-first")
    _admit_batch(client, verifier, 1, "batch-b-later")
    assert _claim_starting(settings, client) == a
    assert _history(client) == original
    assert set(_batch_history(client)) == {IDENTITIES[0].researcher_id}


@pytest.mark.parametrize("before_start", [True, False], ids=["starting", "running"])
def test_batch_heartbeat_cannot_revive_lease_after_data_lock_wait(
    fair_runtime, before_start
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from psycopg import connect
    from test_core_current_head_research_run_retry import _wait_for_database_value

    from thesistrace.data.lifecycle import lock_data_lifecycle

    settings, client, verifier = fair_runtime
    batch = _admit_batch(client, verifier, 0, "heartbeat-expiry")
    execution = _ExecutionBarrier(_real_executor(settings, client), before_start)
    service = _processor(settings, client, execution, heartbeat_seconds=0.2)
    table = "starting_claims" if before_start else "attempts"
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.process_next)
        try:
            assert execution.prepared.wait(timeout=10)
            with (
                connect(settings.database_url) as authority,
                connect(settings.database_url) as protection,
                connect(settings.database_url, autocommit=True) as observer,
            ):
                authority.execute(
                    f"SELECT id FROM research_batches.{table} WHERE batch_id = %s FOR UPDATE",
                    (batch,),
                )
                lock_data_lifecycle(protection)
                authority.execute(
                    f"UPDATE research_batches.{table} SET lease_expires_at = "
                    "clock_timestamp() + interval '2 seconds' WHERE batch_id = %s",
                    (batch,),
                )
                authority.commit()
                heartbeat_pid = _wait_for_database_value(
                    observer,
                    "SELECT pid FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
                    (protection.info.backend_pid,),
                )
                _wait_for_database_value(
                    observer,
                    f"SELECT 1 FROM research_batches.{table} "
                    "WHERE batch_id = %s AND lease_expires_at < clock_timestamp()",
                    (batch,),
                )
                protection.commit()
                _wait_for_database_value(
                    observer,
                    "SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE pid = %s AND state <> 'idle')",
                    (heartbeat_pid,),
                )
                assert observer.execute(
                    f"SELECT lease_expires_at < clock_timestamp() FROM research_batches.{table} "
                    "WHERE batch_id = %s",
                    (batch,),
                ).fetchone() == (True,)
        finally:
            execution.release.set()
        assert future.result(timeout=20)


def test_starting_activation_rechecks_time_after_an_unchanged_row_lock(fair_runtime) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from psycopg import connect
    from test_core_current_head_research_run_retry import _wait_for_database_value

    settings, client, verifier = fair_runtime
    batch = _admit_batch(client, verifier, 0, "activate-expired")
    execution = _ExecutionBarrier(_real_executor(settings, client), True)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_processor(settings, client, execution).process_next)
        try:
            assert execution.prepared.wait(timeout=10)
            with (
                connect(settings.database_url) as holder,
                connect(settings.database_url, autocommit=True) as observer,
            ):
                observer.execute(
                    "UPDATE research_batches.starting_claims SET lease_expires_at = "
                    "clock_timestamp() + interval '4 seconds' WHERE batch_id = %s",
                    (batch,),
                )
                holder.execute(
                    "SELECT id FROM research_batches.starting_claims "
                    "WHERE batch_id = %s FOR UPDATE",
                    (batch,),
                )
                execution.release.set()
                _wait_for_database_value(
                    observer,
                    "SELECT pid FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
                    (holder.info.backend_pid,),
                )
                _wait_for_database_value(
                    observer,
                    "SELECT 1 FROM research_batches.starting_claims "
                    "WHERE batch_id = %s "
                    "AND lease_expires_at < clock_timestamp()",
                    (batch,),
                )
                holder.commit()
        finally:
            execution.release.set()
        assert future.result(timeout=20)
    with client.app.state.core_runtime.database.transaction() as transaction:
        assert (
            transaction.execute(
                "SELECT id FROM research_batches.attempts WHERE batch_id = %s", (batch,)
            ).fetchall()
            == []
        )
    assert client.get(f"/api/research-batches/{batch}").json()["status"] == "queued"

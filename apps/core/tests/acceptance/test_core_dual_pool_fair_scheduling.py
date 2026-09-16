from __future__ import annotations

from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _release_claim_barrier_worker,
    _wait_for_worker_event,
)
from test_core_research_batch_fair_scheduling import _admit_batch, _batch_history
from test_core_research_fair_scheduling import (
    IDENTITIES,
    TEST_PUBLIC_ORIGIN,
    _admit,
    _history,
    _release_start,
    _start,
    _stop_workers,
)
from test_core_research_fair_scheduling import fair_runtime as _fair_runtime
from test_core_research_fair_scheduling import pytestmark as pytestmark

from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.schema import initialize_core

fair_runtime = _fair_runtime


def _stored_contract(client):
    with client.app.state.core_runtime.database.transaction() as transaction:
        return {
            "runs": transaction.execute(
                "SELECT id, researcher_id, created_at, immutable_input, status, "
                "execution_owner, result_manifest_sha256, result_provenance "
                "FROM research_runs.runs ORDER BY id"
            ).fetchall(),
            "batches": transaction.execute(
                "SELECT id, researcher_id, created_at, scope, status "
                "FROM research_batches.batches ORDER BY id"
            ).fetchall(),
            "history": transaction.execute(
                "SELECT * FROM researchers.execution_opportunities ORDER BY pool, researcher_id"
            ).fetchall(),
        }


def _run_five_workers(settings):
    workers = [
        _start(settings, synchronized=True, role=role)
        for role in ["research"] * 3 + ["batch-research"] * 2
    ]
    try:
        for worker in workers:
            _wait_for_worker_event(worker, "ready_to_claim")
        for worker in workers:
            _release_start(worker)
        ordinary = [
            _wait_for_worker_event(worker, "research_run_claimed")["run_id"]
            for worker in workers[:3]
        ]
        batches = [
            _wait_for_worker_event(worker, "worker_claim")["resource_id"]
            for worker in workers[3:]
        ]
        # All five grants coexist before any worker is allowed to finish.
        for worker in workers:
            _release_claim_barrier_worker(worker)
        return ordinary, batches
    finally:
        _stop_workers(workers)


def test_three_plus_two_workers_preserve_results_and_fair_history_across_reinitialization(
    fair_runtime,
) -> None:
    settings, client, verifier = fair_runtime
    ordinary = [
        [_admit(client, verifier, owner, f"dual-run-{owner}-{i}") for i in range(3)]
        for owner in range(2)
    ]
    batches = [
        [_admit_batch(client, verifier, owner, f"dual-batch-{owner}-{i}") for i in range(2)]
        for owner in range(2)
    ]
    claimed_runs, claimed_batches = _run_five_workers(settings)
    assert set(claimed_runs) == {ordinary[0][0], ordinary[0][1], ordinary[1][0]}
    assert set(claimed_batches) == {batches[0][0], batches[1][0]}
    original = _stored_contract(client)
    ordinary_history = _history(client)
    batch_history = _batch_history(client)
    assert initialize_core(settings.database_url) is False
    assert _stored_contract(client) == original

    # Open a new API runtime and fresh Worker processes against the retained DB.
    with TestClient(
        create_app(settings, auth_verifier=verifier, public_origin=TEST_PUBLIC_ORIGIN)
    ) as reopened:
        assert _stored_contract(reopened) == original
        next_runs, next_batches = _run_five_workers(settings)
        assert set(next_runs) == {ordinary[0][2], ordinary[1][1], ordinary[1][2]}
        assert set(next_batches) == {batches[0][1], batches[1][1]}
        for identity in IDENTITIES[:2]:
            assert (
                _history(reopened)[identity.researcher_id]
                > ordinary_history[identity.researcher_id]
            )
            assert (
                _batch_history(reopened)[identity.researcher_id]
                > batch_history[identity.researcher_id]
            )
        results = {}
        for owner in range(2):
            verifier.identity = IDENTITIES[owner]
            owned_runs = list(ordinary[owner])
            for batch in batches[owner]:
                response = reopened.get(f"/api/research-batches/{batch}")
                assert response.status_code == 200, response.text
                detail = response.json()
                assert detail["status"] == "succeeded"
                owned_runs.extend(item["research_run_id"] for item in detail["items"])
                verifier.identity = IDENTITIES[1 - owner]
                assert reopened.get(f"/api/research-batches/{batch}").status_code == 404
                verifier.identity = IDENTITIES[owner]
            for run in owned_runs:
                response = reopened.get(f"/api/research-runs/{run}")
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "succeeded"
                results[run] = (owner, response.json())
                assert "last_sequence" not in response.json()
                verifier.identity = IDENTITIES[1 - owner]
                assert reopened.get(f"/api/research-runs/{run}").status_code == 404
                verifier.identity = IDENTITIES[owner]
        completed = _stored_contract(reopened)
        assert all(row["result_manifest_sha256"] for row in completed["runs"])
        assert initialize_core(settings.database_url) is False
        assert _stored_contract(reopened) == completed
        for run, (owner, result) in results.items():
            verifier.identity = IDENTITIES[owner]
            assert reopened.get(f"/api/research-runs/{run}").json() == result

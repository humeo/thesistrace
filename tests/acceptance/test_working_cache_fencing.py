import multiprocessing
from pathlib import Path
from queue import Empty

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingService
from thesistrace.working_cache import WorkingCacheError, WorkingCacheStore


def test_two_workers_fence_a_staged_stale_cache_writer(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
        track = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "fenced-track"},
        ).json()
        client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "fenced-session"},
            json={"new_sessions": 1, "corrections": []},
        )

    advance_id = tracking_service(settings).get_track(track["id"])["advances"][0]["id"]
    context = multiprocessing.get_context("spawn")
    staged = context.Queue()
    results = context.Queue()
    resume = context.Event()
    worker_a = context.Process(
        target=stage_stale_worker,
        args=(
            str(settings.metadata_path),
            str(settings.object_root),
            str(settings.working_cache_root),
            advance_id,
            staged,
            results,
            resume,
        ),
    )
    worker_a.start()
    token_a, attempt_a = staged.get(timeout=60)
    assert token_a == 2

    coordinator = tracking_service(settings)
    assert coordinator.recover_abandoned_attempts(stale_after_seconds=0) == [
        advance_id
    ]
    worker_b = context.Process(
        target=complete_newer_worker,
        args=(
            str(settings.metadata_path),
            str(settings.object_root),
            str(settings.working_cache_root),
            advance_id,
            results,
        ),
    )
    worker_b.start()
    worker_b.join(timeout=90)
    assert worker_b.exitcode == 0
    resume.set()
    worker_a.join(timeout=90)
    assert worker_a.exitcode == 0

    messages = {}
    while True:
        try:
            key, value = results.get_nowait()
        except Empty:
            break
        messages[key] = value
    assert messages["worker_b_status"] == "succeeded"
    assert messages["worker_b_token"] == 3
    assert messages["worker_a_commit"] == "fenced"
    assert messages["worker_a_delete"] == "fenced"
    assert messages["worker_a_recreate"] == "fenced"

    completed = coordinator.get_track(track["id"])
    assert completed is not None
    assert completed["head_checkpoint_id"] != track["head_checkpoint_id"]
    assert completed["fencing_token"] == 3
    completed_advance = coordinator._advance(advance_id)
    assert completed_advance["attempts"][0]["id"] == attempt_a
    assert [attempt["fencing_token"] for attempt in completed_advance["attempts"]] == [
        2,
        3,
    ]
    basis = coordinator.cache.read_basis(track["id"])
    assert basis["fencing_token"] == 3
    assert not (settings.working_cache_root / ".staging").exists()
    assert coordinator.verify_equivalence(track["id"])["status"] == "equivalent"


def stage_stale_worker(
    metadata_path: str,
    object_root: str,
    cache_root: str,
    advance_id: str,
    staged: multiprocessing.Queue,
    results: multiprocessing.Queue,
    resume: multiprocessing.Event,
) -> None:
    settings = process_settings(metadata_path, object_root, cache_root)
    service = tracking_service(settings)
    claimed = service._claim_advance(advance_id)
    assert claimed is not None
    _advance, attempt = claimed
    track_id = service._advance(advance_id)["daily_track_id"]
    basis = service.cache.read_basis(track_id)
    pending = service.cache.read_pending_alpha(track_id)
    rolling = service.cache.read_rolling_factor(track_id)
    retained = sorted(pending)

    def pause_after_staging() -> None:
        staged.put((attempt["fencing_token"], attempt["id"]))
        if not resume.wait(timeout=90):
            raise RuntimeError("newer worker did not complete")

    coordinates = {
        key: basis[key]
        for key in (
            "daily_track_id",
            "generation_id",
            "basis_checkpoint_id",
            "basis_checkpoint_sha256",
            "definition_content_hash",
            "calculation_kernel",
            "numeric_execution_contract",
            "basis_dataset_release_id",
        )
    }
    coordinates["fencing_token"] = attempt["fencing_token"]
    try:
        service.cache.commit_advance(
            coordinates,
            retained_pending_sessions=retained,
            new_pending_alpha={},
            rolling_factor=rolling,
            attempt_id=attempt["id"],
            before_install=pause_after_staging,
        )
        results.put(("worker_a_commit", "unexpected-success"))
    except WorkingCacheError:
        results.put(("worker_a_commit", "fenced"))
    try:
        service.cache.delete_if_not_newer(
            track_id,
            int(attempt["fencing_token"]),
        )
        results.put(("worker_a_delete", "unexpected-success"))
    except WorkingCacheError:
        results.put(("worker_a_delete", "fenced"))
    try:
        service.cache.commit_seed(
            coordinates,
            pending_alpha=pending,
            rolling_factor=rolling,
        )
        results.put(("worker_a_recreate", "unexpected-success"))
    except WorkingCacheError:
        results.put(("worker_a_recreate", "fenced"))


def complete_newer_worker(
    metadata_path: str,
    object_root: str,
    cache_root: str,
    advance_id: str,
    results: multiprocessing.Queue,
) -> None:
    service = tracking_service(
        process_settings(metadata_path, object_root, cache_root)
    )
    advance = service.execute_advance(advance_id)
    results.put(("worker_b_status", advance["status"]))
    results.put(("worker_b_token", advance["attempts"][-1]["fencing_token"]))


def process_settings(
    metadata_path: str,
    object_root: str,
    cache_root: str,
) -> Settings:
    return Settings(
        metadata_path=Path(metadata_path),
        object_root=Path(object_root),
        working_cache_root=Path(cache_root),
    )


def tracking_service(settings: Settings) -> DailyTrackingService:
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    return DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        WorkingCacheStore(settings.working_cache_root),
    )


def create_succeeded_run(client: TestClient, settings: Settings) -> str:
    client.post(
        "/api/v1/dataset-releases/bootstrap",
        headers={"Idempotency-Key": "fencing-seed"},
        json={"fixture": "v1"},
    )
    draft = client.post(
        "/api/v1/research-definitions",
        json=definition(),
    ).json()
    requested = client.post(
        f"/api/v1/research-definitions/{draft['id']}/runs",
        headers={"Idempotency-Key": "fencing-run"},
    ).json()
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    ResearchRunService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
    ).execute(requested["run"]["id"])
    return str(requested["run"]["id"])


def definition() -> dict[str, object]:
    return {
        "title": "Working Cache fencing",
        "hypothesis": "过去 20 日上涨的股票未来收益更高。",
        "dataset_release": "latest",
        "universe": "top300",
        "alpha": {"expression": "pct_change($close_adj, 20)"},
        "neutralization": "industry",
        "strategy": {
            "holdings_count": 30,
            "rebalance_interval": 5,
            "initial_cash_cny": "10000000",
            "execution": "next_open_full_fill",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
        "risk_free_rate": "0",
    }

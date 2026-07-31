from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingService
from thesistrace.working_cache import WorkingCacheError, WorkingCacheStore


def test_stop_fences_track_preserves_head_and_idempotently_deletes_cache(
    tmp_path: Path,
) -> None:
    settings, track = activated_track(tmp_path)
    service = tracking_service(settings)
    original_head = service.current_view(track["id"])
    assert service.cache.list_track_ids() == [track["id"]]

    stopped = service.stop(track["id"])
    assert stopped is not None
    assert stopped["status"] == "stopped"
    assert stopped["fencing_token"] == 2
    assert stopped["head_checkpoint_id"] == track["head_checkpoint_id"]
    assert stopped["cache_deletion"]["status"] == "completed"
    assert service.cache.list_track_ids() == []
    assert service.cache.read_fence(track["id"]) == {
        "daily_track_id": track["id"],
        "fencing_token": 2,
        "stopped": True,
    }
    preserved = service.current_view(track["id"])
    assert preserved["checkpoint"] == original_head["checkpoint"]
    assert preserved["strategy"] == original_head["strategy"]

    repeated = service.stop(track["id"])
    assert repeated is not None
    assert repeated["fencing_token"] == 2
    assert repeated["cache_deletion"]["status"] == "completed"
    assert service.reconcile_cache_deletions() == []


def test_stop_cleanup_failure_is_durable_and_startup_reconciles_it(
    tmp_path: Path,
) -> None:
    settings, track = activated_track(tmp_path)
    service = tracking_service(settings)
    original_delete = service.cache.delete_if_not_newer

    def fail_delete(_track_id: str, _token: int) -> None:
        raise OSError("shared volume unavailable")

    service.cache.delete_if_not_newer = fail_delete  # type: ignore[method-assign]
    stopped = service.stop(track["id"])
    assert stopped is not None
    assert stopped["status"] == "stopped"
    pending = service.get_track(track["id"])["cache_deletion"]
    assert pending["status"] == "pending"
    assert "shared volume unavailable" in pending["last_error"]
    assert service.cache.list_track_ids() == [track["id"]]

    service.cache.delete_if_not_newer = original_delete  # type: ignore[method-assign]
    with TestClient(create_app(settings)):
        pass
    reconciled = tracking_service(settings).get_track(track["id"])
    assert reconciled["cache_deletion"]["status"] == "completed"
    assert reconciled["cache_deletion"]["attempt_count"] == 2
    assert tracking_service(settings).cache.list_track_ids() == []


def test_stale_inflight_worker_cannot_recreate_cache_after_stop(
    tmp_path: Path,
) -> None:
    settings, track = activated_track(tmp_path)
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "stop-inflight-session"},
            json={"new_sessions": 1, "corrections": []},
        )
    service = tracking_service(settings)
    advance_id = service.get_track(track["id"])["advances"][0]["id"]
    claimed = service._claim_advance(advance_id)
    assert claimed is not None
    _advance, stale_attempt = claimed
    old_basis = service.cache.read_basis(track["id"])

    stopped = service.stop(track["id"])
    assert stopped is not None
    assert stopped["fencing_token"] == 3
    assert service._advance(advance_id)["attempts"][-1]["status"] == "cancelled"
    assert service.cache.list_track_ids() == []
    stale_coordinates = {
        key: old_basis[key]
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
    stale_coordinates["fencing_token"] = stale_attempt["fencing_token"]
    try:
        service.cache.commit_seed(
            stale_coordinates,
            pending_alpha={},
            rolling_factor=[],
        )
    except WorkingCacheError:
        pass
    else:
        raise AssertionError("stale worker recreated a stopped Track cache")
    assert service.cache.list_track_ids() == []


def test_reconciliation_deletes_unknown_cache_namespaces_without_creating_state(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    metadata = MetadataStore(settings.metadata_path)
    metadata.initialize()
    orphan = settings.working_cache_root / "tracks" / "orphan-track"
    orphan.mkdir(parents=True)
    (orphan / "partial.bin").write_bytes(b"partial")
    service = tracking_service(settings)

    assert service.reconcile_cache_deletions() == []
    assert service.cache.list_track_ids() == []
    assert service.get_track("orphan-track") is None


def test_reconciliation_preserves_cache_owned_by_an_activation_reservation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    metadata = MetadataStore(settings.metadata_path)
    metadata.initialize()
    track_id = "track-finalizing"
    seed_run_id = "run-finalizing"
    with metadata.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (id, status, created_at)
            VALUES (?, 'succeeded', ?)
            """,
            (seed_run_id, datetime.now(UTC).isoformat()),
        )
        connection.execute(
            """
            INSERT INTO daily_track_activation_reservations
                (track_id, idempotency_key, seed_run_id, created_at)
            VALUES (?, 'finalizing', ?, ?)
            """,
            (
                track_id,
                seed_run_id,
                datetime.now(UTC).isoformat(),
            ),
        )
    cache_root = settings.working_cache_root / "tracks" / track_id
    cache_root.mkdir(parents=True)
    (cache_root / "partial.bin").write_bytes(b"live activation")

    service = tracking_service(settings)
    assert service.reconcile_cache_deletions() == []
    assert service.cache.list_track_ids() == [track_id]


def activated_track(tmp_path: Path) -> tuple[Settings, dict[str, object]]:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
        track = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "stop-track"},
        ).json()
    return settings, track


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
        headers={"Idempotency-Key": "stop-seed"},
        json={"fixture": "v1"},
    )
    draft = client.post(
        "/api/v1/research-definitions",
        json=definition(),
    ).json()
    requested = client.post(
        f"/api/v1/research-definitions/{draft['id']}/runs",
        headers={"Idempotency-Key": "stop-run"},
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
        "title": "Working Cache stop",
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

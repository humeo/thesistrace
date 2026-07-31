from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore, canonical_json_bytes
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingService
from thesistrace.working_cache import (
    MAX_CACHE_BYTES,
    WorkingCacheError,
    WorkingCacheStore,
)


def test_missing_corrupt_mismatched_and_oversized_caches_rebuild_from_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, track = activated_track(tmp_path)
    service = tracking_service(settings)
    cache = service.cache
    original = cache.read_basis(track["id"])
    expected = expected_coordinates(track)

    for key in (
        "daily_track_id",
        "generation_id",
        "basis_checkpoint_id",
        "basis_checkpoint_sha256",
        "definition_content_hash",
        "calculation_kernel",
        "numeric_execution_contract",
        "basis_dataset_release_id",
        "fencing_token",
    ):
        mismatch = dict(expected)
        mismatch[key] = "wrong" if key != "fencing_token" else 99
        with pytest.raises(WorkingCacheError, match="basis mismatch"):
            cache.validate(track["id"], mismatch)

    track_root = settings.working_cache_root / "tracks" / track["id"]
    (track_root / "basis.json").unlink()
    monkeypatch.setattr(
        service,
        "get_track",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache rebuild must not load the complete Track history")
        ),
    )
    monkeypatch.setattr(
        service,
        "_checkpoint_release_sequence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache rebuild must not traverse the Checkpoint chain")
        ),
    )
    rebuilt = service._ensure_working_cache(track, track["generations"][0])
    assert payload_identities(rebuilt) == payload_identities(original)

    payload = track_root / str(rebuilt["pending_alpha"][0]["path"])
    payload.write_bytes(payload.read_bytes() + b"corrupt")
    rebuilt = service._ensure_working_cache(track, track["generations"][0])
    assert payload_identities(rebuilt) == payload_identities(original)

    (track_root / "partial-install.bin").write_bytes(
        b"x" * (MAX_CACHE_BYTES + 1)
    )
    rebuilt = service._ensure_working_cache(track, track["generations"][0])
    assert payload_identities(rebuilt) == payload_identities(original)
    assert cache.namespace_bytes(track["id"]) <= MAX_CACHE_BYTES
    assert not (settings.working_cache_root / ".staging").exists()

    invalid_basis = dict(rebuilt)
    invalid_basis["pending_alpha"] = [
        *invalid_basis["pending_alpha"],
        invalid_basis["pending_alpha"][0],
    ]
    (track_root / "basis.json").write_bytes(canonical_json_bytes(invalid_basis))
    with pytest.raises(WorkingCacheError, match="pending Alpha bound"):
        cache.validate(track["id"], expected)


def test_complete_cache_loss_rebuilds_the_same_next_compact_checkpoint(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
        intact = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "intact-track"},
        ).json()
        recovered = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "recovered-track"},
        ).json()
        client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "recovery-session"},
            json={"new_sessions": 1, "corrections": []},
        )

    service = tracking_service(settings)
    service.cache.delete(recovered["id"])
    intact_advance = service.get_track(intact["id"])["advances"][0]
    recovered_advance = service.get_track(recovered["id"])["advances"][0]
    assert service.execute_advance(intact_advance["id"])["status"] == "succeeded"
    assert service.execute_advance(recovered_advance["id"])["status"] == "succeeded"

    intact_head = service.get_track(intact["id"])["head"]
    recovered_head = service.get_track(recovered["id"])["head"]
    objects = ImmutableObjectStore(settings.object_root)
    intact_manifest = objects.read_json(intact_head["manifest_sha256"])
    recovered_manifest = objects.read_json(recovered_head["manifest_sha256"])
    assert intact_manifest["objects"] == recovered_manifest["objects"]
    assert payload_identities(service.cache.read_basis(intact["id"])) == (
        payload_identities(service.cache.read_basis(recovered["id"]))
    )
    assert service.verify_equivalence(intact["id"])["status"] == "equivalent"
    assert service.verify_equivalence(recovered["id"])["status"] == "equivalent"


def test_bounded_rebuild_failure_blocks_attempt_without_moving_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, track = activated_track(tmp_path)
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "failed-rebuild-session"},
            json={"new_sessions": 1, "corrections": []},
        )
    service = tracking_service(settings)
    service.cache.delete(track["id"])

    def fail_rebuild(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("bounded rebuild failed")

    monkeypatch.setattr(service, "_rebuild_working_cache", fail_rebuild)
    advance = service.execute_next()
    assert advance is not None
    assert advance["status"] == "blocked"
    unchanged = service.get_track(track["id"])
    assert unchanged is not None
    assert unchanged["head_checkpoint_id"] == track["head_checkpoint_id"]
    assert len(unchanged["checkpoints"]) == 1


def expected_coordinates(track: dict[str, object]) -> dict[str, object]:
    return {
        "daily_track_id": track["id"],
        "generation_id": track["current_generation_id"],
        "basis_checkpoint_id": track["head"]["id"],
        "basis_checkpoint_sha256": track["head"]["manifest_sha256"],
        "definition_content_hash": track["definition_content_hash"],
        "calculation_kernel": track["generations"][0]["calculation_kernel"],
        "numeric_execution_contract": track["numeric_execution_contract"],
        "basis_dataset_release_id": track["head"]["target_dataset_release_id"],
        "fencing_token": len(track["checkpoints"]),
    }


def payload_identities(basis: dict[str, object]) -> dict[str, object]:
    return {
        "pending": [
            (entry["session"], entry["sha256"], entry["bytes"])
            for entry in basis["pending_alpha"]
        ],
        "rolling": {
            key: basis["rolling_factor"][key]
            for key in ("sha256", "bytes", "rows")
        },
    }


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
            headers={"Idempotency-Key": "rebuild-track"},
        ).json()
    raw_track = tracking_service(settings).get_track(str(track["id"]))
    assert raw_track is not None
    return settings, raw_track


def create_succeeded_run(client: TestClient, settings: Settings) -> str:
    client.post(
        "/api/v1/dataset-releases/bootstrap",
        headers={"Idempotency-Key": "recovery-seed"},
        json={"fixture": "v1"},
    )
    draft = client.post(
        "/api/v1/research-definitions",
        json=definition(),
    ).json()
    requested = client.post(
        f"/api/v1/research-definitions/{draft['id']}/runs",
        headers={"Idempotency-Key": "recovery-run"},
    ).json()
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    datasets = DatasetPublisher(metadata, objects)
    ResearchRunService(metadata, datasets, objects).execute(requested["run"]["id"])
    return str(requested["run"]["id"])


def tracking_service(settings: Settings) -> DailyTrackingService:
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    return DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        WorkingCacheStore(settings.working_cache_root),
    )


def definition() -> dict[str, object]:
    return {
        "title": "Working Cache recovery",
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

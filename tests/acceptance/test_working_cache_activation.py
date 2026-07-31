from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.quota import QuotaExceededError
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingService
from thesistrace.working_cache import (
    MAX_CACHE_BYTES,
    WorkingCacheStore,
)


class RejectingCheckpointStorageStore(MetadataStore):
    def commit_private_storage_references(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int:
        del connection, resource_kind, resource_id, objects
        raise QuotaExceededError(
            dimension="max_private_storage_bytes",
            limit=10,
        )


def test_activation_publishes_compact_checkpoint_and_seeds_bounded_cache(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
        activated = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "activate"},
        )

        assert activated.status_code == 201
        track = activated.json()
        repeated = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "activate"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == track["id"]

    objects = ImmutableObjectStore(settings.object_root)
    metadata = MetadataStore(settings.metadata_path)
    raw_track = DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        WorkingCacheStore(settings.working_cache_root),
    ).get_track(str(track["id"]))
    assert raw_track is not None
    checkpoint = objects.read_json(
        raw_track["head"]["manifest_sha256"]
    )
    assert isinstance(checkpoint, dict)
    assert set(checkpoint["objects"]) == {
        "diagnostic_summary",
        "execution_aggregates",
        "factor_summary",
        "rebalance_aggregates",
        "strategy_daily_observations",
        "strategy_summary",
        "terminal_positions",
        "terminal_strategy_state",
    }
    assert not set(checkpoint["objects"]) & {
        "alpha_matrix",
        "forward_labels",
        "factor_evaluation",
        "strategy_backtest",
    }
    assert "migration_seed_objects" not in checkpoint

    cache = WorkingCacheStore(settings.working_cache_root)
    basis = cache.read_basis(track["id"])
    assert basis["daily_track_id"] == track["id"]
    assert basis["generation_id"] == track["current_generation_id"]
    assert basis["basis_checkpoint_id"] == track["head"]["id"]
    assert basis["basis_checkpoint_sha256"] == raw_track["head"][
        "manifest_sha256"
    ]
    assert basis["definition_content_hash"] == raw_track[
        "definition_content_hash"
    ]
    assert basis["calculation_kernel"] == "kernel-v1"
    assert basis["numeric_execution_contract"] == "thesistrace-numeric-v1"
    assert basis["basis_dataset_release_id"] == track["activation_release_id"]
    assert basis["fencing_token"] == 1
    assert len(basis["pending_alpha"]) == 21
    assert basis["rolling_factor"]["rows"] <= 1_512
    assert cache.namespace_bytes(track["id"]) <= MAX_CACHE_BYTES
    assert all(
        rows == sorted(rows, key=lambda row: row["instrument_id"])
        for rows in cache.read_pending_alpha(track["id"]).values()
    )
    assert len(cache.read_rolling_factor(track["id"])) == 1_512
    assert cache.list_track_ids() == [track["id"]]
    assert settings.object_root not in settings.working_cache_root.parents


def test_top3000_seed_shape_stays_below_the_cache_byte_limit(tmp_path: Path) -> None:
    cache = WorkingCacheStore(tmp_path / "working-cache")
    pending = {
        f"2026-07-{session:02d}": [
            {
                "instrument_id": f"equity:{instrument:06d}.SZ",
                "alpha": (instrument - 1_500) / 1_000,
            }
            for instrument in range(3_000)
        ]
        for session in range(1, 22)
    }
    rolling = [
        {
            "session": f"session-{session:04d}",
            "horizon": horizon,
            "sample_count": 3_000,
            "ic": 0.01,
            "rank_ic": 0.02,
            "q1": -0.01,
            "q2": -0.005,
            "q3": 0.0,
            "q4": 0.005,
            "q5": 0.01,
            "top_bottom_return": 0.02,
            "correlation_reason": None,
            "quantile_reason": None,
        }
        for session in range(504)
        for horizon in (1, 5, 20)
    ]

    basis = cache.commit_seed(
        {
            "daily_track_id": "track_capacity",
            "generation_id": "generation_capacity",
            "basis_checkpoint_id": "checkpoint_capacity",
            "basis_checkpoint_sha256": "1" * 64,
            "definition_content_hash": "2" * 64,
            "calculation_kernel": "kernel-v1",
            "numeric_execution_contract": "thesistrace-numeric-v1",
            "basis_dataset_release_id": "dsr_capacity",
            "fencing_token": 1,
        },
        pending_alpha=pending,
        rolling_factor=rolling,
    )

    assert len(basis["pending_alpha"]) == 21
    assert basis["rolling_factor"]["rows"] == 1_512
    assert cache.namespace_bytes("track_capacity") <= MAX_CACHE_BYTES

    retained_entries = {
        entry["session"]: entry for entry in basis["pending_alpha"][1:]
    }
    retained_inodes = {
        session: (
            tmp_path
            / "working-cache"
            / "tracks"
            / "track_capacity"
            / str(entry["path"])
        ).stat().st_ino
        for session, entry in retained_entries.items()
    }
    next_session_rows = [
        {
            "instrument_id": f"equity:{instrument:06d}.SZ",
            "alpha": (instrument - 1_500) / 1_000,
        }
        for instrument in range(3_000)
    ]
    cache.advance_fence("track_capacity", 2, stopped=False)
    advanced_basis = cache.commit_advance(
        {
            "daily_track_id": "track_capacity",
            "generation_id": "generation_capacity",
            "basis_checkpoint_id": "checkpoint_capacity_next",
            "basis_checkpoint_sha256": "3" * 64,
            "definition_content_hash": "2" * 64,
            "calculation_kernel": "kernel-v1",
            "numeric_execution_contract": "thesistrace-numeric-v1",
            "basis_dataset_release_id": "dsr_capacity_next",
            "fencing_token": 2,
        },
        retained_pending_sessions=sorted(retained_entries),
        new_pending_alpha={"2026-07-22": next_session_rows},
        rolling_factor=rolling,
    )
    advanced_entries = {
        entry["session"]: entry for entry in advanced_basis["pending_alpha"]
    }
    assert len(advanced_entries) == 21
    assert cache.namespace_bytes("track_capacity") <= MAX_CACHE_BYTES
    assert all(
        advanced_entries[session]["sha256"] == retained_entries[session]["sha256"]
        for session in retained_entries
    )
    assert all(
        (
            tmp_path
            / "working-cache"
            / "tracks"
            / "track_capacity"
            / str(advanced_entries[session]["path"])
        ).stat().st_ino
        == retained_inodes[session]
        for session in retained_entries
    )


def test_activation_storage_quota_failure_publishes_no_checkpoint_or_cache(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
    metadata = RejectingCheckpointStorageStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    tracking = DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        WorkingCacheStore(settings.working_cache_root),
    )

    with pytest.raises(QuotaExceededError) as rejected:
        tracking.activate(run_id, "reject-checkpoint-storage")

    assert rejected.value.dimension == "max_private_storage_bytes"
    with metadata.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM daily_tracks"
        ).fetchone()[0] == 0
    assert WorkingCacheStore(settings.working_cache_root).list_track_ids() == []
    assert not list(
        (settings.object_root / "manifests").glob("checkpoint_*.json")
    )
    assert metadata.daily_track_activation_reservation_ids() == []


def test_concurrent_activation_atomically_enforces_ten_active_tracks(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
    metadata = MetadataStore(settings.metadata_path)
    with metadata.connect() as connection:
        for ordinal in range(9):
            connection.execute(
                """
                INSERT INTO daily_tracks (id, status, created_at)
                VALUES (?, 'active', ?)
                """,
                (f"existing_active_{ordinal}", f"2026-07-01T00:00:{ordinal:02d}+00:00"),
            )
        connection.execute(
            """
            INSERT INTO daily_tracks (id, status, created_at, stopped_at)
            VALUES ('existing_stopped', 'stopped',
                    '2026-07-01T00:01:00+00:00',
                    '2026-07-01T00:02:00+00:00')
            """
        )

    def activate(idempotency_key: str) -> tuple[dict[str, object], bool]:
        local_metadata = MetadataStore(settings.metadata_path)
        local_objects = ImmutableObjectStore(settings.object_root)
        local_datasets = DatasetPublisher(local_metadata, local_objects)
        service = DailyTrackingService(
            local_metadata,
            local_datasets,
            local_objects,
            WorkingCacheStore(settings.working_cache_root),
        )
        return service.activate(run_id, idempotency_key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(activate, "concurrent-one"),
            executor.submit(activate, "concurrent-two"),
        ]
    successes: list[dict[str, object]] = []
    errors: list[Exception] = []
    for future in futures:
        try:
            successes.append(future.result()[0])
        except Exception as error:
            errors.append(error)

    assert len(successes) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], QuotaExceededError)
    assert errors[0].dimension == "max_active_daily_tracks"
    assert errors[0].limit == 10
    with metadata.connect() as connection:
        active_count = connection.execute(
            "SELECT COUNT(*) FROM daily_tracks WHERE status = 'active'"
        ).fetchone()[0]
    assert active_count == 10
    assert WorkingCacheStore(settings.working_cache_root).list_track_ids() == [
        successes[0]["id"]
    ]


def test_concurrent_same_key_waits_for_and_replays_the_activation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
    calculation_started = Event()
    calculation_can_finish = Event()
    original = DailyTrackingService._commit_activation_cache

    def coordinated_calculation(self, *args, **kwargs):
        calculation_started.set()
        assert calculation_can_finish.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        DailyTrackingService,
        "_commit_activation_cache",
        coordinated_calculation,
    )

    def activate():
        metadata = MetadataStore(settings.metadata_path)
        objects = ImmutableObjectStore(settings.object_root)
        return DailyTrackingService(
            metadata,
            DatasetPublisher(metadata, objects),
            objects,
            WorkingCacheStore(settings.working_cache_root),
        ).activate(run_id, "same-key")

    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(activate)
        assert calculation_started.wait(timeout=10)
        replay = executor.submit(activate)
        with pytest.raises(TimeoutError):
            replay.result(timeout=0.2)
        calculation_can_finish.set()
        owner_result = owner.result(timeout=30)
        replay_result = replay.result(timeout=30)

    assert owner_result[1] is True
    assert replay_result[1] is False
    assert replay_result[0]["id"] == owner_result[0]["id"]
    assert WorkingCacheStore(
        settings.working_cache_root
    ).list_track_ids() == [owner_result[0]["id"]]


def create_succeeded_run(client: TestClient, settings: Settings) -> str:
    client.post(
        "/api/v1/dataset-releases/bootstrap",
        headers={"Idempotency-Key": "cache-seed"},
        json={"fixture": "v1"},
    )
    draft = client.post(
        "/api/v1/research-definitions",
        json=definition(),
    ).json()
    requested = client.post(
        f"/api/v1/research-definitions/{draft['id']}/runs",
        headers={"Idempotency-Key": "cache-run"},
    ).json()
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    datasets = DatasetPublisher(metadata, objects)
    ResearchRunService(metadata, datasets, objects).execute(requested["run"]["id"])
    return str(requested["run"]["id"])


def definition() -> dict[str, object]:
    return {
        "title": "Working Cache seed",
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

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore, canonical_json_bytes
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingError, DailyTrackingService
from thesistrace.working_cache import MAX_CACHE_BYTES, WorkingCacheStore


def test_advance_rotates_bounded_cache_and_publishes_only_compact_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
        track = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "activate-incremental"},
        ).json()
        cache = WorkingCacheStore(settings.working_cache_root)
        seed_basis = cache.read_basis(track["id"])
        seed_pending = {
            entry["session"]: entry["sha256"] for entry in seed_basis["pending_alpha"]
        }
        release = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "one-new-session"},
            json={"new_sessions": 1, "corrections": []},
        ).json()["release"]

    service = tracking_service(settings)
    canonical_entries = {
        str(entry["sha256"]): entry
        for entry in release["objects"]
        if isinstance(entry, dict) and entry.get("kind") == "canonical_partition"
    }
    canonical_reads: list[str] = []
    canonical_read_parquet = service.objects.read_parquet

    def record_canonical_read(digest, contract):
        if str(digest) in canonical_entries:
            canonical_reads.append(str(digest))
        return canonical_read_parquet(digest, contract)

    monkeypatch.setattr(service.objects, "read_parquet", record_canonical_read)
    monkeypatch.setattr(
        service,
        "_compact_tracking_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily Advance must not read full Tracking history")
        ),
    )
    advance = service.execute_next()
    assert advance is not None
    assert advance["status"] == "succeeded"
    assert canonical_reads
    earliest_calendar = min(
        (
            entry
            for entry in canonical_entries.values()
            if entry["family"] == "market.research_calendar"
        ),
        key=lambda entry: str(entry["partition"]["start"]),
    )
    assert str(earliest_calendar["sha256"]) not in canonical_reads
    updated = service.get_track(track["id"])
    assert updated is not None
    assert updated["head"]["target_dataset_release_id"] == release["id"]
    objects = ImmutableObjectStore(settings.object_root)
    manifest = objects.read_json(updated["head"]["manifest_sha256"])
    assert manifest["processed_session_count"] == 1
    assert manifest["processed_session_range"] == {
        "start": release["appended_session_range"]["end"],
        "end": release["appended_session_range"]["end"],
    }
    assert manifest["alpha_calculation"]["maximum_lookback_sessions"] <= 252
    assert manifest["alpha_calculation"]["calculated_sessions"] == 1
    assert set(manifest["objects"]) == {
        "execution_aggregates",
        "factor_summary",
        "rebalance_aggregates",
        "strategy_daily_observations",
        "strategy_summary",
        "terminal_positions",
        "terminal_strategy_state",
    }
    assert not set(manifest["objects"]) & {
        "alpha_matrix",
        "forward_labels",
        "factor_evaluation",
        "label_maturation",
        "strategy_backtest",
    }
    daily_entry = manifest["objects"]["strategy_daily_observations"]
    assert daily_entry["format"] == "partitioned_parquet"
    assert daily_entry["row_count"] == 1
    assert len(daily_entry["parts"]) == 1
    terminal = objects.read_json(
        manifest["objects"]["terminal_strategy_state"]["sha256"]
    )
    assert isinstance(terminal["metric_state"], dict)
    assert isinstance(terminal["last_daily_observation"], dict)
    assert "daily" not in terminal
    assert len(canonical_json_bytes(terminal)) < 10_000

    next_basis = cache.read_basis(track["id"])
    next_pending = {
        entry["session"]: entry["sha256"] for entry in next_basis["pending_alpha"]
    }
    assert len(next_pending) == 21
    retained_sessions = set(seed_pending) & set(next_pending)
    assert len(retained_sessions) == 20
    assert all(next_pending[session] == seed_pending[session] for session in retained_sessions)
    assert next_basis["rolling_factor"]["rows"] == 1_512
    assert next_basis["basis_checkpoint_id"] == updated["head"]["id"]
    assert next_basis["basis_dataset_release_id"] == release["id"]
    assert cache.namespace_bytes(track["id"]) <= MAX_CACHE_BYTES

    materialized_rows: list[int] = []
    read_parquet = service.objects.read_parquet

    def bounded_read(*args, **kwargs):
        table = read_parquet(*args, **kwargs)
        materialized_rows.append(table.num_rows)
        return table

    monkeypatch.setattr(service.objects, "read_parquet", bounded_read)
    view = service.current_view(track["id"])
    assert len(view["strategy"]["daily"]) == 252
    assert materialized_rows
    assert max(materialized_rows) <= 252
    assert view["window"]["maximum_sessions"] == 252
    assert view["window"]["has_earlier"] is True
    assert "daily" not in view["factor_summary"]["horizons"]["1"]
    assert "metric_state" not in view["terminal_strategy_state"]
    assert "last_daily_observation" not in view[
        "terminal_strategy_state"
    ]
    checkpoint_count = len(updated["checkpoints"])
    duplicate = service.execute_advance(advance["id"])
    assert duplicate["checkpoint_id"] == advance["checkpoint_id"]
    assert len(service.get_track(track["id"])["checkpoints"]) == checkpoint_count


def test_cache_commit_failure_does_not_move_tracking_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
        track = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "activate-failure"},
        ).json()
        client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "failure-session"},
            json={"new_sessions": 1, "corrections": []},
        )

    service = tracking_service(settings)
    prior_basis = service.cache.read_basis(track["id"])

    def fail_commit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(service.cache, "commit_advance", fail_commit)
    advance = service.execute_next()
    assert advance is not None
    assert advance["status"] == "blocked"
    unchanged = service.get_track(track["id"])
    assert unchanged is not None
    assert unchanged["head_checkpoint_id"] == track["head_checkpoint_id"]
    assert len(unchanged["checkpoints"]) == 1
    assert service.cache.read_basis(track["id"]) == prior_basis


def test_incomplete_terminal_state_is_rejected_without_history_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        run_id = create_succeeded_run(client, settings)
        track = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "activate-legacy-terminal"},
        ).json()

    service = tracking_service(settings)
    raw_track = service.get_track(str(track["id"]))
    assert raw_track is not None
    head = raw_track["head"]
    manifest = service.objects.read_json(str(head["manifest_sha256"]))
    terminal_entry = manifest["objects"]["terminal_strategy_state"]
    terminal = service.objects.read_json(str(terminal_entry["sha256"]))
    terminal.pop("metric_state")
    terminal.pop("last_daily_observation")
    terminal_object = service.objects.put_json(terminal)
    legacy_manifest = json.loads(json.dumps(manifest))
    legacy_manifest["objects"]["terminal_strategy_state"] = {
        "kind": "terminal_strategy_state",
        "format": "json",
        **terminal_object,
    }
    legacy_manifest_object = service.objects.put_json(legacy_manifest)
    with service.metadata.connect() as connection:
        connection.execute(
            """
            UPDATE tracking_checkpoints
            SET manifest_sha256 = ?
            WHERE id = ?
            """,
            (legacy_manifest_object["sha256"], head["id"]),
        )
    head["manifest_sha256"] = legacy_manifest_object["sha256"]
    monkeypatch.setattr(
        service,
        "get_track",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid continuation must not scan Track history")
        ),
    )
    monkeypatch.setattr(
        service,
        "_compact_tracking_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid continuation must not rebuild full history")
        ),
    )

    with pytest.raises(
        DailyTrackingError,
        match="terminal continuation state is incomplete",
    ):
        service._checkpoint_state_projection(head)


def create_succeeded_run(client: TestClient, settings: Settings) -> str:
    client.post(
        "/api/v1/dataset-releases/bootstrap",
        headers={"Idempotency-Key": "incremental-seed"},
        json={"fixture": "v1"},
    )
    draft = client.post(
        "/api/v1/research-definitions",
        json=definition(),
    ).json()
    requested = client.post(
        f"/api/v1/research-definitions/{draft['id']}/runs",
        headers={"Idempotency-Key": "incremental-run"},
    ).json()
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    datasets = DatasetPublisher(metadata, objects)
    ResearchRunService(metadata, datasets, objects).execute(requested["run"]["id"])
    return str(requested["run"]["id"])


def tracking_service(settings: Settings) -> DailyTrackingService:
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    datasets = DatasetPublisher(metadata, objects)
    return DailyTrackingService(
        metadata,
        datasets,
        objects,
        WorkingCacheStore(settings.working_cache_root),
    )


def definition() -> dict[str, object]:
    return {
        "title": "Incremental Working Cache",
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

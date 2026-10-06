from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_daily_track_detail import (
    _business_sessions,
    _publish_head,
    _refresh_daily_track,
    _run_command,
    _run_worker_once,
)

from thesistrace.benchmark import BenchmarkLevel
from thesistrace.data.benchmark_snapshot import PreparedBenchmarkSnapshots
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)


@pytest.fixture
def comparison_track(tmp_path: Path):
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "canonical-data",
        benchmark_mount=tmp_path / "benchmark-data",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2026, 8, 3), count=5)
    benchmark = PreparedBenchmarkSnapshots(settings.benchmark_mount).prepare(
        (BenchmarkLevel("2010-01-04", "3500"),
         *(BenchmarkLevel(session, "4000") for session in sessions)),
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    head = _publish_head(
        settings, sessions=sessions[:3], expected_manifest=None,
        operation_id="comparison-seed-head",
        benchmark_snapshot_sha256=benchmark.sha256,
    )
    with TestClient(create_app(settings)) as client:
        accepted = client.post("/api/research-runs", json={
            **_run_command("comparison-seed", start_date=sessions[0], end_date=sessions[2]),
            "name": "Comparison seed",
        })
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["id"]
        completed = _run_worker_once(settings, "research")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        started = client.post(f"/api/research-runs/{run_id}/daily-tracks", json={
            "request_id": "comparison-start",
        })
        assert started.status_code == 201, started.text
        # The durable mutation receipt stays independent of the current display name.
        assert "seed_name" not in started.json()
        yield client, settings, run_id, started.json()["id"], head, sessions, benchmark.sha256


def test_daily_track_names_follow_research_rename_and_survive_seed_deletion(comparison_track):
    client, _settings, run_id, track_id, _head, _sessions, _benchmark = comparison_track

    def assert_name(expected):
        listing = client.get("/api/daily-tracks")
        assert listing.status_code == 200
        assert [(item["id"], item["seed_name"]) for item in listing.json()["items"]] == [
            (track_id, expected),
        ]
        detail = client.get(f"/api/daily-tracks/{track_id}")
        assert detail.status_code == 200
        assert detail.json()["seed_name"] == expected
        return detail.json()

    assert_name("Comparison seed")
    renamed = client.patch(f"/api/research-runs/{run_id}", json={"name": "Renamed seed"})
    assert renamed.status_code == 200
    assert_name("Renamed seed")
    assert client.delete(f"/api/research-runs/{run_id}").status_code == 204
    detail = assert_name(None)
    assert detail["origin"]["seed_research_available"] is False
    assert detail["origin"]["seed_run_id"] == run_id


def test_comparison_batch_reads_compact_performance_and_keeps_tracking_origin(comparison_track):
    client, settings, _run_id, track_id, head, sessions, benchmark = comparison_track
    response = client.get("/api/daily-tracks/comparison", params=[
        ("track_id", track_id), ("track_id", "missing"),
    ])
    assert response.status_code == 200, response.text
    assert response.json()["items"][1] == {"id": "missing", "values": None}
    values = response.json()["items"][0]["values"]
    observation = dict(values["observation"])
    assert Decimal(observation.pop("net_asset_value_cny")) == Decimal("9996901.24")
    assert observation == {
        "session": sessions[2], "net_return": 0.0,
        "maximum_drawdown": 0.0, "session_count": 0,
        "returns": [{"session": sessions[2], "net_return": 0.0}],
    }
    assert values["strategy"]["entry_session"] == sessions[1]
    assert values["strategy"]["net_return"] == -0.000309876
    assert values["strategy"]["returns"] == [
        {"session": session, "net_return": -0.000309876} for session in sessions[1:3]
    ]
    assert set(values) == {"status", "phase", "strategy_session", "observation", "strategy"}
    assert set(values["strategy"]) == {
        "entry_session", "net_return", "maximum_drawdown", "returns",
    }
    detail = client.get(f"/api/daily-tracks/{track_id}")
    assert len(response.content) < len(detail.content) / 2
    assert client.get("/api/daily-tracks/comparison").status_code == 422
    assert client.get("/api/daily-tracks/comparison", params={"track_id": ""}).status_code == 422
    assert client.get("/api/daily-tracks/comparison", params=[
        ("track_id", track_id) for _ in range(21)
    ]).status_code == 422

    _publish_head(settings, sessions=sessions, expected_manifest=head,
                  operation_id="comparison-later-head", benchmark_snapshot_sha256=benchmark)
    _refresh_daily_track(client, track_id, "comparison-refresh")
    advanced = _run_worker_once(settings, "tracking")
    assert advanced.returncode == 0, advanced.stdout + advanced.stderr
    response = client.get("/api/daily-tracks/comparison", params={"track_id": track_id})
    assert response.status_code == 200
    values = response.json()["items"][0]["values"]
    assert values["strategy_session"] == sessions[-1]
    assert values["phase"] == "up_to_date"
    assert values["observation"]["net_return"] == 0.0
    assert values["observation"]["session_count"] == 2
    assert values["observation"]["returns"] == [
        {"session": session, "net_return": 0.0} for session in sessions[2:]
    ]
    # A comparison read cannot advance a Track or expose another Researcher's facts.
    foreign_id = UUID("00000000-0000-4000-8000-000000000099")
    private = client.app.state.core_runtime.daily_tracks.compare(foreign_id, [track_id])
    assert private.model_dump(mode="json") == {"items": [{"id": track_id, "values": None}]}

from dataclasses import replace
from pathlib import Path

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _publish_head,
    _refresh_daily_track,
    _run_command,
    _stored_tracking_activation,
)

from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.daily_track.execution import SupervisedTrackingExecutor
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
def test_daily_track_rejects_malformed_observation_state_before_head_publication(
    tmp_path: Path,
    monkeypatch,
):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=sessions, price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = client.post("/api/research-runs", json=_run_command("invalid-observation")).json()[
            "id"
        ]
        assert runtime.research_runs.process_next()
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "invalid-observation-activate"},
        ).json()["id"]
        before = _stored_tracking_activation(settings, track_id)
        _publish_head(
            settings, sessions=(*sessions, "2026-08-06"), price_offset=1, expected_manifest=head
        )
        _refresh_daily_track(client, track_id, "invalid-observation-refresh")
        execute = SupervisedTrackingExecutor.execute

        def malformed(self, *args, **kwargs):
            execution = execute(self, *args, **kwargs)
            execution.result.checkpoint["tracking_observation_state"]["boundary_session"] = (
                "2099-01-01"
            )
            return execution

        with monkeypatch.context() as patch:
            patch.setattr(SupervisedTrackingExecutor, "execute", malformed)
            with pytest.raises(DailyTrackProgressionFailed):
                runtime.daily_tracks.process_next()
        after = _stored_tracking_activation(settings, track_id)
        assert (
            after["current_checkpoint_manifest_sha256"]
            == before["current_checkpoint_manifest_sha256"]
        )
        assert after["terminal_strategy_state"] == before["terminal_strategy_state"]
        assert after["checkpoint_count"] == 1
        assert after["failed_attempt_count"] == 1
        assert client.get(f"/api/daily-tracks/{track_id}").status_code == 200
        assert (
            client.post(
                f"/api/daily-tracks/{track_id}/retry",
                json={"request_id": "valid-observation-retry"},
            ).status_code
            == 202
        )
        assert runtime.daily_tracks.process_next()
        assert (
            client.get(f"/api/daily-tracks/{track_id}").json()["strategy_session"] == "2026-08-06"
        )


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
def test_daily_track_calendar_and_head_snapshot_exclude_concurrent_dataset_publication(
    tmp_path: Path,
    monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from core_runtime import TEST_RESEARCHER

    from thesistrace.data import DatasetLifecycle

    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=sessions, price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = client.post("/api/research-runs", json=_run_command("snapshot-calendar")).json()[
            "id"
        ]
        assert runtime.research_runs.process_next()
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "snapshot-calendar-track"},
        ).json()["id"]
        calendar_read, continue_snapshot, publisher_started = Event(), Event(), Event()
        admission = DatasetLifecycle.current_admission_in_transaction

        def hold_calendar(self, transaction):
            value = admission(self, transaction)
            calendar_read.set()
            assert continue_snapshot.wait(timeout=20)
            return value

        def publish_and_advance():
            publisher_started.set()
            _publish_head(
                settings, sessions=(*sessions, "2026-08-06"), price_offset=1, expected_manifest=head
            )
            _refresh_daily_track(client, track_id, "snapshot-calendar-refresh")
            assert runtime.daily_tracks.process_next()

        with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as executor:
            patch.setattr(DatasetLifecycle, "current_admission_in_transaction", hold_calendar)
            reading = executor.submit(
                runtime.daily_tracks.get, TEST_RESEARCHER.researcher_id, track_id
            )
            try:
                assert calendar_read.wait(timeout=10)
                # Prove the existing publication guard is held by the read transaction.
                with runtime.database.transaction() as tx:
                    available = tx.execute(
                        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS acquired",
                        ("thesistrace-mounted-data-lifecycle",),
                    ).fetchone()
                    assert available["acquired"] is False
                publishing = executor.submit(publish_and_advance)
                assert publisher_started.wait(timeout=10)
            finally:
                continue_snapshot.set()
            detail = reading.result(timeout=30)
            assert detail.strategy_session == sessions[-1]
            assert detail.data_through_session == sessions[-1]
            publishing.result(timeout=40)
        latest = runtime.daily_tracks.get(TEST_RESEARCHER.researcher_id, track_id)
        assert latest.strategy_session == latest.data_through_session == "2026-08-06"

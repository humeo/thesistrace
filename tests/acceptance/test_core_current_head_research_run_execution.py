from __future__ import annotations

import copy
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event, Thread
from time import monotonic

import boto3
import pytest
from botocore.config import Config
from canonical_store import align_canonical_market_data, open_complete_refresh_basis
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import (
    DailyTrackProgressionFailed,
    DailyTrackService,
    TrackingOrigin,
)
from thesistrace.daily_track.cache import MAX_WORKING_CACHE_BYTES
from thesistrace.daily_track.checkpoint import (
    project_tracking_checkpoint,
    restore_tracking_checkpoint,
    restore_tracking_origin,
    terminal_strategy_state,
)
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.financial_collection import (
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialDateShard,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication import Publication, PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import (
    AdvanceInput,
    RunInput,
    advance,
    advance_continuation,
    empty_continuation,
    run,
)
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.execution import SupervisedResearchExecutor
from thesistrace.research_run.models import ImmutableRunInput
from thesistrace.research_run.result import build_result_payload, read_result_bundle
from thesistrace.research_series import research_sessions, slice_research_sessions

ROOT = Path(__file__).resolve().parents[2]


class _InspectableTrackingPostgresDatabase(PostgresDatabase):
    def failed_request_count(self) -> int:
        return int(self._pool.get_stats().get("requests_errors", 0))


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_composite_formula_runs_and_starts_a_daily_track(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = (
        "2010-01-04",
        "2010-04-20",
        "2010-04-21",
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
    )
    generation_id = _publish_composite_head(settings, sessions=sessions)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        catalog = client.get("/api/alpha/catalog").json()
        assert "cs_rank" in {item["identifier"] for item in catalog["builtins"]}
        accepted = client.post(
            "/api/research-runs",
            json=_run_command(
                "composite-formula",
                formula="cs_rank(close_adj) + cs_rank(total_revenue_latest_fy)",
            ),
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["id"]
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "queued"
        execution_events: list[dict[str, object]] = []
        attempt_status_at_child_exit: list[object] = []

        def capture_execution_lifecycle(event: dict[str, object]) -> None:
            execution_events.append(event)
            if event["event"] == "research_execution_child_exited":
                attempt_status_at_child_exit.append(
                    _stored_execution(settings, run_id)["attempt_status"]
                )

        assert (
            client.app.state.core_runtime.research_runs.process_next(
                on_execution_event=capture_execution_lifecycle
            )
            is True
        )
        assert [event["event"] for event in execution_events] == [
            "research_execution_child_started",
            "research_execution_chunk_received",
            "research_execution_chunk_committed",
            "research_execution_child_acknowledged",
            "research_execution_child_exited",
        ]
        received = execution_events[1]
        assert float(received["child_data_read_seconds"]) >= 0
        assert float(received["child_calculation_seconds"]) >= 0
        assert (
            float(received["child_data_read_seconds"])
            + float(received["child_calculation_seconds"])
            <= float(received["child_chunk_seconds"])
        )
        phase_seconds = received["child_calculation_phase_seconds"]
        assert set(phase_seconds) == {
            "input",
            "alpha_and_pending",
            "factor",
            "strategy",
            "finalize",
        }
        assert all(float(value) >= 0 for value in phase_seconds.values())
        assert sum(float(value) for value in phase_seconds.values()) <= float(
            received["child_calculation_seconds"]
        )
        assert attempt_status_at_child_exit == ["running"]
        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded"
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_data_generation_id"] == generation_id
        actual = read_result_bundle(
            runtime.publication.read(
                PublishedRef(
                    manifest_sha256=str(stored["result_manifest_sha256"]),
                    kind="research.result",
                    provenance=stored["result_provenance"],
                )
            )
        )
        assert canonical_json_bytes(actual) == canonical_json_bytes(
            _reference_result(settings, generation_id, runtime.database, run_id)
        )

        financial_only = client.post(
            "/api/research-runs",
            json=_run_command(
                "financial-only-formula",
                formula="total_revenue_latest_fy",
            ),
        ).json()["id"]
        assert runtime.research_runs.process_next() is True
        financial_stored = _stored_execution(settings, financial_only)
        financial_actual = read_result_bundle(
            runtime.publication.read(
                PublishedRef(
                    manifest_sha256=str(financial_stored["result_manifest_sha256"]),
                    kind="research.result",
                    provenance=financial_stored["result_provenance"],
                )
            )
        )
        assert canonical_json_bytes(financial_actual) == canonical_json_bytes(
            _reference_result(
                settings,
                generation_id,
                runtime.database,
                financial_only,
            )
        )
        started = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "composite-track"},
        )
        assert started.status_code == 201
        assert started.json()["status"] == "active"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_2010_to_latest_market_financial_and_composite_runs_commit_multiple_chunks(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _weekday_sessions_between(date(2010, 1, 4), date(2026, 8, 13))
    assert len(sessions) > 4_000
    _publish_composite_head(
        settings,
        sessions=sessions,
        operation_id="long-research-multi-formula",
    )

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        for index, formula in enumerate(
            (
                "close_adj",
                "total_revenue_latest_fy",
                "cs_rank(close_adj) + cs_rank(total_revenue_latest_fy)",
            )
        ):
            execution_events: list[dict[str, object]] = []
            accepted = client.post(
                "/api/research-runs",
                json=_run_command(
                    f"long-research-{index}",
                    formula=formula,
                    start_date=sessions[0],
                    end_date=sessions[-1],
                ),
            )
            assert accepted.status_code == 202, accepted.text
            run_id = str(accepted.json()["id"])
            if index == 0:
                second_checkpoint = Event()
                release_execution = Event()
                committed_boundaries = [0]

                def pause_after_second_checkpoint(
                    stage: str,
                    target_run_id: str,
                    expected_run_id: str = run_id,
                    checkpoint_event: Event = second_checkpoint,
                    release_event: Event = release_execution,
                    boundary_count: list[int] = committed_boundaries,
                ) -> None:
                    if stage == "checkpoint" and target_run_id == expected_run_id:
                        boundary_count[0] += 1
                    if boundary_count[0] == 2 and not checkpoint_event.is_set():
                        checkpoint_event.set()
                        assert release_event.wait(timeout=20)

                processor = ResearchRunService(
                    runtime.database,
                    dataset_lifecycle=DatasetLifecycle(
                        runtime.database,
                        settings.data_mount,
                    ),
                    generation_store=MountedGenerationStore(settings.data_mount),
                    publication=runtime.publication,
                    execution=SupervisedResearchExecutor(settings.data_mount),
                    progress=pause_after_second_checkpoint,
                )
                worker = Thread(
                    target=processor.process_next,
                    kwargs={"on_execution_event": execution_events.append},
                )
                worker.start()
                assert second_checkpoint.wait(timeout=20)
                committed = client.get(f"/api/research-runs/{run_id}").json()
                assert committed["status"] == "running"
                assert committed["progress"]["committed_chunk_count"] == 2
                assert committed["progress"]["completed_research_sessions"] > 0
                assert committed["progress"]["completed_research_sessions"] < len(sessions)
                assert committed["progress"]["remaining_duration_estimate_seconds"] >= 1
                release_execution.set()
                worker.join(timeout=120)
                assert not worker.is_alive()
            else:
                processor = ResearchRunService(
                    runtime.database,
                    dataset_lifecycle=DatasetLifecycle(
                        runtime.database,
                        settings.data_mount,
                    ),
                    generation_store=MountedGenerationStore(settings.data_mount),
                    publication=runtime.publication,
                    execution=SupervisedResearchExecutor(settings.data_mount),
                )
                assert processor.process_next(on_execution_event=execution_events.append) is True
            peak_rss_values = [
                int(event["child_peak_rss_bytes"])
                for event in execution_events
                if event["event"] == "research_execution_chunk_received"
            ]
            assert len(peak_rss_values) >= 3
            assert max(peak_rss_values) <= 1536 * 1024**2
            detail = client.get(f"/api/research-runs/{run_id}").json()
            assert detail["status"] == "succeeded"
            assert detail["progress"]["phase"] == "succeeded"
            assert detail["progress"]["completed_research_sessions"] == len(sessions)
            assert detail["progress"]["total_research_sessions"] == len(sessions)
            assert detail["progress"]["committed_chunk_count"] >= 3
            assert "checkpoint" not in str(detail).lower()
            assert "staged" not in str(detail).lower()
        with runtime.database.transaction() as transaction:
            private_state = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM research_runs.execution_checkpoints)
                        AS checkpoint_count,
                    (SELECT count(*) FROM publication.manifests
                     WHERE kind = 'research.execution-checkpoint')
                        AS checkpoint_manifest_count
                """
            ).fetchone()
        assert private_state == {
            "checkpoint_count": 0,
            "checkpoint_manifest_count": 0,
        }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_financial_track_blocks_at_cutoff_then_catches_up(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = (
        "2010-01-04",
        "2010-04-20",
        "2010-04-21",
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
    )
    seed_head = _publish_composite_head(settings, sessions=seed_sessions)
    formula = "cs_rank(close_adj) + cs_rank(total_revenue_latest_fy)"
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("financial-track-seed", formula=formula),
        )
        run_id = accepted.json()["id"]
        assert client.app.state.core_runtime.research_runs.process_next() is True
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "financial-track-activation"},
        ).json()["id"]

        lagged_sessions = (*seed_sessions, "2026-08-06", "2026-08-07")
        lagged_head = _publish_composite_head(
            settings,
            sessions=lagged_sessions,
            financial_through="2026-08-06",
            expected_manifest=seed_head,
            operation_id="financial-track-lagged",
        )
        assert client.app.state.core_runtime.daily_tracks.process_next() is True
        covered = client.get(f"/api/daily-tracks/{track_id}").json()
        assert covered["status"] == "active"
        assert covered["strategy_session"] == "2026-08-06"

        assert client.app.state.core_runtime.daily_tracks.process_next() is True
        blocked = client.get(f"/api/daily-tracks/{track_id}").json()
        assert blocked["status"] == "blocked"
        assert blocked["strategy_session"] == "2026-08-06"
        assert blocked["blocked_reason"] == (
            "Financial Coverage ends before the next Research Session."
        )
        before = _tracking_checkpoint_history(settings, track_id)

        recovered_sessions = (*lagged_sessions, "2026-08-10")
        _publish_composite_head(
            settings,
            sessions=recovered_sessions,
            expected_manifest=lagged_head,
            operation_id="financial-track-recovered",
        )
        retry = client.post(
            f"/api/daily-tracks/{track_id}/retry",
            json={"request_id": "financial-track-retry"},
        )
        assert retry.status_code == 202
        assert client.app.state.core_runtime.daily_tracks.process_next() is True
        first_recovery = client.get(f"/api/daily-tracks/{track_id}").json()
        assert first_recovery["strategy_session"] == "2026-08-07"
        assert client.app.state.core_runtime.daily_tracks.process_next() is True
        recovered = client.get(f"/api/daily-tracks/{track_id}").json()
        assert recovered["status"] == "active"
        assert recovered["strategy_session"] == recovered_sessions[-1]
        assert _tracking_checkpoint_history(settings, track_id)[: len(before)] == before


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tracking_advance_freezes_and_publishes_only_the_oldest_64_sessions(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-01-02", "2026-01-05", "2026-01-06")
    head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = client.post(
            "/api/research-runs",
            json=_run_command(
                "tracking-target-64-seed",
                start_date=seed_sessions[0],
                end_date=seed_sessions[-1],
            ),
        ).json()["id"]
        assert runtime.research_runs.process_next() is True
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "tracking-target-64-activation"},
        ).json()["id"]
        backlog = _weekday_sessions_after(date.fromisoformat(seed_sessions[-1]), count=70)
        _publish_head(
            settings,
            sessions=(*seed_sessions, *backlog),
            price_offset=1,
            expected_manifest=head,
        )

        execution_events: list[dict[str, object]] = []
        assert runtime.daily_tracks.process_next(on_execution_event=execution_events.append) is True

        detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert detail["strategy_session"] == backlog[63]
        assert detail["lag_sessions"] == 6
        with runtime.database.transaction() as transaction:
            progression = transaction.execute(
                """
                SELECT target_sessions, status
                FROM daily_tracks.session_progressions
                WHERE track_id = %s
                """,
                (track_id,),
            ).fetchone()
            attempt_count = transaction.execute(
                """
                SELECT count(*) AS count
                FROM daily_tracks.session_progression_attempts
                WHERE track_id = %s
                """,
                (track_id,),
            ).fetchone()
        assert progression is not None
        assert [item.isoformat() for item in progression["target_sessions"]] == list(backlog[:64])
        assert progression["status"] == "succeeded"
        assert attempt_count == {"count": 1}
        assert [event["event"] for event in execution_events] == [
            "tracking_execution_child_started",
            "tracking_execution_progress",
            "tracking_execution_progress",
            "tracking_execution_result_received",
            "tracking_execution_child_acknowledged",
            "tracking_execution_child_exited",
        ]
        assert execution_events[-1]["acknowledged"] is True
        assert execution_events[-1]["exit_code"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tracking_advance_blocks_one_session_before_creating_an_attempt(
    tmp_path: Path,
) -> None:
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path,
        tracking_execution_memory_bytes=1,
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("tracking-capacity-block-seed"),
        ).json()["id"]
        assert runtime.research_runs.process_next() is True
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "tracking-capacity-block-activation"},
        ).json()["id"]
        target_sessions = (*seed_sessions, "2026-08-06", "2026-08-07")
        _publish_head(
            settings,
            sessions=target_sessions,
            price_offset=1,
            expected_manifest=head,
        )

        assert runtime.daily_tracks.process_next() is True

        detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert detail["status"] == "blocked"
        assert detail["strategy_session"] == seed_sessions[-1]
        assert detail["blocked_reason"] == ("DailyTrack target exceeds Tracking Worker capacity.")
        assert detail["progress"] == {
            "head_session": seed_sessions[-1],
            "lag_sessions": 2,
            "phase": "blocked",
            "target_start_session": "2026-08-06",
            "target_end_session": "2026-08-06",
            "target_session_count": 1,
            "completed_target_sessions": 0,
            "current_session": None,
            "cycle_attempt": None,
            "cycle_attempt_limit": 3,
            "retry_wait": False,
            "next_attempt_eligible_at": None,
        }
        with runtime.database.transaction() as transaction:
            progression = transaction.execute(
                """
                SELECT target_sessions, status
                FROM daily_tracks.session_progressions
                WHERE track_id = %s
                """,
                (track_id,),
            ).fetchone()
            counts = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM daily_tracks.session_progression_attempts
                     WHERE track_id = %s) AS attempts,
                    (SELECT count(*) FROM data.generation_pins
                     WHERE owner_kind = 'tracking_advance_attempt'
                       AND status = 'active') AS active_pins
                """,
                (track_id,),
            ).fetchone()
        assert progression is not None
        assert progression["target_sessions"] == [date(2026, 8, 6)]
        assert progression["status"] == "blocked"
        assert counts == {"attempts": 0, "active_pins": 0}

        retry = client.post(
            f"/api/daily-tracks/{track_id}/retry",
            json={"request_id": "tracking-capacity-block-retry"},
        )
        assert retry.status_code == 202
        assert retry.json()["status"] == "blocked"
        with runtime.database.transaction() as transaction:
            unchanged = transaction.execute(
                """
                SELECT status, current_cycle_ordinal,
                       (SELECT count(*)
                        FROM daily_tracks.session_progression_attempts
                        WHERE track_id = %s) AS attempt_count
                FROM daily_tracks.session_progressions
                WHERE track_id = %s
                """,
                (track_id, track_id),
            ).fetchone()
        assert unchanged == {
            "status": "blocked",
            "current_cycle_ordinal": None,
            "attempt_count": 0,
        }

    fit_settings = replace(
        settings,
        tracking_execution_memory_bytes=(
            CoreSettings.from_environment().tracking_execution_memory_bytes
        ),
    )
    with TestClient(create_app(fit_settings)) as restarted:
        assert restarted.app.state.core_runtime.daily_tracks.process_next() is False
        retry = restarted.post(
            f"/api/daily-tracks/{track_id}/retry",
            json={"request_id": "tracking-capacity-fit-retry"},
        )
        assert retry.status_code == 202
        assert retry.json()["status"] == "active"
        assert restarted.app.state.core_runtime.daily_tracks.process_next() is True
        first_real_cycle = _tracking_retry_state(fit_settings, str(track_id))
        assert first_real_cycle["progression_status"] == "succeeded"
        assert first_real_cycle["cycle_ordinal"] == 1
        assert first_real_cycle["attempt_cycles"] == [1]
        assert first_real_cycle["attempt_ordinals"] == [1]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tracking_transient_cycle_persists_backoff_rotates_and_requires_retry(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-01-02", "2026-01-05", "2026-01-06")
    head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        track_ids: list[str] = []
        for index in range(2):
            run_id = client.post(
                "/api/research-runs",
                json=_run_command(
                    f"tracking-retry-cycle-seed-{index}",
                    start_date=seed_sessions[0],
                    end_date=seed_sessions[-1],
                ),
            ).json()["id"]
            assert runtime.research_runs.process_next() is True
            track_ids.append(
                str(
                    client.post(
                        f"/api/research-runs/{run_id}/daily-tracks",
                        json={"request_id": f"tracking-retry-cycle-activation-{index}"},
                    ).json()["id"]
                )
            )
        retry_track, control_track = track_ids
        backlog = _weekday_sessions_after(date.fromisoformat(seed_sessions[-1]), count=70)
        backlog_head = _publish_head(
            settings,
            sessions=(*seed_sessions, *backlog),
            price_offset=1,
            expected_manifest=head,
        )
        unavailable_s3 = boto3.client(
            "s3",
            endpoint_url="http://127.0.0.1:1",
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                connect_timeout=0.1,
                read_timeout=0.1,
                retries={"max_attempts": 0},
            ),
        )
        failing = DailyTrackService(
            runtime.database,
            publication=Publication(
                runtime.database,
                unavailable_s3,
                bucket=settings.s3_bucket,
            ),
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )
        try:
            with pytest.raises(DailyTrackProgressionFailed):
                failing.process_next()
            first = _tracking_retry_state(settings, retry_track)
            assert first["track_status"] == "active"
            assert first["progression_status"] == "running"
            assert first["cycle_ordinal"] == 1
            assert first["attempt_ordinals"] == [1]
            assert first["attempt_failures"] == ["InfrastructureFailure"]
            assert first["retry_delay_seconds"] == pytest.approx(5, abs=0.01)
            progress = client.get(f"/api/daily-tracks/{retry_track}").json()["progress"]
            assert progress["phase"] == "retry_wait"
            assert progress["cycle_attempt"] == 1
            assert progress["retry_wait"] is True
            assert progress["completed_target_sessions"] == 0

            claimed: list[str] = []
            assert (
                runtime.daily_tracks.process_next(
                    on_claim=lambda track_id, _attempt_id: claimed.append(track_id)
                )
                is True
            )
            assert claimed == [control_track]
            assert client.get(f"/api/daily-tracks/{control_track}").json()["lag_sessions"] == 6

            _make_tracking_retry_eligible(settings, retry_track)
            claimed.clear()
            assert (
                runtime.daily_tracks.process_next(
                    on_claim=lambda track_id, _attempt_id: claimed.append(track_id)
                )
                is True
            )
            assert claimed == [control_track]
            assert client.get(f"/api/daily-tracks/{control_track}").json()["lag_sessions"] == 0

            with pytest.raises(DailyTrackProgressionFailed):
                failing.process_next()
            second = _tracking_retry_state(settings, retry_track)
            assert second["attempt_ordinals"] == [1, 2]
            assert second["retry_delay_seconds"] == pytest.approx(30, abs=0.01)
            _make_tracking_retry_eligible(settings, retry_track)

            with pytest.raises(DailyTrackProgressionFailed):
                failing.process_next()
            exhausted = _tracking_retry_state(settings, retry_track)
            assert exhausted["track_status"] == "blocked"
            assert exhausted["progression_status"] == "blocked"
            assert exhausted["attempt_ordinals"] == [1, 2, 3]
            assert exhausted["next_attempt_eligible_at"] is None
            assert (
                client.get(f"/api/daily-tracks/{retry_track}").json()["blocked_reason"]
                == "DailyTrack exhausted its automatic infrastructure retries."
            )
            assert runtime.daily_tracks.process_next() is False
        finally:
            unavailable_s3.close()

        _publish_head(
            settings,
            sessions=(*seed_sessions, *backlog),
            price_offset=2,
            expected_manifest=backlog_head,
        )
        restarted_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )
        assert restarted_processor.process_next() is False

        retry = client.post(
            f"/api/daily-tracks/{retry_track}/retry",
            json={"request_id": "tracking-retry-cycle-explicit"},
        )
        assert retry.status_code == 202
        assert retry.json()["status"] == "active"
        assert runtime.daily_tracks.process_next() is True
        recovered = _tracking_retry_state(settings, retry_track)
        assert recovered["track_status"] == "active"
        assert recovered["progression_status"] == "succeeded"
        assert recovered["cycle_ordinal"] == 2
        assert recovered["attempt_cycles"] == [1, 1, 1, 2]
        assert recovered["attempt_ordinals"] == [1, 2, 3, 1]
        assert recovered["attempt_generations"][:3] == [backlog_head] * 3
        assert recovered["attempt_generations"][3] != backlog_head
        assert (
            client.get(f"/api/daily-tracks/{retry_track}").json()["strategy_session"]
            == backlog[63]
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_blocked_and_retry_wait_tracks_stop_without_future_attempts(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        track_ids: list[str] = []
        for index in range(2):
            run_id = client.post(
                "/api/research-runs",
                json=_run_command(f"stop-non-running-track-{index}"),
            ).json()["id"]
            assert runtime.research_runs.process_next() is True
            track_ids.append(
                str(
                    client.post(
                        f"/api/research-runs/{run_id}/daily-tracks",
                        json={"request_id": f"stop-non-running-track-{index}"},
                    ).json()["id"]
                )
            )
        _publish_head(
            settings,
            sessions=(*seed_sessions, "2026-08-06"),
            price_offset=1,
            expected_manifest=head,
        )

        capacity_blocker = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            execution_memory_bytes=1,
        )
        assert capacity_blocker.process_next() is True
        blocked_track, retry_wait_track = track_ids
        assert client.get(f"/api/daily-tracks/{blocked_track}").json()["status"] == "blocked"
        blocked_stop = client.post(
            f"/api/daily-tracks/{blocked_track}/stop",
            json={"request_id": "stop-capacity-blocked-track"},
        )
        assert blocked_stop.status_code == 202
        assert blocked_stop.json()["status"] == "stopped"
        blocked_state = _tracking_retry_state(settings, blocked_track)
        assert blocked_state["progression_status"] == "cancelled"
        assert blocked_state["attempt_ordinals"] == []

        unavailable_s3 = boto3.client(
            "s3",
            endpoint_url="http://127.0.0.1:1",
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                connect_timeout=0.1,
                read_timeout=0.1,
                retries={"max_attempts": 0},
            ),
        )
        try:
            failing = DailyTrackService(
                runtime.database,
                publication=Publication(
                    runtime.database,
                    unavailable_s3,
                    bucket=settings.s3_bucket,
                ),
                dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
                generation_store=MountedGenerationStore(settings.data_mount),
                read_result_bundle=read_result_bundle,
            )
            with pytest.raises(DailyTrackProgressionFailed):
                failing.process_next()
        finally:
            unavailable_s3.close()
        retry_wait = client.get(f"/api/daily-tracks/{retry_wait_track}").json()
        assert retry_wait["progress"]["phase"] == "retry_wait"
        retry_wait_stop = client.post(
            f"/api/daily-tracks/{retry_wait_track}/stop",
            json={"request_id": "stop-retry-wait-track"},
        )
        assert retry_wait_stop.status_code == 202
        assert retry_wait_stop.json()["status"] == "stopped"
        stopped_state = _tracking_retry_state(settings, retry_wait_track)
        assert stopped_state["progression_status"] == "cancelled"
        assert stopped_state["attempt_ordinals"] == [1]
        assert stopped_state["next_attempt_eligible_at"] is None

    with TestClient(create_app(settings)) as restarted:
        assert restarted.app.state.core_runtime.daily_tracks.process_next() is False
        assert _tracking_retry_state(settings, retry_wait_track)["attempt_ordinals"] == [1]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tracking_heartbeat_pool_timeout_enters_the_transient_cycle(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("tracking-heartbeat-pool-timeout"),
        ).json()["id"]
        assert runtime.research_runs.process_next() is True
        track_id = str(
            client.post(
                f"/api/research-runs/{run_id}/daily-tracks",
                json={"request_id": "tracking-heartbeat-pool-timeout-activation"},
            ).json()["id"]
        )
        _publish_head(
            settings,
            sessions=(*seed_sessions, "2026-08-06"),
            price_offset=1,
            expected_manifest=head,
        )

        constrained = _InspectableTrackingPostgresDatabase(
            settings.database_url,
            pool_max_size=2,
            pool_timeout_seconds=0.05,
        )
        constrained.open()
        holder: Thread | None = None
        holder_errors: list[BaseException] = []
        injected = Event()

        def exhaust_pool_during_calculation(event: dict[str, object]) -> None:
            nonlocal holder
            if (
                injected.is_set()
                or event.get("event") != "tracking_execution_progress"
                or event.get("phase") != "calculating"
            ):
                return
            injected.set()
            holder_finished = Event()

            def hold_until_heartbeat_timeout() -> None:
                try:
                    poll = Event()
                    with constrained.transaction():
                        failed_requests = constrained.failed_request_count()
                        for _ in range(500):
                            if constrained.failed_request_count() > failed_requests:
                                return
                            poll.wait(0.01)
                        raise AssertionError("Tracking heartbeat pool request did not time out")
                except BaseException as error:
                    holder_errors.append(error)
                finally:
                    holder_finished.set()

            holder = Thread(target=hold_until_heartbeat_timeout, daemon=True)
            holder.start()
            assert holder_finished.wait(timeout=10)

        processor = DailyTrackService(
            constrained,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(constrained, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            lease_seconds=1,
            heartbeat_seconds=0.05,
        )
        try:
            with pytest.raises(DailyTrackProgressionFailed):
                processor.process_next(on_execution_event=exhaust_pool_during_calculation)
            assert holder is not None
            holder.join(timeout=5)
            assert not holder.is_alive()
            assert holder_errors == []
        finally:
            constrained.close()

        retry_wait = _tracking_retry_state(settings, track_id)
        assert retry_wait["track_status"] == "active"
        assert retry_wait["attempt_ordinals"] == [1]
        assert retry_wait["attempt_failures"] == ["InfrastructureFailure"]
        assert retry_wait["retry_delay_seconds"] == pytest.approx(5, abs=0.01)
        state = _stored_tracking_activation(settings, track_id)
        assert state["current_checkpoint_session"].isoformat() == seed_sessions[-1]
        assert state["active_pin_count"] == 0

        _make_tracking_retry_eligible(settings, track_id)
        assert runtime.daily_tracks.process_next() is True
        assert (
            client.get(f"/api/daily-tracks/{track_id}").json()["strategy_session"]
            == "2026-08-06"
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tracking_retry_blocks_when_current_generation_breaks_the_frozen_target(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("tracking-generation-mismatch-seed"),
        ).json()["id"]
        assert runtime.research_runs.process_next() is True
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "tracking-generation-mismatch-activation"},
        ).json()["id"]
        frozen_target = ("2026-08-06", "2026-08-07", "2026-08-10")
        target_head = _publish_head(
            settings,
            sessions=(*seed_sessions, *frozen_target),
            price_offset=1,
            expected_manifest=seed_head,
        )

        def kill_first_attempt(event: dict[str, object]) -> None:
            if event["event"] == "tracking_execution_child_started":
                os.kill(int(event["child_pid"]), 9)

        with pytest.raises(DailyTrackProgressionFailed):
            runtime.daily_tracks.process_next(on_execution_event=kill_first_attempt)

        mismatched_generation = _publish_head(
            settings,
            sessions=(*seed_sessions, frozen_target[0], frozen_target[-1]),
            price_offset=2,
            expected_manifest=target_head,
        )
        retry = client.post(
            f"/api/daily-tracks/{track_id}/retry",
            json={"request_id": "tracking-generation-mismatch-retry"},
        )
        assert retry.status_code == 202
        with pytest.raises(DailyTrackProgressionFailed):
            runtime.daily_tracks.process_next()

        detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert detail["status"] == "blocked"
        assert detail["strategy_session"] == seed_sessions[-1]
        with runtime.database.transaction() as transaction:
            progression = transaction.execute(
                """
                SELECT target_sessions, status
                FROM daily_tracks.session_progressions
                WHERE track_id = %s
                """,
                (track_id,),
            ).fetchone()
            attempts = transaction.execute(
                """
                SELECT ordinal, data_generation_id, status
                FROM daily_tracks.session_progression_attempts
                WHERE track_id = %s
                ORDER BY ordinal
                """,
                (track_id,),
            ).fetchall()
        assert progression is not None
        assert [value.isoformat() for value in progression["target_sessions"]] == list(
            frozen_target
        )
        assert progression["status"] == "blocked"
        assert [row["data_generation_id"] for row in attempts] == [
            target_head,
            mismatched_generation,
        ]
        assert [row["status"] for row in attempts] == ["failed", "failed"]
        state = _stored_tracking_activation(settings, str(track_id))
        assert state["current_checkpoint_session"].isoformat() == seed_sessions[-1]
        assert state["checkpoint_count"] == 1
        assert state["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_financial_admission_explains_coverage_without_blocking_market_only_formulae(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = (
        "2010-01-04",
        "2010-04-20",
        "2010-04-21",
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
    )
    _publish_composite_head(settings, sessions=sessions, financial_through="2026-08-06")

    with TestClient(create_app(settings)) as client:
        rejected = client.post(
            "/api/research-runs",
            json=_run_command(
                "financial-outside-coverage",
                formula="total_revenue_latest_fy",
                start_date="2026-08-07",
                end_date="2026-08-07",
            ),
        )
        assert rejected.status_code == 422
        issues = rejected.json()["issues"]
        assert len(issues) == 1
        assert issues[0]["code"] == "FINANCIAL_CALCULATION_OUTSIDE_COVERAGE"
        assert issues[0]["field"] == "formula"
        assert issues[0]["message"] == (
            "Financial Formula needs its requested period and lookback inside "
            "Financial Coverage; current Financial Coverage is "
            "2010-01-04 to 2026-08-06."
        )

        market_only = client.post(
            "/api/research-runs",
            json=_run_command(
                "market-only-after-finance-cutoff",
                start_date="2026-08-07",
                end_date="2026-08-07",
            ),
        )
        assert market_only.status_code == 202


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_product_state_hard_cut_reuses_the_exact_canonical_head(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("removed-by-product-state-hard-cut"),
        ).json()["id"]
        assert client.get(f"/api/research-runs/{run_id}").status_code == 200

    drop_product_schemas(settings)
    initialize_core(settings.database_url)

    with TestClient(create_app(settings)) as reset_runtime:
        overview = reset_runtime.get("/api/data")
        assert overview.status_code == 200
        assert overview.json()["data_through_session"] == sessions[-1]
        assert reset_runtime.get(f"/api/research-runs/{run_id}").status_code == 404
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        current_head = DatasetLifecycle(database, settings.data_mount).current_pointer()
        assert current_head is not None
        assert current_head.generation_manifest_sha256 == head
    finally:
        database.close()
    assert (
        MountedGenerationStore(settings.data_mount).validate_generation(head).manifest_sha256
        == head
    )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_fixed_role_worker_replicas_claim_distinct_runs_and_tracks(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        guarded_run_id = client.post(
            "/api/research-runs",
            json=_run_command("single-research-owner"),
        ).json()["id"]
        research_owner = _start_claim_barrier_worker(settings, "research")
        assert _wait_for_barrier_claim(research_owner)["resource_id"] == guarded_run_id
        rejected_research_owner = _run_worker_once(settings, "research")
        assert rejected_research_owner.returncode == 0, (
            rejected_research_owner.stdout + rejected_research_owner.stderr
        )
        assert not [
            event
            for event in _worker_events(rejected_research_owner)
            if event["event"] == "worker_claim"
        ]
        _release_claim_barrier_worker(research_owner)
        assert _stored_execution(settings, guarded_run_id)["attempt_count"] == 1

        run_ids = [
            client.post(
                "/api/research-runs",
                json=_run_command(f"replicated-research-worker-{index}"),
            ).json()["id"]
            for index in range(2)
        ]
        research_workers = _run_worker_replicas(settings, "research", 2)
        assert all(worker.returncode == 0 for worker in research_workers)
        assert {
            client.get(f"/api/research-runs/{run_id}").json()["status"] for run_id in run_ids
        } == {"succeeded"}
        assert {
            event["resource_id"]
            for worker in research_workers
            for event in _worker_events(worker)
            if event["event"] == "worker_claim"
        } == set(run_ids)
        research_events = [event for worker in research_workers for event in _worker_events(worker)]
        assert {
            (event["resource_id"], event["attempt_id"])
            for event in research_events
            if event["event"] == "research_execution_child_started"
        } == {
            (event["resource_id"], event["attempt_id"])
            for event in research_events
            if event["event"] == "worker_claim"
        }
        assert {
            (event["resource_id"], event["attempt_id"])
            for event in research_events
            if event["event"] == "research_execution_child_acknowledged"
        } == {
            (event["resource_id"], event["attempt_id"])
            for event in research_events
            if event["event"] == "worker_claim"
        }

        guarded_track_id = client.post(
            f"/api/research-runs/{guarded_run_id}/daily-tracks",
            json={"request_id": "single-tracking-owner"},
        ).json()["id"]
        extended_sessions = (*sessions, "2026-08-06")
        _publish_head(
            settings,
            sessions=extended_sessions,
            price_offset=1,
            expected_manifest=head,
        )
        tracking_owner = _start_claim_barrier_worker(settings, "tracking")
        assert _wait_for_barrier_claim(tracking_owner)["resource_id"] == guarded_track_id
        rejected_tracking_owner = _run_worker_once(settings, "tracking")
        assert rejected_tracking_owner.returncode == 0, (
            rejected_tracking_owner.stdout + rejected_tracking_owner.stderr
        )
        assert not [
            event
            for event in _worker_events(rejected_tracking_owner)
            if event["event"] == "worker_claim"
        ]
        _release_claim_barrier_worker(tracking_owner)
        guarded_track_state = _stored_tracking_activation(settings, guarded_track_id)
        assert guarded_track_state["progression_count"] == 1
        assert guarded_track_state["attempt_count"] == 1

        track_ids = [
            client.post(
                f"/api/research-runs/{run_id}/daily-tracks",
                json={"request_id": f"replicated-tracking-worker-{index}"},
            ).json()["id"]
            for index, run_id in enumerate(run_ids)
        ]
        tracking_workers = _run_worker_replicas(settings, "tracking", 2)
        assert all(worker.returncode == 0 for worker in tracking_workers), "\n\n".join(
            f"tracking worker {index} exited {worker.returncode}\n"
            f"stdout:\n{worker.stdout}\n"
            f"stderr:\n{worker.stderr}"
            for index, worker in enumerate(tracking_workers)
        )
        assert {
            client.get(f"/api/daily-tracks/{track_id}").json()["strategy_session"]
            for track_id in track_ids
        } == {extended_sessions[-1]}
        assert {
            event["resource_id"]
            for worker in tracking_workers
            for event in _worker_events(worker)
            if event["event"] == "worker_claim"
        } == set(track_ids)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_research_execution_refuses_obsolete_numeric_contract(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("obsolete-research-numeric-contract"),
        )
        run_id = accepted.json()["id"]
        _replace_research_numeric_contract(
            settings,
            run_id,
            "obsolete-numeric-contract",
        )

        assert client.app.state.core_runtime.research_runs.process_next() is True

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        assert detail["failure_reason"] == (
            "Research execution contract does not match this runtime."
        )
        assert "result" not in detail
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_failure_reason"] == "ContractMismatch"
        assert stored["result_manifest_sha256"] is None
        assert stored["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tracking_execution_refuses_obsolete_numeric_contract(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("obsolete-tracking-numeric-contract"),
        ).json()["id"]
        assert client.app.state.core_runtime.research_runs.process_next() is True
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "obsolete-tracking-contract-activation"},
        ).json()["id"]
        _replace_tracking_numeric_contract(
            settings,
            track_id,
            "obsolete-numeric-contract",
        )
        extended_sessions = (*sessions, "2026-08-06")
        _publish_head(
            settings,
            sessions=extended_sessions,
            price_offset=1,
            expected_manifest=head,
        )

        with pytest.raises(DailyTrackProgressionFailed):
            client.app.state.core_runtime.daily_tracks.process_next()

        stored = _stored_tracking_activation(settings, track_id)
        assert stored["track_status"] == "blocked"
        assert stored["latest_attempt_failure_reason"] == "NumericContractError"
        assert stored["current_checkpoint_session"].isoformat() == sessions[-1]
        assert stored["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_uses_the_generation_frozen_when_run_is_admitted(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("attempt-start-head"),
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["id"]
        head_b = _publish_head(
            settings,
            sessions=sessions,
            price_offset=1,
            expected_manifest=head_a,
        )

        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr

        detail = client.get(f"/api/research-runs/{run_id}")
        assert detail.status_code == 200
        public_run = detail.json()
        assert public_run["status"] == "succeeded"
        assert set(public_run) == {
            "id",
            "status",
            "name",
            "folder_id",
            "created_at",
            "start_date",
            "end_date",
            "formula_summary",
            "input",
            "progress",
            "result",
        }
        assert set(public_run["result"]) == {
            "factor",
            "strategy",
            "terminal_strategy_state",
            "provenance",
        }
        assert set(public_run["result"]["provenance"]) == {
            "schema_version",
            "research_run_id",
            "immutable_input_sha256",
            "calculation_contracts",
            "semantic_versions",
        }
        assert len(public_run["result"]["strategy"]["observations"]) == 3
        terminal_account = public_run["result"]["terminal_strategy_state"]
        assert terminal_account["session"] == sessions[-1]
        assert (
            terminal_account["net_nav"]
            == public_run["result"]["strategy"]["observations"][-1]["net_nav"]
        )
        assert set(terminal_account) == {
            "session",
            "gross_cash",
            "net_cash",
            "gross_nav",
            "net_nav",
            "benchmark_nav",
            "cumulative_transaction_cost",
            "positions",
            "rebalance_phase",
            "pending_signal",
        }
        assert "generation" not in str(public_run).lower()

        stored = _stored_execution(settings, run_id)
        assert stored["attempt_data_generation_id"] == head_a
        assert stored["attempt_data_through_session"].isoformat() == sessions[-1]
        assert stored["result_provenance"]["data_generation_id"] == head_a
        assert stored["result_provenance"]["data_through_session"] == sessions[-1]
        assert stored["active_pin_count"] == 0

        tracking = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "attempt-start-head-track"},
        )
        assert tracking.status_code == 201
        track = tracking.json()
        assert track == {
            "id": track["id"],
            "status": "active",
            "seed_run_id": run_id,
            "result_checksum_sha256": track["result_checksum_sha256"],
            "origin_session": sessions[-1],
            "strategy_session": sessions[-1],
        }
        assert "release" not in str(track).lower()
        assert "generation" not in str(track).lower()
        assert client.get("/api/daily-tracks").json()["items"] == [track]
        track_detail = client.get(f"/api/daily-tracks/{track['id']}")
        assert track_detail.status_code == 200
        assert track_detail.json()["origin"]["terminal_account"] == terminal_account
        activation = _stored_tracking_activation(settings, track["id"])
        assert activation["origin_session"].isoformat() == sessions[-1]
        assert activation["current_checkpoint_session"].isoformat() == sessions[-1]
        assert activation["checkpoint_count"] == 1
        assert activation["progression_count"] == 0
        assert activation["terminal_strategy_state"]["session"] == sessions[-1]
        replay = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "attempt-start-head-track"},
        )
        assert replay.status_code == 201
        assert replay.json() == track

        extended_sessions = (*sessions, "2026-08-06", "2026-08-07")
        head_c = _publish_head(
            settings,
            sessions=extended_sessions,
            price_offset=2,
            expected_manifest=head_b,
        )
        claimed = Event()
        continue_advance = Event()
        runtime = client.app.state.core_runtime

        def tracking_barrier(stage: str, _track_id: str, _target: str) -> None:
            if stage == "claimed":
                claimed.set()
                assert continue_advance.wait(timeout=10)

        processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(
                runtime.database,
                settings.data_mount,
            ),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            progress=tracking_barrier,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(processor.process_next)
            assert claimed.wait(timeout=10)
            latest_sessions = (*extended_sessions, "2026-08-10")
            head_d = _publish_head(
                settings,
                sessions=latest_sessions,
                price_offset=3,
                expected_manifest=head_c,
            )
            continue_advance.set()
            assert future.result(timeout=20) is True

        pinned_detail = client.get(f"/api/daily-tracks/{track['id']}").json()
        assert pinned_detail["strategy_session"] == extended_sessions[-1]
        assert pinned_detail["data_through_session"] == latest_sessions[-1]
        assert pinned_detail["lag_sessions"] == 1

        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr

        caught_up = client.get(f"/api/daily-tracks/{track['id']}")
        assert caught_up.status_code == 200
        caught_up_detail = caught_up.json()
        assert caught_up_detail["strategy_session"] == latest_sessions[-1]
        assert caught_up_detail["data_through_session"] == latest_sessions[-1]
        assert caught_up_detail["lag_sessions"] == 0
        assert [
            observation["session"] for observation in caught_up_detail["strategy"]["observations"]
        ] == list(latest_sessions)
        assert "release" not in caught_up.text.lower()
        assert "generation" not in caught_up.text.lower()
        progressed = _stored_tracking_activation(settings, track["id"])
        assert progressed["current_checkpoint_session"].isoformat() == (latest_sessions[-1])
        assert progressed["checkpoint_count"] == 3
        assert progressed["progression_count"] == 2
        assert progressed["active_pin_count"] == 0
        proof = runtime.daily_tracks.verify_persisted_equivalence(track["id"])
        assert proof.status == "equivalent"
        assert proof.head_session == latest_sessions[-1]
        assert proof.session_sequence == (
            sessions[-1],
            *extended_sessions[len(sessions) :],
            latest_sessions[-1],
        )
        assert proof.checkpoint_count == 2
        assert len(proof.checkpoint_evidence_sha256s) == 2
        assert "release" not in repr(proof).lower()
        assert "generation" not in repr(proof).lower()
        origin = TrackingOrigin.model_validate(progressed["origin"])
        store = MountedGenerationStore(settings.data_mount)
        canonical_c = open_complete_refresh_basis(store, head_c)
        research_data_c = _research_data(canonical_c)
        calendar_c = research_sessions(research_data_c)
        prior_c = slice_research_sessions(research_data_c, calendar_c[: len(sessions)])
        reference_origin = restore_tracking_origin(
            origin,
            activation["terminal_strategy_state"],
            prior_c,
        )
        reference_c = advance(
            AdvanceInput(
                prior_state=reference_origin,
                target_research_data=research_data_c,
                appended_sessions=list(extended_sessions[len(sessions) :]),
                continuation=advance_continuation(
                    run_input=reference_origin.run_input_with_research_data(prior_c),
                    prior_continuation=empty_continuation(),
                    target_research_data=prior_c,
                    appended_sessions=calendar_c[: len(sessions)],
                ),
                calculation_scope="forward_tracking",
            )
        )
        checkpoint_c = project_tracking_checkpoint(
            reference_c,
            retained_strategy_sessions=[sessions[-1], *extended_sessions[len(sessions) :]],
        )
        canonical_d = open_complete_refresh_basis(store, head_d)
        research_data_d = _research_data(canonical_d)
        calendar_d = research_sessions(research_data_d)
        prior_d = slice_research_sessions(research_data_d, calendar_d[:-1])
        restored_c = restore_tracking_checkpoint(checkpoint_c, research_data=prior_d)
        reference_d = advance(
            AdvanceInput(
                prior_state=restored_c,
                target_research_data=research_data_d,
                appended_sessions=[latest_sessions[-1]],
                continuation=advance_continuation(
                    run_input=restored_c.run_input_with_research_data(prior_d),
                    prior_continuation=empty_continuation(),
                    target_research_data=prior_d,
                    appended_sessions=calendar_d[:-1],
                ),
                calculation_scope="forward_tracking",
            )
        )
        assert progressed["terminal_strategy_state"] == terminal_strategy_state(reference_d)

        _publish_head(
            settings,
            sessions=(*latest_sessions, "2026-08-11"),
            price_offset=4,
            expected_manifest=head_d,
        )
        stop_claimed = Event()
        finish_stopped_advance = Event()
        stop_events: list[dict[str, object]] = []
        cooperative_stop_requested = Event()
        allow_cooperative_stop = Event()
        publication_count_before_stop = _publication_manifest_count(settings)

        def stop_barrier(stage: str, _track_id: str, _target: str) -> None:
            if stage == "prepared":
                stop_claimed.set()
                assert finish_stopped_advance.wait(timeout=10)

        stopped_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            progress=stop_barrier,
        )

        def capture_stop_event(event: dict[str, object]) -> None:
            stop_events.append(event)
            if event.get("event") == "tracking_execution_child_stop_requested":
                cooperative_stop_requested.set()
                assert allow_cooperative_stop.wait(timeout=10)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                stopped_processor.process_next,
                on_execution_event=capture_stop_event,
            )
            assert stop_claimed.wait(timeout=10)
            stopped = client.post(
                f"/api/daily-tracks/{track['id']}/stop",
                json={"request_id": "attempt-start-head-track-stop"},
            )
            assert stopped.status_code == 202
            assert stopped.json()["status"] == "stopping"
            assert cooperative_stop_requested.wait(timeout=5)
            stopped_while_child_live = _stored_tracking_activation(
                settings,
                track["id"],
            )
            assert stopped_while_child_live["active_pin_count"] == 1
            stopping_detail = client.get(f"/api/daily-tracks/{track['id']}").json()
            assert stopping_detail["status"] == "stopping"
            assert stopping_detail["progress"]["phase"] == "stopping"
            assert _publication_manifest_count(settings) == publication_count_before_stop
            allow_cooperative_stop.set()
            poll = Event()
            deadline = monotonic() + 5
            while monotonic() < deadline:
                if client.get(f"/api/daily-tracks/{track['id']}").json()["status"] == "stopped":
                    break
                poll.wait(0.01)
            else:
                raise AssertionError("cooperative Stop was not confirmed in five seconds")
            finish_stopped_advance.set()
            assert future.result(timeout=20) is True
        assert any(
            event.get("event") == "tracking_execution_child_exited"
            for event in stop_events
        )
        assert not any(
            event.get("event") == "tracking_execution_child_termination_requested"
            for event in stop_events
        )
        terminal_detail = client.get(f"/api/daily-tracks/{track['id']}").json()
        assert terminal_detail["status"] == "stopped"
        assert terminal_detail["progress"]["phase"] == "stopped"
        stopped_replay = client.post(
            f"/api/daily-tracks/{track['id']}/stop",
            json={"request_id": "attempt-start-head-track-stop"},
        )
        assert stopped_replay.status_code == 202
        assert stopped_replay.json() == stopped.json()
        assert runtime.daily_tracks.process_next() is False
        stopped_state = _stored_tracking_activation(settings, track["id"])
        assert stopped_state["current_checkpoint_session"].isoformat() == (latest_sessions[-1])
        assert stopped_state["checkpoint_count"] == 3
        assert stopped_state["cancelled_progression_count"] == 1
        assert stopped_state["cancelled_attempt_count"] == 1
        assert stopped_state["active_pin_count"] == 0
        assert _publication_manifest_count(settings) == publication_count_before_stop

        forced_run = client.post(
            "/api/research-runs",
            json=_run_command("forced-tracking-stop"),
        )
        assert forced_run.status_code == 202
        assert runtime.research_runs.process_next() is True
        forced_track = client.post(
            f"/api/research-runs/{forced_run.json()['id']}/daily-tracks",
            json={"request_id": "forced-tracking-stop-activation"},
        )
        assert forced_track.status_code == 201
        forced_track_id = str(forced_track.json()["id"])
        forced_prepared = Event()
        release_forced = Event()
        forced_events: list[dict[str, object]] = []

        def forced_stop_barrier(stage: str, _track_id: str, _target: str) -> None:
            if stage == "prepared":
                forced_prepared.set()
                assert release_forced.wait(timeout=10)

        def force_child_to_ignore_cooperative_stop(event: dict[str, object]) -> None:
            forced_events.append(event)
            if event.get("event") == "tracking_execution_result_received":
                os.kill(int(event["child_pid"]), signal.SIGSTOP)

        forced_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            progress=forced_stop_barrier,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                forced_processor.process_next,
                on_execution_event=force_child_to_ignore_cooperative_stop,
            )
            assert forced_prepared.wait(timeout=10)
            stop_started = monotonic()
            forced_stop = client.post(
                f"/api/daily-tracks/{forced_track_id}/stop",
                json={"request_id": "forced-tracking-stop-command"},
            )
            assert forced_stop.status_code == 202
            assert forced_stop.json()["status"] == "stopping"
            poll = Event()
            deadline = stop_started + 5
            while monotonic() < deadline:
                if client.get(f"/api/daily-tracks/{forced_track_id}").json()[
                    "status"
                ] == "stopped":
                    break
                poll.wait(0.01)
            else:
                raise AssertionError("healthy supervisor did not confirm Stop in five seconds")
            assert _stored_tracking_activation(settings, forced_track_id)[
                "active_pin_count"
            ] == 0
            assert monotonic() - stop_started < 5
            release_forced.set()
            assert future.result(timeout=5) is True
        assert any(
            event.get("event") == "tracking_execution_child_termination_requested"
            for event in forced_events
        )
        assert client.get(f"/api/daily-tracks/{forced_track_id}").json()[
            "status"
        ] == "stopped"
        assert _stored_tracking_activation(settings, forced_track_id)["active_pin_count"] == 0

    with TestClient(create_app(settings)) as restarted:
        reopened = restarted.get(f"/api/research-runs/{run_id}")
        assert reopened.status_code == 200
        assert reopened.json() == public_run
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert _stored_execution(settings, run_id)["attempt_count"] == 1
        reopened_track = restarted.get(f"/api/daily-tracks/{track['id']}")
        assert reopened_track.status_code == 200
        assert "release" not in reopened_track.text.lower()
        assert "generation" not in reopened_track.text.lower()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_research_delete_preserves_track_until_explicit_stop_and_delete(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("delete-preserves-track-seed"),
        )
        assert accepted.status_code == 202
        run_id = str(accepted.json()["id"])
        runtime = client.app.state.core_runtime
        assert runtime.research_runs.process_next() is True
        stored_run = _stored_execution(settings, run_id)
        result_manifest = str(stored_run["result_manifest_sha256"])

        tracking = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "delete-preserves-track-activation"},
        )
        assert tracking.status_code == 201
        track_id = str(tracking.json()["id"])
        assert client.delete(f"/api/daily-tracks/{track_id}").status_code == 409

        assert client.delete(f"/api/research-runs/{run_id}").status_code == 204
        assert client.delete(f"/api/research-runs/{run_id}").status_code == 404
        assert client.get(f"/api/research-runs/{run_id}").status_code == 404
        surviving = client.get(f"/api/daily-tracks/{track_id}")
        assert surviving.status_code == 200
        assert surviving.json()["origin"]["seed_run_id"] == run_id
        assert surviving.json()["origin"]["seed_research_available"] is False
        assert surviving.json()["strategy_session"] == seed_sessions[-1]
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                "SELECT 1 FROM publication.manifests WHERE sha256 = %s",
                (result_manifest,),
            ).fetchone() == {"?column?": 1}
            research_counts = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM research_runs.runs WHERE id = %s) AS runs,
                    (SELECT count(*) FROM research_runs.attempts WHERE run_id = %s) AS attempts,
                    (SELECT count(*) FROM research_runs.admission_requests
                     WHERE run_id = %s) AS admissions,
                    (SELECT count(*) FROM research_runs.start_tracking_receipts
                     WHERE seed_run_id = %s) AS tracking_receipts
                """,
                (run_id, run_id, run_id, run_id),
            ).fetchone()
        assert research_counts == {
            "runs": 0,
            "attempts": 0,
            "admissions": 0,
            "tracking_receipts": 0,
        }

        advanced_sessions = (*seed_sessions, "2026-08-06", "2026-08-07")
        advanced_head = _publish_head(
            settings,
            sessions=advanced_sessions,
            price_offset=1,
            expected_manifest=seed_head,
        )
        worker_cache_root = tmp_path / "separate-worker-cache"
        worker_tracks = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            working_cache_root=worker_cache_root,
        )
        assert worker_tracks.process_next() is True
        worker_cache_paths = list(worker_cache_root.glob("*.json"))
        assert len(worker_cache_paths) == 1
        advanced = client.get(f"/api/daily-tracks/{track_id}")
        assert advanced.status_code == 200
        assert advanced.json()["strategy_session"] == advanced_sessions[-1]
        assert advanced.json()["origin"]["seed_research_available"] is False

        with runtime.database.transaction() as transaction:
            checkpoint_manifests = {
                str(row["manifest_sha256"])
                for row in transaction.execute(
                    """
                    SELECT manifest_sha256
                    FROM daily_tracks.session_checkpoints
                    WHERE track_id = %s
                    """,
                    (track_id,),
                ).fetchall()
            }
            owned_manifests = checkpoint_manifests | {result_manifest}
            owned_objects = {
                str(row["object_sha256"])
                for row in transaction.execute(
                    """
                    SELECT object_sha256
                    FROM publication.manifest_objects
                    WHERE manifest_sha256 = ANY(%s)
                    """,
                    (list(owned_manifests),),
                ).fetchall()
            }
        assert checkpoint_manifests
        assert owned_objects

        stopped = client.post(
            f"/api/daily-tracks/{track_id}/stop",
            json={"request_id": "delete-preserves-track-stop"},
        )
        assert stopped.status_code == 202
        assert stopped.json()["status"] == "stopped"
        assert worker_cache_paths[0].is_file()
        assert worker_tracks.reconcile_working_cache() == 1
        assert not worker_cache_paths[0].exists()
        stopped_state = _stored_tracking_activation(settings, track_id)
        assert stopped_state["current_checkpoint_session"].isoformat() == advanced_sessions[-1]
        assert {
            str(row["manifest_sha256"])
            for row in _tracking_checkpoint_history(settings, track_id)
        } == checkpoint_manifests
        assert client.delete(f"/api/daily-tracks/{track_id}").status_code == 204
        assert client.delete(f"/api/daily-tracks/{track_id}").status_code == 404
        assert client.get(f"/api/daily-tracks/{track_id}").status_code == 404

        with runtime.database.transaction() as transaction:
            track_counts = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM daily_tracks.tracks WHERE id = %s) AS tracks,
                    (SELECT count(*) FROM daily_tracks.session_tracking_states
                     WHERE track_id = %s) AS states,
                    (SELECT count(*) FROM daily_tracks.session_checkpoints
                     WHERE track_id = %s) AS checkpoints,
                    (SELECT count(*) FROM daily_tracks.session_progressions
                     WHERE track_id = %s) AS progressions,
                    (SELECT count(*) FROM daily_tracks.session_progression_attempts
                     WHERE track_id = %s) AS attempts,
                    (SELECT count(*) FROM daily_tracks.stop_receipts
                     WHERE track_id = %s) AS stop_receipts,
                    (SELECT count(*) FROM daily_tracks.retry_receipts
                     WHERE track_id = %s) AS retry_receipts,
                    (SELECT count(*) FROM publication.manifests
                     WHERE sha256 = ANY(%s)) AS owned_manifests,
                    (SELECT count(*) FROM publication.objects
                     WHERE sha256 = ANY(%s)) AS owned_objects,
                    (SELECT count(*) FROM publication.object_deletions) AS pending_deletions
                """,
                (
                    track_id,
                    track_id,
                    track_id,
                    track_id,
                    track_id,
                    track_id,
                    track_id,
                    list(owned_manifests),
                    list(owned_objects),
                ),
            ).fetchone()
        assert track_counts == {
            "tracks": 0,
            "states": 0,
            "checkpoints": 0,
            "progressions": 0,
            "attempts": 0,
            "stop_receipts": 0,
            "retry_receipts": 0,
            "owned_manifests": 0,
            "owned_objects": 0,
            "pending_deletions": 0,
        }
        current_head = DatasetLifecycle(
            runtime.database,
            settings.data_mount,
        ).current_pointer()
        assert current_head is not None
        assert current_head.generation_manifest_sha256 == advanced_head
        assert (
            MountedGenerationStore(settings.data_mount)
            .validate_generation(advanced_head)
            .manifest_sha256
            == advanced_head
        )
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )
        remaining_keys = {
            str(item["Key"])
            for item in s3.list_objects_v2(
                Bucket=settings.s3_bucket,
                Prefix="publication/v1/sha256/",
            ).get("Contents", [])
        }
        assert (
            not {f"publication/v1/sha256/{digest[:2]}/{digest}" for digest in owned_objects}
            & remaining_keys
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_delete_races_linearize_with_cancel_and_stop(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(
        settings,
        sessions=("2026-08-03", "2026-08-04", "2026-08-05"),
        price_offset=0,
    )

    with TestClient(create_app(settings)) as client:
        queued = client.post(
            "/api/research-runs",
            json=_run_command("delete-cancel-race"),
        )
        run_id = str(queued.json()["id"])
        assert client.delete(f"/api/research-runs/{run_id}").status_code == 409
        run_barrier = Barrier(2)

        def cancel_run():
            run_barrier.wait(timeout=10)
            return client.post(
                f"/api/research-runs/{run_id}/cancel",
                json={"request_id": "delete-cancel-race-cancel"},
            )

        def delete_run():
            run_barrier.wait(timeout=10)
            return client.delete(f"/api/research-runs/{run_id}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            cancel_future = executor.submit(cancel_run)
            delete_future = executor.submit(delete_run)
            cancel_response = cancel_future.result(timeout=30)
            delete_response = delete_future.result(timeout=30)
        assert cancel_response.status_code in {200, 404}
        assert delete_response.status_code in {204, 409}
        remaining_run = client.get(f"/api/research-runs/{run_id}")
        if remaining_run.status_code == 200:
            assert remaining_run.json()["status"] == "cancelled"
            assert client.delete(f"/api/research-runs/{run_id}").status_code == 204
        else:
            assert remaining_run.status_code == 404
        assert client.delete(f"/api/research-runs/{run_id}").status_code == 404

        seed = client.post(
            "/api/research-runs",
            json=_run_command("delete-stop-race"),
        )
        seed_run_id = str(seed.json()["id"])
        runtime = client.app.state.core_runtime
        assert runtime.research_runs.process_next() is True
        tracking = client.post(
            f"/api/research-runs/{seed_run_id}/daily-tracks",
            json={"request_id": "delete-stop-race-activation"},
        )
        track_id = str(tracking.json()["id"])
        track_barrier = Barrier(2)

        def stop_track():
            track_barrier.wait(timeout=10)
            return client.post(
                f"/api/daily-tracks/{track_id}/stop",
                json={"request_id": "delete-stop-race-stop"},
            )

        def delete_track():
            track_barrier.wait(timeout=10)
            return client.delete(f"/api/daily-tracks/{track_id}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            stop_future = executor.submit(stop_track)
            delete_future = executor.submit(delete_track)
            stop_response = stop_future.result(timeout=30)
            delete_response = delete_future.result(timeout=30)
        assert stop_response.status_code in {202, 404}
        assert delete_response.status_code in {204, 409}
        remaining_track = client.get(f"/api/daily-tracks/{track_id}")
        if remaining_track.status_code == 200:
            assert remaining_track.json()["status"] == "stopped"
            assert client.delete(f"/api/daily-tracks/{track_id}").status_code == 204
        else:
            assert remaining_track.status_code == 404
        assert client.delete(f"/api/daily-tracks/{track_id}").status_code == 404


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_current_data_track_limit_releases_capacity_after_stop(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_head = _publish_head(
        settings,
        sessions=("2026-08-03", "2026-08-04", "2026-08-05"),
        price_offset=0,
    )

    with TestClient(create_app(settings)) as client:
        run_ids: list[str] = []
        for index in range(11):
            accepted = client.post(
                "/api/research-runs",
                json=_run_command(f"current-track-capacity-{index}"),
            )
            assert accepted.status_code == 202
            run_ids.append(str(accepted.json()["id"]))
        # Keep one real Worker process boundary; the remaining capacity seeds still
        # execute through the production service, Kernel, PostgreSQL, and RustFS.
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        runtime = client.app.state.core_runtime
        for _ in run_ids[1:]:
            assert runtime.research_runs.process_next() is True
        assert runtime.research_runs.process_next() is False
        for run_id in run_ids:
            assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "succeeded"

        same_seed_barrier = Barrier(4)

        def start_same_seed(index: int):
            same_seed_barrier.wait(timeout=10)
            return client.post(
                f"/api/research-runs/{run_ids[0]}/daily-tracks",
                json={"request_id": f"current-track-same-seed-{index}"},
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            same_seed_futures = [executor.submit(start_same_seed, index) for index in range(4)]
            same_seed_responses = [future.result(timeout=30) for future in same_seed_futures]
        assert [response.status_code for response in same_seed_responses] == [201] * 4
        first_track = same_seed_responses[0].json()
        assert [response.json() for response in same_seed_responses] == [first_track] * 4
        assert client.get("/api/daily-tracks").json()["items"] == [first_track]

        tracks: list[dict[str, object]] = [first_track]
        for index, run_id in enumerate(run_ids[1:9], start=1):
            started = client.post(
                f"/api/research-runs/{run_id}/daily-tracks",
                json={"request_id": f"current-track-capacity-start-{index}"},
            )
            assert started.status_code == 201
            tracks.append(started.json())
        assert len(client.get("/api/daily-tracks").json()["items"]) == 9

        capacity_barrier = Barrier(2)

        def race_capacity(index: int):
            capacity_barrier.wait(timeout=10)
            return client.post(
                f"/api/research-runs/{run_ids[9 + index]}/daily-tracks",
                json={"request_id": f"current-track-capacity-race-{index}"},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            capacity_futures = [executor.submit(race_capacity, index) for index in range(2)]
            capacity_responses = [future.result(timeout=30) for future in capacity_futures]
        assert sorted(response.status_code for response in capacity_responses) == [
            201,
            409,
        ]
        rejected_index = next(
            index
            for index, response in enumerate(capacity_responses)
            if response.status_code == 409
        )
        rejected_run_id = run_ids[9 + rejected_index]
        assert (
            len(
                [
                    item
                    for item in client.get("/api/daily-tracks").json()["items"]
                    if item["status"] in {"active", "blocked"}
                ]
            )
            == 10
        )

        _publish_head(
            settings,
            sessions=("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"),
            price_offset=1,
            expected_manifest=seed_head,
        )
        stopping_prepared = Event()
        release_stopping = Event()
        stopping_child_live = Event()
        release_stopping_child = Event()

        def hold_stopping_track(stage: str, track_id: str, _target: str) -> None:
            if stage == "prepared":
                assert track_id == tracks[0]["id"]
                stopping_prepared.set()
                assert release_stopping.wait(timeout=10)

        stopping_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            progress=hold_stopping_track,
        )

        def hold_stopping_child(event: dict[str, object]) -> None:
            if event.get("event") == "tracking_execution_child_stop_requested":
                stopping_child_live.set()
                assert release_stopping_child.wait(timeout=10)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                stopping_processor.process_next,
                on_execution_event=hold_stopping_child,
            )
            assert stopping_prepared.wait(timeout=10)
            stopped = client.post(
                f"/api/daily-tracks/{tracks[0]['id']}/stop",
                json={"request_id": "current-track-capacity-stop"},
            )
            assert stopped.status_code == 202
            assert stopped.json()["status"] == "stopping"
            assert stopping_child_live.wait(timeout=5)
            assert client.get(f"/api/daily-tracks/{tracks[0]['id']}").json()[
                "status"
            ] == "stopping"
            still_full = client.post(
                f"/api/research-runs/{rejected_run_id}/daily-tracks",
                json={"request_id": "current-track-capacity-while-stopping"},
            )
            assert still_full.status_code == 409
            release_stopping_child.set()
            release_stopping.set()
            assert future.result(timeout=5) is True
        assert client.get(f"/api/daily-tracks/{tracks[0]['id']}").json()[
            "status"
        ] == "stopped"
        admitted = client.post(
            f"/api/research-runs/{rejected_run_id}/daily-tracks",
            json={"request_id": "current-track-capacity-after-stop"},
        )
        assert admitted.status_code == 201
        final_tracks = client.get("/api/daily-tracks").json()["items"]
        assert len(final_tracks) == 11
        assert (
            len(
                [
                    item
                    for item in final_tracks
                    if item["status"] in {"active", "blocked", "stopping"}
                ]
            )
            == 10
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_live_tracking_owner_renews_lease_and_blocks_duplicate_claim(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)
    entered_kernel = Event()
    release_kernel = Event()

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("tracking-live-owner"),
        )
        assert accepted.status_code == 202
        run_id = str(accepted.json()["id"])
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        tracking = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "tracking-live-owner-activate"},
        )
        assert tracking.status_code == 201
        track_id = str(tracking.json()["id"])
        _publish_head(
            settings,
            sessions=(*seed_sessions, "2026-08-06"),
            price_offset=1,
            expected_manifest=seed_head,
        )
        runtime = client.app.state.core_runtime

        def block_started_child(event: dict[str, object]) -> None:
            if (
                event["event"] != "tracking_execution_progress"
                or event.get("phase") != "calculating"
            ):
                return
            entered_kernel.set()
            if not release_kernel.wait(timeout=10):
                raise TimeoutError("live-owner child was not released")

        owner = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            lease_seconds=0.4,
            heartbeat_seconds=0.05,
        )
        duplicate = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                owner.process_next,
                on_execution_event=block_started_child,
            )
            assert entered_kernel.wait(timeout=10)
            live = client.get(f"/api/daily-tracks/{track_id}").json()
            assert live["progress"] == {
                "head_session": seed_sessions[-1],
                "lag_sessions": 1,
                "phase": "calculating",
                "target_start_session": "2026-08-06",
                "target_end_session": "2026-08-06",
                "target_session_count": 1,
                "completed_target_sessions": 0,
                "current_session": "2026-08-06",
                "cycle_attempt": 1,
                "cycle_attempt_limit": 3,
                "retry_wait": False,
                "next_attempt_eligible_at": None,
            }
            initial_timing = _live_tracking_attempt_timing(settings, track_id)
            try:
                renewed_timing = _wait_for_tracking_lease_renewal(
                    settings,
                    track_id,
                    after_heartbeat=initial_timing["heartbeat_at"],
                )
                assert renewed_timing["lease_expires_at"] > initial_timing["lease_expires_at"]
                assert duplicate.process_next() is False
            finally:
                release_kernel.set()
            assert future.result(timeout=20) is True

        detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert detail["strategy_session"] == "2026-08-06"
        stored = _stored_tracking_activation(settings, track_id)
        assert stored["progression_count"] == 1
        assert stored["checkpoint_count"] == 2
        assert stored["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_daily_track_recovers_from_its_last_authoritative_checkpoint(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        tracks: list[dict[str, object]] = []
        for index in range(2):
            accepted = client.post(
                "/api/research-runs",
                json=_run_command(f"track-recovery-seed-{index}"),
            )
            assert accepted.status_code == 202
            run_id = accepted.json()["id"]
            completed = _run_worker_once(settings)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            tracking = client.post(
                f"/api/research-runs/{run_id}/daily-tracks",
                json={"request_id": f"track-recovery-activate-{index}"},
            )
            assert tracking.status_code == 201
            tracks.append(tracking.json())

        first_track, control_track = tracks
        catch_up_sessions = (*seed_sessions, "2026-08-06", "2026-08-07", "2026-08-10")
        catch_up_head = _publish_head(
            settings,
            sessions=catch_up_sessions,
            price_offset=1,
            expected_manifest=seed_head,
        )
        runtime = client.app.state.core_runtime

        failing = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )

        def kill_tracking_child(event: dict[str, object]) -> None:
            if event["event"] == "tracking_execution_child_started":
                os.kill(int(event["child_pid"]), 9)

        with pytest.raises(DailyTrackProgressionFailed):
            failing.process_next(on_execution_event=kill_tracking_child)

        blocked = client.get(f"/api/daily-tracks/{first_track['id']}")
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "blocked"
        assert blocked.json()["strategy_session"] == seed_sessions[-1]
        assert blocked.json()["blocked_reason"] == (
            "DailyTrack could not process the current dataset."
        )
        assert "injected" not in blocked.text
        failed_state = _stored_tracking_activation(settings, str(first_track["id"]))
        assert failed_state["current_checkpoint_session"].isoformat() == (seed_sessions[-1])
        assert failed_state["checkpoint_count"] == 1
        assert failed_state["blocked_progression_count"] == 1
        assert failed_state["failed_attempt_count"] == 1
        assert failed_state["active_pin_count"] == 0

        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        control = client.get(f"/api/daily-tracks/{control_track['id']}").json()
        assert control["strategy_session"] == catch_up_sessions[-1]
        assert control["lag_sessions"] == 0
        assert client.get(f"/api/daily-tracks/{first_track['id']}").json()["status"] == "blocked"

    recovered_sessions = (*catch_up_sessions, "2026-08-11")
    recovered_head = _publish_head(
        settings,
        sessions=recovered_sessions,
        price_offset=2,
        expected_manifest=catch_up_head,
    )
    with TestClient(create_app(settings)) as restarted:
        retry = restarted.post(
            f"/api/daily-tracks/{first_track['id']}/retry",
            json={"request_id": "track-recovery-retry"},
        )
        assert retry.status_code == 202
        assert retry.json()["status"] == "active"
        retry_replay = restarted.post(
            f"/api/daily-tracks/{first_track['id']}/retry",
            json={"request_id": "track-recovery-retry"},
        )
        assert retry_replay.status_code == 202
        assert retry_replay.json() == retry.json()
        retry_conflict = restarted.post(
            f"/api/daily-tracks/{control_track['id']}/retry",
            json={"request_id": "track-recovery-retry"},
        )
        assert retry_conflict.status_code == 409
        assert retry_conflict.json() == {"detail": "DailyTrack Retry request_id conflicts"}
        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr

        fair_control = restarted.get(
            f"/api/daily-tracks/{control_track['id']}"
        ).json()
        assert fair_control["strategy_session"] == recovered_sessions[-1]
        assert restarted.get(f"/api/daily-tracks/{first_track['id']}").json()[
            "strategy_session"
        ] == seed_sessions[-1]
        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr

        frozen_target = restarted.get(f"/api/daily-tracks/{first_track['id']}").json()
        assert frozen_target["strategy_session"] == catch_up_sessions[-1]
        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr

        recovered = restarted.get(f"/api/daily-tracks/{first_track['id']}")
        assert recovered.status_code == 200
        detail = recovered.json()
        assert detail["status"] == "active"
        assert detail["strategy_session"] == recovered_sessions[-1]
        assert detail["data_through_session"] == recovered_sessions[-1]
        assert detail["lag_sessions"] == 0
        observation_sessions = [
            observation["session"] for observation in detail["strategy"]["observations"]
        ]
        assert observation_sessions == list(recovered_sessions)
        assert len(observation_sessions) == len(set(observation_sessions))
        recovered_state = _stored_tracking_activation(
            settings,
            str(first_track["id"]),
        )
        assert recovered_state["checkpoint_count"] == 3
        assert recovered_state["cancelled_progression_count"] == 0
        assert recovered_state["succeeded_progression_count"] == 2
        assert recovered_state["active_pin_count"] == 0
        recovered_canonical = open_complete_refresh_basis(
            MountedGenerationStore(settings.data_mount), recovered_head
        )
        recovered_research_data = _research_data(recovered_canonical)
        recovered_calendar = research_sessions(recovered_research_data)
        recovery_prior_data = slice_research_sessions(
            recovered_research_data,
            recovered_calendar[: len(seed_sessions)],
        )
        recovery_origin = restore_tracking_origin(
            TrackingOrigin.model_validate(recovered_state["origin"]),
            failed_state["terminal_strategy_state"],
            recovery_prior_data,
        )
        recovery_reference = advance(
            AdvanceInput(
                prior_state=recovery_origin,
                target_research_data=recovered_research_data,
                appended_sessions=list(recovered_sessions[len(seed_sessions) :]),
                continuation=advance_continuation(
                    run_input=recovery_origin.run_input_with_research_data(recovery_prior_data),
                    prior_continuation=empty_continuation(),
                    target_research_data=recovery_prior_data,
                    appended_sessions=recovered_calendar[: len(seed_sessions)],
                ),
                calculation_scope="forward_tracking",
            )
        )
        assert recovered_state["terminal_strategy_state"] == terminal_strategy_state(
            recovery_reference
        )

        stopped_control = restarted.post(
            f"/api/daily-tracks/{control_track['id']}/stop",
            json={"request_id": "track-recovery-control-stop"},
        )
        assert stopped_control.status_code == 202

        stale_sessions = (*recovered_sessions, "2026-08-12")
        stale_head = _publish_head(
            settings,
            sessions=stale_sessions,
            price_offset=3,
            expected_manifest=recovered_head,
        )
        stale_claimed = Event()
        release_stale_worker = Event()
        runtime = restarted.app.state.core_runtime

        def stale_barrier(event: dict[str, object]) -> None:
            if event["event"] == "tracking_execution_result_received":
                stale_claimed.set()
                assert release_stale_worker.wait(timeout=10)

        stale_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            stale_future = executor.submit(
                stale_processor.process_next,
                on_execution_event=stale_barrier,
            )
            assert stale_claimed.wait(timeout=10)
            _expire_current_tracking_attempt(settings, str(first_track["id"]))
            assert runtime.daily_tracks.process_next() is False
            lost = restarted.get(f"/api/daily-tracks/{first_track['id']}").json()
            assert lost["status"] == "active"
            assert lost["strategy_session"] == recovered_sessions[-1]
            lost_state = _stored_tracking_activation(
                settings,
                str(first_track["id"]),
            )
            assert lost_state["current_checkpoint_session"].isoformat() == (recovered_sessions[-1])
            assert lost_state["checkpoint_count"] == 3
            assert lost_state["blocked_progression_count"] == 0
            assert lost_state["latest_attempt_failure_reason"] is None
            assert lost_state["active_pin_count"] == 1
            release_stale_worker.set()
            assert stale_future.result(timeout=20) is True

        final = restarted.get(f"/api/daily-tracks/{first_track['id']}").json()
        assert final["status"] == "active"
        assert final["strategy_session"] == stale_sessions[-1]
        assert [
            observation["session"] for observation in final["strategy"]["observations"]
        ] == list(stale_sessions)

        stopped = restarted.post(
            f"/api/daily-tracks/{first_track['id']}/stop",
            json={"request_id": "track-recovery-cache-stop"},
        )
        assert stopped.status_code == 202

        cache_run_ids: list[str] = []
        for index in range(2):
            accepted = restarted.post(
                "/api/research-runs",
                json=_run_command(f"track-recovery-cache-seed-{index}"),
            )
            assert accepted.status_code == 202
            cache_run_ids.append(str(accepted.json()["id"]))
        for _run_id in cache_run_ids:
            completed = _run_worker_once(settings)
            assert completed.returncode == 0, completed.stdout + completed.stderr
        cache_tracks: list[dict[str, object]] = []
        for index, run_id in enumerate(cache_run_ids):
            tracking = restarted.post(
                f"/api/research-runs/{run_id}/daily-tracks",
                json={"request_id": f"track-recovery-cache-activate-{index}"},
            )
            assert tracking.status_code == 201
            cache_tracks.append(tracking.json())
        first_track, control_track = cache_tracks

        cache_sessions = (*stale_sessions, "2026-08-13")
        cache_head = _publish_head(
            settings,
            sessions=cache_sessions,
            price_offset=4,
            expected_manifest=stale_head,
        )
        cache_root = tmp_path / "current-working-cache"
        intact_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )
        cache_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            working_cache_root=cache_root,
        )
        assert intact_processor.process_next() is True
        assert cache_processor.process_next() is True
        cache_path = next(cache_root.glob("*.json"))
        cache_path.write_text("{", encoding="utf-8")
        cache_sessions = (*cache_sessions, "2026-08-14")
        cache_head = _publish_head(
            settings,
            sessions=cache_sessions,
            price_offset=4,
            expected_manifest=cache_head,
        )
        assert intact_processor.process_next() is True
        assert cache_processor.process_next() is True
        intact_detail = restarted.get(f"/api/daily-tracks/{first_track['id']}").json()
        cache_detail = restarted.get(f"/api/daily-tracks/{control_track['id']}").json()
        assert intact_detail["factor"] == cache_detail["factor"]
        assert intact_detail["strategy"] == cache_detail["strategy"]
        assert cache_detail["strategy_session"] == cache_sessions[-1]
        assert [item["session"] for item in cache_detail["strategy"]["observations"]] == list(
            cache_sessions
        )
        assert cache_path.exists()
        assert cache_path.stat().st_size <= MAX_WORKING_CACHE_BYTES
        intact_checkpoint = _stored_tracking_activation(
            settings,
            str(first_track["id"]),
        )
        damaged_checkpoint = _stored_tracking_activation(
            settings,
            str(control_track["id"]),
        )
        assert _checkpoint_payload(
            runtime.publication,
            intact_checkpoint,
        ) == _checkpoint_payload(runtime.publication, damaged_checkpoint)

        authoritative = _stored_tracking_activation(
            settings,
            str(first_track["id"]),
        )
        checkpoint_manifest = str(authoritative["current_checkpoint_manifest_sha256"])
        _remove_manifest_object_reference(settings, checkpoint_manifest)
        unavailable_sessions = (*cache_sessions, "2026-08-24")
        _publish_head(
            settings,
            sessions=unavailable_sessions,
            price_offset=4,
            expected_manifest=cache_head,
        )
        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        next_track = _run_worker_once(settings, "tracking")
        assert next_track.returncode == 0, next_track.stdout + next_track.stderr
        intact_after_failure = restarted.get(f"/api/daily-tracks/{control_track['id']}").json()
        assert intact_after_failure["strategy_session"] == unavailable_sessions[-1]
        unavailable = restarted.get(f"/api/daily-tracks/{first_track['id']}")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"detail": "DailyTrack detail is unavailable"}
        unavailable_state = _stored_tracking_activation(
            settings,
            str(first_track["id"]),
        )
        assert unavailable_state["track_status"] == "blocked"
        assert unavailable_state["current_checkpoint_session"].isoformat() == (cache_sessions[-1])
        assert unavailable_state["checkpoint_count"] == authoritative["checkpoint_count"]
        assert unavailable_state["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_daily_track_uses_overlap_corrections_only_for_future_sessions(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = (
        "2026-07-31",
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
    )
    seed_canonical = _two_instrument_canonical(seed_sessions, corrected=False)
    seed_head = _publish_canonical_head(
        settings,
        seed_canonical,
        operation_id="forward-only-seed",
    )
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("forward-only-seed-run", formula="ts_mean(close_adj, 2)"),
        )
        assert accepted.status_code == 202
        run_id = str(accepted.json()["id"])
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        tracking = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "forward-only-track"},
        )
        assert tracking.status_code == 201
        track_id = str(tracking.json()["id"])
        runtime = client.app.state.core_runtime

        before_state = _stored_tracking_activation(settings, track_id)
        before_history = _tracking_checkpoint_history(settings, track_id)
        before_payload = _checkpoint_payload(runtime.publication, before_state)
        before_checkpoint_text = json.dumps(before_payload, sort_keys=True)
        assert '"orders"' not in before_checkpoint_text
        assert '"fills"' not in before_checkpoint_text
        before_detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert _position_ids(before_state["terminal_strategy_state"]) == {"equity:000001.SZ"}

        corrected = _two_instrument_canonical(seed_sessions, corrected=True)
        replay_root = tmp_path / "operator-replays"
        replay_root.mkdir()
        correction_outcome = _refresh_via_private_operator(
            settings,
            replay_root=replay_root,
            idempotency_key="forward-only-correction",
            canonical=corrected,
            request_start=seed_sessions[0],
        )
        assert correction_outcome["status"] == "succeeded"
        assert correction_outcome["outcome"] == "published"
        correction_head = DatasetLifecycle(
            runtime.database,
            settings.data_mount,
        ).current_pointer()
        assert correction_head is not None
        assert correction_head.generation_manifest_sha256 != seed_head
        assert correction_head.data_through_session == seed_sessions[-1]

        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert _tracking_checkpoint_history(settings, track_id) == before_history
        unchanged_state = _stored_tracking_activation(settings, track_id)
        assert (
            unchanged_state["current_checkpoint_manifest_sha256"]
            == before_state["current_checkpoint_manifest_sha256"]
        )
        assert _checkpoint_payload(runtime.publication, unchanged_state) == before_payload
        assert client.get(f"/api/daily-tracks/{track_id}").json() == before_detail
        overview = client.get("/api/data")
        assert overview.status_code == 200
        assert set(overview.json()) == {
            "market_coverage",
            "financial_coverage",
            "data_through_session",
            "last_market_refresh_at",
            "last_financial_refresh_at",
            "market_research_readiness",
            "financial_research_readiness",
        }
        assert "correction" not in overview.text.lower()

        impact_sessions = (
            *seed_sessions,
            *_weekday_sessions_after(date.fromisoformat(seed_sessions[-1]), count=3),
        )
        corrected_impact = _two_instrument_canonical(impact_sessions, corrected=True)
        impact_outcome = _refresh_via_private_operator(
            settings,
            replay_root=replay_root,
            idempotency_key="forward-only-impact-sessions",
            canonical=corrected_impact,
            request_start=seed_sessions[0],
        )
        assert impact_outcome["status"] == "succeeded"
        assert impact_outcome["outcome"] == "published"
        completed = _run_worker_once(settings, "tracking")
        assert completed.returncode == 0, completed.stdout + completed.stderr

        impact_detail = client.get(f"/api/daily-tracks/{track_id}")
        assert impact_detail.status_code == 200
        assert impact_detail.json()["strategy_session"] == impact_sessions[-1]
        assert "correction" not in impact_detail.text.lower()
        impact_state = _stored_tracking_activation(settings, track_id)
        assert impact_state["checkpoint_count"] == 2
        impact_history = _tracking_checkpoint_history(settings, track_id)
        assert impact_history[0] == before_history[0]
        impact_payload = _checkpoint_payload(runtime.publication, impact_state)
        impact_checkpoint_text = json.dumps(impact_payload, sort_keys=True)
        assert '"orders"' not in impact_checkpoint_text
        assert '"fills"' not in impact_checkpoint_text
        assert _position_ids(impact_state["terminal_strategy_state"]) == {"equity:000002.SZ"}

        seed_research_data = _research_data(seed_canonical)
        counterfactual_prior = restore_tracking_origin(
            TrackingOrigin.model_validate(before_state["origin"]),
            before_state["terminal_strategy_state"],
            seed_research_data,
        )
        uncorrected_impact = _two_instrument_canonical(
            impact_sessions,
            corrected=False,
        )
        uncorrected_research_data = _research_data(uncorrected_impact)
        counterfactual = advance(
            AdvanceInput(
                prior_state=counterfactual_prior,
                target_research_data=uncorrected_research_data,
                appended_sessions=list(impact_sessions[len(seed_sessions) :]),
                continuation=advance_continuation(
                    run_input=counterfactual_prior.run_input_with_research_data(seed_research_data),
                    prior_continuation=empty_continuation(),
                    target_research_data=seed_research_data,
                    appended_sessions=list(seed_sessions),
                ),
                calculation_scope="forward_tracking",
            )
        )
        assert _position_ids(terminal_strategy_state(counterfactual)) == {"equity:000001.SZ"}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_keeps_its_pinned_generation_when_head_moves(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)
    canonical_a = open_complete_refresh_basis(MountedGenerationStore(settings.data_mount), head_a)
    claimed = Event()
    continue_execution = Event()

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("attempt-pinned-head"),
        )
        run_id = accepted.json()["id"]
        runtime = client.app.state.core_runtime

        def barrier(stage: str, _run_id: str) -> None:
            if stage == "claimed":
                claimed.set()
                assert continue_execution.wait(timeout=5)

        processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(settings.data_mount),
            progress=barrier,
        )
        worker = Thread(target=processor.process_next)
        worker.start()
        assert claimed.wait(timeout=5)
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
        assert client.delete(f"/api/research-runs/{run_id}").status_code == 409
        head_b = _publish_head(
            settings,
            sessions=sessions,
            price_offset=9,
            expected_manifest=head_a,
        )
        continue_execution.set()
        worker.join(timeout=10)
        assert not worker.is_alive()

        stored = _stored_execution(settings, run_id)
        assert stored["attempt_data_generation_id"] == head_a
        assert stored["attempt_data_generation_id"] != head_b
        actual = read_result_bundle(
            runtime.publication.read(
                PublishedRef(
                    manifest_sha256=str(stored["result_manifest_sha256"]),
                    kind="research.result",
                    provenance=stored["result_provenance"],
                )
            )
        )
        expected = build_result_payload(
            run(_kernel_input(canonical_a, sessions=sessions)),
            rebalance_interval=1,
            universe="top300",
        )
        assert actual == expected
        assert stored["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_claim_commits_before_execution_child_receives_generation_request(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)
    child_started = Event()
    allow_child_request = Event()
    worker_errors: list[BaseException] = []

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("claim-before-generation-open"),
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["id"]
        runtime = client.app.state.core_runtime
        processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(settings.data_mount),
        )

        def process_one() -> None:
            try:

                def hold_before_request(event: dict[str, object]) -> None:
                    if event["event"] == "research_execution_child_started":
                        child_started.set()
                        assert allow_child_request.wait(timeout=10)

                processor.process_next(on_execution_event=hold_before_request)
            except BaseException as error:  # pragma: no cover - asserted below
                worker_errors.append(error)

        worker = Thread(target=process_one)
        worker.start()
        try:
            assert child_started.wait(timeout=5)
            status_before_child_request = client.get(f"/api/research-runs/{run_id}").json()[
                "status"
            ]
        finally:
            allow_child_request.set()
            worker.join(timeout=15)

        assert not worker.is_alive()
        assert worker_errors == []
        assert status_before_child_request == "running"
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "succeeded"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_orphaned_research_child_exits_without_mutating_product_state(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    generation_id = _publish_head(
        settings,
        sessions=("2026-08-03", "2026-08-04", "2026-08-05"),
        price_offset=0,
    )

    with TestClient(create_app(settings)) as client:
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("orphaned-research-child"),
        ).json()["id"]
        runtime = client.app.state.core_runtime
        with runtime.database.transaction() as transaction:
            immutable_input = transaction.execute(
                "SELECT immutable_input FROM research_runs.runs WHERE id = %s",
                (run_id,),
            ).fetchone()["immutable_input"]
        publication_count = _publication_manifest_count(settings)
        child_environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
        child = subprocess.Popen(
            [sys.executable, "-m", "thesistrace.entrypoints.research_child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_environment,
        )
        assert child.stdin is not None
        child.stdin.write(
            json.dumps(
                {
                    "schema_version": "research-child-request-v1",
                    "data_mount": str(settings.data_mount),
                    "data_generation_id": generation_id,
                    "immutable_input": immutable_input,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        child.stdin.flush()
        child.stdin.close()
        child.wait(timeout=15)

        assert child.returncode == 74
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "queued"
        with runtime.database.transaction() as transaction:
            attempt_count = transaction.execute(
                "SELECT count(*) AS count FROM research_runs.attempts WHERE run_id = %s",
                (run_id,),
            ).fetchone()["count"]
        assert attempt_count == 0
        assert _publication_manifest_count(settings) == publication_count


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_orphaned_tracking_child_exits_before_recovery_releases_its_pin(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("orphaned-tracking-child"),
        ).json()["id"]
        assert client.app.state.core_runtime.research_runs.process_next() is True
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "orphaned-tracking-child-activation"},
        ).json()["id"]
        _publish_head(
            settings,
            sessions=(*seed_sessions, "2026-08-06"),
            price_offset=1,
            expected_manifest=seed_head,
        )
        publication_count = _publication_manifest_count(settings)
        owner = _start_claim_barrier_worker(
            settings,
            "tracking",
            "tracking_execution_result_received",
        )
        try:
            result_event = _wait_for_worker_event(
                owner,
                "tracking_execution_result_received",
            )
            child_pid = int(result_event["child_pid"])
            live_state = _stored_tracking_activation(settings, str(track_id))
            assert live_state["active_pin_count"] == 1
            assert live_state["current_checkpoint_session"].isoformat() == (seed_sessions[-1])

            os.kill(owner.pid, signal.SIGSTOP)
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if _process_state(child_pid).startswith("Z"):
                    break
            else:
                raise AssertionError("Tracking child watchdog did not stop the child")

            owner.kill()
            owner.communicate(timeout=10)
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if not _process_state(child_pid):
                    break
            else:
                raise AssertionError("orphaned Tracking child was not reaped")

            before_recovery = _stored_tracking_activation(settings, str(track_id))
            assert before_recovery["active_pin_count"] == 1
            _expire_current_tracking_attempt(settings, str(track_id))
            assert client.app.state.core_runtime.daily_tracks.process_next() is True

            recovered = _stored_tracking_activation(settings, str(track_id))
            assert recovered["track_status"] == "active"
            assert recovered["latest_attempt_failure_reason"] == "WorkerLost"
            assert recovered["current_checkpoint_session"].isoformat() == (seed_sessions[-1])
            assert recovered["checkpoint_count"] == 1
            assert recovered["active_pin_count"] == 0
            assert _publication_manifest_count(settings) == publication_count
            retry_wait = client.get(f"/api/daily-tracks/{track_id}").json()[
                "progress"
            ]
            assert retry_wait["phase"] == "retry_wait"
            assert retry_wait["cycle_attempt"] == 1
            assert retry_wait["completed_target_sessions"] == 0
            assert client.app.state.core_runtime.daily_tracks.process_next() is False

            _make_tracking_retry_eligible(settings, str(track_id))
            assert client.app.state.core_runtime.daily_tracks.process_next() is True
            completed = _stored_tracking_activation(settings, str(track_id))
            assert completed["track_status"] == "active"
            assert completed["current_checkpoint_session"].isoformat() == "2026-08-06"
            assert completed["active_pin_count"] == 0
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.communicate(timeout=10)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tracking_stop_survives_owner_loss_until_child_and_lease_are_dead(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = client.post(
            "/api/research-runs",
            json=_run_command("lost-owner-tracking-stop"),
        ).json()["id"]
        assert client.app.state.core_runtime.research_runs.process_next() is True
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "lost-owner-tracking-stop-activation"},
        ).json()["id"]
        _publish_head(
            settings,
            sessions=(*seed_sessions, "2026-08-06"),
            price_offset=1,
            expected_manifest=seed_head,
        )
        publication_count = _publication_manifest_count(settings)
        owner = _start_claim_barrier_worker(
            settings,
            "tracking",
            "tracking_execution_result_received",
        )
        try:
            result_event = _wait_for_worker_event(
                owner,
                "tracking_execution_result_received",
            )
            child_pid = int(result_event["child_pid"])
            os.kill(owner.pid, signal.SIGSTOP)

            stopping = client.post(
                f"/api/daily-tracks/{track_id}/stop",
                json={"request_id": "lost-owner-tracking-stop-command"},
            )
            assert stopping.status_code == 202
            assert stopping.json()["status"] == "stopping"
            pending = _stored_tracking_activation(settings, str(track_id))
            assert pending["track_status"] == "stopping"
            assert pending["active_pin_count"] == 1
            assert client.app.state.core_runtime.daily_tracks.process_next() is False
            assert _stored_tracking_activation(settings, str(track_id))[
                "active_pin_count"
            ] == 1

            deadline = monotonic() + 10
            while monotonic() < deadline:
                if _process_state(child_pid).startswith("Z"):
                    break
            else:
                raise AssertionError("Tracking child watchdog did not stop the child")

            owner.kill()
            owner.communicate(timeout=10)
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if not _process_state(child_pid):
                    break
            else:
                raise AssertionError("stopped Tracking child was not reaped")

            before_lease_expiry = _stored_tracking_activation(settings, str(track_id))
            assert before_lease_expiry["track_status"] == "stopping"
            assert before_lease_expiry["active_pin_count"] == 1
            _expire_current_tracking_attempt(settings, str(track_id))
            assert client.app.state.core_runtime.daily_tracks.process_next() is True

            recovered = _stored_tracking_activation(settings, str(track_id))
            assert recovered["track_status"] == "stopped"
            assert recovered["cancelled_progression_count"] == 1
            assert recovered["cancelled_attempt_count"] == 1
            assert recovered["active_pin_count"] == 0
            assert recovered["current_checkpoint_session"].isoformat() == seed_sessions[-1]
            assert _publication_manifest_count(settings) == publication_count
            assert client.app.state.core_runtime.daily_tracks.process_next() is False
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.communicate(timeout=10)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_insufficient_warmup_is_rejected_before_run_creation(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        rejected = client.post(
            "/api/research-runs",
            json=_run_command(
                "attempt-insufficient-warmup",
                formula="ts_mean(close_adj, 2)",
            ),
        )
        assert rejected.status_code == 422
        assert rejected.json()["issues"] == [
            {
                "code": "INSUFFICIENT_CALCULATION_WARMUP",
                "field": "start_date",
                "message": "Research Period requires 1 sessions before 2026-08-03",
                "severity": "error",
                "range": None,
                "details": None,
            }
        ]
        assert client.get("/api/research-runs").json()["items"] == []
        assert client.app.state.core_runtime.research_runs.process_next() is False


@pytest.mark.parametrize("session_count", [1, 2])
@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_short_attempt_publishes_exact_period_and_complete_terminal_state(
    tmp_path: Path,
    session_count: int,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04")[:session_count]
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command(
                f"attempt-short-{session_count}",
                start_date=sessions[0],
                end_date=sessions[-1],
            ),
        )
        run_id = accepted.json()["id"]
        runtime = client.app.state.core_runtime

        assert runtime.research_runs.process_next() is True

        stored = _stored_execution(settings, run_id)
        result = read_result_bundle(
            runtime.publication.read(
                PublishedRef(
                    manifest_sha256=str(stored["result_manifest_sha256"]),
                    kind="research.result",
                    provenance=stored["result_provenance"],
                )
            )
        )
        observations = result["strategy_daily_observations"]
        assert [row["session"] for row in observations] == list(sessions)
        for horizon in result["factor_summary"]["horizons"].values():
            assert horizon["summary"]["ic"]["mean"] is None
            assert horizon["summary"]["rank_ic"]["mean"] is None
            assert horizon["coverage"]["ic_valid_session_count"] == 0
            assert horizon["coverage"]["rank_ic_valid_session_count"] == 0
        strategy_metrics = result["strategy_summary"]["metrics"]
        assert strategy_metrics["annualized_volatility"] is None
        assert strategy_metrics["sharpe"] is None
        terminal = result["terminal_strategy_state"]
        assert terminal["session"] == sessions[-1]
        assert terminal["last_daily_observation"]["session"] == sessions[-1]
        assert terminal["rebalance_phase"]["report_session_count"] == session_count
        assert terminal["metric_state"]["session_count"] == session_count
        assert isinstance(terminal["positions"], list)
        assert stored["active_pin_count"] == 0


@pytest.mark.parametrize("incompatibility", ["coverage", "field"])
@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_is_unchanged_by_an_incompatible_later_head(
    tmp_path: Path,
    incompatibility: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command(f"attempt-revalidate-{incompatibility}"),
        )
        run_id = accepted.json()["id"]
        replacement_sessions = sessions[1:] if incompatibility == "coverage" else sessions
        _publish_head(
            settings,
            sessions=replacement_sessions,
            price_offset=2,
            expected_manifest=head_a,
            available_field_id=(
                "market.volume.shares" if incompatibility == "field" else "price.close.adjusted"
            ),
        )

        assert client.app.state.core_runtime.research_runs.process_next() is True
        assert client.app.state.core_runtime.research_runs.process_next() is False

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded"
        assert detail["start_date"] == sessions[0]
        assert detail["end_date"] == sessions[-1]
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_count"] == 1
        assert stored["attempt_failure_reason"] is None
        assert stored["attempt_data_generation_id"] == head_a
        assert stored["result_manifest_sha256"] is not None
        assert stored["active_pin_count"] == 0
        assert client.delete(f"/api/research-runs/{run_id}").status_code == 204
        assert client.get(f"/api/research-runs/{run_id}").status_code == 404


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize("failure_stage", ["manifest_record", "final_state"])
def test_publication_failure_is_atomic_and_releases_the_generation_pin(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command(f"attempt-publication-failure-{failure_stage}"),
        )
        run_id = accepted.json()["id"]
        runtime = client.app.state.core_runtime
        manifest_count = _publication_manifest_count(settings)
        _install_publication_rejection(settings, failure_stage=failure_stage)
        try:
            assert runtime.research_runs.process_next() is True
        finally:
            _remove_publication_rejection(settings, failure_stage=failure_stage)

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        assert "result" not in detail
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_count"] == 1
        assert stored["result_manifest_sha256"] is None
        assert stored["result_provenance"] is None
        assert stored["active_pin_count"] == 0
        assert _publication_manifest_count(settings) == manifest_count


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_denied_rustfs_write_never_publishes_or_keeps_a_pin(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("attempt-denied-rustfs-write"),
        )
        run_id = accepted.json()["id"]
        runtime = client.app.state.core_runtime
        denied_s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id="ticket14-denied",
            aws_secret_access_key="ticket14-denied-secret",
            region_name=settings.s3_region,
            config=Config(connect_timeout=0.2, read_timeout=0.2, retries={"max_attempts": 0}),
        )
        processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=Publication(
                runtime.database,
                denied_s3,
                bucket=settings.s3_bucket,
            ),
            execution=SupervisedResearchExecutor(settings.data_mount),
        )
        manifest_count = _publication_manifest_count(settings)
        execution_events: list[dict[str, object]] = []

        assert processor.process_next(on_execution_event=execution_events.append) is True
        assert processor.process_next() is False

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        assert "result" not in detail
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_status"] == "failed"
        assert stored["attempt_failure_reason"] == "PermanentExecutionFailure"
        assert stored["result_manifest_sha256"] is None
        assert stored["active_pin_count"] == 0
        assert _publication_manifest_count(settings) == manifest_count
        assert [event["event"] for event in execution_events] == [
            "research_execution_child_started",
            "research_execution_chunk_received",
            "research_execution_child_exited",
        ]
        assert execution_events[-1]["acknowledged"] is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_result_read_failure_stays_sanitized(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command("attempt-result-read-failure"),
        )
        run_id = accepted.json()["id"]
        runtime = client.app.state.core_runtime
        assert runtime.research_runs.process_next() is True

        stored = _stored_execution(settings, run_id)
        digest = _first_result_object_sha256(
            settings,
            str(stored["result_manifest_sha256"]),
        )
        s3 = _s3_client(settings)
        key = f"publication/v1/sha256/{digest[:2]}/{digest}"
        original = s3.get_object(Bucket=settings.s3_bucket, Key=key)
        content = original["Body"].read()
        content_type = str(original["ContentType"])
        metadata = dict(original["Metadata"])
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=b"!" * len(content),
            ContentLength=len(content),
            ContentType=content_type,
            Metadata=metadata,
        )
        try:
            response = client.get(f"/api/research-runs/{run_id}")
        finally:
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=content,
                ContentLength=len(content),
                ContentType=content_type,
                Metadata=metadata,
            )

        assert response.status_code == 503
        assert response.json() == {"detail": "ResearchRun Result unavailable"}
        assert "checksum" not in response.text.lower()
        assert "bucket" not in response.text.lower()
        assert "object" not in response.text.lower()


def _run_command(
    request_id: str,
    *,
    formula: str = "close_adj",
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-05",
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "Attempt-scoped current data",
        "start_date": start_date,
        "end_date": end_date,
        "formula": formula,
        "universe": "top300",
        "neutralization": "none",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _canonical(
    sessions: tuple[str, ...],
    *,
    price_offset: int,
    available_field_id: str,
) -> dict[str, object]:
    template = build_minimal_canonical_fixture(price_offset=price_offset)
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "field_catalog": [
            {
                **template["field_catalog"][0],
                "name": (
                    "close_adj" if available_field_id == "price.close.adjusted" else "volume_shares"
                ),
                "field_id": available_field_id,
            }
        ],
        "research_calendar": list(sessions),
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _two_instrument_canonical(
    sessions: tuple[str, ...],
    *,
    corrected: bool,
) -> dict[str, object]:
    template = build_minimal_canonical_fixture()
    instrument_ids = ("equity:000001.SZ", "equity:000002.SZ")
    ts_codes = ("000001.SZ", "000002.SZ")
    instruments: list[dict[str, object]] = []
    industries: list[dict[str, object]] = []
    for instrument_id, ts_code in zip(instrument_ids, ts_codes, strict=True):
        instrument = copy.deepcopy(template["instruments"][0])
        instrument.update(instrument_id=instrument_id, ts_code=ts_code)
        instruments.append(instrument)
        industry = copy.deepcopy(template["industry_membership"][0])
        industry.update(
            instrument_id=instrument_id,
            sw2021_l1="801010",
            sw2021_l2="801011",
            sw2021_l3="850111",
        )
        industries.append(industry)

    prices: list[dict[str, object]] = []
    states: list[dict[str, object]] = []
    limits: list[dict[str, object]] = []
    price_template = template["prices"][0]
    for session in sessions:
        closes = ("1", "30") if corrected and session == "2026-08-05" else ("20", "10")
        for instrument_id, close, open_price in zip(
            instrument_ids,
            closes,
            ("20", "10"),
            strict=True,
        ):
            price = copy.deepcopy(price_template)
            high = str(max(int(close), int(open_price)))
            low = str(min(int(close), int(open_price)))
            price.update(
                instrument_id=instrument_id,
                session=session,
                open_raw=open_price,
                open_adj=f"{int(open_price):.8f}",
                close_raw=close,
                close_adj=f"{int(close):.8f}",
                high_raw=high,
                high_adj=f"{int(high):.8f}",
                low_raw=low,
                low_adj=f"{int(low):.8f}",
                pre_close_raw=close,
                change_raw="0",
                pct_change_raw="0",
            )
            prices.append(price)
            states.append(
                {
                    "instrument_id": instrument_id,
                    "session": session,
                    "state": "normal",
                }
            )
            limits.append(
                {
                    "instrument_id": instrument_id,
                    "session": session,
                    "lower": "0.01",
                    "upper": "100",
                }
            )
    universe = {
        name: [
            {
                "session": session,
                "instrument_ids": list(instrument_ids),
                "status": "available",
            }
            for session in sessions
        ]
        for name in ("top300", "top1000", "top2000", "top3000")
    }
    return {
        **template,
        "instruments": instruments,
        "industry_membership": industries,
        "research_calendar": list(sessions),
        "prices": prices,
        "trading_states": states,
        "price_limits": limits,
        "base_pool": [
            {"session": session, "instrument_ids": list(instrument_ids)} for session in sessions
        ],
        "liquidity_universes": universe,
    }


def _weekday_sessions_after(start: date, *, count: int) -> tuple[str, ...]:
    sessions: list[str] = []
    cursor = start
    while len(sessions) < count:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            sessions.append(cursor.isoformat())
    return tuple(sessions)


def _weekday_sessions_between(start: date, end: date) -> tuple[str, ...]:
    sessions: list[str] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            sessions.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(sessions)


def _write_refresh_replay(
    path: Path,
    canonical: dict[str, object],
    *,
    request_start: str,
) -> None:
    calendar = canonical["research_calendar"]
    instruments = canonical["instruments"]
    prices = canonical["prices"]
    limits = canonical["price_limits"]
    industries = canonical["industry_membership"]
    assert isinstance(calendar, list)
    assert isinstance(instruments, list)
    assert isinstance(prices, list)
    assert isinstance(limits, list)
    assert isinstance(industries, list)
    open_dates = {str(session).replace("-", "") for session in calendar}
    calendar_dates: list[str] = []
    cursor = date.fromisoformat(request_start)
    request_end = date.fromisoformat(str(calendar[-1]))
    while cursor <= request_end:
        calendar_dates.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    daily = [
        {
            "ts_code": _ts_code(canonical, str(price["instrument_id"])),
            "trade_date": str(price["session"]).replace("-", ""),
            "open": price["open_raw"],
            "high": price["high_raw"],
            "low": price["low_raw"],
            "close": price["close_raw"],
            "pre_close": price["pre_close_raw"],
            "change": price["change_raw"],
            "pct_chg": price["pct_change_raw"],
            "vol": str(Decimal(str(price["volume_shares"])) / Decimal(100)),
            "amount": str(Decimal(str(price["turnover_cny"])) / Decimal(1000)),
        }
        for price in prices
        if isinstance(price, dict)
    ]
    snapshot = {
        "calendar_sse": [
            {
                "exchange": "SSE",
                "cal_date": calendar_date,
                "is_open": "1" if calendar_date in open_dates else "0",
            }
            for calendar_date in calendar_dates
        ],
        "calendar_szse": [
            {
                "exchange": "SZSE",
                "cal_date": calendar_date,
                "is_open": "1" if calendar_date in open_dates else "0",
            }
            for calendar_date in calendar_dates
        ],
        "stock_basic": [
            {
                "ts_code": instrument["ts_code"],
                "exchange": "SZSE",
                "market": "主板",
                "list_date": str(instrument["listed_from"]).replace("-", ""),
                "delist_date": str(instrument["listed_to"]).replace("-", ""),
            }
            for instrument in instruments
            if isinstance(instrument, dict)
        ],
        "daily": daily,
        "adjustments": [
            {
                "ts_code": _ts_code(canonical, str(price["instrument_id"])),
                "trade_date": str(price["session"]).replace("-", ""),
                "adj_factor": price["adjustment_factor"],
            }
            for price in prices
            if isinstance(price, dict)
        ],
        "suspensions": [],
        "price_limits": [
            {
                "ts_code": _ts_code(canonical, str(limit["instrument_id"])),
                "trade_date": str(limit["session"]).replace("-", ""),
                "up_limit": limit["upper"],
                "down_limit": limit["lower"],
            }
            for limit in limits
            if isinstance(limit, dict)
        ],
        "industry_membership": [
            {
                "ts_code": _ts_code(canonical, str(industry["instrument_id"])),
                "in_date": str(industry["active_from"]).replace("-", ""),
                "out_date": str(industry["active_to"]).replace("-", ""),
                "l1_code": "801010",
                "l2_code": "801011",
                "l3_code": "850111",
            }
            for industry in industries
            if isinstance(industry, dict)
        ],
    }
    replay = {
        "format": "thesistrace-tushare-refresh-replay",
        "version": 2,
        "request_start": request_start,
        "request_end": str(calendar[-1]),
        "snapshot": snapshot,
    }
    path.write_text(
        json.dumps(replay, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _refresh_via_private_operator(
    settings: CoreSettings,
    *,
    replay_root: Path,
    idempotency_key: str,
    canonical: dict[str, object],
    request_start: str,
) -> dict[str, object]:
    calendar = canonical["research_calendar"]
    assert isinstance(calendar, list) and calendar
    replay = replay_root / f"{idempotency_key}.json"
    _write_refresh_replay(replay, canonical, request_start=request_start)
    submitted = _run_data_operator(
        settings,
        [
            "refresh",
            "--idempotency-key",
            idempotency_key,
            "--as-of",
            f"{calendar[-1]}T09:00:00+00:00",
        ],
    )
    assert submitted["status"] == "accepted"
    processed = _run_data_operator(
        settings,
        ["work-refresh", "--replay", os.fspath(replay)],
    )
    assert processed == {"status": "processed"}
    return _run_data_operator(
        settings,
        ["inspect-refresh", "--idempotency-key", idempotency_key],
    )


def _ts_code(canonical: dict[str, object], instrument_id: str) -> str:
    instruments = canonical["instruments"]
    assert isinstance(instruments, list)
    for instrument in instruments:
        if isinstance(instrument, dict) and instrument["instrument_id"] == instrument_id:
            return str(instrument["ts_code"])
    raise AssertionError(f"unknown fixture instrument: {instrument_id}")


def _publish_canonical_head(
    settings: CoreSettings,
    canonical: dict[str, object],
    *,
    operation_id: str,
) -> str:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
        source_name="forward-only-test",
        source_lineage={"fixture": operation_id},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _publish_composite_head(
    settings: CoreSettings,
    *,
    sessions: tuple[str, ...],
    financial_through: str | None = None,
    expected_manifest: str | None = None,
    operation_id: str = "composite-e2e",
) -> str:
    observation_through = financial_through or sessions[-1]
    finished_date = max(observation_through, "2026-08-05")
    store = MountedGenerationStore(settings.data_mount)
    market = store.materialize(
        _two_instrument_canonical(sessions, corrected=False),
        prepared_at=datetime(2026, 8, 5, 10, tzinfo=UTC),
        source_name="composite-alpha-test",
        source_lineage={"fixture": "composite-alpha"},
    )
    endpoint_fields = {
        "income": (
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "end_type",
            "total_revenue",
            "n_income_attr_p",
            "update_flag",
        ),
        "balancesheet": (
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "end_type",
            "total_assets",
            "total_liab",
            "total_hldr_eqy_exc_min_int",
            "update_flag",
        ),
        "cashflow": (
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "end_type",
            "n_cashflow_act",
            "update_flag",
        ),
    }
    values = {
        "income": (("100", "10"), ("200", "20")),
        "balancesheet": (("1000", "400", "600"), ("2000", "800", "1200")),
        "cashflow": (("30",), ("60",)),
    }
    raw = RawFinancialBatchStore(settings.data_mount)
    checkpoints: list[FinancialShardCheckpoint] = []
    for endpoint in ("income", "balancesheet", "cashflow"):
        fields = endpoint_fields[endpoint]
        for index, (instrument_id, ts_code) in enumerate(
            (("equity:000001.SZ", "000001.SZ"), ("equity:000002.SZ", "000002.SZ"))
        ):
            item = [
                ts_code,
                "20100420",
                "",
                "20091231",
                "1",
                "1",
                "4",
                *values[endpoint][index],
                "0",
            ]
            payload_sha256 = hashlib.sha256(
                canonical_json_bytes({"fields": list(fields), "items": [item]})
            ).hexdigest()
            payload = {
                "format": "thesistrace-raw-financial-batch",
                "version": 1,
                "source_contract_version": "tushare-financial-ordinary-v2",
                "endpoint": endpoint,
                "parameters": {"ts_code": ts_code},
                "returned_fields": list(fields),
                "items": [item],
                "row_count": 1,
                "source_date_extent": ["20100420", "20100420"],
                "payload_sha256": payload_sha256,
            }
            checkpoints.append(
                FinancialShardCheckpoint(
                    ordinal=len(checkpoints),
                    endpoint=endpoint,
                    instrument_id=instrument_id,
                    ts_code=ts_code,
                    shard="complete-history",
                    status="completed",
                    batch_sha256=raw.store(canonical_json_bytes(payload)),
                    collected_at="2026-08-05T09:00:00+00:00",
                    first_observed_at="2026-08-05T09:00:00+00:00",
                )
            )
    contract = FinancialCollectionContract(
        capability_sha256="e" * 64,
        endpoint_fields=tuple(endpoint_fields.items()),
        suspected_truncation_row_counts=(
            ("income", None),
            ("balancesheet", None),
            ("cashflow", None),
        ),
        shards=(FinancialDateShard("complete-history"),),
    )
    financial = FinancialCandidateStore(settings.data_mount).materialize(
        CompletedFinancialCollection(
            idempotency_key=operation_id,
            generation_manifest_sha256=market.manifest_sha256,
            contract=contract,
            finished_at=f"{finished_date}T10:00:00+00:00",
            target_count=len(checkpoints),
            shards=tuple(checkpoints),
        ),
        observation_through_session=observation_through,
    )
    composite = store.compose_financial_candidate(
        market.manifest_sha256,
        financial.manifest_sha256,
        prepared_at=datetime.fromisoformat(f"{finished_date}T11:00:00+00:00"),
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=composite.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected_manifest,
            candidate_generation_manifest_sha256=composite.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return composite.manifest_sha256


def _publish_head(
    settings: CoreSettings,
    *,
    sessions: tuple[str, ...],
    price_offset: int,
    expected_manifest: str | None = None,
    available_field_id: str = "price.close.adjusted",
) -> str:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        _canonical(
            sessions,
            price_offset=price_offset,
            available_field_id=available_field_id,
        ),
        prepared_at=datetime(2026, 8, 9, price_offset, tzinfo=UTC),
        source_name="attempt-execution-test",
        source_lineage={"price_offset": price_offset},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        operation_id = f"attempt-execution-{price_offset}-{len(sessions)}"
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected_manifest,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _kernel_input(
    canonical: dict[str, object],
    *,
    sessions: tuple[str, ...],
) -> RunInput:
    return RunInput(
        research_data=_research_data(canonical),
        alpha_expression={"kind": "field", "field_id": "price.close.adjusted"},
        field_bindings={"price.close.adjusted": "close_adj"},
        effective_alpha_lookback=0,
        universe="top300",
        neutralization="none",
        holdings_count=1,
        rebalance_interval=1,
        initial_cash_cny="10000000",
        commission_rate_all_in="0.0003",
        commission_min_cny="5",
        stamp_duty_sell_rate="0.0005",
        transfer_fee_rate="0.00001",
        research_start_session=sessions[0],
        research_end_session=sessions[-1],
    )


def _reference_result(
    settings: CoreSettings,
    generation_id: str,
    database: PostgresDatabase,
    run_id: str,
) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT immutable_input FROM research_runs.runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    immutable = ImmutableRunInput.model_validate(row["immutable_input"])
    admission = MountedGenerationStore(settings.data_mount).open_admission(generation_id)
    calendar = list(admission.research_calendar)
    selected = [
        session
        for session in calendar
        if immutable.requested_start_date.isoformat()
        <= session
        <= immutable.requested_end_date.isoformat()
    ]
    start_index = calendar.index(selected[0])
    calculation_sessions = calendar[
        start_index - immutable.alpha_admission.effective_lookback : calendar.index(selected[-1])
        + 1
    ]
    research_data = (
        MountedGenerationStore(settings.data_mount)
        .read_composite_slice(
            generation_id,
            sessions=calculation_sessions,
            universe_name=immutable.universe,
            neutralization=immutable.neutralization,
            field_bindings=immutable.field_bindings,
        )
        .research_data
    )
    strategy = immutable.strategy
    costs = immutable.costs
    return build_result_payload(
        run(
            RunInput(
                research_data=research_data,
                alpha_expression=immutable.alpha_expression,
                field_bindings=immutable.field_bindings,
                effective_alpha_lookback=immutable.alpha_admission.effective_lookback,
                universe=immutable.universe,
                neutralization=immutable.neutralization,
                holdings_count=int(strategy["holdings_count"]),
                rebalance_interval=int(strategy["rebalance_every_sessions"]),
                initial_cash_cny=str(strategy["initial_cash_cny"]),
                commission_rate_all_in=str(costs["commission_rate_all_in"]),
                commission_min_cny=str(costs["commission_min_cny"]),
                stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
                transfer_fee_rate=str(costs["transfer_fee_rate"]),
                research_start_session=selected[0],
                research_end_session=selected[-1],
            )
        ),
        rebalance_interval=int(strategy["rebalance_every_sessions"]),
        universe=immutable.universe,
    )


def _research_data(canonical: dict[str, object]):
    return align_canonical_market_data(
        canonical,
        field_bindings={"price.close.adjusted": "close_adj"},
        universe="top300",
        neutralization="none",
    )


def _stored_execution(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.status, run.result_manifest_sha256, run.result_provenance,
                       attempt.status AS attempt_status,
                       attempt.data_generation_id AS attempt_data_generation_id,
                       attempt.data_through_session AS attempt_data_through_session,
                       attempt.failure_reason AS attempt_failure_reason,
                       (SELECT count(*)
                        FROM research_runs.attempts
                        WHERE run_id = run.id) AS attempt_count,
                       (SELECT count(*)
                        FROM data.generation_pins
                        WHERE status = 'active') AS active_pin_count
                FROM research_runs.runs AS run
                JOIN research_runs.attempts AS attempt ON attempt.run_id = run.id
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return row
    finally:
        database.close()


def _replace_research_numeric_contract(
    settings: CoreSettings,
    run_id: str,
    contract_id: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.runs
                SET immutable_input = jsonb_set(
                    immutable_input,
                    '{numeric_execution_contract}',
                    to_jsonb(%s::text)
                )
                WHERE id = %s
                """,
                (contract_id, run_id),
            )
            assert updated.rowcount == 1
    finally:
        database.close()


def _replace_tracking_numeric_contract(
    settings: CoreSettings,
    track_id: str,
    contract_id: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET origin = jsonb_set(
                    origin,
                    '{calculation_contracts,numeric_execution_contract}',
                    to_jsonb(%s::text)
                )
                WHERE id = %s
                """,
                (contract_id, track_id),
            )
            assert updated.rowcount == 1
    finally:
        database.close()


def _stored_tracking_activation(
    settings: CoreSettings,
    track_id: str,
) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT track.status AS track_status,
                       state.origin_session,
                       track.origin,
                       state.current_checkpoint_manifest_sha256,
                       checkpoint.boundary_session AS current_checkpoint_session,
                       checkpoint.provenance AS current_checkpoint_provenance,
                       checkpoint.terminal_strategy_state,
                       (SELECT count(*)
                        FROM daily_tracks.session_checkpoints
                        WHERE track_id = state.track_id) AS checkpoint_count,
                       (SELECT count(*)
                        FROM daily_tracks.session_progressions
                        WHERE track_id = state.track_id) AS progression_count,
                       (SELECT count(*)
                        FROM daily_tracks.session_progression_attempts
                        WHERE track_id = state.track_id) AS attempt_count,
                       (SELECT count(*)
                        FROM daily_tracks.session_progressions
                        WHERE track_id = state.track_id
                          AND status = 'cancelled') AS cancelled_progression_count,
                       (SELECT count(*)
                        FROM daily_tracks.session_progressions
                        WHERE track_id = state.track_id
                          AND status = 'blocked') AS blocked_progression_count,
                       (SELECT count(*)
                        FROM daily_tracks.session_progressions
                        WHERE track_id = state.track_id
                          AND status = 'succeeded') AS succeeded_progression_count,
                       (SELECT count(*)
                        FROM daily_tracks.session_progression_attempts
                        WHERE track_id = state.track_id
                          AND status = 'cancelled') AS cancelled_attempt_count,
                       (SELECT count(*)
                        FROM daily_tracks.session_progression_attempts
                        WHERE track_id = state.track_id
                          AND status = 'failed') AS failed_attempt_count,
                       (SELECT count(*)
                        FROM data.generation_pins
                        WHERE status = 'active') AS active_pin_count,
                       (SELECT failure_reason
                        FROM daily_tracks.session_progression_attempts
                        WHERE track_id = state.track_id
                        ORDER BY started_at DESC, id DESC
                        LIMIT 1) AS latest_attempt_failure_reason
                FROM daily_tracks.session_tracking_states AS state
                JOIN daily_tracks.tracks AS track ON track.id = state.track_id
                JOIN daily_tracks.session_checkpoints AS checkpoint
                  ON checkpoint.track_id = state.track_id
                 AND checkpoint.manifest_sha256 =
                        state.current_checkpoint_manifest_sha256
                WHERE state.track_id = %s
                """,
                (track_id,),
            ).fetchone()
        assert row is not None
        return row
    finally:
        database.close()


def _tracking_retry_state(
    settings: CoreSettings,
    track_id: str,
) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            progression = transaction.execute(
                """
                SELECT track.status AS track_status,
                       progression.status AS progression_status,
                       progression.current_cycle_ordinal AS cycle_ordinal,
                       progression.next_attempt_eligible_at,
                       latest.finished_at,
                       EXTRACT(
                           EPOCH FROM progression.next_attempt_eligible_at
                                      - latest.finished_at
                       ) AS retry_delay_seconds
                FROM daily_tracks.session_progressions AS progression
                JOIN daily_tracks.tracks AS track ON track.id = progression.track_id
                LEFT JOIN LATERAL (
                    SELECT finished_at
                    FROM daily_tracks.session_progression_attempts
                    WHERE progression_id = progression.id
                    ORDER BY ordinal DESC
                    LIMIT 1
                ) AS latest ON true
                WHERE progression.track_id = %s
                ORDER BY progression.created_at DESC, progression.id DESC
                LIMIT 1
                """,
                (track_id,),
            ).fetchone()
            attempts = transaction.execute(
                """
                SELECT cycle_ordinal, cycle_attempt_ordinal, failure_reason,
                       data_generation_id
                FROM daily_tracks.session_progression_attempts
                WHERE track_id = %s
                ORDER BY ordinal
                """,
                (track_id,),
            ).fetchall()
        assert progression is not None
        return {
            **progression,
            "attempt_cycles": [int(row["cycle_ordinal"]) for row in attempts],
            "attempt_ordinals": [int(row["cycle_attempt_ordinal"]) for row in attempts],
            "attempt_failures": [row["failure_reason"] for row in attempts],
            "attempt_generations": [row["data_generation_id"] for row in attempts],
            "retry_delay_seconds": (
                None
                if progression["retry_delay_seconds"] is None
                else float(progression["retry_delay_seconds"])
            ),
        }
    finally:
        database.close()


def _make_tracking_retry_eligible(settings: CoreSettings, track_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE daily_tracks.session_progressions
                SET next_attempt_eligible_at = now()
                WHERE track_id = %s AND status = 'running'
                  AND queue_position IS NULL
                """,
                (track_id,),
            )
            assert updated.rowcount == 1
    finally:
        database.close()


def _tracking_checkpoint_history(
    settings: CoreSettings,
    track_id: str,
) -> list[dict[str, object]]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT boundary_session::text AS boundary_session,
                       manifest_sha256, provenance, terminal_strategy_state
                FROM daily_tracks.session_checkpoints
                WHERE track_id = %s
                ORDER BY boundary_session, manifest_sha256
                """,
                (track_id,),
            ).fetchall()
        return rows
    finally:
        database.close()


def _position_ids(value: object) -> set[str]:
    assert isinstance(value, dict)
    positions = value.get("positions")
    assert isinstance(positions, list)
    return {str(position["instrument_id"]) for position in positions if isinstance(position, dict)}


def _expire_current_tracking_attempt(settings: CoreSettings, track_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            expired = transaction.execute(
                """
                UPDATE daily_tracks.session_progression_attempts
                SET lease_expires_at = now() - interval '1 second'
                WHERE track_id = %s AND status IN ('running', 'stopping')
                """,
                (track_id,),
            )
        assert expired.rowcount == 1
    finally:
        database.close()


def _process_state(process_id: int) -> str:
    completed = subprocess.run(
        ["/bin/ps", "-o", "stat=", "-p", str(process_id)],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _live_tracking_attempt_timing(
    settings: CoreSettings,
    track_id: str,
) -> dict[str, datetime]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT heartbeat_at, lease_expires_at
                FROM daily_tracks.session_progression_attempts
                WHERE track_id = %s AND status = 'running'
                """,
                (track_id,),
            ).fetchone()
        assert row is not None
        heartbeat_at = row["heartbeat_at"]
        lease_expires_at = row["lease_expires_at"]
        assert isinstance(heartbeat_at, datetime)
        assert isinstance(lease_expires_at, datetime)
        return {
            "heartbeat_at": heartbeat_at,
            "lease_expires_at": lease_expires_at,
        }
    finally:
        database.close()


def _wait_for_tracking_lease_renewal(
    settings: CoreSettings,
    track_id: str,
    *,
    after_heartbeat: datetime,
) -> dict[str, datetime]:
    deadline = monotonic() + 5
    poll_interval = Event()
    latest: dict[str, datetime] | None = None
    while monotonic() < deadline:
        latest = _live_tracking_attempt_timing(settings, track_id)
        if latest["heartbeat_at"] > after_heartbeat:
            return latest
        poll_interval.wait(timeout=0.02)
    raise AssertionError(f"DailyTrack lease was not renewed; latest attempt timing was {latest!r}")


def _checkpoint_payload(
    publication: Publication,
    stored: dict[str, object],
) -> dict[str, object]:
    bundle = publication.read(
        PublishedRef(
            manifest_sha256=str(stored["current_checkpoint_manifest_sha256"]),
            kind="daily-track.checkpoint",
            provenance=dict(stored["current_checkpoint_provenance"]),
        )
    )
    payload = bundle.payloads["checkpoint"]
    value = json.loads(payload.content)
    assert isinstance(value, dict)
    return value


def _publication_manifest_count(settings: CoreSettings) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT count(*) AS count FROM publication.manifests"
            ).fetchone()
        assert row is not None
        return int(row["count"])
    finally:
        database.close()


def _first_result_object_sha256(settings: CoreSettings, manifest_sha256: str) -> str:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT object_sha256
                FROM publication.manifest_objects
                WHERE manifest_sha256 = %s
                ORDER BY ordinal
                LIMIT 1
                """,
                (manifest_sha256,),
            ).fetchone()
        assert row is not None
        return str(row["object_sha256"])
    finally:
        database.close()


def _remove_manifest_object_reference(
    settings: CoreSettings,
    manifest_sha256: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            removed = transaction.execute(
                """
                DELETE FROM publication.manifest_objects
                WHERE manifest_sha256 = %s
                """,
                (manifest_sha256,),
            )
        assert removed.rowcount > 0
    finally:
        database.close()


def _install_publication_rejection(
    settings: CoreSettings,
    *,
    failure_stage: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            if failure_stage == "manifest_record":
                transaction.execute(
                    """
                    CREATE FUNCTION publication.reject_manifest_record() RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION 'injected Result manifest-record failure';
                    END
                    $$;
                    CREATE TRIGGER reject_manifest_record
                    BEFORE INSERT ON publication.manifests
                    FOR EACH ROW
                    EXECUTE FUNCTION publication.reject_manifest_record();
                    """
                )
            elif failure_stage == "final_state":
                transaction.execute(
                    """
                    CREATE FUNCTION research_runs.reject_result_success() RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION 'injected ResearchRun final-state failure';
                    END
                    $$;
                    CREATE TRIGGER reject_result_success
                    BEFORE UPDATE OF status ON research_runs.runs
                    FOR EACH ROW
                    WHEN (NEW.status = 'succeeded')
                    EXECUTE FUNCTION research_runs.reject_result_success();
                    """
                )
            else:
                raise AssertionError(f"unsupported failure stage: {failure_stage}")
    finally:
        database.close()


def _remove_publication_rejection(
    settings: CoreSettings,
    *,
    failure_stage: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            if failure_stage == "manifest_record":
                transaction.execute(
                    """
                    DROP TRIGGER reject_manifest_record ON publication.manifests;
                    DROP FUNCTION publication.reject_manifest_record();
                    """
                )
            elif failure_stage == "final_state":
                transaction.execute(
                    """
                    DROP TRIGGER reject_result_success ON research_runs.runs;
                    DROP FUNCTION research_runs.reject_result_success();
                    """
                )
            else:
                raise AssertionError(f"unsupported failure stage: {failure_stage}")
    finally:
        database.close()


def _run_worker_once(
    settings: CoreSettings,
    role: str = "research",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            role,
            "--once",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT,
        env=_worker_environment(settings),
    )


def _worker_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
    }


def _run_worker_replicas(
    settings: CoreSettings,
    role: str,
    count: int,
) -> list[subprocess.CompletedProcess[str]]:
    with ThreadPoolExecutor(max_workers=count) as executor:
        futures = [executor.submit(_run_worker_once, settings, role) for _ in range(count)]
        return [future.result(timeout=30) for future in futures]


def _start_claim_barrier_worker(
    settings: CoreSettings,
    role: str,
    barrier_event: str = "worker_claim",
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "tests/acceptance/process_worker_with_claim_barrier.py",
            role,
            barrier_event,
        ],
        cwd=ROOT,
        env=_worker_environment(settings),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_barrier_claim(process: subprocess.Popen[str]) -> dict[str, object]:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        assert selector.select(timeout=30), "Worker did not reach its claim barrier"
        line = process.stdout.readline()
    finally:
        selector.close()
    assert line, f"Worker exited before claim: {process.stderr.read() if process.stderr else ''}"
    event = json.loads(line)
    assert event["event"] == "worker_claim"
    return event


def _wait_for_worker_event(
    process: subprocess.Popen[str],
    event_name: str,
) -> dict[str, object]:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        deadline = monotonic() + 30
        while monotonic() < deadline:
            assert selector.select(timeout=max(0.01, deadline - monotonic())), (
                f"Worker did not emit {event_name}"
            )
            line = process.stdout.readline()
            assert line, (
                f"Worker exited before {event_name}: "
                f"{process.stderr.read() if process.stderr else ''}"
            )
            event = json.loads(line)
            if event.get("event") == event_name:
                return event
    finally:
        selector.close()
    raise AssertionError(f"Worker did not emit {event_name}")


def _release_claim_barrier_worker(process: subprocess.Popen[str]) -> None:
    assert process.stdin is not None
    process.stdin.write("release\n")
    process.stdin.flush()
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, stdout + stderr


def _worker_events(
    completed: subprocess.CompletedProcess[str],
) -> list[dict[str, object]]:
    return [json.loads(line) for line in completed.stderr.splitlines() if line.startswith("{")]


def _run_data_operator(
    settings: CoreSettings,
    arguments: list[str],
) -> dict[str, object]:
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_DATA_MOUNT": os.fspath(settings.data_mount),
    }
    completed = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.data_operator", *arguments],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
        timeout=30,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def _s3_client(settings: CoreSettings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )

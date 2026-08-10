from __future__ import annotations

import copy
import json
import os
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
from core_runtime import create_migrated_test_app as create_app
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
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication import Publication, PublishedRef
from thesistrace.research_kernel import (
    AdvanceInput,
    KernelRunError,
    RunInput,
    advance,
    advance_continuation,
    empty_continuation,
    run,
)
from thesistrace.research_kernel.canonical_state import (
    canonical_sessions,
    slice_canonical_sessions,
)
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.result import build_result_payload, read_result_bundle


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_uses_the_head_current_when_execution_starts(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-start-head"),
        )
        assert accepted.status_code == 200
        run_id = accepted.json()["run"]["id"]
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
            "definition_id",
            "definition_revision",
            "start_date",
            "end_date",
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
        assert terminal_account["net_nav"] == public_run["result"]["strategy"][
            "observations"
        ][-1]["net_nav"]
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
        assert stored["attempt_data_generation_id"] == head_b
        assert stored["attempt_data_through_session"].isoformat() == sessions[-1]
        assert stored["result_provenance"]["data_generation_id"] == head_b
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
            "definition_id": public_run["definition_id"],
            "definition_revision": public_run["definition_revision"],
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

        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr

        caught_up = client.get(f"/api/daily-tracks/{track['id']}")
        assert caught_up.status_code == 200
        caught_up_detail = caught_up.json()
        assert caught_up_detail["strategy_session"] == latest_sessions[-1]
        assert caught_up_detail["data_through_session"] == latest_sessions[-1]
        assert caught_up_detail["lag_sessions"] == 0
        assert [
            observation["session"]
            for observation in caught_up_detail["strategy"]["observations"]
        ] == list(latest_sessions)
        assert "release" not in caught_up.text.lower()
        assert "generation" not in caught_up.text.lower()
        progressed = _stored_tracking_activation(settings, track["id"])
        assert progressed["current_checkpoint_session"].isoformat() == (
            latest_sessions[-1]
        )
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
        canonical_c = store.open_generation(head_c).canonical
        calendar_c = canonical_sessions(canonical_c, "reference Head C")
        prior_c = slice_canonical_sessions(canonical_c, calendar_c[: len(sessions)])
        reference_origin = restore_tracking_origin(
            origin,
            activation["terminal_strategy_state"],
            prior_c,
        )
        reference_c = advance(
            AdvanceInput(
                prior_state=reference_origin,
                target_canonical_release=canonical_c,
                appended_sessions=list(extended_sessions[len(sessions) :]),
                continuation=advance_continuation(
                    run_input=reference_origin.run_input_with_canonical(prior_c),
                    prior_continuation=empty_continuation(),
                    target_canonical=prior_c,
                    appended_sessions=calendar_c[: len(sessions)],
                ),
                calculation_scope="forward_tracking",
            )
        )
        checkpoint_c = project_tracking_checkpoint(
            reference_c,
            retained_strategy_sessions=[sessions[-1], *extended_sessions[len(sessions) :]],
        )
        canonical_d = store.open_generation(head_d).canonical
        calendar_d = canonical_sessions(canonical_d, "reference Head D")
        prior_d = slice_canonical_sessions(canonical_d, calendar_d[:-1])
        restored_c = restore_tracking_checkpoint(checkpoint_c, canonical=prior_d)
        reference_d = advance(
            AdvanceInput(
                prior_state=restored_c,
                target_canonical_release=canonical_d,
                appended_sessions=[latest_sessions[-1]],
                continuation=advance_continuation(
                    run_input=restored_c.run_input_with_canonical(prior_d),
                    prior_continuation=empty_continuation(),
                    target_canonical=prior_d,
                    appended_sessions=calendar_d[:-1],
                ),
                calculation_scope="forward_tracking",
            )
        )
        assert progressed["terminal_strategy_state"] == terminal_strategy_state(
            reference_d
        )

        _publish_head(
            settings,
            sessions=(*latest_sessions, "2026-08-11"),
            price_offset=4,
            expected_manifest=head_d,
        )
        stop_claimed = Event()
        finish_stopped_advance = Event()

        def stop_barrier(stage: str, _track_id: str, _target: str) -> None:
            if stage == "claimed":
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
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stopped_processor.process_next)
            assert stop_claimed.wait(timeout=10)
            stopped = client.post(
                f"/api/daily-tracks/{track['id']}/stop",
                json={"request_id": "attempt-start-head-track-stop"},
            )
            assert stopped.status_code == 202
            assert stopped.json()["status"] == "stopped"
            finish_stopped_advance.set()
            assert future.result(timeout=20) is True
        stopped_replay = client.post(
            f"/api/daily-tracks/{track['id']}/stop",
            json={"request_id": "attempt-start-head-track-stop"},
        )
        assert stopped_replay.status_code == 202
        assert stopped_replay.json() == stopped.json()
        assert runtime.daily_tracks.process_next() is False
        stopped_state = _stored_tracking_activation(settings, track["id"])
        assert stopped_state["current_checkpoint_session"].isoformat() == (
            latest_sessions[-1]
        )
        assert stopped_state["checkpoint_count"] == 3
        assert stopped_state["cancelled_progression_count"] == 1
        assert stopped_state["cancelled_attempt_count"] == 1
        assert stopped_state["active_pin_count"] == 0

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
def test_current_data_track_limit_releases_capacity_after_stop(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    _publish_head(
        settings,
        sessions=("2026-08-03", "2026-08-04", "2026-08-05"),
        price_offset=0,
    )

    with TestClient(create_app(settings)) as client:
        run_ids: list[str] = []
        for index in range(11):
            accepted = client.post(
                "/api/definitions/run",
                json=_run_command(f"current-track-capacity-{index}"),
            )
            assert accepted.status_code == 200
            run_ids.append(str(accepted.json()["run"]["id"]))
        for _run_id in run_ids:
            completed = _run_worker_once(settings)
            assert completed.returncode == 0, completed.stdout + completed.stderr

        same_seed_barrier = Barrier(4)

        def start_same_seed(index: int):
            same_seed_barrier.wait(timeout=10)
            return client.post(
                f"/api/research-runs/{run_ids[0]}/daily-tracks",
                json={"request_id": f"current-track-same-seed-{index}"},
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            same_seed_futures = [
                executor.submit(start_same_seed, index) for index in range(4)
            ]
            same_seed_responses = [
                future.result(timeout=30) for future in same_seed_futures
            ]
        assert [response.status_code for response in same_seed_responses] == [201] * 4
        first_track = same_seed_responses[0].json()
        assert [response.json() for response in same_seed_responses] == [
            first_track
        ] * 4
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
            capacity_futures = [
                executor.submit(race_capacity, index) for index in range(2)
            ]
            capacity_responses = [
                future.result(timeout=30) for future in capacity_futures
            ]
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
        assert len(
            [
                item
                for item in client.get("/api/daily-tracks").json()["items"]
                if item["status"] in {"active", "blocked"}
            ]
        ) == 10

        stopped = client.post(
            f"/api/daily-tracks/{tracks[0]['id']}/stop",
            json={"request_id": "current-track-capacity-stop"},
        )
        assert stopped.status_code == 202
        admitted = client.post(
            f"/api/research-runs/{rejected_run_id}/daily-tracks",
            json={"request_id": "current-track-capacity-after-stop"},
        )
        assert admitted.status_code == 201
        final_tracks = client.get("/api/daily-tracks").json()["items"]
        assert len(final_tracks) == 11
        assert len(
            [item for item in final_tracks if item["status"] in {"active", "blocked"}]
        ) == 10


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_live_tracking_owner_renews_lease_and_blocks_duplicate_claim(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)
    entered_kernel = Event()
    release_kernel = Event()

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("tracking-live-owner"),
        )
        assert accepted.status_code == 200
        run_id = str(accepted.json()["run"]["id"])
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

        def block_kernel(value: AdvanceInput):
            entered_kernel.set()
            if not release_kernel.wait(timeout=10):
                raise TimeoutError("live-owner kernel was not released")
            return advance(value)

        owner = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            advance_kernel=block_kernel,
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
            future = executor.submit(owner.process_next)
            assert entered_kernel.wait(timeout=10)
            initial_timing = _live_tracking_attempt_timing(settings, track_id)
            try:
                renewed_timing = _wait_for_tracking_lease_renewal(
                    settings,
                    track_id,
                    after_heartbeat=initial_timing["heartbeat_at"],
                )
                assert renewed_timing["lease_expires_at"] > initial_timing[
                    "lease_expires_at"
                ]
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
    migrate_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        tracks: list[dict[str, object]] = []
        for index in range(2):
            accepted = client.post(
                "/api/definitions/run",
                json=_run_command(f"track-recovery-seed-{index}"),
            )
            assert accepted.status_code == 200
            run_id = accepted.json()["run"]["id"]
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

        def fail_after_calculation(value: AdvanceInput):
            advance(value)
            raise KernelRunError("injected private calculation failure")

        failing = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            advance_kernel=fail_after_calculation,
        )
        with pytest.raises(DailyTrackProgressionFailed):
            failing.process_next()

        blocked = client.get(f"/api/daily-tracks/{first_track['id']}")
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "blocked"
        assert blocked.json()["strategy_session"] == seed_sessions[-1]
        assert blocked.json()["blocked_reason"] == (
            "DailyTrack could not process the current dataset."
        )
        assert "injected" not in blocked.text
        failed_state = _stored_tracking_activation(settings, str(first_track["id"]))
        assert failed_state["current_checkpoint_session"].isoformat() == (
            seed_sessions[-1]
        )
        assert failed_state["checkpoint_count"] == 1
        assert failed_state["blocked_progression_count"] == 1
        assert failed_state["failed_attempt_count"] == 1
        assert failed_state["active_pin_count"] == 0

        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        control = client.get(f"/api/daily-tracks/{control_track['id']}").json()
        assert control["strategy_session"] == catch_up_sessions[-1]
        assert control["lag_sessions"] == 0
        assert client.get(f"/api/daily-tracks/{first_track['id']}").json()[
            "status"
        ] == "blocked"

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
        assert retry_conflict.json() == {
            "detail": "DailyTrack Retry request_id conflicts"
        }
        completed = _run_worker_once(settings)
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
        assert recovered_state["checkpoint_count"] == 2
        assert recovered_state["cancelled_progression_count"] == 0
        assert recovered_state["succeeded_progression_count"] == 1
        assert recovered_state["active_pin_count"] == 0
        recovered_canonical = MountedGenerationStore(
            settings.data_mount
        ).open_generation(recovered_head).canonical
        recovered_calendar = canonical_sessions(
            recovered_canonical,
            "recovery reference Head",
        )
        recovery_prior_canonical = slice_canonical_sessions(
            recovered_canonical,
            recovered_calendar[: len(seed_sessions)],
        )
        recovery_origin = restore_tracking_origin(
            TrackingOrigin.model_validate(recovered_state["origin"]),
            failed_state["terminal_strategy_state"],
            recovery_prior_canonical,
        )
        recovery_reference = advance(
            AdvanceInput(
                prior_state=recovery_origin,
                target_canonical_release=recovered_canonical,
                appended_sessions=list(recovered_sessions[len(seed_sessions) :]),
                continuation=advance_continuation(
                    run_input=recovery_origin.run_input_with_canonical(
                        recovery_prior_canonical
                    ),
                    prior_continuation=empty_continuation(),
                    target_canonical=recovery_prior_canonical,
                    appended_sessions=recovered_calendar[: len(seed_sessions)],
                ),
                calculation_scope="forward_tracking",
            )
        )
        assert recovered_state["terminal_strategy_state"] == terminal_strategy_state(
            recovery_reference
        )

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

        def stale_barrier(stage: str, _track_id: str, _target: str) -> None:
            if stage == "claimed":
                stale_claimed.set()
                assert release_stale_worker.wait(timeout=10)

        stale_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            progress=stale_barrier,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            stale_future = executor.submit(stale_processor.process_next)
            assert stale_claimed.wait(timeout=10)
            _expire_current_tracking_attempt(settings, str(first_track["id"]))
            assert runtime.daily_tracks.process_next() is True
            lost = restarted.get(f"/api/daily-tracks/{first_track['id']}").json()
            assert lost["status"] == "blocked"
            assert lost["strategy_session"] == recovered_sessions[-1]
            lost_state = _stored_tracking_activation(
                settings,
                str(first_track["id"]),
            )
            assert lost_state["current_checkpoint_session"].isoformat() == (
                recovered_sessions[-1]
            )
            assert lost_state["checkpoint_count"] == 2
            assert lost_state["blocked_progression_count"] == 1
            assert lost_state["latest_attempt_failure_reason"] == "WorkerLost"
            assert lost_state["active_pin_count"] == 0

            retry_lost = restarted.post(
                f"/api/daily-tracks/{first_track['id']}/retry",
                json={"request_id": "track-recovery-lost-worker-retry"},
            )
            assert retry_lost.status_code == 202
            completed = _run_worker_once(settings)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            release_stale_worker.set()
            assert stale_future.result(timeout=20) is True

        final = restarted.get(f"/api/daily-tracks/{first_track['id']}").json()
        assert final["status"] == "active"
        assert final["strategy_session"] == stale_sessions[-1]
        assert [
            observation["session"] for observation in final["strategy"]["observations"]
        ] == list(stale_sessions)

        for index, track in enumerate((first_track, control_track)):
            stopped = restarted.post(
                f"/api/daily-tracks/{track['id']}/stop",
                json={"request_id": f"track-recovery-cache-stop-{index}"},
            )
            assert stopped.status_code == 202

        cache_run_ids: list[str] = []
        for index in range(2):
            accepted = restarted.post(
                "/api/definitions/run",
                json=_run_command(f"track-recovery-cache-seed-{index}"),
            )
            assert accepted.status_code == 200
            cache_run_ids.append(str(accepted.json()["run"]["id"]))
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
        intact_detail = restarted.get(
            f"/api/daily-tracks/{first_track['id']}"
        ).json()
        cache_detail = restarted.get(
            f"/api/daily-tracks/{control_track['id']}"
        ).json()
        assert intact_detail["factor"] == cache_detail["factor"]
        assert intact_detail["strategy"] == cache_detail["strategy"]
        assert cache_detail["strategy_session"] == cache_sessions[-1]
        assert [
            item["session"] for item in cache_detail["strategy"]["observations"]
        ] == list(cache_sessions)
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
        checkpoint_manifest = str(
            authoritative["current_checkpoint_manifest_sha256"]
        )
        _remove_manifest_object_reference(settings, checkpoint_manifest)
        unavailable_sessions = (*cache_sessions, "2026-08-24")
        _publish_head(
            settings,
            sessions=unavailable_sessions,
            price_offset=4,
            expected_manifest=cache_head,
        )
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        intact_after_failure = restarted.get(
            f"/api/daily-tracks/{control_track['id']}"
        ).json()
        assert intact_after_failure["strategy_session"] == unavailable_sessions[-1]
        unavailable = restarted.get(f"/api/daily-tracks/{first_track['id']}")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"detail": "DailyTrack detail is unavailable"}
        unavailable_state = _stored_tracking_activation(
            settings,
            str(first_track["id"]),
        )
        assert unavailable_state["track_status"] == "blocked"
        assert unavailable_state["current_checkpoint_session"].isoformat() == (
            cache_sessions[-1]
        )
        assert unavailable_state["checkpoint_count"] == authoritative[
            "checkpoint_count"
        ]
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
    migrate_core(settings.database_url)
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
    alpha = {
        "operator_id": "ts_mean",
        "operands": [
            {"field_id": "price.close.adjusted"},
            {"literal": 2},
        ],
    }

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("forward-only-seed-run", alpha=alpha),
        )
        assert accepted.status_code == 200
        run_id = str(accepted.json()["run"]["id"])
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
        assert _position_ids(before_state["terminal_strategy_state"]) == {
            "equity:000001.SZ"
        }

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
        ).current_head()
        assert correction_head is not None
        assert correction_head.generation_manifest_sha256 != seed_head
        assert correction_head.data_through_session == seed_sessions[-1]

        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert _tracking_checkpoint_history(settings, track_id) == before_history
        unchanged_state = _stored_tracking_activation(settings, track_id)
        assert unchanged_state["current_checkpoint_manifest_sha256"] == before_state[
            "current_checkpoint_manifest_sha256"
        ]
        assert _checkpoint_payload(runtime.publication, unchanged_state) == before_payload
        assert client.get(f"/api/daily-tracks/{track_id}").json() == before_detail
        overview = client.get("/api/data")
        assert overview.status_code == 200
        assert set(overview.json()) == {
            "dataset_coverage",
            "data_through_session",
            "last_refresh_at",
            "readiness",
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
        completed = _run_worker_once(settings)
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
        assert _position_ids(impact_state["terminal_strategy_state"]) == {
            "equity:000002.SZ"
        }

        counterfactual_prior = restore_tracking_origin(
            TrackingOrigin.model_validate(before_state["origin"]),
            before_state["terminal_strategy_state"],
            seed_canonical,
        )
        uncorrected_impact = _two_instrument_canonical(
            impact_sessions,
            corrected=False,
        )
        counterfactual = advance(
            AdvanceInput(
                prior_state=counterfactual_prior,
                target_canonical_release=uncorrected_impact,
                appended_sessions=list(impact_sessions[len(seed_sessions) :]),
                continuation=advance_continuation(
                    run_input=counterfactual_prior.run_input_with_canonical(
                        seed_canonical
                    ),
                    prior_continuation=empty_continuation(),
                    target_canonical=seed_canonical,
                    appended_sessions=list(seed_sessions),
                ),
                calculation_scope="forward_tracking",
            )
        )
        assert _position_ids(terminal_strategy_state(counterfactual)) == {
            "equity:000001.SZ"
        }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_keeps_its_pinned_generation_when_head_moves(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)
    canonical_a = MountedGenerationStore(settings.data_mount).open_generation(head_a).canonical
    claimed = Event()
    continue_execution = Event()

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-pinned-head"),
        )
        run_id = accepted.json()["run"]["id"]
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
            progress=barrier,
        )
        worker = Thread(target=processor.process_next)
        worker.start()
        assert claimed.wait(timeout=5)
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
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
def test_insufficient_warmup_is_one_terminal_domain_failure(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(
                "attempt-insufficient-warmup",
                alpha={
                    "operator_id": "ts_mean",
                    "operands": [
                        {"field_id": "price.close.adjusted"},
                        {"literal": 2},
                    ],
                },
            ),
        )
        run_id = accepted.json()["run"]["id"]

        assert client.app.state.core_runtime.research_runs.process_next() is True
        assert client.app.state.core_runtime.research_runs.process_next() is False

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail == {
            "id": run_id,
            "status": "failed",
            "definition_id": detail["definition_id"],
            "definition_revision": 1,
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "failure_reason": (
                "Selected data does not contain the complete Calculation Warm-up."
            ),
        }
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_count"] == 1
        assert stored["attempt_failure_reason"] == "InsufficientCalculationWarmup"
        assert stored["result_manifest_sha256"] is None
        assert stored["result_provenance"] is None
        assert stored["active_pin_count"] == 0


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
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04")[:session_count]
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(
                f"attempt-short-{session_count}",
                start_date=sessions[0],
                end_date=sessions[-1],
            ),
        )
        run_id = accepted.json()["run"]["id"]
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
def test_attempt_revalidates_the_selected_generation(
    tmp_path: Path,
    incompatibility: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(f"attempt-revalidate-{incompatibility}"),
        )
        run_id = accepted.json()["run"]["id"]
        replacement_sessions = sessions[1:] if incompatibility == "coverage" else sessions
        _publish_head(
            settings,
            sessions=replacement_sessions,
            price_offset=2,
            expected_manifest=head_a,
            available_field_id=(
                "market.volume.shares"
                if incompatibility == "field"
                else "price.close.adjusted"
            ),
        )

        assert client.app.state.core_runtime.research_runs.process_next() is True
        assert client.app.state.core_runtime.research_runs.process_next() is False

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        assert detail["start_date"] == sessions[0]
        assert detail["end_date"] == sessions[-1]
        assert detail["failure_reason"] == (
            "Current data cannot execute the requested Research Period."
        )
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_count"] == 1
        assert stored["attempt_failure_reason"] == "SelectedDataInvalid"
        assert stored["result_manifest_sha256"] is None
        assert stored["active_pin_count"] == 0


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
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(f"attempt-publication-failure-{failure_stage}"),
        )
        run_id = accepted.json()["run"]["id"]
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
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-denied-rustfs-write"),
        )
        run_id = accepted.json()["run"]["id"]
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
        )
        manifest_count = _publication_manifest_count(settings)

        assert processor.process_next() is True
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


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_result_read_failure_stays_sanitized(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-result-read-failure"),
        )
        run_id = accepted.json()["run"]["id"]
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
    alpha: dict[str, object] | None = None,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-05",
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "name": "Attempt-scoped current data",
        "start_date": start_date,
        "end_date": end_date,
        "alpha": alpha or {"field_id": "price.close.adjusted"},
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
                    "close_adj"
                    if available_field_id == "price.close.adjusted"
                    else "volume_shares"
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
    anchors: list[dict[str, object]] = []
    industries: list[dict[str, object]] = []
    for instrument_id, ts_code in zip(instrument_ids, ts_codes, strict=True):
        instrument = copy.deepcopy(template["instruments"][0])
        instrument.update(instrument_id=instrument_id, ts_code=ts_code)
        instruments.append(instrument)
        anchor = copy.deepcopy(template["adjustment_anchors"][0])
        anchor["instrument_id"] = instrument_id
        anchors.append(anchor)
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
        closes = (
            ("1", "30")
            if corrected and session == "2026-08-05"
            else ("20", "10")
        )
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
        "adjustment_anchors": anchors,
        "industry_membership": industries,
        "research_calendar": list(sessions),
        "prices": prices,
        "trading_states": states,
        "price_limits": limits,
        "base_pool": [
            {"session": session, "instrument_ids": list(instrument_ids)}
            for session in sessions
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
        "anchor_daily": [
            row
            for row in daily
            if row["trade_date"] == str(calendar[0]).replace("-", "")
        ],
        "anchor_adjustments": [
            {
                "ts_code": instrument["ts_code"],
                "trade_date": str(calendar[0]).replace("-", ""),
                "adj_factor": "1",
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
        "version": 1,
        "request_start": request_start,
        "request_end": str(calendar[-1]),
        "known_ts_codes": sorted(
            str(instrument["ts_code"])
            for instrument in instruments
            if isinstance(instrument, dict)
        ),
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
        canonical_data=canonical,
        alpha_expression={"field_id": "price.close.adjusted"},
        field_bindings={"price.close.adjusted": "close_adj"},
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
    return {
        str(position["instrument_id"])
        for position in positions
        if isinstance(position, dict)
    }


def _expire_current_tracking_attempt(settings: CoreSettings, track_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            expired = transaction.execute(
                """
                UPDATE daily_tracks.session_progression_attempts
                SET lease_expires_at = now() - interval '1 second'
                WHERE track_id = %s AND status = 'running'
                """,
                (track_id,),
            )
        assert expired.rowcount == 1
    finally:
        database.close()


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
    raise AssertionError(
        f"DailyTrack lease was not renewed; latest attempt timing was {latest!r}"
    )


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


def _run_worker_once(settings: CoreSettings) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
    }
    return subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )


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

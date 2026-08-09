from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

import boto3
import pytest
from botocore.config import Config
from core_runtime import create_migrated_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import DailyTrackService, TrackingOrigin
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
        assert set(public_run["result"]) == {"factor", "strategy", "provenance"}
        assert set(public_run["result"]["provenance"]) == {
            "schema_version",
            "research_run_id",
            "immutable_input_sha256",
            "calculation_contracts",
            "semantic_versions",
        }
        assert len(public_run["result"]["strategy"]["observations"]) == 3
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
            next_release=runtime.data.next_release,
            load_canonical=runtime.data.load_canonical,
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

        assert runtime.daily_tracks.process_next() is True
        assert client.app.state.core_runtime.daily_tracks.process_next() is False

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
            next_release=runtime.data.next_release,
            load_canonical=runtime.data.load_canonical,
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
                SELECT state.origin_session,
                       track.origin,
                       checkpoint.boundary_session AS current_checkpoint_session,
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
                        FROM daily_tracks.session_progression_attempts
                        WHERE track_id = state.track_id
                          AND status = 'cancelled') AS cancelled_attempt_count,
                       (SELECT count(*)
                        FROM data.generation_pins
                        WHERE status = 'active') AS active_pin_count
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


def _s3_client(settings: CoreSettings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )

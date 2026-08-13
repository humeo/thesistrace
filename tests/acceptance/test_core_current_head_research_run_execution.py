from __future__ import annotations

import copy
import hashlib
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
    KernelRunError,
    RunInput,
    advance,
    advance_continuation,
    continuation_snapshot,
    empty_continuation,
    run,
)
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.result import build_result_payload, read_result_bundle
from thesistrace.research_series import (
    AlignedResearchData,
    research_sessions,
    slice_research_sessions,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_composite_alpha_runs_through_http_claim_worker_and_publication(
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
    )
    generation_id = _publish_composite_head(settings, sessions=sessions)
    alpha = {
        "operator_id": "add",
        "operands": [
            {
                "operator_id": "cs_rank",
                "operands": [{"field_id": "price.close.adjusted"}],
            },
            {
                "operator_id": "cs_rank",
                "operands": [{"field_id": "total_revenue_latest_fy"}],
            },
        ],
    }

    with TestClient(create_app(settings)) as client:
        options = client.get("/api/definitions/authoring-options").json()
        assert "cs_rank" in {item["operator_id"] for item in options["operators"]}
        assert {
            "total_revenue_latest_fy",
            "net_profit_parent_latest_fy",
            "operating_cash_flow_latest_fy",
            "total_assets_latest_reported",
            "total_liabilities_latest_reported",
            "equity_parent_latest_reported",
        } <= {item["field_id"] for item in options["fields"]}
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("composite-e2e", alpha=alpha),
        )
        assert accepted.status_code == 200
        assert accepted.json()["outcome"] == "accepted"
        run_id = accepted.json()["run"]["id"]

        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr

        detail = client.get(f"/api/research-runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "succeeded"
        assert len(detail.json()["result"]["strategy"]["observations"]) == 3
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_data_generation_id"] == generation_id
        assert stored["attempt_status"] == "succeeded"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_financial_cutoff_rejects_only_financial_formula_before_queueing(
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
    )
    _publish_composite_head(
        settings,
        sessions=sessions,
        financial_through="2026-08-04",
    )

    with TestClient(create_app(settings)) as client:
        financial = client.post(
            "/api/definitions/run",
            json=_run_command(
                "financial-cutoff",
                alpha={"field_id": "total_revenue_latest_fy"},
            ),
        ).json()
        market = client.post(
            "/api/definitions/run",
            json=_run_command("market-past-financial-cutoff"),
        ).json()

    assert financial["outcome"] == "rejected"
    assert financial["issues"] == [
        {
            "code": "FINANCIAL_CALCULATION_OUTSIDE_COVERAGE",
            "field": "alpha",
            "message": "Financial Alpha calculation slice exceeds Financial Coverage",
        }
    ]
    assert market["outcome"] == "accepted"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_financial_daily_track_blocks_at_cutoff_and_resumes_without_rewriting_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    seed_head = _publish_composite_head(
        settings,
        sessions=seed_sessions,
        operation_id="financial-track-seed",
    )
    composite_alpha = {
        "operator_id": "add",
        "operands": [
            {
                "operator_id": "cs_rank",
                "operands": [{"field_id": "price.close.adjusted"}],
            },
            {
                "operator_id": "cs_rank",
                "operands": [{"field_id": "total_revenue_latest_fy"}],
            },
        ],
    }

    with TestClient(create_app(settings)) as client:
        track_ids: dict[str, str] = {}
        for name, alpha in (
            ("financial", composite_alpha),
            ("market", {"field_id": "price.close.adjusted"}),
        ):
            accepted = client.post(
                "/api/definitions/run",
                json=_run_command(f"{name}-track-seed", alpha=alpha),
            )
            assert accepted.status_code == 200
            run_id = str(accepted.json()["run"]["id"])
            assert client.app.state.core_runtime.research_runs.process_next() is True
            activated = client.post(
                f"/api/research-runs/{run_id}/daily-tracks",
                json={"request_id": f"{name}-track-activation"},
            )
            assert activated.status_code == 201
            track_ids[name] = str(activated.json()["id"])

        lagged_sessions = (*seed_sessions, "2026-08-06", "2026-08-07")
        lagged_head = _publish_composite_head(
            settings,
            sessions=lagged_sessions,
            financial_through="2026-08-06",
            expected_manifest=seed_head,
            operation_id="financial-track-lagged",
        )
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr

        blocked = client.get(f"/api/daily-tracks/{track_ids['financial']}").json()
        assert blocked["status"] == "blocked"
        assert blocked["strategy_session"] == "2026-08-06"
        assert blocked["blocked_reason"] == (
            "Financial Coverage ends before the next Research Session."
        )
        market = client.get(f"/api/daily-tracks/{track_ids['market']}").json()
        assert market["status"] == "active"
        assert market["strategy_session"] == "2026-08-07"
        before_history = _tracking_checkpoint_history(settings, track_ids["financial"])
        assert [item["boundary_session"] for item in before_history] == [
            "2026-08-05",
            "2026-08-06",
        ]
        blocked_state = _stored_tracking_activation(settings, track_ids["financial"])
        assert blocked_state["latest_attempt_failure_reason"] == "FinancialCoverageUnavailable"
        assert blocked_state["active_pin_count"] == 0

        recovered_sessions = (*lagged_sessions, "2026-08-10")
        recovered_head = _publish_composite_head(
            settings,
            sessions=recovered_sessions,
            financial_through=recovered_sessions[-1],
            expected_manifest=lagged_head,
            operation_id="financial-track-recovered",
        )
        retry = client.post(
            f"/api/daily-tracks/{track_ids['financial']}/retry",
            json={"request_id": "financial-track-retry"},
        )
        assert retry.status_code == 202
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr

        recovered = client.get(f"/api/daily-tracks/{track_ids['financial']}").json()
        assert recovered["status"] == "active"
        assert recovered["strategy_session"] == recovered_sessions[-1]
        after_history = _tracking_checkpoint_history(settings, track_ids["financial"])
        assert after_history[:2] == before_history
        assert [item["boundary_session"] for item in after_history] == [
            "2026-08-05",
            "2026-08-06",
            "2026-08-10",
        ]
        final_state = _stored_tracking_activation(settings, track_ids["financial"])
        origin = TrackingOrigin.model_validate(final_state["origin"])
        calculation_sessions = list(recovered_sessions[3:])
        research_data = (
            MountedGenerationStore(settings.data_mount)
            .read_composite_slice(
                recovered_head,
                sessions=calculation_sessions,
                universe_name="top300",
                neutralization="none",
                field_bindings={
                    str(key): str(value)
                    for key, value in origin.immutable_input["field_bindings"].items()
                },
            )
            .research_data
        )
        seed_research_data = slice_research_sessions(
            research_data,
            calculation_sessions[:3],
        )
        reference_origin = restore_tracking_origin(
            origin,
            origin.initial_strategy_state.model_dump(mode="json"),
            seed_research_data,
        )
        reference = advance(
            AdvanceInput(
                prior_state=reference_origin,
                target_research_data=research_data,
                appended_sessions=calculation_sessions[3:],
                continuation=advance_continuation(
                    run_input=reference_origin.run_input_with_research_data(seed_research_data),
                    prior_continuation=empty_continuation(),
                    target_research_data=seed_research_data,
                    appended_sessions=calculation_sessions[:3],
                ),
                calculation_scope="forward_tracking",
            )
        )
        first_incremental_data = slice_research_sessions(
            research_data,
            calculation_sessions[:4],
        )
        incremental = advance(
            AdvanceInput(
                prior_state=reference_origin,
                target_research_data=first_incremental_data,
                appended_sessions=[calculation_sessions[3]],
                continuation=advance_continuation(
                    run_input=reference_origin.run_input_with_research_data(seed_research_data),
                    prior_continuation=empty_continuation(),
                    target_research_data=seed_research_data,
                    appended_sessions=calculation_sessions[:3],
                ),
                calculation_scope="forward_tracking",
            )
        )
        incremental = advance(
            AdvanceInput(
                prior_state=incremental,
                target_research_data=research_data,
                appended_sessions=calculation_sessions[4:],
                continuation=continuation_snapshot(incremental),
                calculation_scope="forward_tracking",
            )
        )
        assert (
            incremental.output_snapshot()["alpha_matrix"]
            == reference.output_snapshot()["alpha_matrix"]
        )
        assert terminal_strategy_state(incremental) == terminal_strategy_state(reference)
        expected_checkpoint = project_tracking_checkpoint(
            reference,
            retained_strategy_sessions=calculation_sessions[3:],
        )
        assert (
            _checkpoint_payload(
                client.app.state.core_runtime.publication,
                final_state,
            )
            == expected_checkpoint
        )
        proof = client.app.state.core_runtime.daily_tracks.verify_persisted_equivalence(
            track_ids["financial"]
        )
        assert proof.status == "equivalent"
        assert proof.head_session == recovered_sessions[-1]

        stopped = client.post(
            f"/api/daily-tracks/{track_ids['market']}/stop",
            json={"request_id": "financial-track-stop-market-control"},
        )
        assert stopped.status_code == 202
        opened_session_slices: list[tuple[str, ...]] = []
        original_read_composite_slice = MountedGenerationStore.read_composite_slice

        def record_composite_slice(
            store: MountedGenerationStore,
            manifest_sha256: str,
            *,
            sessions: list[str],
            universe_name: str,
            neutralization: str,
            field_bindings: dict[str, str],
        ):
            opened_session_slices.append(tuple(sessions))
            return original_read_composite_slice(
                store,
                manifest_sha256,
                sessions=sessions,
                universe_name=universe_name,
                neutralization=neutralization,
                field_bindings=field_bindings,
            )

        monkeypatch.setattr(
            MountedGenerationStore,
            "read_composite_slice",
            record_composite_slice,
        )
        processor = DailyTrackService(
            client.app.state.core_runtime.database,
            publication=client.app.state.core_runtime.publication,
            dataset_lifecycle=DatasetLifecycle(
                client.app.state.core_runtime.database,
                settings.data_mount,
            ),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            working_cache_root=tmp_path / "financial-track-working-cache",
        )
        cold_sessions = (
            *recovered_sessions,
            *_weekday_sessions_after(
                date.fromisoformat(recovered_sessions[-1]),
                count=25,
            ),
        )
        cold_head = _publish_composite_head(
            settings,
            sessions=cold_sessions,
            expected_manifest=recovered_head,
            operation_id="financial-track-cold-cache-rebuild",
        )
        assert processor.process_next() is True
        warm_sessions = (
            *cold_sessions,
            *_weekday_sessions_after(date.fromisoformat(cold_sessions[-1]), count=1),
        )
        _publish_composite_head(
            settings,
            sessions=warm_sessions,
            expected_manifest=cold_head,
            operation_id="financial-track-warm-cache-advance",
        )
        assert processor.process_next() is True
        assert opened_session_slices[-1] == tuple(warm_sessions[3:])


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_uses_the_generation_frozen_at_admission(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
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
            "draft",
            "result",
        }
        assert public_run["draft"] == {
            "name": "Attempt-scoped current data",
            "hypothesis": None,
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "alpha": {"field_id": "price.close.adjusted"},
            "universe": "top300",
            "neutralization": "none",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
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
        restored_c = restore_tracking_checkpoint(
            checkpoint_c,
            research_data=prior_d,
        )
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
        assert stopped_state["current_checkpoint_session"].isoformat() == (latest_sessions[-1])
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
def test_use_as_draft_submits_frozen_values_through_ordinary_run_admission(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        source = client.post(
            "/api/definitions/run",
            json=_run_command("use-as-draft-source"),
        ).json()["run"]
        assert client.app.state.core_runtime.research_runs.process_next() is True
        frozen_draft = client.get(f"/api/research-runs/{source['id']}").json()["draft"]
        head_b = _publish_head(
            settings,
            sessions=sessions,
            price_offset=4,
            expected_manifest=head_a,
        )

        copied = client.post(
            "/api/definitions/run",
            json={"request_id": "use-as-draft-copy", **frozen_draft},
        )

        assert copied.status_code == 200
        assert copied.json()["outcome"] == "accepted"
        copied_run_id = copied.json()["run"]["id"]
        assert copied_run_id != source["id"]
        copied_input = _stored_run_input(settings, copied_run_id)
        assert copied_input["definition"]["content"] == frozen_draft
        assert copied_input["data_generation_manifest_sha256"] == head_b


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_current_data_track_limit_releases_capacity_after_stop(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
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
        assert len([item for item in final_tracks if item["status"] in {"active", "blocked"}]) == 10


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
        assert failed_state["current_checkpoint_session"].isoformat() == (seed_sessions[-1])
        assert failed_state["checkpoint_count"] == 1
        assert failed_state["blocked_progression_count"] == 1
        assert failed_state["failed_attempt_count"] == 1
        assert failed_state["active_pin_count"] == 0

        completed = _run_worker_once(settings)
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
            assert lost_state["current_checkpoint_session"].isoformat() == (recovered_sessions[-1])
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
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
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

        completed = _run_worker_once(settings)
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
        assert _position_ids(impact_state["terminal_strategy_state"]) == {"equity:000002.SZ"}

        counterfactual_prior = restore_tracking_origin(
            TrackingOrigin.model_validate(before_state["origin"]),
            before_state["terminal_strategy_state"],
            _research_data(seed_canonical),
        )
        uncorrected_impact = _two_instrument_canonical(
            impact_sessions,
            corrected=False,
        )
        counterfactual = advance(
            AdvanceInput(
                prior_state=counterfactual_prior,
                target_research_data=_research_data(uncorrected_impact),
                appended_sessions=list(impact_sessions[len(seed_sessions) :]),
                continuation=advance_continuation(
                    run_input=counterfactual_prior.run_input_with_research_data(
                        _research_data(seed_canonical)
                    ),
                    prior_continuation=empty_continuation(),
                    target_research_data=_research_data(seed_canonical),
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
def test_working_cache_and_cold_rebuild_match_after_dependency_correction(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = _weekday_sessions_after(date(2026, 6, 30), count=25)
    seed_head = _publish_canonical_head(
        settings,
        _two_instrument_canonical(seed_sessions, corrected=False),
        operation_id="cache-correction-seed",
    )
    alpha = {
        "operator_id": "ts_mean",
        "operands": [
            {"field_id": "price.close.adjusted"},
            {"literal": 20},
        ],
    }

    with TestClient(create_app(settings)) as client:
        track_ids: list[str] = []
        for index in range(2):
            accepted = client.post(
                "/api/definitions/run",
                json=_run_command(
                    f"cache-correction-run-{index}",
                    alpha=alpha,
                    start_date=seed_sessions[20],
                    end_date=seed_sessions[-1],
                ),
            )
            assert accepted.status_code == 200
            completed = _run_worker_once(settings)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            tracking = client.post(
                f"/api/research-runs/{accepted.json()['run']['id']}/daily-tracks",
                json={"request_id": f"cache-correction-track-{index}"},
            )
            assert tracking.status_code == 201
            track_ids.append(str(tracking.json()["id"]))

        runtime = client.app.state.core_runtime
        cache_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            working_cache_root=tmp_path / "correction-working-cache",
        )
        cold_processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )
        first_sessions = (
            *seed_sessions,
            *_weekday_sessions_after(date.fromisoformat(seed_sessions[-1]), count=500),
        )
        first_head = _publish_canonical_head(
            settings,
            _two_instrument_canonical(first_sessions, corrected=False),
            operation_id="cache-correction-mature",
            expected_manifest=seed_head,
        )
        assert cache_processor.process_next() is True
        assert cold_processor.process_next() is True

        corrected_sessions = (
            *first_sessions,
            *_weekday_sessions_after(date.fromisoformat(first_sessions[-1]), count=1),
        )
        _publish_canonical_head(
            settings,
            _two_instrument_canonical(corrected_sessions, corrected=True),
            operation_id="cache-correction-historical-row",
            expected_manifest=first_head,
        )
        assert cache_processor.process_next() is True
        assert cold_processor.process_next() is True

        cached_state = _stored_tracking_activation(settings, track_ids[0])
        cold_state = _stored_tracking_activation(settings, track_ids[1])
        assert _checkpoint_payload(
            runtime.publication,
            cached_state,
        ) == _checkpoint_payload(runtime.publication, cold_state)


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
            "/api/definitions/run",
            json=_run_command("attempt-pinned-head"),
        )
        run_id = accepted.json()["run"]["id"]
        runtime = client.app.state.core_runtime

        def barrier(stage: str, _run_id: str) -> None:
            if stage == "claimed":
                claimed.set()
                assert continue_execution.wait(timeout=30)

        processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            progress=barrier,
        )
        worker = Thread(target=processor.process_next)
        worker.start()
        try:
            assert claimed.wait(timeout=5)
            assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
            replay_root = tmp_path / "attempt-refresh-replay"
            replay_root.mkdir()
            canonical_b = _canonical(
                sessions,
                price_offset=9,
                available_field_id="price.close.adjusted",
            )
            refreshed = _refresh_via_private_operator(
                settings,
                replay_root=replay_root,
                idempotency_key="attempt-pinned-refresh",
                canonical=canonical_b,
                request_start=sessions[0],
                include_industry_membership=False,
            )
            assert refreshed["outcome"] == "published"
            pointer = DatasetLifecycle(runtime.database, settings.data_mount).current_pointer()
            assert pointer is not None
            head_b = pointer.generation_manifest_sha256
        finally:
            continue_execution.set()
            worker.join(timeout=15)
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
def test_claim_commits_before_generation_parquet_is_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)
    generation_opened = Event()
    allow_generation_open = Event()
    opened_generations: list[str] = []
    worker_errors: list[BaseException] = []

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("claim-before-generation-open"),
        )
        assert accepted.status_code == 200
        run_id = accepted.json()["run"]["id"]
        runtime = client.app.state.core_runtime
        original_read_composite_slice = MountedGenerationStore.read_composite_slice

        def blocking_read_composite_slice(
            store: MountedGenerationStore,
            manifest_sha256: str,
            *,
            sessions: list[str],
            universe_name: str,
            neutralization: str,
            field_bindings: dict[str, str],
        ):
            opened_generations.append(manifest_sha256)
            generation_opened.set()
            if not allow_generation_open.wait(timeout=10):
                raise AssertionError("Generation open was not released by the test")
            return original_read_composite_slice(
                store,
                manifest_sha256,
                sessions=sessions,
                universe_name=universe_name,
                neutralization=neutralization,
                field_bindings=field_bindings,
            )

        monkeypatch.setattr(
            MountedGenerationStore,
            "read_composite_slice",
            blocking_read_composite_slice,
        )
        processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
        )

        def process_one() -> None:
            try:
                processor.process_next()
            except BaseException as error:  # pragma: no cover - asserted below
                worker_errors.append(error)

        worker = Thread(target=process_one)
        worker.start()
        try:
            assert generation_opened.wait(timeout=5)
            status_during_generation_open = client.get(f"/api/research-runs/{run_id}").json()[
                "status"
            ]
        finally:
            allow_generation_open.set()
            worker.join(timeout=15)

        assert not worker.is_alive()
        assert worker_errors == []
        assert status_during_generation_open == "running"
        assert len(opened_generations) == 1
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "succeeded"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_daily_track_claim_commits_before_generation_parquet_is_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)
    generation_opened = Event()
    allow_generation_open = Event()
    worker_errors: list[BaseException] = []

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("daily-track-claim-before-generation-open"),
        )
        assert accepted.status_code == 200
        run_id = accepted.json()["run"]["id"]
        runtime = client.app.state.core_runtime
        assert runtime.research_runs.process_next() is True
        activated = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "daily-track-claim-before-generation-open"},
        )
        assert activated.status_code == 201
        track_id = activated.json()["id"]
        target_sessions = (*seed_sessions, "2026-08-06")
        target_head = _publish_head(
            settings,
            sessions=target_sessions,
            price_offset=1,
            expected_manifest=seed_head,
        )
        original_read_composite_slice = MountedGenerationStore.read_composite_slice

        def blocking_read_composite_slice(
            store: MountedGenerationStore,
            manifest_sha256: str,
            *,
            sessions: list[str],
            universe_name: str,
            neutralization: str,
            field_bindings: dict[str, str],
        ):
            generation_opened.set()
            if not allow_generation_open.wait(timeout=10):
                raise AssertionError("Generation open was not released by the test")
            return original_read_composite_slice(
                store,
                manifest_sha256,
                sessions=sessions,
                universe_name=universe_name,
                neutralization=neutralization,
                field_bindings=field_bindings,
            )

        monkeypatch.setattr(
            MountedGenerationStore,
            "read_composite_slice",
            blocking_read_composite_slice,
        )
        processor = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
        )

        def process_one() -> None:
            try:
                processor.process_next()
            except BaseException as error:  # pragma: no cover - asserted below
                worker_errors.append(error)

        worker = Thread(target=process_one)
        worker.start()
        try:
            assert generation_opened.wait(timeout=5)
            with runtime.database.transaction() as transaction:
                committed_claim = transaction.execute(
                    """
                    SELECT attempt.status AS attempt_status,
                           progression.status AS progression_status,
                           attempt.data_generation_id,
                           pin.status AS pin_status
                    FROM daily_tracks.session_progression_attempts AS attempt
                    JOIN daily_tracks.session_progressions AS progression
                      ON progression.id = attempt.progression_id
                    JOIN data.generation_pins AS pin
                      ON pin.id = attempt.generation_pin_id
                    WHERE progression.track_id = %s
                    ORDER BY attempt.ordinal DESC
                    LIMIT 1
                    """,
                    (track_id,),
                ).fetchone()
        finally:
            allow_generation_open.set()
            worker.join(timeout=15)

        assert committed_claim is not None
        assert committed_claim["attempt_status"] == "running"
        assert committed_claim["progression_status"] == "running"
        assert committed_claim["data_generation_id"] == target_head
        assert committed_claim["pin_status"] == "active"
        assert not worker.is_alive()
        assert worker_errors == []
        assert (
            client.get(f"/api/daily-tracks/{track_id}").json()["strategy_session"]
            == (target_sessions[-1])
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_insufficient_warmup_is_one_terminal_domain_failure(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
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
        draft = detail.pop("draft")
        assert draft["alpha"]["operator_id"] == "ts_mean"
        assert detail == {
            "id": run_id,
            "status": "failed",
            "definition_id": detail["definition_id"],
            "definition_revision": 1,
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "failure_reason": ("Selected data does not contain the complete Calculation Warm-up."),
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
    initialize_core(settings.database_url)
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
    initialize_core(settings.database_url)
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
    initialize_core(settings.database_url)
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


def _write_refresh_replay(
    path: Path,
    canonical: dict[str, object],
    *,
    request_start: str,
    include_industry_membership: bool = True,
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
        ]
        if include_industry_membership
        else [],
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
    include_industry_membership: bool = True,
) -> dict[str, object]:
    calendar = canonical["research_calendar"]
    assert isinstance(calendar, list) and calendar
    replay = replay_root / f"{idempotency_key}.json"
    _write_refresh_replay(
        replay,
        canonical,
        request_start=request_start,
        include_industry_membership=include_industry_membership,
    )
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
    expected_manifest: str | None = None,
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
            expected_generation_manifest_sha256=expected_manifest,
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
    market_store = MountedGenerationStore(settings.data_mount)
    market = market_store.materialize(
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
            (
                ("equity:000001.SZ", "000001.SZ"),
                ("equity:000002.SZ", "000002.SZ"),
            )
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
                "source_contract_version": "tushare-financial-ordinary-v1",
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
        endpoint_fields=tuple(
            (endpoint, endpoint_fields[endpoint])
            for endpoint in ("income", "balancesheet", "cashflow")
        ),
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
    composite = market_store.compose_financial_candidate(
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


def _research_data(canonical: dict[str, object]) -> AlignedResearchData:
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


def _stored_run_input(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT immutable_input FROM research_runs.runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        assert row is not None
        return dict(row["immutable_input"])
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

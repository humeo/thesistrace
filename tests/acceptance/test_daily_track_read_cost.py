"""Deterministic persisted-history benchmark, without rerunning 1000 solver tasks."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter

import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas
from core_runtime import create_initialized_test_app as create_app
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _checkpoint_payload,
    _stored_tracking_activation,
)
from test_core_daily_track_detail import (
    _business_sessions,
    _publish_head,
    _refresh_daily_track,
    _run_command,
)

from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.daily_track.models import DailyTrackStrategyObservationsResultSectionInput
from thesistrace.daily_track.observation_state import (
    TrackingObservationState,
    advance_tracking_observation_state,
)
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication import CompressedJsonPayload, Publication, PublishedRef


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
def test_daily_track_read_cost_is_bounded_at_1000_advances(
    tmp_path: Path, monkeypatch, record_property
):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2020, 1, 2), count=1003)
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (BenchmarkLevel("2010-01-04", "3500"), *(BenchmarkLevel(day, "4000") for day in sessions)),
        published_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    head = _publish_head(
        settings, sessions=sessions[:3], expected_manifest=None, operation_id="cost-seed"
    )
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = client.post(
            "/api/research-runs",
            json=_run_command(
                "cost-run",
                start_date=sessions[0],
                end_date=sessions[2],
            ),
        ).json()["id"]
        assert runtime.research_runs.process_next()
        track_id = client.post(
            f"/api/research-runs/{run_id}/daily-tracks", json={"request_id": "cost-track"}
        ).json()["id"]
        head = _publish_head(
            settings, sessions=sessions[:4], expected_manifest=head, operation_id="cost-first"
        )
        _refresh_daily_track(client, track_id, "cost-refresh")
        assert runtime.daily_tracks.process_next()
        stored = _stored_tracking_activation(settings, track_id)
        template = _checkpoint_payload(runtime.publication, stored)
        prior_manifest = stored["current_checkpoint_manifest_sha256"]
        terminal = stored["terminal_strategy_state"]
        state = TrackingObservationState.model_validate(template["tracking_observation_state"])
        _publish_head(
            settings, sessions=sessions, expected_manifest=head, operation_id="cost-calendar"
        )
        coordinates = runtime.daily_track_sessions
        metrics = []
        for index in range(4, len(sessions)):
            day, prior_day = sessions[index], sessions[index - 1]
            checkpoint = copy.deepcopy(template)
            rows = [
                dict(template["strategy_state"]["retained_delta"][-1], session=session)
                for session in (prior_day, day)
            ]
            if index in {4, 500}:
                rows[0]["net_nav"] = str(Decimal(rows[0]["net_nav"]) * Decimal("0.8"))
            state = advance_tracking_observation_state(state, rows)
            checkpoint.update(
                boundary_session=day, tracking_observation_state=state.model_dump(mode="json")
            )
            checkpoint["strategy_state"]["retained_delta"] = rows
            account = copy.deepcopy(terminal)
            account["session"] = day
            account["last_daily_observation"]["session"] = day
            account["metric_state"]["last_session"] = day
            account["pending_signal"] = None
            account["rebalance_phase"]["report_session_count"] = index + 1
            provenance = dict(
                stored["current_checkpoint_provenance"],
                boundary_session=day,
                predecessor_manifest_sha256=prior_manifest,
            )
            prepared = runtime.publication.prepare(
                kind="daily-track.checkpoint",
                provenance=provenance,
                payloads={"checkpoint": CompressedJsonPayload(checkpoint)},
            )
            with runtime.database.transaction() as tx:
                coordinates.start_progression(
                    tx,
                    progression_id=f"cost-{index}",
                    track_id=track_id,
                    expected_checkpoint_manifest_sha256=prior_manifest,
                    generation_sessions=(date.fromisoformat(prior_day), date.fromisoformat(day)),
                    target_sessions=(date.fromisoformat(day),),
                    planning_data_generation_id=provenance["data_generation_id"],
                    initial_cycle_ordinal=1,
                    provenance={},
                )
                coordinates.start_attempt(
                    tx,
                    attempt_id=f"cost-attempt-{index}",
                    progression_id=f"cost-{index}",
                    ordinal=1,
                    cycle_ordinal=1,
                    cycle_attempt_ordinal=1,
                    fence=1,
                    generation_pin_id=f"cost-pin-{index}",
                    data_generation_id=provenance["data_generation_id"],
                    data_through_session=date.fromisoformat(day),
                    lease_seconds=30,
                )
                published = runtime.publication.record(tx, prepared)
                coordinates.publish_checkpoint(
                    tx,
                    progression_id=f"cost-{index}",
                    attempt_id=f"cost-attempt-{index}",
                    fence=1,
                    checkpoint_manifest_sha256=published.manifest_sha256,
                    terminal_strategy_state=account,
                    provenance=provenance,
                )
            prior_manifest = published.manifest_sha256
            if index - 2 not in {10, 250, 1000}:
                continue
            started = perf_counter()
            full = coordinates.load(track_id)
            full_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            snapshot = coordinates.load_read_snapshot(
                TEST_RESEARCHER.researcher_id, track_id, calendar=list(sessions)
            )
            snapshot_ms = (perf_counter() - started) * 1000
            expected = min(index - 2, 504)
            refs = snapshot["observation_checkpoints"]
            assert len(refs) == expected
            assert all(item["boundary_session"] >= sessions[max(0, index - 503)] for item in refs)
            assert "attempts" not in snapshot and "progressions" not in snapshot
            assert all("terminal_strategy_state" not in item for item in refs)
            # Instrument verified bytes at Publication's actual storage read boundary.
            read_bytes = 0
            read_manifests = []
            read = Publication._read_in_transaction

            def measured(self, *args, _read=read, _manifests=read_manifests, **kwargs):
                nonlocal read_bytes
                bundle = _read(self, *args, **kwargs)
                read_bytes += sum(len(payload.content) for payload in bundle.payloads.values())
                _manifests.append(bundle.manifest_sha256)
                return bundle

            with monkeypatch.context() as patch:
                patch.setattr(Publication, "_read_in_transaction", measured)
                started = perf_counter()
                detail = runtime.daily_tracks.get(TEST_RESEARCHER.researcher_id, track_id)
                detail_ms = (perf_counter() - started) * 1000
            assert detail.strategy_session == day
            assert len(detail.strategy.observations) == min(index + 1, 504)
            if index - 2 == 10:
                page = runtime.daily_tracks.get_result_section(
                    TEST_RESEARCHER.researcher_id,
                    DailyTrackStrategyObservationsResultSectionInput(
                        track_id=track_id,
                        section="strategy_observations",
                        limit=4,
                    ),
                )
                assert str(page.items[-1].net_nav) == str(detail.strategy.observations[3].net_nav)
                assert Decimal(str(page.items[-1].net_nav)) == (
                    Decimal(template["strategy_state"]["retained_delta"][-1]["net_nav"])
                    * Decimal("0.8")
                )
            if index - 2 == 1000:
                assert Decimal(str(detail.strategy.observations[0].net_nav)) == (
                    Decimal(template["strategy_state"]["retained_delta"][-1]["net_nav"])
                    * Decimal("0.8")
                )
                assert set(read_manifests) == {item["manifest_sha256"] for item in refs}
            baseline_bytes = 0
            started = perf_counter()
            for item in full.checkpoints[1:]:
                bundle = runtime.publication.read(
                    PublishedRef(item.manifest_sha256, "daily-track.checkpoint", item.provenance)
                )
                baseline_bytes += sum(len(payload.content) for payload in bundle.payloads.values())
            baseline_ms = (perf_counter() - started) * 1000 + full_ms
            metrics.append(
                {
                    "advances": index - 2,
                    "full_snapshot_bytes": _size(asdict(full)),
                    "bounded_snapshot_bytes": _size(snapshot),
                    "full_checkpoint_bytes": baseline_bytes,
                    "detail_object_bytes": read_bytes,
                    "full_read_ms": round(baseline_ms, 2),
                    "snapshot_ms": round(snapshot_ms, 2),
                    "detail_ms": round(detail_ms, 2),
                    "checkpoint_refs": len(refs),
                }
            )
        assert metrics[-1]["bounded_snapshot_bytes"] < metrics[-1]["full_snapshot_bytes"] / 3
        assert metrics[-1]["detail_object_bytes"] < metrics[-1]["full_checkpoint_bytes"] * 0.6
        record_property("daily_track_read_cost", json.dumps(metrics))
        print("DAILY_TRACK_READ_COST=" + json.dumps(metrics))


def _size(value):
    return len(json.dumps(value, default=str, separators=(",", ":")).encode())

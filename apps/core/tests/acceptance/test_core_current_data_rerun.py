from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas
from core_runtime import create_initialized_test_app as create_app
from fastapi.testclient import TestClient
from test_core_daily_track_detail import (
    _business_sessions,
    _publish_head,
    _run_command,
    _run_worker_once,
)
from test_core_research_agent_mcp_runs import _mcp_client

from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.daily_track.models import DailyTrackProvenanceResultSectionInput
from thesistrace.data.canonical_mapping import adjusted_price_string
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication.holding_retention import HoldingRetention
from thesistrace.research_run import CurrentDataRerunCommand

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(), reason="isolated runtime required",
)


def test_current_data_rerun_keeps_parameters_and_original_result_without_old_generation(
    tmp_path: Path, monkeypatch,
):
    import test_core_daily_track_detail as fixture

    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path / "data",
                       benchmark_mount=tmp_path / "benchmark")
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=5)
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (BenchmarkLevel("2010-01-04", "3500"), *(BenchmarkLevel(day, "4000") for day in sessions)),
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    original_generation = _publish_head(settings, sessions=sessions, expected_manifest=None,
                                        operation_id="rerun-original")
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        command = {**_run_command("original", start_date=sessions[0], end_date=sessions[3]),
                   "initial_cash_cny": "100000", "selection_every_sessions": 3,
                   "exposure_expression": "7 / 10", "weighting": "rank_weight"}
        accepted = client.post("/api/research-runs", json=command)
        assert accepted.status_code == 202, accepted.text
        original_id = accepted.json()["id"]
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        original_detail = client.get(f"/api/research-runs/{original_id}").json()
        assert original_detail["status"] == "succeeded", original_detail
        started = client.post(f"/api/research-runs/{original_id}/daily-tracks",
                              json={"request_id": "rerun-track-origin"})
        assert started.status_code == 201, started.text
        track_id = started.json()["id"]
        provenance = runtime.daily_tracks.get_result_section(
            TEST_RESEARCHER.researcher_id,
            DailyTrackProvenanceResultSectionInput(track_id=track_id, section="provenance"),
        )
        checkpoint = provenance.checkpoint_manifest_sha256
        retention = HoldingRetention(runtime.database, runtime.publication)
        with runtime.database.transaction() as tx:
            tx.execute(
                "UPDATE publication.holding_units SET published_at = now() - interval '8 days', "
                "expires_at = now() - interval '1 second' WHERE id = %s", (original_id,),
            )
        retention.expire_once()
        expired = retention.inspect(TEST_RESEARCHER.researcher_id, original_id)
        canonical = fixture._canonical

        def revised(days):
            value = canonical(days)
            for price in value["prices"]:
                if price["session"] == sessions[3]:
                    for field in ("open", "high", "low", "close"):
                        raw = Decimal(price[f"{field}_raw"]) * Decimal("1.2")
                        price[f"{field}_raw"] = format(raw.normalize(), "f")
                        price[f"{field}_adj"] = adjusted_price_string(
                            raw, Decimal(price["adjustment_factor"]),
                        )
            return value

        monkeypatch.setattr(fixture, "_canonical", revised)
        current_generation = _publish_head(settings, sessions=sessions,
                                            expected_manifest=original_generation,
                                            operation_id="revised-history")
        assert current_generation != original_generation
        old_manifest = (settings.data_mount / "manifests" / "sha256" / original_generation[:2]
                        / f"{original_generation}.json")
        assert old_manifest.is_file()
        old_manifest.rename(tmp_path / "unavailable-original-generation.json")
        rerun = {"request_id": "new-current-data-run", "folder_id": "folder_default",
                 "rerun_source": {"kind": "research_run", "run_id": original_id}}
        response = client.post("/api/research-runs", json=rerun)
        assert response.status_code == 202, response.text
        new_id = response.json()["id"]
        assert new_id != original_id
        assert client.post("/api/research-runs", json=rerun).json()["id"] == new_id
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        new_detail = client.get(f"/api/research-runs/{new_id}").json()
        assert new_detail["status"] == "succeeded", new_detail
        assert new_detail["input"] == original_detail["input"]
        assert new_detail["rerun_origin"]["source_run_id"] == original_id
        assert new_detail["rerun_origin"]["source_data_generation_id"] == original_generation
        assert (new_detail["result"]["terminal_strategy_state"]["net_nav"]
                != original_detail["result"]["terminal_strategy_state"]["net_nav"])
        with runtime.database.transaction() as tx:
            new_input = tx.execute("SELECT immutable_input FROM research_runs.runs WHERE id = %s",
                                   (new_id,)).fetchone()["immutable_input"]
        assert new_input["data_admission"]["generation_manifest_sha256"] == current_generation
        assert client.get(f"/api/research-runs/{original_id}").json() == original_detail
        assert retention.inspect(TEST_RESEARCHER.researcher_id, original_id) == expired
        assert retention.inspect(TEST_RESEARCHER.researcher_id, new_id)["status"] == "available"
        # The admission receipt owns retries even after the original Run is deleted.
        removed = client.delete(f"/api/research-runs/{original_id}")
        assert removed.status_code == 204, removed.text
        assert client.post("/api/research-runs", json=rerun).json()["id"] == new_id

        track_before = client.get(f"/api/daily-tracks/{track_id}").json()
        assert track_before["origin"]["seed_research_available"] is False
        # Tracking owns its origin, so deleting the seed does not remove the research inputs.
        track_command = {
            "request_id": "track-current-data-run", "folder_id": "folder_default",
            "rerun_source": {"kind": "daily_track", "track_id": track_id,
                             "checkpoint_manifest_sha256": checkpoint,
                             "through_session": sessions[2]},
        }
        async def submit_track_via_mcp():
            async with _mcp_client(settings, tmp_path / "rerun-mcp.stderr.log") as agent:
                submitted = await agent.call_tool("submit_research_run", track_command)
                assert submitted.is_error is False, submitted.structured_content
                assert submitted.structured_content["outcome"] == "accepted"
                replayed = await agent.call_tool("submit_research_run", track_command)
                assert (replayed.structured_content["run_id"]
                        == submitted.structured_content["run_id"])
                assert replayed.structured_content["replayed"] is True
                return submitted.structured_content["run_id"]
        track_run_id = anyio.run(submit_track_via_mcp)
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        track_run = client.get(f"/api/research-runs/{track_run_id}").json()
        assert track_run["status"] == "succeeded", track_run
        assert track_run["start_date"] == sessions[0]
        assert track_run["end_date"] == sessions[2]
        assert track_run["input"]["initial_cash_cny"] == "100000"
        assert track_run["rerun_origin"]["source_track_id"] == track_id
        assert track_run["rerun_origin"]["source_checkpoint_manifest_sha256"] == checkpoint
        assert client.get(f"/api/daily-tracks/{track_id}").json() == track_before
        invalid = {**track_command, "request_id": "future-investigation",
                   "rerun_source": {**track_command["rerun_source"],
                                    "through_session": sessions[4]}}
        rejected = client.post("/api/research-runs", json=invalid)
        assert rejected.status_code == 422, rejected.text
        assert "rerun_source.through_session" in rejected.text
        queued = client.post("/api/research-runs", json={
            **track_command, "request_id": "cancel-current-data-run",
        })
        assert queued.status_code == 202, queued.text
        cancelled = client.post(f"/api/research-runs/{queued.json()['id']}/cancel",
                                json={"request_id": "cancel-rerun"})
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

        for source in ({"kind": "research_run", "run_id": new_id},
                       track_command["rerun_source"]):
            outcome = runtime.research_runs.admit_with_outcome(
                uuid4(), CurrentDataRerunCommand.model_validate({
                    "request_id": "foreign-source", "folder_id": "folder_default",
                    "rerun_source": source,
                }),
            )
            assert outcome.outcome == "rejected"
            assert outcome.issues[0].code == "RERUN_SOURCE_NOT_FOUND"
        wrong_checkpoint = client.post("/api/research-runs", json={
            **track_command, "request_id": "wrong-checkpoint",
            "rerun_source": {**track_command["rerun_source"],
                             "checkpoint_manifest_sha256": "f" * 64},
        })
        assert wrong_checkpoint.status_code == 422, wrong_checkpoint.text
        assert "RERUN_SOURCE_NOT_FOUND" in wrong_checkpoint.text
        # A now-unsupported source parameter must be diagnosed, never replaced by a default.
        with runtime.database.transaction() as tx:
            tx.execute(
                "UPDATE research_runs.runs SET immutable_input = jsonb_set(immutable_input, "
                "'{costs,commission_min_cny}', '\"999\"'::jsonb) WHERE id = %s", (new_id,),
            )
        unsupported = client.post("/api/research-runs", json={
            "request_id": "unsupported-source-cost", "folder_id": "folder_default",
            "rerun_source": {"kind": "research_run", "run_id": new_id},
        })
        assert unsupported.status_code == 422, unsupported.text
        assert unsupported.json()["issues"][0]["field"] == "costs"
        with runtime.database.transaction() as tx:
            tx.execute(
                "UPDATE research_runs.runs SET immutable_input = jsonb_set(immutable_input, "
                "'{costs,commission_min_cny}', '\"5\"'::jsonb) WHERE id = %s", (new_id,),
            )

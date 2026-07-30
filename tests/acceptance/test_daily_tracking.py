from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingError, DailyTrackingService


def definition() -> dict[str, object]:
    return {
        "title": "连续动量跟踪",
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


def services(
    settings: Settings,
) -> tuple[ResearchRunService, DailyTrackingService, ImmutableObjectStore]:
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    datasets = DatasetPublisher(metadata, objects)
    return (
        ResearchRunService(metadata, datasets, objects),
        DailyTrackingService(metadata, datasets, objects),
        objects,
    )


def test_daily_track_activation_catchup_replay_and_equivalence(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        seed_release = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "tracking-seed"},
            json={"fixture": "v1"},
        ).json()["release"]
        draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        requested = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "tracking-run"},
        ).json()
        run_id = requested["run"]["id"]
        run_service, tracking, objects = services(settings)
        seed_canonical = DatasetPublisher(
            MetadataStore(settings.metadata_path),
            objects,
        ).materialize_canonical(seed_release)
        historical_open = next(
            row
            for row in seed_canonical["prices"]
            if row["session"] == seed_canonical["research_calendar"][0]
            and row["instrument_id"] == "equity:600000.SH"
        )
        assert run_service.execute(run_id)["status"] == "succeeded"
        queued_rerun = client.post(
            f"/api/v1/research-runs/{run_id}/rerun",
            headers={"Idempotency-Key": "tracking-not-succeeded"},
        ).json()
        assert (
            client.post(
                f"/api/v1/research-runs/{queued_rerun['id']}/daily-tracks",
                headers={"Idempotency-Key": "reject-queued-track"},
            ).status_code
            == 409
        )

        catchup_release = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "tracking-catchup"},
            json={"new_sessions": 3, "corrections": []},
        ).json()["release"]
        later_release = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "tracking-later-release"},
            json={"new_sessions": 1, "corrections": []},
        ).json()["release"]
        activated = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "activate-track"},
        )
        assert activated.status_code == 201
        track = activated.json()
        track_id = track["id"]
        assert track["status"] == "active"
        assert track["activation_release_id"] == seed_release["id"]
        assert track["head"]["target_dataset_release_id"] == seed_release["id"]
        assert track["head"]["predecessor_checkpoint_id"] is None
        assert track["generations"][0]["ordinal"] == 0
        assert track["advances"][0]["target_dataset_release_id"] == catchup_release["id"]

        repeated = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "activate-track"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == track_id

        advance_id = track["advances"][0]["id"]
        metadata = MetadataStore(settings.metadata_path)
        with metadata.connect() as connection:
            connection.execute(
                """
                UPDATE tracking_advances
                SET status = 'running'
                WHERE id = ?
                """,
                (advance_id,),
            )
            connection.execute(
                """
                INSERT INTO tracking_advance_attempts
                    (id, advance_id, ordinal, status, started_at)
                VALUES ('track_attempt_abandoned', ?, 1, 'running',
                        '2000-01-01T00:00:00+00:00')
                """,
                (advance_id,),
            )
        assert tracking.recover_abandoned_attempts(stale_after_seconds=30) == [advance_id]

        claimed = tracking._claim_advance(advance_id)
        assert claimed is not None
        current_advance, current_attempt = claimed
        stale_attempt = {"id": "track_attempt_abandoned"}
        stale_checkpoint = {
            "id": "checkpoint_from_stale_attempt",
            "manifest_sha256": "0" * 64,
            "manifest": {"predecessor_checkpoint_id": track["head"]["id"]},
        }
        with pytest.raises(DailyTrackingError, match="publication was fenced"):
            tracking._publish_advance_success(
                current_advance,
                stale_attempt,
                stale_checkpoint,
            )
        tracking._block_advance(
            current_advance,
            stale_attempt,
            {"reason_code": "STALE_WORKER", "message": "must be ignored"},
        )
        still_claimed = tracking._advance(advance_id)
        assert still_claimed["status"] == "running"
        assert still_claimed["attempts"][-1]["status"] == "running"

        checkpoint = tracking._calculate_advance(current_advance)
        tracking._publish_advance_success(current_advance, current_attempt, checkpoint)
        advanced = tracking._advance(advance_id)
        tracking.enqueue_toward(track_id, later_release["id"])
        assert advanced["status"] == "succeeded"
        assert [attempt["status"] for attempt in advanced["attempts"]] == [
            "failed",
            "succeeded",
        ]
        current = tracking.get_track(track_id)
        assert current is not None
        assert current["head"]["target_dataset_release_id"] == catchup_release["id"]
        current_view = client.get(f"/api/v1/daily-tracks/{track_id}/current").json()
        assert current_view["checkpoint"]["id"] == current["head"]["id"]
        assert (
            client.get(
                f"/api/v1/daily-tracks/{track_id}/generations/"
                f"{current['generations'][0]['id']}"
            ).json()["id"]
            == current["generations"][0]["id"]
        )
        assert (
            client.get(
                f"/api/v1/daily-tracks/{track_id}/advances/{advanced['id']}"
            ).json()["id"]
            == advanced["id"]
        )
        assert (
            client.get(
                f"/api/v1/daily-tracks/{track_id}/checkpoints/"
                f"{current['head']['id']}"
            ).json()["id"]
            == current["head"]["id"]
        )
        assert len(current_view["factor_summary"]["horizons"]["1"]["daily"]) == 504
        assert current_view["recent_label_maturation"]["events"]
        head_manifest = objects.read_json(current["head"]["manifest_sha256"])
        assert head_manifest["processed_sessions"] == [
            "2026-07-30",
            "2026-07-31",
            "2026-08-03",
        ]
        assert head_manifest["predecessor_checkpoint_id"] == track["head"]["id"]
        strategy = objects.read_json(head_manifest["objects"]["strategy_backtest"]["sha256"])
        assert len(strategy["daily"]) == 507
        maturations = objects.read_json(head_manifest["objects"]["label_maturation"]["sha256"])
        assert maturations["events"]
        assert {event["horizon"] for event in maturations["events"]} == {1, 5, 20}
        assert all(
            event["basis_dataset_release_id"] == catchup_release["id"]
            for event in maturations["events"]
        )
        canonical = DatasetPublisher(
            MetadataStore(settings.metadata_path),
            objects,
        ).materialize_canonical(catchup_release)
        calendar = canonical["research_calendar"]
        assert all(
            calendar.index(event["maturity_session"]) - calendar.index(event["signal_session"])
            == event["horizon"] + 1
            for event in maturations["events"]
        )
        factor_history = objects.read_json(head_manifest["objects"]["factor_evaluation"]["sha256"])
        factor_summary = objects.read_json(head_manifest["objects"]["factor_summary"]["sha256"])
        assert len(factor_history["horizons"]["1"]["daily"]) == 507
        assert len(factor_summary["horizons"]["1"]["daily"]) == 504
        assert (
            client.post(f"/api/v1/daily-tracks/{track_id}/verify-equivalence").json()["status"]
            == "equivalent"
        )
        assert (
            tracking.execute_advance(advanced["id"])["checkpoint_id"] == advanced["checkpoint_id"]
        )
        next_advance = tracking.execute_next()
        assert next_advance is not None
        assert next_advance["status"] == "succeeded"
        after_ordered_catchup = tracking.get_track(track_id)
        assert after_ordered_catchup["head"]["target_dataset_release_id"] == later_release["id"]
        ordered_manifest = objects.read_json(after_ordered_catchup["head"]["manifest_sha256"])
        assert len(ordered_manifest["processed_sessions"]) == 1

        correction = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "tracking-correction"},
            json={
                "new_sessions": 1,
                "corrections": [
                    {
                        "session": seed_canonical["research_calendar"][0],
                        "instrument_id": "equity:600000.SH",
                        "field": "open_raw",
                        "value": historical_open["open_raw"],
                    }
                ],
            },
        ).json()["release"]
        queued_replay = tracking.get_track(track_id)
        assert queued_replay is not None
        assert queued_replay["generations"][-1]["reason"] == "historical_correction"
        assert queued_replay["advances"][-1]["target_dataset_release_id"] == correction["id"]
        generation_count = len(queued_replay["generations"])
        advance_count = len(queued_replay["advances"])
        assert tracking.enqueue_active_tracks(correction["id"]) == []
        assert tracking.enqueue_active_tracks(correction["id"]) == []
        reconciled = tracking.get_track(track_id)
        assert len(reconciled["generations"]) == generation_count
        assert len(reconciled["advances"]) == advance_count

        replay = tracking.execute_next()
        assert replay is not None
        assert replay["status"] == "succeeded"
        corrected = tracking.get_track(track_id)
        assert corrected is not None
        assert corrected["current_generation_id"] == replay["generation_id"]
        corrected_head = objects.read_json(corrected["head"]["manifest_sha256"])
        assert corrected_head["predecessor_checkpoint_id"] is None
        assert corrected_head["supersedes_generation_id"] == track["current_generation_id"]
        assert client.post(f"/api/v1/daily-tracks/{track_id}/verify-equivalence").status_code == 200

        generation_count = len(corrected["generations"])
        irrelevant_correction = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "tracking-irrelevant-correction"},
            json={
                "new_sessions": 1,
                "corrections": [
                    {
                        "session": "2026-07-29",
                        "instrument_id": "equity:600000.SH",
                        "field": "pre_close_raw",
                        "value": "8.0100",
                    }
                ],
            },
        ).json()["release"]
        queued_increment = tracking.get_track(track_id)
        assert len(queued_increment["generations"]) == generation_count
        incremental = tracking.execute_next()
        assert incremental is not None
        assert incremental["status"] == "succeeded"
        assert (
            tracking.get_track(track_id)["head"]["target_dataset_release_id"]
            == irrelevant_correction["id"]
        )

        upgraded = client.post(
            f"/api/v1/daily-tracks/{track_id}/kernel-upgrade",
            json={
                "calculation_kernel": "kernel-v2",
                "numeric_execution_contract": "thesistrace-numeric-v1",
            },
        )
        assert upgraded.status_code == 200
        assert upgraded.json()["generations"][-1]["reason"] == "runtime_fix"
        duplicate_pending_upgrade = client.post(
            f"/api/v1/daily-tracks/{track_id}/kernel-upgrade",
            json={
                "calculation_kernel": "kernel-v2",
                "numeric_execution_contract": "thesistrace-numeric-v1",
            },
        )
        assert duplicate_pending_upgrade.status_code == 200
        conflicting_pending_upgrade = client.post(
            f"/api/v1/daily-tracks/{track_id}/kernel-upgrade",
            json={
                "calculation_kernel": "kernel-v1",
                "numeric_execution_contract": "thesistrace-numeric-v1",
            },
        )
        assert conflicting_pending_upgrade.status_code == 409
        assert (
            len(tracking.get_track(track_id)["generations"])
            == len(upgraded.json()["generations"])
        )
        runtime_replay = tracking.execute_next()
        assert runtime_replay is not None
        assert runtime_replay["status"] == "succeeded"
        assert tracking.get_track(track_id)["generations"][-1]["calculation_kernel"] == "kernel-v2"

        for sequence in (1, 2):
            daily_release = client.post(
                "/api/v1/dataset-releases/publish-fixture",
                headers={"Idempotency-Key": f"tracking-daily-{sequence}"},
                json={"new_sessions": 1, "corrections": []},
            ).json()["release"]
            daily_advance = tracking.execute_next()
            assert daily_advance is not None
            assert daily_advance["status"] == "succeeded"
            daily_head = tracking.get_track(track_id)["head"]
            assert daily_head["target_dataset_release_id"] == daily_release["id"]
            daily_manifest = objects.read_json(daily_head["manifest_sha256"])
            assert len(daily_manifest["processed_sessions"]) == 1
            assert (
                client.post(f"/api/v1/daily-tracks/{track_id}/verify-equivalence").status_code
                == 200
            )

        rejected_numeric_change = client.post(
            f"/api/v1/daily-tracks/{track_id}/kernel-upgrade",
            json={
                "calculation_kernel": "kernel-v3",
                "numeric_execution_contract": "numeric-v2",
            },
        )
        assert rejected_numeric_change.status_code == 409
        rejected_unknown_kernel = client.post(
            f"/api/v1/daily-tracks/{track_id}/kernel-upgrade",
            json={
                "calculation_kernel": "kernel-v99",
                "numeric_execution_contract": "thesistrace-numeric-v1",
            },
        )
        assert rejected_unknown_kernel.status_code == 409

        stopped = client.post(f"/api/v1/daily-tracks/{track_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
        advance_count = len(stopped.json()["advances"])
        client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "tracking-after-stop"},
            json={"new_sessions": 1, "corrections": []},
        )
        assert len(tracking.get_track(track_id)["advances"]) == advance_count

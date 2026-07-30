from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.result_objects import STRATEGY_DAILY_CONTRACT
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

        checkpoint = tracking._calculate_advance(
            current_advance,
            fencing_token=current_attempt["fencing_token"],
            attempt_id=current_attempt["id"],
        )
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
        assert (
            current_view["factor_summary"]["horizons"]["1"]["diagnostics"][
                "session_count"
            ]
            == 504
        )
        assert "daily" not in current_view["factor_summary"]["horizons"]["1"]
        assert current_view["recent_label_maturation"]["events"] == []
        head_manifest = objects.read_json(current["head"]["manifest_sha256"])
        assert head_manifest["processed_sessions"] == [
            "2026-07-30",
            "2026-07-31",
            "2026-08-03",
        ]
        assert head_manifest["predecessor_checkpoint_id"] == track["head"]["id"]
        strategy_delta = objects.read_parquet(
            head_manifest["objects"]["strategy_daily_observations"]["sha256"],
            STRATEGY_DAILY_CONTRACT,
        ).to_pylist()
        assert len(strategy_delta) == 3
        assert len(current_view["strategy"]["daily"]) == 507
        assert "forward_labels" not in head_manifest["objects"]
        assert "factor_evaluation" not in head_manifest["objects"]
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
                        "value": str(
                            Decimal(str(historical_open["open_raw"]))
                            + Decimal("0.0100")
                        ),
                    }
                ],
            },
        ).json()["release"]
        prior_correction_head = tracking.get_track(track_id)["head"]
        prior_correction_manifest = objects.read_json(
            prior_correction_head["manifest_sha256"]
        )
        prior_correction_view = client.get(
            f"/api/v1/daily-tracks/{track_id}/current"
        ).json()
        queued_correction = tracking.get_track(track_id)
        assert queued_correction is not None
        assert queued_correction["current_generation_id"] == track["current_generation_id"]
        assert all(
            generation["reason"] != "historical_correction"
            for generation in queued_correction["generations"]
        )
        correction_advance = queued_correction["advances"][-1]
        assert correction_advance["target_dataset_release_id"] == correction["id"]
        assert correction_advance["correction_boundary"] == {
            "accepted_correction_change_set": correction["correction_change_set"],
            "prior_checkpoint_id": prior_correction_head["id"],
            "prior_dataset_release_id": prior_correction_head[
                "target_dataset_release_id"
            ],
            "target_dataset_release_id": correction["id"],
        }
        generation_count = len(queued_correction["generations"])
        advance_count = len(queued_correction["advances"])
        assert tracking.enqueue_active_tracks(correction["id"]) == []
        assert tracking.enqueue_active_tracks(correction["id"]) == []
        reconciled = tracking.get_track(track_id)
        assert len(reconciled["generations"]) == generation_count
        assert len(reconciled["advances"]) == advance_count
        advance_resource = client.get(
            f"/api/v1/daily-tracks/{track_id}/advances/{correction_advance['id']}"
        ).json()
        assert advance_resource["correction_boundary"] == correction_advance[
            "correction_boundary"
        ]

        claimed_correction = tracking._claim_advance(correction_advance["id"])
        assert claimed_correction is not None
        claimed_advance, claimed_attempt = claimed_correction
        tracking._block_advance(
            claimed_advance,
            claimed_attempt,
            {
                "reason_code": "TEST_CORRECTION_RETRY",
                "message": "retry the same correction boundary",
            },
        )
        after_failed_correction = tracking.get_track(track_id)
        assert after_failed_correction["head"]["id"] == prior_correction_head["id"]
        assert after_failed_correction["advances"][-1]["id"] == correction_advance["id"]

        continued = tracking.execute_next()
        assert continued is not None
        assert continued["status"] == "succeeded"
        assert [attempt["status"] for attempt in continued["attempts"]] == [
            "failed",
            "succeeded",
        ]
        corrected = tracking.get_track(track_id)
        assert corrected is not None
        assert corrected["current_generation_id"] == track["current_generation_id"]
        corrected_head = objects.read_json(corrected["head"]["manifest_sha256"])
        assert corrected_head["predecessor_checkpoint_id"] == prior_correction_head["id"]
        assert corrected_head["processed_sessions"] == [
            correction["appended_session_range"]["end"]
        ]
        assert corrected_head["correction_boundary"] == correction_advance[
            "correction_boundary"
        ]
        corrected_view = client.get(
            f"/api/v1/daily-tracks/{track_id}/current"
        ).json()
        assert corrected_view["strategy"]["daily"][:-1] == prior_correction_view[
            "strategy"
        ]["daily"]
        assert (
            objects.read_json(prior_correction_head["manifest_sha256"])
            == prior_correction_manifest
        )
        object_paths_before_verification = sorted(
            path.relative_to(settings.object_root)
            for path in settings.object_root.rglob("*")
            if path.is_file()
        )
        cache_files_before_verification = {
            path.relative_to(tracking.cache.root): path.read_bytes()
            for path in tracking.cache.root.rglob("*")
            if path.is_file()
        }
        head_before_verification = tracking.get_track(track_id)["head"]
        correction_verification = client.post(
            f"/api/v1/daily-tracks/{track_id}/verify-equivalence"
        )
        assert correction_verification.status_code == 200
        assert correction_verification.json()["release_sequence"][-1] == correction["id"]
        assert tracking.get_track(track_id)["head"] == head_before_verification
        assert sorted(
            path.relative_to(settings.object_root)
            for path in settings.object_root.rglob("*")
            if path.is_file()
        ) == object_paths_before_verification
        assert {
            path.relative_to(tracking.cache.root): path.read_bytes()
            for path in tracking.cache.root.rglob("*")
            if path.is_file()
        } == cache_files_before_verification

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
        assert queued_increment["advances"][-1]["correction_boundary"] is None
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
        assert (
            client.post(
                f"/api/v1/daily-tracks/{track_id}/verify-equivalence"
            ).json()["status"]
            == "equivalent"
        )

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

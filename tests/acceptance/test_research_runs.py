import hashlib
from contextlib import contextmanager
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import (
    MAX_RESULT_BUNDLE_BYTES,
    ResearchRunService,
    TransientResearchRunError,
    calculate_research,
)
from thesistrace.storage import MetadataStore


def definition() -> dict[str, object]:
    return {
        "title": "20 日价格动量",
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


def setup_run(client: TestClient, key: str = "run-v1") -> dict[str, object]:
    client.post(
        "/api/v1/dataset-releases/bootstrap",
        headers={"Idempotency-Key": "run-release"},
        json={"fixture": "v1"},
    )
    draft = client.post("/api/v1/research-definitions", json=definition()).json()
    response = client.post(
        f"/api/v1/research-definitions/{draft['id']}/runs",
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202
    return response.json()


def service(settings: Settings, *, calculator=None) -> ResearchRunService:
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    return ResearchRunService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        calculator=calculator,
    )


def test_run_publishes_one_complete_immutable_result_bundle(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        requested = setup_run(client)
        run_id = requested["run"]["id"]
        captured: dict[str, dict[str, object]] = {}

        def capture_artifacts(
            canonical: dict[str, object],
            frozen: dict[str, object],
        ) -> dict[str, dict[str, object]]:
            artifacts = calculate_research(canonical, frozen)
            captured.update(artifacts)
            return artifacts

        completed = service(settings, calculator=capture_artifacts).execute(run_id)

        assert completed["status"] == "succeeded"
        assert completed["result_bundle_id"].startswith("result_")
        assert [
            item["id"]
            for item in client.get("/api/v1/research-definition-versions").json()["items"]
        ] == [requested["frozen_definition"]["id"]]
        detail = client.get(f"/api/v1/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded"
        assert [attempt["status"] for attempt in detail["attempts"]] == ["succeeded"]
        attempt = client.get(f"/api/v1/research-runs/{run_id}/attempts/1")
        assert attempt.status_code == 200
        assert attempt.json()["id"] == detail["attempts"][0]["id"]

        result = client.get(f"/api/v1/research-runs/{run_id}/result")
        assert result.status_code == 200
        payload = result.json()
        manifest = payload["manifest"]
        assert manifest["research_run_id"] == run_id
        assert manifest["definition"]["id"] == requested["frozen_definition"]["id"]
        assert (
            manifest["definition"]["content_hash"] == requested["frozen_definition"]["content_hash"]
        )
        assert manifest["dataset_release"]["id"] == requested["run"]["dataset_release_id"]
        assert manifest["input_sessions"] == {
            "total": 756,
            "warmup": 252,
            "report": 504,
        }
        assert manifest["numeric_execution_contract"] == "thesistrace-numeric-v1"
        assert manifest["calculation_kernel"] == "kernel-v1"
        assert set(manifest["objects"]) == {
            "diagnostic_summary",
            "execution_aggregates",
            "factor_summary",
            "rebalance_aggregates",
            "strategy_daily_observations",
            "strategy_summary",
            "terminal_positions",
            "terminal_strategy_state",
        }
        assert "compatibility_objects" not in manifest
        assert manifest["logical_bytes"]["total"] <= MAX_RESULT_BUNDLE_BYTES
        assert manifest["logical_bytes"]["payloads"] == sum(
            entry["bytes"] for entry in manifest["objects"].values()
        )
        manifest_payload = (
            settings.object_root
            / "sha256"
            / completed["result_manifest_sha256"][:2]
            / f"{completed['result_manifest_sha256']}.json"
        ).read_bytes()
        assert manifest["logical_bytes"]["manifest"] == len(manifest_payload)
        assert manifest["logical_bytes"]["total"] == (
            len(manifest_payload)
            + sum(entry["bytes"] for entry in manifest["objects"].values())
        )
        parquet_kinds = {
            "execution_aggregates",
            "rebalance_aggregates",
            "strategy_daily_observations",
            "terminal_positions",
        }
        for kind, entry in manifest["objects"].items():
            suffix = "parquet" if kind in parquet_kinds else "json"
            assert (
                settings.object_root
                / "sha256"
                / entry["sha256"][:2]
                / f"{entry['sha256']}.{suffix}"
            ).is_file()

        daily_entry = manifest["objects"]["strategy_daily_observations"]
        assert [
            field["name"]
            for field in daily_entry["writer_contract"]["schema"]
        ] == [
            "session",
            "gross_nav",
            "net_nav",
            "benchmark_nav",
            "net_cash",
            "transaction_cost_cny",
            "holdings_count",
            "maximum_single_name_weight",
            "upper_limit_buy_rejections",
            "lower_limit_sell_rejections",
            "suspension_rejections",
        ]
        daily_path = (
            settings.object_root
            / "sha256"
            / daily_entry["sha256"][:2]
            / f"{daily_entry['sha256']}.parquet"
        )
        assert pq.ParquetFile(daily_path).metadata.num_row_groups == 1

        assert all(
            "daily" not in horizon
            for horizon in payload["factor_evaluation"]["horizons"].values()
        )
        assert len(payload["strategy_backtest"]["daily"]) == 504
        assert "fills" not in payload["strategy_backtest"]
        assert "rejections" not in payload["strategy_backtest"]
        assert "alpha_coverage" not in payload["diagnostics"]
        assert payload["diagnostics"]["alpha_coverage_summary"]["session_count"] == 756
        assert (
            payload["factor_evaluation"]["horizons"]["1"]["alpha_checksum"]
            == payload["strategy_backtest"]["alpha_checksum"]
        )

        raw_manifest = service(settings).objects.read_json(
            completed["result_manifest_sha256"]
        )
        assert isinstance(raw_manifest, dict)
        assert "compatibility_objects" not in raw_manifest
        assert payload["strategy_backtest"]["metrics"] == captured[
            "strategy_backtest"
        ]["metrics"]
        assert all(
            payload["factor_evaluation"]["horizons"][horizon]["summary"]
            == captured["factor_evaluation"]["horizons"][horizon]["summary"]
            for horizon in ("1", "5", "20")
        )
        assert payload["terminal_strategy_state"]["session"] == payload[
            "strategy_backtest"
        ]["daily"][-1]["session"]
        assert payload["terminal_strategy_state"]["positions"] == captured[
            "strategy_backtest"
        ]["positions"]
        assert "metric_state" not in payload["terminal_strategy_state"]
        assert "last_daily_observation" not in payload[
            "terminal_strategy_state"
        ]
        missing_attempt = client.get(f"/api/v1/research-runs/{run_id}/attempts/99")
        assert missing_attempt.status_code == 404
        assert missing_attempt.json()["detail"]["reason_code"] == (
            "RESEARCH_RUN_ATTEMPT_NOT_FOUND"
        )

        repeated = service(settings).execute(run_id)
        assert repeated["result_bundle_id"] == completed["result_bundle_id"]
        assert len(client.get(f"/api/v1/research-runs/{run_id}").json()["attempts"]) == 1


def test_attempt_retry_cancel_fence_and_rerun_preserve_inputs(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        requested = setup_run(client)
        run_id = requested["run"]["id"]

        def transient_failure(*_args):
            raise TransientResearchRunError("temporary worker failure")

        retryable = service(settings, calculator=transient_failure).execute(run_id)
        assert retryable["status"] == "queued"
        failed_attempt = client.get(f"/api/v1/research-runs/{run_id}").json()["attempts"][0]
        assert failed_attempt["status"] == "failed"
        assert failed_attempt["diagnostic"] == {
            "reason_code": "TRANSIENT_FAILURE",
            "message": "temporary research infrastructure failure",
            "correlation_id": failed_attempt["id"],
        }

        completed = service(settings).execute(run_id)
        assert completed["status"] == "succeeded"
        assert [attempt["status"] for attempt in completed["attempts"]] == [
            "failed",
            "succeeded",
        ]

        rerun = client.post(
            f"/api/v1/research-runs/{run_id}/rerun",
            headers={"Idempotency-Key": "explicit-rerun"},
        )
        assert rerun.status_code == 202
        assert rerun.json()["id"] != run_id
        assert rerun.json()["definition_version_id"] == requested["frozen_definition"]["id"]
        assert rerun.json()["dataset_release_id"] == requested["run"]["dataset_release_id"]

        cancelled = client.post(f"/api/v1/research-runs/{rerun.json()['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert service(settings).execute(rerun.json()["id"])["status"] == "cancelled"
        assert client.get(f"/api/v1/research-runs/{rerun.json()['id']}/result").status_code == 409

        fenced = client.post(
            f"/api/v1/research-runs/{run_id}/rerun",
            headers={"Idempotency-Key": "cancel-fence"},
        ).json()
        metadata = MetadataStore(settings.metadata_path)

        manifests_before_fence = set(
            (settings.object_root / "manifests").glob("result_*.json")
        )

        def cancel_before_publication(canonical, frozen_definition):
            artifacts = calculate_research(canonical, frozen_definition)
            metadata.cancel_research_run(fenced["id"])
            return artifacts

        fenced_result = service(
            settings,
            calculator=cancel_before_publication,
        ).execute(fenced["id"])
        assert fenced_result["status"] == "cancelled"
        assert fenced_result["result_bundle_id"] is None
        assert set(
            (settings.object_root / "manifests").glob("result_*.json")
        ) == manifests_before_fence
        assert not (settings.object_root / "staging" / fenced["id"]).exists()

        abandoned = client.post(
            f"/api/v1/research-runs/{run_id}/rerun",
            headers={"Idempotency-Key": "abandoned-recovery"},
        ).json()
        assert metadata.claim_research_run(abandoned["id"]) is not None
        with metadata.connect() as connection:
            connection.execute(
                """
                UPDATE research_run_attempts
                SET heartbeat_at = '2000-01-01T00:00:00+00:00'
                WHERE run_id = ?
                """,
                (abandoned["id"],),
            )
        assert metadata.recover_abandoned_research_runs(stale_after_seconds=30) == [abandoned["id"]]
        recovered = service(settings).execute(abandoned["id"])
        assert recovered["status"] == "succeeded"
        assert recovered["attempts"][0]["diagnostic"] == {
            "reason_code": "ABANDONED_ATTEMPT",
            "message": "worker heartbeat expired before publication",
        }


def test_oversized_complete_result_fails_without_publishing_a_bundle(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        requested = setup_run(client, key="oversized-run")
    objects_before = set((settings.object_root / "sha256").rglob("*.*"))

    def oversized_result(
        canonical: dict[str, object],
        frozen: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        artifacts = calculate_research(canonical, frozen)
        strategy = artifacts["strategy_backtest"]
        strategy["positions"] = [
            {
                "instrument_id": f"equity:{hashlib.sha256(str(index).encode()).hexdigest()}",
                "execution_shares": 100,
                "adjusted_units": "100",
                "last_adjusted_price": "10",
            }
            for index in range(50_000)
        ]
        return artifacts

    completed = service(settings, calculator=oversized_result).execute(
        requested["run"]["id"]
    )
    assert completed["status"] == "failed"
    assert completed["result_bundle_id"] is None
    assert completed["result_manifest_sha256"] is None
    assert completed["attempts"][-1]["diagnostic"]["reason_code"] == (
        "CALCULATION_FAILED"
    )
    manifest_root = settings.object_root / "manifests"
    assert not manifest_root.exists() or not list(manifest_root.glob("result_*.json"))
    assert set((settings.object_root / "sha256").rglob("*.*")) == objects_before


def test_commit_response_loss_keeps_the_committed_result_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        requested = setup_run(client, key="commit-response-loss")
    runner = service(settings)
    publish = runner.metadata.publish_research_run_success

    def commit_then_disconnect(**kwargs) -> bool:
        assert publish(**kwargs) is True
        raise ConnectionError("commit response was lost")

    monkeypatch.setattr(
        runner.metadata,
        "publish_research_run_success",
        commit_then_disconnect,
    )

    completed = runner.execute(requested["run"]["id"])

    assert completed["status"] == "succeeded"
    assert runner.result_view(requested["run"]["id"]) is not None
    assert not (
        settings.object_root / "staging" / requested["run"]["id"]
    ).exists()


def test_recovery_reloads_committed_run_after_acquiring_publication_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        requested = setup_run(client, key="commit-before-recovery-lock")
    runner = service(settings)
    run_id = str(requested["run"]["id"])
    claimed = runner.metadata.claim_research_run(run_id)
    assert claimed is not None
    attempt_id = str(claimed[1]["id"])
    result_bundle_id = "result-commit-before-recovery-lock"
    manifest = {"id": result_bundle_id}

    with pytest.raises(RuntimeError, match="process stopped after install"):
        with runner.objects.stage(run_id, attempt_id) as staged:
            manifest_object = staged.put_json(manifest)
            staged.put_manifest(result_bundle_id, manifest)
            with staged.publication(
                manifest_sha256=str(manifest_object["sha256"])
            ):
                raise RuntimeError("process stopped after install")

    original_guard = runner.objects.publication_guard
    published = False

    @contextmanager
    def publish_before_guard(guarded_run_id: str):
        nonlocal published
        if not published:
            published = True
            assert runner.metadata.publish_research_run_success(
                run_id=run_id,
                attempt_id=attempt_id,
                result_bundle_id=result_bundle_id,
                result_manifest_sha256=str(manifest_object["sha256"]),
                storage_objects=[],
            )
        with original_guard(guarded_run_id):
            yield

    monkeypatch.setattr(
        runner.objects,
        "publication_guard",
        publish_before_guard,
    )

    completed = runner.execute(run_id)

    assert completed["status"] == "succeeded"
    assert (
        settings.object_root / "manifests" / f"{result_bundle_id}.json"
    ).exists()
    assert not (settings.object_root / "staging" / run_id).exists()

from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import (
    ResearchRunService,
    TransientResearchRunError,
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

        completed = service(settings).execute(run_id)

        assert completed["status"] == "succeeded"
        assert completed["result_bundle_id"].startswith("result_")
        detail = client.get(f"/api/v1/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded"
        assert [attempt["status"] for attempt in detail["attempts"]] == ["succeeded"]

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
        assert set(manifest["objects"]) >= {
            "alpha_matrix",
            "forward_labels",
            "factor_evaluation",
            "strategy_backtest",
            "strategy_time_series",
            "strategy_events",
            "diagnostics",
        }
        assert all(
            (
                settings.object_root / "sha256" / entry["sha256"][:2] / f"{entry['sha256']}.json"
            ).is_file()
            for entry in manifest["objects"].values()
        )
        assert len(payload["factor_evaluation"]["horizons"]["1"]["daily"]) == 504
        assert len(payload["strategy_backtest"]["daily"]) == 504
        assert (
            payload["factor_evaluation"]["horizons"]["1"]["alpha_checksum"]
            == payload["strategy_backtest"]["alpha_checksum"]
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
            "message": "temporary worker failure",
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

        def cancel_before_publication(*_args):
            metadata.cancel_research_run(fenced["id"])
            return {
                kind: {}
                for kind in {
                    "alpha_matrix",
                    "forward_labels",
                    "factor_evaluation",
                    "strategy_backtest",
                    "strategy_time_series",
                    "strategy_events",
                    "diagnostics",
                }
            }

        fenced_result = service(
            settings,
            calculator=cancel_before_publication,
        ).execute(fenced["id"])
        assert fenced_result["status"] == "cancelled"
        assert fenced_result["result_bundle_id"] is None

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

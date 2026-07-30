from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings


def valid_definition() -> dict[str, object]:
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


def test_draft_validation_and_run_freezing_are_atomic_and_immutable(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        release = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "definition-release"},
            json={"fixture": "v1"},
        ).json()["release"]

        created = client.post("/api/v1/research-definitions", json=valid_definition())
        assert created.status_code == 201
        draft = created.json()
        assert draft["state"] == "draft"
        assert client.get("/api/v1/research-definitions").json()["items"] == [draft]

        invalid_content = {
            **valid_definition(),
            "alpha": {"expression": "lag($close_raw, 0)"},
            "universe": "top42",
            "strategy": {
                **valid_definition()["strategy"],
                "holdings_count": 101,
                "rebalance_interval": 0,
            },
        }
        updated = client.put(
            f"/api/v1/research-definitions/{draft['id']}",
            json=invalid_content,
        )
        assert updated.status_code == 200
        failed_run = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "invalid-run"},
        )
        assert failed_run.status_code == 422
        reasons = {item["reason_code"] for item in failed_run.json()["detail"]["errors"]}
        assert reasons >= {
            "UNIVERSE_NOT_SUPPORTED",
            "FIELD_NOT_AUTHORABLE",
            "WINDOW_OUT_OF_RANGE",
            "HOLDINGS_COUNT_OUT_OF_RANGE",
            "REBALANCE_INTERVAL_OUT_OF_RANGE",
        }
        assert client.get("/api/v1/workspace").json()["resource_counts"]["research_runs"] == 0

        restored = client.put(
            f"/api/v1/research-definitions/{draft['id']}",
            json=valid_definition(),
        ).json()
        run_response = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "valid-run"},
        )
        assert run_response.status_code == 202
        frozen = run_response.json()["frozen_definition"]
        run = run_response.json()["run"]
        assert run["status"] == "queued"
        assert run["dataset_release_id"] == release["id"]
        assert frozen["draft_id"] == draft["id"]
        assert frozen["content"]["dataset_release"] == release["id"]
        assert frozen["content"]["numeric_execution_contract"] == "thesistrace-numeric-v1"
        assert frozen["content"]["semantic_versions"] == {
            "alpha": "alpha-v1",
            "factor": "factor-v1",
            "strategy": "strategy-v1",
            "kernel": "kernel-v1",
        }
        assert frozen["content"]["field_bindings"] == [
            {"name": "close_adj", "field_id": "price.close.adjusted"}
        ]
        assert len(frozen["content_hash"]) == 64

        changed = {
            **valid_definition(),
            "hypothesis": "后来修改的草稿，不得改变已冻结版本。",
        }
        client.put(f"/api/v1/research-definitions/{draft['id']}", json=changed)
        frozen_again = client.get(f"/api/v1/research-definition-versions/{frozen['id']}").json()
        assert frozen_again == frozen
        assert (
            restored["updated_at"]
            != client.get(f"/api/v1/research-definitions/{draft['id']}").json()["updated_at"]
        )

        repeated = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "valid-run"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["run"]["id"] == run["id"]
        assert client.post(f"/api/v1/research-definitions/{draft['id']}/freeze").status_code in {
            404,
            405,
        }

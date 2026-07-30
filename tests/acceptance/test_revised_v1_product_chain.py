from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import (
    MAX_RESULT_BUNDLE_BYTES,
    ResearchRunService,
)
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingService

FORBIDDEN_RESULT_OBJECTS = {
    "alpha_matrix",
    "forward_labels",
    "factor_evaluation",
    "daily_factor",
    "orders",
    "child_orders",
    "fills",
    "rejections",
}


def definition() -> dict[str, object]:
    return {
        "title": "V1 产品链验收",
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


def test_revised_v1_chain_through_public_api(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    datasets = DatasetPublisher(metadata, objects)
    runs = ResearchRunService(metadata, datasets, objects)
    tracking = DailyTrackingService(
        metadata,
        datasets,
        objects,
    )

    with TestClient(create_app(settings)) as client:
        seed = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "v1-chain-seed"},
            json={"fixture": "v1"},
        ).json()["release"]
        canonical = datasets.materialize_canonical(seed)
        historical_open = next(
            row
            for row in canonical["prices"]
            if row["session"] == canonical["research_calendar"][0]
            and row["instrument_id"] == "equity:600000.SH"
        )

        draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        requested = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "v1-chain-run"},
        )
        assert requested.status_code == 202
        run_id = requested.json()["run"]["id"]
        assert runs.execute(run_id)["status"] == "succeeded"

        result = client.get(f"/api/v1/research-runs/{run_id}/result").json()
        manifest = result["manifest"]
        assert manifest["logical_bytes"]["total"] <= MAX_RESULT_BUNDLE_BYTES
        assert not (set(manifest["objects"]) & FORBIDDEN_RESULT_OBJECTS)
        assert len(result["strategy_backtest"]["daily"]) == 504
        assert all(
            "daily" not in horizon
            for horizon in result["factor_evaluation"]["horizons"].values()
        )
        assert "orders" not in result["strategy_backtest"]
        assert "rejections" not in result["strategy_backtest"]
        assert client.get("/api/v1/objects/not-a-public-download").status_code == 404

        activated = client.post(
            f"/api/v1/research-runs/{run_id}/daily-tracks",
            headers={"Idempotency-Key": "v1-chain-track"},
        )
        assert activated.status_code == 201
        track_id = activated.json()["id"]

        first_increment = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "v1-chain-increment-1"},
            json={"new_sessions": 1, "corrections": []},
        ).json()["release"]
        assert tracking.execute_next()["status"] == "succeeded"
        assert tracking.get_track(track_id)["head"][
            "target_dataset_release_id"
        ] == first_increment["id"]

        tracking.cache.delete(track_id)
        assert track_id not in tracking.cache.list_track_ids()
        second_increment = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "v1-chain-increment-2"},
            json={"new_sessions": 1, "corrections": []},
        ).json()["release"]
        assert tracking.execute_next()["status"] == "succeeded"
        rebuilt = tracking.get_track(track_id)
        assert rebuilt["head"]["target_dataset_release_id"] == second_increment["id"]
        assert track_id in tracking.cache.list_track_ids()

        correction = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "v1-chain-correction"},
            json={
                "new_sessions": 1,
                "corrections": [
                    {
                        "session": canonical["research_calendar"][0],
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
        assert tracking.execute_next()["status"] == "succeeded"
        current = client.get(
            f"/api/v1/daily-tracks/{track_id}/current"
        ).json()
        assert current["checkpoint"]["correction_boundary"][
            "target_dataset_release_id"
        ] == correction["id"]

        verified = client.post(
            f"/api/v1/daily-tracks/{track_id}/verify-equivalence"
        )
        assert verified.status_code == 200
        assert verified.json()["release_sequence"][-1] == correction["id"]

        stopped = client.post(f"/api/v1/daily-tracks/{track_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
        assert track_id not in tracking.cache.list_track_ids()

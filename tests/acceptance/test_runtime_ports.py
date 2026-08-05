from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.runtime import RuntimePorts, build_runtime
from thesistrace.storage import MetadataStore


class RecordingDispatch:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def dispatch(self, resource_kind: str, resource_id: str) -> None:
        self.events.append((resource_kind, resource_id))


def test_local_runtime_ports_preserve_the_v1_application(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    runtime = build_runtime(settings)
    dispatch = RecordingDispatch()
    runtime = RuntimePorts(
        control_metadata=runtime.control_metadata,
        objects=runtime.objects,
        execution_dispatch=dispatch,
    )

    with TestClient(create_app(settings, runtime_ports=runtime)) as client:
        published = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "runtime-port-bootstrap"},
            json={"fixture": "v1"},
        )
        assert published.status_code == 201
        assert client.get("/api/v1/workspace").json()["resource_counts"]["dataset_releases"] == 1
        draft = client.post(
            "/api/v1/research-definitions",
            json={
                "title": "runtime ports",
                "hypothesis": "runtime ports preserve V1",
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
            },
        ).json()
        requested = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "runtime-port-run"},
        ).json()
        assert dispatch.events == [("research_run", requested["run"]["id"])]


def test_research_run_service_accepts_explicit_structural_ports(tmp_path: Path) -> None:
    metadata = MetadataStore(tmp_path / "metadata.sqlite3")
    metadata.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    datasets = DatasetPublisher(metadata, objects)
    ResearchRunService(metadata, datasets, objects)

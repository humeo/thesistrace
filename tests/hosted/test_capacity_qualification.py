import asyncio
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import yaml
from temporalio.service import RPCError, RPCStatusCode

from thesistrace.capacity import CapacityQualificationService
from thesistrace.config import Settings
from thesistrace.hosted import capacity_probe
from thesistrace.hosted.activity_policy import HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT
from thesistrace.operator import run
from thesistrace.storage import MetadataStore

ROOT = Path(__file__).resolve().parents[2]


def test_heavy_activity_heartbeat_tolerates_constrained_cpu_sections() -> None:
    assert HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT == timedelta(minutes=5)
    workflow_paths = (
        "capacity_workflow.py",
        "dataset_publication_workflow.py",
        "research_workflow.py",
        "tracking_operations_workflow.py",
        "tracking_workflow.py",
    )
    for name in workflow_paths:
        source = (ROOT / "src" / "thesistrace" / "hosted" / name).read_text()
        assert "heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT" in source
        assert "heartbeat_timeout=timedelta(seconds=30)" not in source


def test_capacity_scenario_uses_retry_safe_untyped_temporal_results(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object], dict[str, object]]] = []
    results: dict[str, dict[str, object]] = {}
    result_attempts: dict[str, int] = {}

    class Handle:
        def __init__(self, workflow_id: str) -> None:
            self.workflow_id = workflow_id

        async def result(self) -> dict[str, object]:
            result_attempts[self.workflow_id] = (
                result_attempts.get(self.workflow_id, 0) + 1
            )
            if result_attempts[self.workflow_id] == 1:
                raise RPCError(
                    "injected history timeout",
                    RPCStatusCode.DEADLINE_EXCEEDED,
                    b"",
                )
            return results[self.workflow_id]

    class Client:
        async def start_workflow(
            self,
            workflow: str,
            request: dict[str, object],
            **options: object,
        ) -> Handle:
            calls.append((workflow, request, options))
            workflow_id = str(options["id"])
            if request.get("operation") == "increment":
                results[workflow_id] = {
                    "created": True,
                    "workflow_id": "publication",
                }
            elif "ordinal" in request:
                ordinal = str(request["ordinal"])
                results[workflow_id] = {
                    "worker_slot": f"worker-{ordinal}",
                    "workflow_id": f"compute-{ordinal}",
                }
            else:
                results[workflow_id] = {
                    "release_id": "release-1",
                    "created": True,
                }
            return Handle(workflow_id)

        def get_workflow_handle(
            self,
            workflow_id: str,
            *,
            result_type: type,
        ) -> Handle:
            assert result_type is dict
            return Handle(workflow_id)

    async def connect(*_args: object, **_kwargs: object) -> Client:
        return Client()

    monkeypatch.setattr(capacity_probe.Client, "connect", connect)
    monkeypatch.setattr(capacity_probe, "RESULT_RETRY_SECONDS", 0)
    result = asyncio.run(
        capacity_probe.run_scenario(
            temporal_address="temporal:7233",
            namespace="thesistrace",
        )
    )

    assert result["prepare"]["release_id"] == "release-1"
    assert calls[0][0] == "CapacityQualificationDataWorkflow"
    assert calls[0][1]["idempotency_key"] == "capacity-qualification-top3000-v1"
    assert all(call[2]["result_type"] is dict for call in calls)
    assert all(attempts == 2 for attempts in result_attempts.values())


def test_capacity_result_wait_retries_when_temporal_reconnect_times_out(
    monkeypatch,
) -> None:
    result_attempts = 0
    connect_attempts = 0

    class Handle:
        async def result(self) -> dict[str, object]:
            nonlocal result_attempts
            result_attempts += 1
            if result_attempts < 3:
                raise RPCError(
                    "injected history timeout",
                    RPCStatusCode.DEADLINE_EXCEEDED,
                    b"",
                )
            return {"status": "succeeded"}

    class Client:
        def get_workflow_handle(
            self,
            workflow_id: str,
            *,
            result_type: type,
        ) -> Handle:
            assert workflow_id == "capacity-probe"
            assert result_type is dict
            return Handle()

    async def connect(*_args: object, **_kwargs: object) -> Client:
        nonlocal connect_attempts
        connect_attempts += 1
        if connect_attempts == 1:
            raise RuntimeError("injected get_system_info timeout")
        return Client()

    monkeypatch.setattr(capacity_probe.Client, "connect", connect)
    monkeypatch.setattr(capacity_probe, "RESULT_RETRY_SECONDS", 0)

    result = asyncio.run(
        capacity_probe._resilient_workflow_result(
            Handle(),
            workflow_id="capacity-probe",
            temporal_address="temporal:7233",
            namespace="thesistrace",
        )
    )

    assert result == {"status": "succeeded"}
    assert result_attempts == 3
    assert connect_attempts == 2


def test_capacity_result_wait_outlives_a_fixed_transient_failure_budget(
    monkeypatch,
) -> None:
    result_attempts = 0

    class Handle:
        async def result(self) -> dict[str, object]:
            nonlocal result_attempts
            result_attempts += 1
            if result_attempts <= 31:
                raise RPCError(
                    "Not enough hosts to serve the request",
                    RPCStatusCode.UNAVAILABLE,
                    b"",
                )
            return {"status": "succeeded"}

    class Client:
        def get_workflow_handle(
            self,
            workflow_id: str,
            *,
            result_type: type,
        ) -> Handle:
            assert workflow_id == "capacity-probe"
            assert result_type is dict
            return Handle()

    async def connect(*_args: object, **_kwargs: object) -> Client:
        return Client()

    monkeypatch.setattr(capacity_probe.Client, "connect", connect)
    monkeypatch.setattr(capacity_probe, "RESULT_RETRY_SECONDS", 0)

    result = asyncio.run(
        capacity_probe._resilient_workflow_result(
            Handle(),
            workflow_id="capacity-probe",
            temporal_address="temporal:7233",
            namespace="thesistrace",
        )
    )

    assert result == {"status": "succeeded"}
    assert result_attempts == 32


def passing_evidence() -> dict[str, object]:
    return {
        "universe": "top3000",
        "compute_workers": [
            {
                "status": "succeeded",
                "activity_attempt": 1,
                "p99_memory_mib": 699,
                "peak_memory_mib": 799,
            }
            for _index in range(4)
        ],
        "dataset_publication": {
            "status": "succeeded",
            "worker_slot": "data-1",
            "activity_attempt": 1,
        },
        "nonworker_services": {"memory_limit_mib": 5120, "cpu_limit": 2},
        "swap_used": False,
        "oom_kill": False,
        "unexpected_restart": False,
        "missing_heartbeat": False,
        "duplicate_publication": False,
        "incorrect_result": False,
        "production_paths": {
            "parquet": True,
            "result_bundle": True,
            "working_cache": True,
            "postgresql": True,
            "temporal": True,
            "object_store": True,
        },
    }


def test_capacity_evidence_rejects_retried_measured_activities(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    service = CapacityQualificationService(store)
    retried_compute = passing_evidence()
    retried_compute["compute_workers"][0]["activity_attempt"] = 2

    compute_record = service.record(
        actor="operator-1",
        release_bundle_id="release-1",
        evidence=retried_compute,
    )

    assert compute_record["status"] == "failed"
    assert "compute_activity_retried" in compute_record["failures"]

    retried_publication = passing_evidence()
    retried_publication["dataset_publication"]["activity_attempt"] = 2
    publication_record = service.record(
        actor="operator-1",
        release_bundle_id="release-1",
        evidence=retried_publication,
    )

    assert publication_record["status"] == "failed"
    assert "dataset_publication_retried" in publication_record["failures"]


def test_latest_capacity_measurement_is_an_immutable_launch_gate(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    service = CapacityQualificationService(store)
    assert service.is_qualified() is False

    failing = passing_evidence()
    failing["compute_workers"][0]["peak_memory_mib"] = 801
    recorded_failure = service.record(
        actor="operator-1",
        release_bundle_id="release-1",
        evidence=failing,
    )
    assert recorded_failure["status"] == "failed"
    assert service.is_qualified() is False

    recorded_pass = service.record(
        actor="operator-1",
        release_bundle_id="release-1",
        evidence=passing_evidence(),
    )
    assert recorded_pass["status"] == "passed"
    assert service.is_qualified() is True

    assert CapacityQualificationService(
        store,
        required_release_bundle_id="release-2",
    ).is_qualified() is False
    assert CapacityQualificationService(
        store,
        required_release_bundle_id="release-1",
    ).is_qualified() is True

    with store.connect() as connection:
        try:
            connection.execute(
                "UPDATE capacity_qualifications SET status = 'failed' WHERE id = ?",
                (recorded_pass["id"],),
            )
        except sqlite3.IntegrityError as error:
            assert "immutable" in str(error)
        else:
            raise AssertionError("capacity qualification was mutable")


def test_operator_records_and_inspects_capacity_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    evidence_path = tmp_path / "capacity.json"
    evidence_path.write_text(json.dumps(passing_evidence()), encoding="utf-8")

    assert run(
        [
            "capacity-qualification",
            "record",
            "--actor",
            "operator-1",
            "--release-bundle-id",
            "release-1",
            "--evidence",
            str(evidence_path),
        ],
        settings=settings,
    ) == 0
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["status"] == "passed"

    assert run(
        ["capacity-qualification", "inspect"],
        settings=settings,
    ) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["id"] == recorded["id"]


def test_compose_declares_the_complete_host_resource_envelope() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "hosted" / "compose.yaml").read_text())
    steady = (
        "postgres",
        "temporal-postgres",
        "temporal",
        "postgrest",
        "deno",
        "insforge",
        "object-store",
        "api",
        "execution-relay",
        "tushare-egress",
        "health-service",
        "otel-collector",
        "prometheus",
        "grafana",
        "edge",
    )

    def memory_mib(value: str) -> float:
        return float(value[:-1]) * (1024 if value.endswith("g") else 1)

    services = compose["services"]
    assert sum(memory_mib(services[name]["mem_limit"]) for name in steady) <= 5120
    assert sum(float(services[name]["cpus"]) for name in steady) <= 2
    assert float(services["health-service"]["cpus"]) >= 0.2
    assert float(services["execution-relay"]["cpus"]) >= 0.1
    for name in steady:
        assert services[name]["memswap_limit"] == services[name]["mem_limit"]
    for index in range(1, 5):
        worker = services[f"compute-worker-{index}"]
        assert worker["mem_limit"] == "1g"
        assert worker["memswap_limit"] == "1g"
        assert float(worker["cpus"]) == 0.75
    assert services["data-worker"]["mem_limit"] == "1g"
    assert services["data-worker"]["memswap_limit"] == "1g"
    assert float(services["data-worker"]["cpus"]) == 0.5


def test_capacity_probe_coordinator_runs_in_the_data_worker() -> None:
    script = (ROOT / "scripts" / "hosted" / "capacity_qualification.py").read_text()

    assert '_container_id(arguments.project, DATA_SERVICE)' in script
    assert '_container_id(arguments.project, "execution-relay")' not in script


def test_hosted_operator_uses_the_admin_database_boundary() -> None:
    script = (ROOT / "scripts" / "hosted-stack").read_text()

    assert (
        'compose run --rm --no-deps -T thesistrace-migrations '
        'thesistrace-operator "$@"'
    ) in script
    assert 'compose exec -T api thesistrace-operator "$@"' not in script


def test_capacity_schema_is_immutable_and_not_granted_to_service_roles() -> None:
    migration = (
        ROOT
        / "deploy"
        / "hosted"
        / "migrations"
        / "0023_capacity_qualification.sql"
    ).read_text()
    assert "capacity_qualifications" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "REVOKE ALL" in migration
    assert "GRANT" not in migration

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from thesistrace.activity_contract import CooperativeActivityCancellation
from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted import temporal_worker
from thesistrace.hosted.execution_relay import relay_once
from thesistrace.hosted.tracking_operations_workflow import (
    tracking_equivalence_workflow_id,
    tracking_generation_rebuild_workflow_id,
)
from thesistrace.objects import ImmutableObjectStore
from thesistrace.operator import run as run_operator
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingService, EquivalenceError
from thesistrace.tracking_operations import (
    TrackingOperationError,
    TrackingOperationResourceExhaustion,
    TrackingOperationService,
)
from thesistrace.working_cache import WorkingCacheStore


def definition() -> dict[str, object]:
    return {
        "title": "Tracking operations",
        "hypothesis": "动量具有持续性。",
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


def active_track(
    tmp_path: Path,
) -> tuple[TrackingOperationService, dict[str, object]]:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "operations-seed"},
            json={"fixture": "v1"},
        ).raise_for_status()
        draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        run = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "operations-run"},
        ).json()["run"]
    metadata = MetadataStore(settings.metadata_path)
    objects = ImmutableObjectStore(settings.object_root)
    publisher = DatasetPublisher(metadata, objects)
    ResearchRunService(metadata, publisher, objects).execute(str(run["id"]))
    tracking = DailyTrackingService(
        metadata,
        publisher,
        objects,
        WorkingCacheStore(settings.working_cache_root),
    )
    track, _created = tracking.activate(
        str(run["id"]),
        "operations-track",
    )
    return TrackingOperationService(metadata, tracking), track


def test_equivalence_is_async_idempotent_and_publishes_bounded_result(
    tmp_path: Path,
) -> None:
    service, track = active_track(tmp_path)
    release, _created = service.tracking.datasets.publish_fixture_increment(
        "operations-equivalence-increment",
        new_sessions=1,
        corrections=[],
    )
    advance = service.tracking.enqueue_toward(
        str(track["id"]),
        str(release["id"]),
    )
    assert advance is not None
    assert service.tracking.execute_advance(
        str(advance["id"])
    )["status"] == "succeeded"

    requested, created = service.request_equivalence(
        str(track["id"]),
        "equivalence-request",
    )
    repeated, repeated_created = service.request_equivalence(
        str(track["id"]),
        "equivalence-request",
    )

    assert created is True
    assert repeated_created is False
    assert requested == repeated
    assert requested["status"] == "queued"
    assert "result" not in requested

    completed = service.execute_equivalence(str(requested["id"]))

    assert completed["status"] == "succeeded"
    assert completed["result"]["outcome"] == "equivalent"
    assert completed["result"]["release_count"] == 2
    assert len(completed["result"]["trace_chain_sha256"]) == 64
    assert "release_sequence" not in completed["result"]
    assert "trace_checksums" not in completed["result"]
    assert service.execute_equivalence(str(requested["id"])) == completed
    deliberate, deliberate_created = service.request_equivalence(
        str(track["id"]),
        "equivalence-deliberate-rerun",
    )
    assert deliberate_created is True
    assert deliberate["id"] != requested["id"]


def test_equivalence_publishes_only_first_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, track = active_track(tmp_path)
    requested, _created = service.request_equivalence(
        str(track["id"]),
        "equivalence-divergence",
    )
    monkeypatch.setattr(
        service.tracking,
        "verify_equivalence",
        lambda _track_id, **_options: (_ for _ in ()).throw(
            EquivalenceError(
                "EQUIVALENCE_MISMATCH at $.checkpoints.checkpoint-1"
            )
        ),
    )

    completed = service.execute_equivalence(str(requested["id"]))

    assert completed["result"] == {
        "outcome": "first_divergence",
        "path": "$.checkpoints.checkpoint-1",
    }


def test_equivalence_resource_exhaustion_publishes_no_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, track = active_track(tmp_path)
    requested, _created = service.request_equivalence(
        str(track["id"]),
        "equivalence-resource-exhaustion",
    )
    prior_head_id = track["head_checkpoint_id"]
    manifest_paths = set(
        (service.tracking.objects.root / "manifests").glob("*.json")
    )
    payload_paths = set(
        (service.tracking.objects.root / "sha256").glob("*/*")
    )

    monkeypatch.setattr(
        service.tracking,
        "verify_equivalence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError),
    )

    with pytest.raises(MemoryError):
        service.execute_equivalence(str(requested["id"]))
    with pytest.raises(MemoryError):
        service.execute_equivalence(str(requested["id"]))
    failed = service.fail_equivalence(
        str(requested["id"]),
        "RESOURCE_EXHAUSTED",
    )
    current = service.tracking.get_track(str(track["id"]))

    assert failed["status"] == "failed"
    assert failed["diagnostic"] == {"reason_code": "RESOURCE_EXHAUSTED"}
    assert "result" not in failed
    assert current is not None
    assert current["head_checkpoint_id"] == prior_head_id
    assert set(
        (service.tracking.objects.root / "manifests").glob("*.json")
    ) == manifest_paths
    assert set(
        (service.tracking.objects.root / "sha256").glob("*/*")
    ) == payload_paths


def test_equivalence_api_returns_async_resource_and_idempotent_status(
    tmp_path: Path,
) -> None:
    service, track = active_track(tmp_path)
    settings = Settings(
        metadata_path=service.metadata.path,
        object_root=service.tracking.objects.root,
        working_cache_root=service.tracking.cache.root,
    )
    with TestClient(create_app(settings)) as client:
        requested = client.post(
            f"/api/v1/daily-tracks/{track['id']}/equivalence-requests",
            headers={"Idempotency-Key": "equivalence-api"},
        )
        repeated = client.post(
            f"/api/v1/daily-tracks/{track['id']}/equivalence-requests",
            headers={"Idempotency-Key": "equivalence-api"},
        )
        inspected = client.get(
            f"/api/v1/daily-tracks/{track['id']}/equivalence-requests/"
            f"{requested.json()['id']}"
        )
        cancelled = client.post(
            f"/api/v1/daily-tracks/{track['id']}/equivalence-requests/"
            f"{requested.json()['id']}/cancel"
        )

    assert requested.status_code == 202
    assert repeated.status_code == 200
    assert requested.json() == repeated.json() == inspected.json()
    assert requested.json()["status"] == "queued"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_equivalence_cancellation_is_terminal_and_fences_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, track = active_track(tmp_path)
    requested, _created = service.request_equivalence(
        str(track["id"]),
        "equivalence-cancel",
    )

    def cancel(_stage: str) -> None:
        service.cancel_equivalence(str(requested["id"]))
        raise CooperativeActivityCancellation

    with pytest.raises(CooperativeActivityCancellation):
        service.execute_equivalence(
            str(requested["id"]),
            progress=cancel,
        )

    cancelled = service.equivalence_request(str(requested["id"]))
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert cancelled["diagnostic"] == {"reason_code": "CANCELLED"}
    assert "result" not in cancelled

    delivered: list[str] = []

    def record_cancel(
        _connection,
        *,
        resource_kind,
        **_values,
    ) -> None:
        delivered.append(resource_kind)

    monkeypatch.setattr(
        service.metadata,
        "_enqueue_tracking_operation",
        record_cancel,
    )
    second, _created = service.request_equivalence(
        str(track["id"]),
        "equivalence-repeat-cancel",
    )
    service.cancel_equivalence(
        str(second["id"]),
        enqueue_workflow_cancellation=True,
    )
    service.cancel_equivalence(
        str(second["id"]),
        enqueue_workflow_cancellation=True,
    )
    assert delivered == [
        "tracking_equivalence",
        "tracking_equivalence_cancel",
    ]


def test_generation_rebuild_is_operator_only_idempotent_and_immutable(
    tmp_path: Path,
) -> None:
    service, track = active_track(tmp_path)
    with pytest.raises(PermissionError):
        service.request_generation_rebuild(
            str(track["id"]),
            calculation_kernel="kernel-v2",
            numeric_execution_contract=str(
                track["numeric_execution_contract"]
            ),
            idempotency_key="rebuild-request",
            operator_authorized=False,
        )

    requested, created = service.request_generation_rebuild(
        str(track["id"]),
        calculation_kernel="kernel-v2",
        numeric_execution_contract=str(
            track["numeric_execution_contract"]
        ),
        idempotency_key="rebuild-request",
        operator_authorized=True,
    )
    repeated, repeated_created = service.request_generation_rebuild(
        str(track["id"]),
        calculation_kernel="kernel-v2",
        numeric_execution_contract=str(
            track["numeric_execution_contract"]
        ),
        idempotency_key="rebuild-request",
        operator_authorized=True,
    )
    assert created is True
    assert repeated_created is False
    assert repeated == requested

    prior_generation_id = str(track["current_generation_id"])
    prior_head_id = str(track["head_checkpoint_id"])
    completed = service.execute_generation_rebuild(
        str(requested["id"])
    )
    current = service.tracking.get_track(str(track["id"]))

    assert completed["status"] == "succeeded"
    assert current is not None
    assert current["current_generation_id"] != prior_generation_id
    assert current["head_checkpoint_id"] != prior_head_id
    assert any(
        generation["id"] == prior_generation_id
        for generation in current["generations"]
    )
    assert service.execute_generation_rebuild(
        str(requested["id"])
    ) == completed


def test_failed_generation_rebuild_removes_partial_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, track = active_track(tmp_path)
    requested, _created = service.request_generation_rebuild(
        str(track["id"]),
        calculation_kernel="kernel-v2",
        numeric_execution_contract=str(
            track["numeric_execution_contract"]
        ),
        idempotency_key="rebuild-failure",
        operator_authorized=True,
    )
    prior_generation_ids = {
        str(item["id"])
        for item in track["generations"]
    }
    monkeypatch.setattr(
        service.tracking,
        "execute_advance",
        lambda _advance_id, **_options: {"status": "blocked"},
    )

    with pytest.raises(TrackingOperationError):
        service.execute_generation_rebuild(str(requested["id"]))
    failed = service.fail_generation_rebuild(
        str(requested["id"]),
        "ACTIVITY_DELIVERY_FAILED",
    )
    current = service.tracking.get_track(str(track["id"]))

    assert failed["status"] == "failed"
    assert failed["generation_id"] is None
    assert failed["advance_id"] is None
    assert current is not None
    assert {
        str(item["id"])
        for item in current["generations"]
    } == prior_generation_ids
    assert current["head_checkpoint_id"] == track["head_checkpoint_id"]


def test_generation_and_advance_binding_roll_back_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, track = active_track(tmp_path)
    requested, _created = service.request_generation_rebuild(
        str(track["id"]),
        calculation_kernel="kernel-v2",
        numeric_execution_contract=str(
            track["numeric_execution_contract"]
        ),
        idempotency_key="rebuild-atomic-binding",
        operator_authorized=True,
    )
    prior_generation_ids = {
        str(item["id"]) for item in track["generations"]
    }
    prior_advance_ids = {
        str(item["id"]) for item in track["advances"]
    }

    def reject_binding(*_args, **_kwargs) -> None:
        raise RuntimeError("forced bind failure")

    monkeypatch.setattr(
        service.metadata,
        "bind_tracking_generation_rebuild",
        reject_binding,
    )

    with pytest.raises(RuntimeError, match="forced bind failure"):
        service.execute_generation_rebuild(str(requested["id"]))

    current = service.tracking.get_track(str(track["id"]))
    pending = service.generation_rebuild(str(requested["id"]))
    assert current is not None
    assert pending is not None
    assert {
        str(item["id"]) for item in current["generations"]
    } == prior_generation_ids
    assert {
        str(item["id"]) for item in current["advances"]
    } == prior_advance_ids
    assert pending["generation_id"] is None
    assert pending["advance_id"] is None


def test_generation_rebuild_propagates_nested_resource_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, track = active_track(tmp_path)
    requested, _created = service.request_generation_rebuild(
        str(track["id"]),
        calculation_kernel="kernel-v2",
        numeric_execution_contract=str(
            track["numeric_execution_contract"]
        ),
        idempotency_key="rebuild-nested-exhaustion",
        operator_authorized=True,
    )
    manifest_paths = set(
        (service.tracking.objects.root / "manifests").glob("*.json")
    )
    payload_paths = set(
        (service.tracking.objects.root / "sha256").glob("*/*")
    )

    def exhaust(*_args, **_kwargs):
        raise MemoryError

    monkeypatch.setattr(
        service.tracking,
        "_calculate_advance",
        exhaust,
    )

    with pytest.raises(TrackingOperationResourceExhaustion):
        service.execute_generation_rebuild(str(requested["id"]))
    with pytest.raises(TrackingOperationResourceExhaustion):
        service.execute_generation_rebuild(str(requested["id"]))

    failed = service.fail_generation_rebuild(
        str(requested["id"]),
        "RESOURCE_EXHAUSTED",
    )
    current = service.tracking.get_track(str(track["id"]))
    assert failed["status"] == "failed"
    assert failed["diagnostic"] == {
        "reason_code": "RESOURCE_EXHAUSTED"
    }
    assert failed["generation_id"] is None
    assert failed["advance_id"] is None
    assert current is not None
    assert current["current_generation_id"] == track[
        "current_generation_id"
    ]
    assert current["head_checkpoint_id"] == track["head_checkpoint_id"]
    assert set(
        (service.tracking.objects.root / "manifests").glob("*.json")
    ) == manifest_paths
    assert set(
        (service.tracking.objects.root / "sha256").glob("*/*")
    ) == payload_paths


def test_generation_rebuild_cancellation_removes_prepared_generation(
    tmp_path: Path,
) -> None:
    service, track = active_track(tmp_path)
    requested, _created = service.request_generation_rebuild(
        str(track["id"]),
        calculation_kernel="kernel-v2",
        numeric_execution_contract=str(
            track["numeric_execution_contract"]
        ),
        idempotency_key="rebuild-cancel",
        operator_authorized=True,
    )
    prior_generation_ids = {
        str(item["id"]) for item in track["generations"]
    }

    def cancel(stage: str) -> None:
        if stage != "generation-prepared":
            return
        service.cancel_generation_rebuild(str(requested["id"]))
        raise CooperativeActivityCancellation

    with pytest.raises(CooperativeActivityCancellation):
        service.execute_generation_rebuild(
            str(requested["id"]),
            progress=cancel,
        )

    cancelled = service.generation_rebuild(str(requested["id"]))
    current = service.tracking.get_track(str(track["id"]))
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert cancelled["diagnostic"] == {"reason_code": "CANCELLED"}
    assert cancelled["generation_id"] is None
    assert cancelled["advance_id"] is None
    assert current is not None
    assert {
        str(item["id"]) for item in current["generations"]
    } == prior_generation_ids


class RecordingClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []
        self.cancelled: list[str] = []

    async def start_workflow(self, workflow, request, **options):
        self.starts.append(
            {
                "workflow": workflow,
                "request": request,
                "options": options,
            }
        )

    def get_workflow_handle(self, workflow_id: str):
        client = self

        class Handle:
            async def cancel(self) -> None:
                client.cancelled.append(workflow_id)

        return Handle()


class OperationOutbox:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def pending(self, *, limit: int):
        assert limit == 25
        return [
            {
                "outbox_id": "outbox-equivalence",
                "workspace_id": "workspace-1",
                "resource_kind": "tracking_equivalence",
                "resource_id": "equivalence-1",
            },
            {
                "outbox_id": "outbox-rebuild",
                "workspace_id": "workspace-1",
                "resource_kind": "tracking_generation_rebuild",
                "resource_id": "rebuild-1",
            },
        ]

    def mark_dispatched(self, outbox_id: str) -> bool:
        self.dispatched.append(outbox_id)
        return True


def test_relay_starts_stable_finite_tracking_operation_workflows() -> None:
    client = RecordingClient()
    outbox = OperationOutbox()

    assert asyncio.run(relay_once(client, outbox)) == 2
    assert [item["options"]["id"] for item in client.starts] == [
        tracking_equivalence_workflow_id("equivalence-1"),
        tracking_generation_rebuild_workflow_id("rebuild-1"),
    ]
    assert outbox.dispatched == [
        "outbox-equivalence",
        "outbox-rebuild",
    ]


def test_relay_cancels_stable_tracking_operation_workflows() -> None:
    class CancellationOutbox(OperationOutbox):
        def pending(self, *, limit: int):
            assert limit == 25
            return [
                {
                    "outbox_id": "cancel-equivalence",
                    "workspace_id": "workspace-1",
                    "resource_kind": "tracking_equivalence_cancel",
                    "resource_id": "equivalence-1",
                },
                {
                    "outbox_id": "cancel-rebuild",
                    "workspace_id": "workspace-1",
                    "resource_kind": (
                        "tracking_generation_rebuild_cancel"
                    ),
                    "resource_id": "rebuild-1",
                },
            ]

    client = RecordingClient()
    outbox = CancellationOutbox()

    assert asyncio.run(relay_once(client, outbox)) == 2
    assert client.cancelled == [
        tracking_equivalence_workflow_id("equivalence-1"),
        tracking_generation_rebuild_workflow_id("rebuild-1"),
    ]


def test_relay_treats_missing_cancel_target_as_idempotent() -> None:
    class MissingHandle:
        async def cancel(self) -> None:
            raise RPCError(
                "workflow not found",
                RPCStatusCode.NOT_FOUND,
                b"",
            )

    class MissingClient(RecordingClient):
        def get_workflow_handle(self, _workflow_id: str):
            return MissingHandle()

    class CancellationOutbox(OperationOutbox):
        def pending(self, *, limit: int):
            assert limit == 25
            return [
                {
                    "outbox_id": "cancel-missing",
                    "workspace_id": "workspace-1",
                    "resource_kind": "tracking_equivalence_cancel",
                    "resource_id": "equivalence-missing",
                }
            ]

    client = MissingClient()
    outbox = CancellationOutbox()

    assert asyncio.run(relay_once(client, outbox)) == 1
    assert outbox.dispatched == ["cancel-missing"]


def test_operator_cli_is_the_generation_rebuild_request_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    class FakeOperations:
        def request_generation_rebuild(self, track_id, **options):
            calls.append({"track_id": track_id, **options})
            return (
                {
                    "id": "rebuild-1",
                    "daily_track_id": track_id,
                    "status": "queued",
                },
                True,
            )

    settings = Settings(
        metadata_path=tmp_path / "operator.sqlite3",
        object_root=tmp_path / "operator-objects",
    )
    exit_code = run_operator(
        [
            "tracking-generation-rebuild",
            "request",
            "--actor",
            "operator-1",
            "--workspace-id",
            "workspace-1",
            "--track-id",
            "track-1",
            "--calculation-kernel",
            "kernel-v2",
            "--numeric-execution-contract",
            "numeric-v1",
            "--idempotency-key",
            "rebuild-key",
        ],
        settings=settings,
        tracking_operation_service=FakeOperations(),
    )

    assert exit_code == 0
    assert calls == [
        {
            "track_id": "track-1",
            "calculation_kernel": "kernel-v2",
            "numeric_execution_contract": "numeric-v1",
            "idempotency_key": "rebuild-key",
            "operator_authorized": True,
        }
    ]
    assert '"status": "queued"' in capsys.readouterr().out
    audit = MetadataStore(
        settings.metadata_path
    ).list_management_audit_events()[-1]
    assert audit["actor"] == "operator-1"
    assert audit["action"] == "tracking_generation_rebuild.request"


def test_operator_cli_cancels_generation_rebuild(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    class FakeOperations:
        def cancel_generation_rebuild(self, rebuild_id, **options):
            calls.append({"rebuild_id": rebuild_id, **options})
            return {
                "id": rebuild_id,
                "daily_track_id": "track-1",
                "status": "cancelled",
            }

    settings = Settings(
        metadata_path=tmp_path / "operator-cancel.sqlite3",
        object_root=tmp_path / "operator-cancel-objects",
    )
    exit_code = run_operator(
        [
            "tracking-generation-rebuild",
            "cancel",
            "--actor",
            "operator-1",
            "--workspace-id",
            "workspace-1",
            "--rebuild-id",
            "rebuild-1",
        ],
        settings=settings,
        tracking_operation_service=FakeOperations(),
    )

    assert exit_code == 0
    assert calls == [
        {
            "rebuild_id": "rebuild-1",
            "enqueue_workflow_cancellation": False,
        }
    ]
    assert '"status": "cancelled"' in capsys.readouterr().out
    audit = MetadataStore(
        settings.metadata_path
    ).list_management_audit_events()[-1]
    assert audit["action"] == "tracking_generation_rebuild.cancel"


@pytest.mark.parametrize(
    ("activity_name", "identifier_key"),
    [
        ("equivalence", "request_id"),
        ("rebuild", "rebuild_id"),
    ],
)
def test_tracking_operation_activities_cancel_cooperatively(
    monkeypatch: pytest.MonkeyPatch,
    activity_name: str,
    identifier_key: str,
) -> None:
    cancelled: list[str] = []

    class CancelService:
        def execute_equivalence(
            self,
            _identifier,
            *,
            progress,
        ):
            progress("inside-equivalence")

        def execute_generation_rebuild(
            self,
            _identifier,
            *,
            progress,
        ):
            progress("inside-rebuild")

        def cancel_equivalence(self, identifier):
            cancelled.append(identifier)

        def cancel_generation_rebuild(self, identifier):
            cancelled.append(identifier)

    class CancellingHeartbeat:
        def __init__(self, *, on_cancel):
            self.on_cancel = on_cancel

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def checkpoint(self, _stage):
            self.on_cancel()
            raise CooperativeActivityCancellation

    monkeypatch.setattr(
        temporal_worker,
        "settings_from_environment",
        lambda: object(),
    )
    monkeypatch.setattr(
        temporal_worker,
        "build_runtime",
        lambda _settings: object(),
    )
    monkeypatch.setattr(
        temporal_worker,
        "_tracking_operation_service",
        lambda _runtime: CancelService(),
    )
    monkeypatch.setattr(
        temporal_worker,
        "ActivityHeartbeat",
        CancellingHeartbeat,
    )
    request = {
        "workspace_id": "workspace-1",
        identifier_key: f"{activity_name}-1",
    }
    execute = (
        temporal_worker.execute_tracking_equivalence
        if activity_name == "equivalence"
        else temporal_worker.execute_tracking_generation_rebuild
    )

    with pytest.raises(CooperativeActivityCancellation):
        execute(request)

    assert cancelled == [f"{activity_name}-1"]


@pytest.mark.parametrize(
    ("activity_name", "identifier_key", "attempt", "non_retryable"),
    [
        ("equivalence", "request_id", 1, False),
        ("equivalence", "request_id", 2, True),
        ("rebuild", "rebuild_id", 1, False),
        ("rebuild", "rebuild_id", 2, True),
    ],
)
def test_tracking_operations_stop_after_two_resource_exhaustions(
    monkeypatch: pytest.MonkeyPatch,
    activity_name: str,
    identifier_key: str,
    attempt: int,
    non_retryable: bool,
) -> None:
    failed: list[tuple[str, str]] = []

    class ExhaustedService:
        def execute_equivalence(self, _identifier, **_options):
            raise MemoryError

        def execute_generation_rebuild(self, _identifier, **_options):
            raise MemoryError

        def fail_equivalence(self, identifier, reason):
            failed.append((identifier, reason))

        def fail_generation_rebuild(self, identifier, reason):
            failed.append((identifier, reason))

        def cancel_equivalence(self, _identifier):
            return None

        def cancel_generation_rebuild(self, _identifier):
            return None

    class Heartbeat:
        def __init__(self, *, on_cancel):
            self.on_cancel = on_cancel

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def checkpoint(self, _stage):
            return None

    monkeypatch.setattr(
        temporal_worker,
        "settings_from_environment",
        lambda: object(),
    )
    monkeypatch.setattr(
        temporal_worker,
        "build_runtime",
        lambda _settings: object(),
    )
    monkeypatch.setattr(
        temporal_worker,
        "_tracking_operation_service",
        lambda _runtime: ExhaustedService(),
    )
    monkeypatch.setattr(
        temporal_worker,
        "ActivityHeartbeat",
        Heartbeat,
    )
    monkeypatch.setattr(
        temporal_worker.activity,
        "info",
        lambda: SimpleNamespace(attempt=attempt),
    )
    request = {
        "workspace_id": "workspace-1",
        identifier_key: f"{activity_name}-1",
    }
    execute = (
        temporal_worker.execute_tracking_equivalence
        if activity_name == "equivalence"
        else temporal_worker.execute_tracking_generation_rebuild
    )

    with pytest.raises(ApplicationError) as error:
        execute(request)

    assert error.value.type == "RESOURCE_EXHAUSTED"
    assert error.value.non_retryable is non_retryable
    assert failed == (
        [(f"{activity_name}-1", "RESOURCE_EXHAUSTED")]
        if attempt == 2
        else []
    )

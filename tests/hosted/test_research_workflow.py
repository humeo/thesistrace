import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError

from thesistrace.api import public_result_view
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted import temporal_worker
from thesistrace.hosted.execution_relay import relay_once
from thesistrace.hosted.research_workflow import (
    RESEARCH_TASK_QUEUE,
    research_workflow_id,
)
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore


class RecordingOutboxStore(MetadataStore):
    def __init__(self, path: Path, *, fail: bool = False) -> None:
        super().__init__(path)
        self.fail = fail
        self.enqueued: list[tuple[str, str]] = []
        self.cancellations: list[tuple[str, str]] = []

    def _enqueue_research_run(
        self,
        connection,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        del connection
        if self.fail:
            raise RuntimeError("outbox unavailable")
        self.enqueued.append((run_id, created_at))

    def _enqueue_research_run_cancellation(
        self,
        connection,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        del connection
        if self.fail:
            raise RuntimeError("cancellation outbox unavailable")
        self.cancellations.append((run_id, created_at))


def create_run(store: MetadataStore, key: str) -> tuple[dict[str, object], bool]:
    draft = store.create_research_draft({"title": "test"})
    _frozen, run, created = store.freeze_definition_and_create_run(
        draft_id=str(draft["id"]),
        frozen_content={"title": "test"},
        content_hash="frozen-content-hash",
        dataset_release_id="release-1",
        idempotency_key=key,
    )
    return run, created


def prepare_store(store: MetadataStore) -> None:
    store.initialize()
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO dataset_releases (id, manifest_json, created_at)
            VALUES (?, '{}', '2026-07-31T00:00:00+00:00')
            """,
            ("release-1",),
        )


def test_new_run_enqueues_once_and_idempotent_replay_consumes_no_capacity(
    tmp_path: Path,
) -> None:
    store = RecordingOutboxStore(tmp_path / "metadata.sqlite3")
    prepare_store(store)

    first, first_created = create_run(store, "same-request")
    second, second_created = create_run(store, "same-request")

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert [run_id for run_id, _created_at in store.enqueued] == [first["id"]]


def test_outbox_failure_rolls_back_frozen_definition_and_run(tmp_path: Path) -> None:
    store = RecordingOutboxStore(tmp_path / "metadata.sqlite3", fail=True)
    prepare_store(store)

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        create_run(store, "failed-request")

    assert store.list_frozen_research_definitions() == []
    assert store.list_research_runs() == []


def test_cancellation_and_its_delivery_command_commit_atomically(tmp_path: Path) -> None:
    store = RecordingOutboxStore(tmp_path / "metadata.sqlite3")
    prepare_store(store)
    run, _created = create_run(store, "cancel-request")

    cancelled = store.cancel_research_run(str(run["id"]))

    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert [run_id for run_id, _created_at in store.cancellations] == [run["id"]]


def test_cancellation_outbox_failure_rolls_back_cancellation(tmp_path: Path) -> None:
    store = RecordingOutboxStore(tmp_path / "metadata.sqlite3")
    prepare_store(store)
    run, _created = create_run(store, "cancel-failure")
    store.fail = True

    with pytest.raises(RuntimeError, match="cancellation outbox unavailable"):
        store.cancel_research_run(str(run["id"]))

    assert store.research_run(str(run["id"]))["status"] == "queued"


class FakeTemporalClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []

    async def start_workflow(self, workflow, request, **options):
        self.starts.append(
            {
                "workflow": workflow,
                "request": request,
                "options": options,
            }
        )

    def get_workflow_handle(self, workflow_id: str):
        raise AssertionError(f"unexpected workflow handle: {workflow_id}")


class FakeOutbox:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def pending(self, *, limit: int) -> list[dict[str, str]]:
        assert limit == 25
        return [
            {
                "outbox_id": "outbox-run-1",
                "workspace_id": "workspace-1",
                "resource_kind": "research_run",
                "resource_id": "run-1",
            }
        ]

    def mark_dispatched(self, outbox_id: str) -> bool:
        self.dispatched.append(outbox_id)
        return True


def test_relay_uses_stable_domain_identity_and_only_opaque_payload() -> None:
    client = FakeTemporalClient()
    outbox = FakeOutbox()

    assert asyncio.run(relay_once(client, outbox)) == 1

    assert outbox.dispatched == ["outbox-run-1"]
    assert len(client.starts) == 1
    start = client.starts[0]
    assert start["request"] == {
        "workspace_id": "workspace-1",
        "run_id": "run-1",
    }
    assert start["options"]["id"] == research_workflow_id("run-1")
    assert start["options"]["task_queue"] == RESEARCH_TASK_QUEUE


class ExistingWorkflowClient(FakeTemporalClient):
    async def start_workflow(self, workflow, request, **options):
        del workflow, request, options
        raise WorkflowAlreadyStartedError("research-run/run-1", "ResearchWorkflow")


def test_relay_acknowledges_an_already_started_workflow() -> None:
    outbox = FakeOutbox()

    assert asyncio.run(relay_once(ExistingWorkflowClient(), outbox)) == 1
    assert outbox.dispatched == ["outbox-run-1"]


class FakeWorkflowHandle:
    def __init__(self) -> None:
        self.cancel_count = 0

    async def cancel(self) -> None:
        self.cancel_count += 1


class CancellationClient(FakeTemporalClient):
    def __init__(self) -> None:
        super().__init__()
        self.handle = FakeWorkflowHandle()
        self.requested_workflow_id: str | None = None

    def get_workflow_handle(self, workflow_id: str) -> FakeWorkflowHandle:
        self.requested_workflow_id = workflow_id
        return self.handle


class CancellationOutbox(FakeOutbox):
    def pending(self, *, limit: int) -> list[dict[str, str]]:
        assert limit == 25
        return [
            {
                "outbox_id": "cancel-run-1",
                "workspace_id": "workspace-1",
                "resource_kind": "research_run_cancel",
                "resource_id": "run-1",
            }
        ]


def test_relay_delivers_durable_cancellation_to_the_stable_workflow() -> None:
    client = CancellationClient()
    outbox = CancellationOutbox()

    assert asyncio.run(relay_once(client, outbox)) == 1
    assert client.requested_workflow_id == research_workflow_id("run-1")
    assert client.handle.cancel_count == 1
    assert outbox.dispatched == ["cancel-run-1"]


def test_resource_exhaustion_is_attempted_at_most_twice(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    store = MetadataStore(settings.metadata_path)
    store.initialize()
    objects = ImmutableObjectStore(settings.object_root)
    publisher = DatasetPublisher(store, objects)
    release, _created = publisher.bootstrap("resource-fixture", "v1")
    draft = store.create_research_draft({"title": "test"})
    _frozen, run, _created = store.freeze_definition_and_create_run(
        draft_id=str(draft["id"]),
        frozen_content={"title": "test"},
        content_hash="frozen-content-hash",
        dataset_release_id=str(release["id"]),
        idempotency_key="resource-exhaustion",
    )

    def exhaust(*_args):
        raise MemoryError

    service = ResearchRunService(
        store,
        publisher,
        objects,
        calculator=exhaust,
    )

    first = service.execute(str(run["id"]))
    second = service.execute(str(run["id"]))
    repeated = service.execute(str(run["id"]))

    assert first["status"] == "queued"
    assert second["status"] == "failed"
    assert len(second["attempts"]) == 2
    assert len(repeated["attempts"]) == 2
    assert {
        attempt["diagnostic"]["reason_code"]
        for attempt in second["attempts"]
    } == {"RESOURCE_EXHAUSTED"}


def test_activity_redelivery_fences_the_abandoned_attempt(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    prepare_store(store)
    run, _created = create_run(store, "activity-redelivery")
    first_claim = store.claim_research_run(str(run["id"]))
    assert first_claim is not None

    recovered = store.prepare_research_run_redelivery(str(run["id"]))
    second_claim = store.claim_research_run(str(run["id"]))

    assert recovered["status"] == "queued"
    assert recovered["attempts"][0]["diagnostic"]["reason_code"] == (
        "ACTIVITY_REDELIVERED"
    )
    assert second_claim is not None
    assert second_claim[1]["ordinal"] == 2


def test_delivery_finalizer_preserves_an_authoritatively_committed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    store = MetadataStore(settings.metadata_path)
    prepare_store(store)
    run, _created = create_run(store, "finalizer-after-commit")
    claimed = store.claim_research_run(str(run["id"]))
    assert claimed is not None
    attempt_id = str(claimed[1]["id"])
    objects = ImmutableObjectStore(settings.object_root)
    result_bundle_id = "result-finalizer-after-commit"
    manifest = {"id": result_bundle_id}

    with pytest.raises(RuntimeError, match="delivery ended after install"):
        with objects.stage(str(run["id"]), attempt_id) as staged:
            manifest_object = staged.put_json(manifest)
            staged.put_manifest(result_bundle_id, manifest)
            with staged.publication(
                manifest_sha256=str(manifest_object["sha256"])
            ):
                raise RuntimeError("delivery ended after install")
    assert store.publish_research_run_success(
        run_id=str(run["id"]),
        attempt_id=attempt_id,
        result_bundle_id=result_bundle_id,
        result_manifest_sha256=str(manifest_object["sha256"]),
    )
    monkeypatch.setattr(
        temporal_worker,
        "settings_from_environment",
        lambda: settings,
    )
    monkeypatch.setattr(
        temporal_worker,
        "build_runtime",
        lambda _settings: SimpleNamespace(
            control_metadata=store,
            objects=objects,
        ),
    )
    monkeypatch.setattr(
        temporal_worker,
        "workspace_execution",
        lambda _workspace_id: nullcontext(),
    )

    with caplog.at_level("INFO", logger="thesistrace.hosted.temporal_worker"):
        finalized = temporal_worker.finalize_research_delivery_failure(
            {"workspace_id": "workspace-1", "run_id": str(run["id"])}
        )

    assert finalized["status"] == "succeeded"
    assert "completion was already committed" in caplog.text
    assert "ACTIVITY_DELIVERY_FAILED" not in caplog.text
    assert (
        settings.object_root / "manifests" / f"{result_bundle_id}.json"
    ).exists()
    assert not (settings.object_root / "staging" / str(run["id"])).exists()


def test_cancelled_run_rejects_a_late_success_publication(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    prepare_store(store)
    run, _created = create_run(store, "late-publication")
    claimed = store.claim_research_run(str(run["id"]))
    assert claimed is not None
    attempt = claimed[1]

    cancelled = store.cancel_research_run(str(run["id"]))
    published = store.publish_research_run_success(
        run_id=str(run["id"]),
        attempt_id=str(attempt["id"]),
        result_bundle_id="result-late",
        result_manifest_sha256="late-manifest",
    )

    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert published is False
    final = store.research_run(str(run["id"]))
    assert final is not None
    assert final["result_bundle_id"] is None
    assert final["attempts"][0]["status"] == "cancelled"


def test_hosted_result_projection_hides_storage_and_transient_artifacts() -> None:
    result = {
        "manifest": {
            "research_run_id": "run-1",
            "manifest_sha256": "secret",
            "dataset_release": {
                "id": "release-1",
                "manifest_sha256": "secret",
            },
            "objects": {"factor_summary": {"sha256": "secret"}},
        },
        "factor_evaluation": {
            "horizons": {
                "1": {
                    "alpha_checksum": "alpha",
                    "label_checksum": "label",
                    "source_checksum": "source",
                    "summary": {"ic": 0.1},
                }
            }
        },
        "strategy_backtest": {
            "alpha_checksum": "alpha",
            "metrics": {"sharpe": 1.2},
            "daily": [{"session": str(index)} for index in range(5)],
            "rebalance_aggregates": [{"session": "1"}],
            "execution_aggregates": [{"session": "1"}],
        },
        "terminal_strategy_state": {
            "positions": [{"instrument_id": str(index)} for index in range(4)]
        },
    }

    view = public_result_view(
        result,
        daily_offset=1,
        daily_limit=2,
        position_offset=2,
        position_limit=1,
    )

    assert set(view["manifest"]) == {"research_run_id", "dataset_release"}
    assert view["manifest"]["dataset_release"] == {"id": "release-1"}
    assert view["factor_evaluation"]["horizons"]["1"] == {
        "summary": {"ic": 0.1}
    }
    assert view["strategy_backtest"]["daily"] == [
        {"session": "1"},
        {"session": "2"},
    ]
    assert "rebalance_aggregates" not in view["strategy_backtest"]
    assert "execution_aggregates" not in view["strategy_backtest"]
    assert view["terminal_strategy_state"]["positions"] == [{"instrument_id": "2"}]

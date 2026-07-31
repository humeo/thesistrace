import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import get_type_hints
from uuid import uuid4

import psycopg
import pytest
from temporalio.converter import DataConverter
from temporalio.exceptions import ApplicationError

from thesistrace.activity_contract import CooperativeActivityCancellation
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted import activity_heartbeat, data_worker
from thesistrace.hosted.activity_heartbeat import ActivityHeartbeat
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.dataset_publication_workflow import (
    DATASET_PUBLICATION_TASK_QUEUE,
    DatasetPublicationWorkflow,
    ScheduledDatasetPublicationRequest,
    ScheduledDatasetPublicationWorkflow,
    dataset_publication_workflow_id,
)
from thesistrace.hosted.execution_relay import relay_once
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import apply_migrations
from thesistrace.management import (
    HOSTED_TUSHARE_SCOPE,
    SourceAuthorizationService,
)
from thesistrace.objects import ImmutableObjectStore
from thesistrace.operator import run
from thesistrace.platform_publications import (
    DatasetPublicationRequestError,
    DatasetPublicationRequestService,
    DatasetPublicationService,
)
from thesistrace.storage import MetadataStore
from thesistrace.storage_admission import StorageAdmissionError

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")


class FakeTemporalClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []

    async def start_workflow(self, workflow, argument, **options):
        self.starts.append(
            {
                "workflow": workflow,
                "argument": argument,
                "options": options,
            }
        )


class RecordingOutbox:
    def __init__(self, entries: list[dict[str, str | None]]) -> None:
        self.entries = entries
        self.marked: list[str] = []

    def pending(self, *, limit: int = 25):
        return self.entries[:limit]

    def mark_dispatched(self, outbox_id: str) -> bool:
        self.marked.append(outbox_id)
        return True


def initialized_store(tmp_path: Path) -> MetadataStore:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    return store


def request_service(store: MetadataStore) -> DatasetPublicationRequestService:
    return DatasetPublicationRequestService(
        store,
        SourceAuthorizationService(store),
    )


def test_operator_and_schedule_requests_use_durable_idempotent_platform_state(
    tmp_path: Path,
) -> None:
    store = initialized_store(tmp_path)
    requests = request_service(store)

    fixture, created = requests.request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_bootstrap",
        parameters={"fixture": "v1"},
        idempotency_key="fixture-bootstrap-1",
    )
    replay, replay_created = requests.request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_bootstrap",
        parameters={"fixture": "v1"},
        idempotency_key="fixture-bootstrap-1",
    )
    scheduled, scheduled_created = requests.request_scheduled(
        schedule_id="post-close",
        scheduled_for="2026-07-31T07:00:00+00:00",
        request_version="v1",
        kind="fixture_increment",
        parameters={"new_sessions": 1, "corrections": []},
    )

    assert created is True
    assert replay_created is False
    assert replay["id"] == fixture["id"]
    assert scheduled_created is True
    assert scheduled["trigger_kind"] == "schedule"
    assert store.dataset_publication(str(fixture["id"])) == fixture
    with store.connect() as connection:
        rows = connection.execute(
            """
            SELECT resource_kind, resource_id, status
            FROM platform_execution_outbox
            ORDER BY created_at, id
            """
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("dataset_publication", fixture["id"], "pending"),
        ("dataset_publication", scheduled["id"], "pending"),
    ]
    success_audit = store.list_management_audit_events()[-1]
    assert success_audit["action"] == "dataset_publication.request"
    assert success_audit["details"] == {
        "kind": "fixture_bootstrap",
        "request_version": "v1",
        "trigger_kind": "operator",
    }


def test_live_request_requires_policy_declaration_but_fixture_does_not(
    tmp_path: Path,
) -> None:
    store = initialized_store(tmp_path)
    requests = request_service(store)

    requests.request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_bootstrap",
        parameters={"fixture": "v1"},
        idempotency_key="fixture-open",
    )
    with pytest.raises(DatasetPublicationRequestError) as blocked:
        requests.request(
            actor="operator-1",
            request_version="v1",
            kind="live_bootstrap",
            parameters={"as_of": "2026-07-31"},
            idempotency_key="live-closed",
        )
    assert blocked.value.reason_code == "SOURCE_AUTHORIZATION_REQUIRED"
    assert store.dataset_publication_for_idempotency_key("live-closed") is None

    SourceAuthorizationService(store).record(
        actor="operator-1",
        scope=HOSTED_TUSHARE_SCOPE,
    )
    live, created = requests.request(
        actor="operator-1",
        request_version="v1",
        kind="live_bootstrap",
        parameters={"as_of": "2026-07-31"},
        idempotency_key="live-open",
    )
    assert created is True
    assert live["kind"] == "live_bootstrap"


def test_versioned_operator_cli_requests_publication_without_exposing_actor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = initialized_store(tmp_path)
    service = request_service(store)
    settings = Settings(
        metadata_path=tmp_path / "operator.sqlite3",
        object_root=tmp_path / "operator-objects",
    )

    assert run(
        [
            "dataset-publication",
            "request",
            "--actor",
            "operator-secret-name",
            "--request-version",
            "v1",
            "--kind",
            "fixture_increment",
            "--idempotency-key",
            "operator-publication",
            "--new-sessions",
            "2",
        ],
        settings=settings,
        publication_request_service=service,
    ) == 0

    output = capsys.readouterr().out
    assert '"created": true' in output
    assert '"request_version": "v1"' in output
    assert "operator-secret-name" not in output


def test_relay_dispatches_publication_on_stable_independent_workflow() -> None:
    publication_id = "publication-1"
    client = FakeTemporalClient()
    outbox = RecordingOutbox(
        [
            {
                "outbox_id": "outbox-publication-1",
                "workspace_id": None,
                "resource_kind": "dataset_publication",
                "resource_id": publication_id,
            }
        ]
    )

    assert asyncio.run(relay_once(client, outbox)) == 1

    assert outbox.marked == ["outbox-publication-1"]
    assert len(client.starts) == 1
    start = client.starts[0]
    assert start["workflow"] == DatasetPublicationWorkflow.run
    assert start["argument"] == {"publication_id": publication_id}
    assert start["options"]["id"] == dataset_publication_workflow_id(publication_id)
    assert start["options"]["task_queue"] == DATASET_PUBLICATION_TASK_QUEUE


def test_scheduled_workflow_uses_bounded_typed_temporal_input() -> None:
    request = ScheduledDatasetPublicationRequest(
        schedule_id="post-close",
        request_version="v1",
        kind="fixture_increment",
        new_sessions=1,
    )

    async def round_trip() -> object:
        payloads = await DataConverter.default.encode([request])
        request_type = get_type_hints(
            ScheduledDatasetPublicationWorkflow.run
        )["request"]
        return (await DataConverter.default.decode(payloads, [request_type]))[0]

    assert asyncio.run(round_trip()) == request


def test_fixture_workflow_atomically_publishes_release_then_tracking_trigger(
    tmp_path: Path,
) -> None:
    store = initialized_store(tmp_path)
    publication, _created = request_service(store).request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_bootstrap",
        parameters={"fixture": "v1"},
        idempotency_key="fixture-workflow",
    )
    objects = ImmutableObjectStore(tmp_path / "objects")
    service = DatasetPublicationService(store, objects)

    completed = service.execute(str(publication["id"]))
    replay = service.execute(str(publication["id"]))

    assert completed["status"] == "succeeded"
    assert replay["status"] == "succeeded"
    release = store.latest_dataset_release()
    assert release is not None
    assert completed["result_release_id"] == release["id"]
    trigger = store.tracking_release_trigger(str(release["id"]))
    assert trigger == {
        "release_id": release["id"],
        "status": "pending",
        "created_at": release["created_at"],
    }
    assert not (objects.root / "staging" / str(publication["id"])).exists()


def test_cancellation_at_commit_fence_publishes_no_release_or_candidate(
    tmp_path: Path,
) -> None:
    store = initialized_store(tmp_path)
    publication, _created = request_service(store).request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_bootstrap",
        parameters={"fixture": "v1"},
        idempotency_key="cancel-at-commit",
    )
    publication_id = str(publication["id"])
    objects = ImmutableObjectStore(tmp_path / "objects")

    completed = DatasetPublicationService(
        store,
        objects,
        cancellation_requested=lambda: True,
    ).execute(publication_id)

    assert completed["status"] == "cancelled"
    assert store.latest_dataset_release() is None
    assert not list((objects.root / "manifests").glob("*.json"))
    assert not list((objects.root / "sha256").glob("*/*"))
    assert not (objects.root / "staging" / publication_id).exists()


class CommitFailureMetadataStore(MetadataStore):
    def publish_dataset_publication_success(self, **_kwargs):
        raise RuntimeError("injected database commit failure")


def test_database_commit_failure_removes_promoted_candidate_objects(
    tmp_path: Path,
) -> None:
    store = CommitFailureMetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    publication, _created = request_service(store).request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_bootstrap",
        parameters={"fixture": "v1"},
        idempotency_key="commit-failure",
    )
    objects = ImmutableObjectStore(tmp_path / "objects")

    completed = DatasetPublicationService(store, objects).execute(
        str(publication["id"])
    )

    assert completed["status"] == "failed"
    assert store.latest_dataset_release() is None
    assert not list((objects.root / "manifests").glob("*.json"))
    assert not list((objects.root / "sha256").glob("*/*"))
    assert not (objects.root / "staging" / str(publication["id"])).exists()


def test_failed_candidate_cleanup_preserves_object_referenced_elsewhere(
    tmp_path: Path,
) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    with objects.stage(
        "publication-1",
        "attempt-1",
        cleanup_uncommitted_payloads=True,
    ) as staged:
        candidate = staged.put_json({"candidate": "shared-before-recovery"})
        staged.put_manifest("candidate-release", {"objects": [candidate]})
        with pytest.raises(RuntimeError, match="injected rollback"):
            with staged.publication(manifest_sha256="f" * 64):
                raise RuntimeError("injected rollback")

    objects.put_manifest("committed-release", {"objects": [candidate]})
    objects.recover_staged_publication(
        "publication-1",
        committed_manifest_sha256=None,
    )

    assert objects.read_json(str(candidate["sha256"])) == {
        "candidate": "shared-before-recovery"
    }
    assert not (
        objects.root / "manifests" / "candidate-release.json"
    ).exists()
    assert (objects.root / "manifests" / "committed-release.json").exists()


class FailingCandidatePublicationService(DatasetPublicationService):
    def _build_candidate(self, publication, objects):
        objects.put_json({"candidate": "must-not-survive-as-a-manifest"})
        objects.put_manifest("candidate-release", {"partial": True})
        raise RuntimeError("injected publication failure")


class ExhaustedPublicationService(DatasetPublicationService):
    def _build_candidate(self, publication, objects):
        del publication, objects
        raise MemoryError("injected exhaustion")


class DiskRejectedPublicationService(DatasetPublicationService):
    def _build_candidate(self, publication, objects):
        del publication, objects
        raise StorageAdmissionError(
            "DISK_PRESSURE",
            "persistent disk rejects all payload growth",
            dimension="disk_usage",
            limit=90,
        )


def test_failure_and_repeated_resource_exhaustion_preserve_previous_truth(
    tmp_path: Path,
) -> None:
    store = initialized_store(tmp_path)
    requests = request_service(store)
    objects = ImmutableObjectStore(tmp_path / "objects")
    root_request, _ = requests.request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_bootstrap",
        parameters={"fixture": "v1"},
        idempotency_key="root",
    )
    root = DatasetPublicationService(store, objects).execute(str(root_request["id"]))
    previous_release_id = str(root["result_release_id"])

    failed_request, _ = requests.request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_increment",
        parameters={"new_sessions": 1, "corrections": []},
        idempotency_key="failed-candidate",
    )
    failed = FailingCandidatePublicationService(store, objects).execute(
        str(failed_request["id"])
    )
    assert failed["status"] == "failed"
    assert store.latest_dataset_release()["id"] == previous_release_id

    disk_request, _ = requests.request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_increment",
        parameters={"new_sessions": 1, "corrections": []},
        idempotency_key="disk-pressure",
    )
    disk_rejected = DiskRejectedPublicationService(store, objects).execute(
        str(disk_request["id"])
    )
    assert disk_rejected["status"] == "failed"
    assert disk_rejected["diagnostic"] == {
        "reason_code": "DISK_PRESSURE",
        "message": "persistent disk rejects all payload growth",
        "correlation_id": disk_rejected["attempts"][-1]["id"],
        "dimension": "disk_usage",
        "limit": 90,
    }
    assert store.latest_dataset_release()["id"] == previous_release_id
    assert not (objects.root / "manifests" / "candidate-release.json").exists()
    assert not (objects.root / "staging" / str(failed_request["id"])).exists()

    exhausted_request, _ = requests.request(
        actor="operator-1",
        request_version="v1",
        kind="fixture_increment",
        parameters={"new_sessions": 1, "corrections": []},
        idempotency_key="resource-exhausted",
    )
    exhausted_service = ExhaustedPublicationService(store, objects)
    first = exhausted_service.execute(str(exhausted_request["id"]))
    second = exhausted_service.execute(str(exhausted_request["id"]))
    assert first["status"] == "queued"
    assert second["status"] == "failed"
    assert second["diagnostic"]["reason_code"] == "RESOURCE_EXHAUSTED"
    assert len(second["attempts"]) == 2
    assert store.latest_dataset_release()["id"] == previous_release_id


def test_only_data_worker_owns_dataset_queue_and_one_activity_slot() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = (root / "deploy" / "hosted" / "compose.yaml").read_text()
    worker = (root / "src" / "thesistrace" / "hosted" / "data_worker.py").read_text()

    assert '["thesistrace-data-worker"]' in compose
    assert compose.count('["thesistrace-data-worker"]') == 1
    assert "DATASET_PUBLICATION_TASK_QUEUE" in worker
    assert "max_concurrent_activities=1" in worker
    assert "DatasetPublicationWorkflow" not in (
        root / "src" / "thesistrace" / "hosted" / "temporal_worker.py"
    ).read_text()

    migration = (
        root
        / "deploy"
        / "hosted"
        / "migrations"
        / "0011_dataset_publication_workflows.sql"
    ).read_text()
    data_grants = migration.split(
        "CREATE OR REPLACE FUNCTION thesistrace_control.hosted_tushare_authorized"
    )[0]
    assert "platform_execution_outbox\nTO thesistrace_data" not in data_grants


def test_schedule_parameters_are_bounded_before_entering_temporal_history(
    tmp_path: Path,
) -> None:
    service = request_service(initialized_store(tmp_path))

    with pytest.raises(DatasetPublicationRequestError) as rejected:
        service.request_scheduled(
            schedule_id="post-close",
            scheduled_for="2026-07-31T07:00:00+00:00",
            request_version="v1",
            kind="fixture_increment",
            parameters={
                "new_sessions": 1,
                "corrections": [
                    {"ts_code": f"{index:06d}.SZ"}
                    for index in range(101)
                ],
            },
        )

    assert rejected.value.reason_code == "DATASET_PUBLICATION_PARAMETERS_INVALID"


@pytest.mark.parametrize(
    ("attempt", "non_retryable"),
    [(1, False), (2, True)],
)
def test_activity_bootstrap_resource_exhaustion_stops_after_two_executions(
    monkeypatch: pytest.MonkeyPatch,
    attempt: int,
    non_retryable: bool,
) -> None:
    monkeypatch.setattr(
        data_worker,
        "settings_from_environment",
        lambda: (_ for _ in ()).throw(MemoryError("injected bootstrap exhaustion")),
    )
    monkeypatch.setattr(
        data_worker.activity,
        "info",
        lambda: SimpleNamespace(attempt=attempt),
    )

    with pytest.raises(ApplicationError) as exhausted:
        data_worker.execute_dataset_publication({"publication_id": "dsp_1"})

    assert exhausted.value.type == "RESOURCE_EXHAUSTED"
    assert exhausted.value.non_retryable is non_retryable


def test_activity_heartbeat_persists_cancellation_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []
    monkeypatch.setattr(activity_heartbeat.activity, "is_cancelled", lambda: True)

    heartbeat = ActivityHeartbeat(on_cancel=lambda: recorded.append("cancelled"))
    for _index in range(2):
        with pytest.raises(CooperativeActivityCancellation):
            heartbeat.checkpoint("validated")

    assert recorded == ["cancelled"]


def test_dataset_candidate_builder_uses_staged_writer_without_committing(
    tmp_path: Path,
) -> None:
    store = initialized_store(tmp_path)
    objects = ImmutableObjectStore(tmp_path / "objects")
    publisher = DatasetPublisher(
        store,
        objects,
        release_committer=lambda release, _key: (release, True),
    )

    candidate, created = publisher.bootstrap("candidate-only", "v1")

    assert created is True
    assert store.latest_dataset_release() is None
    assert candidate["id"].startswith("dsr_")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_data_role_atomically_commits_release_and_tracking_trigger() -> None:
    assert TEST_DATABASE_URL is not None
    apply_migrations(
        TEST_DATABASE_URL,
        ROOT / "deploy" / "hosted" / "migrations",
    )
    suffix = uuid4().hex
    request_key = f"dataset-publication-{suffix}"

    def request_once():
        store = PostgresManagementStore(TEST_DATABASE_URL)
        return DatasetPublicationRequestService(
            store,
            SourceAuthorizationService(store),
        ).request(
            actor="dataset-publication-test",
            request_version="v1",
            kind="fixture_increment",
            parameters={"new_sessions": 1, "corrections": []},
            idempotency_key=request_key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: request_once(), range(2)))
    assert sorted(created for _publication, created in outcomes) == [
        False,
        True,
    ]
    assert {outcome[0]["id"] for outcome in outcomes} == {
        outcomes[0][0]["id"]
    }
    publication = outcomes[0][0]
    data = PostgresControlMetadataStore(
        TEST_DATABASE_URL,
        database_role="data",
    )
    claimed = data.claim_dataset_publication(str(publication["id"]))
    assert claimed is not None
    _current, attempt = claimed
    predecessor = data.latest_dataset_release()
    created_at = datetime.now(UTC).isoformat()
    release = {
        "id": f"dsr_postgres_{suffix}",
        "predecessor_id": (
            None if predecessor is None else predecessor["id"]
        ),
        "created_at": created_at,
        "manifest_sha256": "a" * 64,
        "objects": [],
        "schemas": [],
    }

    assert data.publish_dataset_publication_success(
        publication_id=str(publication["id"]),
        attempt_id=str(attempt["id"]),
        release=release,
        idempotency_key=str(publication["idempotency_key"]),
        storage_objects=[],
    ) is True
    assert data.latest_dataset_release()["id"] == release["id"]
    assert data.tracking_release_trigger(release["id"]) == {
        "release_id": release["id"],
        "status": "pending",
        "created_at": created_at,
    }

    race_key = f"dataset-publication-race-{suffix}"
    race_publication, _created = DatasetPublicationRequestService(
        PostgresManagementStore(TEST_DATABASE_URL),
        SourceAuthorizationService(PostgresManagementStore(TEST_DATABASE_URL)),
    ).request(
        actor="dataset-publication-test",
        request_version="v1",
        kind="fixture_increment",
        parameters={"new_sessions": 1, "corrections": []},
        idempotency_key=race_key,
    )
    race_claimed = data.claim_dataset_publication(
        str(race_publication["id"])
    )
    assert race_claimed is not None
    race_current, race_attempt = race_claimed
    race_release_id = f"dsr_postgres_race_{suffix}"
    race_release = {
        "id": race_release_id,
        "predecessor_id": release["id"],
        "created_at": datetime.now(UTC).isoformat(),
        "manifest_sha256": "b" * 64,
        "objects": [],
        "schemas": [],
    }
    barrier = Barrier(2)

    def publish_race() -> bool:
        barrier.wait()
        return PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="data",
        ).publish_dataset_publication_success(
            publication_id=str(race_publication["id"]),
            attempt_id=str(race_attempt["id"]),
            release=race_release,
            idempotency_key=str(race_current["idempotency_key"]),
            storage_objects=[],
        )

    def cancel_race() -> str:
        barrier.wait()
        cancelled = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="data",
        ).request_dataset_publication_cancellation(
            str(race_publication["id"])
        )
        return str(cancelled["status"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        published_future = executor.submit(publish_race)
        cancelled_future = executor.submit(cancel_race)
        published = published_future.result()
        cancelled_status = cancelled_future.result()
    race_final = data.dataset_publication(str(race_publication["id"]))
    assert race_final is not None
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        race_release_exists = bool(
            connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM thesistrace_product.dataset_releases
                    WHERE id = %s
                )
                """,
                (race_release_id,),
            ).fetchone()[0]
        )
    assert (race_final["status"] == "succeeded") == race_release_exists
    assert published == race_release_exists
    assert cancelled_status in {"succeeded", "cancelled"}

    scheduled_service = DatasetPublicationRequestService(
        data,
        SourceAuthorizationService(data),
    )
    scheduled, scheduled_created = scheduled_service.request_scheduled(
        schedule_id=f"post-close-{suffix}",
        scheduled_for="2026-07-31T07:00:00+00:00",
        request_version="v1",
        kind="fixture_increment",
        parameters={"new_sessions": 1, "corrections": []},
    )
    scheduled_replay, replay_created = scheduled_service.request_scheduled(
        schedule_id=f"post-close-{suffix}",
        scheduled_for="2026-07-31T07:00:00+00:00",
        request_version="v1",
        kind="fixture_increment",
        parameters={"new_sessions": 1, "corrections": []},
    )
    assert scheduled_created is True
    assert replay_created is False
    assert scheduled_replay["id"] == scheduled["id"]

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute("BEGIN")
        connection.execute("SET LOCAL ROLE thesistrace_data")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE thesistrace_product.platform_execution_outbox
                SET status = 'dispatched'
                """
            )
        connection.rollback()
        for role in ("thesistrace_api", "thesistrace_compute"):
            connection.execute("BEGIN")
            connection.execute(f"SET LOCAL ROLE {role}")
            connection.execute(
                "SET LOCAL search_path = thesistrace_product, public"
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM dataset_publications")
            connection.rollback()

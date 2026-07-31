import os
from concurrent.futures import (
    ThreadPoolExecutor,
)
from concurrent.futures import (
    TimeoutError as FutureTimeoutError,
)
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import InsForgeIdentity
from thesistrace.config import Settings
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import apply_migrations
from thesistrace.hosted.provisioning import PostgresProvisioningStore
from thesistrace.objects import ImmutableObjectStore
from thesistrace.operator import run
from thesistrace.ports import LocalWorkerDispatch
from thesistrace.quota import (
    DEFAULT_QUOTA_PROFILE,
    QuotaExceededError,
    QuotaProfileError,
    QuotaProfileService,
)
from thesistrace.runtime import RuntimePorts
from thesistrace.storage import MetadataStore
from thesistrace.tenancy import authenticated_subject
from thesistrace.working_cache import WorkingCacheStore

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")


class RecordingQuotaStore:
    def __init__(self) -> None:
        self.profiles = {
            "workspace-1": dict(DEFAULT_QUOTA_PROFILE),
        }
        self.audit_events: list[dict[str, object]] = []

    def quota_profile(self, workspace_id: str) -> dict[str, int] | None:
        profile = self.profiles.get(workspace_id)
        return None if profile is None else dict(profile)

    def update_quota_profile(
        self,
        *,
        workspace_id: str,
        overrides: dict[str, int],
        audit_event: dict[str, object],
    ) -> dict[str, int]:
        if workspace_id not in self.profiles:
            raise KeyError(workspace_id)
        self.audit_events.append(audit_event)
        self.profiles[workspace_id].update(overrides)
        return dict(self.profiles[workspace_id])

    def append_management_audit_event(self, event: dict[str, object]) -> None:
        self.audit_events.append(event)


class CoordinatedQuotaStore:
    def __init__(self, delegate: PostgresManagementStore) -> None:
        self.delegate = delegate
        self.read_barrier = Barrier(2)

    def quota_profile(self, workspace_id: str) -> dict[str, int] | None:
        profile = self.delegate.quota_profile(workspace_id)
        self.read_barrier.wait(timeout=5)
        return profile

    def update_quota_profile(
        self,
        *,
        workspace_id: str,
        overrides: dict[str, int],
        audit_event: dict[str, object],
    ) -> dict[str, int]:
        return self.delegate.update_quota_profile(
            workspace_id=workspace_id,
            overrides=overrides,
            audit_event=audit_event,
        )

    def append_management_audit_event(self, event: dict[str, object]) -> None:
        self.delegate.append_management_audit_event(event)


class BoundedComputeStore(MetadataStore):
    def __init__(self, path: Path, *, limit: int) -> None:
        super().__init__(path)
        self.limit = limit
        self.nonterminal: set[tuple[str, str]] = set()

    def _admit_user_compute(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        admitted_at: str,
    ) -> None:
        del connection, admitted_at
        if len(self.nonterminal) >= self.limit:
            raise QuotaExceededError(
                dimension="max_nonterminal_user_compute_jobs",
                limit=self.limit,
            )
        self.nonterminal.add((resource_kind, resource_id))

    def _complete_user_compute(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        completed_at: str,
    ) -> None:
        del connection, completed_at
        self.nonterminal.discard((resource_kind, resource_id))


def test_effective_profile_contains_only_three_fixed_dimensions() -> None:
    assert DEFAULT_QUOTA_PROFILE == {
        "max_active_daily_tracks": 10,
        "max_nonterminal_user_compute_jobs": 8,
        "max_private_storage_bytes": 10 * 1024**3,
    }

    store = RecordingQuotaStore()
    profile = QuotaProfileService(store).inspect("workspace-1")

    assert profile == DEFAULT_QUOTA_PROFILE
    assert set(profile) == {
        "max_active_daily_tracks",
        "max_nonterminal_user_compute_jobs",
        "max_private_storage_bytes",
    }


def test_operator_override_is_partial_audited_and_active_limit_only_lowers() -> None:
    store = RecordingQuotaStore()
    service = QuotaProfileService(store)

    updated = service.override(
        actor=" operator-1 ",
        workspace_id="workspace-1",
        max_active_daily_tracks=4,
        max_private_storage_bytes=20 * 1024**3,
    )

    assert updated == {
        "max_active_daily_tracks": 4,
        "max_nonterminal_user_compute_jobs": 8,
        "max_private_storage_bytes": 20 * 1024**3,
    }
    assert store.audit_events[-1]["action"] == "quota_profile.override"
    assert store.audit_events[-1]["outcome"] == "succeeded"
    assert store.audit_events[-1]["details"] == {
        "dimensions": [
            "max_active_daily_tracks",
            "max_private_storage_bytes",
        ],
        "overrides": {
            "max_active_daily_tracks": 4,
            "max_private_storage_bytes": 20 * 1024**3,
        },
    }

    with pytest.raises(QuotaProfileError) as rejected:
        service.override(
            actor="operator-1",
            workspace_id="workspace-1",
            max_active_daily_tracks=11,
        )

    assert rejected.value.reason_code == "QUOTA_OVERRIDE_EXCEEDS_HARD_MAXIMUM"
    assert store.audit_events[-1]["outcome"] == "rejected"
    assert store.audit_events[-1]["reason_code"] == (
        "QUOTA_OVERRIDE_EXCEEDS_HARD_MAXIMUM"
    )


def test_nonterminal_compute_admission_is_atomic_with_run_and_idempotency(
    tmp_path: Path,
) -> None:
    store = BoundedComputeStore(tmp_path / "metadata.sqlite3", limit=2)
    store.initialize()
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO dataset_releases (id, manifest_json, created_at)
            VALUES ('release-1', '{}', '2026-07-31T00:00:00+00:00')
            """
        )
    drafts = [
        store.create_research_draft({"title": f"draft-{index}"})
        for index in range(4)
    ]

    first = create_run(store, str(drafts[0]["id"]), "request-1")
    second = create_run(store, str(drafts[1]["id"]), "request-2")
    replay = create_run(store, str(drafts[0]["id"]), "request-1")

    assert first[2] is True
    assert second[2] is True
    assert replay[2] is False
    assert replay[1]["id"] == first[1]["id"]
    assert len(store.nonterminal) == 2

    with pytest.raises(QuotaExceededError) as rejected:
        create_run(store, str(drafts[2]["id"]), "request-3")

    assert rejected.value.dimension == "max_nonterminal_user_compute_jobs"
    assert len(store.list_research_runs()) == 2

    cancelled = store.cancel_research_run(str(first[1]["id"]))
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    admitted = create_run(store, str(drafts[3]["id"]), "request-4")
    assert admitted[2] is True
    assert len(store.nonterminal) == 2


def test_operator_cli_inspects_and_records_sanitized_partial_override(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = RecordingQuotaStore()
    service = QuotaProfileService(store)
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )

    assert run(
        ["quota", "inspect", "--workspace-id", "workspace-1"],
        settings=settings,
        quota_service=service,
    ) == 0
    assert '"max_active_daily_tracks": 10' in capsys.readouterr().out

    assert run(
        [
            "quota",
            "override",
            "--actor",
            "operator-1",
            "--workspace-id",
            "workspace-1",
            "--max-nonterminal-user-compute-jobs",
            "6",
        ],
        settings=settings,
        quota_service=service,
    ) == 0
    output = capsys.readouterr().out
    assert '"max_nonterminal_user_compute_jobs": 6' in output
    assert "operator-1" not in output
    assert store.audit_events[-1]["details"] == {
        "dimensions": ["max_nonterminal_user_compute_jobs"],
        "overrides": {"max_nonterminal_user_compute_jobs": 6},
    }


def test_api_quota_rejection_is_not_rate_limiting_and_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    store = BoundedComputeStore(settings.metadata_path, limit=1)
    store.initialize()
    runtime = RuntimePorts(
        control_metadata=store,
        objects=ImmutableObjectStore(settings.object_root),
        working_cache=WorkingCacheStore(settings.working_cache_root),
        execution_dispatch=LocalWorkerDispatch(),
    )

    with TestClient(create_app(settings, runtime_ports=runtime)) as client:
        assert client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "quota-release"},
            json={"fixture": "v1"},
        ).status_code == 201
        first_draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        second_draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        first = client.post(
            f"/api/v1/research-definitions/{first_draft['id']}/runs",
            headers={"Idempotency-Key": "quota-first"},
        )
        replay = client.post(
            f"/api/v1/research-definitions/{first_draft['id']}/runs",
            headers={"Idempotency-Key": "quota-first"},
        )
        rejected = client.post(
            f"/api/v1/research-definitions/{second_draft['id']}/runs",
            headers={"Idempotency-Key": "quota-second"},
        )
        rejected_rerun = client.post(
            f"/api/v1/research-runs/{first.json()['run']['id']}/rerun",
            headers={"Idempotency-Key": "quota-rerun"},
        )

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["run"]["id"] == first.json()["run"]["id"]
    assert rejected.status_code == 409
    assert rejected.status_code != 429
    assert rejected.json()["detail"] == {
        "reason_code": "QUOTA_EXCEEDED",
        "message": "Personal Workspace Compute quota is full",
        "dimension": "max_nonterminal_user_compute_jobs",
        "limit": 1,
    }
    assert rejected_rerun.status_code == 409


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_default_profile_serializes_eight_compute_admissions() -> None:
    assert TEST_DATABASE_URL is not None
    apply_migrations(
        TEST_DATABASE_URL,
        ROOT / "deploy" / "hosted" / "migrations",
    )
    suffix = uuid4().hex
    identity = InsForgeIdentity(
        subject=f"quota-subject-{suffix}",
        email=f"quota-{suffix}@example.com",
    )
    now = datetime.now(UTC)
    provisioning = PostgresProvisioningStore(TEST_DATABASE_URL)
    provisioning.issue_invitation(
        actor="quota-test",
        normalized_email=identity.email,
        expires_at=now + timedelta(hours=1),
        now=now,
    )
    workspace_id = provisioning.provision(
        identity=identity,
        normalized_email=identity.email,
        now=now,
    ).identity.workspace_id
    release_id = f"quota-release-{suffix}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO thesistrace_product.dataset_releases (
                id,
                manifest_json,
                created_at
            )
            VALUES (%s, '{}', %s)
            """,
            (release_id, now.isoformat()),
        )
    quota_service = QuotaProfileService(
        PostgresManagementStore(TEST_DATABASE_URL)
    )
    assert quota_service.inspect(workspace_id) == DEFAULT_QUOTA_PROFILE
    assert quota_service.override(
        actor="quota-operator",
        workspace_id=workspace_id,
        max_active_daily_tracks=5,
    )["max_active_daily_tracks"] == 5
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        audit = connection.execute(
            """
            SELECT action, outcome, subject_id, details_json
            FROM thesistrace_control.management_audit_events
            WHERE subject_type = 'quota_profile'
              AND subject_id = %s
            ORDER BY occurred_at DESC, id DESC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
    assert audit == (
        "quota_profile.override",
        "succeeded",
        workspace_id,
        {
            "dimensions": ["max_active_daily_tracks"],
            "overrides": {"max_active_daily_tracks": 5},
        },
    )

    coordinated = QuotaProfileService(
        CoordinatedQuotaStore(PostgresManagementStore(TEST_DATABASE_URL))
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_updates = [
            executor.submit(
                coordinated.override,
                actor="quota-operator-a",
                workspace_id=workspace_id,
                max_active_daily_tracks=4,
            ),
            executor.submit(
                coordinated.override,
                actor="quota-operator-b",
                workspace_id=workspace_id,
                max_private_storage_bytes=20 * 1024**3,
            ),
        ]
        assert all(update.result() for update in concurrent_updates)
    assert quota_service.inspect(workspace_id) == {
        "max_active_daily_tracks": 4,
        "max_nonterminal_user_compute_jobs": 8,
        "max_private_storage_bytes": 20 * 1024**3,
    }

    override_started = Event()

    def lower_active_track_limit() -> dict[str, int]:
        override_started.set()
        return quota_service.override(
            actor="quota-operator-c",
            workspace_id=workspace_id,
            max_active_daily_tracks=3,
        )

    with authenticated_subject(identity.subject):
        store = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="api",
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            with store.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                store.lock_daily_track_activation(connection)
                update = executor.submit(lower_active_track_limit)
                assert override_started.wait(timeout=5)
                with pytest.raises(FutureTimeoutError):
                    update.result(timeout=0.2)
            assert update.result(timeout=5)["max_active_daily_tracks"] == 3
        drafts = [
            store.create_research_draft({"title": f"quota-{index}"})
            for index in range(9)
        ]

    def admit(index: int):
        with authenticated_subject(identity.subject):
            store = PostgresControlMetadataStore(
                TEST_DATABASE_URL,
                database_role="api",
            )
            try:
                return store.freeze_definition_and_create_run(
                    draft_id=str(drafts[index]["id"]),
                    frozen_content={"title": f"quota-{index}"},
                    content_hash=f"quota-hash-{index}",
                    dataset_release_id=release_id,
                    idempotency_key=f"quota-request-{suffix}-{index}",
                )
            except QuotaExceededError as error:
                return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        duplicate_outcomes = list(executor.map(lambda _index: admit(0), range(2)))
    assert all(isinstance(outcome, tuple) for outcome in duplicate_outcomes)
    assert sorted(outcome[2] for outcome in duplicate_outcomes) == [False, True]
    assert {
        outcome[1]["id"] for outcome in duplicate_outcomes
    } == {duplicate_outcomes[0][1]["id"]}

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(admit, range(1, 9)))

    admitted = [outcome for outcome in outcomes if isinstance(outcome, tuple)]
    rejected = [
        outcome for outcome in outcomes if isinstance(outcome, QuotaExceededError)
    ]
    assert len(admitted) == 7
    assert len(rejected) == 1
    assert rejected[0].dimension == "max_nonterminal_user_compute_jobs"

    with authenticated_subject(identity.subject):
        store = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="api",
        )
        cancelled = store.cancel_research_run(
            str(duplicate_outcomes[0][1]["id"])
        )
        assert cancelled is not None
        assert cancelled["status"] == "cancelled"
        tenth_draft = store.create_research_draft({"title": "quota-tenth"})
        _frozen, tenth, created = store.freeze_definition_and_create_run(
            draft_id=str(tenth_draft["id"]),
            frozen_content={"title": "quota-tenth"},
            content_hash="quota-hash-tenth",
            dataset_release_id=release_id,
            idempotency_key=f"quota-request-{suffix}-tenth",
        )
        assert created is True
        assert tenth["status"] == "queued"
        with store.connect() as connection:
            assert connection.execute(
                """
                SELECT count(*)
                FROM user_compute_admissions
                WHERE completed_at IS NULL
                """
            ).fetchone()[0] == 8


def create_run(
    store: MetadataStore,
    draft_id: str,
    idempotency_key: str,
) -> tuple[dict[str, object], dict[str, object], bool]:
    return store.freeze_definition_and_create_run(
        draft_id=draft_id,
        frozen_content={"title": "frozen"},
        content_hash=f"hash-{draft_id}",
        dataset_release_id="release-1",
        idempotency_key=idempotency_key,
    )


def definition() -> dict[str, object]:
    return {
        "title": "Quota acceptance",
        "hypothesis": "Quota admission is independent from validation.",
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

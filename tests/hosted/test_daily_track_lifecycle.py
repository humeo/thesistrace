import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Lock
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import InsForgeIdentity
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import apply_migrations
from thesistrace.hosted.provisioning import PostgresProvisioningStore
from thesistrace.objects import ImmutableObjectStore
from thesistrace.ports import LocalWorkerDispatch
from thesistrace.quota import QuotaExceededError, QuotaProfileService
from thesistrace.research_runs import ResearchRunService
from thesistrace.runtime import RuntimePorts
from thesistrace.storage import MetadataStore
from thesistrace.tenancy import authenticated_subject, workspace_execution
from thesistrace.tracking import DailyTrackingService
from thesistrace.working_cache import WorkingCacheStore

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")


class OneTrackMetadataStore(MetadataStore):
    def active_daily_track_limit(self, connection) -> int:
        del connection
        return 1


class CommitAckLossConnection:
    def __init__(
        self,
        connection,
        store: "CommitAckLossMetadataStore",
    ) -> None:
        self.connection = connection
        self.store = store

    def __getattr__(self, name: str):
        return getattr(self.connection, name)

    def commit(self) -> None:
        self.connection.commit()
        if self.store.fail_next_commit_ack:
            self.store.fail_next_commit_ack = False
            raise RuntimeError("commit acknowledgement was lost")


class CommitAckLossMetadataStore(MetadataStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.fail_next_commit_ack = False

    @contextmanager
    def connect(self):
        with super().connect() as connection:
            yield CommitAckLossConnection(connection, self)


class CoordinatedReservationSnapshotStore(MetadataStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.snapshot_read = Event()
        self.snapshot_can_return = Event()

    def daily_track_activation_reservation_ids(self) -> list[str]:
        reservation_ids = (
            super().daily_track_activation_reservation_ids()
        )
        self.snapshot_read.set()
        assert self.snapshot_can_return.wait(timeout=10)
        return reservation_ids


class HeaderIdentityVerifier:
    def __init__(self, identities: dict[str, InsForgeIdentity]) -> None:
        self.identities = identities

    def verify(self, authorization: str | None) -> InsForgeIdentity:
        if authorization not in self.identities:
            raise AssertionError("test supplied an unknown token")
        return self.identities[authorization]


class CoordinatedTrackStore(PostgresControlMetadataStore):
    def __init__(
        self,
        database_url: str,
        barriers: tuple[Barrier, Barrier],
    ) -> None:
        super().__init__(database_url, database_role="api")
        self.barriers = barriers
        self.activation_lock_calls = 0

    def lock_daily_track_activation(
        self,
        connection,
    ) -> None:
        self.activation_lock_calls += 1
        if self.activation_lock_calls <= len(self.barriers):
            self.barriers[self.activation_lock_calls - 1].wait(
                timeout=30
            )
        super().lock_daily_track_activation(connection)


def definition() -> dict[str, object]:
    return {
        "title": "Hosted DailyTrack",
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


def test_activation_uses_effective_quota_and_stop_fences_all_later_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    metadata = OneTrackMetadataStore(settings.metadata_path)
    metadata.initialize()
    objects = ImmutableObjectStore(settings.object_root)
    cache = WorkingCacheStore(settings.working_cache_root)
    runtime = RuntimePorts(
        control_metadata=metadata,
        objects=objects,
        working_cache=cache,
        execution_dispatch=LocalWorkerDispatch(),
    )
    with TestClient(create_app(settings, runtime_ports=runtime)) as client:
        release = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "track-release"},
            json={"fixture": "v1"},
        ).json()["release"]
        draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        run = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "track-run"},
        ).json()["run"]
        queued = client.post(
            f"/api/v1/research-runs/{run['id']}/daily-tracks",
            headers={"Idempotency-Key": "queued-track"},
        )
        assert queued.status_code == 409
        completed = ResearchRunService(
            metadata,
            DatasetPublisher(metadata, objects),
            objects,
        ).execute(str(run["id"]))
        assert completed["status"] == "succeeded"

        activated = client.post(
            f"/api/v1/research-runs/{run['id']}/daily-tracks",
            headers={"Idempotency-Key": "track-first"},
        )
        replay = client.post(
            f"/api/v1/research-runs/{run['id']}/daily-tracks",
            headers={"Idempotency-Key": "track-first"},
        )
        immutable_paths_before_rejection = {
            path.relative_to(objects.root)
            for directory in ("sha256", "manifests")
            for path in (objects.root / directory).rglob("*")
            if path.is_file()
        }

        def fail_cache_calculation(*_args, **_kwargs) -> None:
            raise AssertionError(
                "quota preflight must precede cache calculation"
            )

        with monkeypatch.context() as patch:
            patch.setattr(
                DailyTrackingService,
                "_commit_activation_cache",
                fail_cache_calculation,
            )
            rejected = client.post(
                f"/api/v1/research-runs/{run['id']}/daily-tracks",
                headers={"Idempotency-Key": "track-over-limit"},
            )
        immutable_paths_after_rejection = {
            path.relative_to(objects.root)
            for directory in ("sha256", "manifests")
            for path in (objects.root / directory).rglob("*")
            if path.is_file()
        }

        assert activated.status_code == 201
        track = activated.json()
        assert replay.status_code == 200
        assert replay.json()["id"] == track["id"]
        assert rejected.status_code == 409
        assert rejected.json()["detail"] == {
            "reason_code": "QUOTA_EXCEEDED",
            "message": "Personal Workspace DailyTrack quota is full",
            "dimension": "max_active_daily_tracks",
            "limit": 1,
        }
        assert (
            immutable_paths_after_rejection
            == immutable_paths_before_rejection
        )
        assert track["seed_run_id"] == run["id"]
        assert track["definition_version_id"] == run["definition_version_id"]
        assert track["activation_release_id"] == release["id"]
        assert (
            track["numeric_execution_contract"]
            == "thesistrace-numeric-v1"
        )
        assert track["head"]["predecessor_checkpoint_id"] is None
        raw_track = DailyTrackingService(
            metadata,
            DatasetPublisher(metadata, objects),
            objects,
            cache,
        ).get_track(str(track["id"]))
        assert raw_track is not None
        checkpoint = objects.read_json(
            str(raw_track["head"]["manifest_sha256"])
        )
        assert checkpoint["tracking_origin"]["activation_session"]
        assert (
            checkpoint["numeric_execution_contract"]
            == "thesistrace-numeric-v1"
        )
        assert "terminal_strategy_state" in checkpoint["objects"]

        publisher = DatasetPublisher(metadata, objects)
        target_releases = [
            publisher.publish_fixture_increment(
                f"stop-target-{status}",
                new_sessions=1,
                corrections=[],
            )[0]
            for status in ("pending", "running")
        ]
        generation_id = str(track["current_generation_id"])
        now = datetime.now(UTC).isoformat()
        with metadata.connect() as connection:
            for status, target_release in zip(
                ("pending", "running"),
                target_releases,
                strict=True,
            ):
                advance_id = f"advance-{status}"
                connection.execute(
                    """
                    INSERT INTO tracking_advances (
                        id,
                        daily_track_id,
                        generation_id,
                        target_dataset_release_id,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        advance_id,
                        track["id"],
                        generation_id,
                            target_release["id"],
                        status,
                        now,
                        now,
                    ),
                )
                if status == "running":
                    connection.execute(
                        """
                        INSERT INTO tracking_advance_attempts (
                            id,
                            advance_id,
                            ordinal,
                            status,
                            started_at
                        )
                        VALUES (?, ?, 1, 'running', ?)
                        """,
                        (f"attempt-{status}", advance_id, now),
                    )

        stopped = client.post(
            f"/api/v1/daily-tracks/{track['id']}/stop"
        )
        stopped_replay = client.post(
            f"/api/v1/daily-tracks/{track['id']}/stop"
        )
        admitted_after_stop = client.post(
            f"/api/v1/research-runs/{run['id']}/daily-tracks",
            headers={"Idempotency-Key": "track-after-stop"},
        )

    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["cache_cleanup_status"] == "completed"
    assert stopped_replay.status_code == 200
    assert stopped_replay.json()["head_checkpoint_id"] == (
        stopped.json()["head_checkpoint_id"]
    )
    assert admitted_after_stop.status_code == 201
    with metadata.connect() as connection:
        advances = connection.execute(
            """
            SELECT status
            FROM tracking_advances
            WHERE daily_track_id = ?
              AND id IN ('advance-pending', 'advance-running')
            ORDER BY id
            """,
            (track["id"],),
        ).fetchall()
        attempts = connection.execute(
            """
            SELECT status
            FROM tracking_advance_attempts
            WHERE id = 'attempt-running'
            ORDER BY id
            """
        ).fetchall()
    assert [row["status"] for row in advances] == ["blocked", "blocked"]
    assert [row["status"] for row in attempts] == ["cancelled"]
    assert track["id"] not in cache.list_track_ids()
    assert admitted_after_stop.json()["id"] in cache.list_track_ids()


def test_startup_reconciles_an_uncommitted_activation_publication(
    tmp_path: Path,
) -> None:
    metadata = MetadataStore(tmp_path / "metadata.sqlite3")
    metadata.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    service = DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        WorkingCacheStore(tmp_path / "working-cache"),
    )
    track_id = "track_orphaned_activation"
    checkpoint_id = "checkpoint_orphaned_activation"
    seed_run_id = "run_orphaned_activation"
    checkpoint = {
        "id": checkpoint_id,
        "kind": "activation",
        "daily_track_id": track_id,
    }

    with metadata.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (id, status, created_at)
            VALUES (?, 'succeeded', ?)
            """,
            (seed_run_id, datetime.now(UTC).isoformat()),
        )
        connection.execute(
            """
            INSERT INTO daily_track_activation_reservations
                (track_id, idempotency_key, seed_run_id, created_at)
            VALUES (?, 'orphaned-activation', ?, ?)
            """,
            (
                track_id,
                seed_run_id,
                datetime.now(UTC).isoformat(),
            ),
        )

    with pytest.raises(RuntimeError, match="crash before metadata commit"):
        with objects.stage(
            track_id,
            "activation-attempt",
            cleanup_uncommitted_payloads=True,
        ) as staged:
            checkpoint_object = staged.put_json(checkpoint)
            staged.put_manifest(checkpoint_id, checkpoint)
            with staged.publication(
                manifest_sha256=str(checkpoint_object["sha256"])
            ):
                raise RuntimeError("crash before metadata commit")

    assert objects.path_for(str(checkpoint_object["sha256"])).exists()
    assert (
        objects.root / "manifests" / f"{checkpoint_id}.json"
    ).exists()
    assert objects.staged_publication_ids(prefix="track_") == [track_id]
    assert metadata.daily_track_activation_reservation_ids() == [track_id]

    assert service.reconcile_activation_staging() == [track_id]
    assert not objects.path_for(str(checkpoint_object["sha256"])).exists()
    assert not (
        objects.root / "manifests" / f"{checkpoint_id}.json"
    ).exists()
    assert objects.staged_publication_ids(prefix="track_") == []
    assert metadata.daily_track_activation_reservation_ids() == []


def test_reconciliation_preserves_a_live_activation_reservation(
    tmp_path: Path,
) -> None:
    metadata = MetadataStore(tmp_path / "metadata.sqlite3")
    metadata.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    service = DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        WorkingCacheStore(tmp_path / "working-cache"),
    )
    track_id = "track_live_activation"
    seed_run_id = "run_live_activation"
    with metadata.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (id, status, created_at)
            VALUES (?, 'succeeded', ?)
            """,
            (seed_run_id, datetime.now(UTC).isoformat()),
        )
        connection.execute(
            """
            INSERT INTO daily_track_activation_reservations
                (track_id, idempotency_key, seed_run_id, created_at)
            VALUES (?, 'live-activation', ?, ?)
            """,
            (
                track_id,
                seed_run_id,
                datetime.now(UTC).isoformat(),
            ),
        )

    with objects.stage(
        track_id,
        "activation-attempt",
        cleanup_uncommitted_payloads=True,
    ):
        assert service.reconcile_activation_staging() == []
        assert metadata.daily_track_activation_reservation_ids() == [
            track_id
        ]


def test_reconciliation_does_not_delete_a_reservation_created_after_snapshot(
    tmp_path: Path,
) -> None:
    metadata = CoordinatedReservationSnapshotStore(
        tmp_path / "metadata.sqlite3"
    )
    metadata.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    service = DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        WorkingCacheStore(tmp_path / "working-cache"),
    )
    track_id = "track_after_reservation_snapshot"
    seed_run_id = "run_after_reservation_snapshot"
    with metadata.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (id, status, created_at)
            VALUES (?, 'succeeded', ?)
            """,
            (seed_run_id, datetime.now(UTC).isoformat()),
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        reconciliation = executor.submit(
            service.reconcile_activation_staging
        )
        assert metadata.snapshot_read.wait(timeout=10)
        with objects.stage(
            track_id,
            "activation-attempt",
            cleanup_uncommitted_payloads=True,
        ):
            with metadata.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO daily_track_activation_reservations
                        (track_id, idempotency_key, seed_run_id, created_at)
                    VALUES (?, 'after-snapshot', ?, ?)
                    """,
                    (
                        track_id,
                        seed_run_id,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            metadata.snapshot_can_return.set()
            assert reconciliation.result(timeout=10) == []
            assert (
                MetadataStore(
                    metadata.path
                ).daily_track_activation_reservation_ids()
                == [track_id]
            )


def test_activation_recovers_when_commit_succeeds_but_ack_is_lost(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    metadata = CommitAckLossMetadataStore(settings.metadata_path)
    metadata.initialize()
    objects = ImmutableObjectStore(settings.object_root)
    cache = WorkingCacheStore(settings.working_cache_root)
    runtime = RuntimePorts(
        control_metadata=metadata,
        objects=objects,
        working_cache=cache,
        execution_dispatch=LocalWorkerDispatch(),
    )
    with TestClient(create_app(settings, runtime_ports=runtime)) as client:
        client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "ack-loss-release"},
            json={"fixture": "v1"},
        )
        draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        run = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "ack-loss-run"},
        ).json()["run"]
    completed = ResearchRunService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
    ).execute(str(run["id"]))
    assert completed["status"] == "succeeded"

    metadata.fail_next_commit_ack = True
    track, created = DailyTrackingService(
        metadata,
        DatasetPublisher(metadata, objects),
        objects,
        cache,
    ).activate(str(run["id"]), "ack-loss-track")

    assert created is True
    assert track["status"] == "active"
    assert cache.list_track_ids() == [track["id"]]
    assert objects.path_for(
        str(track["head"]["manifest_sha256"])
    ).exists()
    assert objects.staged_publication_ids(prefix="track_") == []


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_daily_track_quota_is_workspace_scoped_and_seed_is_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert TEST_DATABASE_URL is not None
    apply_migrations(
        TEST_DATABASE_URL,
        ROOT / "deploy" / "hosted" / "migrations",
    )
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(
            "TRUNCATE TABLE thesistrace_product.dataset_releases CASCADE"
        )
    suffix = uuid4().hex
    identities = [
        InsForgeIdentity(
            subject=f"track-subject-{index}-{suffix}",
            email=f"track-{index}-{suffix}@example.com",
        )
        for index in range(2)
    ]
    provisioning = PostgresProvisioningStore(TEST_DATABASE_URL)
    workspaces: list[str] = []
    for identity in identities:
        now = datetime.now(UTC)
        provisioning.issue_invitation(
            actor="daily-track-test",
            normalized_email=identity.email,
            expires_at=now + timedelta(hours=1),
            now=now,
        )
        workspaces.append(
            provisioning.provision(
                identity=identity,
                normalized_email=identity.email,
                now=now,
            ).identity.workspace_id
        )
    QuotaProfileService(
        PostgresManagementStore(TEST_DATABASE_URL)
    ).override(
        actor="daily-track-test",
        workspace_id=workspaces[0],
        max_active_daily_tracks=1,
    )

    objects = ImmutableObjectStore(tmp_path / "objects")
    cache = WorkingCacheStore(tmp_path / "working-cache")
    release = DatasetPublisher(
        PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="data",
        ),
        objects,
    ).bootstrap(f"daily-track-release-{suffix}", "v1")[0]
    settings = Settings(
        metadata_path=tmp_path / "unused.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
        runtime_mode="hosted",
        database_url=TEST_DATABASE_URL,
        database_role="api",
        auth_mode="insforge",
    )
    api_store = PostgresControlMetadataStore(
        TEST_DATABASE_URL,
        database_role="api",
    )
    runtime = RuntimePorts(
        control_metadata=api_store,
        objects=objects,
        working_cache=cache,
        execution_dispatch=LocalWorkerDispatch(),
    )
    client = TestClient(
        create_app(
            settings,
            runtime_ports=runtime,
            identity_verifier=HeaderIdentityVerifier(
                {
                    "Bearer track-a": identities[0],
                    "Bearer track-b": identities[1],
                }
            ),
        )
    )
    headers_a = {"Authorization": "Bearer track-a"}
    headers_b = {"Authorization": "Bearer track-b"}
    with client:
        draft = client.post(
            "/api/v1/research-definitions",
            headers=headers_a,
            json=definition(),
        ).json()
        requested = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={
                **headers_a,
                "Idempotency-Key": f"track-run-{suffix}",
            },
        ).json()["run"]
    with workspace_execution(workspaces[0]):
        compute = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="compute",
        )
        completed = ResearchRunService(
            compute,
            DatasetPublisher(compute, objects),
            objects,
        ).execute(str(requested["id"]))
    assert completed["status"] == "succeeded"
    assert completed["dataset_release_id"] == release["id"]

    activation_barriers = (Barrier(2), Barrier(2))
    calculation_lock = Lock()
    calculation_count = 0
    original_cache_calculation = (
        DailyTrackingService._commit_activation_cache
    )

    def count_cache_calculation(self, *args, **kwargs):
        nonlocal calculation_count
        with calculation_lock:
            calculation_count += 1
        return original_cache_calculation(self, *args, **kwargs)

    monkeypatch.setattr(
        DailyTrackingService,
        "_commit_activation_cache",
        count_cache_calculation,
    )

    def activate(key: str):
        with authenticated_subject(identities[0].subject):
            store = CoordinatedTrackStore(
                TEST_DATABASE_URL,
                activation_barriers,
            )
            try:
                return DailyTrackingService(
                    store,
                    DatasetPublisher(store, objects),
                    objects,
                    cache,
                ).activate(str(requested["id"]), key)
            except QuotaExceededError as error:
                return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                activate,
                (f"track-a-{suffix}", f"track-b-{suffix}"),
            )
        )
    admitted = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, tuple)
    ]
    rejected = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, QuotaExceededError)
    ]
    assert len(admitted) == 1
    assert len(rejected) == 1
    assert rejected[0].dimension == "max_active_daily_tracks"
    assert rejected[0].limit == 1
    assert calculation_count == 1
    track = admitted[0][0]
    admitted_key = (
        f"track-a-{suffix}"
        if outcomes[0] is admitted[0]
        else f"track-b-{suffix}"
    )
    recovery_store = PostgresControlMetadataStore(
        TEST_DATABASE_URL,
        database_role="api",
    )
    assert recovery_store.daily_track_head_manifest_sha256(
        str(track["id"])
    ) == str(track["head"]["manifest_sha256"])
    assert (
        recovery_store.daily_track_head_manifest_sha256(
            f"missing-track-{suffix}"
        )
        is None
    )
    DailyTrackingService(
        recovery_store,
        DatasetPublisher(recovery_store, objects),
        objects,
        cache,
    ).reconcile_cache_deletions()
    assert str(track["id"]) in cache.list_track_ids()

    with client:
        replay = client.post(
            f"/api/v1/research-runs/{requested['id']}/daily-tracks",
            headers={**headers_a, "Idempotency-Key": admitted_key},
        )
        hidden_activation = client.post(
            f"/api/v1/research-runs/{requested['id']}/daily-tracks",
            headers={
                **headers_b,
                "Idempotency-Key": f"hidden-{suffix}",
            },
        )
        hidden_inspect = client.get(
            f"/api/v1/daily-tracks/{track['id']}",
            headers=headers_b,
        )
        hidden_stop = client.post(
            f"/api/v1/daily-tracks/{track['id']}/stop",
            headers=headers_b,
        )

    assert replay.status_code == 200
    assert replay.json()["id"] == track["id"]
    assert hidden_activation.status_code == 409
    assert hidden_activation.json()["detail"]["reason_code"] == (
        "DAILY_TRACK_CONFLICT"
    )
    assert hidden_inspect.status_code == 404
    assert hidden_stop.status_code == 404

    with authenticated_subject(identities[0].subject):
        store = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="api",
        )
        retention_run_id = f"retention-run-{suffix}"
        retention_track_id = f"retention-track-{suffix}"
        with pytest.raises(
            psycopg.errors.ForeignKeyViolation
        ) as retention_error:
            with store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        id,
                        definition_version_id,
                        dataset_release_id,
                        status,
                        created_at,
                        updated_at
                    )
                    SELECT ?, definition_version_id,
                           dataset_release_id, 'succeeded',
                           created_at, updated_at
                    FROM research_runs
                    WHERE id = ?
                    """,
                    (retention_run_id, requested["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO daily_tracks (
                        id,
                        seed_run_id,
                        definition_version_id,
                        definition_content_hash,
                        activation_release_id,
                        origin_session,
                        numeric_execution_contract,
                        status,
                        current_generation_id,
                        head_checkpoint_id,
                        created_at,
                        fencing_token
                    )
                    SELECT ?, ?, definition_version_id,
                           definition_content_hash,
                           activation_release_id,
                           origin_session,
                           numeric_execution_contract,
                           'stopped', ?, ?, created_at, 1
                    FROM daily_tracks
                    WHERE id = ?
                    """,
                    (
                        retention_track_id,
                        retention_run_id,
                        f"retention-generation-{suffix}",
                        f"retention-checkpoint-{suffix}",
                        track["id"],
                    ),
                )
                connection.execute(
                    "DELETE FROM research_runs WHERE id = ?",
                    (retention_run_id,),
                )
        assert retention_error.value.diag.constraint_name == (
            "daily_tracks_workspace_id_seed_run_id_fkey"
        )
        with store.connect() as connection:
            assert store.active_daily_track_limit(connection) == 1

    original_cache_delete = cache.delete_if_not_newer

    def fail_cache_delete(_track_id: str, _token: int) -> None:
        raise OSError("cache volume unavailable after stop commit")

    monkeypatch.setattr(
        cache,
        "delete_if_not_newer",
        fail_cache_delete,
    )
    with client:
        stopped = client.post(
            f"/api/v1/daily-tracks/{track['id']}/stop",
            headers=headers_a,
        )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["cache_cleanup_status"] == "pending"

    monkeypatch.setattr(
        cache,
        "delete_if_not_newer",
        original_cache_delete,
    )
    recovery = DailyTrackingService(
        recovery_store,
        DatasetPublisher(recovery_store, objects),
        objects,
        cache,
    )
    assert recovery.reconcile_cache_deletions() == [
        {
            "daily_track_id": track["id"],
            "status": "completed",
        }
    ]
    assert str(track["id"]) not in cache.list_track_ids()

    with client:
        recovered_track = client.get(
            f"/api/v1/daily-tracks/{track['id']}",
            headers=headers_a,
        )
        replacement = client.post(
            f"/api/v1/research-runs/{requested['id']}/daily-tracks",
            headers={
                **headers_a,
                "Idempotency-Key": f"replacement-{suffix}",
            },
        )
    assert recovered_track.status_code == 200
    assert recovered_track.json()["cache_cleanup_status"] == "completed"
    assert replacement.status_code == 201

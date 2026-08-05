from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from shutil import which
from subprocess import run
from threading import Event
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import CanonicalSourceBatch, CollectionPlan, DataService
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import (
    CoreRuntime,
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.publication import (
    PreparedPublication,
    Publication,
    PublishedRef,
    VerifiedBundle,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "failure_seam",
    ("collection", "upload", "verification", "manifest", "transaction"),
)
def test_failed_publication_keeps_previous_release_and_retries_after_restart(
    failure_seam: str,
) -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _bootstrap(settings, f"ticket-13-{failure_seam}-root")

    with open_core_runtime(settings) as runtime:
        root = runtime.data.overview().latest_release
        assert root is not None
        durable_before = _durable_counts(runtime.database)
        failure = _failing_data_service(runtime, settings, failure_seam)
        data = failure.data
        assert data.update(f"ticket-13-{failure_seam}").outcome == "accepted"
        with pytest.raises(RuntimeError, match="injected-data-failure"):
            data.process_next_update()
        assert data.overview().status == "updating"
        assert data.overview().latest_update_outcome == "published"
        assert data.overview().latest_release == root
        durable_after = _durable_counts(runtime.database)
        assert durable_after["releases"] == durable_before["releases"]
        assert durable_after["manifests"] == durable_before["manifests"]
        assert durable_after["publication_objects"] == durable_before["publication_objects"]
        assert durable_after["attempts"] == durable_before["attempts"] + 1
        assert _receipt(runtime.database, f"ticket-13-{failure_seam}")["status"] == "accepted"
        if failure_seam == "upload":
            assert len(failure.uploaded_keys) == 1
            orphan_key = failure.uploaded_keys[0]
            orphan_digest = orphan_key.rsplit("/", maxsplit=1)[-1]
            assert _s3_object_exists(settings, orphan_key)
            assert _publication_digest_references(runtime.database, orphan_digest) == 0

    with open_core_runtime(settings) as restarted_runtime:
        assert restarted_runtime.data.process_next_update()
        latest = restarted_runtime.data.overview().latest_release
        assert latest is not None
        assert latest.predecessor_id == root.id
        assert _receipt(
            restarted_runtime.database,
            f"ticket-13-{failure_seam}",
        )["status"] == "published"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_bounded_retry_exhaustion_is_sanitized_and_allows_later_update() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _bootstrap(settings, "ticket-13-exhaustion-root")
    request_id = "ticket-13-exhaustion"

    with open_core_runtime(settings) as runtime:
        root = runtime.data.overview().latest_release
        assert root is not None
        data = DataService(runtime.database, runtime.publication, _AlwaysFailingSource())
        assert data.update(request_id).outcome == "accepted"
        for attempt_number in range(1, 4):
            with pytest.raises(RuntimeError, match="secret-provider-detail"):
                data.process_next_update()
            receipt = _receipt(runtime.database, request_id)
            if attempt_number < 3:
                assert receipt["status"] == "accepted"
                assert data.overview().status == "updating"
                assert data.overview().latest_update_outcome == "published"
            else:
                assert receipt == {
                    "status": "failed",
                    "failure_reason": "RuntimeError",
                    "release_id": None,
                }
                assert data.overview().status == "failed"
                assert data.overview().latest_update_outcome == "failed"
            assert data.overview().latest_release == root

    with TestClient(create_app(settings)) as restarted_http:
        replay = restarted_http.post(
            "/api/data/update",
            headers={"Idempotency-Key": request_id},
        )
        assert replay.status_code == 202
        assert replay.json()["outcome"] == "failed"
        admitted = restarted_http.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-13-after-failure"},
        )
        assert admitted.status_code == 202
        assert admitted.json()["outcome"] == "accepted"

    with open_core_runtime(settings) as restarted_worker:
        assert restarted_worker.data.process_next_update()
        latest = restarted_worker.data.overview().latest_release
        assert latest is not None
        assert latest.predecessor_id == root.id
        assert restarted_worker.data.overview().status == "idle"
        assert restarted_worker.data.overview().latest_update_outcome == "published"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_stale_worker_is_fenced_after_recovery_and_cannot_duplicate_release() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _bootstrap(settings, "ticket-13-stale-root")
    request_id = "ticket-13-stale"
    entered = Event()
    release = Event()
    late_errors: list[Exception] = []

    with open_core_runtime(settings) as stale_runtime:
        root = stale_runtime.data.overview().latest_release
        assert root is not None
        stale_data = DataService(
            stale_runtime.database,
            stale_runtime.publication,
            _BlockingSource(entered, release),
        )
        assert stale_data.update(request_id).outcome == "accepted"

        def run_stale_worker() -> None:
            try:
                stale_data.process_next_update()
            except Exception as error:
                late_errors.append(error)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_stale_worker)
            assert entered.wait(timeout=10)
            with stale_runtime.database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.update_attempts
                    SET started_at = '2000-01-01'
                    WHERE request_id = %s AND status = 'running'
                    """,
                    (request_id,),
                )

            with open_core_runtime(settings) as restarted_worker:
                assert restarted_worker.data.recover_abandoned_updates(
                    stale_before=datetime.now(UTC)
                ) == 1
                assert _receipt(restarted_worker.database, request_id)["status"] == "accepted"
                assert restarted_worker.data.process_next_update()
                winner = restarted_worker.data.overview().latest_release
                assert winner is not None
                assert winner.predecessor_id == root.id

            release.set()
            future.result(timeout=30)

        assert len(late_errors) == 1
        assert _durable_counts(stale_runtime.database)["releases"] == 2
        assert _attempt_count(stale_runtime.database, request_id) == 2
        assert _receipt(stale_runtime.database, request_id)["status"] == "published"
        assert stale_data.overview().latest_release == winner


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_fresh_worker_process_recovers_stale_claim_after_restart() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _bootstrap(settings, "ticket-13-process-root")
    request_id = "ticket-13-process-restart"
    with open_core_runtime(settings) as runtime:
        root = runtime.data.overview().latest_release
        assert root is not None
        assert runtime.data.update(request_id).outcome == "accepted"
        with runtime.database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.update_receipts
                SET status = 'running', updated_at = '2000-01-01'
                WHERE request_id = %s
                """,
                (request_id,),
            )
            transaction.execute(
                """
                INSERT INTO data.update_attempts (request_id, status, started_at)
                VALUES (%s, 'running', '2000-01-01')
                """,
                (request_id,),
            )

    worker = which("thesistrace-core-worker")
    assert worker is not None
    completed = run(
        [worker, "--once"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr

    with TestClient(create_app(settings)) as restarted_http:
        overview = restarted_http.get("/api/data")
        assert overview.status_code == 200
        payload = overview.json()
        assert payload["status"] == "idle"
        assert payload["latest_update_outcome"] == "published"
        assert payload["latest_release"]["predecessor_id"] == root.id
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        assert _attempt_count(database, request_id) == 2
        assert _receipt(database, request_id)["status"] == "published"
    finally:
        database.close()


class _AlwaysFailingSource:
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        raise RuntimeError("secret-provider-detail")


class _BlockingSource:
    def __init__(self, entered: Event, release: Event) -> None:
        self._entered = entered
        self._release = release
        self._delegate = FixtureDataSource()

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        self._entered.set()
        if not self._release.wait(timeout=30):
            raise RuntimeError("blocking source timed out")
        return self._delegate.collect(plan)


class _FailingPublication:
    def __init__(
        self,
        delegate: Publication,
        failure_seam: str,
        delete_object: Callable[[str], None],
    ) -> None:
        self._delegate = delegate
        self._failure_seam = failure_seam
        self._delete_object = delete_object

    def prepare(self, **kwargs: object) -> PreparedPublication:
        prepared = self._delegate.prepare(**kwargs)
        if self._failure_seam == "verification":
            self._delete_object(next(iter(prepared.payload_sha256s.values())))
        return prepared

    def read(self, published_ref: PublishedRef) -> VerifiedBundle:
        return self._delegate.read(published_ref)

    def record(
        self,
        transaction: PostgresTransaction,
        prepared: PreparedPublication,
    ) -> PublishedRef:
        if self._failure_seam == "manifest":
            try:
                return self._delegate.record(
                    _ManifestFailingTransaction(transaction),  # type: ignore[arg-type]
                    prepared,
                )
            except RuntimeError:
                raise
        try:
            published = self._delegate.record(transaction, prepared)
        except Exception as error:
            if self._failure_seam == "verification":
                raise RuntimeError("injected-data-failure") from error
            raise
        if self._failure_seam == "transaction":
            raise RuntimeError("injected-data-failure")
        return published


@dataclass(frozen=True)
class _FailureSetup:
    data: DataService
    uploaded_keys: list[str]


def _failing_data_service(
    runtime: CoreRuntime,
    settings: CoreSettings,
    failure_seam: str,
) -> _FailureSetup:
    if failure_seam == "collection":
        return _FailureSetup(
            DataService(runtime.database, runtime.publication, _InjectedFailingSource()),
            [],
        )
    if failure_seam == "upload":
        failing_s3 = _FailingUploadS3(_s3(settings))
        upload_failure = Publication(
            runtime.database,
            failing_s3,  # type: ignore[arg-type]
            bucket=settings.s3_bucket,
        )
        return _FailureSetup(
            DataService(runtime.database, upload_failure, _UniqueCanonicalSource()),
            failing_s3.uploaded_keys,
        )
    publication = _FailingPublication(
        runtime.publication,
        failure_seam,
        lambda digest: _delete_object(settings, digest),
    )
    return _FailureSetup(
        DataService(  # type: ignore[arg-type]
            runtime.database,
            publication,
            FixtureDataSource(),
        ),
        [],
    )


class _InjectedFailingSource:
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        raise RuntimeError("injected-data-failure")


class _UniqueCanonicalSource:
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        batch = FixtureDataSource().collect(plan)
        return CanonicalSourceBatch(
            source_name=batch.source_name,
            collection_kind=batch.collection_kind,
            source_lineage=batch.source_lineage,
            canonical={**batch.canonical, "failure_nonce": uuid4().hex},
            covered_session_range=batch.covered_session_range,
        )


class _FailingUploadS3:
    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self._put_count = 0
        self.uploaded_keys: list[str] = []

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def head_object(self, **kwargs: object) -> object:
        raise ClientError(
            {"Error": {"Code": "404", "Message": "injected missing object"}},
            "HeadObject",
        )

    def put_object(self, **kwargs: object) -> object:
        self._put_count += 1
        if self._put_count == 2:
            raise RuntimeError("injected-data-failure")
        result = self._delegate.put_object(**kwargs)  # type: ignore[attr-defined]
        self.uploaded_keys.append(str(kwargs["Key"]))
        return result


class _ManifestFailingTransaction:
    def __init__(self, delegate: PostgresTransaction) -> None:
        self._delegate = delegate

    def execute(self, query: object, params: object = None):
        if "INSERT INTO publication.manifests" in str(query):
            raise RuntimeError("injected-data-failure")
        return self._delegate.execute(query, params)  # type: ignore[arg-type]


def _bootstrap(settings: CoreSettings, request_id: str) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": request_id},
        )
        assert response.status_code == 202
    with open_core_runtime(settings) as runtime:
        assert runtime.data.process_next_update()


def _receipt(database: PostgresDatabase, request_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT status, failure_reason, release_id
            FROM data.update_receipts
            WHERE request_id = %s
            """,
            (request_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _durable_counts(database: PostgresDatabase) -> dict[str, int]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
              (SELECT count(*) FROM data.releases) AS releases,
              (SELECT count(*) FROM data.update_attempts) AS attempts,
              (SELECT count(*) FROM publication.manifests) AS manifests,
              (SELECT count(*) FROM publication.objects) AS publication_objects
            """
        ).fetchone()
    assert row is not None
    return {key: int(value) for key, value in row.items()}


def _attempt_count(database: PostgresDatabase, request_id: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS count FROM data.update_attempts WHERE request_id = %s",
            (request_id,),
        ).fetchone()
    assert row is not None
    return int(row["count"])


def _s3_object_exists(settings: CoreSettings, key: str) -> bool:
    response = _s3(settings).head_object(Bucket=settings.s3_bucket, Key=key)
    return int(response["ResponseMetadata"]["HTTPStatusCode"]) == 200


def _publication_digest_references(database: PostgresDatabase, digest: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
              (SELECT count(*) FROM publication.objects WHERE sha256 = %s) +
              (SELECT count(*) FROM publication.manifest_objects WHERE object_sha256 = %s) +
              (SELECT count(*) FROM data.releases WHERE manifest_sha256 = %s) AS count
            """,
            (digest, digest, digest),
        ).fetchone()
    assert row is not None
    return int(row["count"])


def _delete_object(settings: CoreSettings, digest: str) -> None:
    _s3(settings).delete_object(
        Bucket=settings.s3_bucket,
        Key=f"publication/v1/sha256/{digest[:2]}/{digest}",
    )


def _s3(settings: CoreSettings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def _reset_core_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()

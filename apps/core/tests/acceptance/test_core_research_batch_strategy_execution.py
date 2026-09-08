from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

import boto3
import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas, isolated_core_settings
from core_runtime import create_initialized_test_app as create_app
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_core_research_batch_admission import _publish_current_data, _strategy_command
from test_core_research_batch_factor_recovery import (
    _expire_batch_attempt,
    _lost_attempt_evidence,
    _pin_status_for_attempt,
    _run_dependency_command,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.data import DatasetLifecycle
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_batch.execution import (
    ResearchBatchChildLost,
    SupervisedResearchBatchExecutor,
)
from thesistrace.research_batch.planning import validate_research_batch_capacity
from thesistrace.research_batch.private_artifact import (
    PRIVATE_ARTIFACT_MEDIA_TYPE,
    PRIVATE_ARTIFACT_PUBLICATION_KIND,
    PRIVATE_ARTIFACT_SCHEMA_VERSION,
    PRIVATE_ARTIFACT_SERIALIZATION,
    PrivateAlphaFactorArtifactReader,
    PrivateAlphaFactorArtifactWriter,
    PrivateAlphaFactorChunk,
)
from thesistrace.research_batch.service import (
    ResearchBatchService,
    preserve_deleted_run_history,
)
from thesistrace.research_folder import BATCH_RESEARCH_FOLDER_ID
from thesistrace.research_kernel.research_chunks import AlphaFactorExecutionBinding
from thesistrace.research_run.execution import ResearchExecutionResourceExhausted
from thesistrace.research_run.models import StrategyBacktestAdmissionCommand
from thesistrace.research_run.result import read_result_bundle
from thesistrace.research_run.service import ResearchRunService
from thesistrace.researcher.quota import QuotaPolicy


class _StrategyTransportFailureExecutor:
    def execute(self, request, *, emit, cancel_requested):
        raise ResearchBatchChildLost("injected Strategy Sweep transport failure")


class _StrategyPermanentFailureExecutor:
    def execute(self, request, *, emit, cancel_requested):
        raise RuntimeError("injected deterministic Strategy failure")


class _FirstStrategyStartedBarrierExecution:
    def __init__(self, delegate, started: Event, release: Event) -> None:
        self._delegate = delegate
        self._started = started
        self._release = release

    @property
    def message(self):
        return self._delegate.message

    @property
    def child_pid(self) -> int:
        return self._delegate.child_pid

    def advance(self, command: str) -> None:
        self._delegate.advance(command)
        if self.message.get("status") == "item_started" and self.message.get("item_ordinal") == 1:
            self._started.set()
            if not self._release.wait(timeout=30):
                raise AssertionError("First Strategy task barrier was not released")

    def acknowledge(self) -> None:
        self._delegate.acknowledge()

    def close(self) -> None:
        self._delegate.close()


class _FirstStrategyStartedBarrierExecutor:
    def __init__(self, delegate: SupervisedResearchBatchExecutor) -> None:
        self._delegate = delegate
        self.started = Event()
        self.release = Event()

    def execute(self, request, *, emit, cancel_requested):
        return _FirstStrategyStartedBarrierExecution(
            self._delegate.execute(request, emit=emit, cancel_requested=cancel_requested),
            self.started,
            self.release,
        )


class _InvalidSharedEvidenceExecution:
    def __init__(self, delegate, invalid_evidence: str) -> None:
        self._delegate = delegate
        self._invalid_evidence = invalid_evidence
        self._invalidated = False

    @property
    def message(self):
        return self._delegate.message

    @property
    def child_pid(self) -> int:
        return self._delegate.child_pid

    def advance(self, command: str) -> None:
        self._delegate.advance(command)
        if not self._invalidated and self.message.get("status") == "shared_alpha_factor_succeeded":
            self._invalidated = True
            if self._invalid_evidence == "checksum":
                self.message["private_artifact_sha256"] = "0" * 64
            else:
                Path(str(self.message["private_artifact_path"])).unlink()

    def acknowledge(self) -> None:
        self._delegate.acknowledge()

    def close(self) -> None:
        self._delegate.close()


class _InvalidSharedEvidenceExecutor:
    def __init__(
        self,
        delegate: SupervisedResearchBatchExecutor,
        invalid_evidence: str,
    ) -> None:
        self._delegate = delegate
        self._invalid_evidence = invalid_evidence

    def execute(self, request, *, emit, cancel_requested):
        return _InvalidSharedEvidenceExecution(
            self._delegate.execute(request, emit=emit, cancel_requested=cancel_requested),
            self._invalid_evidence,
        )


class _SharedArtifactReadyBarrierExecution:
    def __init__(self, delegate, ready: Event, release: Event) -> None:
        self._delegate = delegate
        self._ready = ready
        self._release = release

    @property
    def message(self):
        return self._delegate.message

    @property
    def child_pid(self) -> int:
        return self._delegate.child_pid

    def advance(self, command: str) -> None:
        self._delegate.advance(command)
        if self.message.get("status") == "shared_alpha_factor_succeeded":
            self._ready.set()
            if not self._release.wait(timeout=30):
                raise AssertionError("Shared private artifact barrier was not released")

    def acknowledge(self) -> None:
        self._delegate.acknowledge()

    def close(self) -> None:
        self._delegate.close()


class _SharedArtifactReadyBarrierExecutor:
    def __init__(self, delegate: SupervisedResearchBatchExecutor) -> None:
        self._delegate = delegate
        self.ready = Event()
        self.release = Event()

    def execute(self, request, *, emit, cancel_requested):
        return _SharedArtifactReadyBarrierExecution(
            self._delegate.execute(request, emit=emit, cancel_requested=cancel_requested),
            self.ready,
            self.release,
        )


def _replace_private_artifact(
    runtime,
    batch_id: str,
    *,
    artifact_batch_id: str | None = None,
    kernel_semantic_version: str | None = None,
) -> None:
    with runtime.database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT manifest_sha256, binding_checksum, binding, content_sha256
            FROM research_batches.private_alpha_factor_artifacts
            WHERE batch_id = %s
            """,
            (batch_id,),
        ).fetchone()
    assert row is not None
    binding = AlphaFactorExecutionBinding.from_value_snapshot(row["binding"])
    provenance = {
        "schema_version": PRIVATE_ARTIFACT_SCHEMA_VERSION,
        "batch_id": batch_id,
        "binding_checksum": row["binding_checksum"],
        "content_sha256": row["content_sha256"],
    }
    with TemporaryDirectory() as directory:
        source_path = Path(directory) / "source.artifact"
        runtime.publication.materialize_payload(
            PublishedRef(
                manifest_sha256=row["manifest_sha256"],
                kind=PRIVATE_ARTIFACT_PUBLICATION_KIND,
                provenance=provenance,
            ),
            "private_alpha_factor",
            source_path,
        )
        with PrivateAlphaFactorArtifactReader(
            source_path,
            expected_batch_id=batch_id,
            expected_binding=binding,
            maximum_chunk_payload_bytes=source_path.stat().st_size,
        ) as reader:
            chunks = tuple(reader)
            final_alpha_continuation = reader.final_alpha_continuation
        binding_value = binding.value_snapshot()
        if kernel_semantic_version is not None:
            semantic_versions = dict(binding_value["semantic_versions"])
            semantic_versions["kernel"] = kernel_semantic_version
            binding_value["semantic_versions"] = semantic_versions
        replacement_binding = AlphaFactorExecutionBinding.from_value_snapshot(binding_value)
        if replacement_binding.checksum != binding.checksum:
            chunks = tuple(
                PrivateAlphaFactorChunk(
                    first_session=chunk.first_session,
                    last_session=chunk.last_session,
                    outcome_payload=_replace_compact_binding_checksum(
                        chunk.outcome_payload,
                        replacement_binding.checksum,
                    ),
                    completed_research_sessions=chunk.completed_research_sessions,
                    final=chunk.final,
                )
                for chunk in chunks
            )
            final_alpha_continuation = dict(final_alpha_continuation)
            final_alpha_continuation["binding_checksum"] = replacement_binding.checksum
        replacement_path = Path(directory) / "replacement.artifact"
        writer = PrivateAlphaFactorArtifactWriter(
            replacement_path,
            batch_id=artifact_batch_id or batch_id,
            binding=replacement_binding,
            maximum_chunk_payload_bytes=max(len(chunk.outcome_payload) for chunk in chunks),
        )
        for chunk in chunks:
            writer.append(chunk)
        replacement = writer.complete(final_alpha_continuation=final_alpha_continuation)
        staged = runtime.publication.stage_file(
            replacement_path,
            media_type=PRIVATE_ARTIFACT_MEDIA_TYPE,
            serialization=PRIVATE_ARTIFACT_SERIALIZATION,
        )
    prepared = runtime.publication.prepare(
        kind=PRIVATE_ARTIFACT_PUBLICATION_KIND,
        payloads={"private_alpha_factor": staged},
        provenance={
            "schema_version": PRIVATE_ARTIFACT_SCHEMA_VERSION,
            "batch_id": batch_id,
            "binding_checksum": replacement_binding.checksum,
            "content_sha256": replacement.sha256,
        },
    )
    with runtime.database.transaction() as transaction:
        published = runtime.publication.record(transaction, prepared)
        transaction.execute(
            """
            UPDATE research_batches.private_alpha_factor_artifacts
            SET manifest_sha256 = %s, binding_checksum = %s, binding = %s,
                content_sha256 = %s, byte_size = %s
            WHERE batch_id = %s
            """,
            (
                published.manifest_sha256,
                replacement_binding.checksum,
                Jsonb(replacement_binding.value_snapshot()),
                replacement.sha256,
                replacement.byte_size,
                batch_id,
            ),
        )


def _replace_compact_binding_checksum(content: bytes, checksum: str) -> bytes:
    value = json.loads(content)
    assert isinstance(value, dict)
    continuation = value["continuation"]
    assert isinstance(continuation, dict)
    value["binding_checksum"] = checksum
    continuation["binding_checksum"] = checksum
    return canonical_json_bytes(value)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.dependency_restart
def test_real_rustfs_loss_retries_shared_strategy_prerequisite(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    restarted_s3_port: int | None = None
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-rustfs-shared-retry"),
        ).json()
        runtime = client.app.state.core_runtime
        _run_dependency_command("stop-rustfs")
        try:
            assert runtime.research_batches.process_next() is True
        finally:
            restarted_s3_port = _run_dependency_command("restart-rustfs")
        interrupted = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert interrupted["status"] == "queued"
        assert interrupted["progress"]["shared_alpha_factor_status"] == "pending"
        assert interrupted["progress"]["completed_strategy_tasks"] == 0

    assert restarted_s3_port is not None
    restarted_settings = replace(
        settings,
        s3_endpoint_url=f"http://127.0.0.1:{restarted_s3_port}",
    )
    with TestClient(create_app(restarted_settings)) as restarted:
        runtime = restarted.app.state.core_runtime
        assert runtime.research_batches.process_next() is True
        completed = restarted.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        with runtime.database.transaction() as transaction:
            attempts = transaction.execute(
                """
                SELECT ordinal, status
                FROM research_batches.task_attempts
                WHERE batch_id = %s AND task_role = 'shared_alpha_factor'
                ORDER BY ordinal
                """,
                (admitted["id"],),
            ).fetchall()
        assert attempts == [
            {"ordinal": 1, "status": "failed"},
            {"ordinal": 2, "status": "succeeded"},
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.database_restart
def test_real_postgres_loss_reuses_acknowledged_private_artifact(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    restarted_postgres_port: int | None = None
    attempt_id: str | None = None
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-postgres-private-artifact-retry"),
        ).json()
        runtime = client.app.state.core_runtime
        barrier = _FirstStrategyStartedBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            )
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=barrier,
            heartbeat_seconds=60,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(processor.process_next)
            assert barrier.started.wait(timeout=30)
            detail = client.get(f"/api/research-batches/{admitted['id']}").json()
            attempt_id = detail["attempt"]["id"]
            assert detail["progress"]["shared_alpha_factor_status"] == "succeeded"
            _run_dependency_command("stop-postgres")
            barrier.release.set()
            try:
                assert future.result(timeout=90) is True
            finally:
                restarted_postgres_port = _run_dependency_command("restart-postgres")

    assert restarted_postgres_port is not None and attempt_id is not None
    restarted_settings = replace(
        settings,
        database_url=(
            "postgresql://thesistrace_owner:owner-test-password@127.0.0.1:"
            f"{restarted_postgres_port}/thesistrace"
        ),
    )
    recovered_events: list[dict[str, object]] = []
    with TestClient(create_app(restarted_settings)) as restarted:
        runtime = restarted.app.state.core_runtime
        _expire_batch_attempt(runtime, attempt_id)
        assert (
            runtime.research_batches.process_next(on_execution_event=recovered_events.append)
            is True
        )
        completed = restarted.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert any(
            event.get("event") == "research_batch_execution_shared_alpha_factor_succeeded"
            and event.get("private_artifact_reused") is True
            for event in recovered_events
        )
        with runtime.database.transaction() as transaction:
            first_strategy_attempts = transaction.execute(
                """
                SELECT ordinal, status
                FROM research_batches.task_attempts
                WHERE batch_id = %s AND task_role = 'strategy'
                  AND item_ordinal = 1
                ORDER BY ordinal
                """,
                (admitted["id"],),
            ).fetchall()
        assert first_strategy_attempts == [
            {"ordinal": 1, "status": "failed"},
            {"ordinal": 2, "status": "succeeded"},
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_transport_failure_before_child_ready_counts_toward_retry_budget(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-startup-failure"),
        ).json()
        runtime = client.app.state.core_runtime
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=_StrategyTransportFailureExecutor(),
        )

        for expected_attempt in range(1, 4):
            assert processor.process_next() is True
            detail = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert detail["attempt"] is None
            if expected_attempt < 3:
                assert detail["status"] == "queued"
                assert all(item["status"] == "queued" for item in detail["items"])
                assert all(item["diagnostic"] is None for item in detail["items"])

        failed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert failed["status"] == "failed"
        assert all(item["outcome"] == "failed" for item in failed["items"])
        assert all(
            item["diagnostic"]["code"] == "RESEARCH_BATCH_INFRASTRUCTURE_UNAVAILABLE"
            for item in failed["items"]
        )
        assert processor.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_deterministic_start_failure_is_not_retried(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-deterministic-start-failure"),
        ).json()
        runtime = client.app.state.core_runtime
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=_StrategyPermanentFailureExecutor(),
        )

        assert processor.process_next() is True
        failed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert failed["status"] == "failed"
        assert all(item["outcome"] == "failed" for item in failed["items"])
        assert all(
            item["diagnostic"]["code"] == "RESEARCH_BATCH_EXECUTION_FAILED"
            for item in failed["items"]
        )
        assert processor.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_reuses_shared_alpha_factor_and_matches_ordinary_runs(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        generation_id = _publish_current_data(settings)
        BenchmarkSnapshotStore(settings.benchmark_mount).publish(
            (
                BenchmarkLevel("2010-01-04", "3500"),
                BenchmarkLevel("2026-08-03", "4000"),
                BenchmarkLevel("2026-08-04", "4040"),
                BenchmarkLevel("2026-08-05", "4080"),
            ),
            published_at=datetime(2026, 8, 5, 18, tzinfo=UTC),
        )
        command = {
            **_strategy_command("strategy-sweep-equivalence"),
            "end_date": "2026-08-05",
        }
        batch = client.post("/api/research-batches", json=command).json()
        child_ids = [str(item["research_run_id"]) for item in batch["items"]]
        assert client.delete(f"/api/research-runs/{child_ids[0]}").status_code == 409
        batch_folder_runs = client.get(
            "/api/research-runs",
            params={"folder_id": BATCH_RESEARCH_FOLDER_ID},
        ).json()["items"]
        assert {run["id"] for run in batch_folder_runs} == set(child_ids)
        target_folder = client.post(
            "/api/research-folders",
            json={"name": "Organized Batch Result"},
        ).json()
        renamed_and_moved = client.patch(
            f"/api/research-runs/{child_ids[0]}",
            json={"name": "Reviewed Sweep", "folder_id": target_folder["id"]},
        )
        assert renamed_and_moved.status_code == 200
        assert renamed_and_moved.json()["name"] == "Reviewed Sweep"
        assert renamed_and_moved.json()["folder_id"] == target_folder["id"]
        organized_batch = client.get(f"/api/research-batches/{batch['id']}").json()
        assert [
            (item["ordinal"], item["item_key"], item["research_run_id"])
            for item in organized_batch["items"]
        ] == [
            (item["ordinal"], item["item_key"], item["research_run_id"]) for item in batch["items"]
        ]
        assert client.delete(f"/api/research-folders/{BATCH_RESEARCH_FOLDER_ID}").status_code == 409
        ordinary = [
            client.post(
                "/api/research-runs",
                json=_ordinary_strategy_command(
                    f"ordinary-strategy-{ordinal}",
                    holdings_count=int(item["holdings_count"]),
                    rebalance_every_sessions=int(item["rebalance_every_sessions"]),
                    end_date="2026-08-05",
                ),
            ).json()
            for ordinal, item in enumerate(command["strategies"], start=1)
        ]
        runtime = client.app.state.core_runtime
        for run in ordinary:
            assert runtime.research_runs.process_next() is True
            assert client.get(f"/api/research-runs/{run['id']}").json()["status"] == ("succeeded")

        assert runtime.research_batches.process_next(on_execution_event=events.append) is True

        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["progress"] == {
            "shared_alpha_factor_status": "succeeded",
            "completed_strategy_tasks": 2,
            "total_strategy_tasks": 2,
        }
        assert completed["live_progress"] is None
        for item, ordinary_run in zip(completed["items"], ordinary, strict=True):
            batch_stored = _stored_run(settings, str(item["research_run_id"]))
            ordinary_stored = _stored_run(settings, str(ordinary_run["id"]))
            assert canonical_json_bytes(
                _stored_result(runtime, batch_stored)
            ) == canonical_json_bytes(_stored_result(runtime, ordinary_stored))
            assert batch_stored["result_provenance"]["data_generation_id"] == (generation_id)
            assert batch_stored["result_provenance"]["research_run_id"] == (item["research_run_id"])
            assert (
                batch_stored["result_provenance"]["calculation_contracts"]
                == (ordinary_stored["result_provenance"]["calculation_contracts"])
            )
            assert (
                batch_stored["result_provenance"]["semantic_versions"]
                == (ordinary_stored["result_provenance"]["semantic_versions"])
            )
            assert batch_stored["key_metrics"] == ordinary_stored["key_metrics"]
            assert batch_stored["key_metrics"]["annualized_excess_return"] is not None

        ordinary_in_batch_folder = client.post(
            "/api/research-runs",
            json={
                **_ordinary_strategy_command(
                    "ordinary-in-batch-folder",
                    holdings_count=1,
                    rebalance_every_sessions=1,
                ),
                "folder_id": BATCH_RESEARCH_FOLDER_ID,
            },
        ).json()

        track = client.post(
            f"/api/research-runs/{completed['items'][0]['research_run_id']}/daily-tracks",
            json={"request_id": "batch-strategy-seed-track"},
        )
        assert track.status_code == 201
        assert track.json()["status"] == "active"
        track_id = str(track.json()["id"])
        untracked_manifest = str(_stored_run(settings, child_ids[1])["result_manifest_sha256"])

        projection_entered = Event()
        release_projection = Event()
        deletion_hook_entered = Event()

        class _ProjectionBarrier:
            def project_child_statuses_in_transaction(
                self,
                transaction,
                researcher_id,
                run_ids,
            ):
                projection_entered.set()
                if not release_projection.wait(timeout=10):
                    raise TimeoutError("Batch detail projection barrier timed out")
                return runtime.research_runs.project_child_statuses_in_transaction(
                    transaction,
                    researcher_id,
                    run_ids,
                )

        consistent_reader = ResearchBatchService(
            runtime.database,
            research_runs=_ProjectionBarrier(),  # type: ignore[arg-type]
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
        )

        def preserve_history(transaction, researcher_id, run_id):
            deletion_hook_entered.set()
            preserve_deleted_run_history(transaction, researcher_id, run_id)

        concurrent_deleter = ResearchRunService(
            runtime.database,
            publication=runtime.publication,
            track_references_result=runtime.daily_tracks.references_result_manifest,
            preserve_dependent_run_history=preserve_history,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            detail_future = executor.submit(
                consistent_reader.get,
                TEST_RESEARCHER.researcher_id,
                batch["id"],
            )
            assert projection_entered.wait(timeout=10)
            delete_future = executor.submit(
                concurrent_deleter.delete,
                TEST_RESEARCHER.researcher_id,
                child_ids[0],
            )
            assert deletion_hook_entered.wait(timeout=10)
            assert delete_future.done() is False
            release_projection.set()
            detail_during_delete = detail_future.result(timeout=10)
            assert detail_during_delete is not None
            assert detail_during_delete.items[0].run_availability == "available"
            assert delete_future.result(timeout=10) is True

        assert client.get(f"/api/research-runs/{child_ids[0]}").status_code == 404
        first_deleted = client.get(f"/api/research-batches/{batch['id']}").json()
        assert first_deleted["status"] == completed["status"]
        assert first_deleted["progress"] == completed["progress"]
        assert first_deleted["items"][0] == {
            **completed["items"][0],
            "run_availability": "deleted",
            "deleted_at": first_deleted["items"][0]["deleted_at"],
        }
        assert first_deleted["items"][0]["deleted_at"] is not None
        assert first_deleted["items"][1] == completed["items"][1]
        assert client.get(f"/api/research-runs/{child_ids[1]}").status_code == 200
        surviving_track = client.get(f"/api/daily-tracks/{track_id}")
        assert surviving_track.status_code == 200
        assert surviving_track.json()["origin"]["seed_run_id"] == child_ids[0]
        assert surviving_track.json()["origin"]["seed_research_available"] is False

        assert client.delete(f"/api/research-runs/{child_ids[1]}").status_code == 204
        final_history = client.get(f"/api/research-batches/{batch['id']}").json()
        assert final_history["status"] == completed["status"]
        assert final_history["progress"] == completed["progress"]
        assert [item["run_availability"] for item in final_history["items"]] == [
            "deleted",
            "deleted",
        ]
        assert [item["status"] for item in final_history["items"]] == [
            "succeeded",
            "succeeded",
        ]
        assert [item["outcome"] for item in final_history["items"]] == [
            "succeeded",
            "succeeded",
        ]
        assert client.get(f"/api/research-runs/{ordinary_in_batch_folder['id']}").status_code == 200
        assert client.delete(f"/api/research-batches/{batch['id']}").status_code == 405
        with runtime.database.transaction() as transaction:
            assert (
                transaction.execute(
                    "SELECT 1 FROM publication.manifests WHERE sha256 = %s",
                    (untracked_manifest,),
                ).fetchone()
                is None
            )

    prepared = [
        event for event in events if event["event"] == "research_batch_execution_batch_prepared"
    ]
    shared = [
        event
        for event in events
        if event["event"] == "research_batch_execution_shared_alpha_factor_succeeded"
    ]
    strategies = [
        event for event in events if event["event"] == "research_batch_execution_item_succeeded"
    ]
    assert len(prepared) == 1
    assert len(shared) == 1
    shared_started = next(
        event
        for event in events
        if event["event"] == "research_batch_execution_shared_alpha_factor_started"
    )
    assert shared_started["alpha_factor_task_started"] is True
    assert shared[0]["alpha_factor_task_started"] is False
    assert shared[0]["alpha_factor_task_completed"] is True
    assert [event["item_ordinal"] for event in strategies] == [1, 2]
    assert all(event["alpha_factor_task_started"] is False for event in strategies)
    assert all(event["strategy_task_started"] is False for event in strategies)
    assert all(event["strategy_task_completed"] is True for event in strategies)
    strategy_starts = [
        event for event in events if event["event"] == "research_batch_execution_item_started"
    ]
    assert [event["item_ordinal"] for event in strategy_starts] == [1, 2]
    assert all(event["strategy_task_started"] is True for event in strategy_starts)
    assert int(prepared[0]["data_io"]["rows_scanned"]) == 0
    assert all(
        int(event["data_io"]["rows_scanned"]) > int(prepared[0]["data_io"]["rows_scanned"])
        for event in strategies
    )
    assert (
        max(
            int(event["child_peak_rss_bytes"])
            for event in events
            if "child_peak_rss_bytes" in event
        )
        <= settings.research_execution_memory_bytes
    )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_reuses_private_artifact_after_worker_loss(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    first_events: list[dict[str, object]] = []
    recovered_events: list[dict[str, object]] = []
    interrupted = False

    def interrupt_after_private_artifact(event: dict[str, object]) -> None:
        nonlocal interrupted
        first_events.append(event)
        if not interrupted and event.get("event") == "research_batch_execution_item_started":
            interrupted = True
            raise ResearchBatchChildLost(
                "injected Worker loss after private artifact acknowledgement"
            )

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-private-artifact-recovery"),
        ).json()
        runtime = client.app.state.core_runtime

        assert (
            runtime.research_batches.process_next(
                on_execution_event=interrupt_after_private_artifact
            )
            is True
        )
        queued = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert queued["status"] == "queued"
        assert queued["progress"]["shared_alpha_factor_status"] == "succeeded"
        assert queued["progress"]["completed_strategy_tasks"] == 0
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_batches.private_alpha_factor_artifacts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone() == {"count": 1}

        assert (
            runtime.research_batches.process_next(on_execution_event=recovered_events.append)
            is True
        )
        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["progress"]["completed_strategy_tasks"] == len(completed["items"])
        assert any(
            event.get("event") == "research_batch_execution_shared_alpha_factor_succeeded"
            and event.get("private_artifact_reused") is True
            for event in recovered_events
        )
        assert not any(
            event.get("event") == "research_batch_execution_shared_alpha_factor_chunk_succeeded"
            for event in recovered_events
        )
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_batches.private_alpha_factor_artifacts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone() == {"count": 0}
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.object_deletions"
            ).fetchone() == {"count": 1}
        assert runtime.publication.collect_one_pending_deletion() is True
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.object_deletions"
            ).fetchone() == {"count": 0}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize("invalid_evidence", ["checksum", "missing_file"])
def test_invalid_new_private_artifact_evidence_is_permanent_without_retry(
    tmp_path: Path,
    invalid_evidence: str,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-invalid-new-private-artifact"),
        ).json()
        runtime = client.app.state.core_runtime
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=_InvalidSharedEvidenceExecutor(
                SupervisedResearchBatchExecutor(
                    settings.data_mount,
                    attempt_control_directory=settings.batch_attempt_control_directory,
                    execution_memory_bytes=settings.research_execution_memory_bytes,
                ),
                invalid_evidence,
            ),
        )

        assert processor.process_next() is True
        failed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert failed["status"] == "failed"
        assert failed["progress"]["shared_alpha_factor_status"] == "failed"
        assert all(
            item["diagnostic"]["code"] == "PRIVATE_ALPHA_FACTOR_ARTIFACT_REJECTED"
            for item in failed["items"]
        )
        with runtime.database.transaction() as transaction:
            attempts = transaction.execute(
                """
                SELECT ordinal, status, failure_reason
                FROM research_batches.task_attempts
                WHERE batch_id = %s AND task_role = 'shared_alpha_factor'
                """,
                (admitted["id"],),
            ).fetchall()
            artifact_count = transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_batches.private_alpha_factor_artifacts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone()
        assert attempts == [
            {
                "ordinal": 1,
                "status": "failed",
                "failure_reason": "PermanentExecutionFailure",
            }
        ]
        assert artifact_count == {"count": 0}
        assert processor.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_expired_strategy_fence_rejects_private_artifact_before_acknowledgement(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-stale-private-artifact-fence"),
        ).json()
        runtime = client.app.state.core_runtime
        barrier = _SharedArtifactReadyBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            )
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=barrier,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(processor.process_next)
            assert barrier.ready.wait(timeout=30)
            attempt_id = client.get(f"/api/research-batches/{admitted['id']}").json()["attempt"][
                "id"
            ]
            active_artifact = (
                settings.batch_attempt_control_directory / f"{attempt_id}.alpha-factor.artifact"
            )
            assert active_artifact.is_file()
            aged_at = (datetime.now(UTC) - timedelta(days=1)).timestamp()
            os.utime(active_artifact, (aged_at, aged_at))
            assert processor.reconcile_attempt_files() == 0
            assert active_artifact.is_file()
            _expire_batch_attempt(runtime, attempt_id)
            barrier.release.set()
            assert future.result(timeout=60) is True

        fenced = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert fenced["status"] == "running"
        assert fenced["progress"]["shared_alpha_factor_status"] == "running"
        assert _pin_status_for_attempt(runtime, attempt_id) == "active"
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_batches.private_alpha_factor_artifacts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone() == {"count": 0}

        recovered_events: list[dict[str, object]] = []
        assert processor.process_next(on_execution_event=recovered_events.append) is True
        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert any(
            event.get("event") == "research_batch_execution_shared_alpha_factor_succeeded"
            and event.get("private_artifact_reused") is False
            for event in recovered_events
        )
        assert _lost_attempt_evidence(runtime, [attempt_id]) == [("failed", "WorkerLost")]
        orphan = (
            settings.batch_attempt_control_directory / "batch_attempt_orphan.alpha-factor.artifact"
        )
        orphan.write_bytes(b"unchecked orphan attempt bytes")
        os.utime(orphan, (aged_at, aged_at))
        assert processor.reconcile_attempt_files() == 1
        assert not orphan.exists()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_three_shared_worker_losses_fail_every_strategy_dependency(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)

    def lose_shared_worker(event: dict[str, object]) -> None:
        if event.get("event") == ("research_batch_execution_shared_alpha_factor_succeeded"):
            raise ResearchBatchChildLost("injected shared Worker loss")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-shared-retry-exhaustion"),
        ).json()
        runtime = client.app.state.core_runtime

        for expected_attempt in range(1, 4):
            assert (
                runtime.research_batches.process_next(on_execution_event=lose_shared_worker) is True
            )
            detail = client.get(f"/api/research-batches/{admitted['id']}").json()
            if expected_attempt < 3:
                assert detail["status"] == "queued"
                assert detail["progress"]["shared_alpha_factor_status"] == "pending"

        failed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert failed["status"] == "failed"
        assert failed["progress"]["shared_alpha_factor_status"] == "failed"
        assert all(item["outcome"] == "failed" for item in failed["items"])
        with runtime.database.transaction() as transaction:
            attempts = transaction.execute(
                """
                SELECT ordinal, status
                FROM research_batches.task_attempts
                WHERE batch_id = %s AND task_role = 'shared_alpha_factor'
                ORDER BY ordinal
                """,
                (admitted["id"],),
            ).fetchall()
        assert attempts == [
            {"ordinal": 1, "status": "failed"},
            {"ordinal": 2, "status": "failed"},
            {"ordinal": 3, "status": "failed"},
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_recovery_rejects_a_corrupt_private_artifact_binding(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    interrupted = False

    def interrupt_second_strategy(event: dict[str, object]) -> None:
        nonlocal interrupted
        if (
            not interrupted
            and event.get("event") == "research_batch_execution_item_started"
            and event.get("item_ordinal") == 2
        ):
            interrupted = True
            raise ResearchBatchChildLost("injected Worker loss before artifact corruption")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-corrupt-private-artifact"),
        ).json()
        runtime = client.app.state.core_runtime
        assert (
            runtime.research_batches.process_next(on_execution_event=interrupt_second_strategy)
            is True
        )
        interrupted_detail = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert interrupted_detail["progress"]["completed_strategy_tasks"] == 1
        with runtime.database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE research_batches.private_alpha_factor_artifacts
                SET binding = jsonb_set(binding, '{universe}', '"top3000"'::jsonb)
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            )

        assert runtime.research_batches.process_next() is True
        failed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert failed["status"] == "completed_with_failures"
        assert [item["outcome"] for item in failed["items"]] == ["succeeded", "failed"]
        assert failed["items"][1]["diagnostic"]["code"] == (
            "PRIVATE_ALPHA_FACTOR_ARTIFACT_REJECTED"
        )
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_batches.private_alpha_factor_artifacts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone() == {"count": 0}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "invalid_case",
    ["missing_object", "corrupt_bytes", "obsolete_contract", "cross_batch"],
)
def test_recovery_rejects_every_invalid_private_artifact_case(
    tmp_path: Path,
    invalid_case: str,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    interrupted = False

    def interrupt_second_strategy(event: dict[str, object]) -> None:
        nonlocal interrupted
        if (
            not interrupted
            and event.get("event") == "research_batch_execution_item_started"
            and event.get("item_ordinal") == 2
        ):
            interrupted = True
            raise ResearchBatchChildLost("injected Worker loss before invalid artifact recovery")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command(f"strategy-invalid-artifact-{invalid_case}"),
        ).json()
        runtime = client.app.state.core_runtime
        assert (
            runtime.research_batches.process_next(on_execution_event=interrupt_second_strategy)
            is True
        )
        with runtime.database.transaction() as transaction:
            artifact = transaction.execute(
                """
                SELECT content_sha256, binding
                FROM research_batches.private_alpha_factor_artifacts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone()
        assert artifact is not None
        if invalid_case in {"missing_object", "corrupt_bytes"}:
            digest = str(artifact["content_sha256"])
            key = f"publication/v1/sha256/{digest[:2]}/{digest}"
            rustfs_admin = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                region_name=settings.s3_region,
            )
            try:
                if invalid_case == "missing_object":
                    rustfs_admin.delete_object(Bucket=settings.s3_bucket, Key=key)
                else:
                    rustfs_admin.put_object(
                        Bucket=settings.s3_bucket,
                        Key=key,
                        Body=b"corrupt private artifact bytes",
                    )
            finally:
                rustfs_admin.close()
        elif invalid_case == "obsolete_contract":
            _replace_private_artifact(
                runtime,
                admitted["id"],
                kernel_semantic_version="kernel-obsolete",
            )
            with runtime.database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE research_runs.runs
                    SET immutable_input = jsonb_set(
                        immutable_input,
                        '{semantic_versions,kernel}',
                        '"kernel-obsolete"'::jsonb
                    )
                    WHERE id IN (
                        SELECT research_run_id
                        FROM research_batches.items
                        WHERE batch_id = %s
                    )
                    """,
                    (admitted["id"],),
                )
        else:
            _replace_private_artifact(
                runtime,
                admitted["id"],
                artifact_batch_id="batch_foreign_owner",
            )

        assert runtime.research_batches.process_next() is True
        rejected = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert rejected["status"] == "completed_with_failures"
        assert [item["outcome"] for item in rejected["items"]] == ["succeeded", "failed"]
        assert rejected["items"][1]["diagnostic"]["code"] == (
            "PRIVATE_ALPHA_FACTOR_ARTIFACT_REJECTED"
        )
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_batches.private_alpha_factor_artifacts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone() == {"count": 0}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_three_strategy_worker_losses_fail_only_that_strategy_and_continue(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)

    def lose_first_strategy_worker(event: dict[str, object]) -> None:
        if (
            event.get("event") == "research_batch_execution_item_started"
            and event.get("item_ordinal") == 1
        ):
            raise ResearchBatchChildLost("injected Strategy task Worker loss")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-item-retry-exhaustion"),
        ).json()
        runtime = client.app.state.core_runtime

        for _ in range(3):
            assert (
                runtime.research_batches.process_next(on_execution_event=lose_first_strategy_worker)
                is True
            )
        interrupted = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert interrupted["status"] == "queued"
        assert [item["outcome"] for item in interrupted["items"]] == ["failed", None]
        assert [item["task_attempt_count"] for item in interrupted["items"]] == [3, 0]

        assert runtime.research_batches.process_next() is True
        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "completed_with_failures"
        assert [item["outcome"] for item in completed["items"]] == [
            "failed",
            "succeeded",
        ]
        assert [item["task_attempt_count"] for item in completed["items"]] == [3, 1]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_resource_exhaustion_is_not_retried_and_other_items_continue(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    exhausted = False

    def exhaust_first_strategy(event: dict[str, object]) -> None:
        nonlocal exhausted
        if (
            not exhausted
            and event.get("event") == "research_batch_execution_item_started"
            and event.get("item_ordinal") == 1
        ):
            exhausted = True
            raise ResearchExecutionResourceExhausted("injected Strategy memory breach")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-resource-exhausted-no-retry"),
        ).json()
        runtime = client.app.state.core_runtime

        assert (
            runtime.research_batches.process_next(on_execution_event=exhaust_first_strategy) is True
        )
        interrupted = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert interrupted["status"] == "queued"
        assert [item["outcome"] for item in interrupted["items"]] == ["failed", None]
        assert interrupted["items"][0]["diagnostic"] == {
            "code": "RESEARCH_BATCH_RESOURCE_EXHAUSTED",
            "category": "resource_exhausted",
            "message": "Research Batch execution exceeded its resource limit.",
        }
        assert [item["task_attempt_count"] for item in interrupted["items"]] == [1, 0]

        assert runtime.research_batches.process_next() is True
        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "completed_with_failures"
        assert [item["outcome"] for item in completed["items"]] == [
            "failed",
            "succeeded",
        ]
        assert [item["task_attempt_count"] for item in completed["items"]] == [1, 1]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_shared_failure_fails_all_dependants_before_strategy(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("strategy-sweep-shared-failure"),
        ).json()
        _replace_item_json(settings, admitted["id"], 1, "field_bindings", {})

        assert (
            client.app.state.core_runtime.research_batches.process_next(
                on_execution_event=events.append
            )
            is True
        )

        failed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert failed["status"] == "failed"
        assert failed["progress"]["shared_alpha_factor_status"] == "failed"
        assert [item["status"] for item in failed["items"]] == ["failed", "failed"]
        assert all(item["outcome"] == "failed" for item in failed["items"])
        assert all(
            item["diagnostic"]
            == {
                "code": "RESEARCH_ITEM_CALCULATION_FAILED",
                "category": "calculation",
                "message": "Shared Alpha-and-Factor calculation failed.",
            }
            for item in failed["items"]
        )
        assert all(
            client.get(f"/api/research-runs/{item['research_run_id']}").json()["failure_reason"]
            == "Research calculation failed."
            for item in failed["items"]
        )

    shared_failure = next(
        event
        for event in events
        if event["event"] == "research_batch_execution_shared_alpha_factor_failed"
    )
    assert shared_failure["alpha_factor_task_failed"] is True
    assert shared_failure["strategy_task_started"] is False
    assert not any(event.get("strategy_task_started") is True for event in events)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_isolates_one_strategy_failure_and_keeps_order(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _strategy_command("strategy-sweep-item-failure")
        admitted = client.post(
            "/api/research-batches",
            json={
                **command,
                "strategies": [
                    command["strategies"][0],
                    command["strategies"][1],
                    {
                        "item_key": "later",
                        "holdings_count": 3,
                        "rebalance_every_sessions": 1,
                    },
                ],
            },
        ).json()
        _replace_nested_strategy_holdings(settings, admitted["id"], 2, 0)

        assert (
            client.app.state.core_runtime.research_batches.process_next(
                on_execution_event=events.append
            )
            is True
        )

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "completed_with_failures"
        assert [item["status"] for item in completed["items"]] == [
            "succeeded",
            "failed",
            "succeeded",
        ]
        assert [item["outcome"] for item in completed["items"]] == [
            "succeeded",
            "failed",
            "succeeded",
        ]
        assert (
            client.get(f"/api/research-runs/{completed['items'][2]['research_run_id']}").json()[
                "result"
            ]
            is not None
        )

    item_events = [
        event
        for event in events
        if event["event"]
        in {
            "research_batch_execution_item_succeeded",
            "research_batch_execution_item_failed",
        }
    ]
    assert [event["item_ordinal"] for event in item_events] == [1, 2, 3]
    assert item_events[1]["strategy_task_failed"] is True
    assert item_events[2]["strategy_task_completed"] is True


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize("item_count", [1, 20])
def test_strategy_sweep_one_and_twenty_items_use_the_same_ordered_contract(
    tmp_path: Path,
    item_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the batch capacity contract with an Operator, whose daily Run quota is unlimited.
    monkeypatch.setattr(
        "thesistrace.entrypoints.runtime.quota_policy_lookup",
        lambda _origin: lambda _researcher_id: QuotaPolicy(
            timezone="Asia/Shanghai", daily_model_budget_nanodollars=None,
            daily_run_limit=None, active_daily_track_limit=None,
        ),
    )
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _strategy_command(f"strategy-sweep-{item_count}")
        strategies = [
            {
                "item_key": f"strategy-{ordinal}",
                "holdings_count": ordinal,
                "rebalance_every_sessions": ordinal,
            }
            for ordinal in range(1, item_count + 1)
        ]
        admitted = client.post(
            "/api/research-batches",
            json={**command, "strategies": strategies},
        ).json()

        assert (
            client.app.state.core_runtime.research_batches.process_next(
                on_execution_event=events.append
            )
            is True
        )

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["progress"] == {
            "shared_alpha_factor_status": "succeeded",
            "completed_strategy_tasks": item_count,
            "total_strategy_tasks": item_count,
        }
        assert [item["item_key"] for item in completed["items"]] == [
            strategy["item_key"] for strategy in strategies
        ]

    shared_events = [
        event
        for event in events
        if event["event"] == "research_batch_execution_shared_alpha_factor_succeeded"
    ]
    strategy_events = [
        event for event in events if event["event"] == "research_batch_execution_item_succeeded"
    ]
    assert len(shared_events) == 1
    assert [event["item_ordinal"] for event in strategy_events] == list(range(1, item_count + 1))
    assert all(event["alpha_factor_task_started"] is False for event in strategy_events)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_long_strategy_sweep_preserves_ordinary_result_partitions_and_equivalence(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    sessions = _business_sessions(505, ending=date(2026, 8, 4))
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings, sessions=sessions)
        command = _strategy_command("strategy-sweep-long-result")
        command = {
            **command,
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "strategies": [command["strategies"][0]],
        }
        batch = client.post("/api/research-batches", json=command).json()
        ordinary = client.post(
            "/api/research-runs",
            json=_ordinary_strategy_command(
                "ordinary-strategy-long-result",
                holdings_count=1,
                rebalance_every_sessions=1,
                start_date=sessions[0],
                end_date=sessions[-1],
            ),
        ).json()
        runtime = client.app.state.core_runtime

        assert runtime.research_runs.process_next() is True
        assert runtime.research_batches.process_next() is True

        completed = client.get(f"/api/research-batches/{batch['id']}").json()
        assert completed["status"] == "succeeded"
        batch_stored = _stored_run(
            settings,
            str(completed["items"][0]["research_run_id"]),
        )
        ordinary_stored = _stored_run(settings, str(ordinary["id"]))
        batch_result = _stored_result(runtime, batch_stored)
        ordinary_result = _stored_result(runtime, ordinary_stored)
        assert len(batch_result["strategy_daily_observations"]) == 505
        assert canonical_json_bytes(batch_result) == canonical_json_bytes(ordinary_result)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_long_history_multi_chunk_strategy_sweep_stays_inside_memory_budget(
    tmp_path: Path,
) -> None:
    _assert_strategy_capacity_is_bounded_by_chunk(
        tmp_path,
        case="wide",
        memory_bytes=300 * 1024**2,
        sessions=_business_sessions(324, ending=date(2026, 8, 4)),
        instrument_count=512,
        formula="close",
    )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_high_work_strategy_sweep_selects_a_bounded_chunk(
    tmp_path: Path,
) -> None:
    formula = " + ".join("ts_mean(close, 252)" for _ in range(16))
    _assert_strategy_capacity_is_bounded_by_chunk(
        tmp_path,
        case="high-work",
        memory_bytes=512 * 1024**2,
        sessions=_business_sessions(400, ending=date(2026, 8, 4)),
        instrument_count=512,
        formula=formula,
    )


def _assert_strategy_capacity_is_bounded_by_chunk(
    tmp_path: Path,
    *,
    case: str,
    memory_bytes: int,
    sessions: tuple[str, ...],
    instrument_count: int,
    formula: str,
) -> None:
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path,
        research_execution_memory_bytes=memory_bytes,
    )
    drop_product_schemas(settings)
    events: list[dict[str, object]] = []
    with TestClient(create_app(settings)) as client:
        _publish_current_data(
            settings,
            operation_id=f"strategy-sweep-{case}-widest-admitted",
            sessions=sessions,
            instrument_count=instrument_count,
        )
        command = _strategy_command(f"strategy-sweep-{case}-widest-admitted")
        runtime = client.app.state.core_runtime
        dataset = runtime.research_runs.current_admission_dataset()
        assert dataset is not None
        effective_lookback = alpha_language.compile(formula).effective_lookback
        full = runtime.research_runs.prepare_child_admission(
            TEST_RESEARCHER.researcher_id,
            StrategyBacktestAdmissionCommand.model_validate(
                {
                    **_ordinary_strategy_command(
                        "capacity-probe-full",
                        holdings_count=1,
                        rebalance_every_sessions=1,
                        start_date=sessions[effective_lookback],
                        end_date=sessions[-1],
                        formula=formula,
                    ),
                    "universe": "top1000",
                }
            ),
            dataset=dataset,
        )
        # Both periods must already fill one Chunk plus the bounded 21-session
        # Alpha continuation. Otherwise the shorter case legitimately needs a
        # smaller streamed artifact frame and is not a total-history comparison.
        short_start_index = max(effective_lookback, len(sessions) - 100)
        short = runtime.research_runs.prepare_child_admission(
            TEST_RESEARCHER.researcher_id,
            StrategyBacktestAdmissionCommand.model_validate(
                {
                    **_ordinary_strategy_command(
                        "capacity-probe-short",
                        holdings_count=1,
                        rebalance_every_sessions=1,
                        start_date=sessions[short_start_index],
                        end_date=sessions[-1],
                        formula=formula,
                    ),
                    "universe": "top1000",
                }
            ),
            dataset=dataset,
        )
        full_capacity = validate_research_batch_capacity(
            "strategy_sweep",
            [full],
            research_calendar=dataset.research_sessions,
            universe_member_union_cardinalities=(dataset.universe_member_union_cardinalities),
        )
        short_capacity = validate_research_batch_capacity(
            "strategy_sweep",
            [short],
            research_calendar=dataset.research_sessions,
            universe_member_union_cardinalities=(dataset.universe_member_union_cardinalities),
        )
        assert full_capacity.session_count == short_capacity.session_count
        assert full_capacity.estimated_peak_bytes == short_capacity.estimated_peak_bytes
        assert full_capacity.estimated_peak_bytes <= memory_bytes
        command = {
            **command,
            "start_date": sessions[effective_lookback],
            "end_date": sessions[-1],
            "universe": "top1000",
            "alpha": {"formula": formula, "hypothesis": "bounded capacity"},
            "strategies": [command["strategies"][0]],
        }
        admitted = client.post("/api/research-batches", json=command)
        assert admitted.status_code == 202

        assert (
            client.app.state.core_runtime.research_batches.process_next(
                on_execution_event=events.append
            )
            is True
        )
        completed = client.get(f"/api/research-batches/{admitted.json()['id']}").json()
        assert completed["status"] == "succeeded", {
            "item_diagnostics": [item["diagnostic"] for item in completed["items"]],
            "failure_events": [
                {
                    key: event[key]
                    for key in (
                        "event",
                        "error_type",
                        "message",
                        "shared_artifact_bytes",
                        "shared_artifact_capacity_bytes",
                    )
                    if key in event
                }
                for event in events
                if event["event"].endswith("_failed")
            ],
        }

    shared = next(
        event
        for event in events
        if event["event"] == "research_batch_execution_shared_alpha_factor_succeeded"
    )
    assert int(shared["shared_chunk_count"]) > 1
    assert int(shared["shared_artifact_bytes"]) <= int(shared["shared_artifact_capacity_bytes"])
    assert (
        max(
            int(event["child_peak_rss_bytes"])
            for event in events
            if "child_peak_rss_bytes" in event
        )
        <= memory_bytes
    )


def _ordinary_strategy_command(
    request_id: str,
    *,
    holdings_count: int,
    rebalance_every_sessions: int,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-04",
    formula: str = "close",
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": request_id,
        "start_date": start_date,
        "end_date": end_date,
        "formula": formula,
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "strategy_backtest",
        "holdings_count": holdings_count,
        "rebalance_every_sessions": rebalance_every_sessions,
    }


def _business_sessions(count: int, *, ending: date) -> tuple[str, ...]:
    sessions: list[str] = []
    current = ending
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current -= timedelta(days=1)
    return tuple(reversed(sessions))


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT result_manifest_sha256, result_provenance, key_metrics
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        database.close()


def _stored_result(runtime, stored: dict[str, object]) -> dict[str, object]:
    bundle = runtime.publication.read(
        PublishedRef(
            manifest_sha256=str(stored["result_manifest_sha256"]),
            kind="research.result",
            provenance=stored["result_provenance"],
        )
    )
    return read_result_bundle(bundle, research_kind="strategy_backtest")


def _replace_item_json(
    settings: CoreSettings,
    batch_id: str,
    ordinal: int,
    field: str,
    value: object,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.runs AS run
                SET immutable_input = jsonb_set(
                    run.immutable_input,
                    ARRAY[%s]::text[],
                    %s::jsonb
                )
                FROM research_batches.items AS item
                WHERE item.batch_id = %s AND item.ordinal = %s
                  AND run.id = item.research_run_id
                """,
                (field, canonical_json_bytes(value).decode(), batch_id, ordinal),
            )
        assert updated.rowcount == 1
    finally:
        database.close()


def _replace_nested_strategy_holdings(
    settings: CoreSettings,
    batch_id: str,
    ordinal: int,
    holdings_count: int,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.runs AS run
                SET immutable_input = jsonb_set(
                    run.immutable_input,
                    '{strategy,holdings_count}',
                    to_jsonb(%s::integer)
                )
                FROM research_batches.items AS item
                WHERE item.batch_id = %s AND item.ordinal = %s
                  AND run.id = item.research_run_id
                """,
                (holdings_count, batch_id, ordinal),
            )
        assert updated.rowcount == 1
    finally:
        database.close()

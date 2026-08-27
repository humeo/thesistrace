from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import boto3
from botocore.config import Config

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.benchmark import (
    AnnualizedExcessCalculator,
    BenchmarkSnapshotStore,
    RemoteAnnualizedExcessCalculator,
    StrategyComparisonService,
    validate_independent_benchmark_mount,
)
from thesistrace.daily_track import DailyTrackService, SessionCoordinateRepository
from thesistrace.daily_track.planning import DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES
from thesistrace.data import (
    DatasetAdmissionService,
    DatasetLifecycle,
    DatasetOverviewService,
    MountedGenerationStore,
)
from thesistrace.entrypoints.readiness import CoreReadiness
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.operational_events import emit_operational_event_data
from thesistrace.publication import Publication
from thesistrace.research_authoring import ResearchAuthoringService
from thesistrace.research_batch import ResearchBatchService, preserve_deleted_run_history
from thesistrace.research_batch.execution import SupervisedResearchBatchExecutor
from thesistrace.research_folder import ResearchFolderService
from thesistrace.research_run import (
    ResearchRunService,
    research_result_manifest_is_referenced,
    research_run_exists,
)
from thesistrace.research_run.execution import SupervisedResearchExecutor
from thesistrace.research_run.planning import DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES
from thesistrace.research_run.result import read_result_bundle, read_semantic_result_section

CORE_ENVIRONMENT_NAMES = (
    "THESISTRACE_DATABASE_URL",
    "THESISTRACE_S3_ENDPOINT_URL",
    "THESISTRACE_S3_ACCESS_KEY_ID",
    "THESISTRACE_S3_SECRET_ACCESS_KEY",
    "THESISTRACE_S3_BUCKET",
    "THESISTRACE_DATA_MOUNT",
    "THESISTRACE_BENCHMARK_MOUNT",
    "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY",
)
PUBLICATION_REQUEST_TIMEOUT_SECONDS = 5.0


def publication_request_config() -> Config:
    return Config(
        connect_timeout=PUBLICATION_REQUEST_TIMEOUT_SECONDS,
        read_timeout=PUBLICATION_REQUEST_TIMEOUT_SECONDS,
        retries={"total_max_attempts": 1, "mode": "standard"},
    )


@dataclass(frozen=True)
class CoreSettings:
    database_url: str
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket: str
    data_mount: Path
    benchmark_mount: Path
    batch_attempt_control_directory: Path
    s3_region: str = "us-east-1"
    research_execution_memory_bytes: int = DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES
    tracking_execution_memory_bytes: int = DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES

    @classmethod
    def from_environment(cls) -> CoreSettings:
        names = {
            "database_url": "THESISTRACE_DATABASE_URL",
            "s3_endpoint_url": "THESISTRACE_S3_ENDPOINT_URL",
            "s3_access_key_id": "THESISTRACE_S3_ACCESS_KEY_ID",
            "s3_secret_access_key": "THESISTRACE_S3_SECRET_ACCESS_KEY",
            "s3_bucket": "THESISTRACE_S3_BUCKET",
            "data_mount": "THESISTRACE_DATA_MOUNT",
            "benchmark_mount": "THESISTRACE_BENCHMARK_MOUNT",
            "batch_attempt_control_directory": (
                "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY"
            ),
        }
        values: dict[str, str] = {}
        missing: list[str] = []
        for field, name in names.items():
            value = os.environ.get(name, "").strip()
            if value:
                values[field] = value
            else:
                missing.append(name)
        if missing:
            raise RuntimeError(f"missing Core configuration: {', '.join(missing)}")
        research_execution_memory_bytes = int(
            os.environ.get(
                "THESISTRACE_RESEARCH_WORKER_EXECUTION_MEMORY_BYTES",
                str(DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES),
            )
        )
        if research_execution_memory_bytes <= 0:
            raise RuntimeError("Research execution memory must be positive")
        tracking_execution_memory_bytes = int(
            os.environ.get(
                "THESISTRACE_TRACKING_WORKER_EXECUTION_MEMORY_BYTES",
                str(DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES),
            )
        )
        if tracking_execution_memory_bytes <= 0:
            raise RuntimeError("Tracking execution memory must be positive")
        data_mount = Path(values["data_mount"])
        try:
            benchmark_mount = validate_independent_benchmark_mount(
                data_mount,
                values["benchmark_mount"],
            )
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        batch_attempt_control_directory = Path(
            values["batch_attempt_control_directory"]
        )
        if batch_attempt_control_directory.resolve().is_relative_to(
            data_mount.resolve()
        ):
            raise RuntimeError(
                "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY must be outside THESISTRACE_DATA_MOUNT"
            )
        return cls(
            database_url=values["database_url"],
            s3_endpoint_url=values["s3_endpoint_url"],
            s3_access_key_id=values["s3_access_key_id"],
            s3_secret_access_key=values["s3_secret_access_key"],
            s3_bucket=values["s3_bucket"],
            data_mount=data_mount,
            benchmark_mount=benchmark_mount,
            batch_attempt_control_directory=batch_attempt_control_directory,
            s3_region=os.environ.get("THESISTRACE_S3_REGION", "us-east-1"),
            research_execution_memory_bytes=research_execution_memory_bytes,
            tracking_execution_memory_bytes=tracking_execution_memory_bytes,
        )


def core_environment_is_configured(
    environment: Mapping[str, str] | None = None,
) -> bool:
    selected = os.environ if environment is None else environment
    return all(selected.get(name, "").strip() for name in CORE_ENVIRONMENT_NAMES)


@dataclass(frozen=True)
class CoreRuntime:
    database: PostgresDatabase
    data_overview: DatasetOverviewService | None
    research_authoring: ResearchAuthoringService
    research_folders: ResearchFolderService
    research_batches: ResearchBatchService
    research_runs: ResearchRunService
    daily_tracks: DailyTrackService
    daily_track_sessions: SessionCoordinateRepository
    publication: Publication
    readiness: CoreReadiness
    annualized_excess_calculator: AnnualizedExcessCalculator


@contextmanager
def open_core_runtime(settings: CoreSettings) -> Iterator[CoreRuntime]:
    comparison = StrategyComparisonService(BenchmarkSnapshotStore(settings.benchmark_mount))
    with _open_runtime(
        settings,
        annualized_excess_calculator=comparison,
        strategy_comparison=comparison,
        include_data_overview=True,
    ) as runtime:
        yield runtime


@contextmanager
def open_worker_runtime(
    settings: CoreSettings,
    *,
    internal_api_origin: str,
) -> Iterator[CoreRuntime]:
    with _open_runtime(
        settings,
        annualized_excess_calculator=RemoteAnnualizedExcessCalculator(
            internal_api_origin
        ),
        strategy_comparison=None,
        include_data_overview=False,
    ) as runtime:
        yield runtime


@contextmanager
def _open_runtime(
    settings: CoreSettings,
    *,
    annualized_excess_calculator: AnnualizedExcessCalculator,
    strategy_comparison: StrategyComparisonService | None,
    include_data_overview: bool,
) -> Iterator[CoreRuntime]:
    working_cache = TemporaryDirectory(prefix="thesistrace-core-working-cache-")
    database = PostgresDatabase(settings.database_url)
    try:
        database.open()
        verify_core_schema(database)
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=publication_request_config(),
        )
        s3.list_buckets()
        publication = Publication(database, s3, bucket=settings.s3_bucket)
        dataset_admission = DatasetAdmissionService(database, settings.data_mount)
        dataset_lifecycle = DatasetLifecycle(database, settings.data_mount)
        dataset_lifecycle.current_pointer()
        data_overview: DatasetOverviewService | None = None
        if include_data_overview:
            data_overview = DatasetOverviewService(
                database,
                settings.data_mount,
                settings.benchmark_mount,
            )
            data_overview.validate_startup()
        generation_store = MountedGenerationStore(settings.data_mount)
        daily_tracks = DailyTrackService(
            database,
            publication=publication,
            dataset_lifecycle=dataset_lifecycle,
            generation_store=generation_store,
            read_result_bundle=partial(
                read_result_bundle,
                research_kind="strategy_backtest",
            ),
            read_semantic_result_section=read_semantic_result_section,
            working_cache_root=Path(working_cache.name) / "daily-tracks",
            seed_research_exists=research_run_exists,
            research_references_result=research_result_manifest_is_referenced,
            execution_memory_bytes=settings.tracking_execution_memory_bytes,
            lifecycle_event=emit_operational_event_data,
            strategy_comparison=strategy_comparison,
        )
        research_runs = ResearchRunService(
            database,
            dataset_lifecycle=dataset_lifecycle,
            generation_store=generation_store,
            publication=publication,
            activate_track=daily_tracks.activate,
            compile_formula=alpha_language.compile,
            current_dataset=dataset_admission.current,
            track_references_result=daily_tracks.references_result_manifest,
            preserve_dependent_run_history=preserve_deleted_run_history,
            execution=SupervisedResearchExecutor(
                settings.data_mount,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            ),
            execution_memory_bytes=settings.research_execution_memory_bytes,
            lifecycle_event=emit_operational_event_data,
            annualized_excess_calculator=annualized_excess_calculator,
            strategy_comparison=strategy_comparison,
        )
        research_batches = ResearchBatchService(
            database,
            research_runs=research_runs,
            dataset_lifecycle=dataset_lifecycle,
            publication=publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            ),
        )
        yield CoreRuntime(
            database=database,
            data_overview=data_overview,
            research_authoring=ResearchAuthoringService(),
            research_folders=ResearchFolderService(database),
            research_batches=research_batches,
            research_runs=research_runs,
            daily_tracks=daily_tracks,
            daily_track_sessions=SessionCoordinateRepository(database),
            publication=publication,
            readiness=CoreReadiness(
                database_url=settings.database_url,
                s3_endpoint_url=settings.s3_endpoint_url,
                s3_access_key_id=settings.s3_access_key_id,
                s3_secret_access_key=settings.s3_secret_access_key,
                s3_bucket=settings.s3_bucket,
                s3_region=settings.s3_region,
                data_mount=settings.data_mount,
            ),
            annualized_excess_calculator=annualized_excess_calculator,
        )
    finally:
        database.close()
        working_cache.cleanup()

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
from thesistrace.daily_track import DailyTrackService, SessionCoordinateRepository
from thesistrace.daily_track.planning import DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES
from thesistrace.data import (
    DatasetAdmissionService,
    DatasetLifecycle,
    DatasetOverviewService,
    MountedGenerationStore,
)
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.publication import Publication
from thesistrace.research_batch import ResearchBatchService
from thesistrace.research_folder import ResearchFolderService
from thesistrace.research_run import (
    ResearchRunService,
    research_result_manifest_is_referenced,
    research_run_exists,
)
from thesistrace.research_run.execution import SupervisedResearchExecutor
from thesistrace.research_run.planning import DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES
from thesistrace.research_run.result import read_result_bundle

CORE_ENVIRONMENT_NAMES = (
    "THESISTRACE_DATABASE_URL",
    "THESISTRACE_S3_ENDPOINT_URL",
    "THESISTRACE_S3_ACCESS_KEY_ID",
    "THESISTRACE_S3_SECRET_ACCESS_KEY",
    "THESISTRACE_S3_BUCKET",
    "THESISTRACE_DATA_MOUNT",
)
PUBLICATION_REQUEST_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class CoreSettings:
    database_url: str
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket: str
    data_mount: Path
    s3_region: str = "us-east-1"
    research_execution_memory_bytes: int = DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES
    tracking_execution_memory_bytes: int = DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES

    @classmethod
    def from_environment(cls) -> CoreSettings:
        names = dict(
            zip(
                (
                    "database_url",
                    "s3_endpoint_url",
                    "s3_access_key_id",
                    "s3_secret_access_key",
                    "s3_bucket",
                    "data_mount",
                ),
                CORE_ENVIRONMENT_NAMES,
                strict=True,
            )
        )
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
        return cls(
            database_url=values["database_url"],
            s3_endpoint_url=values["s3_endpoint_url"],
            s3_access_key_id=values["s3_access_key_id"],
            s3_secret_access_key=values["s3_secret_access_key"],
            s3_bucket=values["s3_bucket"],
            data_mount=Path(values["data_mount"]),
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
    data_overview: DatasetOverviewService
    research_folders: ResearchFolderService
    research_batches: ResearchBatchService
    research_runs: ResearchRunService
    daily_tracks: DailyTrackService
    daily_track_sessions: SessionCoordinateRepository
    publication: Publication


@contextmanager
def open_core_runtime(settings: CoreSettings) -> Iterator[CoreRuntime]:
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
            config=Config(
                connect_timeout=PUBLICATION_REQUEST_TIMEOUT_SECONDS,
                read_timeout=PUBLICATION_REQUEST_TIMEOUT_SECONDS,
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        )
        s3.list_buckets()
        publication = Publication(database, s3, bucket=settings.s3_bucket)
        data_overview = DatasetOverviewService(database, settings.data_mount)
        data_overview.validate_startup()
        dataset_admission = DatasetAdmissionService(database, settings.data_mount)
        dataset_lifecycle = DatasetLifecycle(database, settings.data_mount)
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
            working_cache_root=Path(working_cache.name) / "daily-tracks",
            seed_research_exists=research_run_exists,
            research_references_result=research_result_manifest_is_referenced,
            execution_memory_bytes=settings.tracking_execution_memory_bytes,
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
            execution=SupervisedResearchExecutor(
                settings.data_mount,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            ),
            execution_memory_bytes=settings.research_execution_memory_bytes,
        )
        research_batches = ResearchBatchService(
            database,
            research_runs=research_runs,
            dataset_lifecycle=dataset_lifecycle,
        )
        yield CoreRuntime(
            database=database,
            data_overview=data_overview,
            research_folders=ResearchFolderService(database),
            research_batches=research_batches,
            research_runs=research_runs,
            daily_tracks=daily_tracks,
            daily_track_sessions=SessionCoordinateRepository(database),
            publication=publication,
        )
    finally:
        database.close()
        working_cache.cleanup()

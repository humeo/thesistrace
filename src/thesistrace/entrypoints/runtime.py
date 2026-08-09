from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import boto3

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import DailyTrackService
from thesistrace.data import DataService, DatasetOverviewService, authorable_field_bindings
from thesistrace.definition import DefinitionService
from thesistrace.entrypoints.migrations import verify_core_migrations
from thesistrace.publication import Publication
from thesistrace.research_kernel import operator_catalog
from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.result import read_result_bundle

CORE_ENVIRONMENT_NAMES = (
    "THESISTRACE_DATABASE_URL",
    "THESISTRACE_S3_ENDPOINT_URL",
    "THESISTRACE_S3_ACCESS_KEY_ID",
    "THESISTRACE_S3_SECRET_ACCESS_KEY",
    "THESISTRACE_S3_BUCKET",
    "THESISTRACE_DATA_MOUNT",
)


@dataclass(frozen=True)
class CoreSettings:
    database_url: str
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket: str
    data_mount: Path
    s3_region: str = "us-east-1"

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
        return cls(
            database_url=values["database_url"],
            s3_endpoint_url=values["s3_endpoint_url"],
            s3_access_key_id=values["s3_access_key_id"],
            s3_secret_access_key=values["s3_secret_access_key"],
            s3_bucket=values["s3_bucket"],
            data_mount=Path(values["data_mount"]),
            s3_region=os.environ.get("THESISTRACE_S3_REGION", "us-east-1"),
        )


def core_environment_is_configured(
    environment: Mapping[str, str] | None = None,
) -> bool:
    selected = os.environ if environment is None else environment
    return all(selected.get(name, "").strip() for name in CORE_ENVIRONMENT_NAMES)


@dataclass(frozen=True)
class CoreRuntime:
    database: PostgresDatabase
    data: DataService
    data_overview: DatasetOverviewService
    definitions: DefinitionService
    research_runs: ResearchRunService
    daily_tracks: DailyTrackService
    publication: Publication


@contextmanager
def open_core_runtime(settings: CoreSettings) -> Iterator[CoreRuntime]:
    working_cache = TemporaryDirectory(prefix="thesistrace-core-working-cache-")
    database = PostgresDatabase(settings.database_url)
    try:
        database.open()
        verify_core_migrations(database)
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )
        s3.list_buckets()
        publication = Publication(database, s3, bucket=settings.s3_bucket)
        data = DataService(database, publication)
        data_overview = DatasetOverviewService(database, settings.data_mount)
        data_overview.validate_startup()
        validate_alpha = partial(
            validate_normalized_alpha,
            field_bindings=authorable_field_bindings(),
        )
        daily_tracks = DailyTrackService(
            database,
            publication=publication,
            next_release=data.next_release,
            load_canonical=data.load_canonical,
            read_result_bundle=read_result_bundle,
            working_cache_root=Path(working_cache.name) / "daily-tracks",
        )
        research_runs = ResearchRunService(
            database,
            load_canonical=data.load_canonical,
            publication=publication,
            activate_track=daily_tracks.activate,
        )
        yield CoreRuntime(
            database=database,
            data=data,
            data_overview=data_overview,
            definitions=DefinitionService(
                database,
                authorable_fields=data.authorable_fields,
                operator_catalog=operator_catalog,
                validate_alpha=validate_alpha,
                latest_release=data.latest_release,
                admit_run=research_runs.admit,
            ),
            research_runs=research_runs,
            daily_tracks=daily_tracks,
            publication=publication,
        )
    finally:
        database.close()
        working_cache.cleanup()

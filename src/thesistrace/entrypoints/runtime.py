from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient

from thesistrace._postgres import PostgresDatabase, apply_migrations
from thesistrace.data import DataService
from thesistrace.data.migrations import MIGRATIONS as DATA_MIGRATIONS
from thesistrace.publication import Publication

CORE_ENVIRONMENT_NAMES = (
    "THESISTRACE_DATABASE_URL",
    "THESISTRACE_S3_ENDPOINT_URL",
    "THESISTRACE_S3_ACCESS_KEY_ID",
    "THESISTRACE_S3_SECRET_ACCESS_KEY",
    "THESISTRACE_S3_BUCKET",
)


@dataclass(frozen=True)
class CoreSettings:
    database_url: str
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket: str
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
            **values,
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
    s3: BaseClient
    publication: Publication


@contextmanager
def open_core_runtime(settings: CoreSettings) -> Iterator[CoreRuntime]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        apply_migrations(database, DATA_MIGRATIONS)
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )
        s3.list_buckets()
        yield CoreRuntime(
            database=database,
            data=DataService(database),
            s3=s3,
            publication=Publication(s3, bucket=settings.s3_bucket),
        )
    finally:
        database.close()

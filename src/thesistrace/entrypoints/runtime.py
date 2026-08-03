from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient

from thesistrace._postgres import PostgresDatabase, apply_migrations
from thesistrace.data import DataService
from thesistrace.data.migrations import MIGRATIONS as DATA_MIGRATIONS


@dataclass(frozen=True)
class CoreSettings:
    database_url: str
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_region: str = "us-east-1"

    @classmethod
    def from_environment(cls) -> CoreSettings:
        names = {
            "database_url": "THESISTRACE_DATABASE_URL",
            "s3_endpoint_url": "THESISTRACE_S3_ENDPOINT_URL",
            "s3_access_key_id": "THESISTRACE_S3_ACCESS_KEY_ID",
            "s3_secret_access_key": "THESISTRACE_S3_SECRET_ACCESS_KEY",
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
        return cls(
            **values,
            s3_region=os.environ.get("THESISTRACE_S3_REGION", "us-east-1"),
        )


@dataclass(frozen=True)
class CoreRuntime:
    database: PostgresDatabase
    data: DataService
    s3: BaseClient


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
        )
    finally:
        database.close()

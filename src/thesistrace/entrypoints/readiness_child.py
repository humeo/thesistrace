from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import MountedGenerationStore
from thesistrace.publication import s3_storage_is_available

_PROBE_TIMEOUT_SECONDS = 0.75


def main(arguments: list[str] | None = None) -> None:
    selected = sys.argv[1:] if arguments is None else arguments
    if len(selected) != 1 or selected[0] not in {
        "postgresql",
        "rustfs",
        "dataset_store",
    }:
        raise SystemExit(2)
    try:
        available = _probe(selected[0])
    except Exception:
        available = False
    raise SystemExit(0 if available else 1)


def _probe(name: str) -> bool:
    if name == "postgresql":
        database = PostgresDatabase(
            os.environ["THESISTRACE_DATABASE_URL"],
            pool_timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        )
        try:
            database.open(timeout_seconds=_PROBE_TIMEOUT_SECONDS)
            return database.storage_is_available(timeout_seconds=_PROBE_TIMEOUT_SECONDS)
        finally:
            database.close()
    if name == "rustfs":
        client = boto3.client(
            "s3",
            endpoint_url=os.environ["THESISTRACE_S3_ENDPOINT_URL"],
            aws_access_key_id=os.environ["THESISTRACE_S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["THESISTRACE_S3_SECRET_ACCESS_KEY"],
            region_name=os.environ.get("THESISTRACE_S3_REGION", "us-east-1"),
            config=Config(
                connect_timeout=_PROBE_TIMEOUT_SECONDS,
                read_timeout=_PROBE_TIMEOUT_SECONDS,
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        )
        return s3_storage_is_available(client)
    return MountedGenerationStore(
        Path(os.environ["THESISTRACE_DATA_MOUNT"])
    ).storage_is_available()


if __name__ == "__main__":
    main()

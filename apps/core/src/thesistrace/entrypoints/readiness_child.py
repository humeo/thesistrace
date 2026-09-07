from __future__ import annotations

import os
import sys

_PROBE_TIMEOUT_SECONDS = 0.75


def main(arguments: list[str] | None = None) -> None:
    selected = sys.argv[1:] if arguments is None else arguments
    if len(selected) != 1 or selected[0] not in {
        "postgresql",
        "rustfs",
        "dataset_store",
        "auth",
    }:
        raise SystemExit(2)
    try:
        available = _probe(selected[0])
    except Exception:
        available = False
    raise SystemExit(0 if available else 1)


def _probe(name: str) -> bool:
    if name == "auth":
        import httpx

        response = httpx.get(
            f"{os.environ['THESISTRACE_AUTH_INTERNAL_ORIGIN']}/health/ready",
            follow_redirects=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    if name == "postgresql":
        from thesistrace._postgres import PostgresDatabase

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
        import boto3
        from botocore.config import Config

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
        response = client.list_buckets()
        return response["ResponseMetadata"]["HTTPStatusCode"] == 200
    descriptor: int | None = None
    try:
        descriptor = os.open(
            os.environ["THESISTRACE_DATA_MOUNT"],
            os.O_RDONLY | os.O_DIRECTORY,
        )
        return True
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == "__main__":
    main()

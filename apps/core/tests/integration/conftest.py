import boto3
import pytest
from botocore.client import BaseClient

from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
)


@pytest.fixture
def core_settings() -> CoreSettings:
    if not core_environment_is_configured():
        pytest.skip("the isolated Core PostgreSQL/RustFS runtime is not configured")
    return CoreSettings.from_environment()


@pytest.fixture
def rustfs_admin(core_settings: CoreSettings) -> BaseClient:
    """Infrastructure-only client for damage injection; never a Core product API."""
    return boto3.client(
        "s3",
        endpoint_url=core_settings.s3_endpoint_url,
        aws_access_key_id=core_settings.s3_access_key_id,
        aws_secret_access_key=core_settings.s3_secret_access_key,
        region_name=core_settings.s3_region,
    )

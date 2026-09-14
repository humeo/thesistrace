import hashlib
from pathlib import Path
from zipfile import ZipFile

import boto3
import pytest
from botocore.client import BaseClient

from thesistrace._postgres import SchemaDefinition
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
)


@pytest.fixture(scope="session")
def historical_core_schema() -> tuple[SchemaDefinition, ...]:
    path = Path(__file__).resolve().parents[1] / "fixtures/historical-core-schema"
    archive_path = path / "publication-maintenance-release.zip"
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == (
        "76498ac400bbccbf1a0b406d78ea5bcf6e2a9080eb694c9fe7caa94a10c2994f"
    )
    with ZipFile(archive_path) as archive:
        definitions = tuple(
            SchemaDefinition(name.removesuffix(".sql"), archive.read(name).decode())
            for name in archive.namelist()
        )
    return definitions


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


@pytest.fixture
def rank_ic_migration_target_schemas():
    """Use the actual historical DDL, independent of current product schema changes."""
    import json
    from pathlib import Path

    from thesistrace._postgres import SchemaDefinition
    from thesistrace._postgres.schema import _fingerprint
    from thesistrace.migrations.publication_maintenance_0002 import TARGET

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "publication_maintenance_target.json").read_text()
    )
    definitions = tuple(SchemaDefinition(**row) for row in fixture["schemas"])
    assert _fingerprint(definitions) == fixture["fingerprint"] == TARGET
    return definitions

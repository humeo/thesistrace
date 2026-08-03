import os

import pytest

from thesistrace.entrypoints.runtime import CoreSettings


@pytest.fixture
def core_settings() -> CoreSettings:
    required = (
        "THESISTRACE_DATABASE_URL",
        "THESISTRACE_S3_ENDPOINT_URL",
        "THESISTRACE_S3_ACCESS_KEY_ID",
        "THESISTRACE_S3_SECRET_ACCESS_KEY",
    )
    if any(not os.environ.get(name) for name in required):
        pytest.skip("the isolated Core PostgreSQL/RustFS runtime is not configured")
    return CoreSettings.from_environment()

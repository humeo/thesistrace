import pytest

from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
)


@pytest.fixture
def core_settings() -> CoreSettings:
    if not core_environment_is_configured():
        pytest.skip("the isolated Core PostgreSQL/RustFS runtime is not configured")
    return CoreSettings.from_environment()

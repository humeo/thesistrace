from collections.abc import Iterator

import pytest
from core_runtime import stop_internal_api_servers


@pytest.fixture(autouse=True)
def isolate_internal_strategy_metric_server() -> Iterator[None]:
    try:
        yield
    finally:
        stop_internal_api_servers()

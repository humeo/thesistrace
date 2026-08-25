from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest


def test_outage_polling_ignores_transient_fail_closed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_smoke_module()
    transient = (
        503,
        {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {
                    "status": "unavailable",
                    "code": "POSTGRESQL_UNAVAILABLE",
                },
                "rustfs": {"status": "unavailable", "code": "RUSTFS_UNAVAILABLE"},
                "dataset_store": {
                    "status": "unavailable",
                    "code": "DATASET_STORE_UNAVAILABLE",
                },
            },
        },
        0.01,
    )
    expected = (
        503,
        {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {
                    "status": "unavailable",
                    "code": "POSTGRESQL_UNAVAILABLE",
                },
                "rustfs": {"status": "ready", "code": "RUSTFS_READY"},
                "dataset_store": {"status": "ready", "code": "DATASET_STORE_READY"},
            },
        },
        0.01,
    )
    responses = iter((transient, expected))
    monkeypatch.setattr(smoke, "_request_health", lambda *_args: next(responses))

    assert smoke._wait_for_readiness("http://api:8100", unavailable="postgresql") == expected


def _load_smoke_module() -> ModuleType:
    path = Path(__file__).with_name("production_image_smoke.py")
    spec = spec_from_file_location("thesistrace_production_image_smoke", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

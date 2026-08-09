from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.data import DatasetHeadError, DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.fixture import build_minimal_canonical_fixture


def test_empty_and_prepared_data_overview_survive_real_http_restart(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    migrate_core(core_settings.database_url)
    settings = replace(core_settings, data_mount=tmp_path)
    empty = {
        "dataset_coverage": None,
        "data_through_session": None,
        "last_refresh_at": None,
        "readiness": False,
    }

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/data").json() == empty
        assert client.post("/api/data/update").status_code == 404
        assert client.get("/api/data/releases").status_code == 404
        assert client.get("/api/data/releases/anything").status_code == 404

    generation = MountedGenerationStore(tmp_path).materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="prepared-overview-test",
        source_lineage={"fixture": "minimal"},
    )
    with open_core_runtime(settings) as runtime:
        lifecycle = DatasetLifecycle(runtime.database, tmp_path)
        lifecycle.protect_candidate(
            operation_id="prepared-overview",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="prepared-overview",
        )

    expected = {
        "dataset_coverage": {"start": "2026-08-07", "end": "2026-08-07"},
        "data_through_session": "2026-08-07",
        "last_refresh_at": None,
        "readiness": True,
    }
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/data").json() == expected

    with open_core_runtime(settings) as runtime:
        with runtime.database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.current_dataset_state
                SET last_refresh_at = '2026-08-09T01:02:03+00:00'
                WHERE singleton = 1
                """
            )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/data").json() == {
            **expected,
            "last_refresh_at": "2026-08-09T01:02:03Z",
        }


def test_malformed_existing_head_prevents_healthy_runtime_start(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    migrate_core(core_settings.database_url)
    (tmp_path / "HEAD.json").write_bytes(b'{"format":')
    settings = replace(core_settings, data_mount=tmp_path)

    with pytest.raises(DatasetHeadError, match="malformed"):
        with open_core_runtime(settings):
            raise AssertionError("runtime started from malformed Dataset Head")


def test_same_generation_with_forged_head_projection_is_revalidated(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    migrate_core(core_settings.database_url)
    settings = replace(core_settings, data_mount=tmp_path)
    generation = MountedGenerationStore(tmp_path).materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        source_name="projection-tamper-test",
        source_lineage={"fixture": "minimal"},
    )
    with open_core_runtime(settings) as runtime:
        lifecycle = DatasetLifecycle(runtime.database, tmp_path)
        lifecycle.protect_candidate(
            operation_id="projection-tamper",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="projection-tamper",
        )
        assert runtime.data_overview.overview().readiness is True

        head_path = tmp_path / "HEAD.json"
        head = json.loads(head_path.read_text())
        head["dataset_coverage"]["start"] = "2026-08-06"
        head_path.write_text(json.dumps(head))

        with pytest.raises(DatasetHeadError, match="incompatible"):
            runtime.data_overview.overview()

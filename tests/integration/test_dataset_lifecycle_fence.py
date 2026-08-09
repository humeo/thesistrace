from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture


def test_head_move_and_pin_share_one_real_postgres_lifecycle_fence(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        _clear_lifecycle(database)
        generations = MountedGenerationStore(tmp_path)
        first, second, third = (_materialize(generations, ordinal=ordinal) for ordinal in (1, 2, 3))
        lifecycle = DatasetLifecycle(database, tmp_path)

        assert lifecycle.current_head() is None
        lifecycle.protect_candidate(
            operation_id="bootstrap-first",
            generation_manifest_sha256=first,
            lease_seconds=60,
        )
        first_head = lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=first,
            operation_id="bootstrap-first",
        )
        assert first_head.generation_manifest_sha256 == first

        first_pin = lifecycle.pin_current(
            owner_kind="research_run_attempt",
            owner_id="run-attempt-1",
            lease_seconds=60,
        )
        assert first_pin.status == "active"
        assert first_pin.lease_expires_at > first_pin.heartbeat_at
        lifecycle.protect_candidate(
            operation_id="refresh-second",
            generation_manifest_sha256=second,
            lease_seconds=60,
        )
        protected = lifecycle.retention()
        assert protected.live_candidate_generations == frozenset({second})
        assert protected.all_generations == frozenset({first, second})
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=first,
            candidate_generation_manifest_sha256=second,
            operation_id="refresh-second",
        )
        retention = lifecycle.retention()
        assert retention.head_generation_manifest_sha256 == second
        assert retention.active_pin_generations == frozenset({first})
        assert retention.live_candidate_generations == frozenset()
        assert generations.open_generation(first).canonical == build_minimal_canonical_fixture()

        lifecycle.protect_candidate(
            operation_id="refresh-third",
            generation_manifest_sha256=third,
            lease_seconds=60,
        )
        barrier = threading.Barrier(2)

        def pin_during_move() -> str:
            barrier.wait(timeout=10)
            return lifecycle.pin_current(
                owner_kind="tracking_advance_attempt",
                owner_id="track-attempt-1",
                lease_seconds=60,
            ).generation_manifest_sha256

        def move_during_pin() -> str:
            barrier.wait(timeout=10)
            return lifecycle.compare_and_swap_head(
                expected_generation_manifest_sha256=second,
                candidate_generation_manifest_sha256=third,
                operation_id="refresh-third",
            ).generation_manifest_sha256

        with ThreadPoolExecutor(max_workers=2) as executor:
            pin_future = executor.submit(pin_during_move)
            move_future = executor.submit(move_during_pin)
            selected = pin_future.result(timeout=20)
            assert move_future.result(timeout=20) == third

        assert selected in {second, third}
        assert generations.open_generation(selected).canonical == build_minimal_canonical_fixture()
        assert lifecycle.current_head().generation_manifest_sha256 == third
        assert {pin.owner_id for pin in lifecycle.active_pins()} == {
            "run-attempt-1",
            "track-attempt-1",
        }

        reopened_database = PostgresDatabase(core_settings.database_url)
        reopened_database.open()
        try:
            reopened = DatasetLifecycle(reopened_database, tmp_path)
            assert reopened.current_head().generation_manifest_sha256 == third
            assert {pin.generation_manifest_sha256 for pin in reopened.active_pins()} == {
                first,
                selected,
            }
        finally:
            reopened_database.close()

        lifecycle.release_pin(first_pin.id, owner_id=first_pin.owner_id)
        track_pin = next(
            pin for pin in lifecycle.active_pins() if pin.owner_id == "track-attempt-1"
        )
        lifecycle.release_pin(track_pin.id, owner_id=track_pin.owner_id)
        assert lifecycle.retention().all_generations == frozenset({third})
    finally:
        _clear_lifecycle(database)
        database.close()


def _materialize(store: MountedGenerationStore, *, ordinal: int) -> str:
    return store.materialize(
        build_minimal_canonical_fixture(),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC) + timedelta(minutes=ordinal),
        source_name="lifecycle-integration-test",
        source_lineage={"candidate": ordinal},
    ).manifest_sha256


def _clear_lifecycle(database: PostgresDatabase) -> None:
    with database.transaction() as transaction:
        transaction.execute("TRUNCATE data.generation_pins, data.generation_candidates")

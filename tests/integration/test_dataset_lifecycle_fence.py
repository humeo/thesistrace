from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from psycopg.errors import CheckViolation, RaiseException

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DataLifecycleError, DatasetLifecycle, MountedGenerationStore
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
        first, second, third, fourth = (
            _materialize(generations, ordinal=ordinal) for ordinal in (1, 2, 3, 4)
        )
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
        renewed = lifecycle.heartbeat_pin(
            first_pin.id,
            owner_id=first_pin.owner_id,
            lease_seconds=120,
        )
        assert renewed.lease_expires_at > first_pin.lease_expires_at
        with pytest.raises(DataLifecycleError, match="already has a pin"):
            lifecycle.pin_current(
                owner_kind="research_run_attempt",
                owner_id="run-attempt-1",
                lease_seconds=60,
            )
        lifecycle.protect_candidate(
            operation_id="refresh-second",
            generation_manifest_sha256=second,
            lease_seconds=60,
        )
        assert _candidate_state(database, "refresh-second") == {
            "generation_manifest_sha256": second,
            "status": "live",
        }
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=first,
            candidate_generation_manifest_sha256=second,
            operation_id="refresh-second",
        )
        assert _candidate_state(database, "refresh-second") == {
            "generation_manifest_sha256": second,
            "status": "released",
        }
        assert generations.open_generation(first).canonical == build_minimal_canonical_fixture(
            price_offset=1
        )

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
        selected_offset = 2 if selected == second else 3
        assert generations.open_generation(selected).canonical == build_minimal_canonical_fixture(
            price_offset=selected_offset
        )
        assert lifecycle.current_head().generation_manifest_sha256 == third
        assert lifecycle.current_head().generation.canonical == build_minimal_canonical_fixture(
            price_offset=3
        )
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
        assert lifecycle.active_pins() == ()

        lifecycle.protect_candidate(
            operation_id="refresh-fourth",
            generation_manifest_sha256=fourth,
            lease_seconds=60,
        )
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION data.reject_candidate_completion() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'injected completion failure';
                END
                $$;
                CREATE TRIGGER reject_candidate_completion
                BEFORE UPDATE OF status ON data.generation_candidates
                FOR EACH ROW
                WHEN (NEW.operation_id = 'refresh-fourth')
                EXECUTE FUNCTION data.reject_candidate_completion();
                """
            )
        try:
            with pytest.raises(RaiseException, match="injected completion failure"):
                lifecycle.compare_and_swap_head(
                    expected_generation_manifest_sha256=third,
                    candidate_generation_manifest_sha256=fourth,
                    operation_id="refresh-fourth",
                )
        finally:
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    DROP TRIGGER reject_candidate_completion
                        ON data.generation_candidates;
                    DROP FUNCTION data.reject_candidate_completion();
                    """
                )
        assert (
            DatasetLifecycle(database, tmp_path).current_head().generation_manifest_sha256 == fourth
        )
        assert _candidate_state(database, "refresh-fourth") == {
            "generation_manifest_sha256": fourth,
            "status": "live",
        }
        lifecycle.release_candidate(operation_id="refresh-fourth")
    finally:
        _clear_lifecycle(database)
        database.close()


def _materialize(store: MountedGenerationStore, *, ordinal: int) -> str:
    return store.materialize(
        build_minimal_canonical_fixture(price_offset=ordinal),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC) + timedelta(minutes=ordinal),
        source_name="lifecycle-integration-test",
        source_lineage={"candidate": ordinal},
    ).manifest_sha256


def _clear_lifecycle(database: PostgresDatabase) -> None:
    with database.transaction() as transaction:
        transaction.execute("TRUNCATE data.generation_pins, data.generation_candidates")


def _candidate_state(database: PostgresDatabase, operation_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT generation_manifest_sha256, status
            FROM data.generation_candidates
            WHERE operation_id = %s
            """,
            (operation_id,),
        ).fetchone()
    assert row is not None
    return row


def test_invalid_candidate_is_released_and_database_constraints_reject_bad_rows(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        _clear_lifecycle(database)
        lifecycle = DatasetLifecycle(database, tmp_path)
        with pytest.raises(RuntimeError, match="missing"):
            lifecycle.protect_candidate(
                operation_id="invalid-candidate",
                generation_manifest_sha256="0" * 64,
                lease_seconds=60,
            )
        assert _candidate_state(database, "invalid-candidate") == {
            "generation_manifest_sha256": "0" * 64,
            "status": "released",
        }

        invalid_rows = (
            (
                """
                INSERT INTO data.generation_candidates (
                    operation_id, generation_manifest_sha256, status, lease_expires_at
                ) VALUES (' ', %s, 'live', now() + interval '1 minute')
                """,
                ("1" * 64,),
            ),
            (
                """
                INSERT INTO data.generation_pins (
                    id, owner_kind, owner_id, generation_manifest_sha256,
                    status, lease_expires_at, released_at
                ) VALUES (
                    'bad-pin', 'research_run_attempt', 'owner', 'not-a-sha',
                    'active', now() + interval '1 minute', now()
                )
                """,
                (),
            ),
        )
        for statement, params in invalid_rows:
            with pytest.raises(CheckViolation), database.transaction() as transaction:
                transaction.execute(statement, params)
    finally:
        _clear_lifecycle(database)
        database.close()

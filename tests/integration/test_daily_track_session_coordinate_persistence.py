from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from psycopg.errors import DuplicateTable
from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track.session_persistence import (
    SessionCoordinateConflict,
    SessionCoordinateRepository,
)
from thesistrace.entrypoints.migrations import CORE_MIGRATION_PLANS, migrate_core
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_session_coordinate_history_round_trips_after_commit_and_runtime_reopen(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    _drop_product_schemas(settings.database_url)
    migrate_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        _insert_parent_track(database, track_id="track_session_roundtrip")
        repository = SessionCoordinateRepository(database)
        with database.transaction() as transaction:
            repository.activate(
                transaction,
                track_id="track_session_roundtrip",
                origin_session=date(2026, 8, 3),
                checkpoint_manifest_sha256="a" * 64,
                terminal_strategy_state=_strategy_state("2026-08-03", "10000000"),
                data_generation_id="generation_seed",
                provenance={"kind": "activation", "private": True},
            )
            repository.start_progression(
                transaction,
                progression_id="progression_session_roundtrip",
                track_id="track_session_roundtrip",
                expected_checkpoint_manifest_sha256="a" * 64,
                generation_sessions=(
                    date(2026, 8, 3),
                    date(2026, 8, 4),
                    date(2026, 8, 5),
                ),
                target_sessions=(date(2026, 8, 4), date(2026, 8, 5)),
                data_generation_id="generation_advance",
                provenance={"kind": "advance", "private": True},
            )
            repository.start_attempt(
                transaction,
                attempt_id="attempt_session_roundtrip",
                progression_id="progression_session_roundtrip",
                ordinal=1,
                fence=1,
                generation_pin_id="pin_session_roundtrip",
                data_generation_id="generation_advance",
                data_through_session=date(2026, 8, 5),
                lease_seconds=30,
            )
            repository.publish_checkpoint(
                transaction,
                progression_id="progression_session_roundtrip",
                attempt_id="attempt_session_roundtrip",
                fence=1,
                checkpoint_manifest_sha256="b" * 64,
                terminal_strategy_state=_strategy_state("2026-08-05", "10001000"),
                provenance={"kind": "checkpoint", "private": True},
            )
    finally:
        database.close()

    with open_core_runtime(settings) as runtime:
        snapshot = runtime.daily_track_sessions.load(
            "track_session_roundtrip"
        )

    assert snapshot.track.origin_session == date(2026, 8, 3)
    assert snapshot.track.current_checkpoint_session == date(2026, 8, 5)
    assert snapshot.track.current_checkpoint_manifest_sha256 == "b" * 64
    assert snapshot.track.terminal_strategy_state == _strategy_state(
        "2026-08-05", "10001000"
    )
    assert len(snapshot.progressions) == 1
    assert snapshot.progressions[0].predecessor_checkpoint_session == date(2026, 8, 3)
    assert snapshot.progressions[0].target_sessions == (
        date(2026, 8, 4),
        date(2026, 8, 5),
    )
    assert snapshot.progressions[0].data_generation_id == "generation_advance"
    assert snapshot.progressions[0].status == "succeeded"
    assert len(snapshot.attempts) == 1
    assert snapshot.attempts[0].status == "succeeded"
    assert snapshot.attempts[0].generation_pin_id == "pin_session_roundtrip"
    assert snapshot.attempts[0].data_generation_id == "generation_advance"
    assert snapshot.attempts[0].data_through_session == date(2026, 8, 5)
    assert [checkpoint.boundary_session for checkpoint in snapshot.checkpoints] == [
        date(2026, 8, 3),
        date(2026, 8, 5),
    ]
    assert snapshot.checkpoints[-1].predecessor_manifest_sha256 == "a" * 64
    assert snapshot.checkpoints[-1].data_generation_id == "generation_advance"


@pytest.mark.parametrize(
    ("expected_manifest", "target_sessions"),
    [
        ("a" * 64, (date(2026, 8, 3),)),
        ("a" * 64, (date(2026, 8, 5), date(2026, 8, 4))),
        ("a" * 64, (date(2026, 8, 4), date(2026, 8, 6))),
        ("z" * 64, (date(2026, 8, 4),)),
    ],
    ids=("non-advancing", "reversed", "gapped", "stale-checkpoint"),
)
@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_invalid_session_coordinates_leave_no_partial_progression(
    expected_manifest: str,
    target_sessions: tuple[date, ...],
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings.database_url)
    migrate_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        _insert_parent_track(database, track_id="track_session_invalid")
        repository = SessionCoordinateRepository(database)
        with database.transaction() as transaction:
            repository.activate(
                transaction,
                track_id="track_session_invalid",
                origin_session=date(2026, 8, 3),
                checkpoint_manifest_sha256="a" * 64,
                terminal_strategy_state=_strategy_state("2026-08-03", "10000000"),
                data_generation_id="generation_seed",
                provenance={"kind": "activation"},
            )

        with pytest.raises(SessionCoordinateConflict):
            with database.transaction() as transaction:
                repository.start_progression(
                    transaction,
                    progression_id="progression_session_invalid",
                    track_id="track_session_invalid",
                    expected_checkpoint_manifest_sha256=expected_manifest,
                    generation_sessions=(
                        date(2026, 8, 3),
                        date(2026, 8, 4),
                        date(2026, 8, 5),
                        date(2026, 8, 6),
                    ),
                    target_sessions=target_sessions,
                    data_generation_id="generation_invalid",
                    provenance={"kind": "invalid"},
                )

        snapshot = repository.load("track_session_invalid")
        assert snapshot.track.current_checkpoint_session == date(2026, 8, 3)
        assert snapshot.progressions == ()
        assert snapshot.attempts == ()
        assert len(snapshot.checkpoints) == 1
    finally:
        database.close()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_session_coordinate_migration_is_repeatable_and_failure_preserves_state() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings.database_url)
    migrate_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        _insert_parent_track(database, track_id="track_legacy_untouched")
        with database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO definitions.records (id, revision, content)
                VALUES (
                    'definition_preserved', 1,
                    '{"schema_version":"research-definition-v1"}'::jsonb
                )
                """
            )
            transaction.execute(
                "DELETE FROM daily_tracks.schema_migrations WHERE name = %s",
                ("0008_session_coordinate_persistence",),
            )
            _drop_session_coordinate_objects(transaction)
            transaction.execute(
                "CREATE TABLE daily_tracks.session_tracking_states (sentinel text)"
            )

        with pytest.raises(DuplicateTable):
            migrate_core(settings.database_url)

        with database.transaction() as transaction:
            definition = transaction.execute(
                "SELECT id, revision FROM definitions.records WHERE id = %s",
                ("definition_preserved",),
            ).fetchone()
            legacy = transaction.execute(
                "SELECT id, current_release_id FROM daily_tracks.tracks WHERE id = %s",
                ("track_legacy_untouched",),
            ).fetchone()
            ledger = transaction.execute(
                "SELECT count(*) AS count FROM daily_tracks.schema_migrations WHERE name = %s",
                ("0008_session_coordinate_persistence",),
            ).fetchone()
            transaction.execute("DROP TABLE daily_tracks.session_tracking_states")
        assert definition == {"id": "definition_preserved", "revision": 1}
        assert legacy == {
            "id": "track_legacy_untouched",
            "current_release_id": "legacy_release",
        }
        assert ledger == {"count": 0}
    finally:
        database.close()

    assert migrate_core(settings.database_url) == (
        "daily_tracks.0008_session_coordinate_persistence",
    )
    assert migrate_core(settings.database_url) == ()


def _insert_parent_track(database: PostgresDatabase, *, track_id: str) -> None:
    origin = {
        "seed_run_id": f"run_{track_id}",
        "definition_id": f"definition_{track_id}",
        "definition_revision": 1,
        "immutable_input": {},
        "seed_release_id": "legacy_release",
        "verified_result": {
            "kind": "research.result",
            "research_run_id": f"run_{track_id}",
            "schema_version": "research-result-v1",
            "result_manifest_sha256": "f" * 64,
            "result_checksum_sha256": "e" * 64,
        },
        "initial_strategy_state": _strategy_state("2026-08-03", "10000000"),
        "calculation_contracts": {},
    }
    with database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO daily_tracks.tracks (
                id, status, seed_run_id, origin, current_release_id,
                current_strategy_session
            ) VALUES (%s, 'active', %s, %s, 'legacy_release', '2026-08-03')
            """,
            (track_id, f"run_{track_id}", Jsonb(origin)),
        )


def _strategy_state(session: str, net_nav: str) -> dict[str, object]:
    return {
        "session": session,
        "gross_cash": net_nav,
        "net_cash": net_nav,
        "gross_nav": net_nav,
        "net_nav": net_nav,
        "benchmark_nav": "1",
        "cumulative_transaction_cost": "0",
        "positions": [],
        "rebalance_phase": {},
        "pending_signal": None,
        "last_daily_observation": {"session": session},
        "metric_state": {},
    }


def _drop_session_coordinate_objects(transaction) -> None:
    transaction.execute(
        """
        DROP TABLE daily_tracks.session_progression_attempts,
                   daily_tracks.session_tracking_states,
                   daily_tracks.session_checkpoints,
                   daily_tracks.session_progressions CASCADE;
        """
    )


def _drop_product_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for plan in reversed(CORE_MIGRATION_PLANS):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{plan.schema}" CASCADE')
    finally:
        database.close()

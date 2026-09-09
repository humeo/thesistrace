from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, SchemaError
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core
from thesistrace.research_folder import (
    CreateResearchFolder,
    RenameResearchFolder,
    ResearchFolderService,
)
from thesistrace.researcher import ResearcherIdentity, ResearcherService

RESEARCHER_A = ResearcherIdentity(
    researcher_id=UUID("271bf449-5a2a-41ff-a8df-978b33c6d5c9"),
    email="alpha@example.com",
    display_label="alpha",
)
RESEARCHER_B = ResearcherIdentity(
    researcher_id=UUID("e6889cdb-15ae-42ed-a293-5047435c9c47"),
    email="beta@example.com",
    display_label="beta",
)


@pytest.fixture
def ownership_database() -> PostgresDatabase:
    if not core_environment_is_configured():
        pytest.skip("the isolated Core PostgreSQL/RustFS runtime is not configured")
    settings = CoreSettings.from_environment()
    _drop_core_schemas(settings.database_url)
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url, pool_max_size=8)
    database.open()
    try:
        yield database
    finally:
        database.close()
        _drop_core_schemas(settings.database_url)


def test_bootstrap_is_transactional_and_idempotent_under_concurrent_calls(
    ownership_database: PostgresDatabase,
) -> None:
    service = ResearcherService(ownership_database)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(service.bootstrap, [RESEARCHER_A] * 8))
    service.bootstrap(RESEARCHER_B)

    expected = {
        "researcher_id": str(RESEARCHER_A.researcher_id),
        "system_folders": {
            "default": "folder_default",
            "batch_research": "folder_batch_research",
        },
    }
    assert [result.model_dump(mode="json") for result in results] == [expected] * 8

    with ownership_database.transaction() as transaction:
        researchers = transaction.execute(
            "SELECT id FROM researchers.researchers ORDER BY id"
        ).fetchall()
        folders = transaction.execute(
            """
            SELECT researcher_id, id, name, is_default
            FROM research_folders.folders
            ORDER BY researcher_id, is_default DESC, id
            """
        ).fetchall()
        researcher_columns = transaction.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'researchers' AND table_name = 'researchers'
            ORDER BY ordinal_position
            """
        ).fetchall()
    assert {row["id"] for row in researchers} == {
        RESEARCHER_A.researcher_id,
        RESEARCHER_B.researcher_id,
    }
    assert [(row["researcher_id"], row["id"]) for row in folders] == [
        (RESEARCHER_A.researcher_id, "folder_default"),
        (RESEARCHER_A.researcher_id, "folder_batch_research"),
        (RESEARCHER_B.researcher_id, "folder_default"),
        (RESEARCHER_B.researcher_id, "folder_batch_research"),
    ]
    assert [row["column_name"] for row in researcher_columns] == [
        "id",
        "created_at",
        "updated_at",
    ]


def test_research_folder_service_scopes_every_mutation_to_the_researcher(
    ownership_database: PostgresDatabase,
) -> None:
    researcher_service = ResearcherService(ownership_database)
    researcher_service.bootstrap(RESEARCHER_A)
    researcher_service.bootstrap(RESEARCHER_B)
    folders = ResearchFolderService(ownership_database)

    created = folders.create(
        RESEARCHER_A.researcher_id,
        CreateResearchFolder(name="Signals"),
    )

    assert [item.id for item in folders.list(RESEARCHER_A.researcher_id).items] == [
        "folder_default",
        "folder_batch_research",
        created.id,
    ]
    assert [item.id for item in folders.list(RESEARCHER_B.researcher_id).items] == [
        "folder_default",
        "folder_batch_research",
    ]
    assert (
        folders.rename(
            RESEARCHER_B.researcher_id,
            created.id,
            RenameResearchFolder(name="Stolen"),
        )
        is None
    )
    assert folders.delete(RESEARCHER_B.researcher_id, created.id) is False
    renamed = folders.rename(
        RESEARCHER_A.researcher_id,
        created.id,
        RenameResearchFolder(name="Renamed"),
    )
    assert renamed is not None
    assert renamed.name == "Renamed"


def test_schema_constraints_reject_every_cross_researcher_relationship(
    ownership_database: PostgresDatabase,
) -> None:
    service = ResearcherService(ownership_database)
    service.bootstrap(RESEARCHER_A)
    service.bootstrap(RESEARCHER_B)
    _insert_run(ownership_database, RESEARCHER_A.researcher_id, "run-a")
    _insert_run(ownership_database, RESEARCHER_B.researcher_id, "run-b")
    folder_only_b = ResearchFolderService(ownership_database).create(
        RESEARCHER_B.researcher_id,
        CreateResearchFolder(name="Only B"),
    )

    with pytest.raises(ForeignKeyViolation):
        _insert_run(
            ownership_database,
            RESEARCHER_A.researcher_id,
            "cross-folder-run",
            folder_id=folder_only_b.id,
        )

    with ownership_database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_batches.batches (
                researcher_id, id, batch_kind, status, scope
            ) VALUES (%s, 'batch-a', 'factor_evaluation', 'queued', '{}'::jsonb)
            """,
            (RESEARCHER_A.researcher_id,),
        )
    with pytest.raises(ForeignKeyViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO research_batches.items (
                    researcher_id, batch_id, ordinal, item_key,
                    research_run_id, dependency_role
                ) VALUES (%s, 'batch-a', 1, 'cross-owner', 'run-b', 'factor')
                """,
                (RESEARCHER_A.researcher_id,),
            )

    with pytest.raises(ForeignKeyViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO daily_tracks.tracks (
                    researcher_id, id, status, seed_run_id, origin
                ) VALUES (%s, 'track-cross-owner', 'active', 'run-b', '{}'::jsonb)
                """,
                (RESEARCHER_A.researcher_id,),
            )

    with ownership_database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_runs.admission_requests (
                researcher_id, request_id, request_fingerprint, run_id, outcome
            ) VALUES
                (%s, 'same-request', 'fingerprint-a', 'run-a',
                 '{"outcome":"accepted"}'::jsonb),
                (%s, 'same-request', 'fingerprint-b', 'run-b',
                 '{"outcome":"accepted"}'::jsonb)
            """,
            (RESEARCHER_A.researcher_id, RESEARCHER_B.researcher_id),
        )
    with pytest.raises(UniqueViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO research_runs.admission_requests (
                    researcher_id, request_id, request_fingerprint, run_id, outcome
                ) VALUES (%s, 'same-request', 'duplicate', 'run-a',
                          '{"outcome":"accepted"}'::jsonb)
                """,
                (RESEARCHER_A.researcher_id,),
            )

    assert _receipt_primary_keys(ownership_database) == {
        ("daily_tracks", "refresh_receipts"): ["researcher_id", "request_id"],
        ("daily_tracks", "retry_receipts"): ["researcher_id", "request_id"],
        ("daily_tracks", "stop_receipts"): ["researcher_id", "request_id"],
        ("research_batches", "admission_receipts"): [
            "researcher_id",
            "request_id",
        ],
        ("research_batches", "cancel_receipts"): [
            "researcher_id",
            "request_id",
        ],
        ("research_runs", "admission_requests"): [
            "researcher_id",
            "request_id",
        ],
        ("research_runs", "cancel_receipts"): ["researcher_id", "request_id"],
        ("research_runs", "start_tracking_receipts"): [
            "researcher_id",
            "request_id",
        ],
    }


def test_schema_rejects_cross_parent_receipts_checkpoints_and_blocked_links(
    ownership_database: PostgresDatabase,
) -> None:
    service = ResearcherService(ownership_database)
    service.bootstrap(RESEARCHER_A)
    service.bootstrap(RESEARCHER_B)
    _insert_run(ownership_database, RESEARCHER_A.researcher_id, "run-parent-a")
    _insert_run(ownership_database, RESEARCHER_B.researcher_id, "run-parent-b")
    _insert_track_graph(
        ownership_database,
        researcher_id=RESEARCHER_A.researcher_id,
        run_id="run-parent-a",
        track_id="track-parent-a",
        progression_id="progression-parent-a",
    )
    _insert_track_graph(
        ownership_database,
        researcher_id=RESEARCHER_B.researcher_id,
        run_id="run-parent-b",
        track_id="track-parent-b",
        progression_id="progression-parent-b",
    )
    _insert_attempt(
        ownership_database,
        run_id="run-parent-a",
        attempt_id="attempt-parent-a",
    )
    _insert_attempt(
        ownership_database,
        run_id="run-parent-b",
        attempt_id="attempt-parent-b",
    )

    with pytest.raises(ForeignKeyViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO research_runs.start_tracking_receipts (
                    researcher_id, request_id, request_fingerprint,
                    seed_run_id, track_id, outcome
                ) VALUES (%s, 'cross-track', 'fingerprint',
                          'run-parent-a', 'track-parent-b', %s)
                """,
                (
                    RESEARCHER_A.researcher_id,
                    Jsonb(
                        _track_outcome(
                            track_id="track-parent-b",
                            seed_run_id="run-parent-a",
                            status="active",
                        )
                    ),
                ),
            )

    with pytest.raises(ForeignKeyViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO daily_tracks.refresh_receipts (
                    researcher_id, request_id, request_fingerprint,
                    track_id, outcome
                ) VALUES (%s, 'cross-refresh', 'fingerprint',
                          'track-parent-b', %s)
                """,
                (
                    RESEARCHER_A.researcher_id,
                    Jsonb(
                        _track_outcome(
                            track_id="track-parent-b",
                            seed_run_id="run-parent-b",
                            status="active",
                        )
                    ),
                ),
            )

    with pytest.raises(ForeignKeyViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO research_runs.execution_checkpoints (
                    id, run_id, attempt_id, ordinal, boundary_session, phase,
                    completed_warmup_sessions, completed_research_sessions,
                    continuation_payload, observation_row_count,
                    checkpoint_manifest_sha256, chain_sha256
                ) VALUES (
                    'checkpoint-cross-attempt', 'run-parent-a',
                    'attempt-parent-b', 1, DATE '2026-08-01', 'research',
                    0, 1, '{}'::jsonb, 0, %s, %s
                )
                """,
                ("a" * 64, "b" * 64),
            )

    with pytest.raises(ForeignKeyViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO daily_tracks.retry_receipts (
                    researcher_id, request_id, request_fingerprint,
                    track_id, outcome, progression_id
                ) VALUES (%s, 'cross-progression', 'fingerprint',
                          'track-parent-a', %s, 'progression-parent-b')
                """,
                (
                    RESEARCHER_A.researcher_id,
                    Jsonb(
                        _track_outcome(
                            track_id="track-parent-a",
                            seed_run_id="run-parent-a",
                            status="active",
                        )
                    ),
                ),
            )

    with pytest.raises(ForeignKeyViolation):
        with ownership_database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET status = 'blocked', blocked_reason = 'CAPACITY_EXCEEDED',
                    blocked_progression_id = 'progression-parent-b'
                WHERE id = 'track-parent-a'
                """
            )


def test_run_owner_anchor_preserves_batch_and_track_ownership_after_run_deletion(
    ownership_database: PostgresDatabase,
) -> None:
    ResearcherService(ownership_database).bootstrap(RESEARCHER_A)
    _insert_run(ownership_database, RESEARCHER_A.researcher_id, "retained-run")
    with ownership_database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_batches.batches (
                researcher_id, id, batch_kind, status, scope
            ) VALUES (%s, 'retained-batch', 'factor_evaluation', 'queued', '{}'::jsonb)
            """,
            (RESEARCHER_A.researcher_id,),
        )
        transaction.execute(
            """
            INSERT INTO research_batches.items (
                researcher_id, batch_id, ordinal, item_key,
                research_run_id, dependency_role
            ) VALUES (%s, 'retained-batch', 1, 'retained', 'retained-run', 'factor')
            """,
            (RESEARCHER_A.researcher_id,),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.tracks (
                researcher_id, id, status, seed_run_id, origin
            ) VALUES (%s, 'retained-track', 'active', 'retained-run', '{}'::jsonb)
            """,
            (RESEARCHER_A.researcher_id,),
        )
        transaction.execute(
            "DELETE FROM research_runs.runs WHERE id = 'retained-run'"
        )

    with ownership_database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
                (SELECT count(*) FROM research_runs.runs
                  WHERE id = 'retained-run') AS runs,
                (SELECT count(*) FROM research_runs.run_ownership
                  WHERE researcher_id = %s AND run_id = 'retained-run') AS anchors,
                (SELECT count(*) FROM research_batches.items
                  WHERE researcher_id = %s
                    AND research_run_id = 'retained-run') AS batch_items,
                (SELECT count(*) FROM daily_tracks.tracks
                  WHERE researcher_id = %s
                    AND seed_run_id = 'retained-run') AS tracks
            """,
            (
                RESEARCHER_A.researcher_id,
                RESEARCHER_A.researcher_id,
                RESEARCHER_A.researcher_id,
            ),
        ).fetchone()
    assert row == {"runs": 0, "anchors": 1, "batch_items": 1, "tracks": 1}


def test_current_initializer_refuses_the_ownerless_six_schema_contract() -> None:
    if not core_environment_is_configured():
        pytest.skip("the isolated Core PostgreSQL/RustFS runtime is not configured")
    database_url = CoreSettings.from_environment().database_url
    _drop_core_schemas(database_url)
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema_name in CORE_SCHEMAS:
                if schema_name != "researchers":
                    transaction.execute(f'CREATE SCHEMA "{schema_name}"')
            transaction.execute("CREATE SCHEMA thesistrace_meta")
            transaction.execute(
                """
                CREATE TABLE thesistrace_meta.schema_contract (
                    singleton boolean PRIMARY KEY CHECK (singleton),
                    fingerprint text NOT NULL
                )
                """
            )
            transaction.execute(
                """
                INSERT INTO thesistrace_meta.schema_contract (singleton, fingerprint)
                VALUES (true, 'ownerless-six-schema-fingerprint')
                """
            )

        with pytest.raises(SchemaError, match="explicit data-preserving upgrade"):
            initialize_core(database_url)

        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    to_regnamespace('researchers') IS NULL AS researchers_absent,
                    fingerprint
                FROM thesistrace_meta.schema_contract
                WHERE singleton = true
                """
            ).fetchone()
        assert row == {
            "researchers_absent": True,
            "fingerprint": "ownerless-six-schema-fingerprint",
        }
    finally:
        database.close()
        _drop_core_schemas(database_url)


def test_current_initializer_refuses_a_legacy_fingerprint_without_mutation() -> None:
    if not core_environment_is_configured():
        pytest.skip("the isolated Core PostgreSQL/RustFS runtime is not configured")
    database_url = CoreSettings.from_environment().database_url
    _drop_core_schemas(database_url)
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema_name in CORE_SCHEMAS:
                transaction.execute(f'CREATE SCHEMA "{schema_name}"')
            transaction.execute("CREATE SCHEMA thesistrace_meta")
            transaction.execute(
                """
                CREATE TABLE thesistrace_meta.schema_contract (
                    singleton boolean PRIMARY KEY CHECK (singleton),
                    fingerprint text NOT NULL
                )
                """
            )
            transaction.execute(
                """
                INSERT INTO thesistrace_meta.schema_contract (singleton, fingerprint)
                VALUES (true, 'legacy-ownerless-fingerprint')
                """
            )

        with pytest.raises(SchemaError, match="explicit data-preserving upgrade"):
            initialize_core(database_url)

        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    to_regclass('researchers.researchers') IS NULL AS table_absent,
                    fingerprint
                FROM thesistrace_meta.schema_contract
                WHERE singleton = true
                """
            ).fetchone()
        assert row == {
            "table_absent": True,
            "fingerprint": "legacy-ownerless-fingerprint",
        }
    finally:
        database.close()
        _drop_core_schemas(database_url)


def _insert_run(
    database: PostgresDatabase,
    researcher_id: UUID,
    run_id: str,
    *,
    folder_id: str = "folder_default",
) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_runs.run_ownership (researcher_id, run_id)
            VALUES (%s, %s)
            """,
            (researcher_id, run_id),
        )
        transaction.execute(
            """
            INSERT INTO research_runs.runs (
                researcher_id, id, folder_id, name, requested_start_date,
                requested_end_date, status, immutable_input
            )
            VALUES (
                %s, %s, %s, %s, DATE '2026-08-01', DATE '2026-08-02',
                'queued', '{"research_kind":"factor_evaluation"}'::jsonb
            )
            """,
            (researcher_id, run_id, folder_id, run_id),
        )


def _insert_attempt(
    database: PostgresDatabase,
    *,
    run_id: str,
    attempt_id: str,
) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_runs.attempts (
                id, run_id, ordinal, fence, generation_pin_id,
                data_generation_id, data_through_session, status,
                lease_expires_at
            ) VALUES (
                %s, %s, 1, 1, %s, 'generation', DATE '2026-08-01',
                'running', transaction_timestamp() + interval '1 minute'
            )
            """,
            (attempt_id, run_id, f"pin-{attempt_id}"),
        )


def _insert_track_graph(
    database: PostgresDatabase,
    *,
    researcher_id: UUID,
    run_id: str,
    track_id: str,
    progression_id: str,
) -> None:
    origin_manifest = ("a" if track_id.endswith("a") else "b") * 64
    with database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO daily_tracks.tracks (
                researcher_id, id, status, seed_run_id, origin
            ) VALUES (%s, %s, 'active', %s, '{}'::jsonb)
            """,
            (researcher_id, track_id, run_id),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_checkpoints (
                manifest_sha256, track_id, boundary_session,
                terminal_strategy_state, data_generation_id, provenance
            ) VALUES (%s, %s, DATE '2026-08-01', '{}'::jsonb,
                      'generation', '{}'::jsonb)
            """,
            (origin_manifest, track_id),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_progressions (
                id, track_id, predecessor_checkpoint_manifest_sha256,
                target_sessions, target_start_session, target_end_session,
                planning_data_generation_id, current_cycle_ordinal,
                queue_position, status, provenance
            ) VALUES (
                %s, %s, %s, ARRAY[DATE '2026-08-02'],
                DATE '2026-08-02', DATE '2026-08-02', 'generation',
                1, 1, 'running', '{}'::jsonb
            )
            """,
            (progression_id, track_id, origin_manifest),
        )


def _receipt_primary_keys(
    database: PostgresDatabase,
) -> dict[tuple[str, str], list[str]]:
    with database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT namespace.nspname AS schema_name,
                   relation.relname AS table_name,
                   array_agg(attribute.attname ORDER BY key_column.ordinality) AS columns
            FROM pg_constraint AS constraint_record
            JOIN pg_class AS relation ON relation.oid = constraint_record.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            CROSS JOIN LATERAL unnest(constraint_record.conkey)
                WITH ORDINALITY AS key_column(attribute_number, ordinality)
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = relation.oid
             AND attribute.attnum = key_column.attribute_number
            WHERE constraint_record.contype = 'p'
              AND (namespace.nspname, relation.relname) IN (
                  ('daily_tracks', 'refresh_receipts'),
                  ('daily_tracks', 'retry_receipts'),
                  ('daily_tracks', 'stop_receipts'),
                  ('research_batches', 'admission_receipts'),
                  ('research_batches', 'cancel_receipts'),
                  ('research_runs', 'admission_requests'),
                  ('research_runs', 'cancel_receipts'),
                  ('research_runs', 'start_tracking_receipts')
              )
            GROUP BY namespace.nspname, relation.relname
            ORDER BY namespace.nspname, relation.relname
            """
        ).fetchall()
    return {
        (row["schema_name"], row["table_name"]): list(row["columns"])
        for row in rows
    }


def _track_outcome(
    *,
    track_id: str,
    seed_run_id: str,
    status: str,
) -> dict[str, str]:
    return {
        "id": track_id,
        "status": status,
        "seed_run_id": seed_run_id,
        "result_checksum_sha256": "f" * 64,
        "origin_session": "2026-08-01",
        "strategy_session": "2026-08-01",
    }


def _drop_core_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema_name in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
    finally:
        database.close()

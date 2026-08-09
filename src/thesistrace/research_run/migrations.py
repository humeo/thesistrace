from thesistrace._postgres import Migration, MigrationPlan

MIGRATIONS = MigrationPlan(
    schema="research_runs",
    ledger_table="schema_migrations",
    lock_name="thesistrace-core-research-run-migrations",
    migrations=(
        Migration(
            name="0001_queued_research_runs",
            statement="""
                CREATE TABLE research_runs.runs (
                    id text PRIMARY KEY,
                    definition_id text NOT NULL,
                    definition_revision integer NOT NULL
                        CHECK (definition_revision > 0),
                    dataset_release_id text NOT NULL REFERENCES data.releases(id),
                    status text NOT NULL CHECK (
                        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
                    ),
                    immutable_input jsonb NOT NULL CHECK (
                        jsonb_typeof(immutable_input) = 'object'
                    ),
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );

                CREATE INDEX research_runs_runs_created_idx
                    ON research_runs.runs (created_at DESC, id);
            """,
        ),
        Migration(
            name="0002_execution_attempts_and_results",
            statement="""
                ALTER TABLE research_runs.runs
                    ADD COLUMN execution_fence integer NOT NULL DEFAULT 0
                        CHECK (execution_fence >= 0),
                    ADD COLUMN result_manifest_sha256 text,
                    ADD COLUMN result_provenance jsonb CHECK (
                        result_provenance IS NULL
                        OR jsonb_typeof(result_provenance) = 'object'
                    );

                CREATE TABLE research_runs.attempts (
                    id text PRIMARY KEY,
                    run_id text NOT NULL REFERENCES research_runs.runs(id),
                    ordinal integer NOT NULL CHECK (ordinal > 0),
                    fence integer NOT NULL CHECK (fence > 0),
                    status text NOT NULL CHECK (
                        status IN ('running', 'succeeded', 'failed', 'cancelled')
                    ),
                    started_at timestamptz NOT NULL DEFAULT now(),
                    heartbeat_at timestamptz NOT NULL DEFAULT now(),
                    lease_expires_at timestamptz NOT NULL,
                    finished_at timestamptz,
                    failure_reason text,
                    UNIQUE (run_id, ordinal)
                );

                CREATE UNIQUE INDEX research_runs_one_running_attempt_idx
                    ON research_runs.attempts (run_id)
                    WHERE status = 'running';
            """,
        ),
        Migration(
            name="0003_terminal_failure_reason",
            statement="""
                ALTER TABLE research_runs.runs
                    ADD COLUMN failure_reason text;
            """,
        ),
        Migration(
            name="0004_cancel_receipts",
            statement="""
                CREATE TABLE research_runs.cancel_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    run_id text NOT NULL,
                    outcome jsonb NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
        Migration(
            name="0005_exact_input_reruns",
            statement="""
                ALTER TABLE research_runs.runs
                    ADD COLUMN rerun_of_id text
                        REFERENCES research_runs.runs(id);

                CREATE TABLE research_runs.rerun_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    source_run_id text NOT NULL REFERENCES research_runs.runs(id),
                    rerun_id text NOT NULL REFERENCES research_runs.runs(id),
                    outcome jsonb NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
        Migration(
            name="0006_start_tracking_receipts",
            statement="""
                CREATE TABLE research_runs.start_tracking_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    seed_run_id text NOT NULL,
                    track_id text NOT NULL,
                    outcome jsonb NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
        Migration(
            name="0007_import_legacy_start_tracking_receipts",
            statement="""
                DO $migration$
                BEGIN
                    IF to_regclass('daily_tracks.activation_receipts') IS NOT NULL THEN
                        IF EXISTS (
                            SELECT 1
                            FROM daily_tracks.activation_receipts AS legacy
                            JOIN daily_tracks.tracks AS track
                                ON track.id = legacy.track_id
                            JOIN research_runs.start_tracking_receipts AS current
                                ON current.request_id = legacy.request_id
                            WHERE current.request_fingerprint <> legacy.request_fingerprint
                               OR current.seed_run_id <> track.seed_run_id
                               OR current.track_id <> legacy.track_id
                               OR current.outcome <> legacy.outcome
                        ) THEN
                            RAISE EXCEPTION
                                'incompatible Start Tracking receipt blocks contraction';
                        END IF;

                        INSERT INTO research_runs.start_tracking_receipts (
                            request_id, request_fingerprint, seed_run_id,
                            track_id, outcome, created_at
                        )
                        SELECT legacy.request_id,
                               legacy.request_fingerprint,
                               track.seed_run_id,
                               legacy.track_id,
                               legacy.outcome,
                               legacy.created_at
                        FROM daily_tracks.activation_receipts AS legacy
                        JOIN daily_tracks.tracks AS track
                            ON track.id = legacy.track_id
                        ON CONFLICT (request_id) DO NOTHING;
                    END IF;
                END
                $migration$;
            """,
        ),
        Migration(
            name="0008_requested_dates_without_admission_data_binding",
            statement="""
                ALTER TABLE research_runs.runs
                    DROP COLUMN dataset_release_id,
                    ADD COLUMN requested_start_date date,
                    ADD COLUMN requested_end_date date,
                    ADD CONSTRAINT research_runs_requested_date_order CHECK (
                        requested_start_date IS NULL
                        OR requested_end_date IS NULL
                        OR requested_start_date <= requested_end_date
                    );
            """,
        ),
    ),
)

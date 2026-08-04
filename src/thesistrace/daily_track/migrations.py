from thesistrace._postgres import Migration, MigrationPlan

MIGRATIONS = MigrationPlan(
    schema="daily_tracks",
    ledger_table="schema_migrations",
    lock_name="thesistrace-core-daily-track-migrations",
    migrations=(
        Migration(
            name="0001_active_tracks_and_origins",
            statement="""
                CREATE TABLE daily_tracks.tracks (
                    id text PRIMARY KEY,
                    status text NOT NULL CHECK (status = 'active'),
                    seed_run_id text NOT NULL UNIQUE,
                    origin jsonb NOT NULL CHECK (jsonb_typeof(origin) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );

                CREATE INDEX daily_tracks_created_idx
                    ON daily_tracks.tracks (created_at DESC, id);

                CREATE TABLE daily_tracks.activation_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    track_id text NOT NULL REFERENCES daily_tracks.tracks(id),
                    outcome jsonb NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
    ),
)

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
        Migration(
            name="0002_direct_successor_progression",
            statement="""
                ALTER TABLE daily_tracks.tracks
                    ADD COLUMN current_release_id text,
                    ADD COLUMN current_strategy_session text,
                    ADD COLUMN head_manifest_sha256 text NULL,
                    ADD COLUMN execution_fence bigint NOT NULL DEFAULT 0;

                UPDATE daily_tracks.tracks
                SET current_release_id = origin ->> 'seed_release_id',
                    current_strategy_session =
                        origin -> 'initial_strategy_state' ->> 'session';

                UPDATE daily_tracks.activation_receipts AS receipt
                SET outcome = receipt.outcome || jsonb_build_object(
                    'current_release_id', track.current_release_id
                )
                FROM daily_tracks.tracks AS track
                WHERE track.id = receipt.track_id;

                ALTER TABLE daily_tracks.tracks
                    ALTER COLUMN current_release_id SET NOT NULL,
                    ALTER COLUMN current_strategy_session SET NOT NULL;

                CREATE TABLE daily_tracks.progressions (
                    track_id text NOT NULL REFERENCES daily_tracks.tracks(id),
                    target_release_id text NOT NULL,
                    predecessor_release_id text NOT NULL,
                    fence bigint NOT NULL,
                    status text NOT NULL CHECK (status IN ('running', 'succeeded')),
                    manifest_sha256 text NULL,
                    provenance jsonb NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    finished_at timestamptz NULL,
                    PRIMARY KEY (track_id, target_release_id)
                );

                CREATE TABLE daily_tracks.checkpoints (
                    track_id text NOT NULL REFERENCES daily_tracks.tracks(id),
                    target_release_id text NOT NULL,
                    predecessor_release_id text NOT NULL,
                    manifest_sha256 text NOT NULL UNIQUE,
                    provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
                    strategy_session text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (track_id, target_release_id),
                    FOREIGN KEY (track_id, target_release_id)
                        REFERENCES daily_tracks.progressions(track_id, target_release_id)
                );
            """,
        ),
    ),
)

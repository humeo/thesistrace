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
        Migration(
            name="0003_recoverable_progression_attempts",
            statement="""
                CREATE TABLE daily_tracks.progression_attempts (
                    id text PRIMARY KEY,
                    track_id text NOT NULL,
                    target_release_id text NOT NULL,
                    ordinal integer NOT NULL CHECK (ordinal > 0),
                    fence bigint NOT NULL CHECK (fence > 0),
                    status text NOT NULL CHECK (
                        status IN (
                            'queued', 'running', 'succeeded', 'failed', 'cancelled'
                        )
                    ),
                    started_at timestamptz NOT NULL DEFAULT now(),
                    heartbeat_at timestamptz NOT NULL DEFAULT now(),
                    lease_expires_at timestamptz NOT NULL,
                    finished_at timestamptz NULL,
                    failure_reason text NULL,
                    UNIQUE (track_id, target_release_id, ordinal),
                    FOREIGN KEY (track_id, target_release_id)
                        REFERENCES daily_tracks.progressions(track_id, target_release_id)
                );

                CREATE UNIQUE INDEX daily_tracks_one_live_progression_attempt_idx
                    ON daily_tracks.progression_attempts (track_id, target_release_id)
                    WHERE status = 'running';

                INSERT INTO daily_tracks.progression_attempts (
                    id, track_id, target_release_id, ordinal, fence, status,
                    lease_expires_at, finished_at
                )
                SELECT
                    'attempt_migrated_' || md5(track_id || ':' || target_release_id),
                    track_id,
                    target_release_id,
                    1,
                    fence,
                    CASE status
                        WHEN 'succeeded' THEN 'succeeded'
                        ELSE 'running'
                    END,
                    now(),
                    CASE status
                        WHEN 'succeeded' THEN now()
                        ELSE NULL
                    END
                FROM daily_tracks.progressions;
            """,
        ),
        Migration(
            name="0004_blocked_track_failure_isolation",
            statement="""
                ALTER TABLE daily_tracks.tracks
                    DROP CONSTRAINT tracks_status_check,
                    ADD COLUMN blocked_target_release_id text NULL,
                    ADD COLUMN blocked_reason text NULL,
                    ADD CONSTRAINT tracks_status_check
                        CHECK (status IN ('active', 'blocked')),
                    ADD CONSTRAINT tracks_blocked_state_check CHECK (
                        (status = 'active'
                            AND blocked_target_release_id IS NULL
                            AND blocked_reason IS NULL)
                        OR
                        (status = 'blocked'
                            AND blocked_target_release_id IS NOT NULL
                            AND blocked_reason IS NOT NULL)
                    );

                ALTER TABLE daily_tracks.progressions
                    DROP CONSTRAINT progressions_status_check,
                    ADD CONSTRAINT progressions_status_check
                        CHECK (status IN ('running', 'succeeded', 'blocked'));
            """,
        ),
        Migration(
            name="0005_blocked_retry_receipts",
            statement="""
                CREATE TABLE daily_tracks.retry_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    track_id text NOT NULL REFERENCES daily_tracks.tracks(id),
                    target_release_id text NOT NULL,
                    outcome jsonb NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
        Migration(
            name="0006_irreversible_stop",
            statement="""
                ALTER TABLE daily_tracks.tracks
                    DROP CONSTRAINT tracks_status_check,
                    DROP CONSTRAINT tracks_blocked_state_check,
                    ADD CONSTRAINT tracks_status_check
                        CHECK (status IN ('active', 'blocked', 'stopped')),
                    ADD CONSTRAINT tracks_lifecycle_state_check CHECK (
                        (status IN ('active', 'stopped')
                            AND blocked_target_release_id IS NULL
                            AND blocked_reason IS NULL)
                        OR
                        (status = 'blocked'
                            AND blocked_target_release_id IS NOT NULL
                            AND blocked_reason IS NOT NULL)
                    );

                ALTER TABLE daily_tracks.progressions
                    DROP CONSTRAINT progressions_status_check,
                    ADD CONSTRAINT progressions_status_check CHECK (
                        status IN ('running', 'succeeded', 'blocked', 'cancelled')
                    );

                CREATE TABLE daily_tracks.stop_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    track_id text NOT NULL REFERENCES daily_tracks.tracks(id),
                    outcome jsonb NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
        Migration(
            name="0007_drop_legacy_activation_receipts",
            statement="""
                DROP TABLE daily_tracks.activation_receipts;
            """,
        ),
        Migration(
            name="0008_session_coordinate_persistence",
            statement="""
                CREATE TABLE daily_tracks.session_checkpoints (
                    manifest_sha256 text PRIMARY KEY,
                    track_id text NOT NULL REFERENCES daily_tracks.tracks(id),
                    progression_id text NULL,
                    predecessor_manifest_sha256 text NULL,
                    boundary_session date NOT NULL,
                    terminal_strategy_state jsonb NOT NULL CHECK (
                        jsonb_typeof(terminal_strategy_state) = 'object'
                    ),
                    data_generation_id text NOT NULL,
                    provenance jsonb NOT NULL CHECK (
                        jsonb_typeof(provenance) = 'object'
                    ),
                    created_at timestamptz NOT NULL DEFAULT now(),
                    UNIQUE (track_id, boundary_session),
                    UNIQUE (track_id, manifest_sha256),
                    UNIQUE (track_id, boundary_session, manifest_sha256),
                    UNIQUE (track_id, progression_id, manifest_sha256),
                    FOREIGN KEY (track_id, predecessor_manifest_sha256)
                        REFERENCES daily_tracks.session_checkpoints(
                            track_id, manifest_sha256
                        ),
                    CHECK (
                        (progression_id IS NULL
                            AND predecessor_manifest_sha256 IS NULL)
                        OR
                        (progression_id IS NOT NULL
                            AND predecessor_manifest_sha256 IS NOT NULL)
                    )
                );

                CREATE TABLE daily_tracks.session_tracking_states (
                    track_id text PRIMARY KEY REFERENCES daily_tracks.tracks(id),
                    origin_session date NOT NULL,
                    origin_checkpoint_manifest_sha256 text NOT NULL,
                    current_checkpoint_manifest_sha256 text NOT NULL,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    FOREIGN KEY (
                        track_id, origin_session,
                        origin_checkpoint_manifest_sha256
                    ) REFERENCES daily_tracks.session_checkpoints(
                        track_id, boundary_session, manifest_sha256
                    ),
                    FOREIGN KEY (track_id, current_checkpoint_manifest_sha256)
                        REFERENCES daily_tracks.session_checkpoints(
                            track_id, manifest_sha256
                        )
                );

                CREATE TABLE daily_tracks.session_progressions (
                    id text PRIMARY KEY,
                    track_id text NOT NULL REFERENCES daily_tracks.tracks(id),
                    predecessor_checkpoint_manifest_sha256 text NOT NULL,
                    target_sessions date[] NOT NULL,
                    target_start_session date NOT NULL,
                    target_end_session date NOT NULL,
                    data_generation_id text NOT NULL,
                    status text NOT NULL CHECK (
                        status IN ('running', 'succeeded', 'blocked', 'cancelled')
                    ),
                    checkpoint_manifest_sha256 text NULL,
                    provenance jsonb NOT NULL CHECK (
                        jsonb_typeof(provenance) = 'object'
                    ),
                    created_at timestamptz NOT NULL DEFAULT now(),
                    finished_at timestamptz NULL,
                    UNIQUE (track_id, id),
                    UNIQUE (track_id, id, target_end_session),
                    UNIQUE (track_id, target_end_session),
                    FOREIGN KEY (
                        track_id, predecessor_checkpoint_manifest_sha256
                    ) REFERENCES daily_tracks.session_checkpoints(
                        track_id, manifest_sha256
                    ),
                    CHECK (cardinality(target_sessions) > 0),
                    CHECK (target_start_session = target_sessions[1]),
                    CHECK (
                        target_end_session =
                            target_sessions[cardinality(target_sessions)]
                    ),
                    CHECK (
                        (status = 'succeeded'
                            AND checkpoint_manifest_sha256 IS NOT NULL
                            AND finished_at IS NOT NULL)
                        OR
                        (status <> 'succeeded'
                            AND checkpoint_manifest_sha256 IS NULL)
                    )
                );

                CREATE UNIQUE INDEX daily_tracks_one_unresolved_session_progression_idx
                    ON daily_tracks.session_progressions (track_id)
                    WHERE status IN ('running', 'blocked');

                CREATE TABLE daily_tracks.session_progression_attempts (
                    id text PRIMARY KEY,
                    progression_id text NOT NULL,
                    track_id text NOT NULL,
                    ordinal integer NOT NULL CHECK (ordinal > 0),
                    fence bigint NOT NULL CHECK (fence > 0),
                    generation_pin_id text NOT NULL UNIQUE,
                    data_generation_id text NOT NULL,
                    data_through_session date NOT NULL,
                    status text NOT NULL CHECK (
                        status IN ('running', 'succeeded', 'failed', 'cancelled')
                    ),
                    started_at timestamptz NOT NULL DEFAULT now(),
                    heartbeat_at timestamptz NOT NULL DEFAULT now(),
                    lease_expires_at timestamptz NOT NULL,
                    finished_at timestamptz NULL,
                    failure_reason text NULL,
                    UNIQUE (progression_id, ordinal),
                    FOREIGN KEY (track_id, progression_id)
                        REFERENCES daily_tracks.session_progressions(track_id, id)
                );

                CREATE UNIQUE INDEX daily_tracks_one_live_session_attempt_idx
                    ON daily_tracks.session_progression_attempts (progression_id)
                    WHERE status = 'running';

                ALTER TABLE daily_tracks.session_checkpoints
                    ADD CONSTRAINT session_checkpoint_progression_fk
                    FOREIGN KEY (track_id, progression_id, boundary_session)
                    REFERENCES daily_tracks.session_progressions(
                        track_id, id, target_end_session
                    );

                ALTER TABLE daily_tracks.session_progressions
                    ADD CONSTRAINT session_progression_checkpoint_fk
                    FOREIGN KEY (track_id, id, checkpoint_manifest_sha256)
                    REFERENCES daily_tracks.session_checkpoints(
                        track_id, progression_id, manifest_sha256
                    );
            """,
        ),
        Migration(
            name="0009_session_coordinate_application_contract",
            statement="""
                ALTER TABLE daily_tracks.tracks
                    ALTER COLUMN current_release_id DROP NOT NULL,
                    ALTER COLUMN current_strategy_session DROP NOT NULL,
                    ADD COLUMN blocked_progression_id text NULL
                        REFERENCES daily_tracks.session_progressions(id),
                    DROP CONSTRAINT tracks_lifecycle_state_check;

                UPDATE daily_tracks.tracks AS track
                SET blocked_progression_id = track.blocked_target_release_id,
                    blocked_target_release_id = NULL
                WHERE track.status = 'blocked'
                  AND track.blocked_progression_id IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM daily_tracks.session_progressions AS progression
                      WHERE progression.id = track.blocked_target_release_id
                        AND progression.track_id = track.id
                        AND progression.status = 'blocked'
                  );

                ALTER TABLE daily_tracks.tracks
                    ADD CONSTRAINT tracks_lifecycle_state_check CHECK (
                        (status IN ('active', 'stopped')
                            AND blocked_target_release_id IS NULL
                            AND blocked_progression_id IS NULL
                            AND blocked_reason IS NULL)
                        OR
                        (status = 'blocked'
                            AND blocked_reason IS NOT NULL
                            AND (
                                (blocked_target_release_id IS NOT NULL
                                    AND blocked_progression_id IS NULL)
                                OR
                                (blocked_target_release_id IS NULL
                                    AND blocked_progression_id IS NOT NULL)
                            ))
                    );

                ALTER TABLE daily_tracks.retry_receipts
                    ALTER COLUMN target_release_id DROP NOT NULL,
                    ADD COLUMN progression_id text NULL
                        REFERENCES daily_tracks.session_progressions(id),
                    ADD CONSTRAINT retry_receipts_one_target_check CHECK (
                        (target_release_id IS NOT NULL
                            AND progression_id IS NULL)
                        OR
                        (target_release_id IS NULL
                            AND progression_id IS NOT NULL)
                );
            """,
        ),
        Migration(
            name="0010_contract_release_coordinate_storage",
            statement="""
                DO $migration$
                BEGIN
                    IF EXISTS (SELECT 1 FROM daily_tracks.progressions)
                       OR EXISTS (SELECT 1 FROM daily_tracks.checkpoints)
                       OR EXISTS (SELECT 1 FROM daily_tracks.progression_attempts)
                       OR EXISTS (
                           SELECT 1 FROM daily_tracks.tracks
                           WHERE current_release_id IS NOT NULL
                              OR current_strategy_session IS NOT NULL
                              OR head_manifest_sha256 IS NOT NULL
                              OR blocked_target_release_id IS NOT NULL
                       )
                       OR EXISTS (
                           SELECT 1 FROM daily_tracks.retry_receipts
                           WHERE target_release_id IS NOT NULL
                       )
                       OR EXISTS (
                           SELECT 1 FROM daily_tracks.tracks AS track
                           WHERE NOT EXISTS (
                               SELECT 1
                               FROM daily_tracks.session_tracking_states AS state
                               WHERE state.track_id = track.id
                           )
                       ) THEN
                        RAISE EXCEPTION '%',
                            'UNSUPPORTED_LEGACY_DATASET_RELEASE_STATE: '
                            || 'run the private development-reset command or perform '
                            || 'a separately managed migration before current-data cutover';
                    END IF;
                END
                $migration$;

                DROP TABLE daily_tracks.progression_attempts;
                DROP TABLE daily_tracks.checkpoints;
                DROP TABLE daily_tracks.progressions;

                ALTER TABLE daily_tracks.tracks
                    DROP CONSTRAINT tracks_lifecycle_state_check,
                    DROP COLUMN current_release_id,
                    DROP COLUMN current_strategy_session,
                    DROP COLUMN head_manifest_sha256,
                    DROP COLUMN blocked_target_release_id,
                    ADD CONSTRAINT tracks_lifecycle_state_check CHECK (
                        (status IN ('active', 'stopped')
                            AND blocked_progression_id IS NULL
                            AND blocked_reason IS NULL)
                        OR
                        (status = 'blocked'
                            AND blocked_progression_id IS NOT NULL
                            AND blocked_reason IS NOT NULL)
                    );

                ALTER TABLE daily_tracks.retry_receipts
                    DROP CONSTRAINT retry_receipts_one_target_check,
                    DROP COLUMN target_release_id,
                    ALTER COLUMN progression_id SET NOT NULL;
            """,
        ),
    ),
)

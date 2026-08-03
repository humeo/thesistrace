from thesistrace._postgres import Migration, MigrationPlan

MIGRATIONS = MigrationPlan(
    schema="data",
    ledger_table="schema_migrations",
    lock_name="thesistrace-core-data-migrations",
    migrations=(
        Migration(
            name="0001_empty_data_state",
            statement="""
                CREATE TABLE data.state (
                    singleton smallint PRIMARY KEY CHECK (singleton = 1),
                    status text NOT NULL CHECK (status IN ('idle', 'updating', 'failed')),
                    latest_update_outcome text NULL CHECK (
                        latest_update_outcome IS NULL OR
                        latest_update_outcome IN ('published', 'no_change', 'failed')
                    ),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );

                INSERT INTO data.state (singleton, status)
                VALUES (1, 'idle');

                CREATE TABLE data.releases (
                    id text PRIMARY KEY,
                    predecessor_id text NULL REFERENCES data.releases(id),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
        Migration(
            name="0002_dataset_update_and_publication",
            statement="""
                ALTER TABLE data.releases
                    ADD COLUMN manifest_sha256 text NOT NULL,
                    ADD COLUMN source_name text NOT NULL,
                    ADD COLUMN collection_kind text NOT NULL,
                    ADD COLUMN canonical_schema text NOT NULL,
                    ADD COLUMN session_start text NOT NULL,
                    ADD COLUMN session_end text NOT NULL,
                    ADD COLUMN session_count integer NOT NULL CHECK (session_count > 0);

                CREATE UNIQUE INDEX data_releases_manifest_sha256_idx
                    ON data.releases (manifest_sha256);

                CREATE TABLE data.update_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    status text NOT NULL CHECK (
                        status IN ('accepted', 'running', 'published', 'no_change', 'failed')
                    ),
                    release_id text NULL REFERENCES data.releases(id),
                    failure_reason text NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );

                CREATE UNIQUE INDEX data_one_active_update_idx
                    ON data.update_receipts ((true))
                    WHERE status IN ('accepted', 'running');

                CREATE TABLE data.update_attempts (
                    id bigserial PRIMARY KEY,
                    request_id text NOT NULL REFERENCES data.update_receipts(request_id),
                    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
                    started_at timestamptz NOT NULL DEFAULT now(),
                    finished_at timestamptz NULL
                );

                CREATE TABLE data.fields (
                    field_id text PRIMARY KEY,
                    definition jsonb NOT NULL
                );

                CREATE TABLE data.release_fields (
                    release_id text NOT NULL REFERENCES data.releases(id),
                    field_id text NOT NULL REFERENCES data.fields(field_id),
                    PRIMARY KEY (release_id, field_id)
                );
            """,
        ),
        Migration(
            name="0003_authoritative_release_head",
            statement="""
                ALTER TABLE data.releases
                    ADD COLUMN appended_session_start text NULL,
                    ADD COLUMN appended_session_end text NULL;

                UPDATE data.releases
                SET appended_session_start = session_start,
                    appended_session_end = session_end;

                ALTER TABLE data.releases
                    ALTER COLUMN appended_session_start SET NOT NULL,
                    ALTER COLUMN appended_session_end SET NOT NULL;

                ALTER TABLE data.state
                    ADD COLUMN latest_release_id text NULL REFERENCES data.releases(id);

                UPDATE data.state
                SET latest_release_id = (
                    SELECT id
                    FROM data.releases
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                )
                WHERE singleton = 1;
            """,
        ),
        Migration(
            name="0004_release_provenance_compatibility",
            statement="""
                ALTER TABLE data.releases
                    ADD COLUMN provenance_version smallint NOT NULL DEFAULT 1
                    CHECK (provenance_version IN (1, 2));

                UPDATE data.releases AS release
                SET provenance_version = 2
                FROM data.update_receipts AS receipt,
                     data.schema_migrations AS migration
                WHERE receipt.release_id = release.id
                  AND receipt.status = 'published'
                  AND migration.name = '0003_authoritative_release_head'
                  AND receipt.updated_at > migration.applied_at;

                DO $migration$
                DECLARE
                    release_count integer;
                    head_count integer;
                BEGIN
                    SELECT count(*) INTO release_count FROM data.releases;
                    SELECT count(*) INTO head_count
                    FROM data.releases AS candidate
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM data.releases AS child
                        WHERE child.predecessor_id = candidate.id
                    );
                    IF release_count > 0 AND head_count <> 1 THEN
                        RAISE EXCEPTION
                            'Dataset Release graph has no unique authoritative head';
                    END IF;
                END
                $migration$;

                UPDATE data.state
                SET latest_release_id = (
                    SELECT candidate.id
                    FROM data.releases AS candidate
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM data.releases AS child
                        WHERE child.predecessor_id = candidate.id
                    )
                )
                WHERE singleton = 1;

                ALTER TABLE data.releases
                    ALTER COLUMN provenance_version DROP DEFAULT;
            """,
        ),
    ),
)

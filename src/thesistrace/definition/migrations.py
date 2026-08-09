from thesistrace._postgres import Migration, MigrationPlan

MIGRATIONS = MigrationPlan(
    schema="definitions",
    ledger_table="schema_migrations",
    lock_name="thesistrace-core-definition-migrations",
    migrations=(
        Migration(
            name="0001_mutable_definitions",
            statement="""
                CREATE TABLE definitions.records (
                    id text PRIMARY KEY,
                    revision integer NOT NULL CHECK (revision > 0),
                    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );

                CREATE INDEX definitions_records_updated_idx
                    ON definitions.records (updated_at DESC, id);
            """,
        ),
        Migration(
            name="0002_definition_run_receipts",
            statement="""
                CREATE TABLE definitions.run_receipts (
                    request_id text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    definition_id text NOT NULL REFERENCES definitions.records(id),
                    saved_revision integer NOT NULL CHECK (saved_revision > 0),
                    saved_content jsonb NOT NULL CHECK (
                        jsonb_typeof(saved_content) = 'object'
                    ),
                    outcome text NOT NULL CHECK (outcome = 'rejected'),
                    issues jsonb NOT NULL CHECK (jsonb_typeof(issues) = 'array'),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
            """,
        ),
        Migration(
            name="0003_accepted_definition_runs",
            statement="""
                ALTER TABLE definitions.run_receipts
                    DROP CONSTRAINT run_receipts_outcome_check,
                    ADD COLUMN research_run_id text NULL,
                    ADD COLUMN dataset_release_id text NULL,
                    ADD CONSTRAINT run_receipts_outcome_check CHECK (
                        outcome IN ('rejected', 'accepted')
                    ),
                    ADD CONSTRAINT run_receipts_admission_shape_check CHECK (
                        (
                            outcome = 'rejected'
                            AND research_run_id IS NULL
                            AND dataset_release_id IS NULL
                        ) OR (
                            outcome = 'accepted'
                            AND research_run_id IS NOT NULL
                            AND dataset_release_id IS NOT NULL
                            AND issues = '[]'::jsonb
                        )
                    );
            """,
        ),
        Migration(
            name="0004_current_data_run_receipts",
            statement="""
                ALTER TABLE definitions.run_receipts
                    DROP CONSTRAINT run_receipts_admission_shape_check,
                    DROP COLUMN dataset_release_id,
                    ADD CONSTRAINT run_receipts_admission_shape_check CHECK (
                        (
                            outcome = 'rejected'
                            AND research_run_id IS NULL
                        ) OR (
                            outcome = 'accepted'
                            AND research_run_id IS NOT NULL
                            AND issues = '[]'::jsonb
                        )
                    );
            """,
        ),
    ),
)

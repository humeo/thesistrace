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
    ),
)

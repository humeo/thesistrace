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
    ),
)

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
    ),
)

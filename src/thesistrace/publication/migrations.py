from thesistrace._postgres import Migration, MigrationPlan

MIGRATIONS = MigrationPlan(
    schema="publication",
    ledger_table="schema_migrations",
    lock_name="thesistrace-core-publication-migrations",
    migrations=(
        Migration(
            name="0001_immutable_publications",
            statement="""
                CREATE TABLE publication.objects (
                    sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
                    byte_size bigint NOT NULL CHECK (byte_size >= 0),
                    created_at timestamptz NOT NULL DEFAULT now()
                );

                CREATE TABLE publication.manifests (
                    sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
                    schema_version integer NOT NULL,
                    kind text NOT NULL,
                    manifest_bytes bytea NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                );

                CREATE TABLE publication.manifest_objects (
                    manifest_sha256 text NOT NULL
                        REFERENCES publication.manifests(sha256),
                    ordinal integer NOT NULL CHECK (ordinal >= 0),
                    logical_name text NOT NULL,
                    object_sha256 text NOT NULL
                        REFERENCES publication.objects(sha256),
                    PRIMARY KEY (manifest_sha256, ordinal),
                    UNIQUE (manifest_sha256, logical_name)
                );
            """,
        ),
    ),
)

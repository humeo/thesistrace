from __future__ import annotations

from importlib.resources import files

from psycopg import sql

from thesistrace._postgres import (
    PostgresDatabase,
    SchemaDefinition,
    initialize_schemas,
    verify_schemas,
)

CORE_SCHEMAS = (
    "researchers",
    "publication",
    "data",
    "research_folders",
    "research_runs",
    "research_batches",
    "daily_tracks",
)
_SCHEMA_PACKAGES = {
    "researchers": "researcher",
    "research_runs": "research_run",
    "research_batches": "research_batch",
    "daily_tracks": "daily_track",
    "research_folders": "research_folder",
}

CORE_SCHEMA_DEFINITIONS = tuple(
    SchemaDefinition(
        name=schema,
        statement=files(f"thesistrace.{_SCHEMA_PACKAGES.get(schema, schema)}")
        .joinpath("schema.sql")
        .read_text(),
    )
    for schema in CORE_SCHEMAS
)
_CORE_RUNTIME_ROLE = "core_runtime"
_AUTH_RUNTIME_ROLE = "auth_runtime"
_CORE_METADATA_SCHEMA = "thesistrace_meta"


def initialize_core(database_url: str) -> bool:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        return initialize_schemas(database, CORE_SCHEMA_DEFINITIONS)
    finally:
        database.close()


def configure_core_runtime_access(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        verify_core_schema(database)
        with database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtext('thesistrace-core-runtime-access'))"
            )
            core_role = sql.Identifier(_CORE_RUNTIME_ROLE)
            auth_role = sql.Identifier(_AUTH_RUNTIME_ROLE)
            for schema_name in CORE_SCHEMAS:
                schema = sql.Identifier(schema_name)
                transaction.execute(
                    sql.SQL(
                        "REVOKE ALL PRIVILEGES ON SCHEMA {} FROM PUBLIC, {}, {}"
                    ).format(
                        schema,
                        core_role,
                        auth_role,
                    )
                )
                transaction.execute(
                    sql.SQL(
                        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} "
                        "FROM PUBLIC, {}, {}"
                    ).format(schema, core_role, auth_role)
                )
                transaction.execute(
                    sql.SQL(
                        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} "
                        "FROM PUBLIC, {}, {}"
                    ).format(schema, core_role, auth_role)
                )
                transaction.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        schema, core_role
                    )
                )
                transaction.execute(
                    sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                        "IN SCHEMA {} TO {}"
                    ).format(schema, core_role)
                )
                transaction.execute(
                    sql.SQL(
                        "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES "
                        "IN SCHEMA {} TO {}"
                    ).format(schema, core_role)
                )

            metadata_schema = sql.Identifier(_CORE_METADATA_SCHEMA)
            transaction.execute(
                sql.SQL(
                    "REVOKE ALL PRIVILEGES ON SCHEMA {} FROM PUBLIC, {}, {}"
                ).format(
                    metadata_schema,
                    core_role,
                    auth_role,
                )
            )
            transaction.execute(
                sql.SQL(
                    "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} "
                    "FROM PUBLIC, {}, {}"
                ).format(metadata_schema, core_role, auth_role)
            )
            transaction.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    metadata_schema, core_role
                )
            )
            transaction.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                    metadata_schema, core_role
                )
            )
    finally:
        database.close()


def verify_core_schema(database: PostgresDatabase) -> None:
    verify_schemas(database, CORE_SCHEMA_DEFINITIONS)

__all__ = (
    "CORE_SCHEMAS",
    "configure_core_runtime_access",
    "initialize_core",
    "verify_core_schema",
)

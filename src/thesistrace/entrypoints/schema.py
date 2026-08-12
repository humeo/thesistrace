from __future__ import annotations

from importlib.resources import files

from thesistrace._postgres import (
    PostgresDatabase,
    SchemaDefinition,
    initialize_schemas,
    verify_schemas,
)

CORE_SCHEMAS = (
    "publication",
    "data",
    "research_folders",
    "definitions",
    "research_runs",
    "daily_tracks",
)
_SCHEMA_PACKAGES = {
    "definitions": "definition",
    "research_runs": "research_run",
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


def initialize_core(database_url: str) -> bool:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        return initialize_schemas(database, CORE_SCHEMA_DEFINITIONS)
    finally:
        database.close()


def verify_core_schema(database: PostgresDatabase) -> None:
    verify_schemas(database, CORE_SCHEMA_DEFINITIONS)

__all__ = ("CORE_SCHEMAS", "initialize_core", "verify_core_schema")

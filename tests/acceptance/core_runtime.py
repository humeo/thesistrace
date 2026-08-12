from fastapi import FastAPI

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app as create_core_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core


def create_initialized_test_app(settings: CoreSettings | None = None) -> FastAPI:
    selected_settings = settings or CoreSettings.from_environment()
    initialize_core(selected_settings.database_url)
    return create_core_app(selected_settings)


def drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in (
                "thesistrace_meta",
                "daily_tracks",
                "research_runs",
                "definitions",
                "research_folders",
                "publication",
                "data",
            ):
                transaction.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    finally:
        database.close()

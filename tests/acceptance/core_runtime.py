from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app as create_core_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core


def isolated_core_settings(data_mount: Path) -> CoreSettings:
    return replace(
        CoreSettings.from_environment(),
        data_mount=data_mount,
        batch_attempt_control_directory=(
            data_mount.parent
            / f"{data_mount.name}-batch-attempt-control"
            / ".batch-attempts"
        ),
    )


def create_initialized_test_app(settings: CoreSettings | None = None) -> FastAPI:
    selected_settings = settings or CoreSettings.from_environment()
    initialize_core(selected_settings.database_url)
    return create_core_app(selected_settings)


def drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        database.close()

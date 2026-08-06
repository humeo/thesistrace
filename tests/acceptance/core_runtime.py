from fastapi import FastAPI

from thesistrace.entrypoints.http import create_app as create_core_app
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings


def create_migrated_test_app(settings: CoreSettings | None = None) -> FastAPI:
    selected_settings = settings or CoreSettings.from_environment()
    migrate_core(selected_settings.database_url)
    return create_core_app(selected_settings)

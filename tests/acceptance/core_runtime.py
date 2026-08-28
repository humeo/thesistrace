from dataclasses import replace
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Request

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app as create_core_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core
from thesistrace.researcher import ResearcherIdentity, ResearcherService

TEST_PUBLIC_ORIGIN = "https://core.test"
TEST_RESEARCHER = ResearcherIdentity(
    researcher_id=UUID("018f6f7e-8342-7c9a-a4df-9a86147d2e01"),
    email="researcher@example.test",
    display_label="researcher",
)


class _TestSessionVerifier:
    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        return TEST_RESEARCHER


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
    database = PostgresDatabase(selected_settings.database_url)
    database.open()
    try:
        ResearcherService(database).bootstrap(TEST_RESEARCHER)
    finally:
        database.close()
    app = create_core_app(
        selected_settings,
        auth_verifier=_TestSessionVerifier(),
        public_origin=TEST_PUBLIC_ORIGIN,
    )

    @app.middleware("http")
    async def add_explicit_test_origin(request: Request, call_next):  # type: ignore[no-untyped-def]
        if (
            request.url.path.startswith("/api/")
            and request.method in {"POST", "PATCH", "DELETE"}
            and "origin" not in request.headers
        ):
            request.scope["headers"] = [
                *request.scope["headers"],
                (b"origin", TEST_PUBLIC_ORIGIN.encode("ascii")),
            ]
        return await call_next(request)

    return app


def drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        database.close()

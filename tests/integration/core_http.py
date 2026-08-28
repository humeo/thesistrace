from uuid import UUID

from fastapi import FastAPI, Request

from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.researcher import ResearcherIdentity

TEST_PUBLIC_ORIGIN = "https://core.test"
TEST_RESEARCHER = ResearcherIdentity(
    researcher_id=UUID("018f6f7e-8342-7c9a-a4df-9a86147d2e02"),
    email="integration@example.test",
    display_label="integration",
)


class _TestSessionVerifier:
    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        return TEST_RESEARCHER


def create_authenticated_core_app(settings: CoreSettings) -> FastAPI:
    app = create_app(
        settings,
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

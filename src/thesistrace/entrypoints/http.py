from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from thesistrace.data import (
    DataOverview,
    ReleaseHistory,
    ReleaseSummary,
    UpdateAcceptance,
)
from thesistrace.data.service import DataUpdateConflict
from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings, open_core_runtime


class DataUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def create_app(settings: CoreSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        selected_settings = settings or CoreSettings.from_environment()
        with open_core_runtime(selected_settings) as runtime:
            app.state.core_runtime = runtime
            yield

    app = FastAPI(title="ThesisTrace Core", lifespan=lifespan)

    @app.get("/api/data", response_model=DataOverview)
    def data_overview(request: Request) -> DataOverview:
        return _runtime(request).data.overview()

    @app.get("/api/data/releases", response_model=ReleaseHistory)
    def data_releases(request: Request) -> ReleaseHistory:
        return _runtime(request).data.list_releases()

    @app.get("/api/data/releases/{release_id}", response_model=ReleaseSummary)
    def data_release(request: Request, release_id: str) -> ReleaseSummary:
        release = _runtime(request).data.get_release(release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="Dataset Release not found")
        return release

    @app.post(
        "/api/data/update",
        response_model=UpdateAcceptance,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def update_data(
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        _command: Annotated[DataUpdateRequest | None, Body()] = None,
    ) -> UpdateAcceptance:
        try:
            return _runtime(request).data.update(idempotency_key)
        except DataUpdateConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def _runtime(request: Request) -> CoreRuntime:
    return request.app.state.core_runtime


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical ThesisTrace Core HTTP adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    arguments = parser.parse_args()
    uvicorn.run(app, host=arguments.host, port=arguments.port, log_level="warning")


if __name__ == "__main__":
    main()

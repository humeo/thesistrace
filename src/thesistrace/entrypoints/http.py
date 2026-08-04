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
from thesistrace.definition import (
    DefinitionAuthoringOptions,
    DefinitionConflict,
    DefinitionDetail,
    DefinitionList,
    DefinitionRunCommand,
    DefinitionRunConflict,
    DefinitionRunOutcome,
    DefinitionSaveCommand,
)
from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings, open_core_runtime
from thesistrace.research_run import ResearchRunList, ResearchRunSummary


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

    @app.post("/api/definitions/run", response_model=DefinitionRunOutcome)
    def run_new_definition(
        request: Request,
        command: DefinitionRunCommand,
    ) -> DefinitionRunOutcome:
        return _run_definition(request, None, command)

    @app.post(
        "/api/definitions/{definition_id}/run",
        response_model=DefinitionRunOutcome,
    )
    def run_existing_definition(
        request: Request,
        definition_id: str,
        command: DefinitionRunCommand,
    ) -> DefinitionRunOutcome:
        return _run_definition(request, definition_id, command)

    @app.get("/api/definitions", response_model=DefinitionList)
    def list_definitions(request: Request) -> DefinitionList:
        return _runtime(request).definitions.list()

    @app.get(
        "/api/definitions/authoring-options",
        response_model=DefinitionAuthoringOptions,
    )
    def definition_authoring_options(request: Request) -> DefinitionAuthoringOptions:
        return _runtime(request).definitions.authoring_options()

    @app.get("/api/definitions/{definition_id}", response_model=DefinitionDetail)
    def get_definition(request: Request, definition_id: str) -> DefinitionDetail:
        definition = _runtime(request).definitions.get(definition_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Research Definition not found")
        return definition

    @app.get("/api/research-runs", response_model=ResearchRunList)
    def list_research_runs(request: Request) -> ResearchRunList:
        return _runtime(request).research_runs.list()

    @app.get("/api/research-runs/{run_id}", response_model=ResearchRunSummary)
    def get_research_run(request: Request, run_id: str) -> ResearchRunSummary:
        run = _runtime(request).research_runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.post(
        "/api/definitions",
        response_model=DefinitionDetail,
        status_code=status.HTTP_201_CREATED,
    )
    def create_definition(
        request: Request,
        command: DefinitionSaveCommand,
    ) -> DefinitionDetail:
        try:
            return _runtime(request).definitions.create(command)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.put("/api/definitions/{definition_id}", response_model=DefinitionDetail)
    def save_definition(
        request: Request,
        definition_id: str,
        command: DefinitionSaveCommand,
    ) -> DefinitionDetail:
        try:
            definition = _runtime(request).definitions.save(definition_id, command)
        except DefinitionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"current_revision": error.current_revision},
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if definition is None:
            raise HTTPException(status_code=404, detail="Research Definition not found")
        return definition

    return app


def _runtime(request: Request) -> CoreRuntime:
    return request.app.state.core_runtime


def _run_definition(
    request: Request,
    definition_id: str | None,
    command: DefinitionRunCommand,
) -> DefinitionRunOutcome:
    try:
        return _runtime(request).definitions.run(definition_id, command)
    except DefinitionRunConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DefinitionConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"current_revision": error.current_revision},
        ) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research Definition not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical ThesisTrace Core HTTP adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    arguments = parser.parse_args()
    uvicorn.run(app, host=arguments.host, port=arguments.port, log_level="warning")


if __name__ == "__main__":
    main()

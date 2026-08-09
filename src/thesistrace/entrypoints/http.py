from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status

from thesistrace.daily_track import (
    DailyTrackActivationLimitReached,
    DailyTrackDetail,
    DailyTrackDetailUnavailable,
    DailyTrackList,
    DailyTrackRetryConflict,
    DailyTrackRetryUnavailable,
    DailyTrackStopConflict,
    DailyTrackStopUnavailable,
    DailyTrackSummary,
    RetryDailyTrackCommand,
    StopDailyTrackCommand,
)
from thesistrace.data import DataOverview
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
from thesistrace.research_run import (
    ResearchRunCancelCommand,
    ResearchRunCancelConflict,
    ResearchRunDetail,
    ResearchRunList,
    ResearchRunRerunCommand,
    ResearchRunRerunConflict,
    ResearchRunResultUnavailable,
    ResearchRunStartTrackingConflict,
    ResearchRunSummary,
    ResearchRunTrackingTemporarilyUnavailable,
    ResearchRunTrackingUnavailable,
    StartTrackingCommand,
)


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
        return _runtime(request).data_overview.overview()

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

    @app.get(
        "/api/research-runs/{run_id}",
        response_model=ResearchRunDetail,
    )
    def get_research_run(request: Request, run_id: str) -> ResearchRunDetail:
        try:
            run = _runtime(request).research_runs.get_detail(run_id)
        except ResearchRunResultUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="ResearchRun Result unavailable",
            ) from error
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.post(
        "/api/research-runs/{run_id}/cancel",
        response_model=ResearchRunSummary,
    )
    def cancel_research_run(
        request: Request,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunSummary:
        try:
            run = _runtime(request).research_runs.cancel(run_id, command)
        except ResearchRunCancelConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.post(
        "/api/research-runs/{run_id}/rerun",
        response_model=ResearchRunSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def rerun_research_run(
        request: Request,
        run_id: str,
        command: ResearchRunRerunCommand,
    ) -> ResearchRunSummary:
        try:
            run = _runtime(request).research_runs.rerun(run_id, command)
        except ResearchRunRerunConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.post(
        "/api/research-runs/{run_id}/daily-tracks",
        response_model=DailyTrackSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def start_tracking(
        request: Request,
        run_id: str,
        command: StartTrackingCommand,
    ) -> DailyTrackSummary:
        try:
            track = _runtime(request).research_runs.start_tracking(run_id, command)
        except DailyTrackActivationLimitReached as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunStartTrackingConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunTrackingUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunTrackingTemporarilyUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if track is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return track

    @app.get("/api/daily-tracks", response_model=DailyTrackList)
    def list_daily_tracks(request: Request) -> DailyTrackList:
        return _runtime(request).daily_tracks.list()

    @app.get("/api/daily-tracks/{track_id}", response_model=DailyTrackDetail)
    def get_daily_track(request: Request, track_id: str) -> DailyTrackDetail:
        try:
            track = _runtime(request).daily_tracks.get(track_id)
        except DailyTrackDetailUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="DailyTrack detail is unavailable",
            ) from error
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    @app.post(
        "/api/daily-tracks/{track_id}/retry",
        response_model=DailyTrackSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_daily_track(
        request: Request,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DailyTrackSummary:
        try:
            track = _runtime(request).daily_tracks.retry(track_id, command)
        except DailyTrackRetryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackRetryUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    @app.post(
        "/api/daily-tracks/{track_id}/stop",
        response_model=DailyTrackSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def stop_daily_track(
        request: Request,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DailyTrackSummary:
        try:
            track = _runtime(request).daily_tracks.stop(track_id, command)
        except DailyTrackStopConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackStopUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

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

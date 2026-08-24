from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from thesistrace.daily_track import (
    DailyTrackActivationLimitReached,
    DailyTrackDeleteConflict,
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
from thesistrace.entrypoints.alpha_http import install_alpha_http
from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings, open_core_runtime
from thesistrace.research_batch import (
    ResearchBatchAdmissionCommand,
    ResearchBatchAdmissionConflict,
    ResearchBatchAdmissionIssue,
    ResearchBatchAdmissionRejected,
    ResearchBatchAdmissionRejection,
    ResearchBatchDetail,
    ResearchBatchList,
)
from thesistrace.research_folder import (
    CreateResearchFolder,
    RenameResearchFolder,
    ResearchFolderConflict,
    ResearchFolderList,
    ResearchFolderSummary,
)
from thesistrace.research_run import (
    OrganizeResearchRunCommand,
    ResearchKind,
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionConflict,
    ResearchRunAdmissionRejected,
    ResearchRunAdmissionRejection,
    ResearchRunCancelCommand,
    ResearchRunCancelConflict,
    ResearchRunDeleteConflict,
    ResearchRunDetail,
    ResearchRunList,
    ResearchRunOrganizationConflict,
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

    @app.exception_handler(RequestValidationError)
    async def admission_validation_error(
        request: Request,
        error: RequestValidationError,
    ):
        if request.method == "POST" and request.url.path == "/api/research-batches":
            rejection = ResearchBatchAdmissionRejection(
                issues=_batch_admission_validation_issues(error)
            )
            return JSONResponse(
                status_code=422,
                content=rejection.model_dump(mode="json"),
            )
        return await request_validation_exception_handler(request, error)
    install_alpha_http(
        app,
        financial_authoring_ready=lambda request: (
            _runtime(request).data_overview.overview().financial_research_readiness
        ),
    )

    @app.get("/health/live", include_in_schema=False)
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/data", response_model=DataOverview)
    def data_overview(request: Request) -> DataOverview:
        return _runtime(request).data_overview.overview()

    @app.get("/api/research-folders", response_model=ResearchFolderList)
    def list_research_folders(request: Request) -> ResearchFolderList:
        return _runtime(request).research_folders.list()

    @app.post(
        "/api/research-folders",
        response_model=ResearchFolderSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def create_research_folder(
        request: Request,
        command: CreateResearchFolder,
    ) -> ResearchFolderSummary:
        return _runtime(request).research_folders.create(command)

    @app.patch(
        "/api/research-folders/{folder_id}",
        response_model=ResearchFolderSummary,
    )
    def rename_research_folder(
        request: Request,
        folder_id: str,
        command: RenameResearchFolder,
    ) -> ResearchFolderSummary:
        try:
            folder = _runtime(request).research_folders.rename(folder_id, command)
        except ResearchFolderConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if folder is None:
            raise HTTPException(status_code=404, detail="Research Folder not found")
        return folder

    @app.delete(
        "/api/research-folders/{folder_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_research_folder(request: Request, folder_id: str) -> None:
        try:
            deleted = _runtime(request).research_folders.delete(folder_id)
        except ResearchFolderConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="Research Folder not found")

    @app.post(
        "/api/research-batches",
        response_model=ResearchBatchDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def admit_research_batch(
        request: Request,
        command: ResearchBatchAdmissionCommand,
    ) -> ResearchBatchDetail | JSONResponse:
        try:
            return _runtime(request).research_batches.admit(command)
        except ResearchBatchAdmissionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchBatchAdmissionRejected as error:
            rejection = ResearchBatchAdmissionRejection(issues=error.issues)
            return JSONResponse(
                status_code=422,
                content=rejection.model_dump(mode="json"),
            )

    @app.get("/api/research-batches", response_model=ResearchBatchList)
    def list_research_batches(
        request: Request,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> ResearchBatchList:
        try:
            return _runtime(request).research_batches.list(cursor=cursor, limit=limit)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get(
        "/api/research-batches/{batch_id}",
        response_model=ResearchBatchDetail,
    )
    def get_research_batch(request: Request, batch_id: str) -> ResearchBatchDetail:
        batch = _runtime(request).research_batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Research Batch not found")
        return batch

    @app.post(
        "/api/research-runs",
        response_model=ResearchRunSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def admit_research_run(
        request: Request,
        command: ResearchRunAdmissionCommand,
    ) -> ResearchRunSummary | JSONResponse:
        try:
            return _runtime(request).research_runs.admit(command)
        except ResearchRunAdmissionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunAdmissionRejected as error:
            rejection = ResearchRunAdmissionRejection(issues=error.issues)
            return JSONResponse(
                status_code=422,
                content=rejection.model_dump(mode="json"),
            )

    @app.get("/api/research-runs", response_model=ResearchRunList)
    def list_research_runs(
        request: Request,
        folder_id: str | None = None,
        research_kind: ResearchKind | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> ResearchRunList:
        try:
            return _runtime(request).research_runs.list(
                folder_id=folder_id,
                research_kind=research_kind,
                cursor=cursor,
                limit=limit,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.patch(
        "/api/research-runs/{run_id}",
        response_model=ResearchRunSummary,
    )
    def organize_research_run(
        request: Request,
        run_id: str,
        command: OrganizeResearchRunCommand,
    ) -> ResearchRunSummary:
        try:
            run = _runtime(request).research_runs.organize(run_id, command)
        except ResearchRunOrganizationConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

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

    @app.delete(
        "/api/research-runs/{run_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_research_run(request: Request, run_id: str) -> None:
        try:
            deleted = _runtime(request).research_runs.delete(run_id)
        except ResearchRunDeleteConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="ResearchRun not found")

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

    @app.delete(
        "/api/daily-tracks/{track_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_daily_track(request: Request, track_id: str) -> None:
        try:
            deleted = _runtime(request).daily_tracks.delete(track_id)
        except DailyTrackDeleteConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="DailyTrack not found")

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

    return app


def _batch_admission_validation_issues(
    error: RequestValidationError,
) -> list[ResearchBatchAdmissionIssue]:
    body = error.body if isinstance(error.body, Mapping) else {}
    return [
        ResearchBatchAdmissionIssue(
            code="INVALID_BATCH_INPUT",
            field=_batch_validation_field(issue.get("loc", ())),
            item_key=_batch_validation_item_key(body, issue.get("loc", ())),
            message=str(issue.get("msg", "Research Batch input is invalid")),
        )
        for issue in error.errors()
    ]


def _batch_validation_field(location: object) -> str:
    components = _batch_validation_components(location)
    field = ""
    for component in components:
        if isinstance(component, int):
            field = f"{field}[{component}]"
        elif isinstance(component, str):
            field = f"{field}.{component}" if field else component
    return field or "batch"


def _batch_validation_item_key(
    body: Mapping[object, object],
    location: object,
) -> str | None:
    components = _batch_validation_components(location)
    for array_name in ("factors", "strategies"):
        if array_name not in components:
            continue
        position = components.index(array_name)
        ordinal = (
            components[position + 1]
            if position + 1 < len(components)
            and isinstance(components[position + 1], int)
            else 20
        )
        items = body.get(array_name)
        if not isinstance(items, list) or not 0 <= ordinal < len(items):
            return None
        item = items[ordinal]
        if not isinstance(item, Mapping):
            return None
        item_key = item.get("item_key")
        if not isinstance(item_key, str) or not item_key.strip():
            return None
        return item_key.strip()
    return None


def _batch_validation_components(location: object) -> list[str | int]:
    if not isinstance(location, Sequence) or isinstance(location, (str, bytes)):
        return []
    return [
        component
        for component in location
        if isinstance(component, (str, int))
        and component not in {"body", "factor_evaluation", "strategy_sweep"}
    ]


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

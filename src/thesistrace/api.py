from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from thesistrace.config import Settings, settings_from_environment
from thesistrace.datasets import DatasetPublisher, InvalidFixtureError
from thesistrace.definitions import DefinitionValidationError, ResearchDefinitionService
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import MetadataStore
from thesistrace.tracking import DailyTrackingError, DailyTrackingService
from thesistrace.tushare_source import (
    HttpTushareTransport,
    TushareAdapter,
    TushareSourceError,
    TushareTransport,
    normalize_tushare_snapshot,
)


class BootstrapRequest(BaseModel):
    fixture: str


class LiveBootstrapRequest(BaseModel):
    as_of: date


class PriceCorrection(BaseModel):
    session: str
    instrument_id: str
    field: str
    value: str


class FixtureIncrementRequest(BaseModel):
    new_sessions: int
    corrections: list[PriceCorrection]


class KernelUpgradeRequest(BaseModel):
    calculation_kernel: str
    numeric_execution_contract: str


def create_app(
    settings: Settings,
    *,
    tushare_transport: TushareTransport | None = None,
) -> FastAPI:
    store = MetadataStore(settings.metadata_path)
    store.initialize()
    objects = ImmutableObjectStore(settings.object_root)
    publisher = DatasetPublisher(store, objects)
    definitions = ResearchDefinitionService(store, publisher)
    research_runs = ResearchRunService(store, publisher, objects)
    tracking = DailyTrackingService(store, publisher, objects)
    source_transport = tushare_transport or HttpTushareTransport()
    app = FastAPI(title="ThesisTrace", version="0.1.0")

    @app.get("/api/v1/workspace")
    def get_workspace() -> dict[str, object]:
        return {
            "installation_id": store.installation_id(),
            "resource_counts": store.resource_counts(),
            "latest_dataset_release": store.latest_dataset_release(),
        }

    @app.get("/api/v1/research-definitions")
    def list_research_definitions() -> dict[str, object]:
        return {"items": store.list_research_drafts()}

    @app.post("/api/v1/research-definitions")
    def create_research_definition(content: dict[str, object]) -> JSONResponse:
        return JSONResponse(status_code=201, content=definitions.create_draft(content))

    @app.get("/api/v1/research-definitions/{draft_id}")
    def get_research_definition(draft_id: str) -> dict[str, object]:
        draft = store.research_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="research definition draft not found")
        return draft

    @app.put("/api/v1/research-definitions/{draft_id}")
    def update_research_definition(draft_id: str, content: dict[str, object]) -> dict[str, object]:
        draft = definitions.update_draft(draft_id, content)
        if draft is None:
            raise HTTPException(status_code=404, detail="research definition draft not found")
        return draft

    @app.post("/api/v1/research-definitions/{draft_id}/runs")
    def request_research_run(
        draft_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            frozen, run, created = definitions.request_run(draft_id, idempotency_key)
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail="research definition draft not found"
            ) from error
        except DefinitionValidationError as error:
            raise HTTPException(status_code=422, detail={"errors": error.errors}) from error
        return JSONResponse(
            status_code=202 if created else 200,
            content={"frozen_definition": frozen, "run": run},
        )

    @app.get("/api/v1/research-definition-versions/{version_id}")
    def get_research_definition_version(version_id: str) -> dict[str, object]:
        frozen = store.frozen_research_definition(version_id)
        if frozen is None:
            raise HTTPException(status_code=404, detail="frozen definition not found")
        return frozen

    @app.get("/api/v1/research-definition-versions")
    def list_research_definition_versions() -> dict[str, object]:
        return {"items": store.list_frozen_research_definitions()}

    @app.get("/api/v1/research-runs")
    def list_research_runs() -> dict[str, object]:
        return {"items": store.list_research_runs()}

    @app.get("/api/v1/research-runs/{run_id}")
    def get_research_run(run_id: str) -> dict[str, object]:
        run = store.research_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.get("/api/v1/research-runs/{run_id}/result")
    def get_research_run_result(run_id: str) -> dict[str, object]:
        try:
            result = research_runs.result_view(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="ResearchRun not found") from error
        if result is None:
            raise HTTPException(
                status_code=409,
                detail="ResearchRun has no successful Result Bundle",
            )
        return result

    @app.post("/api/v1/research-runs/{run_id}/cancel")
    def cancel_research_run(run_id: str) -> dict[str, object]:
        run = store.cancel_research_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.post("/api/v1/research-runs/{run_id}/rerun")
    def rerun_research(
        run_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            run, created = store.create_research_rerun(run_id, idempotency_key)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="ResearchRun not found") from error
        return JSONResponse(status_code=202 if created else 200, content=run)

    @app.post("/api/v1/research-runs/{run_id}/daily-tracks")
    def activate_daily_track(
        run_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            track, created = tracking.activate(run_id, idempotency_key)
        except DailyTrackingError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=201 if created else 200, content=track)

    @app.get("/api/v1/daily-tracks")
    def list_daily_tracks() -> dict[str, object]:
        return {"items": tracking.list_tracks()}

    @app.get("/api/v1/daily-tracks/{track_id}")
    def get_daily_track(track_id: str) -> dict[str, object]:
        track = tracking.get_track(track_id)
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    @app.get("/api/v1/daily-tracks/{track_id}/current")
    def get_daily_track_current_view(track_id: str) -> dict[str, object]:
        try:
            return tracking.current_view(track_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="DailyTrack not found") from error
        except DailyTrackingError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/daily-tracks/{track_id}/stop")
    def stop_daily_track(track_id: str) -> dict[str, object]:
        track = tracking.stop(track_id)
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    @app.post("/api/v1/daily-tracks/{track_id}/kernel-upgrade")
    def upgrade_daily_track_kernel(
        track_id: str,
        request: KernelUpgradeRequest,
    ) -> dict[str, object]:
        try:
            return tracking.upgrade_kernel(
                track_id,
                calculation_kernel=request.calculation_kernel,
                numeric_execution_contract=request.numeric_execution_contract,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="DailyTrack not found") from error
        except DailyTrackingError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/daily-tracks/{track_id}/verify-equivalence")
    def verify_daily_track(track_id: str) -> dict[str, object]:
        try:
            return tracking.verify_equivalence(track_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="DailyTrack not found") from error
        except DailyTrackingError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/health")
    def get_health() -> dict[str, object]:
        heartbeat = store.last_worker_heartbeat()
        worker_available = (
            heartbeat is not None
            and (datetime.now(UTC) - heartbeat).total_seconds()
            <= settings.worker_stale_after_seconds
        )
        object_store_available = probe_object_store(settings.object_root)
        status = "available" if worker_available and object_store_available else "degraded"
        return {
            "status": status,
            "components": {
                "database": {"status": "available"},
                "object_store": {
                    "status": "available" if object_store_available else "unavailable"
                },
                "worker": {
                    "status": "available" if worker_available else "unavailable",
                    "last_heartbeat_at": heartbeat.isoformat() if heartbeat else None,
                },
            },
        }

    @app.post("/api/v1/dataset-releases/bootstrap")
    def bootstrap_dataset_release(
        request: BootstrapRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            release, created = publisher.bootstrap(idempotency_key, request.fixture)
        except InvalidFixtureError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(
            status_code=201 if created else 200,
            content={"status": "succeeded", "release": release},
        )

    @app.post("/api/v1/sources/tushare/preflight")
    def preflight_tushare() -> dict[str, object]:
        if not settings.tushare_token:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "TOKEN_MISSING", "source_code": None},
            )
        adapter = TushareAdapter(
            token=settings.tushare_token,
            transport=source_transport,
        )
        try:
            return adapter.preflight()
        except TushareSourceError as error:
            raise HTTPException(status_code=424, detail=error.diagnostic()) from error

    @app.post("/api/v1/dataset-releases/bootstrap-live")
    def bootstrap_live_dataset_release(
        request: LiveBootstrapRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        if not settings.tushare_token:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "TOKEN_MISSING", "source_code": None},
            )
        adapter = TushareAdapter(
            token=settings.tushare_token,
            transport=source_transport,
        )
        try:
            adapter.preflight()
            snapshot = adapter.collect_bootstrap_snapshot(request.as_of)
            source, canonical = normalize_tushare_snapshot(snapshot)
            release, created = publisher.bootstrap_documents(
                idempotency_key,
                source=source,
                canonical=canonical,
                source_kind="source_tushare",
                source_schema="tushare-v1",
            )
        except TushareSourceError as error:
            raise HTTPException(status_code=424, detail=error.diagnostic()) from error
        except InvalidFixtureError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(
            status_code=201 if created else 200,
            content={"status": "succeeded", "release": release},
        )

    @app.post("/api/v1/dataset-releases/publish-fixture")
    def publish_fixture_increment(
        request: FixtureIncrementRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            release, created = publisher.publish_fixture_increment(
                idempotency_key,
                new_sessions=request.new_sessions,
                corrections=[item.model_dump() for item in request.corrections],
            )
        except (InvalidFixtureError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if created:
            tracking.enqueue_active_tracks(str(release["id"]))
        return JSONResponse(
            status_code=201 if created else 200,
            content={"status": "succeeded", "release": release},
        )

    @app.get("/api/v1/dataset-releases")
    def list_dataset_releases() -> dict[str, object]:
        return {"items": store.list_dataset_releases()}

    @app.get("/api/v1/dataset-releases/{release_id}")
    def get_dataset_release(release_id: str) -> dict[str, object]:
        release = store.dataset_release(release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="dataset release not found")
        return release

    @app.get("/api/v1/dataset-releases/{release_id}/data-contract")
    def get_dataset_contract(release_id: str) -> dict[str, object]:
        release = store.dataset_release(release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="dataset release not found")
        try:
            return publisher.data_contract(release)
        except InvalidFixtureError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/objects/{digest}")
    def get_object(digest: str) -> FileResponse:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise HTTPException(status_code=404, detail="object not found")
        path = objects.path_for(digest)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="object not found")
        return FileResponse(
            path,
            media_type="application/json",
            headers={"ETag": f'"sha256:{digest}"', "Cache-Control": "public, immutable"},
        )

    return app


def probe_object_store(root: Path) -> bool:
    probe_path = root / f".health-{uuid4()}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe_path.write_bytes(b"ok")
        return probe_path.read_bytes() == b"ok"
    except OSError:
        return False
    finally:
        probe_path.unlink(missing_ok=True)


def main() -> None:
    uvicorn.run(create_app(settings_from_environment()), host="127.0.0.1", port=8000)

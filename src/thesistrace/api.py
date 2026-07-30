from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from thesistrace.config import Settings, settings_from_environment
from thesistrace.datasets import DatasetPublisher, InvalidFixtureError
from thesistrace.definitions import DefinitionValidationError, ResearchDefinitionService
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.storage import DatasetPublicationConflict, MetadataStore
from thesistrace.tracking import (
    DailyTrackingError,
    DailyTrackingService,
    EquivalenceError,
)
from thesistrace.tushare_source import (
    HttpTushareTransport,
    TushareAdapter,
    TushareSourceError,
    TushareTransport,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)
from thesistrace.working_cache import WorkingCacheStore


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


def error_detail(reason_code: str, message: str) -> dict[str, str]:
    return {"reason_code": reason_code, "message": message}


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
    cache_root = settings.working_cache_root or settings.metadata_path.parent / "working-cache"
    tracking = DailyTrackingService(
        store,
        publisher,
        objects,
        WorkingCacheStore(cache_root),
    )
    tracking.reconcile_cache_deletions()
    source_transport = tushare_transport or HttpTushareTransport()
    app = FastAPI(title="ThesisTrace", version="0.1.0")

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": error_detail(
                    "REQUEST_VALIDATION_FAILED",
                    "request validation failed",
                )
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        _request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        if isinstance(error.detail, dict):
            detail = error.detail
        else:
            reason_code = (
                "ROUTE_NOT_FOUND"
                if error.status_code == 404
                else "METHOD_NOT_ALLOWED"
                if error.status_code == 405
                else f"HTTP_{error.status_code}"
            )
            detail = error_detail(reason_code, str(error.detail))
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": detail},
            headers=error.headers,
        )

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
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_NOT_FOUND",
                    "research definition draft not found",
                ),
            )
        return draft

    @app.put("/api/v1/research-definitions/{draft_id}")
    def update_research_definition(draft_id: str, content: dict[str, object]) -> dict[str, object]:
        draft = definitions.update_draft(draft_id, content)
        if draft is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_NOT_FOUND",
                    "research definition draft not found",
                ),
            )
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
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_NOT_FOUND",
                    "research definition draft not found",
                ),
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
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_VERSION_NOT_FOUND",
                    "frozen definition not found",
                ),
            )
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
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            )
        return run

    @app.get("/api/v1/research-runs/{run_id}/attempts/{ordinal}")
    def get_research_run_attempt(run_id: str, ordinal: int) -> dict[str, object]:
        run = store.research_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            )
        attempts = run.get("attempts")
        if isinstance(attempts, list):
            for attempt in attempts:
                if isinstance(attempt, dict) and attempt.get("ordinal") == ordinal:
                    return attempt
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "RESEARCH_RUN_ATTEMPT_NOT_FOUND",
                "ResearchRun Attempt not found",
            ),
        )

    @app.get("/api/v1/research-runs/{run_id}/result")
    def get_research_run_result(run_id: str) -> dict[str, object]:
        try:
            result = research_runs.result_view(run_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            ) from error
        if result is None:
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "RESULT_BUNDLE_UNAVAILABLE",
                    "ResearchRun has no successful Result Bundle",
                ),
            )
        return result

    @app.post("/api/v1/research-runs/{run_id}/cancel")
    def cancel_research_run(run_id: str) -> dict[str, object]:
        run = store.cancel_research_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            )
        return run

    @app.post("/api/v1/research-runs/{run_id}/rerun")
    def rerun_research(
        run_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            run, created = store.create_research_rerun(run_id, idempotency_key)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            ) from error
        return JSONResponse(status_code=202 if created else 200, content=run)

    @app.post("/api/v1/research-runs/{run_id}/daily-tracks")
    def activate_daily_track(
        run_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            track, created = tracking.activate(run_id, idempotency_key)
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error
        return JSONResponse(status_code=201 if created else 200, content=track)

    @app.get("/api/v1/daily-tracks")
    def list_daily_tracks() -> dict[str, object]:
        return {"items": tracking.list_tracks()}

    @app.get("/api/v1/daily-tracks/{track_id}")
    def get_daily_track(track_id: str) -> dict[str, object]:
        track = tracking.get_track(track_id)
        if track is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            )
        return track

    def get_track_child(
        track_id: str,
        collection: str,
        child_id: str,
        reason_code: str,
        label: str,
    ) -> dict[str, object]:
        track = tracking.get_track(track_id)
        if track is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            )
        children = track.get(collection)
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict) and child.get("id") == child_id:
                    return child
        raise HTTPException(
            status_code=404,
            detail=error_detail(reason_code, f"{label} not found"),
        )

    @app.get("/api/v1/daily-tracks/{track_id}/generations/{generation_id}")
    def get_daily_track_generation(track_id: str, generation_id: str) -> dict[str, object]:
        return get_track_child(
            track_id,
            "generations",
            generation_id,
            "TRACKING_GENERATION_NOT_FOUND",
            "Tracking Generation",
        )

    @app.get("/api/v1/daily-tracks/{track_id}/advances/{advance_id}")
    def get_daily_track_advance(track_id: str, advance_id: str) -> dict[str, object]:
        return get_track_child(
            track_id,
            "advances",
            advance_id,
            "TRACKING_ADVANCE_NOT_FOUND",
            "Tracking Advance",
        )

    @app.get("/api/v1/daily-tracks/{track_id}/checkpoints/{checkpoint_id}")
    def get_daily_track_checkpoint(track_id: str, checkpoint_id: str) -> dict[str, object]:
        return get_track_child(
            track_id,
            "checkpoints",
            checkpoint_id,
            "TRACKING_CHECKPOINT_NOT_FOUND",
            "Tracking Checkpoint",
        )

    @app.get("/api/v1/daily-tracks/{track_id}/current")
    def get_daily_track_current_view(track_id: str) -> dict[str, object]:
        try:
            return tracking.current_view(track_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error

    @app.post("/api/v1/daily-tracks/{track_id}/stop")
    def stop_daily_track(track_id: str) -> dict[str, object]:
        track = tracking.stop(track_id)
        if track is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            )
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
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error

    @app.post("/api/v1/daily-tracks/{track_id}/verify-equivalence")
    def verify_daily_track(track_id: str) -> dict[str, object]:
        try:
            return tracking.verify_equivalence(track_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            ) from error
        except EquivalenceError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("EQUIVALENCE_MISMATCH", str(error)),
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error

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
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
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
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
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
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except (InvalidFixtureError, ValueError) as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
        try:
            enqueue_failures = tracking.enqueue_active_tracks(str(release["id"]))
        except Exception:
            enqueue_failures = [
                {
                    "track_id": "*",
                    "reason_code": "TRACK_ENQUEUE_FAILED",
                    "message": "tracking reconciliation will retry",
                }
            ]
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "status": "succeeded",
                "release": release,
                "tracking_enqueue_failures": enqueue_failures,
            },
        )

    @app.post("/api/v1/dataset-releases/publish-live")
    def publish_live_increment(
        request: LiveBootstrapRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        existing = store.dataset_release_for_idempotency_key(idempotency_key)
        if existing is not None:
            try:
                enqueue_failures = tracking.enqueue_active_tracks(str(existing["id"]))
            except Exception:
                enqueue_failures = [
                    {
                        "track_id": "*",
                        "reason_code": "TRACK_ENQUEUE_FAILED",
                        "message": "tracking reconciliation will retry",
                    }
                ]
            return JSONResponse(
                status_code=200,
                content={
                    "status": "succeeded",
                    "release": existing,
                    "tracking_enqueue_failures": enqueue_failures,
                },
            )
        if not settings.tushare_token:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "TOKEN_MISSING", "source_code": None},
            )
        predecessor = store.latest_dataset_release()
        if predecessor is None:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "LIVE_BOOTSTRAP_REQUIRED"},
            )
        schemas = predecessor.get("schemas")
        if not isinstance(schemas, list) or not any(
            isinstance(item, dict) and item.get("family") == "source_tushare"
            for item in schemas
        ):
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "LIVE_PREDECESSOR_REQUIRED"},
            )
        try:
            canonical = publisher.materialize_canonical(predecessor)
            instruments = canonical.get("instruments")
            calendar = canonical.get("research_calendar")
            if (
                not isinstance(instruments, list)
                or not isinstance(calendar, list)
                or not calendar
            ):
                raise InvalidFixtureError("predecessor canonical data is incomplete")
            adapter = TushareAdapter(
                token=settings.tushare_token,
                transport=source_transport,
            )
            snapshot = adapter.collect_incremental_snapshot(
                last_session=str(calendar[-1]),
                known_ts_codes={
                    str(item["ts_code"])
                    for item in instruments
                    if isinstance(item, dict)
                },
                as_of=request.as_of,
            )
            source, canonical_delta = normalize_tushare_increment(snapshot, canonical)
            release, created = publisher.publish_increment_documents(
                idempotency_key,
                source=source,
                canonical_delta=canonical_delta,
                source_schema="tushare-v1",
            )
        except TushareSourceError as error:
            raise HTTPException(status_code=424, detail=error.diagnostic()) from error
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
        try:
            enqueue_failures = tracking.enqueue_active_tracks(str(release["id"]))
        except Exception:
            enqueue_failures = [
                {
                    "track_id": "*",
                    "reason_code": "TRACK_ENQUEUE_FAILED",
                    "message": "tracking reconciliation will retry",
                }
            ]
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "status": "succeeded",
                "release": release,
                "tracking_enqueue_failures": enqueue_failures,
            },
        )

    @app.get("/api/v1/dataset-releases")
    def list_dataset_releases() -> dict[str, object]:
        return {"items": store.list_dataset_releases()}

    @app.get("/api/v1/dataset-releases/{release_id}")
    def get_dataset_release(release_id: str) -> dict[str, object]:
        release = store.dataset_release(release_id)
        if release is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DATASET_RELEASE_NOT_FOUND", "dataset release not found"),
            )
        return release

    @app.get("/api/v1/dataset-releases/{release_id}/data-contract")
    def get_dataset_contract(release_id: str) -> dict[str, object]:
        release = store.dataset_release(release_id)
        if release is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DATASET_RELEASE_NOT_FOUND", "dataset release not found"),
            )
        try:
            return publisher.data_contract(release)
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DATA_CONTRACT_UNAVAILABLE", str(error)),
            ) from error

    @app.get("/api/v1/objects/{digest}")
    def get_object(digest: str) -> FileResponse:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise HTTPException(
                status_code=404,
                detail=error_detail("IMMUTABLE_OBJECT_NOT_FOUND", "object not found"),
            )
        json_path = objects.path_for(digest)
        parquet_path = objects.parquet_path_for(digest)
        if json_path.is_file():
            path = json_path
            media_type = "application/json"
        elif parquet_path.is_file():
            path = parquet_path
            media_type = "application/vnd.apache.parquet"
        else:
            raise HTTPException(
                status_code=404,
                detail=error_detail("IMMUTABLE_OBJECT_NOT_FOUND", "object not found"),
            )
        return FileResponse(
            path,
            media_type=media_type,
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

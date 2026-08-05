import os
from datetime import UTC, date, datetime

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from thesistrace.config import Settings, settings_from_environment
from thesistrace.datasets import DatasetPublisher, InvalidFixtureError
from thesistrace.objects import ImmutableObjectStore
from thesistrace.runtime import RuntimePorts, build_runtime
from thesistrace.storage import DatasetPublicationConflict
from thesistrace.tushare_source import (
    HttpTushareTransport,
    TushareAdapter,
    TushareSourceError,
    TushareTransport,
    normalize_tushare_increment,
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


def error_detail(reason_code: str, message: str) -> dict[str, str]:
    return {"reason_code": reason_code, "message": message}


def page(items: list[dict[str, object]], offset: int, limit: int) -> dict[str, object]:
    selected = items[offset : offset + limit]
    return {
        "items": selected,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(selected) < len(items),
    }


def create_app(
    settings: Settings,
    *,
    tushare_transport: TushareTransport | None = None,
    runtime_ports: RuntimePorts | None = None,
) -> FastAPI:
    runtime = runtime_ports or build_runtime(settings)
    store = runtime.control_metadata
    objects = runtime.objects
    publisher = DatasetPublisher(store, objects)
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

    @app.get("/api/v1/health")
    def get_health() -> dict[str, object]:
        heartbeat = store.last_worker_heartbeat()
        worker_available = (
            heartbeat is not None
            and (datetime.now(UTC) - heartbeat).total_seconds()
            <= settings.worker_stale_after_seconds
        )
        object_store_available = objects.ready()
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

    @app.get("/api/v1/live")
    def get_liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/api/v1/ready")
    def get_readiness():
        try:
            store.last_worker_heartbeat()
            object_store_ready = objects.ready()
        except Exception:
            object_store_ready = False
        if not object_store_ready:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready"},
            )
        return {"status": "ready"}

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
        return JSONResponse(
            status_code=201 if created else 200,
            content={"status": "succeeded", "release": release},
        )

    @app.post("/api/v1/dataset-releases/publish-live")
    def publish_live_increment(
        request: LiveBootstrapRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        existing = store.dataset_release_for_idempotency_key(idempotency_key)
        if existing is not None:
            return JSONResponse(
                status_code=200,
                content={"status": "succeeded", "release": existing},
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
            isinstance(item, dict) and item.get("family") == "source_tushare" for item in schemas
        ):
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "LIVE_PREDECESSOR_REQUIRED"},
            )
        try:
            canonical = publisher.materialize_canonical_tail(predecessor, 20)
            instruments = canonical.get("instruments")
            calendar = canonical.get("research_calendar")
            if not isinstance(instruments, list) or not isinstance(calendar, list) or not calendar:
                raise InvalidFixtureError("predecessor canonical data is incomplete")
            adapter = TushareAdapter(
                token=settings.tushare_token,
                transport=source_transport,
            )
            snapshot = adapter.collect_incremental_snapshot(
                last_session=str(calendar[-1]),
                known_ts_codes={
                    str(item["ts_code"]) for item in instruments if isinstance(item, dict)
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
        return JSONResponse(
            status_code=201 if created else 200,
            content={"status": "succeeded", "release": release},
        )

    @app.get("/api/v1/dataset-releases")
    def list_dataset_releases(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, object]:
        return page(store.list_dataset_releases(), offset, limit)

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
        if not isinstance(objects, ImmutableObjectStore):
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "IMMUTABLE_OBJECT_NOT_FOUND",
                    "object not found",
                ),
            )
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
                detail=error_detail(
                    "IMMUTABLE_OBJECT_NOT_FOUND",
                    "object not found",
                ),
            )
        return FileResponse(
            path,
            media_type=media_type,
            headers={"ETag": f'"sha256:{digest}"', "Cache-Control": "public, immutable"},
        )

    return app


def main() -> None:
    uvicorn.run(
        create_app(settings_from_environment()),
        host=os.environ.get("THESISTRACE_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("THESISTRACE_API_PORT", "8000")),
        log_config=None,
    )

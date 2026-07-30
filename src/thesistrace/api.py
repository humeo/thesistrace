from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from thesistrace.config import Settings, settings_from_environment
from thesistrace.datasets import DatasetPublisher, InvalidFixtureError
from thesistrace.objects import ImmutableObjectStore
from thesistrace.storage import MetadataStore


class BootstrapRequest(BaseModel):
    fixture: str


def create_app(settings: Settings) -> FastAPI:
    store = MetadataStore(settings.metadata_path)
    store.initialize()
    objects = ImmutableObjectStore(settings.object_root)
    publisher = DatasetPublisher(store, objects)
    app = FastAPI(title="ThesisTrace", version="0.1.0")

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

    @app.get("/api/v1/dataset-releases/{release_id}")
    def get_dataset_release(release_id: str) -> dict[str, object]:
        release = store.dataset_release(release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="dataset release not found")
        return release

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

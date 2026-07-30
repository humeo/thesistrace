from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI

from thesistrace.config import Settings
from thesistrace.storage import MetadataStore


def create_app(settings: Settings) -> FastAPI:
    store = MetadataStore(settings.metadata_path)
    store.initialize()
    app = FastAPI(title="ThesisTrace", version="0.1.0")

    @app.get("/api/v1/workspace")
    def get_workspace() -> dict[str, object]:
        return {
            "installation_id": store.installation_id(),
            "resource_counts": store.resource_counts(),
            "latest_dataset_release": None,
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
    settings = Settings(
        metadata_path=Path(".local/metadata.sqlite3"),
        object_root=Path(".local/objects"),
    )
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8000)

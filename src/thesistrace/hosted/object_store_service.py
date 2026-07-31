import fcntl
import hmac
import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import BinaryIO
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from thesistrace.hosted.observability import configure_observability, instrument_http
from thesistrace.objects import (
    ImmutableObjectStore,
    ParquetContractError,
    StagedObjectStore,
    canonical_json_bytes,
)
from thesistrace.storage_admission import (
    DEFAULT_ALL_WRITE_REJECTION_PERCENT,
    DEFAULT_DISK_WARNING_PERCENT,
    DEFAULT_PERSISTENT_DISK_BYTES,
    DEFAULT_PRIVATE_WRITE_REJECTION_PERCENT,
    DiskPressurePolicy,
    StorageAdmissionError,
)

MAINTENANCE_ROLES = {"api", "compute", "data"}
LEASE_SECONDS = 30.0
logger = logging.getLogger(__name__)


@dataclass
class FileLease:
    role: str
    run_id: str
    attempt_id: str | None
    handle: BinaryIO
    expires_at: float


class GuardRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = Lock()
        self.leases: dict[str, FileLease] = {}

    def acquire(self, run_id: str, role: str) -> tuple[str, int]:
        bucket = __import__("hashlib").sha256(
            run_id.encode("utf-8")
        ).hexdigest()[:2]
        path = self.root / "staging" / f".run-{bucket}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self._reap_expired_locked()
            handle = path.open("a+b")
            try:
                fcntl.flock(
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError:
                handle.close()
                raise
            token = f"guard_{uuid4().hex}"
            self.leases[token] = FileLease(
                role=role,
                run_id=run_id,
                attempt_id=None,
                handle=handle,
                expires_at=time.monotonic() + LEASE_SECONDS,
            )
            return token, int(LEASE_SECONDS)

    def renew(self, token: str, role: str) -> int:
        with self.lock:
            self._reap_expired_locked()
            lease = self.leases.get(token)
            if lease is None or lease.role != role:
                raise KeyError(token)
            lease.expires_at = time.monotonic() + LEASE_SECONDS
        return int(LEASE_SECONDS)

    def release(self, token: str) -> None:
        with self.lock:
            lease = self.leases.pop(token, None)
        if lease is None:
            return
        self._close(lease)

    def _reap_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, lease in self.leases.items()
            if lease.expires_at <= now
        ]
        for token in expired:
            self._close(self.leases.pop(token))

    @staticmethod
    def _close(lease: FileLease) -> None:
        fcntl.flock(lease.handle.fileno(), fcntl.LOCK_UN)
        lease.handle.close()


class StageRegistry:
    def __init__(self) -> None:
        self.lock = Lock()
        self.leases: dict[str, FileLease] = {}

    def open(
        self,
        *,
        run_id: str,
        attempt_id: str,
        role: str,
        lock_path: Path,
    ) -> tuple[str, int]:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        try:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            handle.close()
            raise
        token = f"stage_{uuid4().hex}"
        with self.lock:
            self._reap_expired_locked()
            self.leases[token] = FileLease(
                role=role,
                run_id=run_id,
                attempt_id=attempt_id,
                handle=handle,
                expires_at=time.monotonic() + LEASE_SECONDS,
            )
        return token, int(LEASE_SECONDS)

    def authorize(
        self,
        token: str,
        *,
        run_id: str,
        attempt_id: str,
        role: str,
    ) -> int:
        with self.lock:
            self._reap_expired_locked()
            lease = self.leases.get(token)
            if (
                lease is None
                or lease.role != role
                or lease.run_id != run_id
                or lease.attempt_id != attempt_id
            ):
                raise KeyError(token)
            lease.expires_at = time.monotonic() + LEASE_SECONDS
        return int(LEASE_SECONDS)

    def close(self, token: str) -> None:
        with self.lock:
            lease = self.leases.pop(token, None)
        if lease is not None:
            GuardRegistry._close(lease)

    def reap_expired(self) -> None:
        with self.lock:
            self._reap_expired_locked()

    def has_active_run(self, run_id: str) -> bool:
        with self.lock:
            self._reap_expired_locked()
            return any(
                lease.run_id == run_id
                for lease in self.leases.values()
            )

    def _reap_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, lease in self.leases.items()
            if lease.expires_at <= now
        ]
        for token in expired:
            GuardRegistry._close(self.leases.pop(token))


def create_object_store_app(
    root: Path,
    role_tokens: dict[str, str],
    *,
    disk_capacity_bytes: int = DEFAULT_PERSISTENT_DISK_BYTES,
    disk_warning_percent: int = DEFAULT_DISK_WARNING_PERCENT,
    private_write_rejection_percent: int = (
        DEFAULT_PRIVATE_WRITE_REJECTION_PERCENT
    ),
    all_write_rejection_percent: int = (
        DEFAULT_ALL_WRITE_REJECTION_PERCENT
    ),
    disk_used_bytes: Callable[[], int] | None = None,
) -> FastAPI:
    if set(role_tokens) != {"api", "compute", "data"} or any(
        not token for token in role_tokens.values()
    ):
        raise ValueError(
            "ObjectStore requires distinct api, compute, and data tokens"
        )
    if len(set(role_tokens.values())) != len(role_tokens):
        raise ValueError("ObjectStore role tokens must be distinct")
    store = ImmutableObjectStore(root)
    disk_policy = DiskPressurePolicy(
        disk_capacity_bytes,
        warning_percent=disk_warning_percent,
        private_write_rejection_percent=private_write_rejection_percent,
        all_write_rejection_percent=all_write_rejection_percent,
    )
    if disk_used_bytes is None:
        def current_disk_usage() -> int:
            return shutil.disk_usage(
                root if root.exists() else root.parent
            ).used

        disk_used_bytes = current_disk_usage
    guards = GuardRegistry(root)
    stages = StageRegistry()
    app = FastAPI(title="ThesisTrace Private ObjectStore")
    instrument_http(app)

    def admit_growth(role: str, candidate_bytes: int) -> None:
        decision = disk_policy.evaluate(
            used_bytes=int(disk_used_bytes()),
            candidate_bytes=candidate_bytes,
            private_growth=role != "data",
        )
        if decision.warning:
            logger.warning(
                "persistent disk warning threshold reached "
                "projected_percent=%.2f role=%s",
                decision.projected_percent,
                role,
            )

    def admit_object_payload(
        role: str,
        writer: ImmutableObjectStore,
        payload: bytes,
        *,
        suffix: str,
    ) -> None:
        digest = __import__("hashlib").sha256(payload).hexdigest()
        destination = (
            writer.root / "sha256" / digest[:2] / f"{digest}{suffix}"
        )
        admit_growth(role, 0 if destination.exists() else len(payload))

    def admit_manifest_payload(
        role: str,
        writer: ImmutableObjectStore,
        resource_id: str,
        payload: bytes,
    ) -> None:
        destination = writer.root / "manifests" / f"{resource_id}.json"
        admit_growth(role, 0 if destination.exists() else len(payload))

    def require_role(
        request: Request,
        allowed: set[str],
    ) -> str:
        authorization = request.headers.get("Authorization", "")
        supplied = (
            authorization.removeprefix("Bearer ")
            if authorization.startswith("Bearer ")
            else ""
        )
        for role, token in role_tokens.items():
            if hmac.compare_digest(supplied, token):
                if role not in allowed:
                    raise HTTPException(status_code=403)
                return role
        raise HTTPException(status_code=401)

    def stage_store(
        run_id: str,
        attempt_id: str,
        request: Request,
        role: str,
    ) -> tuple[StagedObjectStore, str]:
        token = request.headers.get("X-Stage-Token", "")
        try:
            stages.authorize(
                token,
                run_id=path_identity(run_id),
                attempt_id=path_identity(attempt_id),
                role=role,
            )
        except KeyError as error:
            raise HTTPException(status_code=403) from error
        stage = StagedObjectStore(
            store,
            run_id=path_identity(run_id),
            attempt_id=path_identity(attempt_id),
            cleanup_uncommitted_payloads=False,
        )
        metadata_path = stage.root / ".remote-stage.json"
        if not metadata_path.exists():
            raise HTTPException(status_code=404)
        metadata = read_object(metadata_path)
        stage.cleanup_uncommitted_payloads = bool(
            metadata["cleanup_uncommitted_payloads"]
        )
        if metadata.get("owner_role") != role:
            raise HTTPException(status_code=403)
        return stage, token

    def require_stage_role(
        role: str,
        run_id: str,
        *,
        operation: str = "write",
    ) -> None:
        write_prefixes = {
            "api": ("track_",),
            "compute": ("run_", "advance_"),
            "data": ("dsp_",),
        }
        recover_prefixes = {
            **write_prefixes,
            "api": ("track_", "run_"),
        }
        prefixes = (
            recover_prefixes
            if operation == "recover"
            else write_prefixes
        )
        if not path_identity(run_id).startswith(
            prefixes.get(role, ())
        ):
            raise HTTPException(status_code=403)

    def require_manifest_role(
        role: str,
        resource_id: str,
    ) -> None:
        allowed_prefixes = {
            "api": ("checkpoint_",),
            "compute": ("result_", "checkpoint_"),
            "data": ("dsr_",),
        }
        if not path_identity(resource_id).startswith(
            allowed_prefixes.get(role, ())
        ):
            raise HTTPException(status_code=403)

    @app.exception_handler(ParquetContractError)
    async def parquet_error(
        _request: Request,
        _error: ParquetContractError,
    ) -> Response:
        return Response(status_code=422)

    @app.exception_handler(StorageAdmissionError)
    async def storage_admission_error(
        _request: Request,
        error: StorageAdmissionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=507,
            content={
                "detail": {
                    "reason_code": error.reason_code,
                    "message": str(error),
                    "dimension": error.dimension,
                    "limit": error.limit,
                }
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        if not root.is_dir() or not os.access(
            root,
            os.R_OK | os.W_OK | os.X_OK,
        ):
            raise HTTPException(status_code=503)
        return {"status": "ready"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        used_bytes = int(disk_used_bytes())
        used_ratio = used_bytes / disk_capacity_bytes
        return (
            "# HELP thesistrace_storage_used_bytes Persistent disk bytes used.\n"
            "# TYPE thesistrace_storage_used_bytes gauge\n"
            f"thesistrace_storage_used_bytes {used_bytes}\n"
            "# HELP thesistrace_storage_capacity_bytes Persistent disk capacity.\n"
            "# TYPE thesistrace_storage_capacity_bytes gauge\n"
            f"thesistrace_storage_capacity_bytes {disk_capacity_bytes}\n"
            "# HELP thesistrace_storage_used_ratio Persistent disk used ratio.\n"
            "# TYPE thesistrace_storage_used_ratio gauge\n"
            f"thesistrace_storage_used_ratio {used_ratio:.9f}\n"
        )

    @app.post("/v1/probe")
    def probe(request: Request) -> dict[str, str]:
        require_role(request, MAINTENANCE_ROLES)
        if not store.probe():
            raise HTTPException(status_code=503)
        return {"status": "available"}

    @app.put("/v1/objects/json")
    async def put_json(request: Request) -> dict[str, object]:
        role = require_role(request, {"compute", "data"})
        payload = await request.body()
        admit_object_payload(role, store, payload, suffix=".json")
        return store.put_canonical_json_bytes(payload)

    @app.put("/v1/objects/parquet")
    async def put_parquet(request: Request) -> dict[str, object]:
        role = require_role(request, {"compute", "data"})
        payload = await request.body()
        admit_object_payload(role, store, payload, suffix=".parquet")
        return store.put_parquet_bytes(payload)

    @app.put("/v1/manifests/{resource_id}")
    async def put_manifest(
        resource_id: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, {"compute", "data"})
        require_manifest_role(role, resource_id)
        payload = await request.body()
        value = decode_canonical_json(payload)
        normalized_resource_id = path_identity(resource_id)
        admit_manifest_payload(
            role,
            store,
            normalized_resource_id,
            payload,
        )
        store.put_manifest(normalized_resource_id, value)
        return {"status": "stored"}

    @app.get("/v1/objects/{digest}/json")
    def read_json(digest: str, request: Request) -> Response:
        require_role(request, MAINTENANCE_ROLES)
        try:
            value = store.read_json(digest_identity(digest))
        except FileNotFoundError as error:
            raise HTTPException(status_code=404) from error
        return Response(
            content=canonical_json_bytes(value),
            media_type="application/json",
        )

    @app.get("/v1/objects/{digest}/parquet")
    def read_parquet(digest: str, request: Request) -> Response:
        require_role(request, MAINTENANCE_ROLES)
        try:
            payload = store.read_parquet_bytes(
                digest_identity(digest)
            )
        except FileNotFoundError as error:
            raise HTTPException(status_code=404) from error
        return Response(
            content=payload,
            media_type="application/vnd.apache.parquet",
        )

    @app.delete("/v1/storage-objects")
    async def delete_storage_object(
        request: Request,
    ) -> dict[str, bool]:
        require_role(request, {"api"})
        body = await request.json()
        object_key = body.get("object_key")
        if not isinstance(object_key, str):
            raise HTTPException(status_code=422)
        return {"deleted": store.delete_storage_object(object_key)}

    @app.post("/v1/stages/{run_id}/attempts/{attempt_id}")
    async def open_stage(
        run_id: str,
        attempt_id: str,
        request: Request,
    ) -> dict[str, object]:
        role = require_role(request, MAINTENANCE_ROLES)
        require_stage_role(role, run_id)
        body = await request.json()
        cleanup = bool(body.get("cleanup_uncommitted_payloads"))
        stage = StagedObjectStore(
            store,
            run_id=path_identity(run_id),
            attempt_id=path_identity(attempt_id),
            cleanup_uncommitted_payloads=cleanup,
        )
        if (stage.root / ".remote-stage.json").exists():
            raise HTTPException(status_code=409)
        stage.root.mkdir(parents=True, exist_ok=True)
        token: str | None = None
        try:
            token, lease_seconds = stages.open(
                run_id=path_identity(run_id),
                attempt_id=path_identity(attempt_id),
                role=role,
                lock_path=stage.root / ".stage.lock",
            )
            write_object(
                stage.root / ".remote-stage.json",
                {
                    "cleanup_uncommitted_payloads": cleanup,
                    "owner_role": role,
                },
            )
        except BlockingIOError as error:
            raise HTTPException(status_code=409) from error
        except Exception:
            if token is not None:
                stages.close(token)
                shutil.rmtree(stage.root, ignore_errors=True)
            raise
        return {
            "status": "open",
            "stage_token": token,
            "lease_seconds": lease_seconds,
        }

    @app.put(
        "/v1/stages/{run_id}/attempts/{attempt_id}/"
        "objects/{object_format}"
    )
    async def put_stage_object(
        run_id: str,
        attempt_id: str,
        object_format: str,
        request: Request,
    ) -> dict[str, object]:
        role = require_role(request, MAINTENANCE_ROLES)
        stage, _token = stage_store(
            run_id,
            attempt_id,
            request,
            role,
        )
        payload = await request.body()
        if object_format == "json":
            admit_object_payload(
                role,
                stage.writer,
                payload,
                suffix=".json",
            )
            return stage.writer.put_canonical_json_bytes(payload)
        if object_format == "parquet":
            admit_object_payload(
                role,
                stage.writer,
                payload,
                suffix=".parquet",
            )
            return stage.writer.put_parquet_bytes(payload)
        raise HTTPException(status_code=404)

    @app.put(
        "/v1/stages/{run_id}/attempts/{attempt_id}/"
        "manifests/{resource_id}"
    )
    async def put_stage_manifest(
        run_id: str,
        attempt_id: str,
        resource_id: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, MAINTENANCE_ROLES)
        require_manifest_role(role, resource_id)
        stage, _token = stage_store(
            run_id,
            attempt_id,
            request,
            role,
        )
        payload = await request.body()
        value = decode_canonical_json(payload)
        normalized_resource_id = path_identity(resource_id)
        admit_manifest_payload(
            role,
            stage.writer,
            normalized_resource_id,
            payload,
        )
        stage.put_manifest(normalized_resource_id, value)
        return {"status": "stored"}

    @app.post(
        "/v1/stages/{run_id}/attempts/{attempt_id}/promote"
    )
    async def promote_stage(
        run_id: str,
        attempt_id: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, MAINTENANCE_ROLES)
        body = await request.json()
        stage, _token = stage_store(
            run_id,
            attempt_id,
            request,
            role,
        )
        stage.promote(
            manifest_sha256=digest_identity(
                str(body["manifest_sha256"])
            ),
            before_move=lambda: admit_growth(role, 0),
        )
        return {"status": "promoted"}

    @app.post(
        "/v1/stages/{run_id}/attempts/{attempt_id}/resolve"
    )
    def resolve_stage(
        run_id: str,
        attempt_id: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, MAINTENANCE_ROLES)
        stage, token = stage_store(
            run_id,
            attempt_id,
            request,
            role,
        )
        if not (stage.root / ".publication.json").exists():
            raise HTTPException(status_code=409)
        shutil.rmtree(stage.root, ignore_errors=True)
        remove_empty_parent(stage.root.parent)
        stages.close(token)
        return {"status": "resolved"}

    @app.delete("/v1/stages/{run_id}/attempts/{attempt_id}")
    def discard_stage(
        run_id: str,
        attempt_id: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, MAINTENANCE_ROLES)
        stage, token = stage_store(
            run_id,
            attempt_id,
            request,
            role,
        )
        if (stage.root / ".publication.json").exists():
            raise HTTPException(status_code=409)
        shutil.rmtree(stage.root, ignore_errors=True)
        remove_empty_parent(stage.root.parent)
        stages.close(token)
        return {"status": "discarded"}

    @app.post(
        "/v1/stages/{run_id}/attempts/{attempt_id}/lease"
    )
    def renew_stage(
        run_id: str,
        attempt_id: str,
        request: Request,
    ) -> dict[str, int]:
        role = require_role(request, MAINTENANCE_ROLES)
        _stage, token = stage_store(
            run_id,
            attempt_id,
            request,
            role,
        )
        return {"lease_seconds": stages.authorize(
            token,
            run_id=path_identity(run_id),
            attempt_id=path_identity(attempt_id),
            role=role,
        )}

    @app.post(
        "/v1/stages/{run_id}/attempts/{attempt_id}/release"
    )
    def release_stage(
        run_id: str,
        attempt_id: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, MAINTENANCE_ROLES)
        _stage, token = stage_store(
            run_id,
            attempt_id,
            request,
            role,
        )
        stages.close(token)
        return {"status": "released"}

    @app.post("/v1/stages/{run_id}/recover")
    async def recover_stage(
        run_id: str,
        request: Request,
    ) -> dict[str, bool]:
        role = require_role(request, MAINTENANCE_ROLES)
        require_stage_role(role, run_id, operation="recover")
        stages.reap_expired()
        body = await request.json()
        committed = body.get("committed_manifest_sha256")
        if committed is not None:
            committed = digest_identity(str(committed))
        return {
            "recovered": store.recover_staged_publication(
                path_identity(run_id),
                committed_manifest_sha256=committed,
            )
        }

    @app.get("/v1/stages")
    def staged_ids(
        prefix: str,
        request: Request,
    ) -> dict[str, list[str]]:
        role = require_role(request, MAINTENANCE_ROLES)
        require_stage_role(role, prefix)
        return {
            "ids": store.staged_publication_ids(
                prefix=path_identity(prefix)
            )
        }

    @app.post("/v1/stages/{run_id}/wait")
    def wait_for_stage(
        run_id: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, MAINTENANCE_ROLES)
        normalized_run_id = path_identity(run_id)
        require_stage_role(role, normalized_run_id)
        if (
            stages.has_active_run(normalized_run_id)
            or store.staged_publication_active(normalized_run_id)
        ):
            raise HTTPException(status_code=409)
        return {"status": "complete"}

    @app.post("/v1/guards/{run_id}")
    def acquire_guard(
        run_id: str,
        request: Request,
    ) -> dict[str, object]:
        role = require_role(request, MAINTENANCE_ROLES)
        require_stage_role(role, run_id, operation="recover")
        try:
            token, lease_seconds = guards.acquire(
                path_identity(run_id),
                role,
            )
        except BlockingIOError as error:
            raise HTTPException(status_code=409) from error
        return {
            "token": token,
            "lease_seconds": lease_seconds,
        }

    @app.post("/v1/guards/{token}/lease")
    def renew_guard(
        token: str,
        request: Request,
    ) -> dict[str, int]:
        role = require_role(request, MAINTENANCE_ROLES)
        try:
            lease_seconds = guards.renew(
                path_identity(token),
                role,
            )
        except KeyError as error:
            raise HTTPException(status_code=403) from error
        return {"lease_seconds": lease_seconds}

    @app.delete("/v1/guards/{token}")
    def release_guard(
        token: str,
        request: Request,
    ) -> dict[str, str]:
        role = require_role(request, MAINTENANCE_ROLES)
        normalized_token = path_identity(token)
        try:
            guards.renew(normalized_token, role)
        except KeyError as error:
            raise HTTPException(status_code=403) from error
        guards.release(normalized_token)
        return {"status": "released"}

    return app


def path_identity(value: str) -> str:
    if not value or "/" in value or value in {".", ".."}:
        raise HTTPException(status_code=404)
    return value


def digest_identity(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef"
        for character in value
    ):
        raise HTTPException(status_code=404)
    return value


def decode_canonical_json(payload: bytes) -> object:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParquetContractError(
            "JSON object payload is invalid"
        ) from error
    if canonical_json_bytes(value) != payload:
        raise ParquetContractError(
            "JSON object payload is not canonical"
        )
    return value


def write_object(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(canonical_json_bytes(value))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ParquetContractError(
            "remote stage metadata is invalid"
        )
    return value


def remove_empty_parent(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def main() -> None:
    configure_observability("object-store")
    root = Path(
        os.environ.get(
            "THESISTRACE_OBJECT_STORE_ROOT",
            "/var/lib/thesistrace/objects",
        )
    )
    raw_tokens = os.environ.get("THESISTRACE_OBJECT_STORE_TOKENS")
    if not raw_tokens:
        raise RuntimeError(
            "THESISTRACE_OBJECT_STORE_TOKENS is required"
        )
    tokens = json.loads(raw_tokens)
    if not isinstance(tokens, dict):
        raise RuntimeError(
            "THESISTRACE_OBJECT_STORE_TOKENS must be a JSON object"
        )
    app = create_object_store_app(
        root,
        {str(role): str(token) for role, token in tokens.items()},
        disk_capacity_bytes=int(
            os.environ.get(
                "THESISTRACE_PERSISTENT_DISK_BYTES",
                str(DEFAULT_PERSISTENT_DISK_BYTES),
            )
        ),
        disk_warning_percent=int(
            os.environ.get(
                "THESISTRACE_DISK_WARNING_PERCENT",
                str(DEFAULT_DISK_WARNING_PERCENT),
            )
        ),
        private_write_rejection_percent=int(
            os.environ.get(
                "THESISTRACE_PRIVATE_WRITE_REJECTION_PERCENT",
                str(DEFAULT_PRIVATE_WRITE_REJECTION_PERCENT),
            )
        ),
        all_write_rejection_percent=int(
            os.environ.get(
                "THESISTRACE_ALL_WRITE_REJECTION_PERCENT",
                str(DEFAULT_ALL_WRITE_REJECTION_PERCENT),
            )
        ),
    )
    uvicorn.run(app, host="0.0.0.0", port=8010, log_config=None)


if __name__ == "__main__":
    main()

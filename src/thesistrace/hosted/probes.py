import asyncio
import threading
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

READY_HEARTBEAT_STALE_SECONDS = 30.0


@dataclass
class ProcessProbeState:
    service: str
    slot: str
    _ready: bool = False
    _heartbeat_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def mark_ready(self) -> None:
        with self._lock:
            self._ready = True
            self._heartbeat_at = time.time()

    def mark_not_ready(self) -> None:
        with self._lock:
            self._ready = False
            self._heartbeat_at = time.time()

    def heartbeat(self) -> None:
        with self._lock:
            self._heartbeat_at = time.time()

    def snapshot(self) -> tuple[bool, float]:
        with self._lock:
            return self._ready, self._heartbeat_at


def create_probe_app(state: ProcessProbeState) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/live")
    def live() -> dict[str, str]:
        return {
            "service": state.service,
            "slot": state.slot,
            "status": "alive",
        }

    @app.get("/ready", status_code=200)
    def ready():
        is_ready, heartbeat_at = state.snapshot()
        is_ready = is_ready and time.time() - heartbeat_at <= READY_HEARTBEAT_STALE_SECONDS
        payload = {
            "service": state.service,
            "slot": state.slot,
            "status": "ready" if is_ready else "not_ready",
        }
        if is_ready:
            return payload
        from fastapi.responses import JSONResponse

        return JSONResponse(payload, status_code=503)

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        is_ready, heartbeat_at = state.snapshot()
        is_ready = is_ready and time.time() - heartbeat_at <= READY_HEARTBEAT_STALE_SECONDS
        service = prometheus_label(state.service)
        slot = prometheus_label(state.slot)
        return (
            "# HELP thesistrace_service_info Fixed service identity.\n"
            "# TYPE thesistrace_service_info gauge\n"
            f'thesistrace_service_info{{service="{service}",slot="{slot}"}} 1\n'
            "# HELP thesistrace_service_ready Role-specific readiness state.\n"
            "# TYPE thesistrace_service_ready gauge\n"
            f"thesistrace_service_ready {1 if is_ready else 0}\n"
            "# HELP thesistrace_service_heartbeat_timestamp_seconds "
            "Latest in-process heartbeat.\n"
            "# TYPE thesistrace_service_heartbeat_timestamp_seconds gauge\n"
            f"thesistrace_service_heartbeat_timestamp_seconds {heartbeat_at:.6f}\n"
        )

    return app


class ProcessProbeServer:
    def __init__(
        self,
        state: ProcessProbeState,
        *,
        host: str = "0.0.0.0",
        port: int = 9100,
    ) -> None:
        self.state = state
        self.server = uvicorn.Server(
            uvicorn.Config(
                create_probe_app(state),
                host=host,
                port=port,
                access_log=False,
                log_config=None,
            )
        )
        self.thread = threading.Thread(
            target=self.server.run,
            name=f"{state.service}-probe",
            daemon=True,
        )

    def __enter__(self) -> "ProcessProbeServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.state.mark_not_ready()
        self.server.should_exit = True
        self.thread.join(timeout=5)


async def monitor_role(
    awaitable: Awaitable[None],
    state: ProcessProbeState,
) -> None:
    runner = asyncio.create_task(awaitable)
    try:
        await asyncio.sleep(0.5)
        if runner.done():
            await runner
        state.mark_ready()
        while True:
            done, _pending = await asyncio.wait({runner}, timeout=10)
            if runner in done:
                await runner
                return
            state.heartbeat()
    finally:
        state.mark_not_ready()
        if not runner.done():
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


def prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

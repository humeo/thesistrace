import asyncio
import threading
from datetime import datetime

from thesistrace.hosted.temporal_worker import run_with_worker_heartbeat


def test_compute_worker_records_product_health_heartbeat() -> None:
    observed: list[datetime] = []

    async def worker() -> None:
        while not observed:
            await asyncio.sleep(0)

    asyncio.run(
        run_with_worker_heartbeat(
            worker(),
            observed.append,
            interval_seconds=0.001,
        )
    )

    assert len(observed) == 1


def test_compute_worker_survives_transient_product_heartbeat_failure() -> None:
    attempts = 0
    heartbeat_threads: list[int] = []
    event_loop_thread = threading.get_ident()

    def record_heartbeat(_recorded_at: datetime) -> None:
        nonlocal attempts
        attempts += 1
        heartbeat_threads.append(threading.get_ident())
        if attempts == 1:
            raise RuntimeError("injected database disconnect")

    async def worker() -> None:
        while attempts < 2:
            await asyncio.sleep(0)

    asyncio.run(
        run_with_worker_heartbeat(
            worker(),
            record_heartbeat,
            interval_seconds=0,
        )
    )

    assert attempts == 2
    assert heartbeat_threads
    assert all(thread_id != event_loop_thread for thread_id in heartbeat_threads)

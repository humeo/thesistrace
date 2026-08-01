import asyncio
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

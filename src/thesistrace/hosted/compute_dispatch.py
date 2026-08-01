import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client
from temporalio.common import Priority
from temporalio.service import RPCError

logger = logging.getLogger(__name__)

COMPUTE_WORKFLOW_TASK_QUEUE = "thesistrace-compute-workflows"
P1_ACTIVITY_TASK_QUEUE = "thesistrace-compute-p1"
P3_ACTIVITY_TASK_QUEUE = "thesistrace-compute-p3"
PLATFORM_FAIRNESS_KEY = "__platform__"
WORKSPACE_FAIRNESS_WEIGHT = 1.0


@dataclass(frozen=True)
class ComputeTaskQueues:
    workflow: str = COMPUTE_WORKFLOW_TASK_QUEUE
    p1: str = P1_ACTIVITY_TASK_QUEUE
    p3: str = P3_ACTIVITY_TASK_QUEUE


DEFAULT_COMPUTE_TASK_QUEUES = ComputeTaskQueues()


class ActivityWorker(Protocol):
    async def run(self) -> None: ...

    async def shutdown(self) -> None: ...


def activity_priority(workspace_id: str) -> Priority:
    if not workspace_id:
        raise ValueError("Workspace identity is required for fair dispatch")
    return Priority(
        priority_key=3,
        fairness_key=workspace_id,
        fairness_weight=WORKSPACE_FAIRNESS_WEIGHT,
    )


def platform_activity_priority() -> Priority:
    return Priority(
        priority_key=3,
        fairness_key=PLATFORM_FAIRNESS_KEY,
        fairness_weight=WORKSPACE_FAIRNESS_WEIGHT,
    )


def choose_activity_task_queue(
    preference: str,
    *,
    p1_backlog: int,
    p3_backlog: int,
    queues: ComputeTaskQueues = DEFAULT_COMPUTE_TASK_QUEUES,
) -> str:
    if preference not in {"p1", "p3"}:
        raise ValueError("Compute slot preference must be p1 or p3")
    if preference == "p1":
        return queues.p1 if p1_backlog > 0 or p3_backlog == 0 else queues.p3
    return queues.p3 if p3_backlog > 0 or p1_backlog == 0 else queues.p1


async def activity_backlogs(
    client: Client,
    namespace: str,
    queues: ComputeTaskQueues = DEFAULT_COMPUTE_TASK_QUEUES,
) -> tuple[int, int]:
    async def describe(task_queue: str) -> int:
        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=namespace,
                task_queue=TaskQueue(name=task_queue),
                task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
                report_stats=True,
            ),
            retry=True,
        )
        return int(response.stats.approximate_backlog_count)

    return tuple(
        await asyncio.gather(
            describe(queues.p1),
            describe(queues.p3),
        )
    )


async def run_preferred_activity_poller(
    *,
    preference: str,
    worker_factory: Callable[[str], ActivityWorker],
    backlog: Callable[[], Awaitable[tuple[int, int]]],
    poll_interval_seconds: float = 1.0,
    queues: ComputeTaskQueues = DEFAULT_COMPUTE_TASK_QUEUES,
) -> None:
    if preference not in {"p1", "p3"}:
        raise ValueError("Compute slot preference must be p1 or p3")
    current_queue = queues.p1 if preference == "p1" else queues.p3
    while True:
        worker = worker_factory(current_queue)
        runner = asyncio.create_task(worker.run())
        try:
            while True:
                await asyncio.sleep(poll_interval_seconds)
                if runner.done():
                    await runner
                    raise RuntimeError("Temporal activity Worker stopped unexpectedly")
                try:
                    p1_backlog, p3_backlog = await backlog()
                except RPCError:
                    logger.warning(
                        "Temporal activity backlog lookup failed; retaining queue",
                        exc_info=True,
                    )
                    continue
                target_queue = choose_activity_task_queue(
                    preference,
                    p1_backlog=p1_backlog,
                    p3_backlog=p3_backlog,
                    queues=queues,
                )
                if target_queue != current_queue:
                    await worker.shutdown()
                    await runner
                    current_queue = target_queue
                    break
        except BaseException:
            await asyncio.shield(worker.shutdown())
            await asyncio.shield(runner)
            raise

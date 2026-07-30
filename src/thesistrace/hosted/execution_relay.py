import argparse
import asyncio
import logging

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from thesistrace.config import settings_from_environment
from thesistrace.hosted.execution_outbox import (
    PostgresExecutionOutbox,
    require_research_entry,
)
from thesistrace.hosted.research_workflow import (
    RESEARCH_TASK_QUEUE,
    ResearchWorkflow,
    research_workflow_id,
)

logger = logging.getLogger(__name__)


async def relay_once(
    client: Client,
    outbox: PostgresExecutionOutbox,
    *,
    limit: int = 25,
) -> int:
    dispatched = 0
    for entry in outbox.pending(limit=limit):
        resource_kind, workspace_id, run_id = require_research_entry(entry)
        if resource_kind == "research_run":
            try:
                await client.start_workflow(
                    ResearchWorkflow.run,
                    {"workspace_id": workspace_id, "run_id": run_id},
                    id=research_workflow_id(run_id),
                    task_queue=RESEARCH_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
        else:
            handle = client.get_workflow_handle(research_workflow_id(run_id))
            await handle.cancel()
        outbox.mark_dispatched(entry["outbox_id"])
        dispatched += 1
    return dispatched


async def run(interval: float, *, once: bool) -> None:
    settings = settings_from_environment()
    if not settings.database_url:
        raise RuntimeError("THESISTRACE_DATABASE_URL is required")
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    outbox = PostgresExecutionOutbox(settings.database_url)
    while True:
        try:
            await relay_once(client, outbox)
        except Exception:
            logger.exception("Execution outbox relay iteration failed")
        if once:
            return
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Relay durable work to Temporal")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args.interval, once=args.once))

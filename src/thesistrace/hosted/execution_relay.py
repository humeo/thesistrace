import argparse
import asyncio
import logging

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from thesistrace.config import settings_from_environment
from thesistrace.hosted.dataset_publication_workflow import (
    DATASET_PUBLICATION_TASK_QUEUE,
    DatasetPublicationWorkflow,
    dataset_publication_workflow_id,
)
from thesistrace.hosted.execution_outbox import (
    PostgresExecutionOutbox,
    require_execution_entry,
)
from thesistrace.hosted.research_workflow import (
    RESEARCH_TASK_QUEUE,
    ResearchWorkflow,
    research_workflow_id,
)
from thesistrace.hosted.tracking_workflow import (
    TRACKING_TASK_QUEUE,
    TrackingAdvanceWorkflow,
    TrackingReleaseWorkflow,
    tracking_advance_workflow_id,
    tracking_release_workflow_id,
    tracking_release_workflow_retry_policy,
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
        resource_kind, workspace_id, resource_id = require_execution_entry(entry)
        if resource_kind == "dataset_publication":
            try:
                await client.start_workflow(
                    DatasetPublicationWorkflow.run,
                    {"publication_id": resource_id},
                    id=dataset_publication_workflow_id(resource_id),
                    task_queue=DATASET_PUBLICATION_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
        elif resource_kind == "research_run":
            if workspace_id is None:
                raise ValueError("ResearchRun execution requires a Workspace")
            try:
                await client.start_workflow(
                    ResearchWorkflow.run,
                    {"workspace_id": workspace_id, "run_id": resource_id},
                    id=research_workflow_id(resource_id),
                    task_queue=RESEARCH_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
        elif resource_kind == "tracking_release":
            try:
                await client.start_workflow(
                    TrackingReleaseWorkflow.run,
                    {"release_id": resource_id},
                    id=tracking_release_workflow_id(resource_id),
                    task_queue=TRACKING_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    retry_policy=tracking_release_workflow_retry_policy(),
                )
            except WorkflowAlreadyStartedError:
                pass
        elif resource_kind == "tracking_advance":
            if workspace_id is None:
                raise ValueError("Tracking Advance execution requires a Workspace")
            try:
                await client.start_workflow(
                    TrackingAdvanceWorkflow.run,
                    {
                        "workspace_id": workspace_id,
                        "advance_id": resource_id,
                    },
                    id=tracking_advance_workflow_id(resource_id),
                    task_queue=TRACKING_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
        elif resource_kind == "research_run_cancel":
            handle = client.get_workflow_handle(
                research_workflow_id(resource_id)
            )
            await handle.cancel()
        else:
            raise ValueError(f"unsupported execution resource: {resource_kind}")
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

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from thesistrace.config import settings_from_environment
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted.activity_heartbeat import ActivityHeartbeat
from thesistrace.hosted.research_workflow import RESEARCH_TASK_QUEUE, ResearchWorkflow
from thesistrace.research_runs import ResearchRunService, recover_staged_research_run
from thesistrace.runtime import build_runtime
from thesistrace.tenancy import workspace_execution

logger = logging.getLogger(__name__)


@activity.defn(name="execute_research_run")
def execute_research_run(request: dict[str, str]) -> dict[str, str]:
    workspace_id = request["workspace_id"]
    run_id = request["run_id"]
    settings = settings_from_environment()
    with workspace_execution(workspace_id):
        runtime = build_runtime(settings)
        if activity.info().attempt > 1:
            runtime.control_metadata.prepare_research_run_redelivery(run_id)
        with ActivityHeartbeat() as heartbeat:
            completed = ResearchRunService(
                runtime.control_metadata,
                DatasetPublisher(runtime.control_metadata, runtime.objects),
                runtime.objects,
                progress=heartbeat.checkpoint,
            ).execute(run_id)
    if completed["status"] == "queued":
        attempts = completed.get("attempts")
        diagnostic = (
            attempts[-1].get("diagnostic")
            if isinstance(attempts, list)
            and attempts
            and isinstance(attempts[-1], dict)
            else None
        )
        reason_code = (
            str(diagnostic.get("reason_code"))
            if isinstance(diagnostic, dict)
            else "TRANSIENT_FAILURE"
        )
        raise ApplicationError(
            "research Activity requested retry",
            type=reason_code,
        )
    return {"run_id": run_id, "status": str(completed["status"])}


@activity.defn(name="finalize_research_delivery_failure")
def finalize_research_delivery_failure(request: dict[str, str]) -> dict[str, str]:
    settings = settings_from_environment()
    with workspace_execution(request["workspace_id"]):
        runtime = build_runtime(settings)
        runtime.control_metadata.fail_research_run_delivery(
            request["run_id"]
        )
        failed = recover_staged_research_run(
            runtime.control_metadata,
            runtime.objects,
            request["run_id"],
        )
    if failed["status"] == "cancelled":
        logger.info(
            "Research Activity cancellation finalized run_id=%s",
            request["run_id"],
        )
    elif failed["status"] == "succeeded":
        logger.info(
            "Research Activity completion was already committed run_id=%s",
            request["run_id"],
        )
    else:
        logger.error(
            "Research Activity delivery exhausted run_id=%s "
            "reason_code=ACTIVITY_DELIVERY_FAILED",
            request["run_id"],
        )
    return {
        "run_id": request["run_id"],
        "status": str(failed["status"]),
    }


async def run() -> None:
    settings = settings_from_environment()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = Worker(
            client,
            task_queue=RESEARCH_TASK_QUEUE,
            workflows=[ResearchWorkflow],
            activities=[
                execute_research_run,
                finalize_research_delivery_failure,
            ],
            activity_executor=executor,
            max_concurrent_activities=1,
        )
        await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

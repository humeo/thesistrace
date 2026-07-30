import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from thesistrace.config import settings_from_environment
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted.research_workflow import RESEARCH_TASK_QUEUE, ResearchWorkflow
from thesistrace.research_runs import ResearchRunService
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
        completed = ResearchRunService(
            runtime.control_metadata,
            DatasetPublisher(runtime.control_metadata, runtime.objects),
            runtime.objects,
        ).execute(run_id)
    return {"run_id": run_id, "status": str(completed["status"])}


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
            activities=[execute_research_run],
            activity_executor=executor,
            max_concurrent_activities=1,
        )
        await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

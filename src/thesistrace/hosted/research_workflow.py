from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError

from thesistrace.hosted.activity_policy import (
    HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
    heavy_activity_retry_policy,
)
from thesistrace.hosted.compute_dispatch import (
    COMPUTE_WORKFLOW_TASK_QUEUE,
    P3_ACTIVITY_TASK_QUEUE,
    activity_priority,
)

RESEARCH_TASK_QUEUE = COMPUTE_WORKFLOW_TASK_QUEUE


@workflow.defn
class ResearchWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, str]:
        try:
            return await workflow.execute_activity(
                "execute_research_run",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
                retry_policy=heavy_activity_retry_policy(),
                task_queue=P3_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        except ActivityError:
            return await workflow.execute_activity(
                "finalize_research_delivery_failure",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=heavy_activity_retry_policy(),
                task_queue=P3_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
            )


def research_workflow_id(run_id: str) -> str:
    return f"research-run/{run_id}"

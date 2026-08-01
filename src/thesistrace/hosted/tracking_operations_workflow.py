from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError

from thesistrace.hosted.activity_policy import (
    HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
    resource_aware_activity_retry_policy,
)
from thesistrace.hosted.compute_dispatch import (
    COMPUTE_WORKFLOW_TASK_QUEUE,
    P3_ACTIVITY_TASK_QUEUE,
    activity_priority,
)

TRACKING_OPERATIONS_TASK_QUEUE = COMPUTE_WORKFLOW_TASK_QUEUE


@workflow.defn
class TrackingEquivalenceWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, str]:
        try:
            return await workflow.execute_activity(
                "execute_tracking_equivalence",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
                retry_policy=resource_aware_activity_retry_policy(),
                task_queue=P3_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
                cancellation_type=(
                    workflow.ActivityCancellationType
                    .WAIT_CANCELLATION_COMPLETED
                ),
            )
        except ActivityError:
            return await workflow.execute_activity(
                "finalize_tracking_equivalence_failure",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=resource_aware_activity_retry_policy(),
                task_queue=P3_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
            )


@workflow.defn
class TrackingGenerationRebuildWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, str]:
        try:
            return await workflow.execute_activity(
                "execute_tracking_generation_rebuild",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
                retry_policy=resource_aware_activity_retry_policy(),
                task_queue=P3_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
                cancellation_type=(
                    workflow.ActivityCancellationType
                    .WAIT_CANCELLATION_COMPLETED
                ),
            )
        except ActivityError:
            return await workflow.execute_activity(
                "finalize_tracking_generation_rebuild_failure",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=resource_aware_activity_retry_policy(),
                task_queue=P3_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
            )


def tracking_equivalence_workflow_id(request_id: str) -> str:
    return f"tracking-equivalence/{request_id}"


def tracking_generation_rebuild_workflow_id(
    rebuild_id: str,
) -> str:
    return f"tracking-generation-rebuild/{rebuild_id}"

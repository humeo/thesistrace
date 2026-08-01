from datetime import timedelta

from temporalio import workflow

from thesistrace.hosted.activity_policy import (
    HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
    heavy_activity_retry_policy,
)
from thesistrace.hosted.compute_dispatch import (
    P3_ACTIVITY_TASK_QUEUE,
    platform_activity_priority,
)


@workflow.defn(name="CapacityQualificationComputeWorkflow")
class CapacityQualificationComputeWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, object]:
        return await workflow.execute_activity(
            "execute_capacity_qualification_compute",
            request,
            result_type=dict,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=heavy_activity_retry_policy(),
            task_queue=P3_ACTIVITY_TASK_QUEUE,
            priority=platform_activity_priority(),
        )


@workflow.defn(name="CapacityQualificationDataWorkflow")
class CapacityQualificationDataWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, object]:
        return await workflow.execute_activity(
            "execute_capacity_qualification_data",
            request,
            result_type=dict,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=heavy_activity_retry_policy(),
        )

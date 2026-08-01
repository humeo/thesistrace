from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from thesistrace.activity_contract import (
    MAX_AUTOMATIC_ACTIVITY_EXECUTIONS,
)
from thesistrace.hosted.activity_policy import (
    HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
    heavy_activity_retry_policy,
    resource_aware_activity_retry_policy,
)
from thesistrace.hosted.compute_dispatch import (
    COMPUTE_WORKFLOW_TASK_QUEUE,
    P1_ACTIVITY_TASK_QUEUE,
    activity_priority,
    platform_activity_priority,
)

TRACKING_TASK_QUEUE = COMPUTE_WORKFLOW_TASK_QUEUE


@workflow.defn
class TrackingReleaseWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, object]:
        page_request = dict(request)
        active_track_count = 0
        advance_count = 0
        while True:
            try:
                page = await workflow.execute_activity(
                    "fanout_tracking_release",
                    page_request,
                    result_type=dict,
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
                    retry_policy=resource_aware_activity_retry_policy(),
                    task_queue=P1_ACTIVITY_TASK_QUEUE,
                    priority=platform_activity_priority(),
                )
            except ActivityError as error:
                if (
                    isinstance(error.cause, ApplicationError)
                    and error.cause.type == "RESOURCE_EXHAUSTED"
                ):
                    raise ApplicationError(
                        "Tracking fanout exhausted Worker resources",
                        type="RESOURCE_EXHAUSTED",
                        non_retryable=True,
                    ) from error
                raise
            active_track_count += int(page["active_track_count"])
            advance_count += len(page["advance_ids"])
            next_cursor = page.get("next_cursor")
            if not isinstance(next_cursor, dict):
                break
            scan_upper_bound = page.get("scan_upper_bound")
            if not isinstance(scan_upper_bound, dict):
                raise RuntimeError("Tracking fanout scan bound is missing")
            page_request = {
                **request,
                "after_workspace_id": str(next_cursor["workspace_id"]),
                "after_track_id": str(next_cursor["track_id"]),
                "through_workspace_id": str(
                    scan_upper_bound["workspace_id"]
                ),
                "through_track_id": str(scan_upper_bound["track_id"]),
            }
        return {
            "release_id": request["release_id"],
            "active_track_count": active_track_count,
            "advance_count": advance_count,
        }


@workflow.defn
class TrackingAdvanceWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, str]:
        try:
            return await workflow.execute_activity(
                "execute_tracking_advance",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
                retry_policy=heavy_activity_retry_policy(),
                task_queue=P1_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
                cancellation_type=(
                    workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED
                ),
            )
        except ActivityError:
            return await workflow.execute_activity(
                "finalize_tracking_advance_delivery_failure",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=heavy_activity_retry_policy(),
                task_queue=P1_ACTIVITY_TASK_QUEUE,
                priority=activity_priority(request["workspace_id"]),
            )


def tracking_release_workflow_id(release_id: str) -> str:
    return f"tracking-release/{release_id}"


def tracking_advance_workflow_id(advance_id: str) -> str:
    return f"tracking-advance/{advance_id}"


def tracking_release_workflow_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2,
        maximum_interval=timedelta(minutes=5),
        maximum_attempts=MAX_AUTOMATIC_ACTIVITY_EXECUTIONS,
        non_retryable_error_types=["RESOURCE_EXHAUSTED"],
    )

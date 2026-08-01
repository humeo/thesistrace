from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

from thesistrace.hosted.activity_policy import (
    HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
    heavy_activity_retry_policy,
)

DATASET_PUBLICATION_TASK_QUEUE = "thesistrace-data"


@dataclass(frozen=True)
class ScheduledDatasetPublicationRequest:
    schedule_id: str
    kind: str
    request_version: str = "v1"
    new_sessions: int = 1


@workflow.defn
class DatasetPublicationWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, str]:
        try:
            return await workflow.execute_activity(
                "execute_dataset_publication",
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT,
                retry_policy=heavy_activity_retry_policy(),
                cancellation_type=(
                    workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED
                ),
            )
        except ActivityError as error:
            finalizer = (
                "finalize_dataset_publication_resource_exhaustion"
                if isinstance(error.cause, ApplicationError)
                and error.cause.type == "RESOURCE_EXHAUSTED"
                else "finalize_dataset_publication_delivery_failure"
            )
            return await workflow.execute_activity(
                finalizer,
                request,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=heavy_activity_retry_policy(),
            )


@workflow.defn
class ScheduledDatasetPublicationWorkflow:
    @workflow.run
    async def run(
        self,
        request: ScheduledDatasetPublicationRequest,
    ) -> dict[str, object]:
        if request.kind == "fixture_bootstrap":
            parameters: dict[str, object] = {"fixture": "v1"}
        elif request.kind == "fixture_increment":
            parameters = {
                "new_sessions": request.new_sessions,
                "corrections": [],
            }
        elif request.kind in {"live_bootstrap", "live_increment"}:
            parameters = {"as_of": workflow.now().date().isoformat()}
        else:
            parameters = {}
        scheduled_request: dict[str, object] = {
            "schedule_id": request.schedule_id,
            "request_version": request.request_version,
            "kind": request.kind,
            "parameters": parameters,
            "scheduled_for": workflow.now().isoformat(),
        }
        return await workflow.execute_activity(
            "request_scheduled_dataset_publication",
            scheduled_request,
            result_type=dict,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=heavy_activity_retry_policy(),
        )


def dataset_publication_workflow_id(publication_id: str) -> str:
    return f"dataset-publication/{publication_id}"

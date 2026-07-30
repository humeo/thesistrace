import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from thesistrace.activity_contract import (
    MAX_RESOURCE_EXHAUSTION_EXECUTIONS,
    is_resource_exhaustion,
)
from thesistrace.config import settings_from_environment
from thesistrace.hosted.activity_heartbeat import ActivityHeartbeat
from thesistrace.hosted.dataset_publication_workflow import (
    DATASET_PUBLICATION_TASK_QUEUE,
    DatasetPublicationWorkflow,
    ScheduledDatasetPublicationWorkflow,
)
from thesistrace.platform_publications import (
    DatasetPublicationRequestService,
    DatasetPublicationService,
    local_source_authorization_gate,
)
from thesistrace.runtime import build_runtime

logger = logging.getLogger(__name__)


@activity.defn(name="execute_dataset_publication")
def execute_dataset_publication(request: dict[str, str]) -> dict[str, str]:
    publication_id = request["publication_id"]
    runtime = None
    try:
        settings = settings_from_environment()
        runtime = build_runtime(settings)
        if activity.info().attempt > 1:
            runtime.control_metadata.prepare_dataset_publication_redelivery(
                publication_id
            )
        with ActivityHeartbeat(
            on_cancel=lambda: (
                runtime.control_metadata.request_dataset_publication_cancellation(
                    publication_id
                )
            )
        ) as heartbeat:
            completed = DatasetPublicationService(
                runtime.control_metadata,
                runtime.objects,
                settings=settings,
                progress=heartbeat.checkpoint,
                cancellation_requested=activity.is_cancelled,
            ).execute(publication_id)
    except ApplicationError:
        raise
    except Exception as error:
        if not is_resource_exhaustion(error):
            raise
        final_execution = (
            activity.info().attempt >= MAX_RESOURCE_EXHAUSTION_EXECUTIONS
        )
        if final_execution and runtime is not None:
            failed = (
                runtime.control_metadata.fail_dataset_publication_resource_exhaustion(
                    publication_id
                )
            )
            DatasetPublicationService(
                runtime.control_metadata,
                runtime.objects,
                settings=settings,
            ).recover(publication_id)
            return {
                "publication_id": publication_id,
                "status": str(failed["status"]),
            }
        raise ApplicationError(
            "Data Worker resource envelope was exhausted",
            type="RESOURCE_EXHAUSTED",
            non_retryable=final_execution,
        ) from error
    if completed["status"] == "queued":
        diagnostic = completed.get("diagnostic")
        reason_code = (
            str(diagnostic.get("reason_code"))
            if isinstance(diagnostic, dict)
            else "TRANSIENT_FAILURE"
        )
        raise ApplicationError(
            "Dataset Publication Activity requested retry",
            type=reason_code,
        )
    return {
        "publication_id": publication_id,
        "status": str(completed["status"]),
    }


@activity.defn(name="finalize_dataset_publication_delivery_failure")
def finalize_dataset_publication_delivery_failure(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    runtime = build_runtime(settings)
    failed = runtime.control_metadata.fail_dataset_publication_delivery(
        request["publication_id"]
    )
    DatasetPublicationService(
        runtime.control_metadata,
        runtime.objects,
        settings=settings,
    ).recover(request["publication_id"])
    logger.error(
        "Dataset Publication delivery exhausted publication_id=%s "
        "reason_code=ACTIVITY_DELIVERY_FAILED",
        request["publication_id"],
    )
    return {
        "publication_id": request["publication_id"],
        "status": str(failed["status"]),
    }


@activity.defn(name="finalize_dataset_publication_resource_exhaustion")
def finalize_dataset_publication_resource_exhaustion(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    runtime = build_runtime(settings)
    failed = (
        runtime.control_metadata.fail_dataset_publication_resource_exhaustion(
            request["publication_id"]
        )
    )
    DatasetPublicationService(
        runtime.control_metadata,
        runtime.objects,
        settings=settings,
    ).recover(request["publication_id"])
    logger.error(
        "Dataset Publication resource exhausted publication_id=%s "
        "reason_code=RESOURCE_EXHAUSTED",
        request["publication_id"],
    )
    return {
        "publication_id": request["publication_id"],
        "status": str(failed["status"]),
    }


@activity.defn(name="request_scheduled_dataset_publication")
def request_scheduled_dataset_publication(
    request: dict[str, Any],
) -> dict[str, Any]:
    settings = settings_from_environment()
    runtime = build_runtime(settings)
    publication, created = DatasetPublicationRequestService(
        runtime.control_metadata,
        local_source_authorization_gate(runtime.control_metadata),
    ).request_scheduled(
        schedule_id=str(request["schedule_id"]),
        scheduled_for=str(request["scheduled_for"]),
        request_version=str(request.get("request_version", "v1")),
        kind=str(request["kind"]),
        parameters=dict(request["parameters"]),
    )
    return {
        "publication_id": publication["id"],
        "created": created,
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
            task_queue=DATASET_PUBLICATION_TASK_QUEUE,
            workflows=[
                DatasetPublicationWorkflow,
                ScheduledDatasetPublicationWorkflow,
            ],
            activities=[
                execute_dataset_publication,
                finalize_dataset_publication_delivery_failure,
                finalize_dataset_publication_resource_exhaustion,
                request_scheduled_dataset_publication,
            ],
            activity_executor=executor,
            max_concurrent_activities=1,
        )
        await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

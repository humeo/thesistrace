import asyncio
import logging
import os
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
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
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted.activity_heartbeat import ActivityHeartbeat
from thesistrace.hosted.capacity_corpus import (
    publish_capacity_corpus,
    publish_capacity_increment,
)
from thesistrace.hosted.capacity_workflow import CapacityQualificationDataWorkflow
from thesistrace.hosted.dataset_publication_workflow import (
    DATASET_PUBLICATION_TASK_QUEUE,
    DatasetPublicationWorkflow,
    ScheduledDatasetPublicationWorkflow,
)
from thesistrace.hosted.observability import configure_observability
from thesistrace.hosted.probes import (
    ProcessProbeServer,
    ProcessProbeState,
    monitor_role,
)
from thesistrace.platform_publications import (
    DatasetPublicationRequestService,
    DatasetPublicationService,
    local_source_authorization_gate,
)
from thesistrace.runtime import build_runtime

logger = logging.getLogger(__name__)


@activity.defn(name="execute_capacity_qualification_data")
def execute_capacity_qualification_data(
    request: dict[str, str],
) -> dict[str, object]:
    runtime = build_runtime(settings_from_environment())
    publisher = DatasetPublisher(runtime.control_metadata, runtime.objects)
    with ActivityHeartbeat():
        if request["operation"] == "prepare":
            release, created = publish_capacity_corpus(
                publisher,
                idempotency_key=request["idempotency_key"],
            )
        elif request["operation"] == "increment":
            release, created = publish_capacity_increment(
                publisher,
                idempotency_key=request["idempotency_key"],
            )
        else:
            raise RuntimeError("unknown capacity Data operation")
    return {
        "status": "succeeded",
        "release_id": release["id"],
        "created": created,
        "worker_slot": os.environ.get("THESISTRACE_SERVICE_SLOT", "unknown"),
        "workflow_id": activity.info().workflow_id,
        "activity_id": activity.info().activity_id,
        "activity_attempt": activity.info().attempt,
    }


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
    state = ProcessProbeState(
        service="data-worker",
        slot=os.environ.get("THESISTRACE_SERVICE_SLOT", "data-1"),
    )
    with ProcessProbeServer(state):
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker = build_data_worker(client, executor=executor)
            await monitor_role(worker.run(), state)


def build_data_worker(
    client: Client,
    *,
    task_queue: str = DATASET_PUBLICATION_TASK_QUEUE,
    workflows: Sequence[type] | None = None,
    activities: Sequence[Callable] | None = None,
    executor: Executor | None = None,
) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=workflows
        if workflows is not None
        else [
            DatasetPublicationWorkflow,
            ScheduledDatasetPublicationWorkflow,
            CapacityQualificationDataWorkflow,
        ],
        activities=activities
        if activities is not None
        else [
            execute_dataset_publication,
            finalize_dataset_publication_delivery_failure,
            finalize_dataset_publication_resource_exhaustion,
            request_scheduled_dataset_publication,
            execute_capacity_qualification_data,
        ],
        activity_executor=executor,
        max_concurrent_activities=1,
        max_concurrent_activity_task_polls=1,
        disable_eager_activity_execution=True,
    )


def main() -> None:
    configure_observability("data-worker")
    asyncio.run(run())

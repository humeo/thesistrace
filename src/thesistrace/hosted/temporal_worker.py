import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import timedelta

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
from thesistrace.hosted.compute_dispatch import (
    COMPUTE_WORKFLOW_TASK_QUEUE,
    DEFAULT_COMPUTE_TASK_QUEUES,
    ComputeTaskQueues,
    activity_backlogs,
    run_preferred_activity_poller,
)
from thesistrace.hosted.observability import configure_observability
from thesistrace.hosted.probes import (
    ProcessProbeServer,
    ProcessProbeState,
    monitor_role,
)
from thesistrace.hosted.research_workflow import ResearchWorkflow
from thesistrace.hosted.tracking_operations_workflow import (
    TrackingEquivalenceWorkflow,
    TrackingGenerationRebuildWorkflow,
)
from thesistrace.hosted.tracking_workflow import (
    TrackingAdvanceWorkflow,
    TrackingReleaseWorkflow,
)
from thesistrace.research_runs import ResearchRunService, recover_staged_research_run
from thesistrace.runtime import build_runtime
from thesistrace.tenancy import workspace_execution
from thesistrace.tracking import CorrectionImpactCache, DailyTrackingService
from thesistrace.tracking_operations import TrackingOperationService

logger = logging.getLogger(__name__)
TRACKING_FANOUT_PAGE_SIZE = 100


def _tracking_service(runtime) -> DailyTrackingService:
    return DailyTrackingService(
        runtime.control_metadata,
        DatasetPublisher(runtime.control_metadata, runtime.objects),
        runtime.objects,
        runtime.working_cache,
    )


def _tracking_operation_service(runtime) -> TrackingOperationService:
    return TrackingOperationService(
        runtime.control_metadata,
        _tracking_service(runtime),
    )


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


@activity.defn(name="fanout_tracking_release")
def fanout_tracking_release(
    request: dict[str, str],
) -> dict[str, object]:
    try:
        return _fanout_tracking_release(request)
    except ApplicationError:
        raise
    except Exception as error:
        if not is_resource_exhaustion(error):
            raise
        final_execution = (
            activity.info().attempt
            >= MAX_RESOURCE_EXHAUSTION_EXECUTIONS
        )
        raise ApplicationError(
            "Tracking fanout exhausted Worker resources",
            type="RESOURCE_EXHAUSTED",
            non_retryable=final_execution,
        ) from error


def _fanout_tracking_release(
    request: dict[str, str],
) -> dict[str, object]:
    settings = settings_from_environment()
    runtime = build_runtime(settings)
    release_id = request["release_id"]
    scan_upper_bound = (
        {
            "workspace_id": request["through_workspace_id"],
            "track_id": request["through_track_id"],
        }
        if "through_workspace_id" in request
        and "through_track_id" in request
        else runtime.control_metadata.active_daily_track_scan_bound()
    )
    if scan_upper_bound is None:
        return {
            "release_id": release_id,
            "active_track_count": 0,
            "advance_ids": [],
            "next_cursor": None,
            "scan_upper_bound": None,
        }
    track_refs = runtime.control_metadata.active_daily_track_refs(
        after_workspace_id=request.get("after_workspace_id"),
        after_track_id=request.get("after_track_id"),
        through_workspace_id=scan_upper_bound["workspace_id"],
        through_track_id=scan_upper_bound["track_id"],
        limit=TRACKING_FANOUT_PAGE_SIZE + 1,
    )
    page_refs = track_refs[:TRACKING_FANOUT_PAGE_SIZE]
    advances: list[str] = []
    tracking = _tracking_service(runtime)
    correction_cache = CorrectionImpactCache()
    with ActivityHeartbeat() as heartbeat:
        for index, ref in enumerate(page_refs):
            with workspace_execution(ref["workspace_id"]):
                advance = tracking.enqueue_toward(
                    ref["track_id"],
                    release_id,
                    correction_cache=correction_cache,
                )
            if advance is not None:
                advances.append(str(advance["id"]))
            heartbeat.checkpoint(f"track-{index + 1}")
    next_cursor = (
        {
            "workspace_id": page_refs[-1]["workspace_id"],
            "track_id": page_refs[-1]["track_id"],
        }
        if len(track_refs) > TRACKING_FANOUT_PAGE_SIZE
        else None
    )
    return {
        "release_id": release_id,
        "active_track_count": len(page_refs),
        "advance_ids": advances,
        "next_cursor": next_cursor,
        "scan_upper_bound": scan_upper_bound,
    }


@activity.defn(name="execute_tracking_advance")
def execute_tracking_advance(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    advance_id = request["advance_id"]
    with workspace_execution(request["workspace_id"]):
        runtime = build_runtime(settings)
        service = _tracking_service(runtime)
        if activity.info().attempt > 1:
            service.prepare_advance_redelivery(advance_id)
        with ActivityHeartbeat():
            completed = service.execute_advance(advance_id)
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
        else None
    )
    if completed["status"] == "blocked" and reason_code in {
        "RESOURCE_EXHAUSTED",
        "TRACKING_CALCULATION_FAILED",
    }:
        raise ApplicationError(
            "Tracking Activity requested retry",
            type=reason_code,
        )
    return {
        "advance_id": advance_id,
        "status": str(completed["status"]),
    }


@activity.defn(name="finalize_tracking_advance_delivery_failure")
def finalize_tracking_advance_delivery_failure(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    with workspace_execution(request["workspace_id"]):
        runtime = build_runtime(settings)
        failed = _tracking_service(runtime).fail_advance_delivery(
            request["advance_id"]
        )
    if failed["status"] == "succeeded":
        logger.info(
            "Tracking Activity completion was already committed advance_id=%s",
            request["advance_id"],
        )
    elif failed["status"] == "failed":
        logger.error(
            "Tracking Activity delivery exhausted advance_id=%s "
            "reason_code=ACTIVITY_DELIVERY_FAILED",
            request["advance_id"],
        )
    else:
        logger.info(
            "Tracking Activity delivery finalizer preserved terminal Track state "
            "advance_id=%s status=%s",
            request["advance_id"],
            failed["status"],
        )
    return {
        "advance_id": request["advance_id"],
        "status": str(failed["status"]),
    }


@activity.defn(name="execute_tracking_equivalence")
def execute_tracking_equivalence(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    with workspace_execution(request["workspace_id"]):
        runtime = build_runtime(settings)
        service = _tracking_operation_service(runtime)
        try:
            with ActivityHeartbeat(
                on_cancel=lambda: service.cancel_equivalence(
                    request["request_id"]
                )
            ) as heartbeat:
                completed = service.execute_equivalence(
                    request["request_id"],
                    progress=heartbeat.checkpoint,
                )
        except Exception as error:
            if not is_resource_exhaustion(error):
                raise
            final_execution = (
                activity.info().attempt
                >= MAX_RESOURCE_EXHAUSTION_EXECUTIONS
            )
            if final_execution:
                service.fail_equivalence(
                    request["request_id"],
                    "RESOURCE_EXHAUSTED",
                )
            raise ApplicationError(
                "Equivalence exhausted Worker resources",
                type="RESOURCE_EXHAUSTED",
                non_retryable=final_execution,
            ) from error
    return {
        "request_id": request["request_id"],
        "status": str(completed["status"]),
    }


@activity.defn(name="finalize_tracking_equivalence_failure")
def finalize_tracking_equivalence_failure(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    with workspace_execution(request["workspace_id"]):
        runtime = build_runtime(settings)
        failed = _tracking_operation_service(runtime).fail_equivalence(
            request["request_id"],
            "ACTIVITY_DELIVERY_FAILED",
        )
    return {
        "request_id": request["request_id"],
        "status": str(failed["status"]),
    }


@activity.defn(name="execute_tracking_generation_rebuild")
def execute_tracking_generation_rebuild(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    with workspace_execution(request["workspace_id"]):
        runtime = build_runtime(settings)
        service = _tracking_operation_service(runtime)
        try:
            with ActivityHeartbeat(
                on_cancel=lambda: service.cancel_generation_rebuild(
                    request["rebuild_id"]
                )
            ) as heartbeat:
                completed = service.execute_generation_rebuild(
                    request["rebuild_id"],
                    progress=heartbeat.checkpoint,
                )
        except Exception as error:
            if not is_resource_exhaustion(error):
                raise
            final_execution = (
                activity.info().attempt
                >= MAX_RESOURCE_EXHAUSTION_EXECUTIONS
            )
            if final_execution:
                service.fail_generation_rebuild(
                    request["rebuild_id"],
                    "RESOURCE_EXHAUSTED",
                )
            raise ApplicationError(
                "Generation rebuild exhausted Worker resources",
                type="RESOURCE_EXHAUSTED",
                non_retryable=final_execution,
            ) from error
    return {
        "rebuild_id": request["rebuild_id"],
        "status": str(completed["status"]),
    }


@activity.defn(name="finalize_tracking_generation_rebuild_failure")
def finalize_tracking_generation_rebuild_failure(
    request: dict[str, str],
) -> dict[str, str]:
    settings = settings_from_environment()
    with workspace_execution(request["workspace_id"]):
        runtime = build_runtime(settings)
        failed = _tracking_operation_service(
            runtime
        ).fail_generation_rebuild(
            request["rebuild_id"],
            "ACTIVITY_DELIVERY_FAILED",
        )
    return {
        "rebuild_id": request["rebuild_id"],
        "status": str(failed["status"]),
    }


async def run_compute_slot(
    *,
    preference: str,
    workflow_worker: Worker | None,
    activity_worker: Callable[[str], Worker],
    backlog: Callable[[], Awaitable[tuple[int, int]]],
    queues: ComputeTaskQueues = DEFAULT_COMPUTE_TASK_QUEUES,
    poll_interval_seconds: float = 1.0,
) -> None:
    workflow_task = (
        asyncio.create_task(workflow_worker.run())
        if workflow_worker is not None
        else None
    )
    activity_task = asyncio.create_task(
        run_preferred_activity_poller(
            preference=preference,
            worker_factory=activity_worker,
            backlog=backlog,
            queues=queues,
            poll_interval_seconds=poll_interval_seconds,
        )
    )
    tasks = [
        task
        for task in (workflow_task, activity_task)
        if task is not None
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        if workflow_worker is not None:
            await asyncio.shield(workflow_worker.shutdown())
        activity_task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def build_compute_workflow_worker(
    client: Client,
    *,
    task_queue: str = COMPUTE_WORKFLOW_TASK_QUEUE,
    workflows: Sequence[type] | None = None,
) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=workflows
        if workflows is not None
        else [
            ResearchWorkflow,
            TrackingReleaseWorkflow,
            TrackingAdvanceWorkflow,
            TrackingEquivalenceWorkflow,
            TrackingGenerationRebuildWorkflow,
        ],
        no_remote_activities=True,
        disable_eager_activity_execution=True,
        max_cached_workflows=0,
        max_concurrent_workflow_tasks=1,
        max_concurrent_workflow_task_polls=1,
    )


def build_compute_activity_worker(
    client: Client,
    *,
    task_queue: str,
    activities: Sequence[Callable] | None = None,
    executor: Executor | None = None,
    identity: str | None = None,
) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        activities=activities
        if activities is not None
        else [
            execute_research_run,
            finalize_research_delivery_failure,
            fanout_tracking_release,
            execute_tracking_advance,
            finalize_tracking_advance_delivery_failure,
            execute_tracking_equivalence,
            finalize_tracking_equivalence_failure,
            execute_tracking_generation_rebuild,
            finalize_tracking_generation_rebuild_failure,
        ],
        activity_executor=executor,
        max_concurrent_activities=1,
        max_concurrent_activity_task_polls=1,
        graceful_shutdown_timeout=timedelta(hours=3),
        identity=identity,
    )


async def run() -> None:
    settings = settings_from_environment()
    state = ProcessProbeState(
        service="compute-worker",
        slot=os.environ.get(
            "THESISTRACE_SERVICE_SLOT",
            settings.compute_slot_preference,
        ),
    )
    with ProcessProbeServer(state):
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            workflow_worker = (
                build_compute_workflow_worker(
                    client,
                )
                if settings.compute_workflow_poller
                else None
            )

            def activity_worker(task_queue: str) -> Worker:
                return build_compute_activity_worker(
                    client,
                    task_queue=task_queue,
                    executor=executor,
                )

            async def backlog() -> tuple[int, int]:
                return await activity_backlogs(
                    client,
                    settings.temporal_namespace,
                )

            await monitor_role(
                run_compute_slot(
                    preference=settings.compute_slot_preference,
                    workflow_worker=workflow_worker,
                    activity_worker=activity_worker,
                    backlog=backlog,
                ),
                state,
            )


def main() -> None:
    configure_observability("compute-worker")
    asyncio.run(run())

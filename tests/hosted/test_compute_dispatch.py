import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from temporalio import workflow as temporal_workflow
from temporalio.service import RPCError, RPCStatusCode

from thesistrace.hosted.compute_dispatch import (
    COMPUTE_WORKFLOW_TASK_QUEUE,
    P1_ACTIVITY_TASK_QUEUE,
    P3_ACTIVITY_TASK_QUEUE,
    PLATFORM_FAIRNESS_KEY,
    ComputeTaskQueues,
    activity_priority,
    choose_activity_task_queue,
    run_preferred_activity_poller,
)
from thesistrace.hosted.research_workflow import (
    RESEARCH_TASK_QUEUE,
    ResearchWorkflow,
)
from thesistrace.hosted.tracking_operations_workflow import (
    TRACKING_OPERATIONS_TASK_QUEUE,
    TrackingEquivalenceWorkflow,
    TrackingGenerationRebuildWorkflow,
)
from thesistrace.hosted.tracking_workflow import (
    TRACKING_TASK_QUEUE,
    TrackingAdvanceWorkflow,
    TrackingReleaseWorkflow,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("preference", "p1_backlog", "p3_backlog", "expected"),
    [
        ("p1", 3, 3, P1_ACTIVITY_TASK_QUEUE),
        ("p3", 3, 3, P3_ACTIVITY_TASK_QUEUE),
        ("p1", 0, 3, P3_ACTIVITY_TASK_QUEUE),
        ("p3", 3, 0, P1_ACTIVITY_TASK_QUEUE),
        ("p1", 0, 0, P1_ACTIVITY_TASK_QUEUE),
        ("p3", 0, 0, P3_ACTIVITY_TASK_QUEUE),
    ],
)
def test_slot_preference_is_reserved_but_work_conserving(
    preference: str,
    p1_backlog: int,
    p3_backlog: int,
    expected: str,
) -> None:
    assert (
        choose_activity_task_queue(
            preference,
            p1_backlog=p1_backlog,
            p3_backlog=p3_backlog,
        )
        == expected
    )


def test_compute_queue_contract_separates_workflow_and_priority_tiers() -> None:
    queues = ComputeTaskQueues()

    assert queues.workflow == COMPUTE_WORKFLOW_TASK_QUEUE
    assert queues.p1 == P1_ACTIVITY_TASK_QUEUE
    assert queues.p3 == P3_ACTIVITY_TASK_QUEUE
    assert len({queues.workflow, queues.p1, queues.p3}) == 3
    assert {
        RESEARCH_TASK_QUEUE,
        TRACKING_TASK_QUEUE,
        TRACKING_OPERATIONS_TASK_QUEUE,
    } == {queues.workflow}


def test_workspace_priority_is_equal_weight_and_stable() -> None:
    first = activity_priority("workspace-a")
    second = activity_priority("workspace-a")
    other = activity_priority("workspace-b")

    assert first == second
    assert first.priority_key == 3
    assert first.fairness_key == "workspace-a"
    assert first.fairness_weight == 1.0
    assert other.fairness_key == "workspace-b"
    assert other.fairness_weight == first.fairness_weight


def test_empty_workspace_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="Workspace"):
        activity_priority("")


@pytest.mark.parametrize(
    (
        "workflow_instance",
        "workflow_request",
        "activity_name",
        "task_queue",
        "fairness_key",
    ),
    [
        (
            ResearchWorkflow(),
            {"workspace_id": "workspace-r", "run_id": "run-1"},
            "execute_research_run",
            P3_ACTIVITY_TASK_QUEUE,
            "workspace-r",
        ),
        (
            TrackingAdvanceWorkflow(),
            {"workspace_id": "workspace-a", "advance_id": "advance-1"},
            "execute_tracking_advance",
            P1_ACTIVITY_TASK_QUEUE,
            "workspace-a",
        ),
        (
            TrackingEquivalenceWorkflow(),
            {"workspace_id": "workspace-e", "request_id": "request-1"},
            "execute_tracking_equivalence",
            P3_ACTIVITY_TASK_QUEUE,
            "workspace-e",
        ),
        (
            TrackingGenerationRebuildWorkflow(),
            {"workspace_id": "workspace-g", "rebuild_id": "rebuild-1"},
            "execute_tracking_generation_rebuild",
            P3_ACTIVITY_TASK_QUEUE,
            "workspace-g",
        ),
        (
            TrackingReleaseWorkflow(),
            {"release_id": "release-1"},
            "fanout_tracking_release",
            P1_ACTIVITY_TASK_QUEUE,
            PLATFORM_FAIRNESS_KEY,
        ),
    ],
)
def test_production_workflows_route_activities_with_native_temporal_fairness(
    monkeypatch: pytest.MonkeyPatch,
    workflow_instance,
    workflow_request: dict[str, str],
    activity_name: str,
    task_queue: str,
    fairness_key: str,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def execute_activity(*args, **options):
        calls.append((args, options))
        if activity_name == "fanout_tracking_release":
            return {
                "active_track_count": 0,
                "advance_ids": [],
                "next_cursor": None,
            }
        return {"status": "succeeded"}

    monkeypatch.setattr(
        temporal_workflow,
        "execute_activity",
        execute_activity,
    )

    asyncio.run(workflow_instance.run(workflow_request))

    assert len(calls) == 1
    args, options = calls[0]
    assert args[0] == activity_name
    assert options["task_queue"] == task_queue
    priority = options["priority"]
    assert priority.priority_key == 3
    assert priority.fairness_key == fairness_key
    assert priority.fairness_weight == 1.0


class FakeWorker:
    def __init__(self, task_queue: str, events: list[str]) -> None:
        self.task_queue = task_queue
        self.events = events
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        self.events.append(f"poll:{self.task_queue}")
        await self._shutdown.wait()
        self.events.append(f"stopped:{self.task_queue}")

    async def shutdown(self) -> None:
        self.events.append(f"shutdown:{self.task_queue}")
        self._shutdown.set()


def test_slot_switches_from_fallback_to_preferred_without_a_second_scheduler() -> None:
    events: list[str] = []
    backlogs = iter([(0, 4), (4, 4)])

    async def backlog() -> tuple[int, int]:
        try:
            return next(backlogs)
        except StopIteration:
            raise asyncio.CancelledError from None

    def worker_factory(task_queue: str) -> FakeWorker:
        return FakeWorker(task_queue, events)

    async def scenario() -> None:
        task = asyncio.create_task(
            run_preferred_activity_poller(
                preference="p1",
                worker_factory=worker_factory,
                backlog=backlog,
                poll_interval_seconds=0,
            )
        )
        while f"poll:{P1_ACTIVITY_TASK_QUEUE}" not in events:
            await asyncio.sleep(0)
        while f"poll:{P3_ACTIVITY_TASK_QUEUE}" not in events:
            await asyncio.sleep(0)
        while events.count(f"poll:{P1_ACTIVITY_TASK_QUEUE}") < 2:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert events[:5] == [
        f"poll:{P1_ACTIVITY_TASK_QUEUE}",
        f"shutdown:{P1_ACTIVITY_TASK_QUEUE}",
        f"stopped:{P1_ACTIVITY_TASK_QUEUE}",
        f"poll:{P3_ACTIVITY_TASK_QUEUE}",
        f"shutdown:{P3_ACTIVITY_TASK_QUEUE}",
    ]
    assert events[-1] == f"stopped:{P1_ACTIVITY_TASK_QUEUE}"


def test_transient_backlog_rpc_failure_does_not_stop_activity_worker() -> None:
    events: list[str] = []
    calls = 0

    async def backlog() -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RPCError(
                "injected timeout",
                RPCStatusCode.DEADLINE_EXCEEDED,
                b"",
            )
        raise asyncio.CancelledError

    def worker_factory(task_queue: str) -> FakeWorker:
        return FakeWorker(task_queue, events)

    async def scenario() -> None:
        task = asyncio.create_task(
            run_preferred_activity_poller(
                preference="p1",
                worker_factory=worker_factory,
                backlog=backlog,
                poll_interval_seconds=0,
            )
        )
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert calls == 2
    assert events == [
        f"poll:{P1_ACTIVITY_TASK_QUEUE}",
        f"shutdown:{P1_ACTIVITY_TASK_QUEUE}",
        f"stopped:{P1_ACTIVITY_TASK_QUEUE}",
    ]


def test_poller_requires_exactly_one_primary_tier() -> None:
    async def backlog() -> tuple[int, int]:
        return 0, 0

    def worker_factory(_task_queue: str) -> Callable[[], None]:
        raise AssertionError("invalid preference must fail before polling")

    with pytest.raises(ValueError, match="preference"):
        asyncio.run(
            run_preferred_activity_poller(
                preference="other",
                worker_factory=worker_factory,
                backlog=backlog,
                poll_interval_seconds=0,
            )
        )


def test_temporal_fairness_is_enabled_for_the_hosted_service() -> None:
    config = (
        ROOT / "deploy" / "hosted" / "temporal" / "dynamicconfig.yaml"
    ).read_text()

    assert "matching.enableFairness:\n  - value: true\n    constraints: {}" in config
    assert (
        "matching.numTaskqueueReadPartitions:\n"
        "  - value: 1\n"
        "    constraints: {}"
    ) in config
    assert (
        "matching.numTaskqueueWritePartitions:\n"
        "  - value: 1\n"
        "    constraints: {}"
    ) in config

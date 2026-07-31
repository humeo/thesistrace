#!/usr/bin/env python3
import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import uuid4

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Worker

from thesistrace.hosted.compute_dispatch import (
    ComputeTaskQueues,
    activity_backlogs,
    activity_priority,
    run_preferred_activity_poller,
)

COMPUTE_ACTIVITY = "hosted_dispatch_probe_compute"
DATA_ACTIVITY = "hosted_dispatch_probe_data"
PREFERENCES = ("p1", "p1", "p1", "p3")


@workflow.defn(name="HostedDispatchProbeWorkflow")
class DispatchProbeWorkflow:
    @workflow.run
    async def run(self, request: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            COMPUTE_ACTIVITY,
            request,
            result_type=dict,
            task_queue=str(request["activity_task_queue"]),
            priority=activity_priority(str(request["workspace_id"])),
            start_to_close_timeout=timedelta(minutes=5),
        )


@workflow.defn(name="HostedDataDispatchProbeWorkflow")
class DataDispatchProbeWorkflow:
    @workflow.run
    async def run(self, request: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            DATA_ACTIVITY,
            request,
            result_type=dict,
            start_to_close_timeout=timedelta(minutes=5),
        )


@dataclass
class ProbeState:
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    running: dict[int, tuple[dict[str, Any], asyncio.Event]] = field(
        default_factory=dict
    )
    starts: list[tuple[int, str, str, int]] = field(default_factory=list)
    compute_running: int = 0
    max_compute_running: int = 0
    data_running: int = 0
    max_data_running: int = 0
    data_release: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute_compute(
        self,
        slot: int,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        release = asyncio.Event()
        async with self.condition:
            if slot in self.running:
                raise AssertionError(f"slot {slot} accepted concurrent work")
            self.running[slot] = (request, release)
            self.compute_running += 1
            self.max_compute_running = max(
                self.max_compute_running,
                self.compute_running,
            )
            self.starts.append(
                (
                    slot,
                    str(request["tier"]),
                    str(request["workspace_id"]),
                    int(request["sequence"]),
                )
            )
            self.condition.notify_all()
        try:
            await release.wait()
        finally:
            async with self.condition:
                self.running.pop(slot, None)
                self.compute_running -= 1
                self.condition.notify_all()
        return request

    async def execute_data(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        async with self.condition:
            self.data_running += 1
            self.max_data_running = max(
                self.max_data_running,
                self.data_running,
            )
            self.condition.notify_all()
        try:
            await self.data_release.wait()
        finally:
            async with self.condition:
                self.data_running -= 1
                self.condition.notify_all()
        return request

    async def wait_for(self, predicate, *, timeout: float = 20) -> None:
        async def wait() -> None:
            async with self.condition:
                await self.condition.wait_for(predicate)

        await asyncio.wait_for(wait(), timeout=timeout)

    async def request_for_slot(self, slot: int) -> dict[str, Any]:
        async with self.condition:
            return dict(self.running[slot][0])

    async def release_slot(self, slot: int) -> None:
        async with self.condition:
            self.running[slot][1].set()

    async def release_everything(self) -> None:
        async with self.condition:
            for _request, release in self.running.values():
                release.set()
            self.data_release.set()


def compute_activity(state: ProbeState, slot: int):
    @activity.defn(name=COMPUTE_ACTIVITY)
    async def execute(request: dict[str, Any]) -> dict[str, Any]:
        return await state.execute_compute(slot, request)

    return execute


def data_activity(state: ProbeState):
    @activity.defn(name=DATA_ACTIVITY)
    async def execute(request: dict[str, Any]) -> dict[str, Any]:
        return await state.execute_data(request)

    return execute


def requests(
    *,
    tier: str,
    count: int,
    task_queue: str,
    phase: str,
) -> list[dict[str, Any]]:
    sequences = Counter()
    result = []
    for index in range(count):
        workspace_id = f"workspace-{index % 2}"
        sequences[workspace_id] += 1
        result.append(
            {
                "id": f"{phase}-{tier}-{index}",
                "tier": tier,
                "workspace_id": workspace_id,
                "sequence": sequences[workspace_id],
                "activity_task_queue": task_queue,
            }
        )
    return result


async def start_requests(
    client: Client,
    workflow_task_queue: str,
    probe_id: str,
    values: list[dict[str, Any]],
) -> list[WorkflowHandle]:
    handles = []
    for value in values:
        handles.append(
            await client.start_workflow(
                DispatchProbeWorkflow.run,
                value,
                id=f"{probe_id}/{value['id']}",
                task_queue=workflow_task_queue,
            )
        )
    return handles


async def wait_for_backlog(
    client: Client,
    namespace: str,
    queues: ComputeTaskQueues,
    minimum: tuple[int, int],
) -> None:
    async def wait() -> None:
        while True:
            current = await activity_backlogs(client, namespace, queues)
            if current[0] >= minimum[0] and current[1] >= minimum[1]:
                return
            await asyncio.sleep(0.05)

    await asyncio.wait_for(wait(), timeout=40)


async def advance_slot(state: ProbeState, slot: int) -> dict[str, Any]:
    current = await state.request_for_slot(slot)
    current_id = str(current["id"])
    await state.release_slot(slot)
    await state.wait_for(
        lambda: slot in state.running
        and str(state.running[slot][0]["id"]) != current_id
    )
    return await state.request_for_slot(slot)


async def advance_slots(
    state: ProbeState,
    slots: list[int],
) -> list[tuple[int, dict[str, Any]]]:
    current_ids = {
        slot: str((await state.request_for_slot(slot))["id"])
        for slot in slots
    }
    async with state.condition:
        for slot in slots:
            state.running[slot][1].set()
    await state.wait_for(
        lambda: all(
            slot in state.running
            and str(state.running[slot][0]["id"]) != current_ids[slot]
            for slot in slots
        )
    )
    return [
        (slot, await state.request_for_slot(slot))
        for slot in slots
    ]


async def complete_tier(
    state: ProbeState,
    *,
    tier: str,
    expected_starts: int,
) -> None:
    def started() -> int:
        return sum(1 for _slot, value, _workspace, _sequence in state.starts if value == tier)

    while started() < expected_starts:
        async with state.condition:
            slots = [
                slot
                for slot, (request, _release) in state.running.items()
                if request["tier"] == tier
            ]
            before = started()
        if not slots:
            await state.wait_for(
                lambda before=before: started() > before
            )
            continue
        slot = slots[0]
        await state.release_slot(slot)
        await state.wait_for(
            lambda before=before, slot=slot: (
                started() > before or slot not in state.running
            )
        )
    async with state.condition:
        slots = [
            slot
            for slot, (request, _release) in state.running.items()
            if request["tier"] == tier
        ]
    for slot in slots:
        await state.release_slot(slot)


def assert_workspace_fairness(
    starts: list[tuple[int, str, str, int]],
    tier: str,
) -> None:
    tier_starts = [item for item in starts if item[1] == tier]
    counts = Counter(item[2] for item in tier_starts)
    assert set(counts) == {"workspace-0", "workspace-1"}
    assert abs(counts["workspace-0"] - counts["workspace-1"]) <= 1


def assert_batch_fifo(
    batches: list[dict[str, object]],
    tier: str,
) -> None:
    last_sequence = {"workspace-0": 0, "workspace-1": 0}
    for batch in batches:
        tasks = batch["tasks"]
        assert isinstance(tasks, list)
        for workspace_id in last_sequence:
            sequences = sorted(
                sequence
                for value, workspace, sequence in tasks
                if value == tier and workspace == workspace_id
            )
            if not sequences:
                continue
            expected = list(
                range(
                    last_sequence[workspace_id] + 1,
                    last_sequence[workspace_id] + len(sequences) + 1,
                )
            )
            assert sequences == expected
            last_sequence[workspace_id] = sequences[-1]


def normalized_dispatch_batch(
    decisions: list[tuple[int, dict[str, Any]]],
) -> dict[str, object]:
    return {
        "slot_tiers": sorted(
            (slot, str(request["tier"]))
            for slot, request in decisions
        ),
        "tasks": sorted(
            (
                str(request["tier"]),
                str(request["workspace_id"]),
                int(request["sequence"]),
            )
            for _slot, request in decisions
        ),
    }


def dispatch_decision_signature(
    batches: list[dict[str, object]],
    starts: list[tuple[int, str, str, int]],
) -> dict[str, object]:
    counts = Counter(
        (tier, workspace)
        for _slot, tier, workspace, _sequence in starts
    )
    return {
        "decisions": {
            "availability_batches": [
                batch["slot_tiers"]
                for batch in batches
            ],
        },
        "workspace_dispatches": sorted(
            (tier, workspace, count)
            for (tier, workspace), count in counts.items()
        ),
    }


async def run_once(
    client: Client,
    slot_clients: list[Client],
    namespace: str,
    probe_id: str,
) -> dict[str, object]:
    from thesistrace.hosted.data_worker import build_data_worker
    from thesistrace.hosted.temporal_worker import (
        build_compute_activity_worker,
        build_compute_workflow_worker,
    )

    queues = ComputeTaskQueues(
        workflow=f"{probe_id}-workflow",
        p1=f"{probe_id}-p1",
        p3=f"{probe_id}-p3",
    )
    data_queue = f"{probe_id}-data"
    state = ProbeState()
    workflow_worker = build_compute_workflow_worker(
        client,
        task_queue=queues.workflow,
        workflows=[DispatchProbeWorkflow],
    )
    data_worker = build_data_worker(
        client,
        task_queue=data_queue,
        workflows=[DataDispatchProbeWorkflow],
        activities=[data_activity(state)],
    )
    worker_tasks = [
        asyncio.create_task(workflow_worker.run()),
        asyncio.create_task(data_worker.run()),
    ]
    poller_tasks: list[asyncio.Task] = []
    handles: list[WorkflowHandle] = []
    try:
        p1_requests = requests(
            tier="p1",
            count=32,
            task_queue=queues.p1,
            phase="both",
        )
        p3_requests = requests(
            tier="p3",
            count=32,
            task_queue=queues.p3,
            phase="both",
        )
        handles.extend(
            await start_requests(
                client,
                queues.workflow,
                probe_id,
                p1_requests,
            )
        )
        handles.extend(
            await start_requests(
                client,
                queues.workflow,
                probe_id,
                p3_requests,
            )
        )
        await wait_for_backlog(client, namespace, queues, (32, 32))

        data_handle = await client.start_workflow(
            DataDispatchProbeWorkflow.run,
            {"id": "data"},
            id=f"{probe_id}/data",
            task_queue=data_queue,
        )

        async def backlog() -> tuple[int, int]:
            return await activity_backlogs(client, namespace, queues)

        for slot, preference in enumerate(PREFERENCES):
            def worker_factory(task_queue: str, *, slot: int = slot) -> Worker:
                return build_compute_activity_worker(
                    slot_clients[slot],
                    task_queue=task_queue,
                    activities=[compute_activity(state, slot)],
                    identity=f"{probe_id}-slot-{slot}",
                )

            poller_tasks.append(
                asyncio.create_task(
                    run_preferred_activity_poller(
                        preference=preference,
                        worker_factory=worker_factory,
                        backlog=backlog,
                        poll_interval_seconds=0.05,
                        queues=queues,
                    )
                )
            )
            await asyncio.sleep(0.1)
            if poller_tasks[-1].done():
                await poller_tasks[-1]
            await state.wait_for(lambda slot=slot: slot in state.running)

        await state.wait_for(
            lambda: state.compute_running == 4 and state.data_running == 1
        )
        assert state.max_compute_running == 4
        assert state.max_data_running == 1
        assert [state.running[index][0]["tier"] for index in range(4)] == [
            "p1",
            "p1",
            "p1",
            "p3",
        ]
        controlled_batches = [
            normalized_dispatch_batch(
                [
                    (slot, await state.request_for_slot(slot))
                    for slot in range(4)
                ]
            )
        ]

        for _cycle in range(6):
            decisions = await advance_slots(state, list(range(4)))
            for slot, next_request in decisions:
                assert next_request["tier"] == PREFERENCES[slot]
            controlled_batches.append(
                normalized_dispatch_batch(decisions)
            )

        for _cycle in range(9):
            next_request = await advance_slot(state, 3)
            assert next_request["tier"] == "p3"
            controlled_batches.append(
                normalized_dispatch_batch([(3, next_request)])
            )

        controlled_trace = list(state.starts)
        assert len(controlled_trace) == 37
        assert_workspace_fairness(controlled_trace, "p1")
        assert_workspace_fairness(controlled_trace, "p3")
        assert_batch_fifo(controlled_batches, "p1")
        assert_batch_fifo(controlled_batches, "p3")

        await complete_tier(state, tier="p1", expected_starts=32)
        await state.wait_for(
            lambda: len(state.running) == 4
            and all(
                request["tier"] == "p3"
                for request, _release in state.running.values()
            )
        )
        assert [state.running[index][0]["tier"] for index in range(4)] == [
            "p3",
            "p3",
            "p3",
            "p3",
        ]

        borrowed_p3 = {
            slot: await state.request_for_slot(slot)
            for slot in range(4)
        }
        later_p1 = requests(
            tier="p1",
            count=8,
            task_queue=queues.p1,
            phase="later-p1",
        )
        later_p1_handles = await start_requests(
            client,
            queues.workflow,
            probe_id,
            later_p1,
        )
        await wait_for_backlog(client, namespace, queues, (8, 0))
        await asyncio.sleep(0.2)
        assert {
            slot: await state.request_for_slot(slot)
            for slot in range(4)
        } == borrowed_p3

        for slot in range(3):
            assert (await advance_slot(state, slot))["tier"] == "p1"
        assert await state.request_for_slot(3) == borrowed_p3[3]

        await complete_tier(state, tier="p3", expected_starts=32)
        await asyncio.gather(
            *(handle.result() for handle in handles),
        )
        await state.wait_for(
            lambda: len(state.running) == 4
            and all(
                request["tier"] == "p1"
                for request, _release in state.running.values()
            )
        )
        assert set(state.running) == {0, 1, 2, 3}
        await complete_tier(state, tier="p1", expected_starts=40)
        await asyncio.gather(
            *(handle.result() for handle in later_p1_handles),
        )

        state.data_release.set()
        await data_handle.result()
        return dispatch_decision_signature(
            controlled_batches,
            controlled_trace,
        )
    finally:
        await state.release_everything()
        for task in poller_tasks:
            task.cancel()
        await asyncio.gather(*poller_tasks, return_exceptions=True)
        await workflow_worker.shutdown()
        await data_worker.shutdown()
        await asyncio.gather(*worker_tasks, return_exceptions=True)


async def probe(address: str, namespace: str) -> None:
    client = await Client.connect(address, namespace=namespace)
    slot_clients = [
        await Client.connect(address, namespace=namespace)
        for _slot in PREFERENCES
    ]
    run_id = uuid4().hex
    first = await run_once(
        client,
        slot_clients,
        namespace,
        f"dispatch-{run_id}-a",
    )
    second = await run_once(
        client,
        slot_clients,
        namespace,
        f"dispatch-{run_id}-b",
    )
    if first["decisions"] != second["decisions"]:
        print(f"first dispatch trace: {first}")
        print(f"second dispatch trace: {second}")
    assert first["decisions"] == second["decisions"]
    print(
        "Temporal dispatch probe passed: "
        f"decisions={first['decisions']}, "
        f"workspace_dispatches={[first['workspace_dispatches'], second['workspace_dispatches']]}, "
        "max_compute=4, independent_data=1"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="temporal:7233")
    parser.add_argument("--namespace", default="thesistrace")
    args = parser.parse_args()
    asyncio.run(probe(args.address, args.namespace))


if __name__ == "__main__":
    main()

import argparse
import asyncio
import json

from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import Worker

TASK_QUEUE = "thesistrace-recovery-probe"


@workflow.defn(name="HostedRecoveryProbeWorkflow")
class RecoveryProbeWorkflow:
    def __init__(self) -> None:
        self.released = False

    @workflow.run
    async def run(self, probe_id: str) -> dict[str, str]:
        await workflow.wait_condition(lambda: self.released)
        return {"probe_id": probe_id, "status": "continued_after_restore"}

    @workflow.signal
    def continue_after_restore(self) -> None:
        self.released = True


async def start_probe(address: str, namespace: str, probe_id: str) -> None:
    client = await Client.connect(address, namespace=namespace)
    await client.start_workflow(
        RecoveryProbeWorkflow.run,
        probe_id,
        id=probe_id,
        task_queue=TASK_QUEUE,
    )
    print(json.dumps({"probe_id": probe_id, "status": "started"}, sort_keys=True))


async def verify_probe(address: str, namespace: str, probe_id: str) -> None:
    client = await Client.connect(address, namespace=namespace)
    handle = client.get_workflow_handle(probe_id)
    description = await handle.describe()
    if description.status.name != "RUNNING":
        raise RuntimeError("recovery probe was not restored as a running Workflow")
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[RecoveryProbeWorkflow],
    ):
        await handle.signal(RecoveryProbeWorkflow.continue_after_restore)
        result = await asyncio.wait_for(handle.result(), timeout=60)
    if result != {"probe_id": probe_id, "status": "continued_after_restore"}:
        raise RuntimeError("restored recovery probe returned an invalid result")
    print(json.dumps(result, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "verify"))
    parser.add_argument("--probe-id", required=True)
    parser.add_argument("--address", default="temporal:7233")
    parser.add_argument("--namespace", default="thesistrace")
    arguments = parser.parse_args()
    operation = start_probe if arguments.action == "start" else verify_probe
    asyncio.run(operation(arguments.address, arguments.namespace, arguments.probe_id))


if __name__ == "__main__":
    main()

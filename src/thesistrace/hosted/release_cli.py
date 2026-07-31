import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from temporalio.client import Client

from thesistrace.config import database_url_from_environment
from thesistrace.hosted.release_operations import (
    PostgresMaintenanceGate,
    ReleaseBundle,
    ReleaseOperationError,
    activate_candidate_release,
    activate_previous_release,
    install_release_bundle,
    seal_recovery_bundle,
    stage_release_bundle,
)

PRODUCTION_WORKFLOW_TYPES = (
    "DatasetPublicationWorkflow",
    "ScheduledDatasetPublicationWorkflow",
    "ResearchWorkflow",
    "TrackingReleaseWorkflow",
    "TrackingAdvanceWorkflow",
    "TrackingEquivalenceWorkflow",
    "TrackingGenerationRebuildWorkflow",
)


class TemporalMaintenanceControl:
    def __init__(self, client: Client) -> None:
        self.client = client

    async def pause_schedules(self) -> int:
        count = 0
        schedules = await self.client.list_schedules()
        async for schedule in schedules:
            await self.client.get_schedule_handle(schedule.id).pause(
                note="ThesisTrace release maintenance"
            )
            count += 1
        return count

    async def resume_schedules(self) -> int:
        count = 0
        schedules = await self.client.list_schedules()
        async for schedule in schedules:
            await self.client.get_schedule_handle(schedule.id).unpause(
                note="ThesisTrace release maintenance complete"
            )
            count += 1
        return count

    async def running_activity_count(self) -> int:
        count = 0
        workflow_filter = " OR ".join(
            f'WorkflowType="{workflow_type}"'
            for workflow_type in PRODUCTION_WORKFLOW_TYPES
        )
        executions = self.client.list_workflows(
            f'ExecutionStatus="Running" AND ({workflow_filter})'
        )
        async for execution in executions:
            description = await self.client.get_workflow_handle(
                execution.id,
                run_id=execution.run_id,
            ).describe()
            count += len(description.raw_description.pending_activities)
        return count


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ReleaseOperationError(f"{name} is required")
    return value


async def enter_maintenance(max_drain_seconds: int) -> dict[str, object]:
    if not 1 <= max_drain_seconds <= 900:
        raise ReleaseOperationError("maintenance drain must be between 1 and 900 seconds")
    database_url = database_url_from_environment()
    if not database_url:
        raise ReleaseOperationError("maintenance database credentials are required")
    gate = PostgresMaintenanceGate(database_url)
    await asyncio.to_thread(gate.set_enabled, True)
    client = await Client.connect(
        os.environ.get("THESISTRACE_TEMPORAL_ADDRESS", "temporal:7233"),
        namespace=os.environ.get("THESISTRACE_TEMPORAL_NAMESPACE", "thesistrace"),
    )
    temporal = TemporalMaintenanceControl(client)
    paused = await temporal.pause_schedules()
    deadline = time.monotonic() + max_drain_seconds
    remaining = await temporal.running_activity_count()
    while remaining > 0 and time.monotonic() < deadline:
        await asyncio.sleep(min(2.0, deadline - time.monotonic()))
        remaining = await temporal.running_activity_count()
    return {
        "maintenance": "entered",
        "paused_schedules": paused,
        "drained": remaining == 0,
        "remaining_activities": remaining,
        "interrupted_activity_state": (
            "none" if remaining == 0 else "nonterminal_redelivery"
        ),
    }


async def exit_maintenance() -> dict[str, object]:
    database_url = database_url_from_environment()
    if not database_url:
        raise ReleaseOperationError("maintenance database credentials are required")
    gate = PostgresMaintenanceGate(database_url)
    client = await Client.connect(
        os.environ.get("THESISTRACE_TEMPORAL_ADDRESS", "temporal:7233"),
        namespace=os.environ.get("THESISTRACE_TEMPORAL_NAMESPACE", "thesistrace"),
    )
    resumed = await TemporalMaintenanceControl(client).resume_schedules()
    await asyncio.to_thread(gate.set_enabled, False)
    return {"maintenance": "exited", "resumed_schedules": resumed}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Operate immutable Hosted releases")
    commands = result.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install-bundle")
    install.add_argument("--repository-root", type=Path, required=True)
    install.add_argument("--state-root", type=Path, required=True)
    install.add_argument("--manifest", type=Path, required=True)
    stage = commands.add_parser("stage-bundle")
    stage.add_argument("--repository-root", type=Path, required=True)
    stage.add_argument("--state-root", type=Path, required=True)
    stage.add_argument("--manifest", type=Path, required=True)
    activate = commands.add_parser("activate-candidate")
    activate.add_argument("--state-root", type=Path, required=True)
    rollback = commands.add_parser("activate-previous")
    rollback.add_argument("--state-root", type=Path, required=True)
    enter = commands.add_parser("maintenance-enter")
    enter.add_argument("--max-drain-seconds", type=int, default=900)
    commands.add_parser("maintenance-exit")
    recovery = commands.add_parser("seal-recovery")
    recovery.add_argument("--secret-root", type=Path, required=True)
    recovery.add_argument("--output", type=Path, required=True)
    recovery.add_argument("--passphrase-file", type=Path, required=True)
    return result


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command in {"install-bundle", "stage-bundle"}:
        bundle = ReleaseBundle.from_manifest(
            arguments.manifest,
            arguments.repository_root,
        )
        bundle_id = (
            install_release_bundle(arguments.state_root, bundle)
            if arguments.command == "install-bundle"
            else stage_release_bundle(arguments.state_root, bundle)
        )
        output: object = {
            "bundle_id": bundle_id,
            "version": bundle.version,
        }
    elif arguments.command == "activate-candidate":
        output = activate_candidate_release(arguments.state_root)
    elif arguments.command == "activate-previous":
        output = activate_previous_release(arguments.state_root)
    elif arguments.command == "maintenance-enter":
        output = asyncio.run(enter_maintenance(arguments.max_drain_seconds))
    elif arguments.command == "seal-recovery":
        values = {
            path.name: path.read_text().rstrip("\n")
            for path in sorted(arguments.secret_root.iterdir())
            if path.is_file()
        }
        seal_recovery_bundle(
            arguments.output,
            values,
            passphrase=arguments.passphrase_file.read_text().rstrip("\n"),
        )
        output = {"recovery_bundle": str(arguments.output), "secret_count": len(values)}
    else:
        output = asyncio.run(exit_maintenance())
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    if isinstance(output, dict) and output.get("status") == "restore_required":
        raise SystemExit(3)


if __name__ == "__main__":
    main()

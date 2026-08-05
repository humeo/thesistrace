import argparse
import asyncio
import json
from pathlib import Path

from thesistrace.config import database_url_from_environment
from thesistrace.hosted.release_operations import (
    PostgresMaintenanceGate,
    ReleaseBundle,
    ReleaseOperationError,
    activate_candidate_release,
    activate_previous_release,
    lock_release_images,
    seal_recovery_bundle,
    stage_release_bundle,
    validate_previous_release,
    verify_release_image_lock,
)


async def enter_maintenance(max_drain_seconds: int) -> dict[str, object]:
    if not 1 <= max_drain_seconds <= 900:
        raise ReleaseOperationError("maintenance drain must be between 1 and 900 seconds")
    database_url = database_url_from_environment()
    if not database_url:
        raise ReleaseOperationError("maintenance database credentials are required")
    gate = PostgresMaintenanceGate(database_url)
    await asyncio.to_thread(gate.set_enabled, True)
    return {"maintenance": "entered"}


async def exit_maintenance() -> dict[str, object]:
    database_url = database_url_from_environment()
    if not database_url:
        raise ReleaseOperationError("maintenance database credentials are required")
    gate = PostgresMaintenanceGate(database_url)
    await asyncio.to_thread(gate.set_enabled, False)
    return {"maintenance": "exited"}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Operate immutable Hosted releases")
    commands = result.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage-bundle")
    stage.add_argument("--repository-root", type=Path, required=True)
    stage.add_argument("--state-root", type=Path, required=True)
    stage.add_argument("--manifest", type=Path, required=True)
    activate = commands.add_parser("activate-candidate")
    activate.add_argument("--state-root", type=Path, required=True)
    for name in ("lock-images", "verify-images"):
        images = commands.add_parser(name)
        images.add_argument("--state-root", type=Path, required=True)
        images.add_argument("--bundle-id", required=True)
        images.add_argument("--image", action="append", required=True)
    rollback = commands.add_parser("activate-previous")
    rollback.add_argument("--state-root", type=Path, required=True)
    rollback_check = commands.add_parser("check-previous")
    rollback_check.add_argument("--state-root", type=Path, required=True)
    enter = commands.add_parser("maintenance-enter")
    enter.add_argument("--max-drain-seconds", type=int, default=900)
    commands.add_parser("maintenance-exit")
    recovery = commands.add_parser("seal-recovery")
    recovery.add_argument("--secret-root", type=Path, required=True)
    recovery.add_argument("--output", type=Path, required=True)
    recovery.add_argument("--passphrase-file", type=Path, required=True)
    return result


def parsed_images(values: list[str]) -> dict[str, str]:
    try:
        images = dict(value.split("=", 1) for value in values)
    except ValueError as error:
        raise ReleaseOperationError("images must use NAME=SHA256 format") from error
    if len(images) != len(values):
        raise ReleaseOperationError("release image names must be unique")
    return images


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "stage-bundle":
        bundle = ReleaseBundle.from_manifest(
            arguments.manifest,
            arguments.repository_root,
        )
        bundle_id = stage_release_bundle(arguments.state_root, bundle)
        output: object = {
            "bundle_id": bundle_id,
            "version": bundle.version,
        }
    elif arguments.command == "activate-candidate":
        output = activate_candidate_release(arguments.state_root)
    elif arguments.command in {"lock-images", "verify-images"}:
        images = parsed_images(arguments.image)
        operation = (
            lock_release_images
            if arguments.command == "lock-images"
            else verify_release_image_lock
        )
        output = operation(arguments.state_root, arguments.bundle_id, images)
    elif arguments.command == "activate-previous":
        output = activate_previous_release(arguments.state_root)
    elif arguments.command == "check-previous":
        output = validate_previous_release(arguments.state_root)
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

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from thesistrace.capacity import (
    CapacityQualificationError,
    CapacityQualificationService,
)
from thesistrace.config import Settings, settings_from_environment
from thesistrace.datasets import DatasetPublisher
from thesistrace.management import (
    HOSTED_TUSHARE_SCOPE,
    SourceAuthorizationError,
    SourceAuthorizationService,
    build_management_store,
)
from thesistrace.platform_publications import (
    DatasetPublicationRequestError,
    DatasetPublicationRequestService,
    DatasetPublicationRequestStore,
)
from thesistrace.provisioning import (
    ProvisioningError,
    RegistrationService,
    build_registration_service,
)
from thesistrace.quota import (
    QuotaProfileError,
    QuotaProfileService,
    QuotaProfileStore,
)
from thesistrace.runtime import build_runtime
from thesistrace.storage import MetadataStore
from thesistrace.tenancy import workspace_execution
from thesistrace.tracking import DailyTrackingError, DailyTrackingService
from thesistrace.tracking_operations import (
    TrackingOperationError,
    TrackingOperationService,
)

CLI_VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate a ThesisTrace hosted deployment")
    parser.add_argument("--version", action="version", version=f"%(prog)s {CLI_VERSION}")
    resources = parser.add_subparsers(dest="resource", required=True)

    source_authorization = resources.add_parser("source-authorization")
    commands = source_authorization.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record")
    record.add_argument("--actor", required=True)
    record.add_argument("--scope", required=True)

    commands.add_parser("inspect")

    capacity = resources.add_parser("capacity-qualification")
    capacity_commands = capacity.add_subparsers(dest="command", required=True)
    capacity_record = capacity_commands.add_parser("record")
    capacity_record.add_argument("--actor", required=True)
    capacity_record.add_argument("--release-bundle-id", required=True)
    capacity_record.add_argument("--evidence", type=Path, required=True)
    capacity_commands.add_parser("inspect")

    invitations = resources.add_parser("invitation")
    invitation_commands = invitations.add_subparsers(dest="command", required=True)

    issue = invitation_commands.add_parser("issue")
    issue.add_argument("--actor", required=True)
    issue.add_argument("--email", required=True)
    issue.add_argument("--expires-at", required=True)

    revoke = invitation_commands.add_parser("revoke")
    revoke.add_argument("--actor", required=True)
    revoke.add_argument("--invitation-id", required=True)

    inspect = invitation_commands.add_parser("inspect")
    inspect.add_argument("--invitation-id", required=True)

    quotas = resources.add_parser("quota")
    quota_commands = quotas.add_subparsers(dest="command", required=True)

    quota_inspect = quota_commands.add_parser("inspect")
    quota_inspect.add_argument("--workspace-id", required=True)

    quota_override = quota_commands.add_parser("override")
    quota_override.add_argument("--actor", required=True)
    quota_override.add_argument("--workspace-id", required=True)
    quota_override.add_argument("--max-active-daily-tracks", type=int)
    quota_override.add_argument(
        "--max-nonterminal-user-compute-jobs",
        type=int,
    )
    quota_override.add_argument("--max-private-storage-bytes", type=int)

    publications = resources.add_parser("dataset-publication")
    publication_commands = publications.add_subparsers(
        dest="command",
        required=True,
    )
    publication_request = publication_commands.add_parser("request")
    publication_request.add_argument("--actor", required=True)
    publication_request.add_argument(
        "--request-version",
        choices=("v1",),
        default="v1",
    )
    publication_request.add_argument(
        "--kind",
        choices=(
            "fixture_bootstrap",
            "fixture_increment",
            "live_bootstrap",
            "live_increment",
        ),
        required=True,
    )
    publication_request.add_argument("--idempotency-key", required=True)
    publication_request.add_argument("--as-of")
    publication_request.add_argument("--new-sessions", type=int)
    publication_request.add_argument("--corrections-json", default="[]")

    tracking_rebuilds = resources.add_parser(
        "tracking-generation-rebuild"
    )
    rebuild_commands = tracking_rebuilds.add_subparsers(
        dest="command",
        required=True,
    )
    rebuild_request = rebuild_commands.add_parser("request")
    rebuild_request.add_argument("--actor", required=True)
    rebuild_request.add_argument("--workspace-id", required=True)
    rebuild_request.add_argument("--track-id", required=True)
    rebuild_request.add_argument("--calculation-kernel", required=True)
    rebuild_request.add_argument(
        "--numeric-execution-contract",
        required=True,
    )
    rebuild_request.add_argument("--idempotency-key", required=True)
    rebuild_cancel = rebuild_commands.add_parser("cancel")
    rebuild_cancel.add_argument("--actor", required=True)
    rebuild_cancel.add_argument("--workspace-id", required=True)
    rebuild_cancel.add_argument("--rebuild-id", required=True)
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    registration_service: RegistrationService | None = None,
    quota_service: QuotaProfileService | None = None,
    publication_request_service: DatasetPublicationRequestService | None = None,
    tracking_operation_service: TrackingOperationService | None = None,
) -> int:
    arguments = build_parser().parse_args(argv)
    active_settings = settings or settings_from_environment()
    local_store = MetadataStore(active_settings.metadata_path)
    if not active_settings.database_url:
        local_store.initialize()
    management_store = build_management_store(active_settings, local_store)
    service = SourceAuthorizationService(management_store)

    if arguments.resource == "capacity-qualification":
        capacity_service = CapacityQualificationService(management_store)
        if arguments.command == "inspect":
            print(
                json.dumps(
                    capacity_service.inspect(),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        try:
            evidence = json.loads(arguments.evidence.read_text(encoding="utf-8"))
            if not isinstance(evidence, dict):
                raise ValueError("capacity evidence must be a JSON object")
            qualification = capacity_service.record(
                actor=arguments.actor,
                release_bundle_id=arguments.release_bundle_id,
                evidence=evidence,
            )
        except (OSError, ValueError, CapacityQualificationError) as error:
            print(
                json.dumps(
                    {
                        "reason_code": getattr(
                            error,
                            "reason_code",
                            "CAPACITY_QUALIFICATION_INVALID",
                        ),
                        "message": str(error),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        print(json.dumps(qualification, ensure_ascii=False, sort_keys=True))
        return 0

    if arguments.resource == "tracking-generation-rebuild":
        actor = arguments.actor.strip()
        if not actor:
            print(
                json.dumps(
                    {
                        "reason_code": "OPERATOR_ACTOR_REQUIRED",
                        "message": "Operator actor is required",
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        def operate(
            operations: TrackingOperationService,
        ) -> tuple[dict[str, object], bool | None]:
            if arguments.command == "cancel":
                return (
                    operations.cancel_generation_rebuild(
                        arguments.rebuild_id,
                        enqueue_workflow_cancellation=(
                            active_settings.runtime_mode == "hosted"
                        ),
                    ),
                    None,
                )
            return operations.request_generation_rebuild(
                arguments.track_id,
                calculation_kernel=arguments.calculation_kernel,
                numeric_execution_contract=(
                    arguments.numeric_execution_contract
                ),
                idempotency_key=arguments.idempotency_key,
                operator_authorized=True,
            )

        try:
            operations = tracking_operation_service
            if operations is None:
                compute_settings = replace(
                    active_settings,
                    database_role="compute",
                )
                with workspace_execution(arguments.workspace_id):
                    runtime = build_runtime(compute_settings)
                    tracking = DailyTrackingService(
                        runtime.control_metadata,
                        DatasetPublisher(
                            runtime.control_metadata,
                            runtime.objects,
                        ),
                        runtime.objects,
                        runtime.working_cache,
                    )
                    operations = TrackingOperationService(
                        runtime.control_metadata,
                        tracking,
                    )
                    rebuild, created = operate(operations)
            else:
                rebuild, created = operate(operations)
        except (
            KeyError,
            PermissionError,
            TrackingOperationError,
            DailyTrackingError,
        ):
            print(
                json.dumps(
                    {
                        "reason_code": (
                            "TRACKING_GENERATION_REBUILD_DENIED"
                        ),
                        "message": (
                            "DailyTrack or Generation rebuild not found "
                            "or operation not allowed"
                        ),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        action = (
            "tracking_generation_rebuild.cancel"
            if arguments.command == "cancel"
            else "tracking_generation_rebuild.request"
        )
        management_store.append_management_audit_event(
            {
                "id": f"audit_{uuid4().hex}",
                "occurred_at": datetime.now(UTC).isoformat(),
                "actor": actor,
                "action": action,
                "outcome": "succeeded",
                "reason_code": None,
                "subject_type": "tracking_generation_rebuild",
                "subject_id": rebuild["id"],
                "details": {
                    "workspace_id": arguments.workspace_id,
                    **(
                        {"daily_track_id": arguments.track_id}
                        if arguments.command == "request"
                        else {}
                    ),
                },
            }
        )
        response: dict[str, object] = {"rebuild": rebuild}
        if created is not None:
            response["created"] = created
        print(
            json.dumps(
                response,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if arguments.resource == "dataset-publication":
        publications = (
            publication_request_service
            or DatasetPublicationRequestService(
                cast(DatasetPublicationRequestStore, management_store),
                service,
            )
        )
        try:
            parameters = _publication_parameters(arguments)
            publication, created = publications.request(
                actor=arguments.actor,
                request_version=arguments.request_version,
                kind=arguments.kind,
                parameters=parameters,
                idempotency_key=arguments.idempotency_key,
            )
        except (DatasetPublicationRequestError, ValueError) as error:
            print(
                json.dumps(
                    {
                        "reason_code": (
                            error.reason_code
                            if isinstance(
                                error,
                                DatasetPublicationRequestError,
                            )
                            else "DATASET_PUBLICATION_PARAMETERS_INVALID"
                        ),
                        "message": str(error),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                {
                    "created": created,
                    "publication": publication,
                },
                default=_json_default,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if arguments.resource == "quota":
        if quota_service is None and not active_settings.database_url:
            print(
                json.dumps(
                    {
                        "reason_code": "HOSTED_DATABASE_REQUIRED",
                        "message": "Quota Profiles require the hosted database",
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        quotas = quota_service or QuotaProfileService(
            cast(QuotaProfileStore, management_store)
        )
        try:
            if arguments.command == "inspect":
                profile = quotas.inspect(arguments.workspace_id)
            else:
                profile = quotas.override(
                    actor=arguments.actor,
                    workspace_id=arguments.workspace_id,
                    max_active_daily_tracks=arguments.max_active_daily_tracks,
                    max_nonterminal_user_compute_jobs=(
                        arguments.max_nonterminal_user_compute_jobs
                    ),
                    max_private_storage_bytes=(
                        arguments.max_private_storage_bytes
                    ),
                )
        except QuotaProfileError as error:
            print(
                json.dumps(
                    {
                        "reason_code": error.reason_code,
                        "message": str(error),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                {
                    "workspace_id": arguments.workspace_id,
                    "profile": profile,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if arguments.resource == "invitation":
        registration = registration_service or build_registration_service(
            settings=active_settings,
            source_authorization=service,
        )
        try:
            if arguments.command == "issue":
                invitation = registration.issue_invitation(
                    actor=arguments.actor,
                    email=arguments.email,
                    expires_at=_parse_instant(arguments.expires_at),
                )
            elif arguments.command == "revoke":
                invitation = registration.revoke_invitation(
                    actor=arguments.actor,
                    invitation_id=arguments.invitation_id,
                )
            else:
                invitation = registration.invitation(arguments.invitation_id)
                if invitation is None:
                    raise ProvisioningError(
                        "INVITATION_NOT_FOUND",
                        "registration invitation not found",
                    )
        except (ProvisioningError, ValueError) as error:
            reason_code = (
                error.reason_code
                if isinstance(error, ProvisioningError)
                else "INVITATION_EXPIRY_INVALID"
            )
            print(
                json.dumps(
                    {"reason_code": reason_code, "message": str(error)},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                invitation,
                default=_json_default,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "inspect":
        declaration = service.inspect()
        print(json.dumps(declaration, ensure_ascii=False, sort_keys=True))
        return 0

    try:
        declaration = service.record(actor=arguments.actor, scope=arguments.scope)
    except SourceAuthorizationError as error:
        print(
            json.dumps(
                {"reason_code": error.reason_code, "message": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "declaration": declaration,
                "notice": (
                    "This records the Operator policy declaration; "
                    "it does not validate upstream legal rights."
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["HOSTED_TUSHARE_SCOPE", "main", "run"]


def _parse_instant(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("expiry must include a timezone")
    return parsed


def _json_default(value: object) -> object:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _publication_parameters(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.kind == "fixture_bootstrap":
        return {"fixture": "v1"}
    if arguments.kind == "fixture_increment":
        try:
            corrections = json.loads(arguments.corrections_json)
        except json.JSONDecodeError as error:
            raise ValueError("corrections must be valid JSON") from error
        if not isinstance(corrections, list):
            raise ValueError("corrections must be a JSON list")
        return {
            "new_sessions": arguments.new_sessions,
            "corrections": corrections,
        }
    return {"as_of": arguments.as_of}

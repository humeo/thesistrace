import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime

from thesistrace.config import Settings, settings_from_environment
from thesistrace.management import (
    HOSTED_TUSHARE_SCOPE,
    SourceAuthorizationError,
    SourceAuthorizationService,
    build_management_store,
)
from thesistrace.provisioning import (
    ProvisioningError,
    RegistrationService,
    build_registration_service,
)
from thesistrace.storage import MetadataStore

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
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    registration_service: RegistrationService | None = None,
) -> int:
    arguments = build_parser().parse_args(argv)
    active_settings = settings or settings_from_environment()
    local_store = MetadataStore(active_settings.metadata_path)
    if not active_settings.database_url:
        local_store.initialize()
    service = SourceAuthorizationService(
        build_management_store(active_settings, local_store)
    )

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

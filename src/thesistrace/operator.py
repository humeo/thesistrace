import argparse
import json
import sys
from collections.abc import Sequence

from thesistrace.config import Settings, settings_from_environment
from thesistrace.management import (
    HOSTED_TUSHARE_SCOPE,
    SourceAuthorizationError,
    SourceAuthorizationService,
    build_management_store,
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
    return parser


def run(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    active_settings = settings or settings_from_environment()
    local_store = MetadataStore(active_settings.metadata_path)
    if not active_settings.database_url:
        local_store.initialize()
    service = SourceAuthorizationService(
        build_management_store(active_settings, local_store)
    )

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

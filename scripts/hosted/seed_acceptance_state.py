import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg

from thesistrace.config import database_url_from_environment
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.management import HOSTED_TUSHARE_SCOPE, SourceAuthorizationService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Seed private state for clean-stack Hosted acceptance",
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("assert-clean")
    commands.add_parser("assert-idle")
    commands.add_parser("storage-status")
    commands.add_parser("local-source-authorization")
    invitation = commands.add_parser("invitation")
    invitation.add_argument("--email", required=True)
    otp = commands.add_parser("otp")
    otp.add_argument("--email", required=True)
    otp.add_argument(
        "--purpose",
        choices=("VERIFY_EMAIL", "RESET_PASSWORD"),
        required=True,
    )
    otp.add_argument("--code", required=True)
    publication = commands.add_parser("publication-status")
    publication.add_argument("--publication-id", required=True)
    return result


def main() -> None:
    if os.environ.get("THESISTRACE_ACCEPTANCE_MODE") != "1":
        raise SystemExit("acceptance state seeding is disabled")
    arguments = parser().parse_args()
    database_url = database_url_from_environment()
    if not database_url:
        raise SystemExit("THESISTRACE_DATABASE_URL is required")
    if arguments.command == "assert-clean":
        assert_clean(database_url)
        return
    if arguments.command == "assert-idle":
        assert_idle(database_url)
        return
    if arguments.command == "storage-status":
        inspect_storage(database_url)
        return
    if arguments.command == "local-source-authorization":
        if os.environ.get("THESISTRACE_LOCAL_ACCEPTANCE") != "1":
            raise SystemExit("local source authorization fixture is disabled")
        service = SourceAuthorizationService(PostgresManagementStore(database_url))
        declaration = service.inspect()
        if declaration is None:
            declaration = service.record(
                actor="local-acceptance",
                scope=HOSTED_TUSHARE_SCOPE,
            )
        print(json.dumps(declaration, sort_keys=True))
        return
    if arguments.command == "publication-status":
        inspect_publication(database_url, arguments.publication_id)
        return
    email = arguments.email.strip().casefold()
    if not email or "@" not in email:
        raise SystemExit("a normalized email is required")
    if arguments.command == "invitation":
        seed_invitation(database_url, email)
    else:
        code = arguments.code.strip()
        if len(code) != 6 or not code.isdigit():
            raise SystemExit("acceptance OTP must be a six-digit code")
        seed_otp(database_url, email, arguments.purpose, code)


def assert_clean(database_url: str) -> None:
    tables = (
        "thesistrace_control.product_users",
        "thesistrace_control.personal_workspaces",
        "thesistrace_control.registration_invitations",
        "thesistrace_control.launch_qualifications",
        "thesistrace_product.dataset_releases",
        "thesistrace_product.research_definition_drafts",
        "thesistrace_product.research_runs",
        "thesistrace_product.daily_tracks",
    )
    with psycopg.connect(database_url) as connection:
        counts = {
            table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in tables
        }
    populated = {table: count for table, count in counts.items() if count}
    if populated:
        raise SystemExit(f"Hosted acceptance requires a clean stack: {populated}")
    print("clean Hosted acceptance state verified")


def assert_idle(database_url: str) -> None:
    tables = (
        "thesistrace_product.research_runs",
        "thesistrace_product.dataset_publications",
        "thesistrace_product.tracking_advances",
        "thesistrace_product.tracking_equivalence_requests",
        "thesistrace_product.tracking_generation_rebuilds",
    )
    with psycopg.connect(database_url) as connection:
        counts = {
            table: int(
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE status IN ('queued', 'running')"
                ).fetchone()[0]
            )
            for table in tables
        }
    busy = {table: count for table, count in counts.items() if count}
    if busy:
        raise SystemExit(f"Hosted browser acceptance requires an idle stack: {busy}")
    print(json.dumps({"status": "passed", "workflow_running": 0}, sort_keys=True))


def seed_invitation(database_url: str, email: str) -> None:
    now = datetime.now(UTC)
    invitation_id = f"invite_acceptance_{uuid4().hex}"
    with psycopg.connect(database_url) as connection:
        insert_audit_event(
            connection,
            action="acceptance.invitation.seed",
            subject_type="registration_invitation",
            subject_id=invitation_id,
            details={"fixture": True},
        )
        connection.execute(
            """
            INSERT INTO thesistrace_control.registration_invitations (
                id, normalized_email, state, issued_by, issued_at, expires_at
            )
            VALUES (%s, %s, 'issued', 'release-acceptance-fixture', %s, %s)
            """,
            (
                invitation_id,
                email,
                now,
                now + timedelta(hours=1),
            ),
        )
    print("acceptance invitation seeded")


def seed_otp(
    database_url: str,
    email: str,
    purpose: str,
    code: str,
) -> None:
    with psycopg.connect(database_url) as connection:
        subject_id = hashlib.sha256(email.encode()).hexdigest()[:20]
        insert_audit_event(
            connection,
            action="acceptance.otp.seed",
            subject_type="email_otp",
            subject_id=subject_id,
            details={"fixture": True, "purpose": purpose},
        )
        connection.execute(
            """
            INSERT INTO auth.email_otps (
                email, purpose, otp_hash, otp_type, expires_at,
                consumed_at, redirect_to, attempts_count
            )
            VALUES (
                %s, %s, crypt(%s, gen_salt('bf', 10)), 'NUMERIC_CODE',
                now() + interval '15 minutes', NULL, NULL, 0
            )
            ON CONFLICT (email, purpose)
            DO UPDATE SET
                otp_hash = EXCLUDED.otp_hash,
                otp_type = EXCLUDED.otp_type,
                expires_at = EXCLUDED.expires_at,
                consumed_at = NULL,
                redirect_to = NULL,
                attempts_count = 0,
                updated_at = now()
            """,
            (email, purpose, code),
        )
    print(f"acceptance {purpose} OTP seeded")


def insert_audit_event(
    connection: psycopg.Connection,
    *,
    action: str,
    subject_type: str,
    subject_id: str,
    details: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO thesistrace_control.management_audit_events (
            id, occurred_at, actor, action, outcome, reason_code,
            subject_type, subject_id, details_json
        )
        VALUES (%s, now(), 'release-acceptance', %s, 'succeeded', NULL,
                %s, %s, %s::jsonb)
        """,
        (
            f"audit_acceptance_{uuid4().hex}",
            action,
            subject_type,
            subject_id,
            json.dumps(details, sort_keys=True, separators=(",", ":")),
        ),
    )


def inspect_publication(database_url: str, publication_id: str) -> None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT publication.status, publication.result_release_id,
                   publication.result_manifest_sha256,
                   publication.diagnostic_json,
                   outbox.status,
                   release.manifest_json,
                   pointer.release_id,
                   trigger.status
            FROM thesistrace_product.dataset_publications AS publication
            LEFT JOIN thesistrace_product.platform_execution_outbox AS outbox
              ON outbox.resource_id = publication.id
            LEFT JOIN thesistrace_product.dataset_releases AS release
              ON release.id = publication.result_release_id
            LEFT JOIN thesistrace_product.dataset_release_pointer AS pointer
              ON pointer.singleton = 1
            LEFT JOIN thesistrace_product.tracking_release_triggers AS trigger
              ON trigger.release_id = publication.result_release_id
            WHERE publication.id = %s
            """,
            (publication_id,),
        ).fetchone()
        attempts = connection.execute(
            """
            SELECT id, ordinal, status, diagnostic_json, started_at, finished_at
            FROM thesistrace_product.dataset_publication_attempts
            WHERE publication_id = %s
            ORDER BY ordinal
            """,
            (publication_id,),
        ).fetchall()
        objects = (
            connection.execute(
                """
                SELECT reference.object_key, stored.sha256,
                       stored.compressed_bytes, stored.object_kind
                FROM thesistrace_control.storage_references AS reference
                JOIN thesistrace_control.stored_objects AS stored
                  ON stored.object_key = reference.object_key
                WHERE reference.owner_scope = 'platform'
                  AND reference.resource_kind = 'dataset_release'
                  AND reference.resource_id = %s
                ORDER BY reference.object_key
                """,
                (row[1],),
            ).fetchall()
            if row is not None and row[1] is not None
            else []
        )
    if row is None:
        raise SystemExit("Dataset Publication not found")
    print(
        json.dumps(
            {
                "status": row[0],
                "result_release_id": row[1],
                "result_manifest_sha256": row[2],
                "diagnostic": row[3],
                "outbox_status": row[4],
                "release_manifest_json": row[5],
                "latest_release_id": row[6],
                "tracking_trigger_status": row[7],
                "attempt_count": len(attempts),
                "attempts": [
                    {
                        "id": attempt[0],
                        "ordinal": int(attempt[1]),
                        "status": attempt[2],
                        "diagnostic": attempt[3],
                        "started_at": attempt[4],
                        "finished_at": attempt[5],
                    }
                    for attempt in attempts
                ],
                "storage_objects": [
                    {
                        "object_key": item[0],
                        "sha256": item[1],
                        "compressed_bytes": int(item[2]),
                        "object_kind": item[3],
                    }
                    for item in objects
                ],
            },
            sort_keys=True,
        )
    )


def inspect_storage(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT
                (SELECT count(*)
                   FROM thesistrace_control.stored_objects),
                (SELECT count(DISTINCT object_key)
                   FROM thesistrace_control.storage_references),
                (SELECT count(*)
                   FROM thesistrace_control.stored_objects AS stored
                  WHERE NOT EXISTS (
                      SELECT 1
                      FROM thesistrace_control.storage_references AS reference
                      WHERE reference.object_key = stored.object_key
                  ))
            """
        ).fetchone()
    if row is None:
        raise SystemExit("Storage index is unavailable")
    print(
        json.dumps(
            {
                "stored_object_count": int(row[0]),
                "referenced_object_count": int(row[1]),
                "unreferenced_object_count": int(row[2]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

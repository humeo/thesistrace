#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_NAME = "thesistrace_local_acceptance_test"

DatabaseLifecycle = Callable[[str, str, str], None]
TestRunner = Callable[[tuple[str, ...], dict[str, str]], bytes]


class LocalPostgresAcceptanceError(RuntimeError):
    pass


def postgres_test_targets() -> tuple[str, ...]:
    return (
        "tests/hosted/test_workspace_isolation.py::"
        "test_two_users_have_private_research_and_the_same_bounded_dataset_view",
        "tests/hosted/test_workspace_isolation.py::"
        "test_production_roles_and_rls_cover_every_private_table",
        "tests/hosted/test_workspace_isolation.py::"
        "test_api_identity_directory_has_only_verification_column_access",
        "tests/hosted/test_workspace_isolation.py::"
        "test_api_role_has_only_the_control_table_access_needed_for_provisioning",
        "tests/hosted/test_registration_provisioning.py::"
        "test_postgres_invitation_issue_is_fenced_by_latest_launch_measurement",
    )


def connection_info(
    *,
    state_dir: Path,
    port: int,
    database_name: str,
) -> str:
    try:
        password = (state_dir / "secrets" / "postgres_password").read_text().strip()
    except OSError as error:
        raise LocalPostgresAcceptanceError(
            "local PostgreSQL administrator credential is unavailable"
        ) from error
    if not password:
        raise LocalPostgresAcceptanceError(
            "local PostgreSQL administrator credential is empty"
        )
    return psycopg.conninfo.make_conninfo(
        host="127.0.0.1",
        port=port,
        user="postgres",
        password=password,
        dbname=database_name,
        connect_timeout=10,
    )


def manage_database(operation: str, admin_info: str, database_name: str) -> None:
    if operation not in {"recreate", "drop"}:
        raise LocalPostgresAcceptanceError(
            f"unsupported local PostgreSQL lifecycle operation: {operation}"
        )
    with psycopg.connect(admin_info, autocommit=True) as connection:
        connection.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (database_name,),
        )
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(
                sql.Identifier(database_name)
            )
        )
        if operation == "recreate":
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name)
                )
            )
    if operation == "recreate":
        database_info = psycopg.conninfo.make_conninfo(
            admin_info,
            dbname=database_name,
        )
        with psycopg.connect(database_info) as connection:
            connection.execute("CREATE SCHEMA auth")
            connection.execute(
                """
                CREATE TABLE auth.users (
                    id uuid PRIMARY KEY,
                    email text NOT NULL,
                    email_verified boolean NOT NULL DEFAULT false,
                    encrypted_password text,
                    raw_user_metadata jsonb
                )
                """
            )


def run_tests(command: tuple[str, ...], environment: dict[str, str]) -> bytes:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise LocalPostgresAcceptanceError(
            "real PostgreSQL RLS acceptance failed:\n"
            + output[-8000:].decode("utf-8", errors="replace")
        )
    return output


def run_postgres_acceptance(
    *,
    state_dir: Path,
    port: int,
    database_lifecycle: DatabaseLifecycle = manage_database,
    test_runner: TestRunner = run_tests,
) -> dict[str, object]:
    admin_info = connection_info(
        state_dir=state_dir,
        port=port,
        database_name="postgres",
    )
    test_info = connection_info(
        state_dir=state_dir,
        port=port,
        database_name=TEST_DATABASE_NAME,
    )
    command = ("uv", "run", "pytest", "-q", *postgres_test_targets())
    database_lifecycle("recreate", admin_info, TEST_DATABASE_NAME)
    try:
        output = test_runner(
            command,
            {**os.environ, "THESISTRACE_TEST_DATABASE_URL": test_info},
        )
    finally:
        database_lifecycle("drop", admin_info, TEST_DATABASE_NAME)
    return {
        "status": "passed",
        "database": "isolated-runtime-postgresql",
        "loopback_port": port,
        "tests": list(postgres_test_targets()),
        "output_sha256": hashlib.sha256(output).hexdigest(),
    }


def main() -> None:
    if os.environ.get("THESISTRACE_LOCAL_ACCEPTANCE") != "1":
        raise LocalPostgresAcceptanceError(
            "local PostgreSQL acceptance requires THESISTRACE_LOCAL_ACCEPTANCE=1"
        )
    state_dir = Path(
        os.environ.get("THESISTRACE_HOST_STATE_DIR", ROOT / ".hosted")
    ).resolve()
    try:
        port = int(os.environ.get("THESISTRACE_LOCAL_POSTGRES_PORT", "25432"))
    except ValueError as error:
        raise LocalPostgresAcceptanceError(
            "THESISTRACE_LOCAL_POSTGRES_PORT must be an integer"
        ) from error
    print(
        json.dumps(
            run_postgres_acceptance(state_dir=state_dir, port=port),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except LocalPostgresAcceptanceError as error:
        raise SystemExit(str(error)) from error

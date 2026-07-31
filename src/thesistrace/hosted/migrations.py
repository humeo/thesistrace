import hashlib
import os
from pathlib import Path

import psycopg
from psycopg import sql


class MigrationError(RuntimeError):
    pass


SERVICE_ROLES = {
    "api": "thesistrace_api",
    "relay": "thesistrace_relay",
    "data": "thesistrace_data",
    "compute": "thesistrace_compute",
}


def apply_migrations(database_url: str, directory: Path) -> list[str]:
    migration_files = sorted(directory.glob("*.sql"))
    if not migration_files:
        raise MigrationError(f"no SQL migrations found in {directory}")

    applied: list[str] = []
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("thesistrace-hosted-migrations",),
            )
            connection.execute("CREATE SCHEMA IF NOT EXISTS thesistrace_control")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS thesistrace_control.schema_migrations (
                    name text PRIMARY KEY,
                    sha256 text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            for migration_file in migration_files:
                payload = migration_file.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                row = connection.execute(
                    """
                    SELECT sha256
                    FROM thesistrace_control.schema_migrations
                    WHERE name = %s
                    """,
                    (migration_file.name,),
                ).fetchone()
                if row is not None:
                    if row[0] != digest:
                        raise MigrationError(
                            f"applied migration changed: {migration_file.name}"
                        )
                    continue
                connection.execute(payload.decode("utf-8"))
                connection.execute(
                    """
                    INSERT INTO thesistrace_control.schema_migrations (name, sha256)
                    VALUES (%s, %s)
                    """,
                    (migration_file.name, digest),
                )
                applied.append(migration_file.name)
    return applied


def provision_service_role_credentials(
    database_url: str,
    credentials: dict[str, str],
) -> None:
    if set(credentials) != set(SERVICE_ROLES):
        raise MigrationError(
            "api, relay, data, and compute database passwords are required"
        )
    if any(not password for password in credentials.values()):
        raise MigrationError("service database passwords cannot be empty")
    if len(set(credentials.values())) != len(credentials):
        raise MigrationError(
            "service database passwords must be distinct"
        )
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            for service, role in SERVICE_ROLES.items():
                connection.execute(
                    sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role),
                        sql.Literal(credentials[service]),
                    )
                )


def main() -> None:
    if os.environ.get("THESISTRACE_INJECT_MIGRATION_FAILURE") == "1":
        raise MigrationError("injected migration failure")
    database_url = os.environ.get("THESISTRACE_DATABASE_URL")
    if not database_url:
        raise MigrationError("THESISTRACE_DATABASE_URL is required")
    directory = Path(
        os.environ.get(
            "THESISTRACE_MIGRATIONS_DIR",
            "/app/deploy/hosted/migrations",
        )
    )
    applied = apply_migrations(database_url, directory)
    credentials = {
        service: os.environ.get(
            f"THESISTRACE_{service.upper()}_DATABASE_PASSWORD",
            "",
        )
        for service in SERVICE_ROLES
    }
    provision_service_role_credentials(database_url, credentials)
    print(f"ThesisTrace migrations complete; applied={len(applied)}")


if __name__ == "__main__":
    main()

import hashlib
import os
from pathlib import Path

import psycopg


class MigrationError(RuntimeError):
    pass


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
    print(f"ThesisTrace migrations complete; applied={len(applied)}")


if __name__ == "__main__":
    main()

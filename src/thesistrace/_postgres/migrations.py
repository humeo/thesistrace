from __future__ import annotations

import hashlib
from dataclasses import dataclass

from psycopg import sql

from thesistrace._postgres.database import PostgresDatabase


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    name: str
    statement: str


@dataclass(frozen=True)
class MigrationPlan:
    schema: str
    ledger_table: str
    lock_name: str
    migrations: tuple[Migration, ...]


def apply_migrations(database: PostgresDatabase, plan: MigrationPlan) -> tuple[str, ...]:
    applied: list[str] = []
    with database.transaction() as transaction:
        transaction.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (plan.lock_name,))
        transaction.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(plan.schema))
        )
        transaction.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.{} (
                    name text PRIMARY KEY,
                    sha256 text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            ).format(sql.Identifier(plan.schema), sql.Identifier(plan.ledger_table))
        )
        ledger = sql.Identifier(plan.schema, plan.ledger_table)
        for migration in plan.migrations:
            digest = hashlib.sha256(migration.statement.encode()).hexdigest()
            row = transaction.execute(
                sql.SQL("SELECT sha256 FROM {} WHERE name = %s").format(ledger),
                (migration.name,),
            ).fetchone()
            if row is not None:
                if row["sha256"] != digest:
                    raise MigrationError(f"applied migration changed: {migration.name}")
                continue
            transaction.execute(migration.statement)
            transaction.execute(
                sql.SQL("INSERT INTO {} (name, sha256) VALUES (%s, %s)").format(ledger),
                (migration.name, digest),
            )
            applied.append(migration.name)
    return tuple(applied)


def verify_migrations(database: PostgresDatabase, plan: MigrationPlan) -> None:
    with database.transaction() as transaction:
        ledger_name = f"{plan.schema}.{plan.ledger_table}"
        ledger_row = transaction.execute(
            "SELECT to_regclass(%s) AS ledger",
            (ledger_name,),
        ).fetchone()
        if ledger_row is None or ledger_row["ledger"] is None:
            raise MigrationError(f"missing migration ledger: {ledger_name}")

        rows = transaction.execute(
            sql.SQL("SELECT name, sha256 FROM {}.{}").format(
                sql.Identifier(plan.schema),
                sql.Identifier(plan.ledger_table),
            )
        ).fetchall()
        applied = {row["name"]: row["sha256"] for row in rows}
        missing: list[str] = []
        for migration in plan.migrations:
            digest = hashlib.sha256(migration.statement.encode()).hexdigest()
            applied_digest = applied.get(migration.name)
            if applied_digest is None:
                missing.append(migration.name)
            elif applied_digest != digest:
                raise MigrationError(f"applied migration changed: {migration.name}")
        if missing:
            raise MigrationError(
                f"pending migrations for {plan.schema}: {', '.join(missing)}"
            )

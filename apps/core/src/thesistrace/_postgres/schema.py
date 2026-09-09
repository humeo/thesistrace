from __future__ import annotations

import hashlib
from dataclasses import dataclass

from psycopg import sql

from thesistrace._postgres.database import PostgresDatabase, PostgresTransaction

_METADATA_SCHEMA = "thesistrace_meta"
_METADATA_TABLE = "schema_contract"


class SchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class SchemaDefinition:
    name: str
    statement: str


def initialize_schemas(
    database: PostgresDatabase,
    definitions: tuple[SchemaDefinition, ...],
) -> bool:
    fingerprint = _fingerprint(definitions)
    schemas = tuple(definition.name for definition in definitions)
    with database.transaction() as transaction:
        transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))"
        )
        present = _present_schemas(transaction, (*schemas, _METADATA_SCHEMA))
        if not present:
            for definition in definitions:
                transaction.execute(definition.statement)
            transaction.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(_METADATA_SCHEMA))
            )
            transaction.execute(
                sql.SQL(
                    "CREATE TABLE {}.{} (singleton boolean PRIMARY KEY CHECK (singleton), "
                    "fingerprint text NOT NULL)"
                ).format(sql.Identifier(_METADATA_SCHEMA), sql.Identifier(_METADATA_TABLE))
            )
            transaction.execute(
                sql.SQL("INSERT INTO {}.{} (singleton, fingerprint) VALUES (true, %s)").format(
                    sql.Identifier(_METADATA_SCHEMA), sql.Identifier(_METADATA_TABLE)
                ),
                (fingerprint,),
            )
            return True
        _verify(transaction, schemas, fingerprint, present)
        return False


def verify_schemas(
    database: PostgresDatabase,
    definitions: tuple[SchemaDefinition, ...],
) -> None:
    schemas = tuple(definition.name for definition in definitions)
    with database.transaction() as transaction:
        _verify(
            transaction,
            schemas,
            _fingerprint(definitions),
            _present_schemas(transaction, (*schemas, _METADATA_SCHEMA)),
        )


def _verify(
    transaction: PostgresTransaction,
    schemas: tuple[str, ...],
    fingerprint: str,
    present: frozenset[str],
) -> None:
    expected = {*schemas, _METADATA_SCHEMA}
    if present != expected:
        raise SchemaError(
            "unsupported existing Core schema; see docs/database-migrations.md for an explicit "
            "data-preserving upgrade"
        )
    row = transaction.execute(
        sql.SQL("SELECT fingerprint FROM {}.{} WHERE singleton = true").format(
            sql.Identifier(_METADATA_SCHEMA), sql.Identifier(_METADATA_TABLE)
        )
    ).fetchone()
    if row is None or row["fingerprint"] != fingerprint:
        raise SchemaError(
            "Core schema does not match this checkout; see docs/database-migrations.md for an "
            "explicit data-preserving upgrade"
        )


def _present_schemas(
    transaction: PostgresTransaction,
    schemas: tuple[str, ...],
) -> frozenset[str]:
    rows = transaction.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
        (list(schemas),),
    ).fetchall()
    return frozenset(row["nspname"] for row in rows)


def _fingerprint(definitions: tuple[SchemaDefinition, ...]) -> str:
    contract = "\n".join(
        f"-- {definition.name}\n{definition.statement.strip()}" for definition in definitions
    )
    return hashlib.sha256(contract.encode()).hexdigest()


__all__ = (
    "SchemaDefinition",
    "SchemaError",
    "initialize_schemas",
    "verify_schemas",
)

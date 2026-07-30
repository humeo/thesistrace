from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql

from thesistrace.storage import MetadataStore
from thesistrace.tenancy import service_workspace, verified_subject

HOSTED_DATABASE_ROLES = {
    "api": "thesistrace_api",
    "compute": "thesistrace_compute",
    "data": "thesistrace_data",
}


class HybridRow(dict[str, object]):
    def __getitem__(self, key: str | int) -> object:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def hybrid_row(cursor: psycopg.Cursor[Any]) -> Any:
    columns = [column.name for column in cursor.description or ()]

    def make_row(values: Sequence[object]) -> HybridRow:
        return HybridRow(zip(columns, values, strict=True))

    return make_row


class PostgresConnectionAdapter:
    def __init__(self, connection: psycopg.Connection[HybridRow]) -> None:
        self.connection = connection

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] | None = None,
    ) -> psycopg.Cursor[HybridRow]:
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            return self.connection.execute("SELECT 1")
        return self.connection.execute(
            statement.replace("?", "%s"),
            tuple(parameters or ()),
        )

    def rollback(self) -> None:
        self.connection.rollback()


class PostgresControlMetadataStore(MetadataStore):
    def __init__(self, database_url: str, *, database_role: str) -> None:
        if database_role not in HOSTED_DATABASE_ROLES:
            raise ValueError(f"unsupported hosted database role: {database_role}")
        self.database_url = database_url
        self.database_role = database_role

    def initialize(self) -> None:
        return None

    @contextmanager
    def connect(self) -> Iterator[PostgresConnectionAdapter]:
        with psycopg.connect(self.database_url, row_factory=hybrid_row) as connection:
            connection.execute("BEGIN")
            role = HOSTED_DATABASE_ROLES[self.database_role]
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            connection.execute(
                "SET LOCAL search_path = thesistrace_product, public"
            )
            if self.database_role == "api":
                subject = verified_subject()
                if subject is not None:
                    connection.execute(
                        "SELECT thesistrace_control.set_api_identity(%s)",
                        (subject,),
                    )
            elif self.database_role == "compute":
                workspace_id = service_workspace()
                if workspace_id is not None:
                    connection.execute(
                        "SELECT thesistrace_control.set_service_workspace(%s)",
                        (workspace_id,),
                    )
            yield PostgresConnectionAdapter(connection)


__all__ = ["PostgresControlMetadataStore"]

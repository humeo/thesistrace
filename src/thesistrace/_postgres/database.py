from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

type PostgresTransaction = Connection[dict[str, Any]]


class PostgresDatabase:
    def __init__(self, database_url: str) -> None:
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    def open(self) -> None:
        self._pool.open(wait=True, timeout=10)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def session_advisory_lock(self, name: str) -> Iterator[None]:
        with self._pool.connection() as connection:
            connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (name,))
            connection.commit()
            try:
                yield
            finally:
                connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
                connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[PostgresTransaction]:
        with self._pool.connection() as connection:
            with connection.transaction():
                yield connection

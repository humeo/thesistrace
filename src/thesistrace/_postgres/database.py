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
        with self.session_advisory_locks(name):
            yield

    @contextmanager
    def session_advisory_lock_shared(self, name: str) -> Iterator[None]:
        if not name:
            raise ValueError("Advisory lock name must be non-empty")
        with self._pool.connection() as connection:
            connection.execute("SELECT pg_advisory_lock_shared(hashtext(%s))", (name,))
            connection.commit()
            try:
                yield
            finally:
                connection.execute("SELECT pg_advisory_unlock_shared(hashtext(%s))", (name,))
                connection.commit()

    @contextmanager
    def try_session_advisory_lock(self, name: str) -> Iterator[bool]:
        if not name:
            raise ValueError("Advisory lock name must be non-empty")
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired",
                (name,),
            ).fetchone()
            connection.commit()
            acquired = bool(row and row["acquired"])
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
                    connection.commit()

    @contextmanager
    def session_advisory_locks(self, *names: str) -> Iterator[None]:
        if not names or any(not name for name in names):
            raise ValueError("Advisory lock names must be non-empty")
        with self._pool.connection() as connection:
            for name in names:
                connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (name,))
            connection.commit()
            try:
                yield
            finally:
                for name in reversed(names):
                    connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
                connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[PostgresTransaction]:
        with self._pool.connection() as connection:
            with connection.transaction():
                yield connection

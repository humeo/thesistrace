from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

type PostgresTransaction = Connection[dict[str, Any]]


class PostgresDatabase:
    def __init__(
        self,
        database_url: str,
        *,
        pool_max_size: int = 4,
        pool_timeout_seconds: float = 30,
    ) -> None:
        if pool_max_size <= 0 or pool_timeout_seconds <= 0:
            raise ValueError("PostgreSQL pool capacity and timeout must be positive")
        self._pool_timeout_seconds = pool_timeout_seconds
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=pool_max_size,
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
        with self._session_advisory_locks((name,), shared=True):
            yield

    @contextmanager
    def try_session_advisory_lock(self, name: str) -> Iterator[bool]:
        if not name:
            raise ValueError("Advisory lock name must be non-empty")
        with self._pool.connection() as connection:
            try:
                row = connection.execute(
                    "SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired",
                    (name,),
                ).fetchone()
                acquired = bool(row and row["acquired"])
                connection.commit()
            except BaseException:
                connection.close()
                raise
            try:
                yield acquired
            finally:
                if acquired:
                    self._release_session_locks(connection, (name,), shared=False)

    @contextmanager
    def session_advisory_locks(self, *names: str) -> Iterator[None]:
        if not names or any(not name for name in names):
            raise ValueError("Advisory lock names must be non-empty")
        with self._session_advisory_locks(names, shared=False):
            yield

    @contextmanager
    def _session_advisory_locks(
        self,
        names: tuple[str, ...],
        *,
        shared: bool,
    ) -> Iterator[None]:
        lock_function = "pg_advisory_lock_shared" if shared else "pg_advisory_lock"
        with self._pool.connection() as connection:
            try:
                for name in names:
                    connection.execute(f"SELECT {lock_function}(hashtext(%s))", (name,))
                    # The execute may have acquired a session lock even if the
                    # following commit fails. Closing is the only unambiguous
                    # cleanup for a partially acquired sequence.
                    connection.commit()
            except BaseException:
                connection.close()
                raise
            try:
                yield
            finally:
                self._release_session_locks(connection, names, shared=shared)

    @staticmethod
    def _release_session_locks(
        connection: PostgresTransaction,
        names: tuple[str, ...],
        *,
        shared: bool,
    ) -> None:
        unlock_function = "pg_advisory_unlock_shared" if shared else "pg_advisory_unlock"
        try:
            for name in reversed(names):
                connection.execute(f"SELECT {unlock_function}(hashtext(%s))", (name,))
                connection.commit()
        except BaseException:
            # A closed connection makes PostgreSQL release every session lock,
            # including locks not yet visited after an unlock failure. The pool
            # replaces rather than reuses the closed connection.
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[PostgresTransaction]:
        with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
            with connection.transaction():
                yield connection

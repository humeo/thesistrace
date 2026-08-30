from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Thread

from thesistrace._postgres import PostgresDatabase

_WORKER_LEASE_SECONDS = 900
_WORKER_HEARTBEAT_SECONDS = 30.0


@dataclass(frozen=True)
class DataRefreshWorkerOwner:
    _database: PostgresDatabase
    _owner_token: str
    _heartbeat_failed: Event

    def assert_owned(self) -> None:
        if self._heartbeat_failed.is_set():
            raise RuntimeError("Data Operator Worker lease was lost")
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM data.refresh_worker_leases
                    WHERE singleton = 1
                      AND owner_token = %s
                      AND lease_expires_at > clock_timestamp()
                ) AS owned
                """,
                (self._owner_token,),
            ).fetchone()
        if row is None or row["owned"] is not True:
            self._heartbeat_failed.set()
            raise RuntimeError("Data Operator Worker lease was lost")


class DataRefreshWorkerLease:
    """Own the singleton Data Operator Worker availability lease."""

    def __init__(
        self,
        database: PostgresDatabase,
        *,
        lease_seconds: int = _WORKER_LEASE_SECONDS,
        heartbeat_seconds: float = _WORKER_HEARTBEAT_SECONDS,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0:
            raise ValueError("Worker lease and heartbeat intervals must be positive")
        if heartbeat_seconds >= lease_seconds:
            raise ValueError("Worker heartbeat must be shorter than its lease")
        self._database = database
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds

    @contextmanager
    def maintain(self) -> Iterator[DataRefreshWorkerOwner]:
        owner_token = secrets.token_hex(16)
        self._acquire(owner_token)
        stopped = Event()
        failed = Event()
        owner = DataRefreshWorkerOwner(self._database, owner_token, failed)
        heartbeat = Thread(
            target=self._maintain,
            args=(owner_token, stopped, failed),
            name="data-operator-worker-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        try:
            yield owner
        finally:
            stopped.set()
            heartbeat.join(timeout=5)
            if heartbeat.is_alive():
                failed.set()
            self._release(owner_token)

    def _acquire(self, owner_token: str) -> None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                INSERT INTO data.refresh_worker_leases (
                    singleton, owner_token, lease_expires_at,
                    last_heartbeat_at, started_at
                )
                SELECT 1, %s,
                       observed_at + make_interval(secs => %s),
                       observed_at, observed_at
                FROM (SELECT clock_timestamp() AS observed_at) AS clock
                ON CONFLICT (singleton) DO UPDATE
                SET owner_token = EXCLUDED.owner_token,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    started_at = EXCLUDED.started_at
                WHERE data.refresh_worker_leases.owner_token IS NULL
                   OR data.refresh_worker_leases.lease_expires_at <= clock_timestamp()
                RETURNING singleton
                """,
                (owner_token, self._lease_seconds),
            ).fetchone()
        if row is None:
            raise RuntimeError("A Data Operator Worker lease is already active")

    def _maintain(self, owner_token: str, stopped: Event, failed: Event) -> None:
        while not stopped.wait(self._heartbeat_seconds):
            try:
                with self._database.transaction() as transaction:
                    renewed = transaction.execute(
                        """
                        UPDATE data.refresh_worker_leases
                        SET lease_expires_at = (
                                clock_timestamp() + make_interval(secs => %s)
                            ),
                            last_heartbeat_at = clock_timestamp()
                        WHERE singleton = 1
                          AND owner_token = %s
                          AND lease_expires_at > clock_timestamp()
                        """,
                        (self._lease_seconds, owner_token),
                    )
                if renewed.rowcount != 1:
                    raise RuntimeError("Data Operator Worker lease was lost")
            except Exception:
                failed.set()
                return

    def _release(self, owner_token: str) -> None:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.refresh_worker_leases
                SET owner_token = NULL,
                    lease_expires_at = NULL
                WHERE singleton = 1 AND owner_token = %s
                """,
                (owner_token,),
            )

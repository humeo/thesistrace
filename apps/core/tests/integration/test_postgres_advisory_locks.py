from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import LiteralString

from psycopg.errors import QueryCanceled

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings


def test_cancelled_multi_lock_acquisition_releases_earlier_session_lock(
    core_settings: CoreSettings,
) -> None:
    database = _open_database(core_settings)
    blocker = _open_database(core_settings)
    observer = _open_database(core_settings)
    verifier = _open_database(core_settings)
    blocker_ready = threading.Event()
    release_blocker = threading.Event()
    blocker_errors: list[BaseException] = []
    acquisition_errors: list[BaseException] = []
    first = "test-cancelled-multi-lock-first"
    second = "test-cancelled-multi-lock-second"

    def hold_second() -> None:
        try:
            with blocker.session_advisory_lock(second):
                blocker_ready.set()
                if not release_blocker.wait(timeout=10):
                    raise TimeoutError("test did not release the blocking advisory lock")
        except BaseException as error:
            blocker_errors.append(error)

    def acquire_both() -> None:
        try:
            with database.session_advisory_locks(first, second):
                raise AssertionError("cancelled acquisition unexpectedly entered its body")
        except BaseException as error:
            acquisition_errors.append(error)

    blocker_thread = threading.Thread(target=hold_second)
    acquisition_thread = threading.Thread(target=acquire_both)
    try:
        blocker_thread.start()
        assert blocker_ready.wait(timeout=10)
        acquisition_thread.start()
        waiting_pid = _await_advisory_waiter(observer)
        with observer.transaction() as transaction:
            assert transaction.execute(
                "SELECT pg_cancel_backend(%s) AS cancelled",
                (waiting_pid,),
            ).fetchone() == {"cancelled": True}
        acquisition_thread.join(timeout=10)
        assert not acquisition_thread.is_alive()
        assert len(acquisition_errors) == 1
        assert isinstance(acquisition_errors[0], QueryCanceled)

        with verifier.try_session_advisory_lock(first) as acquired:
            assert acquired is True
    finally:
        release_blocker.set()
        blocker_thread.join(timeout=10)
        acquisition_thread.join(timeout=10)
        database.close()
        blocker.close()
        observer.close()
        verifier.close()
    assert blocker_errors == []


def test_backend_loss_while_locked_discards_session_and_releases_all_locks(
    core_settings: CoreSettings,
) -> None:
    database = _open_database(core_settings)
    observer = _open_database(core_settings)
    verifier = _open_database(core_settings)
    body_entered = threading.Event()
    leave_body = threading.Event()
    worker_errors: list[BaseException] = []
    first = "test-lost-backend-first"
    second = "test-lost-backend-second"

    with observer.transaction() as transaction:
        existing_lock_holders = {
            _pid(row)
            for row in transaction.execute(
                "SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory'"
            ).fetchall()
        }

    def hold_both() -> None:
        try:
            with database.session_advisory_locks(first, second):
                body_entered.set()
                if not leave_body.wait(timeout=10):
                    raise TimeoutError("test did not release the advisory-lock body")
        except BaseException as error:
            worker_errors.append(error)

    worker = threading.Thread(target=hold_both)
    try:
        worker.start()
        assert body_entered.wait(timeout=10)
        holder_pid = _await_new_advisory_holder(observer, existing_lock_holders)
        with observer.transaction() as transaction:
            assert transaction.execute(
                "SELECT pg_terminate_backend(%s) AS terminated",
                (holder_pid,),
            ).fetchone() == {"terminated": True}
        leave_body.set()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert worker_errors == []

        with verifier.try_session_advisory_lock(first) as first_acquired:
            assert first_acquired is True
        with verifier.try_session_advisory_lock(second) as second_acquired:
            assert second_acquired is True
        with database.transaction() as transaction:
            assert transaction.execute("SELECT 1 AS value").fetchone() == {"value": 1}
    finally:
        leave_body.set()
        worker.join(timeout=10)
        database.close()
        observer.close()
        verifier.close()


def _open_database(settings: CoreSettings) -> PostgresDatabase:
    database = PostgresDatabase(settings.database_url)
    database.open()
    return database


def _await_advisory_waiter(database: PostgresDatabase) -> int:
    return _poll_pid(
        database,
        """
        SELECT pid
        FROM pg_stat_activity
        WHERE wait_event_type = 'Lock' AND wait_event = 'advisory'
        ORDER BY query_start
        LIMIT 1
        """,
        lambda rows: _pid(rows[0]) if rows else None,
    )


def _await_new_advisory_holder(
    database: PostgresDatabase,
    existing_holders: set[int],
) -> int:
    return _poll_pid(
        database,
        "SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory' AND granted",
        lambda rows: next(
            (_pid(row) for row in rows if _pid(row) not in existing_holders),
            None,
        ),
    )


def _poll_pid(
    database: PostgresDatabase,
    query: LiteralString,
    select: Callable[[Sequence[Mapping[str, object]]], int | None],
) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with database.transaction() as transaction:
            rows = transaction.execute(query).fetchall()
        selected = select(rows)
        if selected is not None:
            return selected
        time.sleep(0.01)
    raise AssertionError("timed out waiting for PostgreSQL advisory-lock state")


def _pid(row: Mapping[str, object]) -> int:
    value = row["pid"]
    assert isinstance(value, int)
    return value

from __future__ import annotations

import time
from datetime import datetime, timedelta

from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from psycopg.errors import LockNotAvailable

from thesistrace._postgres import PostgresDatabase
from thesistrace.publication.service import (
    Publication,
    PublicationPreparationError,
    PublicationUnavailableError,
    PublicationVerificationError,
    _digest_from_object_key,
    lock_publication_mutation,
)

MAINTENANCE_LOCK = "thesistrace-publication-maintenance"
PREFIX = "publication/v1/sha256/"
PAGE_SIZE = 1000
DELETE_LIMIT = 10
STEP_SECONDS = 10
SWEEP_REST_SECONDS = 3600


class PublicationMaintenance:
    """One durable, bounded maintenance step, independent of product Worker pools."""

    def __init__(self, database: PostgresDatabase, s3: BaseClient, *, bucket: str) -> None:
        self._database = database
        self._s3 = s3
        self._bucket = bucket
        self._publication = Publication(database, s3, bucket=bucket)

    def run_once(self) -> dict[str, object]:
        started = time.monotonic()
        with self._database.try_session_advisory_connection(MAINTENANCE_LOCK) as connection:
            if connection is None:
                return {"status": "busy", "job": None}
            with connection.transaction():
                state = connection.execute(
                    "SELECT *, clock_timestamp() AS current_time "
                    "FROM publication.maintenance_state WHERE next_due_at <= clock_timestamp() "
                    "ORDER BY next_due_at, job LIMIT 1"
                ).fetchone()
                if state is not None:
                    # Reserve before I/O: a crashed owner cannot bypass global rate limits.
                    connection.execute(
                        "UPDATE publication.maintenance_state "
                        "SET next_due_at = clock_timestamp() + %s WHERE job = %s",
                        (
                            timedelta(seconds=60 if state["job"] == "orphan_scan" else 5),
                            state["job"],
                        ),
                    )
            if state is None:
                return {"status": "idle", "job": None}
            try:
                if state["job"] == "orphan_scan":
                    result = self._scan(connection, state, started + STEP_SECONDS)
                    delay = SWEEP_REST_SECONDS if result["sweep_completed"] else 60
                else:
                    delay = 5
                    result = self._queued(connection, started + STEP_SECONDS)
            except (
                BotoCoreError,
                ClientError,
                PublicationVerificationError,
                PublicationPreparationError,
                LockNotAvailable,
            ) as error:
                code = _failure_code(error)
                delay = min(900, 60 * 2 ** min(state["failure_count"], 4))
                with connection.transaction():
                    connection.execute(
                        "UPDATE publication.maintenance_state "
                        "SET next_due_at = clock_timestamp() + %s, "
                        "failure_count = failure_count + 1, last_error = %s, last_key = %s "
                        "WHERE job = %s",
                        (timedelta(seconds=delay), code, state["last_key"], state["job"]),
                    )
                return {
                    "status": "failed",
                    "job": state["job"],
                    "failure_code": code,
                    "retry_seconds": delay,
                    "elapsed_seconds": time.monotonic() - started,
                }
            with connection.transaction():
                connection.execute(
                    "UPDATE publication.maintenance_state "
                    "SET next_due_at = clock_timestamp() + %s, "
                    "failure_count = 0, last_error = NULL "
                    "WHERE job = %s",
                    (timedelta(seconds=delay), state["job"]),
                )
            with connection.transaction():
                ages = connection.execute(
                    "SELECT extract(epoch FROM clock_timestamp() - last_sweep_completed_at) "
                    "AS full_sweep_age_seconds, "
                    "(SELECT extract(epoch FROM clock_timestamp() - min(created_at)) "
                    "FROM publication.object_deletions) AS oldest_deletion_age_seconds "
                    "FROM publication.maintenance_state WHERE job = 'orphan_scan'"
                ).fetchone()
            return {
                **{key: max(0, int(value)) for key, value in ages.items() if value is not None},
                "status": "completed",
                "job": state["job"],
                "elapsed_seconds": time.monotonic() - started,
                **result,
            }

    def _queued(self, connection, deadline):
        processed = deleted = 0
        while processed < DELETE_LIMIT and time.monotonic() < deadline:
            with connection.transaction():
                connection.execute("SET LOCAL lock_timeout = '1s'")
                outcome = self._publication.collect_pending_deletion_in_transaction(
                    connection, deadline=deadline
                )
            if outcome is None:
                break
            processed += 1
            deleted += int(outcome == "deleted")
        return {"processed": processed, "deleted": deleted, "skipped": processed - deleted}

    def _scan(self, connection, state, deadline):
        if state["cutoff"] is None:
            state["cutoff"] = state["current_time"] - timedelta(hours=1)
            with connection.transaction():
                connection.execute(
                    "UPDATE publication.maintenance_state SET cutoff = %s, sweep_started_at = %s "
                    "WHERE job = 'orphan_scan'",
                    (state["cutoff"], state["current_time"]),
                )
        arguments = dict(Bucket=self._bucket, Prefix=PREFIX, MaxKeys=PAGE_SIZE)
        if state["last_key"]:
            arguments["StartAfter"] = state["last_key"]
        if time.monotonic() >= deadline:
            return {
                "listed": 0,
                "processed": 0,
                "deleted": 0,
                "skipped": 0,
                "sweep_completed": False,
            }
        page = self._s3.list_objects_v2(**arguments)
        items = page.get("Contents", [])
        if (
            not isinstance(items, list)
            or len(items) > PAGE_SIZE
            or not isinstance(page.get("IsTruncated"), bool)
            or (page["IsTruncated"] and not items)
        ):
            raise PublicationVerificationError("Invalid maintenance page")
        previous = state["last_key"]
        for item in items:
            if not isinstance(item, dict):
                raise PublicationVerificationError("Invalid maintenance page item")
            key = item.get("Key")
            if (
                not isinstance(key, str)
                or _digest_from_object_key(key) is None
                or key <= previous
                or not _aware(item.get("LastModified"))
            ):
                raise PublicationVerificationError("Invalid maintenance page ordering or metadata")
            previous = key
        with connection.transaction():
            recorded = {
                row["sha256"]
                for row in connection.execute(
                    "SELECT sha256 FROM publication.objects WHERE sha256 = ANY(%s)",
                    ([_digest_from_object_key(item["Key"]) for item in items],),
                ).fetchall()
            }
        processed = deleted = 0
        for item in items:
            if time.monotonic() >= deadline or deleted >= DELETE_LIMIT:
                break
            key = item["Key"]
            digest = _digest_from_object_key(key)
            if digest not in recorded and item["LastModified"] <= state["cutoff"]:
                removed = self._remove_orphan(connection, key, digest, state["cutoff"], deadline)
                if removed is None:
                    break
                deleted += int(removed)
            state["last_key"] = key
            processed += 1
        complete = processed == len(items) and not page["IsTruncated"]
        with connection.transaction():
            if complete:
                connection.execute(
                    "UPDATE publication.maintenance_state SET last_key = '', cutoff = NULL, "
                    "sweep_started_at = NULL, last_sweep_completed_at = clock_timestamp(), "
                    "next_due_at = clock_timestamp() + %s "
                    "WHERE job = 'orphan_scan'",
                    (timedelta(seconds=SWEEP_REST_SECONDS),),
                )
            else:
                connection.execute(
                    "UPDATE publication.maintenance_state SET last_key = %s "
                    "WHERE job = 'orphan_scan'",
                    (state["last_key"],),
                )
        return {
            "listed": len(items),
            "processed": processed,
            "deleted": deleted,
            "skipped": processed - deleted,
            "sweep_completed": complete,
        }

    def _remove_orphan(self, connection, key, digest, cutoff, deadline):
        with connection.transaction():
            connection.execute("SET LOCAL lock_timeout = '1s'")
            lock_publication_mutation(connection)
            if (
                connection.execute(
                    "SELECT 1 FROM publication.objects WHERE sha256 = %s", (digest,)
                ).fetchone()
                is not None
            ):
                return False
            if time.monotonic() >= deadline:
                return None
            try:
                metadata = self._s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError as error:
                if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise
            modified = metadata.get("LastModified")
            if not _aware(modified):
                raise PublicationVerificationError("Orphan metadata has no modification time")
            if modified > cutoff:
                return False
            if time.monotonic() >= deadline:
                return None
            # HEAD may outlive the owning session. Verify the same connection and
            # reference fence again before starting destructive I/O.
            if (
                connection.execute(
                    "SELECT 1 FROM publication.objects WHERE sha256 = %s", (digest,)
                ).fetchone()
                is not None
            ):
                return False
            if time.monotonic() >= deadline:
                return None
            self._s3.delete_object(Bucket=self._bucket, Key=key)
            connection.execute(
                "UPDATE publication.maintenance_state SET last_key = %s WHERE job = 'orphan_scan'",
                (key,),
            )
            return True


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _failure_code(error: Exception) -> str:
    if isinstance(error, LockNotAvailable):
        return "PUBLICATION_MUTATION_BUSY"
    cause = error
    while cause.__cause__ is not None:
        cause = cause.__cause__
    if isinstance(cause, ClientError):
        return {
            "AccessDenied": "PUBLICATION_ACCESS_DENIED",
            "NoSuchBucket": "PUBLICATION_BUCKET_MISSING",
        }.get(cause.response.get("Error", {}).get("Code"), "PUBLICATION_STORAGE_UNAVAILABLE")
    if isinstance(error, PublicationVerificationError) and not isinstance(
        error, PublicationUnavailableError
    ):
        return "PUBLICATION_LIST_INVALID"
    return "PUBLICATION_STORAGE_UNAVAILABLE"

"""Seven-day idle retention for explicitly designated diagnostic payloads.

Expiry releases live object references, retaining verified tombstones in the
immutable manifest inventory. Reporting payloads and snapshot identities survive.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from thesistrace.publication.service import (
    Publication,
    PublicationVerificationError,
    PublishedRef,
    lock_publication_mutation,
)

T = TypeVar("T")


class PayloadRetention:
    def __init__(self, database, publication: Publication):
        self._database = database
        self._publication = publication

    def read_detail(
        self,
        reference: PublishedRef,
        read: Callable,
        *,
        payload_name: str | None = None,
    ) -> tuple[dict | None, T | None]:
        with self._database.transaction() as tx:
            # Hold this row through bounded I/O; expiry and manifest release wait.
            row = tx.execute(
                "SELECT * FROM publication.payload_retention WHERE manifest_sha256 = %s FOR UPDATE",
                (reference.manifest_sha256,),
            ).fetchone()
            self._publication.payload_names_in_transaction(tx, reference)
            if (
                row is not None
                and payload_name is not None
                and payload_name not in row["payload_names"]
            ):
                return None, read(tx)
            now = tx.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            if row is not None and (row["expired_at"] is not None or row["expires_at"] <= now):
                return {**row, "status": "expired"}, None
            if row is not None:
                # Keep an admitted read valid across its old deadline. This is
                # uncommitted and rolls back with failed verification below.
                tx.execute(
                    "UPDATE publication.payload_retention SET expires_at = %s + interval '7 days' "
                    "WHERE manifest_sha256 = %s", (now, reference.manifest_sha256),
                )
            value = read(tx)
            if row is not None:
                row = tx.execute(
                    "UPDATE publication.payload_retention SET last_read_at = t.now, "
                    "expires_at = t.now + interval '7 days' "
                    "FROM (SELECT clock_timestamp() AS now) t WHERE manifest_sha256 = %s "
                    "RETURNING payload_retention.*",
                    (reference.manifest_sha256,),
                ).fetchone()
            return row, value

    def expire_one_in_transaction(self, tx) -> bool:
        lock_publication_mutation(tx)
        row = tx.execute(
            "SELECT * FROM publication.payload_retention "
            "WHERE expired_at IS NULL AND expires_at <= clock_timestamp() "
            "ORDER BY expires_at, manifest_sha256 LIMIT 1 FOR UPDATE SKIP LOCKED"
        ).fetchone()
        if row is None:
            return False
        sha = row["manifest_sha256"]
        objects = tx.execute(
            "SELECT mo.*, o.byte_size FROM publication.manifest_objects mo "
            "JOIN publication.objects o ON o.sha256 = mo.object_sha256 "
            "WHERE mo.manifest_sha256 = %s AND mo.logical_name = ANY(%s)",
            (sha, row["payload_names"]),
        ).fetchall()
        if {r["logical_name"] for r in objects} != set(row["payload_names"]):
            raise PublicationVerificationError("Expiring payload inventory is incomplete")
        for item in objects:
            tx.execute(
                "INSERT INTO publication.expired_payloads "
                "(manifest_sha256, ordinal, logical_name, object_sha256, byte_size) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    sha,
                    item["ordinal"],
                    item["logical_name"],
                    item["object_sha256"],
                    item["byte_size"],
                ),
            )
        tx.execute(
            "DELETE FROM publication.manifest_objects WHERE manifest_sha256 = %s "
            "AND logical_name = ANY(%s)",
            (sha, row["payload_names"]),
        )
        tx.execute(
            "UPDATE publication.payload_retention SET expired_at = clock_timestamp() "
            "WHERE manifest_sha256 = %s",
            (sha,),
        )
        for item in objects:
            digest = item["object_sha256"]
            tx.execute(
                "INSERT INTO publication.object_deletions(object_sha256) "
                "SELECT %s WHERE NOT EXISTS (SELECT 1 FROM publication.manifest_objects "
                "WHERE object_sha256 = %s) ON CONFLICT DO NOTHING",
                (digest, digest),
            )
        return True

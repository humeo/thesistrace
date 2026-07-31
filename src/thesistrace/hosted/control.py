import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from thesistrace.quota import (
    QuotaExceededError,
    daily_track_activation_lock_key,
)
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

    def commit(self) -> None:
        self.connection.commit()

    def lock_research_run(self, run_id: str) -> HybridRow | None:
        return self.connection.execute(
            """
            SELECT status
            FROM thesistrace_product.research_runs
            WHERE id = %s
            FOR UPDATE
            """,
            (run_id,),
        ).fetchone()


class PostgresControlMetadataStore(MetadataStore):
    def __init__(self, database_url: str, *, database_role: str) -> None:
        if database_role not in HOSTED_DATABASE_ROLES:
            raise ValueError(f"unsupported hosted database role: {database_role}")
        self.database_url = database_url
        self.database_role = database_role

    def initialize(self) -> None:
        return None

    @contextmanager
    def storage_mutation_fence(self) -> Iterator[None]:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                ("thesistrace:storage-mutations",),
            )
            try:
                yield
            finally:
                connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    ("thesistrace:storage-mutations",),
                )

    def next_dataset_release_on_path(
        self,
        ancestor_id: str,
        descendant_id: str,
    ) -> dict[str, object] | None:
        if ancestor_id == descendant_id:
            return None
        descendant = self.dataset_release(descendant_id)
        if descendant is None:
            return None
        if descendant.get("predecessor_id") == ancestor_id:
            return descendant
        with self.connect() as connection:
            row = connection.execute(
                """
                WITH RECURSIVE lineage(
                    id,
                    predecessor_id,
                    manifest_json
                ) AS (
                    SELECT id,
                           manifest_json::jsonb ->> 'predecessor_id',
                           manifest_json
                    FROM dataset_releases
                    WHERE id = ?
                    UNION ALL
                    SELECT release.id,
                           release.manifest_json::jsonb
                               ->> 'predecessor_id',
                           release.manifest_json
                    FROM dataset_releases AS release
                    JOIN lineage
                      ON release.id = lineage.predecessor_id
                )
                SELECT manifest_json
                FROM lineage
                WHERE predecessor_id = ?
                LIMIT 1
                """,
                (descendant_id, ancestor_id),
            ).fetchone()
        if row is None or row["manifest_json"] is None:
            return None
        return dict(json.loads(str(row["manifest_json"])))

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

    def _enqueue_research_run(
        self,
        connection: PostgresConnectionAdapter,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO execution_outbox
                (id, resource_kind, resource_id, status, created_at)
            VALUES (?, 'research_run', ?, 'pending', ?)
            """,
            (f"outbox_{run_id}", run_id, created_at),
        )

    def _enqueue_research_run_cancellation(
        self,
        connection: PostgresConnectionAdapter,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO execution_outbox
                (id, resource_kind, resource_id, status, created_at)
            VALUES (?, 'research_run_cancel', ?, 'pending', ?)
            ON CONFLICT (workspace_id, resource_kind, resource_id) DO NOTHING
            """,
            (f"cancel_{run_id}", run_id, created_at),
        )

    def _enqueue_tracking_operation(
        self,
        connection: PostgresConnectionAdapter,
        *,
        resource_kind: str,
        resource_id: str,
        created_at: str,
    ) -> None:
        if resource_kind not in {
            "tracking_equivalence",
            "tracking_equivalence_cancel",
            "tracking_generation_rebuild",
            "tracking_generation_rebuild_cancel",
        }:
            raise ValueError("unsupported Tracking operation")
        connection.execute(
            """
            INSERT INTO execution_outbox
                (id, resource_kind, resource_id, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            ON CONFLICT (workspace_id, resource_kind, resource_id)
            DO NOTHING
            """,
            (
                f"outbox_{resource_kind}_{resource_id}",
                resource_kind,
                resource_id,
                created_at,
            ),
        )

    def enqueue_tracking_advance_execution(
        self,
        connection: PostgresConnectionAdapter,
        *,
        track_id: str,
        advance_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO tracking_execution_outbox
                (id, daily_track_id, advance_id, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            ON CONFLICT(workspace_id, advance_id) DO NOTHING
            """,
            (
                f"outbox_{advance_id}",
                track_id,
                advance_id,
                created_at,
            ),
        )

    def _admit_user_compute(
        self,
        connection: PostgresConnectionAdapter,
        *,
        resource_kind: str,
        resource_id: str,
        admitted_at: str,
    ) -> None:
        workspace = connection.execute(
            "SELECT thesistrace_control.current_workspace_id() AS workspace_id"
        ).fetchone()
        if workspace is None or workspace["workspace_id"] is None:
            raise RuntimeError("Personal Workspace context is missing")
        workspace_id = str(workspace["workspace_id"])
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (workspace_id,),
        )
        profile = connection.execute(
            """
            SELECT max_nonterminal_user_compute_jobs
            FROM thesistrace_control.workspace_quota_profiles
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if profile is None:
            raise RuntimeError("Personal Workspace Quota Profile is missing")
        limit = int(profile["max_nonterminal_user_compute_jobs"])
        active = int(
            connection.execute(
                """
                SELECT count(*)
                FROM user_compute_admissions
                WHERE completed_at IS NULL
                """
            ).fetchone()[0]
        )
        if active >= limit:
            raise QuotaExceededError(
                dimension="max_nonterminal_user_compute_jobs",
                limit=limit,
            )
        connection.execute(
            """
            INSERT INTO user_compute_admissions (
                resource_kind,
                resource_id,
                admitted_at
            )
            VALUES (?, ?, ?)
            """,
            (resource_kind, resource_id, admitted_at),
        )

    def commit_private_storage_references(
        self,
        connection: PostgresConnectionAdapter,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int:
        row = connection.execute(
            """
            SELECT accepted, used_bytes, limit_bytes
            FROM thesistrace_control.commit_workspace_storage_references(
                ?, ?, ?::jsonb
            )
            """,
            (
                resource_kind,
                resource_id,
                json.dumps(
                    objects,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("private storage admission returned no result")
        if not bool(row["accepted"]):
            raise QuotaExceededError(
                dimension="max_private_storage_bytes",
                limit=int(row["limit_bytes"]),
            )
        return int(row["used_bytes"])

    def commit_platform_storage_references(
        self,
        connection: PostgresConnectionAdapter,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int:
        row = connection.execute(
            """
            SELECT thesistrace_control.commit_platform_storage_references(
                ?, ?, ?::jsonb
            ) AS used_bytes
            """,
            (
                resource_kind,
                resource_id,
                json.dumps(
                    objects,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("platform storage indexing returned no result")
        return int(row["used_bytes"])

    def request_resource_deletion(
        self,
        *,
        resource_kind: str,
        resource_id: str,
        actor: str,
        deleted_at: str,
    ) -> dict[str, object] | None:
        tombstone_id = f"tombstone_{uuid4().hex}"
        try:
            with self.connect() as connection:
                row = connection.execute(
                    """
                    SELECT tombstone_id, workspace_id, resource_kind,
                           resource_id, authoritative_manifest_sha256,
                           actor, deleted_at
                    FROM thesistrace_control.request_resource_deletion(
                        ?, ?, ?, ?, ?::timestamptz
                    )
                    """,
                    (
                        tombstone_id,
                        resource_kind,
                        resource_id,
                        actor,
                        deleted_at,
                    ),
                ).fetchone()
        except psycopg.Error as error:
            message = error.diag.message_primary or str(error)
            if message in {
                "RESOURCE_NOT_TERMINAL",
                "RESOURCE_RETAINED",
                "RESOURCE_STORAGE_UNINDEXED",
            }:
                raise ValueError(message) from error
            raise
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("tombstone_id")
        result["deleted_at"] = str(result["deleted_at"])
        return result

    def pending_resource_cleanups(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT tombstone_id, resource_kind, resource_id,
                       daily_track_id, fencing_token,
                       attempt_count, last_error
                FROM thesistrace_control.pending_resource_cleanups()
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def resource_cleanup_candidates(self, tombstone_id: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT object_key
                FROM thesistrace_control.resource_cleanup_candidates(?)
                    AS candidate(object_key)
                """,
                (tombstone_id,),
            ).fetchall()
        return [str(row["object_key"]) for row in rows]

    def complete_resource_cleanup(
        self,
        tombstone_id: str,
        completed_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                SELECT thesistrace_control.complete_resource_cleanup(
                    ?, ?::timestamptz
                )
                """,
                (tombstone_id, completed_at),
            )

    def fail_resource_cleanup(
        self,
        tombstone_id: str,
        error: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                SELECT thesistrace_control.fail_resource_cleanup(?, ?)
                """,
                (tombstone_id, error),
            )

    def _lock_idempotent_admission(
        self,
        connection: PostgresConnectionAdapter,
        *,
        operation: str,
        idempotency_key: str,
    ) -> None:
        workspace = connection.execute(
            "SELECT thesistrace_control.current_workspace_id() AS workspace_id"
        ).fetchone()
        if workspace is None or workspace["workspace_id"] is None:
            raise RuntimeError("Personal Workspace context is missing")
        lock_identity = (
            f"{workspace['workspace_id']}:{operation}:{idempotency_key}"
        )
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (lock_identity,),
        )

    def _complete_user_compute(
        self,
        connection: PostgresConnectionAdapter,
        *,
        resource_kind: str,
        resource_id: str,
        completed_at: str,
    ) -> None:
        connection.execute(
            """
            UPDATE user_compute_admissions
            SET completed_at = COALESCE(completed_at, ?)
            WHERE resource_kind = ?
              AND resource_id = ?
              AND completed_at IS NULL
            """,
            (completed_at, resource_kind, resource_id),
        )

    def _lock_dataset_publication_slot(
        self,
        connection: PostgresConnectionAdapter,
    ) -> None:
        connection.execute(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended('dataset-publication-slot', 0)
            )
            """
        )

    def lock_daily_track_activation(
        self,
        connection: PostgresConnectionAdapter,
    ) -> None:
        workspace = connection.execute(
            "SELECT thesistrace_control.current_workspace_id() AS workspace_id"
        ).fetchone()
        if workspace is None or workspace["workspace_id"] is None:
            raise RuntimeError("Personal Workspace context is missing")
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (
                daily_track_activation_lock_key(
                    str(workspace["workspace_id"])
                ),
            ),
        )

    def active_daily_track_limit(
        self,
        connection: PostgresConnectionAdapter,
    ) -> int:
        row = connection.execute(
            """
            SELECT max_active_daily_tracks
            FROM thesistrace_control.workspace_quota_profiles
            WHERE workspace_id = thesistrace_control.current_workspace_id()
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("Personal Workspace Quota Profile is missing")
        return int(row["max_active_daily_tracks"])

    def lock_daily_track(
        self,
        connection: PostgresConnectionAdapter,
        track_id: str,
    ) -> None:
        connection.execute(
            """
            SELECT id
            FROM daily_tracks
            WHERE id = ?
            FOR UPDATE
            """,
            (track_id,),
        )

    def daily_track_head_manifest_sha256(
        self,
        track_id: str,
    ) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    thesistrace_control.daily_track_head_manifest_sha256(
                        ?
                    ) AS manifest_sha256
                """,
                (track_id,),
            ).fetchone()
        if row is None or row["manifest_sha256"] is None:
            return None
        return str(row["manifest_sha256"])

    def daily_track_activation_reservation_ids(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT track_id
                FROM
                    thesistrace_control.daily_track_activation_reservation_ids()
                    AS reservation(track_id)
                """
            ).fetchall()
        return [str(row["track_id"]) for row in rows]

    def delete_daily_track_activation_reservation(
        self,
        track_id: str,
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    thesistrace_control.delete_daily_track_activation_reservation(
                        ?
                    ) AS deleted
                """,
                (track_id,),
            ).fetchone()
        return bool(row is not None and row["deleted"])

    def daily_track_cache_states(
        self,
        track_ids: list[str],
    ) -> dict[str, tuple[str, int]]:
        if not track_ids:
            return {}
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT track_id, status, fencing_token
                FROM thesistrace_control.daily_track_cache_states(?)
                """,
                (track_ids,),
            ).fetchall()
        return {
            str(row["track_id"]): (
                str(row["status"]),
                int(row["fencing_token"]),
            )
            for row in rows
        }

    def active_daily_track_refs(
        self,
        *,
        after_workspace_id: str | None = None,
        after_track_id: str | None = None,
        through_workspace_id: str | None = None,
        through_track_id: str | None = None,
        limit: int = 101,
    ) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT workspace_id, track_id
                FROM thesistrace_control.active_daily_track_refs(
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    after_workspace_id,
                    after_track_id,
                    through_workspace_id,
                    through_track_id,
                    limit,
                ),
            ).fetchall()
        return [
            {
                "workspace_id": str(row["workspace_id"]),
                "track_id": str(row["track_id"]),
            }
            for row in rows
        ]

    def active_daily_track_scan_bound(
        self,
    ) -> dict[str, str] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT workspace_id, track_id
                FROM thesistrace_control.active_daily_track_scan_bound()
                """
            ).fetchone()
        return (
            None
            if row is None
            else {
                "workspace_id": str(row["workspace_id"]),
                "track_id": str(row["track_id"]),
            }
        )

    def pending_working_cache_deletions(
        self,
        track_id: str | None = None,
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT daily_track_id, fencing_token,
                       attempt_count, track_status
                FROM
                    thesistrace_control.pending_working_cache_deletions(
                        ?
                    )
                """,
                (track_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fail_working_cache_deletion(
        self,
        track_id: str,
        error: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                SELECT thesistrace_control.fail_working_cache_deletion(
                    ?, ?
                )
                """,
                (track_id, error),
            )

    def complete_working_cache_deletion(
        self,
        track_id: str,
        completed_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                SELECT
                    thesistrace_control.complete_working_cache_deletion(
                        ?, ?
                    )
                """,
                (track_id, completed_at),
            )

    def request_dataset_publication(
        self,
        record: dict[str, object],
        audit_event: dict[str, object] | None,
    ) -> tuple[dict[str, object], bool]:
        if audit_event is not None or record.get("trigger_kind") != "schedule":
            raise PermissionError(
                "Data role can only request validated scheduled publications"
            )
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT publication_id, created
                FROM thesistrace_control.request_scheduled_dataset_publication(
                    ?, ?, ?, ?::jsonb, ?, ?
                )
                """,
                (
                    record["id"],
                    record["request_version"],
                    record["kind"],
                    json.dumps(
                        record["parameters"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    record["idempotency_key"],
                    record["created_at"],
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Scheduled Dataset Publication was not created")
            publication = self._dataset_publication(
                connection,
                str(row["publication_id"]),
            )
            if publication is None:
                raise RuntimeError("Scheduled Dataset Publication disappeared")
            return publication, bool(row["created"])

    def _lock_dataset_publication(
        self,
        connection: PostgresConnectionAdapter,
        publication_id: str,
    ) -> None:
        connection.execute(
            """
            SELECT id
            FROM dataset_publications
            WHERE id = ?
            FOR UPDATE
            """,
            (publication_id,),
        )

    def _lock_dataset_publication_request(
        self,
        connection: PostgresConnectionAdapter,
        idempotency_key: str,
    ) -> None:
        connection.execute(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended('dataset-publication-request:' || ?, 0)
            )
            """,
            (idempotency_key,),
        )

    def source_authorization_is_authorized(self) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT thesistrace_control.hosted_tushare_authorized()
                    AS authorized
                """
            ).fetchone()
        return bool(row and row["authorized"])


__all__ = ["PostgresControlMetadataStore"]

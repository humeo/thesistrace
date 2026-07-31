import fcntl
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

RESOURCE_TABLES = (
    "dataset_releases",
    "research_definitions",
    "research_runs",
    "daily_tracks",
)


class DatasetPublicationConflict(RuntimeError):
    pass


class MetadataStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    installation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS worker_heartbeat (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    heartbeat_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS management_audit_events (
                    id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('succeeded', 'rejected')),
                    reason_code TEXT,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_authorization_declarations (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    intended_scope TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    declared_at TEXT NOT NULL,
                    audit_event_id TEXT NOT NULL
                        REFERENCES management_audit_events(id)
                );

                CREATE TRIGGER IF NOT EXISTS management_audit_events_no_update
                BEFORE UPDATE ON management_audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'management audit events are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS management_audit_events_no_delete
                BEFORE DELETE ON management_audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'management audit events are non-deletable');
                END;

                CREATE TRIGGER IF NOT EXISTS source_authorizations_no_update
                BEFORE UPDATE ON source_authorization_declarations
                BEGIN
                    SELECT RAISE(ABORT, 'source authorization declarations are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS source_authorizations_no_delete
                BEFORE DELETE ON source_authorization_declarations
                BEGIN
                    SELECT RAISE(ABORT, 'source authorization declarations are non-deletable');
                END;

                CREATE TABLE IF NOT EXISTS dataset_releases (
                    id TEXT PRIMARY KEY,
                    manifest_json TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS dataset_release_pointer (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    release_id TEXT NOT NULL REFERENCES dataset_releases(id)
                );

                CREATE TABLE IF NOT EXISTS publication_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    release_id TEXT NOT NULL REFERENCES dataset_releases(id)
                );

                CREATE TABLE IF NOT EXISTS dataset_publications (
                    id TEXT PRIMARY KEY,
                    request_version TEXT NOT NULL CHECK (request_version = 'v1'),
                    kind TEXT NOT NULL CHECK (
                        kind IN (
                            'fixture_bootstrap',
                            'fixture_increment',
                            'live_bootstrap',
                            'live_increment'
                        )
                    ),
                    parameters_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    trigger_kind TEXT NOT NULL CHECK (
                        trigger_kind IN ('operator', 'schedule')
                    ),
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'queued',
                            'running',
                            'succeeded',
                            'failed',
                            'cancelled'
                        )
                    ),
                    result_release_id TEXT REFERENCES dataset_releases(id),
                    result_manifest_sha256 TEXT,
                    diagnostic_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dataset_publication_attempts (
                    id TEXT PRIMARY KEY,
                    publication_id TEXT NOT NULL
                        REFERENCES dataset_publications(id),
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('running', 'succeeded', 'failed', 'cancelled')
                    ),
                    diagnostic_json TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    UNIQUE (publication_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS platform_execution_outbox (
                    id TEXT PRIMARY KEY,
                    resource_kind TEXT NOT NULL
                        CHECK (resource_kind = 'dataset_publication'),
                    resource_id TEXT NOT NULL
                        REFERENCES dataset_publications(id),
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'dispatched')
                    ),
                    created_at TEXT NOT NULL,
                    dispatched_at TEXT,
                    UNIQUE (resource_kind, resource_id)
                );

                CREATE TABLE IF NOT EXISTS tracking_release_triggers (
                    release_id TEXT PRIMARY KEY REFERENCES dataset_releases(id),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'dispatched')),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_definitions (
                    id TEXT PRIMARY KEY,
                    draft_id TEXT,
                    version INTEGER,
                    content_json TEXT,
                    content_hash TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS research_runs (
                    id TEXT PRIMARY KEY,
                    definition_version_id TEXT,
                    dataset_release_id TEXT,
                    status TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS research_definition_drafts (
                    id TEXT PRIMARY KEY,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_run_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES research_runs(id)
                );

                CREATE TABLE IF NOT EXISTS research_run_attempts (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES research_runs(id),
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    completed_at TEXT,
                    diagnostic_json TEXT,
                    UNIQUE(run_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS daily_tracks (
                    id TEXT PRIMARY KEY,
                    seed_run_id TEXT,
                    definition_version_id TEXT,
                    definition_content_hash TEXT,
                    activation_release_id TEXT,
                    origin_session TEXT,
                    numeric_execution_contract TEXT,
                    status TEXT,
                    current_generation_id TEXT,
                    head_checkpoint_id TEXT,
                    created_at TEXT,
                    stopped_at TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_track_activation_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    daily_track_id TEXT NOT NULL REFERENCES daily_tracks(id)
                );

                CREATE TABLE IF NOT EXISTS daily_track_activation_reservations (
                    track_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    seed_run_id TEXT NOT NULL REFERENCES research_runs(id),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tracking_generations (
                    id TEXT PRIMARY KEY,
                    daily_track_id TEXT NOT NULL REFERENCES daily_tracks(id),
                    ordinal INTEGER NOT NULL,
                    calculation_kernel TEXT NOT NULL,
                    numeric_execution_contract TEXT NOT NULL,
                    basis_dataset_release_id TEXT NOT NULL,
                    supersedes_generation_id TEXT,
                    supersedes_head_checkpoint_id TEXT,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(daily_track_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS tracking_checkpoints (
                    id TEXT PRIMARY KEY,
                    daily_track_id TEXT NOT NULL REFERENCES daily_tracks(id),
                    generation_id TEXT NOT NULL REFERENCES tracking_generations(id),
                    predecessor_checkpoint_id TEXT,
                    target_dataset_release_id TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tracking_advances (
                    id TEXT PRIMARY KEY,
                    daily_track_id TEXT NOT NULL REFERENCES daily_tracks(id),
                    generation_id TEXT NOT NULL REFERENCES tracking_generations(id),
                    target_dataset_release_id TEXT NOT NULL,
                    correction_boundary_json TEXT,
                    status TEXT NOT NULL,
                    checkpoint_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(daily_track_id, generation_id, target_dataset_release_id)
                );

                CREATE TABLE IF NOT EXISTS tracking_execution_outbox (
                    id TEXT PRIMARY KEY,
                    daily_track_id TEXT NOT NULL REFERENCES daily_tracks(id),
                    advance_id TEXT NOT NULL UNIQUE REFERENCES tracking_advances(id),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'dispatched')),
                    created_at TEXT NOT NULL,
                    dispatched_at TEXT
                );

                CREATE INDEX IF NOT EXISTS
                tracking_execution_outbox_pending_order
                ON tracking_execution_outbox(created_at, id)
                WHERE status = 'pending';

                CREATE TABLE IF NOT EXISTS tracking_advance_attempts (
                    id TEXT PRIMARY KEY,
                    advance_id TEXT NOT NULL REFERENCES tracking_advances(id),
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    diagnostic_json TEXT,
                    UNIQUE(advance_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS tracking_equivalence_requests (
                    id TEXT PRIMARY KEY,
                    daily_track_id TEXT NOT NULL REFERENCES daily_tracks(id),
                    generation_id TEXT NOT NULL REFERENCES tracking_generations(id),
                    head_checkpoint_id TEXT NOT NULL REFERENCES tracking_checkpoints(id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    diagnostic_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tracking_generation_rebuilds (
                    id TEXT PRIMARY KEY,
                    daily_track_id TEXT NOT NULL REFERENCES daily_tracks(id),
                    calculation_kernel TEXT NOT NULL,
                    numeric_execution_contract TEXT NOT NULL,
                    basis_generation_id TEXT NOT NULL,
                    basis_head_checkpoint_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    generation_id TEXT,
                    advance_id TEXT,
                    diagnostic_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS working_cache_deletions (
                    daily_track_id TEXT PRIMARY KEY REFERENCES daily_tracks(id),
                    fencing_token INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    requested_at TEXT NOT NULL,
                    completed_at TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS stored_objects (
                    object_key TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    compressed_bytes INTEGER NOT NULL,
                    object_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS storage_references (
                    owner_scope TEXT NOT NULL,
                    workspace_id TEXT,
                    resource_kind TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    object_key TEXT NOT NULL REFERENCES stored_objects(object_key),
                    created_at TEXT NOT NULL,
                    UNIQUE (
                        owner_scope,
                        workspace_id,
                        resource_kind,
                        resource_id,
                        object_key
                    )
                );

                CREATE TABLE IF NOT EXISTS resource_tombstones (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    resource_kind TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    authoritative_manifest_sha256 TEXT,
                    actor TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    UNIQUE (workspace_id, resource_kind, resource_id)
                );

                CREATE TABLE IF NOT EXISTS resource_cleanup_jobs (
                    tombstone_id TEXT PRIMARY KEY
                        REFERENCES resource_tombstones(id),
                    daily_track_id TEXT,
                    fencing_token INTEGER,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT,
                    last_error TEXT
                );
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO workspace (singleton, installation_id, created_at)
                VALUES (1, ?, ?)
                """,
                (str(uuid4()), datetime.now(UTC).isoformat()),
            )
            self._ensure_column(connection, "dataset_releases", "manifest_json", "TEXT")
            self._ensure_column(connection, "dataset_releases", "created_at", "TEXT")
            for column, definition in (
                ("draft_id", "TEXT"),
                ("version", "INTEGER"),
                ("content_json", "TEXT"),
                ("content_hash", "TEXT"),
                ("created_at", "TEXT"),
            ):
                self._ensure_column(connection, "research_definitions", column, definition)
            for column, definition in (
                ("definition_version_id", "TEXT"),
                ("dataset_release_id", "TEXT"),
                ("status", "TEXT"),
                ("created_at", "TEXT"),
                ("updated_at", "TEXT"),
                ("started_at", "TEXT"),
                ("completed_at", "TEXT"),
                ("result_bundle_id", "TEXT"),
                ("result_manifest_sha256", "TEXT"),
            ):
                self._ensure_column(connection, "research_runs", column, definition)
            for column, definition in (
                ("seed_run_id", "TEXT"),
                ("definition_version_id", "TEXT"),
                ("definition_content_hash", "TEXT"),
                ("activation_release_id", "TEXT"),
                ("origin_session", "TEXT"),
                ("numeric_execution_contract", "TEXT"),
                ("status", "TEXT"),
                ("current_generation_id", "TEXT"),
                ("head_checkpoint_id", "TEXT"),
                ("created_at", "TEXT"),
                ("stopped_at", "TEXT"),
                ("fencing_token", "INTEGER NOT NULL DEFAULT 0"),
            ):
                self._ensure_column(connection, "daily_tracks", column, definition)
            self._ensure_column(
                connection,
                "tracking_advance_attempts",
                "fencing_token",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "tracking_advances",
                "correction_boundary_json",
                "TEXT",
            )

    def lock_daily_track_activation(
        self,
        connection,
    ) -> None:
        del connection

    def active_daily_track_limit(self, connection) -> int:
        del connection
        return 10

    def lock_daily_track(self, connection, track_id: str) -> None:
        del connection, track_id

    def daily_track_head_manifest_sha256(
        self,
        track_id: str,
    ) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT checkpoint.manifest_sha256
                FROM daily_tracks AS track
                JOIN tracking_checkpoints AS checkpoint
                  ON checkpoint.id = track.head_checkpoint_id
                WHERE track.id = ?
                """,
                (track_id,),
            ).fetchone()
        return None if row is None else str(row["manifest_sha256"])

    def daily_track_activation_reservation_ids(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT track_id
                FROM daily_track_activation_reservations
                ORDER BY track_id
                """
            ).fetchall()
        return [str(row["track_id"]) for row in rows]

    def delete_daily_track_activation_reservation(
        self,
        track_id: str,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM daily_track_activation_reservations
                WHERE track_id = ?
                """,
                (track_id,),
            )
        return cursor.rowcount == 1

    def daily_track_cache_states(
        self,
        track_ids: list[str],
    ) -> dict[str, tuple[str, int]]:
        if not track_ids:
            return {}
        placeholders = ", ".join("?" for _ in track_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, status, fencing_token
                FROM daily_tracks
                WHERE id IN ({placeholders})
                """,
                track_ids,
            ).fetchall()
        return {
            str(row["id"]): (
                str(row["status"]),
                int(row["fencing_token"]),
            )
            for row in rows
        }

    def pending_working_cache_deletions(
        self,
        track_id: str | None = None,
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT deletion.daily_track_id,
                       deletion.fencing_token,
                       deletion.attempt_count,
                       track.status AS track_status
                FROM working_cache_deletions AS deletion
                LEFT JOIN daily_tracks AS track
                  ON track.id = deletion.daily_track_id
                WHERE deletion.status = 'pending'
                  AND deletion.daily_track_id =
                      COALESCE(?, deletion.daily_track_id)
                ORDER BY deletion.requested_at,
                         deletion.daily_track_id
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
                UPDATE working_cache_deletions
                SET attempt_count = attempt_count + 1,
                    last_error = ?
                WHERE daily_track_id = ? AND status = 'pending'
                """,
                (error, track_id),
            )

    def complete_working_cache_deletion(
        self,
        track_id: str,
        completed_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE working_cache_deletions
                SET status = 'completed',
                    attempt_count = attempt_count + 1,
                    completed_at = ?, last_error = NULL
                WHERE daily_track_id = ? AND status = 'pending'
                """,
                (completed_at, track_id),
            )

    def installation_id(self) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT installation_id FROM workspace WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("workspace metadata is not initialized")
        return str(row["installation_id"])

    def record_source_authorization(
        self,
        declaration: dict[str, object],
        audit_event: dict[str, object],
    ) -> None:
        with self.connect() as connection:
            self._insert_management_audit_event(connection, audit_event)
            connection.execute(
                """
                INSERT INTO source_authorization_declarations (
                    id, source, intended_scope, actor, declared_at, audit_event_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    declaration["id"],
                    declaration["source"],
                    declaration["scope"],
                    declaration["actor"],
                    declaration["declared_at"],
                    declaration["audit_event_id"],
                ),
            )

    def append_management_audit_event(self, event: dict[str, object]) -> None:
        with self.connect() as connection:
            self._insert_management_audit_event(connection, event)

    def latest_source_authorization(self) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    source,
                    intended_scope AS scope,
                    actor,
                    declared_at,
                    audit_event_id
                FROM source_authorization_declarations
                WHERE source = 'tushare'
                ORDER BY declared_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def source_authorization_is_authorized(self) -> bool:
        declaration = self.latest_source_authorization()
        return bool(
            declaration
            and declaration.get("source") == "tushare"
            and declaration.get("scope") == "hosted-shared-dataset-releases"
        )

    def list_management_audit_events(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    occurred_at,
                    actor,
                    action,
                    outcome,
                    reason_code,
                    subject_type,
                    subject_id,
                    details_json
                FROM management_audit_events
                ORDER BY occurred_at, id
                """
            ).fetchall()
        return [
            {
                **dict(row),
                "details": json.loads(str(row["details_json"])),
            }
            for row in rows
        ]

    @staticmethod
    def _insert_management_audit_event(
        connection: sqlite3.Connection,
        event: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO management_audit_events (
                id,
                occurred_at,
                actor,
                action,
                outcome,
                reason_code,
                subject_type,
                subject_id,
                details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["id"],
                event["occurred_at"],
                event["actor"],
                event["action"],
                event["outcome"],
                event["reason_code"],
                event["subject_type"],
                event["subject_id"],
                json.dumps(event["details"], sort_keys=True, separators=(",", ":")),
            ),
        )

    def resource_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in RESOURCE_TABLES
            }

    def request_dataset_publication(
        self,
        record: dict[str, object],
        audit_event: dict[str, object] | None,
    ) -> tuple[dict[str, object], bool]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication_request(
                connection,
                str(record["idempotency_key"]),
            )
            existing = connection.execute(
                """
                SELECT id
                FROM dataset_publications
                WHERE idempotency_key = ?
                """,
                (record["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                publication = self._dataset_publication(
                    connection,
                    str(existing["id"]),
                )
                if publication is None:
                    raise RuntimeError("Dataset Publication disappeared")
                return publication, False
            connection.execute(
                """
                INSERT INTO dataset_publications (
                    id,
                    request_version,
                    kind,
                    parameters_json,
                    idempotency_key,
                    trigger_kind,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
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
                    record["trigger_kind"],
                    record["created_at"],
                    record["updated_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO platform_execution_outbox (
                    id,
                    resource_kind,
                    resource_id,
                    status,
                    created_at
                )
                VALUES (?, 'dataset_publication', ?, 'pending', ?)
                """,
                (
                    f"outbox_{record['id']}",
                    record["id"],
                    record["created_at"],
                ),
            )
            if audit_event is not None:
                self._insert_management_audit_event(connection, audit_event)
            publication = self._dataset_publication(
                connection,
                str(record["id"]),
            )
            if publication is None:
                raise RuntimeError("Dataset Publication was not created")
            return publication, True

    def dataset_publication_for_idempotency_key(
        self,
        idempotency_key: str,
    ) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM dataset_publications
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            return (
                None
                if row is None
                else self._dataset_publication(connection, str(row["id"]))
            )

    def dataset_publication(
        self,
        publication_id: str,
    ) -> dict[str, object] | None:
        with self.connect() as connection:
            return self._dataset_publication(connection, publication_id)

    def claim_dataset_publication(
        self,
        publication_id: str,
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication_slot(connection)
            row = connection.execute(
                """
                SELECT status
                FROM dataset_publications
                WHERE id = ?
                """,
                (publication_id,),
            ).fetchone()
            if row is None or row["status"] != "queued":
                return None
            running = connection.execute(
                """
                SELECT id
                FROM dataset_publications
                WHERE status = 'running'
                LIMIT 1
                """
            ).fetchone()
            if running is not None:
                return None
            ordinal = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM dataset_publication_attempts
                    WHERE publication_id = ?
                    """,
                    (publication_id,),
                ).fetchone()[0]
            ) + 1
            attempt_id = f"dpa_{uuid4().hex[:20]}"
            connection.execute(
                """
                UPDATE dataset_publications
                SET status = 'running',
                    diagnostic_json = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'queued'
                """,
                (now, publication_id),
            )
            connection.execute(
                """
                INSERT INTO dataset_publication_attempts (
                    id,
                    publication_id,
                    ordinal,
                    status,
                    started_at
                )
                VALUES (?, ?, ?, 'running', ?)
                """,
                (attempt_id, publication_id, ordinal, now),
            )
            publication = self._dataset_publication(connection, publication_id)
            if publication is None:
                raise RuntimeError("Dataset Publication disappeared")
            attempt = publication["attempts"][-1]
            if not isinstance(attempt, dict):
                raise RuntimeError("Dataset Publication Attempt is invalid")
            return publication, attempt

    def prepare_dataset_publication_redelivery(
        self,
        publication_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = {
            "reason_code": "ACTIVITY_REDELIVERED",
            "message": "the prior Dataset Publication delivery ended before publication",
        }
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication(connection, publication_id)
            row = connection.execute(
                "SELECT status FROM dataset_publications WHERE id = ?",
                (publication_id,),
            ).fetchone()
            if row is None:
                raise KeyError(publication_id)
            if row["status"] == "running":
                connection.execute(
                    """
                    UPDATE dataset_publication_attempts
                    SET status = 'failed',
                        diagnostic_json = ?,
                        finished_at = ?
                    WHERE publication_id = ?
                      AND status = 'running'
                    """,
                    (
                        json.dumps(diagnostic, sort_keys=True, separators=(",", ":")),
                        now,
                        publication_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE dataset_publications
                    SET status = 'queued',
                        diagnostic_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(diagnostic, sort_keys=True, separators=(",", ":")),
                        now,
                        publication_id,
                    ),
                )
            publication = self._dataset_publication(connection, publication_id)
            if publication is None:
                raise KeyError(publication_id)
            return publication

    def finish_dataset_publication_attempt(
        self,
        *,
        publication_id: str,
        attempt_id: str,
        retryable: bool,
        diagnostic: dict[str, object],
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        next_status = "queued" if retryable else "failed"
        diagnostic_json = json.dumps(
            diagnostic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication(connection, publication_id)
            updated = connection.execute(
                """
                UPDATE dataset_publication_attempts
                SET status = 'failed',
                    diagnostic_json = ?,
                    finished_at = ?
                WHERE id = ?
                  AND publication_id = ?
                  AND status = 'running'
                """,
                (diagnostic_json, now, attempt_id, publication_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Dataset Publication Attempt fence failed")
            updated = connection.execute(
                """
                UPDATE dataset_publications
                SET status = ?,
                    diagnostic_json = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'running'
                """,
                (next_status, diagnostic_json, now, publication_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Dataset Publication fence failed")
            publication = self._dataset_publication(connection, publication_id)
            if publication is None:
                raise KeyError(publication_id)
            return publication

    def request_dataset_publication_cancellation(
        self,
        publication_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = {
            "reason_code": "CANCELLED",
            "message": "Dataset Publication was cancelled",
        }
        diagnostic_json = json.dumps(
            diagnostic,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication(connection, publication_id)
            connection.execute(
                """
                UPDATE dataset_publication_attempts
                SET status = 'cancelled',
                    diagnostic_json = ?,
                    finished_at = ?
                WHERE publication_id = ?
                  AND status = 'running'
                """,
                (diagnostic_json, now, publication_id),
            )
            connection.execute(
                """
                UPDATE dataset_publications
                SET status = 'cancelled',
                    diagnostic_json = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('queued', 'running')
                """,
                (diagnostic_json, now, publication_id),
            )
            publication = self._dataset_publication(connection, publication_id)
            if publication is None:
                raise KeyError(publication_id)
            return publication

    def cancel_dataset_publication(
        self,
        *,
        publication_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        del attempt_id
        return self.request_dataset_publication_cancellation(publication_id)

    def fail_dataset_publication_delivery(
        self,
        publication_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = {
            "reason_code": "ACTIVITY_DELIVERY_FAILED",
            "message": "Dataset Publication Activity delivery was exhausted",
        }
        diagnostic_json = json.dumps(
            diagnostic,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication(connection, publication_id)
            row = connection.execute(
                "SELECT status FROM dataset_publications WHERE id = ?",
                (publication_id,),
            ).fetchone()
            if row is None:
                raise KeyError(publication_id)
            if row["status"] not in {"succeeded", "failed", "cancelled"}:
                connection.execute(
                    """
                    UPDATE dataset_publication_attempts
                    SET status = 'failed',
                        diagnostic_json = ?,
                        finished_at = ?
                    WHERE publication_id = ?
                      AND status = 'running'
                    """,
                    (diagnostic_json, now, publication_id),
                )
                connection.execute(
                    """
                    UPDATE dataset_publications
                    SET status = 'failed',
                        diagnostic_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (diagnostic_json, now, publication_id),
                )
            publication = self._dataset_publication(connection, publication_id)
            if publication is None:
                raise KeyError(publication_id)
            return publication

    def fail_dataset_publication_resource_exhaustion(
        self,
        publication_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = {
            "reason_code": "RESOURCE_EXHAUSTED",
            "message": "accepted Data Worker resource envelope was exhausted",
        }
        diagnostic_json = json.dumps(
            diagnostic,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication(connection, publication_id)
            row = connection.execute(
                "SELECT status FROM dataset_publications WHERE id = ?",
                (publication_id,),
            ).fetchone()
            if row is None:
                raise KeyError(publication_id)
            if row["status"] not in {"succeeded", "failed", "cancelled"}:
                connection.execute(
                    """
                    UPDATE dataset_publication_attempts
                    SET status = 'failed',
                        diagnostic_json = ?,
                        finished_at = ?
                    WHERE publication_id = ?
                      AND status = 'running'
                    """,
                    (diagnostic_json, now, publication_id),
                )
                connection.execute(
                    """
                    UPDATE dataset_publications
                    SET status = 'failed',
                        diagnostic_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (diagnostic_json, now, publication_id),
                )
            publication = self._dataset_publication(connection, publication_id)
            if publication is None:
                raise KeyError(publication_id)
            return publication

    def publish_dataset_publication_success(
        self,
        *,
        publication_id: str,
        attempt_id: str,
        release: dict[str, object],
        idempotency_key: str,
        storage_objects: list[dict[str, object]],
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_dataset_publication(connection, publication_id)
            publication = connection.execute(
                """
                SELECT status
                FROM dataset_publications
                WHERE id = ?
                """,
                (publication_id,),
            ).fetchone()
            attempt = connection.execute(
                """
                SELECT status
                FROM dataset_publication_attempts
                WHERE id = ?
                  AND publication_id = ?
                """,
                (attempt_id, publication_id),
            ).fetchone()
            if (
                publication is None
                or publication["status"] != "running"
                or attempt is None
                or attempt["status"] != "running"
            ):
                return False
            if cancellation_requested is not None and cancellation_requested():
                diagnostic = {
                    "reason_code": "CANCELLED",
                    "message": "Dataset Publication was cancelled",
                }
                diagnostic_json = json.dumps(
                    diagnostic,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    """
                    UPDATE dataset_publication_attempts
                    SET status = 'cancelled',
                        diagnostic_json = ?,
                        finished_at = ?
                    WHERE id = ?
                      AND publication_id = ?
                      AND status = 'running'
                    """,
                    (
                        diagnostic_json,
                        now,
                        attempt_id,
                        publication_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE dataset_publications
                    SET status = 'cancelled',
                        diagnostic_json = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND status = 'running'
                    """,
                    (diagnostic_json, now, publication_id),
                )
                return False
            self.commit_platform_storage_references(
                connection,
                resource_kind="dataset_release",
                resource_id=str(release["id"]),
                objects=storage_objects,
            )
            committed_release, _created = self._publish_dataset_release(
                connection,
                release,
                idempotency_key,
            )
            updated_attempt = connection.execute(
                """
                UPDATE dataset_publication_attempts
                SET status = 'succeeded',
                    finished_at = ?
                WHERE id = ?
                  AND publication_id = ?
                  AND status = 'running'
                """,
                (now, attempt_id, publication_id),
            )
            if updated_attempt.rowcount != 1:
                raise RuntimeError("Dataset Publication Attempt fence failed")
            updated = connection.execute(
                """
                UPDATE dataset_publications
                SET status = 'succeeded',
                    result_release_id = ?,
                    result_manifest_sha256 = ?,
                    diagnostic_json = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'running'
                """,
                (
                    committed_release["id"],
                    committed_release["manifest_sha256"],
                    now,
                    publication_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Dataset Publication fence failed")
            return True

    def tracking_release_trigger(
        self,
        release_id: str,
    ) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT release_id, status, created_at
                FROM tracking_release_triggers
                WHERE release_id = ?
                """,
                (release_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def active_daily_track_refs(
        self,
        *,
        after_workspace_id: str | None = None,
        after_track_id: str | None = None,
        through_workspace_id: str | None = None,
        through_track_id: str | None = None,
        limit: int = 101,
    ) -> list[dict[str, str]]:
        bounded_limit = min(max(limit, 1), 101)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT 'local' AS workspace_id, id AS track_id
                FROM daily_tracks
                WHERE status = 'active'
                  AND (
                      ? IS NULL
                      OR 'local' > ?
                      OR ('local' = ? AND id > ?)
                  )
                  AND (
                      ? IS NULL
                      OR 'local' < ?
                      OR ('local' = ? AND id <= ?)
                  )
                ORDER BY id
                LIMIT ?
                """,
                (
                    after_workspace_id,
                    after_workspace_id,
                    after_workspace_id,
                    after_track_id,
                    through_workspace_id,
                    through_workspace_id,
                    through_workspace_id,
                    through_track_id,
                    bounded_limit,
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
                SELECT 'local' AS workspace_id, id AS track_id
                FROM daily_tracks
                WHERE status = 'active'
                ORDER BY id DESC
                LIMIT 1
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

    def enqueue_tracking_advance_execution(
        self,
        connection,
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
            ON CONFLICT(advance_id) DO NOTHING
            """,
            (
                f"outbox_{advance_id}",
                track_id,
                advance_id,
                created_at,
            ),
        )

    def _lock_dataset_publication_slot(self, connection) -> None:
        del connection

    def _lock_dataset_publication(
        self,
        connection,
        publication_id: str,
    ) -> None:
        del connection, publication_id

    def _lock_dataset_publication_request(
        self,
        connection,
        idempotency_key: str,
    ) -> None:
        del connection, idempotency_key

    @staticmethod
    def _dataset_publication(
        connection,
        publication_id: str,
    ) -> dict[str, object] | None:
        row = connection.execute(
            """
            SELECT
                id,
                request_version,
                kind,
                parameters_json,
                idempotency_key,
                trigger_kind,
                status,
                result_release_id,
                result_manifest_sha256,
                diagnostic_json,
                created_at,
                updated_at
            FROM dataset_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()
        if row is None:
            return None
        attempts = connection.execute(
            """
            SELECT
                id,
                publication_id,
                ordinal,
                status,
                diagnostic_json,
                started_at,
                finished_at
            FROM dataset_publication_attempts
            WHERE publication_id = ?
            ORDER BY ordinal
            """,
            (publication_id,),
        ).fetchall()
        return {
            **dict(row),
            "parameters": MetadataStore._decode_json(
                row["parameters_json"]
            ),
            "diagnostic": (
                None
                if row["diagnostic_json"] is None
                else MetadataStore._decode_json(row["diagnostic_json"])
            ),
            "attempts": [
                {
                    **dict(attempt),
                    "diagnostic": (
                        None
                        if attempt["diagnostic_json"] is None
                        else MetadataStore._decode_json(
                            attempt["diagnostic_json"]
                        )
                    ),
                }
                for attempt in attempts
            ],
        }

    @staticmethod
    def _decode_json(value: object) -> object:
        if isinstance(value, (dict, list)):
            return value
        return json.loads(str(value))

    def latest_dataset_release(self) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT release.manifest_json
                FROM dataset_release_pointer AS pointer
                JOIN dataset_releases AS release ON release.id = pointer.release_id
                WHERE pointer.singleton = 1
                """
            ).fetchone()
        if row is None or row["manifest_json"] is None:
            return None
        return dict(json.loads(str(row["manifest_json"])))

    def dataset_release(self, release_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM dataset_releases WHERE id = ?",
                (release_id,),
            ).fetchone()
        if row is None or row["manifest_json"] is None:
            return None
        return dict(json.loads(str(row["manifest_json"])))

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
                           json_extract(
                               manifest_json,
                               '$.predecessor_id'
                           ),
                           manifest_json
                    FROM dataset_releases
                    WHERE id = ?
                    UNION ALL
                    SELECT release.id,
                           json_extract(
                               release.manifest_json,
                               '$.predecessor_id'
                           ),
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

    def list_dataset_releases(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT manifest_json
                FROM dataset_releases
                ORDER BY created_at, id
                """
            ).fetchall()
        return [
            dict(json.loads(str(row["manifest_json"])))
            for row in rows
            if row["manifest_json"] is not None
        ]

    def dataset_release_for_idempotency_key(self, key: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT release.manifest_json
                FROM publication_idempotency AS request
                JOIN dataset_releases AS release ON release.id = request.release_id
                WHERE request.idempotency_key = ?
                """,
                (key,),
            ).fetchone()
        if row is None or row["manifest_json"] is None:
            return None
        return dict(json.loads(str(row["manifest_json"])))

    def publish_dataset_release(
        self,
        release: dict[str, object],
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._publish_dataset_release(
                connection,
                release,
                idempotency_key,
            )

    def publish_dataset_release_with_storage(
        self,
        release: dict[str, object],
        idempotency_key: str,
        storage_objects: list[dict[str, object]],
    ) -> tuple[dict[str, object], bool]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.commit_platform_storage_references(
                connection,
                resource_kind="dataset_release",
                resource_id=str(release["id"]),
                objects=storage_objects,
            )
            return self._publish_dataset_release(
                connection,
                release,
                idempotency_key,
            )

    @staticmethod
    def _publish_dataset_release(
        connection,
        release: dict[str, object],
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        existing = connection.execute(
            """
            SELECT release.manifest_json
            FROM publication_idempotency AS request
            JOIN dataset_releases AS release ON release.id = request.release_id
            WHERE request.idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if existing is not None and existing["manifest_json"] is not None:
            return dict(json.loads(str(existing["manifest_json"]))), False
        pointer = connection.execute(
            "SELECT release_id FROM dataset_release_pointer WHERE singleton = 1"
        ).fetchone()
        current_release_id = None if pointer is None else str(pointer["release_id"])
        expected_predecessor = release.get("predecessor_id")
        if current_release_id != expected_predecessor:
            raise DatasetPublicationConflict(
                "latest Dataset Release changed during publication"
            )
        release_id = str(release["id"])
        manifest_json = json.dumps(
            release,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute(
            """
            INSERT INTO dataset_releases (id, manifest_json, created_at)
            VALUES (?, ?, ?)
            """,
            (release_id, manifest_json, str(release["created_at"])),
        )
        connection.execute(
            """
            INSERT INTO dataset_release_pointer (singleton, release_id)
            VALUES (1, ?)
            ON CONFLICT(singleton) DO UPDATE SET release_id = excluded.release_id
            """,
            (release_id,),
        )
        connection.execute(
            """
            INSERT INTO publication_idempotency (idempotency_key, release_id)
            VALUES (?, ?)
            """,
            (idempotency_key, release_id),
        )
        connection.execute(
            """
            INSERT INTO tracking_release_triggers (
                release_id,
                status,
                created_at
            )
            VALUES (?, 'pending', ?)
            ON CONFLICT(release_id) DO NOTHING
            """,
            (release_id, str(release["created_at"])),
        )
        return release, True

    def last_worker_heartbeat(self) -> datetime | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT heartbeat_at FROM worker_heartbeat WHERE singleton = 1"
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(str(row["heartbeat_at"]))

    def record_worker_heartbeat(self, heartbeat_at: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO worker_heartbeat (singleton, heartbeat_at)
                VALUES (1, ?)
                ON CONFLICT(singleton) DO UPDATE SET heartbeat_at = excluded.heartbeat_at
                """,
                (heartbeat_at.astimezone(UTC).isoformat(),),
            )

    def create_research_draft(self, content: dict[str, object]) -> dict[str, object]:
        draft_id = f"def_{uuid4().hex[:20]}"
        now = datetime.now(UTC).isoformat()
        content_json = json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_definition_drafts (id, content_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (draft_id, content_json, now, now),
            )
        return {
            "id": draft_id,
            "state": "draft",
            "content": content,
            "created_at": now,
            "updated_at": now,
        }

    def update_research_draft(
        self, draft_id: str, content: dict[str, object]
    ) -> dict[str, object] | None:
        now = datetime.now(UTC).isoformat()
        content_json = json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self.connect() as connection:
            current = connection.execute(
                "SELECT created_at FROM research_definition_drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()
            if current is None:
                return None
            connection.execute(
                """
                UPDATE research_definition_drafts
                SET content_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (content_json, now, draft_id),
            )
        return {
            "id": draft_id,
            "state": "draft",
            "content": content,
            "created_at": str(current["created_at"]),
            "updated_at": now,
        }

    def research_draft(self, draft_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, content_json, created_at, updated_at
                FROM research_definition_drafts
                WHERE id = ?
                """,
                (draft_id,),
            ).fetchone()
        return self._draft_from_row(row)

    def list_research_drafts(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, content_json, created_at, updated_at
                FROM research_definition_drafts
                ORDER BY created_at, id
                """
            ).fetchall()
        return [draft for row in rows if (draft := self._draft_from_row(row)) is not None]

    def freeze_definition_and_create_run(
        self,
        *,
        draft_id: str,
        frozen_content: dict[str, object],
        content_hash: str,
        dataset_release_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, object], dict[str, object], bool]:
        with self.connect() as connection:
            self._lock_idempotent_admission(
                connection,
                operation="research_run",
                idempotency_key=idempotency_key,
            )
            existing = connection.execute(
                """
                SELECT run.id AS run_id, run.definition_version_id, run.dataset_release_id,
                       run.status, run.created_at, run.updated_at, run.started_at,
                       run.completed_at, run.result_bundle_id,
                       run.result_manifest_sha256, definition.draft_id, definition.version,
                       definition.content_json, definition.content_hash,
                       definition.created_at AS definition_created_at
                FROM research_run_idempotency AS request
                JOIN research_runs AS run ON run.id = request.run_id
                JOIN research_definitions AS definition
                  ON definition.id = run.definition_version_id
                WHERE request.idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                frozen, run = self._frozen_and_run_from_join(existing)
                return frozen, run, False
            version = (
                int(
                    connection.execute(
                        "SELECT COUNT(*) FROM research_definitions WHERE draft_id = ?",
                        (draft_id,),
                    ).fetchone()[0]
                )
                + 1
            )
            frozen_id = f"defv_{uuid4().hex[:20]}"
            run_id = f"run_{uuid4().hex[:20]}"
            now = datetime.now(UTC).isoformat()
            content_json = json.dumps(
                frozen_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            connection.execute(
                """
                INSERT INTO research_definitions
                    (id, draft_id, version, content_json, content_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (frozen_id, draft_id, version, content_json, content_hash, now),
            )
            connection.execute(
                """
                INSERT INTO research_runs
                    (id, definition_version_id, dataset_release_id, status, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (run_id, frozen_id, dataset_release_id, now, now),
            )
            self._admit_user_compute(
                connection,
                resource_kind="research_run",
                resource_id=run_id,
                admitted_at=now,
            )
            connection.execute(
                """
                INSERT INTO research_run_idempotency (idempotency_key, run_id)
                VALUES (?, ?)
                """,
                (idempotency_key, run_id),
            )
            self._enqueue_research_run(
                connection,
                run_id=run_id,
                created_at=now,
            )
        frozen = {
            "id": frozen_id,
            "draft_id": draft_id,
            "version": version,
            "state": "frozen",
            "content": frozen_content,
            "content_hash": content_hash,
            "created_at": now,
        }
        run = {
            "id": run_id,
            "definition_version_id": frozen_id,
            "dataset_release_id": dataset_release_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "result_bundle_id": None,
            "result_manifest_sha256": None,
        }
        return frozen, run, True

    def _enqueue_research_run(
        self,
        connection,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        """Hosted stores override this transaction hook to write the execution outbox."""
        del connection, run_id, created_at

    def _enqueue_research_run_cancellation(
        self,
        connection,
        *,
        run_id: str,
        created_at: str,
    ) -> None:
        """Hosted stores override this transaction hook to deliver cancellation."""
        del connection, run_id, created_at

    def _enqueue_tracking_operation(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        created_at: str,
    ) -> None:
        """Hosted stores override this hook to deliver Tracking operations."""
        del connection, resource_kind, resource_id, created_at

    @staticmethod
    def bind_tracking_generation_rebuild(
        connection,
        *,
        rebuild_id: str,
        track_id: str,
        basis_generation_id: str,
        basis_head_checkpoint_id: str,
        generation_id: str,
        advance_id: str,
        updated_at: str,
    ) -> None:
        updated = connection.execute(
            """
            UPDATE tracking_generation_rebuilds
            SET generation_id = ?, advance_id = ?, updated_at = ?
            WHERE id = ?
              AND daily_track_id = ?
              AND basis_generation_id = ?
              AND basis_head_checkpoint_id = ?
              AND status = 'running'
            """,
            (
                generation_id,
                advance_id,
                updated_at,
                rebuild_id,
                track_id,
                basis_generation_id,
                basis_head_checkpoint_id,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError(
                "Tracking Generation rebuild binding was fenced"
            )

    def _admit_user_compute(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        admitted_at: str,
    ) -> None:
        """Hosted stores override this transaction hook to enforce Compute quota."""
        del connection, resource_kind, resource_id, admitted_at

    def commit_private_storage_references(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int:
        return self._commit_storage_references(
            connection,
            owner_scope="workspace",
            workspace_id="local",
            resource_kind=resource_kind,
            resource_id=resource_id,
            objects=objects,
        )

    @contextmanager
    def storage_mutation_fence(self) -> Iterator[None]:
        path = self.path.with_suffix(f"{self.path.suffix}.storage.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def commit_platform_storage_references(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int:
        return self._commit_storage_references(
            connection,
            owner_scope="platform",
            workspace_id=None,
            resource_kind=resource_kind,
            resource_id=resource_id,
            objects=objects,
        )

    @staticmethod
    def _commit_storage_references(
        connection,
        *,
        owner_scope: str,
        workspace_id: str | None,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int:
        now = datetime.now(UTC).isoformat()
        for value in objects:
            connection.execute(
                """
                INSERT INTO stored_objects (
                    object_key, sha256, compressed_bytes,
                    object_kind, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(object_key) DO NOTHING
                """,
                (
                    value["object_key"],
                    value["sha256"],
                    int(value["bytes"]),
                    value["kind"],
                    now,
                ),
            )
            stored = connection.execute(
                """
                SELECT sha256, compressed_bytes, object_kind
                FROM stored_objects
                WHERE object_key = ?
                """,
                (value["object_key"],),
            ).fetchone()
            if (
                stored is None
                or stored["sha256"] != value["sha256"]
                or int(stored["compressed_bytes"]) != int(value["bytes"])
                or stored["object_kind"] != value["kind"]
            ):
                raise RuntimeError(
                    "Stored object identity conflicts with byte accounting"
                )
            connection.execute(
                """
                INSERT INTO storage_references (
                    owner_scope, workspace_id, resource_kind,
                    resource_id, object_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    owner_scope,
                    workspace_id,
                    resource_kind,
                    resource_id,
                    value["object_key"],
                    now,
                ),
            )
        row = connection.execute(
            """
            SELECT COALESCE(sum(stored.compressed_bytes), 0) AS used_bytes
            FROM stored_objects AS stored
            WHERE EXISTS (
                SELECT 1
                FROM storage_references AS reference
                WHERE reference.owner_scope = ?
                  AND reference.workspace_id IS ?
                  AND reference.object_key = stored.object_key
            )
            """,
            (owner_scope, workspace_id),
        ).fetchone()
        return 0 if row is None else int(row["used_bytes"])

    def request_resource_deletion(
        self,
        *,
        resource_kind: str,
        resource_id: str,
        actor: str,
        deleted_at: str,
    ) -> dict[str, object] | None:
        if resource_kind not in {"research_run", "daily_track"}:
            raise ValueError("unsupported private resource kind")
        tombstone_id = f"tombstone_{uuid4().hex}"
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if resource_kind == "research_run":
                row = connection.execute(
                    """
                    SELECT status, result_bundle_id,
                           result_manifest_sha256
                    FROM research_runs
                    WHERE id = ?
                    """,
                    (resource_id,),
                ).fetchone()
                if row is None:
                    return None
                if row["status"] not in {"succeeded", "failed", "cancelled"}:
                    raise ValueError("RESOURCE_NOT_TERMINAL")
                retained = connection.execute(
                    "SELECT 1 FROM daily_tracks WHERE seed_run_id = ? LIMIT 1",
                    (resource_id,),
                ).fetchone()
                if retained is not None:
                    raise ValueError("RESOURCE_RETAINED")
                if row["result_bundle_id"] is not None:
                    indexed = connection.execute(
                        """
                        SELECT 1
                        FROM storage_references
                        WHERE owner_scope = 'workspace'
                          AND workspace_id = 'local'
                          AND resource_kind = 'research_run'
                          AND resource_id = ?
                        LIMIT 1
                        """,
                        (resource_id,),
                    ).fetchone()
                    if indexed is None:
                        raise ValueError("RESOURCE_STORAGE_UNINDEXED")
                manifest_sha256 = row["result_manifest_sha256"]
                fencing_token = None
                daily_track_id = None
            else:
                row = connection.execute(
                    """
                    SELECT track.status, track.fencing_token,
                           checkpoint.manifest_sha256
                    FROM daily_tracks AS track
                    LEFT JOIN tracking_checkpoints AS checkpoint
                      ON checkpoint.id = track.head_checkpoint_id
                    WHERE track.id = ?
                    """,
                    (resource_id,),
                ).fetchone()
                if row is None:
                    return None
                if row["status"] != "stopped":
                    raise ValueError("RESOURCE_NOT_TERMINAL")
                unindexed = connection.execute(
                    """
                    SELECT 1
                    FROM tracking_checkpoints AS checkpoint
                    WHERE checkpoint.daily_track_id = ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM storage_references AS reference
                          WHERE reference.owner_scope = 'workspace'
                            AND reference.workspace_id = 'local'
                            AND reference.resource_kind = 'tracking_checkpoint'
                            AND reference.resource_id = checkpoint.id
                      )
                    LIMIT 1
                    """,
                    (resource_id,),
                ).fetchone()
                if unindexed is not None:
                    raise ValueError("RESOURCE_STORAGE_UNINDEXED")
                manifest_sha256 = row["manifest_sha256"]
                fencing_token = int(row["fencing_token"])
                daily_track_id = resource_id

            connection.execute(
                """
                INSERT INTO resource_tombstones (
                    id, workspace_id, resource_kind, resource_id,
                    authoritative_manifest_sha256, actor, deleted_at
                ) VALUES (?, 'local', ?, ?, ?, ?, ?)
                """,
                (
                    tombstone_id,
                    resource_kind,
                    resource_id,
                    manifest_sha256,
                    actor,
                    deleted_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO resource_cleanup_jobs (
                    tombstone_id, daily_track_id, fencing_token, status
                ) VALUES (?, ?, ?, 'pending')
                """,
                (tombstone_id, daily_track_id, fencing_token),
            )

            if resource_kind == "research_run":
                self._move_storage_references(
                    connection,
                    tombstone_id=tombstone_id,
                    resource_kind="research_run",
                    resource_ids=[resource_id],
                    deleted_at=deleted_at,
                )
                connection.execute(
                    "DELETE FROM research_run_attempts WHERE run_id = ?",
                    (resource_id,),
                )
                connection.execute(
                    "DELETE FROM research_run_idempotency WHERE run_id = ?",
                    (resource_id,),
                )
                connection.execute(
                    """
                    DELETE FROM daily_track_activation_reservations
                    WHERE seed_run_id = ?
                    """,
                    (resource_id,),
                )
                connection.execute(
                    "DELETE FROM research_runs WHERE id = ?",
                    (resource_id,),
                )
            else:
                checkpoint_ids = [
                    str(value["id"])
                    for value in connection.execute(
                        """
                        SELECT id FROM tracking_checkpoints
                        WHERE daily_track_id = ?
                        """,
                        (resource_id,),
                    ).fetchall()
                ]
                self._move_storage_references(
                    connection,
                    tombstone_id=tombstone_id,
                    resource_kind="tracking_checkpoint",
                    resource_ids=checkpoint_ids,
                    deleted_at=deleted_at,
                )
                connection.execute(
                    "DELETE FROM tracking_execution_outbox WHERE daily_track_id = ?",
                    (resource_id,),
                )
                connection.execute(
                    """
                    DELETE FROM tracking_advance_attempts
                    WHERE advance_id IN (
                        SELECT id FROM tracking_advances
                        WHERE daily_track_id = ?
                    )
                    """,
                    (resource_id,),
                )
                for table in (
                    "tracking_equivalence_requests",
                    "tracking_generation_rebuilds",
                    "tracking_advances",
                    "tracking_checkpoints",
                    "tracking_generations",
                ):
                    connection.execute(
                        f"DELETE FROM {table} WHERE daily_track_id = ?",
                        (resource_id,),
                    )
                connection.execute(
                    """
                    DELETE FROM daily_track_activation_idempotency
                    WHERE daily_track_id = ?
                    """,
                    (resource_id,),
                )
                connection.execute(
                    "DELETE FROM working_cache_deletions WHERE daily_track_id = ?",
                    (resource_id,),
                )
                connection.execute(
                    "DELETE FROM daily_tracks WHERE id = ?",
                    (resource_id,),
                )

        return {
            "id": tombstone_id,
            "workspace_id": "local",
            "resource_kind": resource_kind,
            "resource_id": resource_id,
            "authoritative_manifest_sha256": manifest_sha256,
            "actor": actor,
            "deleted_at": deleted_at,
        }

    @staticmethod
    def _move_storage_references(
        connection,
        *,
        tombstone_id: str,
        resource_kind: str,
        resource_ids: list[str],
        deleted_at: str,
    ) -> None:
        for resource_id in resource_ids:
            connection.execute(
                """
                INSERT INTO storage_references (
                    owner_scope, workspace_id, resource_kind,
                    resource_id, object_key, created_at
                )
                SELECT DISTINCT owner_scope, workspace_id,
                       'resource_tombstone', ?, object_key, ?
                FROM storage_references
                WHERE owner_scope = 'workspace'
                  AND workspace_id = 'local'
                  AND resource_kind = ?
                  AND resource_id = ?
                ON CONFLICT DO NOTHING
                """,
                (
                    tombstone_id,
                    deleted_at,
                    resource_kind,
                    resource_id,
                ),
            )
            connection.execute(
                """
                DELETE FROM storage_references
                WHERE owner_scope = 'workspace'
                  AND workspace_id = 'local'
                  AND resource_kind = ?
                  AND resource_id = ?
                """,
                (resource_kind, resource_id),
            )

    def pending_resource_cleanups(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT job.tombstone_id, tombstone.resource_kind,
                       tombstone.resource_id, job.daily_track_id,
                       job.fencing_token, job.attempt_count,
                       job.last_error
                FROM resource_cleanup_jobs AS job
                JOIN resource_tombstones AS tombstone
                  ON tombstone.id = job.tombstone_id
                WHERE job.status = 'pending'
                ORDER BY tombstone.deleted_at, job.tombstone_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def resource_cleanup_candidates(self, tombstone_id: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT own.object_key
                FROM storage_references AS own
                WHERE own.owner_scope = 'workspace'
                  AND own.workspace_id = 'local'
                  AND own.resource_kind = 'resource_tombstone'
                  AND own.resource_id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM storage_references AS retained
                      WHERE retained.object_key = own.object_key
                        AND NOT (
                            retained.owner_scope = own.owner_scope
                            AND retained.workspace_id = own.workspace_id
                            AND retained.resource_kind = own.resource_kind
                            AND retained.resource_id = own.resource_id
                        )
                  )
                ORDER BY own.object_key
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
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM storage_references
                WHERE owner_scope = 'workspace'
                  AND workspace_id = 'local'
                  AND resource_kind = 'resource_tombstone'
                  AND resource_id = ?
                """,
                (tombstone_id,),
            )
            connection.execute(
                """
                DELETE FROM stored_objects
                WHERE NOT EXISTS (
                    SELECT 1 FROM storage_references
                    WHERE storage_references.object_key = stored_objects.object_key
                )
                """
            )
            connection.execute(
                """
                UPDATE resource_cleanup_jobs
                SET status = 'completed', attempt_count = attempt_count + 1,
                    completed_at = ?, last_error = NULL
                WHERE tombstone_id = ? AND status = 'pending'
                """,
                (completed_at, tombstone_id),
            )

    def fail_resource_cleanup(
        self,
        tombstone_id: str,
        error: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE resource_cleanup_jobs
                SET attempt_count = attempt_count + 1,
                    last_error = ?
                WHERE tombstone_id = ? AND status = 'pending'
                """,
                (error, tombstone_id),
            )

    def _lock_idempotent_admission(
        self,
        connection,
        *,
        operation: str,
        idempotency_key: str,
    ) -> None:
        """Hosted stores override this transaction hook to serialize request retries."""
        del connection, operation, idempotency_key

    def _complete_user_compute(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        completed_at: str,
    ) -> None:
        """Hosted stores override this transaction hook to release Compute quota."""
        del connection, resource_kind, resource_id, completed_at

    @staticmethod
    def _lock_research_run(connection, run_id: str):
        lock_research_run = getattr(connection, "lock_research_run", None)
        if callable(lock_research_run):
            return lock_research_run(run_id)
        return connection.execute(
            "SELECT status FROM research_runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    def _transition_research_run(
        self,
        connection,
        *,
        run_id: str,
        allowed_statuses: set[str],
        next_status: str,
        attempt_status: str,
        diagnostic_json: str,
        now: str,
        attempt_id: str | None = None,
    ) -> bool:
        run = self._lock_research_run(connection, run_id)
        if run is None:
            raise KeyError(run_id)
        current_status = str(run["status"])
        if attempt_id is not None:
            attempt = connection.execute(
                """
                SELECT id
                FROM research_run_attempts
                WHERE id = ? AND run_id = ?
                """,
                (attempt_id, run_id),
            ).fetchone()
            if attempt is None:
                raise KeyError(attempt_id)
        if current_status not in allowed_statuses:
            return False
        attempt_filter = "" if attempt_id is None else " AND id = ?"
        attempt_parameters: tuple[object, ...] = (
            attempt_status,
            now,
            now,
            diagnostic_json,
            run_id,
        )
        if attempt_id is not None:
            attempt_parameters += (attempt_id,)
        connection.execute(
            f"""
            UPDATE research_run_attempts
            SET status = ?, completed_at = ?, heartbeat_at = ?,
                diagnostic_json = ?
            WHERE run_id = ? AND status = 'running'
              {attempt_filter}
            """,
            attempt_parameters,
        )
        updated = connection.execute(
            """
            UPDATE research_runs
            SET status = ?, updated_at = ?, completed_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                next_status,
                now,
                None if next_status == "queued" else now,
                run_id,
                current_status,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("ResearchRun transition fence failed")
        if next_status in {"succeeded", "failed", "cancelled"}:
            self._complete_user_compute(
                connection,
                resource_kind="research_run",
                resource_id=run_id,
                completed_at=now,
            )
        return True

    def frozen_research_definition(self, version_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, draft_id, version, content_json, content_hash, created_at
                FROM research_definitions
                WHERE id = ?
                """,
                (version_id,),
            ).fetchone()
        if row is None or row["content_json"] is None:
            return None
        return {
            "id": str(row["id"]),
            "draft_id": str(row["draft_id"]),
            "version": int(row["version"]),
            "state": "frozen",
            "content": json.loads(str(row["content_json"])),
            "content_hash": str(row["content_hash"]),
            "created_at": str(row["created_at"]),
        }

    def list_frozen_research_definitions(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM research_definitions
                ORDER BY created_at, id
                """
            ).fetchall()
        return [
            frozen
            for row in rows
            if (frozen := self.frozen_research_definition(str(row["id"]))) is not None
        ]

    def research_run(self, run_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, definition_version_id, dataset_release_id, status,
                       created_at, updated_at, started_at, completed_at,
                       result_bundle_id, result_manifest_sha256
                FROM research_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            attempts = connection.execute(
                """
                SELECT id, run_id, ordinal, status, started_at, heartbeat_at,
                       completed_at, diagnostic_json
                FROM research_run_attempts
                WHERE run_id = ?
                ORDER BY ordinal
                """,
                (run_id,),
            ).fetchall()
        run = self._run_from_row(row)
        run["attempts"] = [self._attempt_from_row(attempt) for attempt in attempts]
        return run

    def list_research_runs(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM research_runs
                ORDER BY created_at, id
                """
            ).fetchall()
        return [run for row in rows if (run := self.research_run(str(row["id"]))) is not None]

    def next_queued_research_run_id(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM research_runs
                WHERE status = 'queued'
                ORDER BY created_at, id
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else str(row["id"])

    def recover_abandoned_research_runs(
        self,
        *,
        stale_after_seconds: int,
    ) -> list[str]:
        cutoff = (datetime.now(UTC) - timedelta(seconds=stale_after_seconds)).isoformat()
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {
                "reason_code": "ABANDONED_ATTEMPT",
                "message": "worker heartbeat expired before publication",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT attempt.id, attempt.run_id
                FROM research_run_attempts AS attempt
                JOIN research_runs AS run ON run.id = attempt.run_id
                WHERE attempt.status = 'running'
                  AND run.status = 'running'
                  AND attempt.heartbeat_at < ?
                ORDER BY attempt.started_at, attempt.id
                """,
                (cutoff,),
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in rows]
            for row in rows:
                connection.execute(
                    """
                    UPDATE research_run_attempts
                    SET status = 'failed', completed_at = ?,
                        diagnostic_json = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, diagnostic, str(row["id"])),
                )
                connection.execute(
                    """
                    UPDATE research_runs
                    SET status = 'queued', updated_at = ?, completed_at = NULL
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, str(row["run_id"])),
                )
        return run_ids

    def prepare_research_run_redelivery(self, run_id: str) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {
                "reason_code": "ACTIVITY_REDELIVERED",
                "message": "the prior Activity delivery ended before publication",
                "correlation_id": run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._transition_research_run(
                connection,
                run_id=run_id,
                allowed_statuses={"running"},
                next_status="queued",
                attempt_status="failed",
                diagnostic_json=diagnostic,
                now=now,
            )
        recovered = self.research_run(run_id)
        if recovered is None:
            raise KeyError(run_id)
        return recovered

    def fail_research_run_delivery(self, run_id: str) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {
                "reason_code": "ACTIVITY_DELIVERY_FAILED",
                "message": "research execution could not be delivered",
                "correlation_id": run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._transition_research_run(
                connection,
                run_id=run_id,
                allowed_statuses={"queued", "running"},
                next_status="failed",
                attempt_status="failed",
                diagnostic_json=diagnostic,
                now=now,
            )
        failed = self.research_run(run_id)
        if failed is None:
            raise KeyError(run_id)
        return failed

    def claim_research_run(
        self,
        run_id: str,
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._lock_research_run(connection, run_id)
            if row is None:
                raise KeyError(run_id)
            if row["status"] != "queued":
                return None
            ordinal = (
                int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(ordinal), 0)
                        FROM research_run_attempts
                        WHERE run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()[0]
                )
                + 1
            )
            attempt_id = f"attempt_{uuid4().hex[:20]}"
            connection.execute(
                """
                UPDATE research_runs
                SET status = 'running',
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, run_id),
            )
            connection.execute(
                """
                INSERT INTO research_run_attempts
                    (id, run_id, ordinal, status, started_at, heartbeat_at)
                VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (attempt_id, run_id, ordinal, now, now),
            )
        run = self.research_run(run_id)
        if run is None:
            raise RuntimeError("claimed ResearchRun disappeared")
        return run, dict(run["attempts"][-1])

    def finish_research_run_attempt(
        self,
        *,
        run_id: str,
        attempt_id: str,
        retryable: bool,
        diagnostic: dict[str, object],
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic_json = json.dumps(
            diagnostic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._transition_research_run(
                connection,
                run_id=run_id,
                allowed_statuses={"running"},
                next_status="queued" if retryable else "failed",
                attempt_status="failed",
                diagnostic_json=diagnostic_json,
                now=now,
                attempt_id=attempt_id,
            )
        run = self.research_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def publish_research_run_success(
        self,
        *,
        run_id: str,
        attempt_id: str,
        result_bundle_id: str,
        result_manifest_sha256: str,
        storage_objects: list[dict[str, object]],
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._lock_research_run(connection, run_id)
            attempt = connection.execute(
                "SELECT status FROM research_run_attempts WHERE id = ? AND run_id = ?",
                (attempt_id, run_id),
            ).fetchone()
            if (
                run is None
                or attempt is None
                or run["status"] != "running"
                or attempt["status"] != "running"
            ):
                return False
            self.commit_private_storage_references(
                connection,
                resource_kind="research_run",
                resource_id=run_id,
                objects=storage_objects,
            )
            run_update = connection.execute(
                """
                UPDATE research_runs
                SET status = 'succeeded', updated_at = ?, completed_at = ?,
                    result_bundle_id = ?, result_manifest_sha256 = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    now,
                    now,
                    result_bundle_id,
                    result_manifest_sha256,
                    run_id,
                ),
            )
            if run_update.rowcount != 1:
                return False
            attempt_update = connection.execute(
                """
                UPDATE research_run_attempts
                SET status = 'succeeded', completed_at = ?, heartbeat_at = ?
                WHERE id = ? AND run_id = ? AND status = 'running'
                """,
                (now, now, attempt_id, run_id),
            )
            if attempt_update.rowcount != 1:
                raise RuntimeError("ResearchRun Attempt publication fence failed")
            self._complete_user_compute(
                connection,
                resource_kind="research_run",
                resource_id=run_id,
                completed_at=now,
            )
        return True

    def cancel_research_run(self, run_id: str) -> dict[str, object] | None:
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {"reason_code": "CANCELLED", "message": "cancelled by user"},
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                transitioned = self._transition_research_run(
                    connection,
                    run_id=run_id,
                    allowed_statuses={"queued", "running"},
                    next_status="cancelled",
                    attempt_status="cancelled",
                    diagnostic_json=diagnostic,
                    now=now,
                )
            except KeyError:
                return None
            if transitioned:
                self._enqueue_research_run_cancellation(
                    connection,
                    run_id=run_id,
                    created_at=now,
                )
        return self.research_run(run_id)

    def acknowledge_research_run_cancellation(
        self,
        *,
        run_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {"reason_code": "CANCELLED", "message": "execution was cancelled"},
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._transition_research_run(
                connection,
                run_id=run_id,
                allowed_statuses={"queued", "running"},
                next_status="cancelled",
                attempt_status="cancelled",
                diagnostic_json=diagnostic,
                now=now,
                attempt_id=attempt_id,
            )
        cancelled = self.research_run(run_id)
        if cancelled is None:
            raise KeyError(run_id)
        return cancelled

    def create_research_rerun(
        self,
        source_run_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lock_idempotent_admission(
                connection,
                operation="research_run",
                idempotency_key=idempotency_key,
            )
            existing = connection.execute(
                """
                SELECT run.id, run.definition_version_id, run.dataset_release_id,
                       run.status, run.created_at, run.updated_at, run.started_at,
                       run.completed_at, run.result_bundle_id,
                       run.result_manifest_sha256
                FROM research_run_idempotency AS request
                JOIN research_runs AS run ON run.id = request.run_id
                WHERE request.idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return self._run_from_row(existing), False
            source = connection.execute(
                """
                SELECT definition_version_id, dataset_release_id
                FROM research_runs
                WHERE id = ?
                """,
                (source_run_id,),
            ).fetchone()
            if source is None:
                raise KeyError(source_run_id)
            run_id = f"run_{uuid4().hex[:20]}"
            connection.execute(
                """
                INSERT INTO research_runs
                    (id, definition_version_id, dataset_release_id, status,
                     created_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (
                    run_id,
                    str(source["definition_version_id"]),
                    str(source["dataset_release_id"]),
                    now,
                    now,
                ),
            )
            self._admit_user_compute(
                connection,
                resource_kind="research_run",
                resource_id=run_id,
                admitted_at=now,
            )
            connection.execute(
                """
                INSERT INTO research_run_idempotency (idempotency_key, run_id)
                VALUES (?, ?)
                """,
                (idempotency_key, run_id),
            )
            self._enqueue_research_run(
                connection,
                run_id=run_id,
                created_at=now,
            )
        run = self.research_run(run_id)
        if run is None:
            raise RuntimeError("created ResearchRun disappeared")
        return run, True

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _draft_from_row(row: sqlite3.Row | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "state": "draft",
            "content": json.loads(str(row["content_json"])),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _frozen_and_run_from_join(
        row: sqlite3.Row,
    ) -> tuple[dict[str, object], dict[str, object]]:
        frozen = {
            "id": str(row["definition_version_id"]),
            "draft_id": str(row["draft_id"]),
            "version": int(row["version"]),
            "state": "frozen",
            "content": json.loads(str(row["content_json"])),
            "content_hash": str(row["content_hash"]),
            "created_at": str(row["definition_created_at"]),
        }
        run = {
            "id": str(row["run_id"]),
            "definition_version_id": str(row["definition_version_id"]),
            "dataset_release_id": str(row["dataset_release_id"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"] or row["created_at"]),
            "started_at": (str(row["started_at"]) if row["started_at"] is not None else None),
            "completed_at": (str(row["completed_at"]) if row["completed_at"] is not None else None),
            "result_bundle_id": (
                str(row["result_bundle_id"]) if row["result_bundle_id"] is not None else None
            ),
            "result_manifest_sha256": (
                str(row["result_manifest_sha256"])
                if row["result_manifest_sha256"] is not None
                else None
            ),
        }
        return frozen, run

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": str(row["id"]),
            "definition_version_id": str(row["definition_version_id"]),
            "dataset_release_id": str(row["dataset_release_id"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"] or row["created_at"]),
            "started_at": (str(row["started_at"]) if row["started_at"] is not None else None),
            "completed_at": (str(row["completed_at"]) if row["completed_at"] is not None else None),
            "result_bundle_id": (
                str(row["result_bundle_id"]) if row["result_bundle_id"] is not None else None
            ),
            "result_manifest_sha256": (
                str(row["result_manifest_sha256"])
                if row["result_manifest_sha256"] is not None
                else None
            ),
        }

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "ordinal": int(row["ordinal"]),
            "status": str(row["status"]),
            "started_at": str(row["started_at"]),
            "heartbeat_at": str(row["heartbeat_at"]),
            "completed_at": (str(row["completed_at"]) if row["completed_at"] is not None else None),
            "diagnostic": (
                json.loads(str(row["diagnostic_json"]))
                if row["diagnostic_json"] is not None
                else None
            ),
        }

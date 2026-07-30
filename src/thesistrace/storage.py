import json
import sqlite3
from collections.abc import Iterator
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
                    status TEXT NOT NULL,
                    checkpoint_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(daily_track_id, generation_id, target_dataset_release_id)
                );

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

                CREATE TABLE IF NOT EXISTS working_cache_deletions (
                    daily_track_id TEXT PRIMARY KEY REFERENCES daily_tracks(id),
                    fencing_token INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    requested_at TEXT NOT NULL,
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

    def installation_id(self) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT installation_id FROM workspace WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("workspace metadata is not initialized")
        return str(row["installation_id"])

    def resource_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in RESOURCE_TABLES
            }

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
        release_id = str(release["id"])
        manifest_json = json.dumps(
            release, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            connection.execute(
                """
                INSERT INTO research_run_idempotency (idempotency_key, run_id)
                VALUES (?, ?)
                """,
                (idempotency_key, run_id),
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

    def claim_research_run(
        self,
        run_id: str,
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM research_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
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
            attempt = connection.execute(
                """
                SELECT status
                FROM research_run_attempts
                WHERE id = ? AND run_id = ?
                """,
                (attempt_id, run_id),
            ).fetchone()
            if attempt is None:
                raise KeyError(attempt_id)
            if attempt["status"] == "running":
                connection.execute(
                    """
                    UPDATE research_run_attempts
                    SET status = 'failed', completed_at = ?, heartbeat_at = ?,
                        diagnostic_json = ?
                    WHERE id = ?
                    """,
                    (now, now, diagnostic_json, attempt_id),
                )
                next_status = "queued" if retryable else "failed"
                connection.execute(
                    """
                    UPDATE research_runs
                    SET status = ?, updated_at = ?,
                        completed_at = CASE WHEN ? = 'failed' THEN ? ELSE NULL END
                    WHERE id = ? AND status = 'running'
                    """,
                    (next_status, now, next_status, now, run_id),
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
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT status FROM research_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
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
            connection.execute(
                """
                UPDATE research_run_attempts
                SET status = 'succeeded', completed_at = ?, heartbeat_at = ?
                WHERE id = ?
                """,
                (now, now, attempt_id),
            )
            connection.execute(
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
        return True

    def cancel_research_run(self, run_id: str) -> dict[str, object] | None:
        now = datetime.now(UTC).isoformat()
        diagnostic = json.dumps(
            {"reason_code": "CANCELLED", "message": "cancelled by operator"},
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM research_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] in {"queued", "running"}:
                connection.execute(
                    """
                    UPDATE research_runs
                    SET status = 'cancelled', updated_at = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (now, now, run_id),
                )
                connection.execute(
                    """
                    UPDATE research_run_attempts
                    SET status = 'cancelled', completed_at = ?, heartbeat_at = ?,
                        diagnostic_json = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (now, now, diagnostic, run_id),
                )
        return self.research_run(run_id)

    def create_research_rerun(
        self,
        source_run_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            connection.execute(
                """
                INSERT INTO research_run_idempotency (idempotency_key, run_id)
                VALUES (?, ?)
                """,
                (idempotency_key, run_id),
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

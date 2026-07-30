import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

RESOURCE_TABLES = (
    "dataset_releases",
    "research_definitions",
    "research_runs",
    "daily_tracks",
)


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

                CREATE TABLE IF NOT EXISTS daily_tracks (
                    id TEXT PRIMARY KEY
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
            ):
                self._ensure_column(connection, "research_runs", column, definition)

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

    def publish_dataset_release(self, release: dict[str, object], idempotency_key: str) -> None:
        release_id = str(release["id"])
        manifest_json = json.dumps(
            release, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self.connect() as connection:
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
                       run.status, run.created_at, definition.draft_id, definition.version,
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
                    (id, definition_version_id, dataset_release_id, status, created_at)
                VALUES (?, ?, ?, 'queued', ?)
                """,
                (run_id, frozen_id, dataset_release_id, now),
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
        }
        return frozen, run

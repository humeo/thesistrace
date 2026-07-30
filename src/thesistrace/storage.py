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
                    id TEXT PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS research_runs (
                    id TEXT PRIMARY KEY
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

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

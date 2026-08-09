from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from psycopg.errors import UniqueViolation

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.head_store import DatasetHead, MountedDatasetHeadStore

_LIFECYCLE_LOCK = "thesistrace-mounted-data-lifecycle"
_OWNER_KINDS = {"research_run_attempt", "tracking_advance_attempt"}


class DataLifecycleError(RuntimeError):
    pass


class DataNotReady(DataLifecycleError):
    pass


@dataclass(frozen=True)
class GenerationPin:
    id: str
    owner_kind: str
    owner_id: str
    generation_manifest_sha256: str
    status: str
    lease_expires_at: datetime
    heartbeat_at: datetime


@dataclass(frozen=True)
class GenerationRetention:
    head_generation_manifest_sha256: str | None
    active_pin_generations: frozenset[str]
    live_candidate_generations: frozenset[str]

    @property
    def all_generations(self) -> frozenset[str]:
        head = (
            frozenset()
            if self.head_generation_manifest_sha256 is None
            else frozenset({self.head_generation_manifest_sha256})
        )
        return head | self.active_pin_generations | self.live_candidate_generations


class DatasetLifecycle:
    """The shared PostgreSQL fence for mounted Head and Generation retention state."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._database = database
        self._heads = MountedDatasetHeadStore(mount_root)

    def current_head(self) -> DatasetHead | None:
        for _ in range(4):
            with self._database.transaction() as transaction:
                _lock(transaction)
                pointer = self._heads.current_pointer()
            if pointer is None:
                return None
            try:
                resolved = self._heads.resolve(pointer)
            except RuntimeError:
                with self._database.transaction() as transaction:
                    _lock(transaction)
                    if self._heads.current_pointer() == pointer:
                        raise
                continue
            with self._database.transaction() as transaction:
                _lock(transaction)
                if self._heads.current_pointer() == pointer:
                    return resolved
        raise DataLifecycleError("Dataset Head changed repeatedly during inspection")

    def protect_candidate(
        self,
        *,
        operation_id: str,
        generation_manifest_sha256: str,
        lease_seconds: float,
    ) -> None:
        _require_identity(operation_id, "candidate operation")
        _require_lease(lease_seconds)
        with self._database.transaction() as transaction:
            _lock(transaction)
            row = transaction.execute(
                """
                SELECT generation_manifest_sha256, status
                FROM data.generation_candidates
                WHERE operation_id = %s
                FOR UPDATE
                """,
                (operation_id,),
            ).fetchone()
            if row is None:
                transaction.execute(
                    """
                    INSERT INTO data.generation_candidates (
                        operation_id, generation_manifest_sha256, status, lease_expires_at
                    ) VALUES (%s, %s, 'live', now() + make_interval(secs => %s))
                    """,
                    (operation_id, generation_manifest_sha256, lease_seconds),
                )
                return
            if row != {
                "generation_manifest_sha256": generation_manifest_sha256,
                "status": "live",
            }:
                raise DataLifecycleError("candidate operation identity conflicts")
            transaction.execute(
                """
                UPDATE data.generation_candidates
                SET lease_expires_at = now() + make_interval(secs => %s), updated_at = now()
                WHERE operation_id = %s AND status = 'live'
                """,
                (lease_seconds, operation_id),
            )
        try:
            self._heads.open_generation(generation_manifest_sha256)
        except RuntimeError:
            self.release_candidate(operation_id=operation_id)
            raise

    def compare_and_swap_head(
        self,
        *,
        expected_generation_manifest_sha256: str | None,
        candidate_generation_manifest_sha256: str,
        operation_id: str,
    ) -> DatasetHead:
        resolved_candidate = self._heads.open_generation(candidate_generation_manifest_sha256)
        with self._database.transaction() as transaction:
            _lock(transaction)
            candidate = transaction.execute(
                """
                SELECT generation_manifest_sha256, status
                FROM data.generation_candidates
                WHERE operation_id = %s
                FOR UPDATE
                """,
                (operation_id,),
            ).fetchone()
            if candidate != {
                "generation_manifest_sha256": candidate_generation_manifest_sha256,
                "status": "live",
            }:
                raise DataLifecycleError("Head candidate is not protected by live work")
            head = self._heads.compare_and_swap_generation(
                expected_generation_manifest_sha256=expected_generation_manifest_sha256,
                candidate=resolved_candidate,
            )
            transaction.execute(
                """
                UPDATE data.generation_candidates
                SET status = 'released', updated_at = now()
                WHERE operation_id = %s AND status = 'live'
                """,
                (operation_id,),
            )
            return head

    def release_candidate(self, *, operation_id: str) -> None:
        with self._database.transaction() as transaction:
            _lock(transaction)
            transaction.execute(
                """
                UPDATE data.generation_candidates
                SET status = 'released', updated_at = now()
                WHERE operation_id = %s AND status = 'live'
                """,
                (operation_id,),
            )

    def pin_current(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        lease_seconds: float,
    ) -> GenerationPin:
        if owner_kind not in _OWNER_KINDS:
            raise ValueError("Generation pin owner kind is invalid")
        _require_identity(owner_id, "Generation pin owner")
        _require_lease(lease_seconds)
        with self._database.transaction() as transaction:
            _lock(transaction)
            pointer = self._heads.current_pointer()
            if pointer is None:
                raise DataNotReady("Dataset Head is not ready")
            pin_id = f"generation_pin_{uuid4().hex[:20]}"
            try:
                row = transaction.execute(
                    """
                    INSERT INTO data.generation_pins (
                        id, owner_kind, owner_id, generation_manifest_sha256,
                        status, lease_expires_at
                    ) VALUES (
                        %s, %s, %s, %s, 'active',
                        now() + make_interval(secs => %s)
                    )
                    RETURNING id, owner_kind, owner_id, generation_manifest_sha256,
                              status, lease_expires_at, heartbeat_at
                    """,
                    (
                        pin_id,
                        owner_kind,
                        owner_id,
                        pointer.generation_manifest_sha256,
                        lease_seconds,
                    ),
                ).fetchone()
            except UniqueViolation as error:
                raise DataLifecycleError("Generation pin owner already has a pin") from error
            assert row is not None
            pin = _pin(row)
        try:
            self._heads.resolve(pointer)
        except RuntimeError:
            self.release_pin(pin.id, owner_id=pin.owner_id)
            raise
        return pin

    def heartbeat_pin(self, pin_id: str, *, owner_id: str, lease_seconds: float) -> GenerationPin:
        _require_lease(lease_seconds)
        with self._database.transaction() as transaction:
            _lock(transaction)
            row = transaction.execute(
                """
                UPDATE data.generation_pins
                SET heartbeat_at = now(),
                    lease_expires_at = now() + make_interval(secs => %s)
                WHERE id = %s AND owner_id = %s AND status = 'active'
                RETURNING id, owner_kind, owner_id, generation_manifest_sha256,
                          status, lease_expires_at, heartbeat_at
                """,
                (lease_seconds, pin_id, owner_id),
            ).fetchone()
            if row is None:
                raise DataLifecycleError("active Generation pin was not found")
            return _pin(row)

    def release_pin(self, pin_id: str, *, owner_id: str) -> None:
        with self._database.transaction() as transaction:
            _lock(transaction)
            result = transaction.execute(
                """
                UPDATE data.generation_pins
                SET status = 'released', released_at = now()
                WHERE id = %s AND owner_id = %s AND status = 'active'
                """,
                (pin_id, owner_id),
            )
            if result.rowcount != 1:
                raise DataLifecycleError("active Generation pin was not found")

    def active_pins(self) -> tuple[GenerationPin, ...]:
        with self._database.transaction() as transaction:
            _lock(transaction)
            rows = transaction.execute(
                """
                SELECT id, owner_kind, owner_id, generation_manifest_sha256,
                       status, lease_expires_at, heartbeat_at
                FROM data.generation_pins
                WHERE status = 'active'
                ORDER BY id
                """
            ).fetchall()
            return tuple(_pin(row) for row in rows)

    def retention(self) -> GenerationRetention:
        with self._database.transaction() as transaction:
            _lock(transaction)
            head = self._heads.current_pointer()
            pins = transaction.execute(
                """
                SELECT DISTINCT generation_manifest_sha256
                FROM data.generation_pins
                WHERE status = 'active'
                """
            ).fetchall()
            candidates = transaction.execute(
                """
                SELECT DISTINCT generation_manifest_sha256
                FROM data.generation_candidates
                WHERE status = 'live'
                """
            ).fetchall()
            return GenerationRetention(
                head_generation_manifest_sha256=(
                    None if head is None else head.generation_manifest_sha256
                ),
                active_pin_generations=frozenset(
                    str(row["generation_manifest_sha256"]) for row in pins
                ),
                live_candidate_generations=frozenset(
                    str(row["generation_manifest_sha256"]) for row in candidates
                ),
            )


def _lock(transaction: PostgresTransaction) -> None:
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (_LIFECYCLE_LOCK,),
    )


def _pin(row: dict[str, object]) -> GenerationPin:
    return GenerationPin(
        id=str(row["id"]),
        owner_kind=str(row["owner_kind"]),
        owner_id=str(row["owner_id"]),
        generation_manifest_sha256=str(row["generation_manifest_sha256"]),
        status=str(row["status"]),
        lease_expires_at=row["lease_expires_at"],
        heartbeat_at=row["heartbeat_at"],
    )


def _require_identity(value: str, subject: str) -> None:
    if not value.strip():
        raise ValueError(f"{subject} must not be empty")


def _require_lease(value: float) -> None:
    if value <= 0:
        raise ValueError("Generation lifecycle lease must be positive")


__all__ = (
    "DataLifecycleError",
    "DataNotReady",
    "DatasetLifecycle",
    "GenerationPin",
    "GenerationRetention",
)

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from psycopg.errors import UniqueViolation

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.head_store import (
    DatasetHead,
    DatasetHeadPointer,
    MountedDatasetHeadStore,
)

_LIFECYCLE_LOCK = "thesistrace-mounted-data-lifecycle"
CURRENT_DATA_CUTOVER_LOCK = "thesistrace-current-data-cutover"
MOUNTED_DATA_MUTATION_LOCK = "thesistrace-mounted-data-mutation"
_OWNER_KINDS = {"research_run_attempt", "tracking_advance_attempt"}


class DataLifecycleError(RuntimeError):
    pass


class DataNotReady(DataLifecycleError):
    pass


@contextmanager
def mounted_data_mutation_lock(
    database: PostgresDatabase,
) -> Iterator[None]:
    """Let operators coexist while excluding Reset and collection."""
    with database.session_advisory_lock_shared(MOUNTED_DATA_MUTATION_LOCK):
        yield


@contextmanager
def try_exclusive_mounted_data_mutation_lock(
    database: PostgresDatabase,
) -> Iterator[bool]:
    """Try to exclude active mounted writers without waiting behind their work."""
    with database.try_session_advisory_lock(MOUNTED_DATA_MUTATION_LOCK) as acquired:
        yield acquired


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
class ProtectedRefreshCandidate:
    operation_id: str
    generation_manifest_sha256: str
    resolved_candidate: object


class DatasetLifecycle:
    """The shared PostgreSQL fence for mounted Head and Generation retention state."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._database = database
        self._heads = MountedDatasetHeadStore(mount_root)

    def current_head(self) -> DatasetHead | None:
        for _ in range(4):
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                pointer = self._heads.current_pointer()
            if pointer is None:
                return None
            try:
                resolved = self._heads.resolve(pointer)
            except RuntimeError:
                with self._database.transaction() as transaction:
                    lock_data_lifecycle(transaction)
                    if self._heads.current_pointer() == pointer:
                        raise
                continue
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                if self._heads.current_pointer() == pointer:
                    return resolved
        raise DataLifecycleError("Dataset Head changed repeatedly during inspection")

    def current_pointer(self) -> DatasetHeadPointer | None:
        for _ in range(4):
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                pointer = self._heads.current_pointer()
            if pointer is None:
                return None
            try:
                self._heads.resolve_descriptor(pointer)
            except RuntimeError:
                with self._database.transaction() as transaction:
                    lock_data_lifecycle(transaction)
                    if self._heads.current_pointer() == pointer:
                        raise
                continue
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                if self._heads.current_pointer() == pointer:
                    return pointer
        raise DataLifecycleError("Dataset Head changed repeatedly during inspection")

    def protect_candidate(
        self,
        *,
        operation_id: str,
        generation_manifest_sha256: str,
        lease_seconds: float,
    ) -> None:
        self._register_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation_manifest_sha256,
            lease_seconds=lease_seconds,
        )
        try:
            self._heads.open_generation(generation_manifest_sha256)
        except RuntimeError:
            self.release_candidate(operation_id=operation_id)
            raise

    def _register_candidate(
        self,
        *,
        operation_id: str,
        generation_manifest_sha256: str,
        lease_seconds: float,
    ) -> None:
        _require_identity(operation_id, "candidate operation")
        _require_lease(lease_seconds)
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            if collection_is_active(transaction):
                raise DataLifecycleError("Data collection is active")
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
            elif row != {
                "generation_manifest_sha256": generation_manifest_sha256,
                "status": "live",
            }:
                raise DataLifecycleError("candidate operation identity conflicts")
            else:
                transaction.execute(
                    """
                    UPDATE data.generation_candidates
                    SET lease_expires_at = now() + make_interval(secs => %s), updated_at = now()
                    WHERE operation_id = %s AND status = 'live'
                    """,
                    (lease_seconds, operation_id),
                )

    @contextmanager
    def protected_refresh_candidate(
        self,
        *,
        operation_id: str,
        generation_manifest_sha256: str,
        lease_seconds: float,
    ) -> Iterator[ProtectedRefreshCandidate]:
        self._register_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation_manifest_sha256,
            lease_seconds=lease_seconds,
        )
        with self._heads.resolved_pointer_candidate(
            generation_manifest_sha256
        ) as resolved:
            yield ProtectedRefreshCandidate(
                operation_id=operation_id,
                generation_manifest_sha256=generation_manifest_sha256,
                resolved_candidate=resolved,
            )

    def compare_and_swap_refresh_head(
        self,
        *,
        expected_generation_manifest_sha256: str | None,
        candidate: ProtectedRefreshCandidate,
        prepared_at: datetime | None = None,
    ) -> DatasetHeadPointer:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            protected = transaction.execute(
                """
                SELECT generation_manifest_sha256, status
                FROM data.generation_candidates
                WHERE operation_id = %s
                  AND status = 'live'
                  AND lease_expires_at > now()
                FOR UPDATE
                """,
                (candidate.operation_id,),
            ).fetchone()
            if protected != {
                "generation_manifest_sha256": candidate.generation_manifest_sha256,
                "status": "live",
            }:
                raise DataLifecycleError("Head candidate is not protected by live work")
            head = self._heads.compare_and_swap_pointer_resolved(
                expected_generation_manifest_sha256=(
                    expected_generation_manifest_sha256
                ),
                candidate=candidate.resolved_candidate,  # type: ignore[arg-type]
                prepared_at=prepared_at,
            )
            transaction.execute(
                """
                UPDATE data.generation_candidates
                SET status = 'released', released_at = now(), updated_at = now()
                WHERE operation_id = %s AND status = 'live'
                """,
                (candidate.operation_id,),
            )
            return head

    def compare_and_swap_head(
        self,
        *,
        expected_generation_manifest_sha256: str | None,
        candidate_generation_manifest_sha256: str,
        operation_id: str,
        prepared_at: datetime | None = None,
    ) -> DatasetHead:
        with self._heads.resolved_candidate(candidate_generation_manifest_sha256) as resolved:
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                candidate = transaction.execute(
                    """
                    SELECT generation_manifest_sha256, status
                    FROM data.generation_candidates
                    WHERE operation_id = %s
                      AND status = 'live'
                      AND lease_expires_at > now()
                    FOR UPDATE
                    """,
                    (operation_id,),
                ).fetchone()
                if candidate != {
                    "generation_manifest_sha256": candidate_generation_manifest_sha256,
                    "status": "live",
                }:
                    raise DataLifecycleError("Head candidate is not protected by live work")
                head = self._heads.compare_and_swap_resolved(
                    expected_generation_manifest_sha256=expected_generation_manifest_sha256,
                    candidate=resolved,
                    prepared_at=prepared_at,
                )
                transaction.execute(
                    """
                    UPDATE data.generation_candidates
                    SET status = 'released', released_at = now(), updated_at = now()
                    WHERE operation_id = %s AND status = 'live'
                    """,
                    (operation_id,),
                )
                return head

    def release_candidate(self, *, operation_id: str) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            transaction.execute(
                """
                UPDATE data.generation_candidates
                SET status = 'released', released_at = now(), updated_at = now()
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
        with self._database.transaction() as transaction:
            return self.pin_current_in_transaction(
                transaction,
                owner_kind=owner_kind,
                owner_id=owner_id,
                lease_seconds=lease_seconds,
            )

    def pin_current_in_transaction(
        self,
        transaction: PostgresTransaction,
        *,
        owner_kind: str,
        owner_id: str,
        lease_seconds: float,
    ) -> GenerationPin:
        if owner_kind not in _OWNER_KINDS:
            raise ValueError("Generation pin owner kind is invalid")
        _require_identity(owner_id, "Generation pin owner")
        _require_lease(lease_seconds)
        lock_data_lifecycle(transaction)
        pointer = self._heads.current_pointer()
        if pointer is None:
            raise DataNotReady("Dataset Head is not ready")
        self._heads.resolve(pointer)
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
        return _pin(row)

    def heartbeat_pin(self, pin_id: str, *, owner_id: str, lease_seconds: float) -> GenerationPin:
        with self._database.transaction() as transaction:
            return self.heartbeat_pin_in_transaction(
                transaction,
                pin_id,
                owner_id=owner_id,
                lease_seconds=lease_seconds,
            )

    def heartbeat_pin_in_transaction(
        self,
        transaction: PostgresTransaction,
        pin_id: str,
        *,
        owner_id: str,
        lease_seconds: float,
    ) -> GenerationPin:
        _require_lease(lease_seconds)
        lock_data_lifecycle(transaction)
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
            self.release_pin_in_transaction(
                transaction,
                pin_id,
                owner_id=owner_id,
            )

    def release_pin_in_transaction(
        self,
        transaction: PostgresTransaction,
        pin_id: str,
        *,
        owner_id: str,
    ) -> None:
        lock_data_lifecycle(transaction)
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
            lock_data_lifecycle(transaction)
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

    def retention_root_ids_in_transaction(
        self,
        transaction: PostgresTransaction,
    ) -> tuple[str, ...]:
        lock_data_lifecycle(transaction)
        roots: set[str] = set()
        pointer = self._heads.current_pointer()
        if pointer is not None:
            roots.add(pointer.generation_manifest_sha256)
        roots.update(
            str(row["generation_manifest_sha256"])
            for row in transaction.execute(
                """
                SELECT generation_manifest_sha256
                FROM data.generation_pins
                WHERE status = 'active'
                """
            ).fetchall()
        )
        roots.update(
            str(row["generation_manifest_sha256"])
            for row in transaction.execute(
                """
                SELECT generation_manifest_sha256
                FROM data.generation_candidates
                WHERE status = 'live'
                """
            ).fetchall()
        )
        return tuple(sorted(roots))


def lock_data_lifecycle(transaction: PostgresTransaction) -> None:
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (_LIFECYCLE_LOCK,),
    )


def collection_is_active(transaction: PostgresTransaction) -> bool:
    row = transaction.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM data.collection_operations WHERE status = 'running'
        ) AS active
        """
    ).fetchone()
    return bool(row and row["active"])


def release_generation_candidate(
    transaction: PostgresTransaction,
    *,
    operation_id: str,
) -> None:
    _require_identity(operation_id, "candidate operation")
    transaction.execute(
        """
        UPDATE data.generation_candidates
        SET status = 'released', released_at = now(), updated_at = now()
        WHERE operation_id = %s AND status = 'live'
        """,
        (operation_id,),
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
    "collection_is_active",
    "lock_data_lifecycle",
    "release_generation_candidate",
)

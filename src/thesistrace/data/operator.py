from __future__ import annotations

import copy
import hashlib
import logging
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.canonical_mapping import liquidity_universes
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
from thesistrace.data.head_store import DatasetHead, DatasetHeadConflict
from thesistrace.data.lifecycle import (
    DatasetLifecycle,
    lock_data_lifecycle,
    release_generation_candidate,
)
from thesistrace.data.source import (
    BootstrapCollectionPlan,
    BootstrapDataSource,
    CanonicalSourceBatch,
    DataSourceError,
    bootstrap_collection_plan,
)
from thesistrace.data.validation import validate_bootstrap_batch
from thesistrace.publication.serialization import canonical_json_bytes


class DataOperatorError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BootstrapOutcome:
    status: str
    generation_manifest_sha256: str
    data_through_session: str
    prepared_at: str


@dataclass(frozen=True)
class _BootstrapClaim:
    owner_token: str | None
    row: dict[str, object] | None


_BOOTSTRAP_LEASE_SECONDS = 900
_BOOTSTRAP_HEARTBEAT_SECONDS = 30
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BootstrapHeartbeat:
    failed: Event

    def assert_owned(self) -> None:
        if self.failed.is_set():
            raise RuntimeError("Bootstrap operation heartbeat lost ownership")


class DataOperator:
    """Deployment-private mutation boundary for the mounted Canonical Data Store."""

    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        source: BootstrapDataSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        lease_seconds: float = _BOOTSTRAP_LEASE_SECONDS,
        heartbeat_seconds: float = _BOOTSTRAP_HEARTBEAT_SECONDS,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("Bootstrap lease and heartbeat intervals are invalid")
        self._database = database
        self._source = source
        self._clock = clock
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._generations = MountedGenerationStore(mount_root)
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds

    def bootstrap(self, *, idempotency_key: str, as_of: datetime) -> BootstrapOutcome:
        key = _identity(idempotency_key, "Bootstrap idempotency key")
        plan = bootstrap_collection_plan(as_of)
        fingerprint = hashlib.sha256(
            canonical_json_bytes(
                {
                    "command": "data-operator/bootstrap/v1",
                    "as_of": as_of.astimezone(UTC).isoformat(),
                    "request_start": plan.start_date.isoformat(),
                    "request_end": plan.completed_through_date.isoformat(),
                }
            )
        ).hexdigest()
        claim = self._claim(key, fingerprint, plan)
        if claim.owner_token is None:
            assert claim.row is not None
            return self._reopen(claim.row, fingerprint)

        owner_token = claim.owner_token
        operation_id = _operation_id(key, owner_token)
        candidate_manifest: str | None = None
        candidate_live = False
        try:
            with self._maintain_claim(key, owner_token) as heartbeat:
                current_head = self._lifecycle.current_head()
                prior_manifest = None if claim.row is None else claim.row.get(
                    "generation_manifest_sha256"
                )
                if (
                    current_head is not None
                    and prior_manifest
                    and current_head.generation_manifest_sha256 == prior_manifest
                ):
                    outcome = _outcome(current_head)
                    self._lifecycle.release_candidate(
                        operation_id=_operation_id(key, str(claim.row["owner_token"]))
                    )
                    self._complete(key, owner_token, outcome)
                    return outcome
                if current_head is not None:
                    raise DataOperatorError("HEAD_ALREADY_EXISTS")
                batch = self._source.collect_bootstrap(plan)
                heartbeat.assert_owned()
                expanded = _apply_bootstrap_expansion(batch)
                validate_bootstrap_batch(expanded)
                heartbeat.assert_owned()
                materialized_at = self._operator_time()
                generation = self._generations.materialize(
                    expanded.canonical,
                    prepared_at=materialized_at,
                    source_name=expanded.source_name,
                    source_lineage=expanded.source_lineage,
                )
                heartbeat.assert_owned()
                candidate_manifest = generation.manifest_sha256
                self._lifecycle.protect_candidate(
                    operation_id=operation_id,
                    generation_manifest_sha256=candidate_manifest,
                    lease_seconds=self._lease_seconds,
                )
                candidate_live = True
                self._record_candidate(key, owner_token, candidate_manifest)
                heartbeat.assert_owned()
                try:
                    completed_at = self._operator_time()
                    head = self._lifecycle.compare_and_swap_head(
                        expected_generation_manifest_sha256=None,
                        candidate_generation_manifest_sha256=candidate_manifest,
                        operation_id=operation_id,
                        prepared_at=completed_at,
                    )
                    candidate_live = False
                except DatasetHeadConflict as error:
                    self._lifecycle.release_candidate(operation_id=operation_id)
                    candidate_live = False
                    raise DataOperatorError("HEAD_ALREADY_EXISTS") from error
                outcome = _outcome(head)
                try:
                    self._complete(key, owner_token, outcome)
                except RuntimeError as error:
                    raise DataOperatorError("BOOTSTRAP_COMPLETION_PENDING") from error
                return outcome
        except DataOperatorError as error:
            if error.code == "BOOTSTRAP_COMPLETION_PENDING":
                raise
            self._fail(key, owner_token, error.code)
            raise
        except DataSourceError as error:
            code = f"SOURCE_{error.category.upper()}"
            self._fail(key, owner_token, code)
            raise DataOperatorError(code) from error
        except (GenerationStoreError, ValueError) as error:
            self._fail(key, owner_token, "INVALID_CANONICAL_DATA")
            raise DataOperatorError("INVALID_CANONICAL_DATA") from error
        except (OSError, RuntimeError) as error:
            if candidate_live:
                self._lifecycle.release_candidate(operation_id=operation_id)
            self._fail(key, owner_token, "BOOTSTRAP_INFRASTRUCTURE_FAILURE")
            raise DataOperatorError("BOOTSTRAP_INFRASTRUCTURE_FAILURE") from error

    def _operator_time(self) -> datetime:
        selected = self._clock()
        if selected.tzinfo is None:
            raise DataOperatorError("INVALID_PREPARATION_TIME")
        return selected

    @contextmanager
    def _maintain_claim(
        self,
        key: str,
        owner_token: str,
    ) -> Iterator[_BootstrapHeartbeat]:
        stopped = Event()
        state = _BootstrapHeartbeat(failed=Event())
        thread = Thread(
            target=self._heartbeat_claim,
            args=(key, owner_token, stopped, state.failed),
            name=f"data-bootstrap-heartbeat-{hashlib.sha256(key.encode()).hexdigest()[:12]}",
            daemon=True,
        )
        thread.start()
        try:
            yield state
        finally:
            stopped.set()
            thread.join(timeout=5)
            if thread.is_alive():
                state.failed.set()

    def _heartbeat_claim(
        self,
        key: str,
        owner_token: str,
        stopped: Event,
        failed: Event,
    ) -> None:
        while not stopped.wait(self._heartbeat_seconds):
            try:
                with self._database.transaction() as transaction:
                    renewed = transaction.execute(
                        """
                        UPDATE data.bootstrap_operations
                        SET lease_expires_at = now() + make_interval(secs => %s),
                            updated_at = now()
                        WHERE idempotency_key = %s
                          AND status = 'running'
                          AND owner_token = %s
                        """,
                        (self._lease_seconds, key, owner_token),
                    )
            except Exception as error:
                logger.error(
                    "Bootstrap operation heartbeat failed",
                    extra={"error_type": type(error).__name__},
                )
                failed.set()
                return
            if renewed.rowcount != 1:
                failed.set()
                return

    def _claim(
        self,
        key: str,
        fingerprint: str,
        plan: BootstrapCollectionPlan,
    ) -> _BootstrapClaim:
        owner_token = secrets.token_hex(16)
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            inserted = transaction.execute(
                """
                INSERT INTO data.bootstrap_operations (
                    idempotency_key, fingerprint, status, owner_token,
                    lease_expires_at, as_of, request_start, request_end
                ) VALUES (
                    %s, %s, 'running', %s,
                    now() + make_interval(secs => %s), %s, %s, %s
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING *
                """,
                (
                    key,
                    fingerprint,
                    owner_token,
                    self._lease_seconds,
                    plan.as_of,
                    plan.start_date,
                    plan.completed_through_date,
                ),
            ).fetchone()
            if inserted is not None:
                return _BootstrapClaim(owner_token=owner_token, row=None)
            row = transaction.execute(
                """
                SELECT *, lease_expires_at <= now() AS lease_expired
                FROM data.bootstrap_operations
                WHERE idempotency_key = %s
                FOR UPDATE
                """,
                (key,),
            ).fetchone()
            assert row is not None
            if (
                row["fingerprint"] != fingerprint
                or row["status"] != "running"
                or not row["lease_expired"]
            ):
                return _BootstrapClaim(owner_token=None, row=row)
            reclaimed = transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET owner_token = %s,
                    lease_expires_at = now() + make_interval(secs => %s),
                    updated_at = now()
                WHERE idempotency_key = %s
                  AND status = 'running'
                  AND owner_token = %s
                  AND lease_expires_at <= now()
                RETURNING *
                """,
                (
                    owner_token,
                    self._lease_seconds,
                    key,
                    row["owner_token"],
                ),
            ).fetchone()
            if reclaimed is None:
                raise RuntimeError("Bootstrap operation lease changed during claim")
            release_generation_candidate(
                transaction,
                operation_id=_operation_id(key, str(row["owner_token"])),
            )
            return _BootstrapClaim(owner_token=owner_token, row=row)

    def _reopen(self, row: dict[str, object], fingerprint: str) -> BootstrapOutcome:
        if row["fingerprint"] != fingerprint:
            raise DataOperatorError("IDEMPOTENCY_KEY_CONFLICT")
        if row["status"] == "failed":
            raise DataOperatorError(str(row["failure_code"]))
        manifest = row["generation_manifest_sha256"]
        if row["status"] == "running" and manifest:
            head = self._lifecycle.current_head()
            if head is not None and head.generation_manifest_sha256 == manifest:
                outcome = _outcome(head)
                self._lifecycle.release_candidate(
                    operation_id=_operation_id(
                        str(row["idempotency_key"]),
                        str(row["owner_token"]),
                    )
                )
                self._complete(
                    str(row["idempotency_key"]),
                    str(row["owner_token"]),
                    outcome,
                )
                return outcome
        if row["status"] == "running":
            raise DataOperatorError("BOOTSTRAP_IN_PROGRESS")
        return BootstrapOutcome(
            status="succeeded",
            generation_manifest_sha256=str(manifest),
            data_through_session=str(row["data_through_session"]),
            prepared_at=row["prepared_at"].isoformat(),
        )

    def _record_candidate(self, key: str, owner_token: str, manifest: str) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            result = transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET generation_manifest_sha256 = %s,
                    lease_expires_at = now() + make_interval(secs => %s),
                    updated_at = now()
                WHERE idempotency_key = %s
                  AND status = 'running'
                  AND owner_token = %s
                """,
                (manifest, self._lease_seconds, key, owner_token),
            )
            if result.rowcount != 1:
                raise RuntimeError("Bootstrap operation lost candidate ownership")

    def _complete(self, key: str, owner_token: str, outcome: BootstrapOutcome) -> None:
        with self._database.transaction() as transaction:
            result = transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET status = 'succeeded', generation_manifest_sha256 = %s,
                    data_through_session = %s, prepared_at = %s,
                    failure_code = NULL, updated_at = now()
                WHERE idempotency_key = %s
                  AND status = 'running'
                  AND owner_token = %s
                """,
                (
                    outcome.generation_manifest_sha256,
                    outcome.data_through_session,
                    outcome.prepared_at,
                    key,
                    owner_token,
                ),
            )
            if result.rowcount == 1:
                return
            row = transaction.execute(
                "SELECT * FROM data.bootstrap_operations WHERE idempotency_key = %s",
                (key,),
            ).fetchone()
            if row is not None and _row_matches_outcome(row, outcome):
                return
            raise RuntimeError("Bootstrap operation completion lost ownership")

    def _fail(self, key: str, owner_token: str, code: str) -> None:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET status = 'failed', failure_code = %s, updated_at = now()
                WHERE idempotency_key = %s
                  AND status = 'running'
                  AND owner_token = %s
                """,
                (code, key, owner_token),
            )


def _apply_bootstrap_expansion(batch: CanonicalSourceBatch) -> CanonicalSourceBatch:
    canonical = copy.deepcopy(batch.canonical)
    sessions = canonical.get("research_calendar")
    base_pool = canonical.get("base_pool")
    prices = canonical.get("prices")
    states = canonical.get("trading_states")
    if not all(isinstance(value, list) for value in (sessions, base_pool, prices, states)):
        raise ValueError("Bootstrap canonical inputs are incomplete")
    canonical["liquidity_universes"] = liquidity_universes(
        sessions,
        base_pool,
        prices,
        states,
    )
    return CanonicalSourceBatch(
        source_name=batch.source_name,
        collection_kind="bootstrap",
        source_lineage=batch.source_lineage,
        canonical=canonical,
        covered_session_range=batch.covered_session_range,
    )


def _identity(value: str, subject: str) -> str:
    normalized = value.strip()
    if not normalized or normalized != value:
        raise ValueError(f"{subject} must be a non-empty canonical value")
    return normalized


def _operation_id(idempotency_key: str, owner_token: str) -> str:
    identity = f"{idempotency_key}:{owner_token}".encode()
    return f"bootstrap:{hashlib.sha256(identity).hexdigest()[:32]}"


def _outcome(head: DatasetHead) -> BootstrapOutcome:
    return BootstrapOutcome(
        status="succeeded",
        generation_manifest_sha256=str(head.generation_manifest_sha256),
        data_through_session=str(head.data_through_session),
        prepared_at=str(head.prepared_at),
    )


def _row_matches_outcome(row: dict[str, object], outcome: BootstrapOutcome) -> bool:
    prepared_at = row.get("prepared_at")
    return (
        row.get("status") == "succeeded"
        and row.get("generation_manifest_sha256") == outcome.generation_manifest_sha256
        and str(row.get("data_through_session")) == outcome.data_through_session
        and isinstance(prepared_at, datetime)
        and prepared_at.isoformat() == outcome.prepared_at
    )


__all__ = ("BootstrapOutcome", "DataOperator", "DataOperatorError")

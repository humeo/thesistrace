from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.benchmark import (
    BenchmarkLevelSource,
    BenchmarkSnapshotError,
    BenchmarkSnapshotStore,
    BenchmarkSnapshotUpdater,
)
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
from thesistrace.data.head_store import (
    DatasetHeadConflict,
    DatasetHeadPointer,
    MountedDatasetHeadStore,
)
from thesistrace.data.lifecycle import (
    DataLifecycleError,
    DatasetLifecycle,
    collection_is_active,
    lock_data_lifecycle,
    mounted_data_mutation_lock,
    release_generation_candidate,
)
from thesistrace.data.source import DataSource, DataSourceError, refresh_collection_plan
from thesistrace.data.validation import validate_release_batch
from thesistrace.operational_events import non_blocking_operational_event_sink
from thesistrace.publication.serialization import canonical_json_bytes

_REFRESH_LEASE_SECONDS = 900
_REFRESH_HEARTBEAT_SECONDS = 30
_REFRESH_MAX_ATTEMPTS = 3


class DataRefreshError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _RefreshFenced(RuntimeError):
    pass


@dataclass(frozen=True)
class RefreshOutcome:
    idempotency_key: str
    kind: str
    as_of: str
    status: str
    outcome: str | None
    data_through_session: str | None
    last_refresh_at: str | None
    failure_code: str | None
    last_failure_code: str | None
    attempt_count: int


@dataclass(frozen=True)
class _RefreshClaim:
    key: str
    owner_token: str
    attempt_count: int


@dataclass(frozen=True)
class _RefreshHeartbeat:
    failed: Event

    def assert_owned(self) -> None:
        if self.failed.is_set():
            raise _RefreshFenced("Refresh operation lost its renewable claim")


@dataclass(frozen=True)
class _RefreshFailure:
    code: str
    retry: bool


class DataRefreshService:
    """Private fenced Worker lifecycle for the mounted current Dataset."""

    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        *,
        benchmark_mount_root: Path | str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        lease_seconds: float = _REFRESH_LEASE_SECONDS,
        heartbeat_seconds: float = _REFRESH_HEARTBEAT_SECONDS,
        max_attempts: int = _REFRESH_MAX_ATTEMPTS,
        lifecycle_event: Callable[[dict[str, object]], None] | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        if (
            lease_seconds <= 0
            or heartbeat_seconds <= 0
            or heartbeat_seconds >= lease_seconds
            or max_attempts <= 0
        ):
            raise ValueError("Refresh lease, heartbeat, and attempt policy is invalid")
        self._database = database
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._max_attempts = max_attempts
        self._lifecycle_event = non_blocking_operational_event_sink(
            lifecycle_event or (lambda _event: None),
            component="data_operator",
        )
        self._monotonic = monotonic
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._heads = MountedDatasetHeadStore(mount_root)
        self._generations = MountedGenerationStore(mount_root)
        self._benchmark_store = BenchmarkSnapshotStore(benchmark_mount_root)

    @contextmanager
    def _timed_phase(self, operation_id: str, phase: str) -> Iterator[None]:
        started_at = self._monotonic()
        yield
        elapsed = self._monotonic() - started_at
        self._lifecycle_event(
            _data_refresh_event(
                "data_refresh_phase_completed",
                operation_id=operation_id,
                phase=phase,
                outcome="completed",
                duration_ms=_duration_ms(elapsed),
            )
        )

    def submit(self, *, idempotency_key: str, as_of: datetime) -> RefreshOutcome:
        key = _identity(idempotency_key)
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise DataRefreshError("INVALID_AS_OF")
        normalized_as_of = as_of.astimezone(UTC)
        fingerprint = hashlib.sha256(
            canonical_json_bytes(
                {
                    "command": "data-operator/refresh/v1",
                    "as_of": normalized_as_of.isoformat(),
                }
            )
        ).hexdigest()
        with self._database.transaction() as transaction:
            existing = transaction.execute(
                "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                (key,),
            ).fetchone()
        if existing is not None:
            if existing["fingerprint"] != fingerprint:
                raise DataRefreshError("IDEMPOTENCY_KEY_CONFLICT")
            return _outcome(existing)
        if self._lifecycle.current_pointer() is None:
            raise DataRefreshError("DATA_NOT_READY")
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                INSERT INTO data.refresh_operations (
                    idempotency_key, kind, fingerprint, status, as_of
                ) VALUES (%s, 'market', %s, 'accepted', %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING *
                """,
                (key, fingerprint, normalized_as_of),
            ).fetchone()
            if row is None:
                row = transaction.execute(
                    "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                    (key,),
                ).fetchone()
        assert row is not None
        if row["fingerprint"] != fingerprint:
            raise DataRefreshError("IDEMPOTENCY_KEY_CONFLICT")
        return _outcome(row)

    def inspect(self, idempotency_key: str) -> RefreshOutcome:
        key = _identity(idempotency_key)
        with self._database.transaction() as transaction:
            row = transaction.execute(
                "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                (key,),
            ).fetchone()
        if row is None:
            raise DataRefreshError("REFRESH_NOT_FOUND")
        return _outcome(row)

    def process_next(
        self,
        source: DataSource,
        *,
        benchmark_source: BenchmarkLevelSource,
    ) -> bool:
        with mounted_data_mutation_lock(self._database):
            return self._process_next(source, benchmark_source=benchmark_source)

    def _process_next(
        self,
        source: DataSource,
        *,
        benchmark_source: BenchmarkLevelSource,
    ) -> bool:
        reconciled = self._reconcile_pending_completion()
        recovered = self._recover_expired_claims()
        claim = self._claim()
        if claim is None:
            return reconciled or recovered
        head_moved = False
        operation_id = _operation_id(claim.key, claim.owner_token)
        operation_started = self._monotonic()
        phase = "claim"
        successful_outcome: str | None = None
        self._lifecycle_event(
            _data_refresh_event(
                "data_refresh_started",
                operation_id=operation_id,
                attempt_number=claim.attempt_count,
                status="running",
            )
        )
        candidate_scope = ExitStack()
        try:
            with self._maintain_claim(claim) as heartbeat:
                phase = "current_head"
                with self._timed_phase(operation_id, phase):
                    head = self._lifecycle.current_pointer()
                    refresh_base = (
                        None
                        if head is None
                        else self._generations.open_refresh_base(
                            head.generation_manifest_sha256
                        )
                    )
                if head is None or refresh_base is None:
                    raise DataRefreshError("DATA_NOT_READY")
                expected_manifest = head.generation_manifest_sha256
                self._record_expected_head(claim, expected_manifest)
                plan = refresh_collection_plan(self._as_of(claim), refresh_base.canonical)
                assert plan.overlap_start_session is not None
                phase = "market"
                with self._timed_phase(operation_id, phase):
                    batch = source.collect(plan)
                heartbeat.assert_owned()
                phase = "validation"
                with self._timed_phase(operation_id, phase):
                    validate_release_batch(batch, predecessor_session=head.data_through_session)
                    candidate_canonical = batch.canonical
                    unchanged = candidate_canonical == refresh_base.canonical
                if unchanged:
                    phase = "benchmark"
                    with self._timed_phase(operation_id, phase):
                        current_admission = self._generations.open_admission(
                            expected_manifest
                        )
                        self._update_benchmark(
                            current_admission.research_calendar,
                            benchmark_source,
                            claim=claim,
                            expected_manifest=expected_manifest,
                        )
                    heartbeat.assert_owned()
                    completed_at = self._operator_time()
                    self._complete_no_change(
                        claim,
                        expected_manifest=expected_manifest,
                        data_through_session=head.data_through_session,
                        completed_at=completed_at,
                    )
                    successful_outcome = "no_change"
                else:
                    prepared_at = self._operator_time()
                    phase = "materialization"
                    with self._timed_phase(operation_id, phase):
                        generation = self._generations.materialize_refresh(
                            predecessor_manifest_sha256=expected_manifest,
                            replacement_canonical=candidate_canonical,
                            replace_from_session=plan.overlap_start_session,
                            prepared_at=prepared_at,
                            source_name=batch.source_name,
                            source_lineage=batch.source_lineage,
                        )
                    heartbeat.assert_owned()
                    phase = "benchmark"
                    with self._timed_phase(operation_id, phase):
                        candidate_admission = self._generations.open_admission(
                            generation.manifest_sha256
                        )
                        self._update_benchmark(
                            candidate_admission.research_calendar,
                            benchmark_source,
                            claim=claim,
                            expected_manifest=expected_manifest,
                        )
                    heartbeat.assert_owned()
                    phase = "candidate_validation"
                    with self._timed_phase(operation_id, phase):
                        protected_candidate = candidate_scope.enter_context(
                            self._lifecycle.protected_refresh_candidate(
                                operation_id=operation_id,
                                generation_manifest_sha256=generation.manifest_sha256,
                                lease_seconds=self._lease_seconds,
                                admission_guard=lambda transaction: (
                                    self._record_candidate_in_transaction(
                                        transaction,
                                        claim,
                                        expected_manifest=expected_manifest,
                                        candidate_manifest=generation.manifest_sha256,
                                        prepared_at=prepared_at,
                                    )
                                ),
                            )
                        )
                    heartbeat.assert_owned()
                    phase = "publication"
                    try:
                        with self._timed_phase(operation_id, phase):
                            moved = self._lifecycle.compare_and_swap_refresh_head(
                                expected_generation_manifest_sha256=expected_manifest,
                                candidate=protected_candidate,
                                prepared_at=prepared_at,
                                publication_guard=lambda transaction: (
                                    self._owned_refresh_transaction(
                                        transaction,
                                        claim,
                                        expected_manifest=expected_manifest,
                                        candidate_manifest=generation.manifest_sha256,
                                    )
                                ),
                            )
                            head_moved = True
                            completed_at = self._operator_time()
                            self._complete_published(claim, moved, completed_at)
                    except Exception:
                        if self._post_cas_head_state(generation.manifest_sha256) is not False:
                            head_moved = True
                        raise
                    successful_outcome = "published"
        except _RefreshFenced:
            self._lifecycle_event(
                _data_refresh_event(
                    "data_refresh_fenced",
                    level="WARNING",
                    operation_id=operation_id,
                    attempt_number=claim.attempt_count,
                    phase=phase,
                    outcome="fenced",
                    duration_ms=_duration_ms(self._monotonic() - operation_started),
                )
            )
        except Exception as error:
            if head_moved:
                self._lifecycle_event(
                    _data_refresh_event(
                        "data_refresh_failed",
                        level="ERROR",
                        operation_id=operation_id,
                        attempt_number=claim.attempt_count,
                        phase=phase,
                        status="running",
                        outcome="completion_pending",
                        duration_ms=_duration_ms(self._monotonic() - operation_started),
                        failure_code="REFRESH_COMPLETION_PENDING",
                        exception_type=type(error).__name__,
                    )
                )
                raise DataRefreshError("REFRESH_COMPLETION_PENDING") from error
            code, retryable = _failure_policy(error)
            try:
                failure = self._record_failure(claim, code=code, retryable=retryable)
            except _RefreshFenced:
                self._lifecycle_event(
                    _data_refresh_event(
                        "data_refresh_fenced",
                        level="WARNING",
                        operation_id=operation_id,
                        attempt_number=claim.attempt_count,
                        phase=phase,
                        outcome="fenced",
                        duration_ms=_duration_ms(self._monotonic() - operation_started),
                    )
                )
                return True
            self._lifecycle_event(
                _data_refresh_event(
                    "data_refresh_failed",
                    level="WARNING" if failure.retry else "ERROR",
                    operation_id=operation_id,
                    attempt_number=claim.attempt_count,
                    phase=phase,
                    status="accepted" if failure.retry else "failed",
                    outcome="retry_scheduled" if failure.retry else "failed",
                    duration_ms=_duration_ms(self._monotonic() - operation_started),
                    failure_code=failure.code,
                    exception_type=type(error).__name__,
                )
            )
            raise DataRefreshError(code) from error
        finally:
            candidate_scope.close()
        if successful_outcome is not None:
            self._lifecycle_event(
                _data_refresh_event(
                    "data_refresh_succeeded",
                    operation_id=operation_id,
                    attempt_number=claim.attempt_count,
                    status="succeeded",
                    outcome=successful_outcome,
                    duration_ms=_duration_ms(self._monotonic() - operation_started),
                )
            )
        return True

    def _update_benchmark(
        self,
        research_calendar: Sequence[str],
        source: BenchmarkLevelSource,
        *,
        claim: _RefreshClaim,
        expected_manifest: str,
    ) -> None:
        BenchmarkSnapshotUpdater(
            self._benchmark_store,
            source,
            clock=self._operator_time,
            publication_guard=lambda: self._owned_refresh_mutation(
                claim,
                expected_manifest=expected_manifest,
            ),
        ).update(research_calendar)

    @contextmanager
    def _owned_refresh_mutation(
        self,
        claim: _RefreshClaim,
        *,
        expected_manifest: str,
    ) -> Iterator[None]:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            with self._owned_refresh_transaction(
                transaction,
                claim,
                expected_manifest=expected_manifest,
            ):
                yield

    @contextmanager
    def _owned_refresh_transaction(
        self,
        transaction: PostgresTransaction,
        claim: _RefreshClaim,
        *,
        expected_manifest: str,
        candidate_manifest: str | None = None,
    ) -> Iterator[None]:
        self._require_owned_refresh(
            transaction,
            claim,
            expected_manifest=expected_manifest,
            candidate_manifest=candidate_manifest,
        )
        yield
        renewed = transaction.execute(
            """
            UPDATE data.refresh_operations
            SET lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                updated_at = clock_timestamp()
            WHERE idempotency_key = %s AND status = 'running' AND owner_token = %s
            """,
            (self._lease_seconds, claim.key, claim.owner_token),
        )
        if renewed.rowcount != 1:
            raise _RefreshFenced("Refresh mutation lost ownership before commit")

    def _require_owned_refresh(
        self,
        transaction: PostgresTransaction,
        claim: _RefreshClaim,
        *,
        expected_manifest: str,
        candidate_manifest: str | None = None,
    ) -> None:
        row = transaction.execute(
            """
            SELECT expected_generation_manifest_sha256, generation_manifest_sha256
            FROM data.refresh_operations
            WHERE idempotency_key = %s AND status = 'running'
              AND owner_token = %s AND lease_expires_at > clock_timestamp()
            FOR UPDATE
            """,
            (claim.key, claim.owner_token),
        ).fetchone()
        if (
            row is None
            or row["expected_generation_manifest_sha256"] != expected_manifest
            or (
                candidate_manifest is not None
                and row["generation_manifest_sha256"] != candidate_manifest
            )
        ):
            raise _RefreshFenced("Refresh mutation belongs to a stale owner")
        pointer = self._heads.current_pointer()
        if pointer is None or pointer.generation_manifest_sha256 != expected_manifest:
            raise DatasetHeadConflict("Dataset Head changed before Refresh mutation")
        transaction.execute(
            """
            UPDATE data.refresh_operations
            SET lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                updated_at = clock_timestamp()
            WHERE idempotency_key = %s AND status = 'running' AND owner_token = %s
            """,
            (self._lease_seconds, claim.key, claim.owner_token),
        )

    def _claim(self) -> _RefreshClaim | None:
        owner_token = secrets.token_hex(16)
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            if collection_is_active(transaction):
                return None
            row = transaction.execute(
                """
                SELECT * FROM data.refresh_operations
                WHERE status = 'accepted'
                  AND NOT EXISTS (
                      SELECT 1 FROM data.refresh_operations
                      WHERE status = 'running'
                  )
                ORDER BY created_at, idempotency_key
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            claimed = transaction.execute(
                """
                UPDATE data.refresh_operations
                SET status = 'running', owner_token = %s,
                    lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                    attempt_count = attempt_count + 1,
                    started_at = clock_timestamp(), updated_at = clock_timestamp()
                WHERE idempotency_key = %s AND status = 'accepted'
                RETURNING attempt_count
                """,
                (owner_token, self._lease_seconds, row["idempotency_key"]),
            ).fetchone()
            if claimed is None:
                return None
            return _RefreshClaim(
                key=str(row["idempotency_key"]),
                owner_token=owner_token,
                attempt_count=int(claimed["attempt_count"]),
            )

    @contextmanager
    def _maintain_claim(self, claim: _RefreshClaim) -> Iterator[_RefreshHeartbeat]:
        stopped = Event()
        heartbeat = _RefreshHeartbeat(failed=Event())
        thread = Thread(
            target=self._heartbeat_claim,
            args=(claim, stopped, heartbeat.failed),
            name=f"data-refresh-heartbeat-{hashlib.sha256(claim.key.encode()).hexdigest()[:12]}",
            daemon=True,
        )
        thread.start()
        try:
            yield heartbeat
        finally:
            stopped.set()
            thread.join(timeout=5)
            if thread.is_alive():
                heartbeat.failed.set()

    def _heartbeat_claim(self, claim: _RefreshClaim, stopped: Event, failed: Event) -> None:
        while not stopped.wait(self._heartbeat_seconds):
            try:
                with self._database.transaction() as transaction:
                    lock_data_lifecycle(transaction)
                    renewed = transaction.execute(
                        """
                        UPDATE data.refresh_operations
                        SET lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                            updated_at = clock_timestamp()
                        WHERE idempotency_key = %s AND status = 'running'
                          AND owner_token = %s
                          AND lease_expires_at > clock_timestamp()
                        """,
                        (self._lease_seconds, claim.key, claim.owner_token),
                    )
                    if renewed.rowcount != 1:
                        raise _RefreshFenced("Refresh operation lease expired")
                    transaction.execute(
                        """
                        UPDATE data.generation_candidates
                        SET lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                            updated_at = clock_timestamp()
                        WHERE operation_id = %s AND status = 'live'
                          AND lease_expires_at > clock_timestamp()
                        """,
                        (
                            self._lease_seconds,
                            _operation_id(claim.key, claim.owner_token),
                        ),
                    )
            except Exception as error:
                self._lifecycle_event(
                    _data_refresh_event(
                        "data_refresh_heartbeat_failed",
                        level="WARNING",
                        operation_id=_operation_id(claim.key, claim.owner_token),
                        attempt_number=claim.attempt_count,
                        failure_code="REFRESH_INFRASTRUCTURE_FAILURE",
                        exception_type=type(error).__name__,
                    )
                )
                failed.set()
                return

    def _as_of(self, claim: _RefreshClaim) -> datetime:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT as_of FROM data.refresh_operations
                WHERE idempotency_key = %s AND status = 'running'
                  AND owner_token = %s
                  AND lease_expires_at > clock_timestamp()
                """,
                (claim.key, claim.owner_token),
            ).fetchone()
        if row is None:
            raise _RefreshFenced("Refresh operation no longer owns work")
        return row["as_of"]

    def _record_expected_head(self, claim: _RefreshClaim, expected_manifest: str) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            pointer = self._heads.current_pointer()
            if pointer is None or pointer.generation_manifest_sha256 != expected_manifest:
                raise DatasetHeadConflict("Dataset Head changed before Refresh execution")
            updated = transaction.execute(
                """
                UPDATE data.refresh_operations
                SET expected_generation_manifest_sha256 = %s,
                    updated_at = clock_timestamp()
                WHERE idempotency_key = %s AND status = 'running' AND owner_token = %s
                  AND lease_expires_at > clock_timestamp()
                """,
                (expected_manifest, claim.key, claim.owner_token),
            )
            if updated.rowcount != 1:
                raise _RefreshFenced("Refresh lost expected-Head ownership")

    def _record_candidate_in_transaction(
        self,
        transaction: PostgresTransaction,
        claim: _RefreshClaim,
        *,
        expected_manifest: str,
        candidate_manifest: str,
        prepared_at: datetime,
    ) -> None:
        pointer = self._heads.current_pointer()
        if pointer is None or pointer.generation_manifest_sha256 != expected_manifest:
            raise DatasetHeadConflict("Dataset Head changed before candidate publication")
        updated = transaction.execute(
            """
            UPDATE data.refresh_operations
            SET generation_manifest_sha256 = %s, candidate_prepared_at = %s,
                lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                updated_at = clock_timestamp()
            WHERE idempotency_key = %s AND status = 'running' AND owner_token = %s
              AND expected_generation_manifest_sha256 = %s
              AND lease_expires_at > clock_timestamp()
            """,
            (
                candidate_manifest,
                prepared_at,
                self._lease_seconds,
                claim.key,
                claim.owner_token,
                expected_manifest,
            ),
        )
        if updated.rowcount != 1:
            raise _RefreshFenced("Refresh lost candidate ownership")

    def _complete_no_change(
        self,
        claim: _RefreshClaim,
        *,
        expected_manifest: str,
        data_through_session: str,
        completed_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            pointer = self._heads.current_pointer()
            if pointer is None or pointer.generation_manifest_sha256 != expected_manifest:
                raise DatasetHeadConflict("Dataset Head changed before no-change completion")
            _complete_operation(
                transaction,
                claim,
                outcome="no_change",
                generation_manifest_sha256=expected_manifest,
                data_through_session=data_through_session,
                completed_at=completed_at,
            )

    def _post_cas_head_state(self, generation_manifest_sha256: str) -> bool | None:
        try:
            with self._database.transaction() as transaction:
                lock_data_lifecycle(transaction)
                pointer = self._heads.current_pointer()
        except Exception:
            return None
        return (
            pointer is not None and pointer.generation_manifest_sha256 == generation_manifest_sha256
        )

    def _complete_published(
        self,
        claim: _RefreshClaim,
        head: DatasetHeadPointer,
        completed_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            pointer = self._heads.current_pointer()
            if (
                pointer is None
                or pointer.generation_manifest_sha256 != head.generation_manifest_sha256
            ):
                raise _RefreshFenced("Published Refresh Head is no longer current")
            _complete_operation(
                transaction,
                claim,
                outcome="published",
                generation_manifest_sha256=head.generation_manifest_sha256,
                data_through_session=head.data_through_session,
                completed_at=completed_at,
            )

    def _record_failure(
        self,
        claim: _RefreshClaim,
        *,
        code: str,
        retryable: bool,
    ) -> _RefreshFailure:
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            release_generation_candidate(
                transaction,
                operation_id=_operation_id(claim.key, claim.owner_token),
            )
            retry = retryable and claim.attempt_count < self._max_attempts
            if retry:
                updated = transaction.execute(
                    """
                    UPDATE data.refresh_operations
                    SET status = 'accepted', owner_token = NULL, lease_expires_at = NULL,
                        expected_generation_manifest_sha256 = NULL,
                        generation_manifest_sha256 = NULL, candidate_prepared_at = NULL,
                        started_at = NULL, last_failure_code = %s, updated_at = now()
                    WHERE idempotency_key = %s AND status = 'running' AND owner_token = %s
                      AND lease_expires_at > clock_timestamp()
                    """,
                    (code, claim.key, claim.owner_token),
                )
            else:
                terminal_code = "RETRY_EXHAUSTED" if retryable else code
                updated = transaction.execute(
                    """
                    UPDATE data.refresh_operations
                    SET status = 'failed', failure_code = %s, last_failure_code = %s,
                        finished_at = now(), updated_at = now()
                    WHERE idempotency_key = %s AND status = 'running' AND owner_token = %s
                      AND lease_expires_at > clock_timestamp()
                    """,
                    (terminal_code, code, claim.key, claim.owner_token),
                )
            if updated.rowcount != 1:
                raise _RefreshFenced("Refresh failure belongs to a stale owner")
        return _RefreshFailure(
            code=code if retry else ("RETRY_EXHAUSTED" if retryable else code),
            retry=retry,
        )

    def _reconcile_pending_completion(self) -> bool:
        reconciled = False
        lifecycle_events: list[dict[str, object]] = []
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            pointer = self._heads.current_pointer()
            if pointer is None:
                return False
            rows = transaction.execute(
                """
                SELECT * FROM data.refresh_operations
                WHERE status = 'running' AND generation_manifest_sha256 = %s
                FOR UPDATE
                """,
                (pointer.generation_manifest_sha256,),
            ).fetchall()
            for row in rows:
                operation_id = _operation_id(
                    str(row["idempotency_key"]), str(row["owner_token"])
                )
                release_generation_candidate(
                    transaction,
                    operation_id=operation_id,
                )
                completed_at = self._operator_time()
                _complete_reconciled_operation(
                    transaction,
                    row,
                    data_through_session=pointer.data_through_session,
                    completed_at=completed_at,
                )
                duration_ms = _persisted_duration_ms(row.get("started_at"), completed_at)
                lifecycle_events.extend(
                    (
                        _data_refresh_event(
                            "data_refresh_phase_completed",
                            operation_id=operation_id,
                            attempt_number=int(row["attempt_count"]),
                            phase="publication",
                            outcome="recovered",
                            duration_ms=duration_ms,
                        ),
                        _data_refresh_event(
                            "data_refresh_succeeded",
                            operation_id=operation_id,
                            attempt_number=int(row["attempt_count"]),
                            status="succeeded",
                            outcome="published",
                            duration_ms=duration_ms,
                        ),
                    )
                )
                reconciled = True
        for event in lifecycle_events:
            self._lifecycle_event(event)
        return reconciled

    def _recover_expired_claims(self) -> bool:
        recovered = False
        with self._database.transaction() as transaction:
            lock_data_lifecycle(transaction)
            rows = transaction.execute(
                """
                SELECT * FROM data.refresh_operations
                WHERE status = 'running' AND lease_expires_at <= clock_timestamp()
                FOR UPDATE SKIP LOCKED
                """
            ).fetchall()
            for row in rows:
                recovered = True
                owner_token = str(row["owner_token"])
                release_generation_candidate(
                    transaction,
                    operation_id=_operation_id(str(row["idempotency_key"]), owner_token),
                )
                if int(row["attempt_count"]) >= self._max_attempts:
                    transaction.execute(
                        """
                        UPDATE data.refresh_operations
                        SET status = 'failed', failure_code = 'RETRY_EXHAUSTED',
                            last_failure_code = 'WORKER_LEASE_EXPIRED',
                            finished_at = now(), updated_at = now()
                        WHERE idempotency_key = %s AND status = 'running'
                          AND owner_token = %s
                        """,
                        (row["idempotency_key"], owner_token),
                    )
                else:
                    transaction.execute(
                        """
                        UPDATE data.refresh_operations
                        SET status = 'accepted', owner_token = NULL, lease_expires_at = NULL,
                            expected_generation_manifest_sha256 = NULL,
                            generation_manifest_sha256 = NULL,
                            candidate_prepared_at = NULL, started_at = NULL,
                            last_failure_code = 'WORKER_LEASE_EXPIRED', updated_at = now()
                        WHERE idempotency_key = %s AND status = 'running'
                          AND owner_token = %s
                        """,
                        (row["idempotency_key"], owner_token),
                    )
        return recovered

    def _operator_time(self) -> datetime:
        selected = self._clock()
        if selected.tzinfo is None:
            raise DataRefreshError("INVALID_PREPARATION_TIME")
        return selected.astimezone(UTC)


def _complete_operation(
    transaction: PostgresTransaction,
    claim: _RefreshClaim,
    *,
    outcome: str,
    generation_manifest_sha256: str,
    data_through_session: str,
    completed_at: datetime,
) -> None:
    updated = transaction.execute(
        """
        UPDATE data.refresh_operations
        SET status = 'succeeded', outcome = %s,
            generation_manifest_sha256 = %s, data_through_session = %s,
            last_refresh_at = %s, failure_code = NULL, last_failure_code = NULL,
            finished_at = now(), updated_at = now()
        WHERE idempotency_key = %s AND status = 'running' AND owner_token = %s
          AND lease_expires_at > clock_timestamp()
        """,
        (
            outcome,
            generation_manifest_sha256,
            data_through_session,
            completed_at,
            claim.key,
            claim.owner_token,
        ),
    )
    if updated.rowcount != 1:
        raise _RefreshFenced("Refresh completion belongs to a stale owner")
    _update_last_refresh(transaction, completed_at)


def _complete_reconciled_operation(
    transaction: PostgresTransaction,
    row: dict[str, object],
    *,
    data_through_session: str,
    completed_at: datetime,
) -> None:
    updated = transaction.execute(
        """
        UPDATE data.refresh_operations
        SET status = 'succeeded', outcome = 'published',
            data_through_session = %s, last_refresh_at = %s,
            failure_code = NULL, last_failure_code = NULL,
            finished_at = now(), updated_at = now()
        WHERE idempotency_key = %s AND status = 'running'
          AND generation_manifest_sha256 = %s
        """,
        (
            data_through_session,
            completed_at,
            row["idempotency_key"],
            row["generation_manifest_sha256"],
        ),
    )
    if updated.rowcount == 1:
        _update_last_refresh(transaction, completed_at)


def _update_last_refresh(transaction: PostgresTransaction, completed_at: datetime) -> None:
    transaction.execute(
        """
        UPDATE data.current_dataset_state
        SET last_market_refresh_at = GREATEST(last_market_refresh_at, %s)
        WHERE singleton = 1
        """,
        (completed_at,),
    )


def _failure_policy(error: Exception) -> tuple[str, bool]:
    if isinstance(error, DataRefreshError):
        retryable = error.code in {"DATA_NOT_READY", "HEAD_CHANGED"}
        return error.code, retryable
    if isinstance(error, DataSourceError):
        return f"SOURCE_{error.category.upper()}", error.category == "unavailable"
    if isinstance(error, BenchmarkSnapshotError):
        return error.code, False
    if isinstance(error, DatasetHeadConflict):
        return "HEAD_CHANGED", True
    if isinstance(error, ValueError):
        return "INVALID_CANONICAL_DATA", False
    if isinstance(error, (GenerationStoreError, DataLifecycleError, OSError, RuntimeError)):
        return "REFRESH_INFRASTRUCTURE_FAILURE", True
    return "REFRESH_INFRASTRUCTURE_FAILURE", True


def _data_refresh_event(
    event: str,
    *,
    level: str = "INFO",
    **context: object,
) -> dict[str, object]:
    return {"event": event, "level": level, **context}


def _duration_ms(elapsed_seconds: float) -> int:
    return min(max(round(elapsed_seconds * 1000), 0), 2_147_483_647)


def _persisted_duration_ms(started_at: object, completed_at: datetime) -> int:
    if not isinstance(started_at, datetime):
        return 0
    return _duration_ms((completed_at - started_at).total_seconds())


def _operation_id(idempotency_key: str, owner_token: str) -> str:
    identity = f"{idempotency_key}:{owner_token}".encode()
    return f"refresh:{hashlib.sha256(identity).hexdigest()[:32]}"


def _identity(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > 512
        or "\0" in normalized
        or any(0xD800 <= ord(character) <= 0xDFFF for character in normalized)
    ):
        raise DataRefreshError("INVALID_IDEMPOTENCY_KEY")
    return normalized


def validate_market_refresh_request(
    *,
    idempotency_key: str,
    as_of: str,
) -> tuple[str, datetime]:
    key = _identity(idempotency_key)
    if len(as_of) > 128 or as_of != as_of.strip():
        raise DataRefreshError("INVALID_AS_OF")
    try:
        parsed_as_of = datetime.fromisoformat(as_of)
    except (TypeError, ValueError) as error:
        raise DataRefreshError("INVALID_AS_OF") from error
    if parsed_as_of.tzinfo is None or parsed_as_of.utcoffset() is None:
        raise DataRefreshError("INVALID_AS_OF")
    return key, parsed_as_of.astimezone(UTC)


def _outcome(row: dict[str, object]) -> RefreshOutcome:
    as_of = row["as_of"]
    if not isinstance(as_of, datetime):
        raise DataRefreshError("REFRESH_RECEIPT_INVALID")
    return RefreshOutcome(
        idempotency_key=str(row["idempotency_key"]),
        kind=str(row["kind"]),
        as_of=as_of.astimezone(UTC).isoformat(),
        status=str(row["status"]),
        outcome=None if row["outcome"] is None else str(row["outcome"]),
        data_through_session=(
            None if row["data_through_session"] is None else str(row["data_through_session"])
        ),
        last_refresh_at=(
            None if row["last_refresh_at"] is None else row["last_refresh_at"].isoformat()
        ),
        failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
        last_failure_code=(
            None if row["last_failure_code"] is None else str(row["last_failure_code"])
        ),
        attempt_count=int(row["attempt_count"]),
    )


__all__ = ("DataRefreshError", "DataRefreshService", "RefreshOutcome")

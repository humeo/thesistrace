from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.financial_candidate import (
    FinancialCandidateError,
    FinancialCandidateStore,
    FinancialFamilyCandidate,
)
from thesistrace.data.financial_collection import (
    FinancialCollectionContract,
    FinancialCollectionError,
    FinancialCollectionOutcome,
    FinancialCollectionService,
    FinancialRawSource,
)
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
from thesistrace.data.head_store import DatasetHeadConflict
from thesistrace.data.lifecycle import DatasetLifecycle, mounted_data_mutation_lock
from thesistrace.publication.serialization import canonical_json_bytes


class FinancialRefreshError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FinancialRefreshOutcome:
    idempotency_key: str
    candidate: FinancialFamilyCandidate
    expected_shard_count: int
    completed_shard_count: int
    resumed_shard_count: int
    generation_manifest_sha256: str | None = None


class FinancialRefreshService:
    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        source: FinancialRawSource,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._database = database
        self._monotonic = monotonic or time.monotonic
        self._progress = progress or (lambda _event: None)
        self._collection = FinancialCollectionService(
            database,
            mount_root,
            source,
            clock=self._clock,
            monotonic=self._monotonic,
            progress=self._progress,
        )
        self._candidates = FinancialCandidateStore(mount_root)
        self._generations = MountedGenerationStore(mount_root)
        self._lifecycle = DatasetLifecycle(database, mount_root)

    def publish(
        self,
        *,
        idempotency_key: str,
        generation_manifest_sha256: str,
        contract: FinancialCollectionContract,
        prior_candidate_manifest_sha256: str,
        observation_through_session: str,
    ) -> FinancialRefreshOutcome:
        fingerprint = _fingerprint(
            idempotency_key,
            generation_manifest_sha256,
            contract,
            prior_candidate_manifest_sha256,
            observation_through_session,
        )
        published = self._published_outcome(idempotency_key, fingerprint)
        if published is not None:
            return published
        outcome = self.rebuild(
            idempotency_key=idempotency_key,
            generation_manifest_sha256=generation_manifest_sha256,
            contract=contract,
            prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
            observation_through_session=observation_through_session,
        )
        with self._database.session_advisory_lock("financial-publication"):
            self._reconcile_inherited_publication()
            source_financial = self._generations.inspect_root(
                generation_manifest_sha256
            ).financial_candidate_manifest_sha256
            published = self._published_outcome(idempotency_key, fingerprint)
            if published is not None:
                return published
            reconciled = self._reconcile_publication(idempotency_key, outcome)
            if reconciled is not None:
                return reconciled
            for attempt in range(4):
                current = self._lifecycle.current_pointer()
                if current is None:
                    raise FinancialRefreshError("FINANCIAL_DATASET_NOT_READY")
                current_generation = self._generations.inspect_root(
                    current.generation_manifest_sha256
                )
                if (
                    current_generation.financial_candidate_manifest_sha256
                    != source_financial
                ):
                    raise FinancialRefreshError("FINANCIAL_TARGET_CHANGED")
                prepared_at = self._validated_clock()
                operation_id = _publication_operation_id(idempotency_key, attempt)
                with mounted_data_mutation_lock(self._database):
                    financial = self._candidates.validate_against_market_generation(
                        outcome.candidate.manifest_sha256,
                        current.generation_manifest_sha256,
                    )
                    composed = self._generations.compose_financial_candidate(
                        current.generation_manifest_sha256,
                        financial.manifest_sha256,
                        prepared_at=prepared_at,
                        publication_coordinate=fingerprint,
                    )
                    self._record_publication_candidate(
                        idempotency_key,
                        financial.manifest_sha256,
                        composed.manifest_sha256,
                        prepared_at,
                    )
                    self._lifecycle.protect_candidate(
                        operation_id=operation_id,
                        generation_manifest_sha256=composed.manifest_sha256,
                        lease_seconds=900,
                    )
                    try:
                        moved = self._lifecycle.compare_and_swap_head(
                            expected_generation_manifest_sha256=(
                                current.generation_manifest_sha256
                            ),
                            candidate_generation_manifest_sha256=composed.manifest_sha256,
                            operation_id=operation_id,
                            prepared_at=prepared_at,
                            financial_publication_key=idempotency_key,
                        )
                    except DatasetHeadConflict:
                        self._lifecycle.release_candidate(operation_id=operation_id)
                        continue
                    except Exception as error:
                        head_state = self._physical_head_is(composed.manifest_sha256)
                        if head_state is False:
                            self._lifecycle.release_candidate(operation_id=operation_id)
                            raise
                        raise FinancialRefreshError(
                            "FINANCIAL_PUBLICATION_COMPLETION_PENDING"
                        ) from error
                self._complete_publication(
                    idempotency_key,
                    generation_manifest_sha256=moved.generation_manifest_sha256,
                    completed_at=prepared_at,
                )
                self._progress(
                    {
                        "event": "financial_refresh",
                        "phase": "publication",
                        "status": "completed",
                        "idempotency_key": idempotency_key,
                        "candidate_manifest_sha256": financial.manifest_sha256,
                        "generation_manifest_sha256": moved.generation_manifest_sha256,
                    }
                )
                return replace(
                    outcome,
                    candidate=financial,
                    generation_manifest_sha256=moved.generation_manifest_sha256,
                )
        raise FinancialRefreshError("FINANCIAL_HEAD_CHANGED_REPEATEDLY")

    def _reconcile_publication(
        self,
        idempotency_key: str,
        outcome: FinancialRefreshOutcome,
    ) -> FinancialRefreshOutcome | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT fingerprint, publication_candidate_manifest_sha256,
                       composed_generation_manifest_sha256,
                       publication_prepared_at, publication_head_moved_at
                FROM data.financial_refresh_operations
                WHERE idempotency_key = %s AND status = 'succeeded'
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (idempotency_key,),
            ).fetchone()
        if (
            row is None
            or row["publication_candidate_manifest_sha256"] is None
            or row["composed_generation_manifest_sha256"] is None
            or row["publication_prepared_at"] is None
        ):
            return None
        publication_candidate = str(row["publication_candidate_manifest_sha256"])
        composed = str(row["composed_generation_manifest_sha256"])
        if row["publication_head_moved_at"] is None:
            if not self._current_head_inherits_publication(
                composed,
                publication_coordinate=str(row["fingerprint"]),
            ):
                return None
            for attempt in range(4):
                self._lifecycle.release_candidate(
                    operation_id=_publication_operation_id(idempotency_key, attempt)
                )
            self._record_publication_head_moved(
                idempotency_key,
                generation_manifest_sha256=composed,
                moved_at=row["publication_prepared_at"],
            )
        self._complete_publication(
            idempotency_key,
            generation_manifest_sha256=composed,
            completed_at=row["publication_prepared_at"],
        )
        return replace(
            outcome,
            candidate=self._candidates.reopen(publication_candidate),
            generation_manifest_sha256=composed,
        )

    def _physical_head_is(self, generation_manifest_sha256: str) -> bool | None:
        try:
            pointer = self._lifecycle.current_pointer()
        except Exception:
            return None
        return (
            pointer is not None
            and pointer.generation_manifest_sha256 == generation_manifest_sha256
        )

    def _current_head_inherits_publication(
        self,
        generation_manifest_sha256: str,
        *,
        publication_coordinate: str,
    ) -> bool:
        try:
            pointer = self._lifecycle.current_pointer()
            if pointer is None:
                return False
            if pointer.generation_manifest_sha256 == generation_manifest_sha256:
                return True
            current = self._generations.inspect_root(pointer.generation_manifest_sha256)
        except Exception:
            return False
        return current.financial_publication_coordinate == publication_coordinate

    def _reconcile_inherited_publication(self) -> None:
        pointer = self._lifecycle.current_pointer()
        if pointer is None:
            return
        current = self._generations.inspect_root(pointer.generation_manifest_sha256)
        coordinate = current.financial_publication_coordinate
        if coordinate is None:
            return
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT idempotency_key, composed_generation_manifest_sha256,
                       publication_prepared_at, publication_head_moved_at
                FROM data.financial_refresh_operations
                WHERE fingerprint = %s AND status = 'succeeded'
                  AND published_generation_manifest_sha256 IS NULL
                FOR UPDATE
                """,
                (coordinate,),
            ).fetchall()
        for row in rows:
            key = str(row["idempotency_key"])
            composed = str(row["composed_generation_manifest_sha256"])
            prepared_at = row["publication_prepared_at"]
            if prepared_at is None:
                continue
            if row["publication_head_moved_at"] is None:
                for attempt in range(4):
                    self._lifecycle.release_candidate(
                        operation_id=_publication_operation_id(key, attempt)
                    )
                self._record_publication_head_moved(
                    key,
                    generation_manifest_sha256=composed,
                    moved_at=prepared_at,
                )
            self._complete_publication(
                key,
                generation_manifest_sha256=composed,
                completed_at=prepared_at,
            )

    def _record_publication_head_moved(
        self,
        idempotency_key: str,
        *,
        generation_manifest_sha256: str,
        moved_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_refresh_operations
                SET publication_head_moved_at = %s, updated_at = now()
                WHERE idempotency_key = %s AND status = 'succeeded'
                  AND composed_generation_manifest_sha256 = %s
                  AND publication_head_moved_at IS NULL
                """,
                (moved_at, idempotency_key, generation_manifest_sha256),
            ).rowcount
        if changed != 1:
            raise FinancialRefreshError("FINANCIAL_PUBLICATION_COMPLETION_CONFLICT")

    def rebuild(
        self,
        *,
        idempotency_key: str,
        generation_manifest_sha256: str,
        contract: FinancialCollectionContract,
        prior_candidate_manifest_sha256: str,
        observation_through_session: str,
    ) -> FinancialRefreshOutcome:
        fingerprint = _fingerprint(
            idempotency_key,
            generation_manifest_sha256,
            contract,
            prior_candidate_manifest_sha256,
            observation_through_session,
        )
        with mounted_data_mutation_lock(self._database):
            existing = self._initialize(
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                generation_manifest_sha256=generation_manifest_sha256,
                prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
                observation_through_session=observation_through_session,
                allow_create=True,
            )
            if existing is not None:
                return existing
        with self._database.session_advisory_lock(f"financial-refresh:{idempotency_key}"):
            existing = self._initialize(
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                generation_manifest_sha256=generation_manifest_sha256,
                prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
                observation_through_session=observation_through_session,
                allow_create=False,
            )
            if existing is not None:
                return existing
            before = self._collection.inspect(idempotency_key)
            resumed_count = sum(checkpoint.status == "completed" for checkpoint in before)
            try:
                self._candidates.preflight_rebuild(
                    prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
                    generation_manifest_sha256=generation_manifest_sha256,
                    contract=contract,
                    observation_through_session=observation_through_session,
                )
            except FinancialCandidateError as error:
                code = (
                    "FINANCIAL_MARKET_GENERATION_INVALID"
                    if str(error) == "MARKET_GENERATION_INVALID"
                    else str(error)
                )
                self._fail(idempotency_key, code)
                self._collection_failed_progress(
                    idempotency_key,
                    resumed_count,
                    code,
                )
                if code != str(error):
                    raise FinancialRefreshError(code) from error
                raise
            try:
                collection = self._collection.collect(
                    idempotency_key=idempotency_key,
                    generation_manifest_sha256=generation_manifest_sha256,
                    contract=contract,
                )
                snapshot = self._collection.completed_snapshot(idempotency_key)
            except FinancialCollectionError as error:
                self._fail(idempotency_key, error.code)
                self._collection_failed_progress(
                    idempotency_key,
                    resumed_count,
                    error.code,
                    self._collection.inspect_outcome(idempotency_key),
                )
                raise
            except GenerationStoreError as error:
                code = "FINANCIAL_MARKET_GENERATION_INVALID"
                self._fail(idempotency_key, code)
                self._collection_failed_progress(idempotency_key, resumed_count, code)
                raise FinancialRefreshError(code) from error
            candidate_started = self._monotonic()
            self._progress(
                {
                    "event": "financial_refresh",
                    "phase": "candidate",
                    "status": "started",
                    "idempotency_key": idempotency_key,
                    "target_count": collection.target_count,
                    "completed_count": collection.completed_count,
                    "failed_count": 0,
                    "resumed_count": resumed_count,
                }
            )
            try:
                candidate = self._candidates.rebuild(
                    snapshot,
                    prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
                    observation_through_session=observation_through_session,
                )
            except FinancialCandidateError as error:
                self._fail(idempotency_key, str(error))
                self._progress(
                    {
                        "event": "financial_refresh",
                        "phase": "candidate",
                        "status": "failed",
                        "idempotency_key": idempotency_key,
                        "target_count": collection.target_count,
                        "completed_count": collection.completed_count,
                        "failed_count": 1,
                        "resumed_count": resumed_count,
                        "duration_seconds": _duration(candidate_started, self._monotonic()),
                    }
                )
                raise
            outcome = FinancialRefreshOutcome(
                idempotency_key=idempotency_key,
                candidate=candidate,
                expected_shard_count=collection.target_count,
                completed_shard_count=collection.completed_count,
                resumed_shard_count=resumed_count,
            )
            self._complete(outcome)
            self._progress(
                {
                    "event": "financial_refresh",
                    "phase": "candidate",
                    "status": "completed",
                    "idempotency_key": idempotency_key,
                    "target_count": collection.target_count,
                    "completed_count": collection.completed_count,
                    "failed_count": 0,
                    "resumed_count": resumed_count,
                    "duration_seconds": _duration(candidate_started, self._monotonic()),
                    "candidate_manifest_sha256": candidate.manifest_sha256,
                }
            )
            return outcome

    def _initialize(
        self,
        *,
        idempotency_key: str,
        fingerprint: str,
        generation_manifest_sha256: str,
        prior_candidate_manifest_sha256: str,
        observation_through_session: str,
        allow_create: bool,
    ) -> FinancialRefreshOutcome | None:
        with self._database.transaction() as transaction:
            if allow_create:
                transaction.execute(
                    """
                    INSERT INTO data.financial_refresh_operations (
                        idempotency_key, fingerprint, generation_manifest_sha256,
                        prior_candidate_manifest_sha256, observation_through_session, status
                    ) VALUES (%s, %s, %s, %s, %s, 'running')
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (
                        idempotency_key,
                        fingerprint,
                        generation_manifest_sha256,
                        prior_candidate_manifest_sha256,
                        observation_through_session,
                    ),
                )
            row = transaction.execute(
                """
                SELECT * FROM data.financial_refresh_operations
                WHERE idempotency_key = %s FOR UPDATE
                """,
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Financial refresh claim disappeared")
        if str(row["fingerprint"]) != fingerprint:
            raise FinancialRefreshError("FINANCIAL_REFRESH_IDEMPOTENCY_KEY_REUSED")
        if row["status"] == "failed":
            raise FinancialRefreshError(str(row["failure_code"]))
        if row["status"] == "running":
            return None
        candidate = self._candidates.validate(str(row["candidate_manifest_sha256"]))
        return FinancialRefreshOutcome(
            idempotency_key=idempotency_key,
            candidate=candidate,
            expected_shard_count=int(row["expected_shard_count"]),
            completed_shard_count=int(row["completed_shard_count"]),
            resumed_shard_count=int(row["resumed_shard_count"]),
        )

    def _complete(self, outcome: FinancialRefreshOutcome) -> None:
        completed_at = self._clock()
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_refresh_operations
                SET status = 'succeeded', candidate_manifest_sha256 = %s,
                    expected_shard_count = %s, completed_shard_count = %s,
                    resumed_shard_count = %s, finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (
                    outcome.candidate.manifest_sha256,
                    outcome.expected_shard_count,
                    outcome.completed_shard_count,
                    outcome.resumed_shard_count,
                    completed_at,
                    completed_at,
                    outcome.idempotency_key,
                ),
            ).rowcount
            if changed == 1:
                transaction.execute(
                    """
                    UPDATE data.financial_collection_operations
                    SET retention_released_at = COALESCE(retention_released_at, %s),
                        updated_at = %s
                    WHERE idempotency_key = %s AND status = 'succeeded'
                    """,
                    (completed_at, completed_at, outcome.idempotency_key),
                )
        if changed != 1:
            raise FinancialRefreshError("FINANCIAL_REFRESH_COMPLETION_CONFLICT")

    def _published_outcome(
        self,
        idempotency_key: str,
        fingerprint: str,
    ) -> FinancialRefreshOutcome | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT fingerprint, published_generation_manifest_sha256,
                       published_outcome
                FROM data.financial_refresh_operations
                WHERE idempotency_key = %s AND status = 'succeeded'
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if str(row["fingerprint"]) != fingerprint:
            raise FinancialRefreshError("FINANCIAL_REFRESH_IDEMPOTENCY_KEY_REUSED")
        if row["published_generation_manifest_sha256"] is None:
            return None
        manifest = str(row["published_generation_manifest_sha256"])
        snapshot = row["published_outcome"]
        if not isinstance(snapshot, dict):
            raise FinancialRefreshError("FINANCIAL_PUBLISHED_GENERATION_INVALID")
        try:
            candidate = FinancialFamilyCandidate(
                manifest_sha256=str(snapshot["manifest_sha256"]),
                family_id=str(snapshot["family_id"]),
                schema_contract=str(snapshot["schema_contract"]),
                coverage_start=str(snapshot["coverage_start"]),
                observation_through_session=str(snapshot["observation_through_session"]),
                reconciliation_status=str(snapshot["reconciliation_status"]),
                revision_coverage=str(snapshot["revision_coverage"]),
                table_names=tuple(str(value) for value in snapshot["table_names"]),
                row_count=int(snapshot["row_count"]),
                quarantined_row_count=int(snapshot["quarantined_row_count"]),
                raw_batch_count=int(snapshot["raw_batch_count"]),
            )
            expected = int(snapshot["expected_shard_count"])
            completed = int(snapshot["completed_shard_count"])
            resumed = int(snapshot["resumed_shard_count"])
        except (KeyError, TypeError, ValueError) as error:
            raise FinancialRefreshError("FINANCIAL_PUBLISHED_GENERATION_INVALID") from error
        return FinancialRefreshOutcome(
            idempotency_key=idempotency_key,
            candidate=candidate,
            expected_shard_count=expected,
            completed_shard_count=completed,
            resumed_shard_count=resumed,
            generation_manifest_sha256=manifest,
        )

    def _record_publication_candidate(
        self,
        idempotency_key: str,
        candidate_manifest_sha256: str,
        generation_manifest_sha256: str,
        prepared_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_refresh_operations
                SET publication_candidate_manifest_sha256 = %s,
                    composed_generation_manifest_sha256 = %s,
                    publication_prepared_at = %s, updated_at = now()
                WHERE idempotency_key = %s AND status = 'succeeded'
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (
                    candidate_manifest_sha256,
                    generation_manifest_sha256,
                    prepared_at,
                    idempotency_key,
                ),
            ).rowcount
        if changed != 1:
            raise FinancialRefreshError("FINANCIAL_PUBLICATION_CONFLICT")

    def _complete_publication(
        self,
        idempotency_key: str,
        *,
        generation_manifest_sha256: str,
        completed_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT publication_candidate_manifest_sha256,
                       expected_shard_count, completed_shard_count, resumed_shard_count
                FROM data.financial_refresh_operations
                WHERE idempotency_key = %s AND status = 'succeeded'
                FOR UPDATE
                """,
                (idempotency_key,),
            ).fetchone()
            if operation is None or operation["publication_candidate_manifest_sha256"] is None:
                raise FinancialRefreshError("FINANCIAL_PUBLICATION_COMPLETION_CONFLICT")
            candidate = self._candidates.reopen(
                str(operation["publication_candidate_manifest_sha256"])
            )
            snapshot = {
                **candidate.__dict__,
                "table_names": list(candidate.table_names),
                "expected_shard_count": int(operation["expected_shard_count"]),
                "completed_shard_count": int(operation["completed_shard_count"]),
                "resumed_shard_count": int(operation["resumed_shard_count"]),
            }
            changed = transaction.execute(
                """
                UPDATE data.financial_refresh_operations
                SET published_generation_manifest_sha256 = %s, published_at = %s,
                    published_outcome = %s,
                    retention_released_at = COALESCE(retention_released_at, %s),
                    updated_at = %s
                WHERE idempotency_key = %s AND status = 'succeeded'
                  AND composed_generation_manifest_sha256 = %s
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (
                    generation_manifest_sha256,
                    completed_at,
                    Jsonb(snapshot),
                    completed_at,
                    completed_at,
                    idempotency_key,
                    generation_manifest_sha256,
                ),
            ).rowcount
            if changed == 1:
                transaction.execute(
                    """
                    UPDATE data.current_dataset_state
                    SET last_financial_refresh_at = GREATEST(
                        last_financial_refresh_at, %s
                    )
                    WHERE singleton = 1
                    """,
                    (completed_at,),
                )
        if changed != 1:
            raise FinancialRefreshError("FINANCIAL_PUBLICATION_COMPLETION_CONFLICT")

    def _validated_clock(self) -> datetime:
        selected = self._clock()
        if selected.tzinfo is None:
            raise FinancialRefreshError("FINANCIAL_REFRESH_CLOCK_INVALID")
        return selected.astimezone(UTC)

    def release(self, idempotency_key: str) -> None:
        with mounted_data_mutation_lock(self._database):
            with self._database.transaction() as transaction:
                row = transaction.execute(
                    """
                SELECT status FROM data.financial_refresh_operations
                WHERE idempotency_key = %s FOR UPDATE
                """,
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    raise FinancialRefreshError("FINANCIAL_REFRESH_NOT_FOUND")
                if row["status"] != "succeeded":
                    raise FinancialRefreshError("FINANCIAL_REFRESH_NOT_RELEASABLE")
                transaction.execute(
                    """
                    UPDATE data.financial_refresh_operations
                    SET retention_released_at = COALESCE(retention_released_at, now()),
                        updated_at = now()
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )

    def _fail(self, idempotency_key: str, code: str) -> None:
        failed_at = self._clock()
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.financial_refresh_operations
                SET status = 'failed', failure_code = %s,
                    finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (code, failed_at, failed_at, idempotency_key),
            )

    def _collection_failed_progress(
        self,
        idempotency_key: str,
        resumed_count: int,
        failure_code: str,
        collection: FinancialCollectionOutcome | None = None,
    ) -> None:
        self._progress(
            {
                "event": "financial_refresh",
                "phase": "collection",
                "status": "failed",
                "idempotency_key": idempotency_key,
                "target_count": 0 if collection is None else collection.target_count,
                "completed_count": (
                    resumed_count if collection is None else collection.completed_count
                ),
                "failed_count": 1,
                "resumed_count": resumed_count,
                "failure_code": failure_code,
            }
        )


def _duration(started: float, finished: float) -> float:
    return round(max(0.0, finished - started), 6)


def _publication_operation_id(idempotency_key: str, attempt: int) -> str:
    identity = hashlib.sha256(f"{idempotency_key}:{attempt}".encode()).hexdigest()[:32]
    return f"financial-refresh:{identity}"


def _fingerprint(
    idempotency_key: str,
    generation_manifest_sha256: str,
    contract: FinancialCollectionContract,
    prior_candidate_manifest_sha256: str,
    observation_through_session: str,
) -> str:
    if not idempotency_key or idempotency_key != idempotency_key.strip():
        raise FinancialRefreshError("FINANCIAL_REFRESH_REQUEST_INVALID")
    for value in (generation_manifest_sha256, prior_candidate_manifest_sha256):
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise FinancialRefreshError("FINANCIAL_REFRESH_REQUEST_INVALID")
    try:
        through = date.fromisoformat(observation_through_session).isoformat()
        normalized_contract = FinancialCollectionContract.from_descriptor(contract.descriptor())
    except ValueError as error:
        raise FinancialRefreshError("FINANCIAL_REFRESH_REQUEST_INVALID") from error
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "command": "data-operator/financial-refresh/v1",
                "idempotency_key": idempotency_key,
                "generation_manifest_sha256": generation_manifest_sha256,
                "contract": normalized_contract.descriptor(),
                "prior_candidate_manifest_sha256": prior_candidate_manifest_sha256,
                "observation_through_session": through,
            }
        )
    ).hexdigest()

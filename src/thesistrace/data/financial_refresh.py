from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

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
from thesistrace.data.generation_store import GenerationStoreError
from thesistrace.data.lifecycle import mounted_data_mutation_lock
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
            row = transaction.execute(
                """
                SELECT * FROM data.financial_refresh_operations
                WHERE idempotency_key = %s FOR UPDATE
                """,
                (idempotency_key,),
            ).fetchone()
            if row is None:
                if not allow_create:
                    raise RuntimeError("Financial refresh claim disappeared")
                transaction.execute(
                    """
                    INSERT INTO data.financial_refresh_operations (
                        idempotency_key, fingerprint, generation_manifest_sha256,
                        prior_candidate_manifest_sha256, observation_through_session, status
                    ) VALUES (%s, %s, %s, %s, %s, 'running')
                    """,
                    (
                        idempotency_key,
                        fingerprint,
                        generation_manifest_sha256,
                        prior_candidate_manifest_sha256,
                        observation_through_session,
                    ),
                )
                return None
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

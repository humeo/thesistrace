from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from psycopg.errors import UniqueViolation

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.canonical_mapping import liquidity_universes
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
from thesistrace.data.head_store import DatasetHeadConflict
from thesistrace.data.lifecycle import DatasetLifecycle
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


class DataOperator:
    """Deployment-private mutation boundary for the mounted Canonical Data Store."""

    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        source: BootstrapDataSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database = database
        self._source = source
        self._clock = clock
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._generations = MountedGenerationStore(mount_root)

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
        existing = self._claim(key, fingerprint, plan)
        if existing is not None:
            return self._reopen(existing, fingerprint)

        operation_id = _operation_id(key)
        candidate_manifest: str | None = None
        candidate_live = False
        try:
            if self._lifecycle.current_head() is not None:
                raise DataOperatorError("HEAD_ALREADY_EXISTS")
            batch = self._source.collect_bootstrap(plan)
            expanded = _apply_bootstrap_expansion(batch)
            validate_bootstrap_batch(expanded)
            prepared_at = self._clock()
            if prepared_at.tzinfo is None:
                raise DataOperatorError("INVALID_PREPARATION_TIME")
            generation = self._generations.materialize(
                expanded.canonical,
                prepared_at=prepared_at,
                source_name=expanded.source_name,
                source_lineage=expanded.source_lineage,
            )
            candidate_manifest = generation.manifest_sha256
            self._record_candidate(key, candidate_manifest)
            self._lifecycle.protect_candidate(
                operation_id=operation_id,
                generation_manifest_sha256=candidate_manifest,
                lease_seconds=900,
            )
            candidate_live = True
            try:
                head = self._lifecycle.compare_and_swap_head(
                    expected_generation_manifest_sha256=None,
                    candidate_generation_manifest_sha256=candidate_manifest,
                    operation_id=operation_id,
                )
                candidate_live = False
            except DatasetHeadConflict as error:
                self._lifecycle.release_candidate(operation_id=operation_id)
                candidate_live = False
                raise DataOperatorError("HEAD_ALREADY_EXISTS") from error
            outcome = BootstrapOutcome(
                status="succeeded",
                generation_manifest_sha256=head.generation_manifest_sha256,
                data_through_session=head.data_through_session,
                prepared_at=head.prepared_at,
            )
            try:
                self._complete(key, outcome)
            except RuntimeError as error:
                raise DataOperatorError("BOOTSTRAP_COMPLETION_PENDING") from error
            return outcome
        except DataOperatorError as error:
            if error.code == "BOOTSTRAP_COMPLETION_PENDING":
                raise
            self._fail(key, error.code)
            raise
        except DataSourceError as error:
            code = f"SOURCE_{error.category.upper()}"
            self._fail(key, code)
            raise DataOperatorError(code) from error
        except (GenerationStoreError, ValueError) as error:
            self._fail(key, "INVALID_CANONICAL_DATA")
            raise DataOperatorError("INVALID_CANONICAL_DATA") from error
        except (OSError, RuntimeError) as error:
            if candidate_live:
                self._lifecycle.release_candidate(operation_id=operation_id)
            self._fail(key, "BOOTSTRAP_INFRASTRUCTURE_FAILURE")
            raise DataOperatorError("BOOTSTRAP_INFRASTRUCTURE_FAILURE") from error

    def _claim(
        self,
        key: str,
        fingerprint: str,
        plan: BootstrapCollectionPlan,
    ) -> dict[str, object] | None:
        try:
            with self._database.transaction() as transaction:
                row = transaction.execute(
                    "SELECT * FROM data.bootstrap_operations WHERE idempotency_key = %s",
                    (key,),
                ).fetchone()
                if row is not None:
                    return row
                transaction.execute(
                    """
                    INSERT INTO data.bootstrap_operations (
                        idempotency_key, fingerprint, status, as_of,
                        request_start, request_end
                    ) VALUES (%s, %s, 'running', %s, %s, %s)
                    """,
                    (
                        key,
                        fingerprint,
                        plan.as_of,
                        plan.start_date,
                        plan.completed_through_date,
                    ),
                )
                return None
        except UniqueViolation:
            with self._database.transaction() as transaction:
                row = transaction.execute(
                    "SELECT * FROM data.bootstrap_operations WHERE idempotency_key = %s",
                    (key,),
                ).fetchone()
            assert row is not None
            return row

    def _reopen(self, row: dict[str, object], fingerprint: str) -> BootstrapOutcome:
        if row["fingerprint"] != fingerprint:
            raise DataOperatorError("IDEMPOTENCY_KEY_CONFLICT")
        if row["status"] == "failed":
            raise DataOperatorError(str(row["failure_code"]))
        manifest = row["generation_manifest_sha256"]
        if row["status"] == "running" and manifest:
            head = self._lifecycle.current_head()
            if head is not None and head.generation_manifest_sha256 == manifest:
                outcome = BootstrapOutcome(
                    status="succeeded",
                    generation_manifest_sha256=head.generation_manifest_sha256,
                    data_through_session=head.data_through_session,
                    prepared_at=head.prepared_at,
                )
                self._lifecycle.release_candidate(
                    operation_id=_operation_id(str(row["idempotency_key"]))
                )
                self._complete(str(row["idempotency_key"]), outcome)
                return outcome
        if row["status"] == "running":
            raise DataOperatorError("BOOTSTRAP_IN_PROGRESS")
        return BootstrapOutcome(
            status="succeeded",
            generation_manifest_sha256=str(manifest),
            data_through_session=str(row["data_through_session"]),
            prepared_at=row["prepared_at"].isoformat(),
        )

    def _record_candidate(self, key: str, manifest: str) -> None:
        with self._database.transaction() as transaction:
            result = transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET generation_manifest_sha256 = %s, updated_at = now()
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (manifest, key),
            )
            if result.rowcount != 1:
                raise RuntimeError("Bootstrap operation lost candidate ownership")

    def _complete(self, key: str, outcome: BootstrapOutcome) -> None:
        with self._database.transaction() as transaction:
            result = transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET status = 'succeeded', generation_manifest_sha256 = %s,
                    data_through_session = %s, prepared_at = %s,
                    failure_code = NULL, updated_at = now()
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (
                    outcome.generation_manifest_sha256,
                    outcome.data_through_session,
                    outcome.prepared_at,
                    key,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("Bootstrap operation completion lost ownership")

    def _fail(self, key: str, code: str) -> None:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET status = 'failed', failure_code = %s, updated_at = now()
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (code, key),
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


def _operation_id(idempotency_key: str) -> str:
    return f"bootstrap:{hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]}"


__all__ = ("BootstrapOutcome", "DataOperator", "DataOperatorError")

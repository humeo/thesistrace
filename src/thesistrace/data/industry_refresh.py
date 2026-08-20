from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.generation_family import MountedDatasetFamilyDescriptor
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
from thesistrace.data.head_store import DatasetHeadConflict
from thesistrace.data.industry_source import (
    IndustrySource,
    IndustrySourceError,
    industry_source_payload_bytes,
)
from thesistrace.data.lifecycle import DatasetLifecycle, mounted_data_mutation_lock
from thesistrace.publication.serialization import canonical_json_bytes

_RAW_MAX_BYTES = 128 * 1024 * 1024


class IndustryRefreshError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IndustryRefreshOutcome:
    idempotency_key: str
    fingerprint: str
    candidate: MountedDatasetFamilyDescriptor
    source_lineage_sha256: str
    generation_manifest_sha256: str | None = None


class IndustryRefreshService:
    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        source: IndustrySource,
        *,
        clock: Callable[[], datetime] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._database = database
        self._root = Path(mount_root).resolve()
        self._source = source
        self._clock = clock or (lambda: datetime.now(UTC))
        self._progress = progress or (lambda _event: None)
        self._generations = MountedGenerationStore(self._root)
        self._lifecycle = DatasetLifecycle(database, self._root)
        self._files = AddressedFileStore(self._root)

    def publish(
        self,
        *,
        idempotency_key: str,
        observation_through_session: str,
    ) -> IndustryRefreshOutcome:
        fingerprint, through = _request_fingerprint(
            idempotency_key,
            observation_through_session,
        )
        with self._database.session_advisory_lock(
            f"industry-refresh:{idempotency_key}"
        ):
            outcome = self._existing_outcome(idempotency_key, fingerprint)
            if outcome is not None and outcome.generation_manifest_sha256 is not None:
                return outcome
            if outcome is None:
                self._initialize(idempotency_key, fingerprint, through)
                outcome = self._build(idempotency_key, fingerprint, through)
            return self._publish_candidate(outcome)

    def inspect(self, idempotency_key: str) -> dict[str, object]:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT * FROM data.industry_refresh_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise IndustryRefreshError("INDUSTRY_REFRESH_NOT_FOUND")
        return {
            key: value.isoformat() if isinstance(value, (date, datetime)) else value
            for key, value in row.items()
        }

    def _initialize(self, key: str, fingerprint: str, through: str) -> None:
        pointer = self._lifecycle.current_pointer()
        if pointer is None:
            raise IndustryRefreshError("INDUSTRY_DATASET_NOT_READY")
        generation = self._generations.inspect_root(pointer.generation_manifest_sha256)
        if through not in generation.research_sessions:
            raise IndustryRefreshError("INDUSTRY_COVERAGE_EXCEEDS_MARKET")
        prior = _industry_manifest(generation.families)
        with mounted_data_mutation_lock(self._database):
            with self._database.transaction() as transaction:
                transaction.execute(
                    """
                    INSERT INTO data.industry_refresh_operations (
                        idempotency_key, fingerprint,
                        source_generation_manifest_sha256,
                        prior_industry_manifest_sha256,
                        observation_through_session, status
                    ) VALUES (%s, %s, %s, %s, %s, 'running')
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (
                        key,
                        fingerprint,
                        pointer.generation_manifest_sha256,
                        prior,
                        through,
                    ),
                )
        existing = self._existing_outcome(key, fingerprint)
        if existing is not None:
            return
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, fingerprint FROM data.industry_refresh_operations
                WHERE idempotency_key = %s
                """,
                (key,),
            ).fetchone()
        if row is None or row["status"] != "running":
            raise IndustryRefreshError("INDUSTRY_REFRESH_CLAIM_CONFLICT")
        if str(row["fingerprint"]) != fingerprint:
            raise IndustryRefreshError("INDUSTRY_REFRESH_IDEMPOTENCY_KEY_REUSED")

    def _build(
        self,
        key: str,
        fingerprint: str,
        through: str,
    ) -> IndustryRefreshOutcome:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT source_generation_manifest_sha256, status
                FROM data.industry_refresh_operations
                WHERE idempotency_key = %s FOR UPDATE
                """,
                (key,),
            ).fetchone()
        if row is None or row["status"] != "running":
            existing = self._existing_outcome(key, fingerprint)
            if existing is None:
                raise IndustryRefreshError("INDUSTRY_REFRESH_CLAIM_CONFLICT")
            return existing
        source_generation = str(row["source_generation_manifest_sha256"])
        identities = self._generations.read_historical_ordinary_a_share_lifecycles(
            source_generation
        )
        code_by_id = {identity.instrument_id: identity.ts_code for identity in identities}
        self._progress(
            {
                "event": "industry_refresh",
                "phase": "collection",
                "status": "started",
                "idempotency_key": key,
            }
        )
        try:
            snapshot = self._source.collect(allowed_codes=set(code_by_id.values()))
            self._store_raw(snapshot.source_lineage_sha256, snapshot.raw_payload())
            candidate = self._generations.materialize_industry_candidate(
                source_generation,
                [dict(row) for row in snapshot.memberships],
                observation_through_session=through,
            )
        except IndustrySourceError as error:
            if error.source_lineage_sha256 is not None and error.raw_payload is not None:
                self._store_raw(error.source_lineage_sha256, error.raw_payload)
            self._fail(
                key,
                error.code,
                source_lineage_sha256=error.source_lineage_sha256,
                diagnostic=error.diagnostic,
            )
            self._failed_progress(key, error.code)
            raise IndustryRefreshError(error.code) from error
        except IndustryRefreshError as error:
            self._fail(key, error.code)
            self._failed_progress(key, error.code)
            raise
        except (GenerationStoreError, AddressedFileError) as error:
            code = "INDUSTRY_CANDIDATE_INVALID"
            self._fail(key, code)
            self._failed_progress(key, code)
            raise IndustryRefreshError(code) from error
        finished_at = self._validated_clock()
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.industry_refresh_operations
                SET status = 'succeeded', source_lineage_sha256 = %s,
                    candidate_manifest_sha256 = %s, finished_at = %s,
                    updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (
                    snapshot.source_lineage_sha256,
                    candidate.manifest_sha256,
                    finished_at,
                    finished_at,
                    key,
                ),
            ).rowcount
        if changed != 1:
            raise IndustryRefreshError("INDUSTRY_REFRESH_COMPLETION_CONFLICT")
        self._progress(
            {
                "event": "industry_refresh",
                "phase": "candidate",
                "status": "completed",
                "idempotency_key": key,
                "candidate_manifest_sha256": candidate.manifest_sha256,
            }
        )
        return IndustryRefreshOutcome(
            idempotency_key=key,
            fingerprint=fingerprint,
            candidate=candidate,
            source_lineage_sha256=snapshot.source_lineage_sha256,
        )

    def _publish_candidate(
        self,
        outcome: IndustryRefreshOutcome,
    ) -> IndustryRefreshOutcome:
        reconciled = self._reconcile_publication(outcome)
        if reconciled is not None:
            return reconciled
        with self._database.session_advisory_lock("industry-publication"):
            reconciled = self._reconcile_publication(outcome)
            if reconciled is not None:
                return reconciled
            operation = self.inspect(outcome.idempotency_key)
            prior = operation["prior_industry_manifest_sha256"]
            for attempt in range(4):
                current = self._lifecycle.current_pointer()
                if current is None:
                    raise IndustryRefreshError("INDUSTRY_DATASET_NOT_READY")
                descriptor = self._generations.inspect_root(
                    current.generation_manifest_sha256
                )
                if descriptor.industry_publication_coordinate == outcome.fingerprint:
                    self._complete_publication(
                        outcome,
                        descriptor.manifest_sha256,
                        self._validated_clock(),
                    )
                    return replace(
                        outcome,
                        generation_manifest_sha256=descriptor.manifest_sha256,
                    )
                if _industry_manifest(descriptor.families) != prior:
                    self._fail_publication_target(
                        outcome.idempotency_key,
                        "INDUSTRY_TARGET_CHANGED",
                    )
                    raise IndustryRefreshError("INDUSTRY_TARGET_CHANGED")
                prepared_at = self._validated_clock()
                operation_id = _publication_operation_id(outcome.idempotency_key, attempt)
                with mounted_data_mutation_lock(self._database):
                    composed = self._generations.compose_industry_candidate(
                        current.generation_manifest_sha256,
                        outcome.candidate.manifest_sha256,
                        prepared_at=prepared_at,
                        publication_coordinate=outcome.fingerprint,
                    )
                    self._record_publication_candidate(
                        outcome.idempotency_key,
                        composed.manifest_sha256,
                        prepared_at,
                    )
                    self._lifecycle.protect_prevalidated_candidate(
                        operation_id=operation_id,
                        generation_manifest_sha256=composed.manifest_sha256,
                        lease_seconds=900,
                    )
                    try:
                        moved = self._lifecycle.compare_and_swap_head(
                            expected_generation_manifest_sha256=(
                                current.generation_manifest_sha256
                            ),
                            candidate_generation_manifest_sha256=(
                                composed.manifest_sha256
                            ),
                            operation_id=operation_id,
                            prepared_at=prepared_at,
                            industry_publication_key=outcome.idempotency_key,
                        )
                    except DatasetHeadConflict:
                        self._lifecycle.release_candidate(operation_id=operation_id)
                        continue
                self._complete_publication(
                    outcome,
                    moved.generation_manifest_sha256,
                    prepared_at,
                )
                self._progress(
                    {
                        "event": "industry_refresh",
                        "phase": "publication",
                        "status": "completed",
                        "idempotency_key": outcome.idempotency_key,
                        "generation_manifest_sha256": moved.generation_manifest_sha256,
                    }
                )
                return replace(
                    outcome,
                    generation_manifest_sha256=moved.generation_manifest_sha256,
                )
        raise IndustryRefreshError("INDUSTRY_HEAD_CHANGED_REPEATEDLY")

    def _reconcile_publication(
        self,
        outcome: IndustryRefreshOutcome,
    ) -> IndustryRefreshOutcome | None:
        operation = self.inspect(outcome.idempotency_key)
        published = operation["published_generation_manifest_sha256"]
        if published is not None:
            return replace(outcome, generation_manifest_sha256=str(published))
        current = self._lifecycle.current_pointer()
        if current is None:
            return None
        descriptor = self._generations.inspect_root(current.generation_manifest_sha256)
        if descriptor.industry_publication_coordinate != outcome.fingerprint:
            return None
        completed_at = self._validated_clock()
        self._record_head_moved_if_missing(
            outcome.idempotency_key,
            current.generation_manifest_sha256,
            completed_at,
        )
        self._complete_publication(
            outcome,
            current.generation_manifest_sha256,
            completed_at,
        )
        return replace(
            outcome,
            generation_manifest_sha256=current.generation_manifest_sha256,
        )

    def _existing_outcome(
        self,
        key: str,
        fingerprint: str,
    ) -> IndustryRefreshOutcome | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT fingerprint, status, failure_code,
                       candidate_manifest_sha256, source_lineage_sha256,
                       published_generation_manifest_sha256
                FROM data.industry_refresh_operations
                WHERE idempotency_key = %s
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        if str(row["fingerprint"]) != fingerprint:
            raise IndustryRefreshError("INDUSTRY_REFRESH_IDEMPOTENCY_KEY_REUSED")
        if row["status"] == "failed":
            raise IndustryRefreshError(str(row["failure_code"]))
        if row["status"] == "running":
            return None
        candidate = self._generations.open_industry_candidate(
            str(row["candidate_manifest_sha256"])
        )
        return IndustryRefreshOutcome(
            idempotency_key=key,
            fingerprint=fingerprint,
            candidate=candidate,
            source_lineage_sha256=str(row["source_lineage_sha256"]),
            generation_manifest_sha256=(
                None
                if row["published_generation_manifest_sha256"] is None
                else str(row["published_generation_manifest_sha256"])
            ),
        )

    def _record_publication_candidate(
        self,
        key: str,
        generation_manifest_sha256: str,
        prepared_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.industry_refresh_operations
                SET composed_generation_manifest_sha256 = %s,
                    publication_prepared_at = %s,
                    publication_head_moved_at = NULL, updated_at = %s
                WHERE idempotency_key = %s AND status = 'succeeded'
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (generation_manifest_sha256, prepared_at, prepared_at, key),
            ).rowcount
        if changed != 1:
            raise IndustryRefreshError("INDUSTRY_PUBLICATION_CONFLICT")

    def _record_head_moved_if_missing(
        self,
        key: str,
        generation_manifest_sha256: str,
        moved_at: datetime,
    ) -> None:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.industry_refresh_operations
                SET publication_head_moved_at = COALESCE(
                        publication_head_moved_at, %s
                    ), composed_generation_manifest_sha256 = COALESCE(
                        composed_generation_manifest_sha256, %s
                    ), updated_at = %s
                WHERE idempotency_key = %s AND status = 'succeeded'
                """,
                (moved_at, generation_manifest_sha256, moved_at, key),
            )

    def _complete_publication(
        self,
        outcome: IndustryRefreshOutcome,
        generation_manifest_sha256: str,
        completed_at: datetime,
    ) -> None:
        snapshot = {
            "candidate_manifest_sha256": outcome.candidate.manifest_sha256,
            "source_lineage_sha256": outcome.source_lineage_sha256,
            "family_id": outcome.candidate.family_id,
            "coverage": outcome.candidate.dataset_coverage,
        }
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.industry_refresh_operations
                SET published_generation_manifest_sha256 = %s,
                    published_at = %s, published_outcome = %s,
                    retention_released_at = COALESCE(retention_released_at, %s),
                    updated_at = %s
                WHERE idempotency_key = %s AND status = 'succeeded'
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (
                    generation_manifest_sha256,
                    completed_at,
                    Jsonb(snapshot),
                    completed_at,
                    completed_at,
                    outcome.idempotency_key,
                ),
            ).rowcount
            if changed == 1:
                transaction.execute(
                    """
                    UPDATE data.current_dataset_state
                    SET last_industry_refresh_at = GREATEST(
                        last_industry_refresh_at, %s
                    )
                    WHERE singleton = 1
                    """,
                    (completed_at,),
                )
        if changed == 0:
            existing = self.inspect(outcome.idempotency_key)
            if existing["published_generation_manifest_sha256"] == generation_manifest_sha256:
                return
        if changed != 1:
            raise IndustryRefreshError("INDUSTRY_PUBLICATION_COMPLETION_CONFLICT")

    def _fail(
        self,
        key: str,
        code: str,
        *,
        source_lineage_sha256: str | None = None,
        diagnostic: Mapping[str, object] | None = None,
    ) -> None:
        failed_at = self._validated_clock()
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.industry_refresh_operations
                SET status = 'failed', failure_code = %s,
                    failure_diagnostic = %s, source_lineage_sha256 = %s,
                    finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (
                    code,
                    None if diagnostic is None else Jsonb(_bounded_diagnostic(diagnostic)),
                    source_lineage_sha256,
                    failed_at,
                    failed_at,
                    key,
                ),
            )

    def _fail_publication_target(self, key: str, code: str) -> None:
        failed_at = self._validated_clock()
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.industry_refresh_operations
                SET status = 'failed', failure_code = %s,
                    candidate_manifest_sha256 = NULL,
                    finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'succeeded'
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (code, failed_at, failed_at, key),
            ).rowcount
        if changed != 1:
            raise IndustryRefreshError("INDUSTRY_PUBLICATION_FAILURE_CONFLICT")

    def _store_raw(self, sha256: str, payload: Mapping[str, object]) -> None:
        content = industry_source_payload_bytes(payload)
        if len(content) > _RAW_MAX_BYTES or hashlib.sha256(content).hexdigest() != sha256:
            raise IndustryRefreshError("INDUSTRY_SOURCE_LINEAGE_INVALID")
        self._files.store(self._raw_path(sha256), sha256, content)

    def _raw_path(self, sha256: str) -> Path:
        return self._root / "industry" / "raw" / "sha256" / sha256[:2] / f"{sha256}.json"

    def _validated_clock(self) -> datetime:
        selected = self._clock()
        if selected.tzinfo is None:
            raise IndustryRefreshError("INDUSTRY_REFRESH_CLOCK_INVALID")
        return selected.astimezone(UTC)

    def _failed_progress(self, key: str, code: str) -> None:
        self._progress(
            {
                "event": "industry_refresh",
                "phase": "collection",
                "status": "failed",
                "idempotency_key": key,
                "failure_code": code,
            }
        )


def _industry_manifest(families: tuple[MountedDatasetFamilyDescriptor, ...]) -> str | None:
    return next(
        (
            family.manifest_sha256
            for family in families
            if family.family_id == "equity.industry_membership"
        ),
        None,
    )


def _publication_operation_id(idempotency_key: str, attempt: int) -> str:
    identity = hashlib.sha256(f"{idempotency_key}:{attempt}".encode()).hexdigest()[:32]
    return f"industry-refresh:{identity}"


def _request_fingerprint(key: str, through: str) -> tuple[str, str]:
    if not key or key != key.strip():
        raise IndustryRefreshError("INDUSTRY_REFRESH_REQUEST_INVALID")
    try:
        normalized = date.fromisoformat(through).isoformat()
    except ValueError as error:
        raise IndustryRefreshError("INDUSTRY_REFRESH_REQUEST_INVALID") from error
    fingerprint = hashlib.sha256(
        canonical_json_bytes(
            {
                "command": "data-operator/industry-refresh/v1",
                "idempotency_key": key,
                "observation_through_session": normalized,
            }
        )
    ).hexdigest()
    return fingerprint, normalized


def _bounded_diagnostic(value: Mapping[str, object]) -> dict[str, object]:
    diagnostic = dict(value)
    examples = diagnostic.get("examples")
    if isinstance(examples, list):
        diagnostic["examples"] = examples[:4]
    if len(canonical_json_bytes(diagnostic)) <= 16 * 1024:
        return diagnostic
    return {
        "instrument_id": str(diagnostic.get("instrument_id", ""))[:128],
        "overlap_count": int(diagnostic.get("overlap_count", 0)),
        "diagnostic_truncated": True,
    }


__all__ = (
    "IndustryRefreshError",
    "IndustryRefreshOutcome",
    "IndustryRefreshService",
    "IndustrySource",
)

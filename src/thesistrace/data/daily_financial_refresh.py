from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.financial_announcements import (
    FINANCIAL_ANNOUNCEMENT_CATEGORIES,
    FinancialAnnouncement,
    FinancialAnnouncementDiscovery,
    FinancialAnnouncementSource,
)
from thesistrace.data.financial_candidate import (
    FinancialCandidateError,
    FinancialCandidateStore,
    FinancialDiscoveryPublication,
    FinancialFamilyCandidate,
)
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialCollectionError,
    FinancialRawSource,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
    _raw_batch_content,
    _source_failure_code,
)
from thesistrace.data.generation_store import (
    GenerationStoreError,
    HistoricalInstrumentIdentity,
    MountedGenerationStore,
)
from thesistrace.data.head_store import DatasetHeadConflict
from thesistrace.data.lifecycle import (
    DatasetLifecycle,
    mounted_data_mutation_lock,
)
from thesistrace.data.source import RawSourceError, RawSourceResponse
from thesistrace.publication.serialization import canonical_json_bytes


class FinancialDailyRefreshError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FinancialDailyRefreshInspection:
    idempotency_key: str
    status: str
    target_session: str
    matched_trigger_count: int
    pending_trigger_count: int
    checked_no_structured_change_count: int
    accepted_instrument_count: int
    failed_instrument_count: int


@dataclass(frozen=True)
class FinancialDailyRefreshOutcome:
    idempotency_key: str
    status: str
    candidate: FinancialFamilyCandidate
    generation_manifest_sha256: str
    attempted_through_session: str
    complete_through_session: str
    accepted_instrument_count: int
    failed_instrument_count: int
    pending_instrument_count: int
    discovery_gap_count: int


class FinancialDailyRefreshStore:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def begin(
        self,
        *,
        idempotency_key: str,
        source_generation_manifest_sha256: str,
        prior_financial_manifest_sha256: str,
        discovery_baseline_session: str,
        prior_attempted_through_session: str,
        prior_complete_through_session: str,
        target_session: str,
        started_at: datetime,
    ) -> None:
        started = _aware_clock(started_at)
        coordinates = tuple(
            _iso_date(value)
            for value in (
                discovery_baseline_session,
                prior_attempted_through_session,
                prior_complete_through_session,
                target_session,
            )
        )
        baseline, prior_attempted, prior_complete, target = coordinates
        if not idempotency_key or idempotency_key != idempotency_key.strip():
            raise FinancialDailyRefreshError("INVALID_IDEMPOTENCY_KEY")
        _require_sha256(source_generation_manifest_sha256)
        _require_sha256(prior_financial_manifest_sha256)
        if not (baseline <= prior_complete <= prior_attempted <= target):
            raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_COORDINATES_INVALID")
        fingerprint = _sha(
            {
                "source_generation_manifest_sha256": source_generation_manifest_sha256,
                "prior_financial_manifest_sha256": prior_financial_manifest_sha256,
                "discovery_baseline_session": baseline,
                "prior_attempted_through_session": prior_attempted,
                "prior_complete_through_session": prior_complete,
                "target_session": target,
            }
        )
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO data.financial_daily_refresh_operations (
                    idempotency_key, fingerprint,
                    source_generation_manifest_sha256,
                    prior_financial_manifest_sha256,
                    discovery_baseline_session,
                    prior_attempted_through_session,
                    prior_complete_through_session, target_session,
                    status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'running', %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    idempotency_key,
                    fingerprint,
                    source_generation_manifest_sha256,
                    prior_financial_manifest_sha256,
                    baseline,
                    prior_attempted,
                    prior_complete,
                    target,
                    started,
                    started,
                ),
            )
            row = transaction.execute(
                """
                SELECT fingerprint
                FROM data.financial_daily_refresh_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_WRITE_FAILED")
        if str(row["fingerprint"]) != fingerprint:
            raise FinancialDailyRefreshError("IDEMPOTENCY_KEY_REUSED")

    def record_discovery(
        self,
        *,
        idempotency_key: str,
        discovery: FinancialAnnouncementDiscovery,
        identities: Sequence[HistoricalInstrumentIdentity],
        recorded_at: datetime,
    ) -> None:
        recorded = _aware_clock(recorded_at)
        identity_by_code = _identity_by_code(identities)
        completed = tuple(discovery.completed_categories)
        gaps = tuple(discovery.gaps)
        gap_categories = tuple(item.category for item in gaps)
        if (
            tuple(
                category
                for category in FINANCIAL_ANNOUNCEMENT_CATEGORIES
                if category in completed
            )
            != completed
            or len(set(completed)) != len(completed)
            or set(completed).intersection(gap_categories)
            or set(completed).union(gap_categories)
            != set(FINANCIAL_ANNOUNCEMENT_CATEGORIES)
        ):
            raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_CATEGORY_SET_INVALID")
        _require_sha256(discovery.source_lineage_sha256)
        evidence = _discovery_evidence(discovery)
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT status, target_session, prior_complete_through_session,
                       discovery_evidence
                FROM data.financial_daily_refresh_operations
                WHERE idempotency_key = %s
                FOR UPDATE
                """,
                (idempotency_key,),
            ).fetchone()
            if operation is None:
                raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_FOUND")
            if str(operation["status"]) != "running":
                raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_RUNNING")
            if _iso_date(discovery.end_date) != operation["target_session"].isoformat():
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_TARGET_MISMATCH")
            existing = operation["discovery_evidence"]
            if existing is not None:
                if existing != evidence:
                    raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_REPLAY_MISMATCH")
                return
            for announcement in discovery.announcements:
                identity = identity_by_code.get(announcement.ts_code)
                if identity is None:
                    raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_IDENTITY_INVALID")
                _insert_trigger(
                    transaction,
                    idempotency_key=idempotency_key,
                    identity=identity,
                    announcement=announcement,
                    source_lineage_sha256=discovery.source_lineage_sha256,
                    recorded_at=recorded,
                )
            for category in completed:
                transaction.execute(
                    """
                    UPDATE data.financial_discovery_gaps
                    SET status = 'resolved', resolved_by_operation_key = %s,
                        resolved_at = %s, updated_at = %s
                    WHERE status = 'open' AND category = %s
                      AND unresolved_from_date >= %s
                      AND query_end_date <= %s
                    """,
                    (
                        idempotency_key,
                        recorded,
                        recorded,
                        category,
                        _iso_date(discovery.start_date),
                        _iso_date(discovery.end_date),
                    ),
                )
            first_unverified = operation["prior_complete_through_session"] + timedelta(days=1)
            for gap in gaps:
                unresolved_from = max(_date(gap.start_date), first_unverified)
                if unresolved_from <= _date(gap.end_date):
                    _upsert_gap(
                        transaction,
                        idempotency_key=idempotency_key,
                        category=gap.category,
                        query_start_date=_date(gap.start_date),
                        query_end_date=_date(gap.end_date),
                        unresolved_from_date=unresolved_from,
                        failure_code=gap.failure_code,
                        recorded_at=recorded,
                    )
            transaction.execute(
                """
                UPDATE data.financial_daily_refresh_operations
                SET discovery_start_date = %s, discovery_end_date = %s,
                    discovery_evidence = %s, source_lineage_sha256 = %s,
                    updated_at = %s
                WHERE idempotency_key = %s
                """,
                (
                    _iso_date(discovery.start_date),
                    _iso_date(discovery.end_date),
                    Jsonb(evidence),
                    discovery.source_lineage_sha256,
                    recorded,
                    idempotency_key,
                ),
            )

    def pending_identities(
        self,
        idempotency_key: str,
    ) -> tuple[HistoricalInstrumentIdentity, ...]:
        self._require_running_discovery(idempotency_key)
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT DISTINCT instrument_id, ts_code
                FROM data.financial_announcement_triggers
                WHERE status = 'pending'
                ORDER BY instrument_id, ts_code
                """
            ).fetchall()
        return tuple(
            HistoricalInstrumentIdentity(str(row["instrument_id"]), str(row["ts_code"]))
            for row in rows
        )

    def pending_announcement_ids(
        self,
        instrument_id: str,
    ) -> tuple[str, ...]:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT announcement_id
                FROM data.financial_announcement_triggers
                WHERE instrument_id = %s AND status = 'pending'
                ORDER BY source_published_date, announcement_id
                """,
                (instrument_id,),
            ).fetchall()
        return tuple(str(row["announcement_id"]) for row in rows)

    def attempted_instrument_ids(self, idempotency_key: str) -> frozenset[str]:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT instrument_id
                FROM data.financial_refresh_instrument_attempts
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchall()
        return frozenset(str(row["instrument_id"]) for row in rows)

    def accepted_checkpoints(
        self,
        idempotency_key: str,
    ) -> tuple[FinancialShardCheckpoint, ...]:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT checkpoints
                FROM data.financial_refresh_instrument_attempts
                WHERE idempotency_key = %s AND status = 'accepted'
                ORDER BY instrument_id
                """,
                (idempotency_key,),
            ).fetchall()
        checkpoints = tuple(
            _checkpoint_from_payload(item)
            for row in rows
            for item in row["checkpoints"]
        )
        return tuple(
            FinancialShardCheckpoint(
                ordinal=ordinal,
                endpoint=item.endpoint,
                instrument_id=item.instrument_id,
                ts_code=item.ts_code,
                shard=item.shard,
                status=item.status,
                batch_sha256=item.batch_sha256,
                collected_at=item.collected_at,
                first_observed_at=item.first_observed_at,
            )
            for ordinal, item in enumerate(checkpoints)
        )

    def record_instrument_attempt(
        self,
        *,
        idempotency_key: str,
        instrument_id: str,
        status: Literal["accepted", "failed"],
        matched_announcement_ids: Sequence[str],
        checkpoints: Sequence[FinancialShardCheckpoint],
        failure_code: str | None,
        failure_endpoint: str | None,
        attempted_at: datetime,
    ) -> None:
        attempted = _aware_clock(attempted_at)
        matches = tuple(sorted(set(matched_announcement_ids)))
        for announcement_id in matches:
            _require_sha256(announcement_id)
        checkpoint_payload = [_checkpoint_payload(item) for item in checkpoints]
        if status == "accepted":
            if (
                failure_code is not None
                or failure_endpoint is not None
                or tuple(item.endpoint for item in checkpoints) != FINANCIAL_ENDPOINTS
                or any(
                    item.instrument_id != instrument_id
                    or item.status != "completed"
                    or item.batch_sha256 is None
                    or item.collected_at is None
                    or item.first_observed_at is None
                    for item in checkpoints
                )
            ):
                raise FinancialDailyRefreshError("FINANCIAL_INSTRUMENT_ATTEMPT_INVALID")
        elif status == "failed":
            if not failure_code or not failure_endpoint or checkpoints or matches:
                raise FinancialDailyRefreshError("FINANCIAL_INSTRUMENT_ATTEMPT_INVALID")
        else:
            raise FinancialDailyRefreshError("FINANCIAL_INSTRUMENT_ATTEMPT_INVALID")
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT status, discovery_evidence
                FROM data.financial_daily_refresh_operations
                WHERE idempotency_key = %s
                FOR UPDATE
                """,
                (idempotency_key,),
            ).fetchone()
            if operation is None or str(operation["status"]) != "running":
                raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_RUNNING")
            if operation["discovery_evidence"] is None:
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")
            pending = transaction.execute(
                """
                SELECT announcement_id
                FROM data.financial_announcement_triggers
                WHERE instrument_id = %s AND status = 'pending'
                FOR UPDATE
                """,
                (instrument_id,),
            ).fetchall()
            pending_ids = {str(row["announcement_id"]) for row in pending}
            if not pending_ids or not set(matches).issubset(pending_ids):
                raise FinancialDailyRefreshError("FINANCIAL_TRIGGER_TARGET_INVALID")
            inserted = transaction.execute(
                """
                INSERT INTO data.financial_refresh_instrument_attempts (
                    idempotency_key, instrument_id, status,
                    matched_announcement_ids, checkpoints,
                    failure_code, failure_endpoint, attempted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (idempotency_key, instrument_id) DO NOTHING
                RETURNING instrument_id
                """,
                (
                    idempotency_key,
                    instrument_id,
                    status,
                    Jsonb(list(matches)),
                    Jsonb(checkpoint_payload),
                    failure_code,
                    failure_endpoint,
                    attempted,
                ),
            ).fetchone()
            if inserted is None:
                existing = transaction.execute(
                    """
                    SELECT status, matched_announcement_ids, checkpoints,
                           failure_code, failure_endpoint, attempted_at
                    FROM data.financial_refresh_instrument_attempts
                    WHERE idempotency_key = %s AND instrument_id = %s
                    """,
                    (idempotency_key, instrument_id),
                ).fetchone()
                expected = (
                    status,
                    list(matches),
                    checkpoint_payload,
                    failure_code,
                    failure_endpoint,
                    attempted,
                )
                actual = (
                    str(existing["status"]),
                    existing["matched_announcement_ids"],
                    existing["checkpoints"],
                    existing["failure_code"],
                    existing["failure_endpoint"],
                    existing["attempted_at"],
                )
                if actual != expected:
                    raise FinancialDailyRefreshError("FINANCIAL_ATTEMPT_REPLAY_MISMATCH")
                return
            if status == "failed":
                return
            if matches:
                transaction.execute(
                    """
                    UPDATE data.financial_announcement_triggers
                    SET status = 'matched', resolution_code = 'matched_source_version',
                        last_attempt_operation_key = %s, resolved_at = %s,
                        updated_at = %s
                    WHERE instrument_id = %s AND status = 'pending'
                      AND announcement_id = ANY(%s)
                    """,
                    (idempotency_key, attempted, attempted, instrument_id, list(matches)),
                )
            transaction.execute(
                """
                UPDATE data.financial_announcement_triggers
                SET accepted_no_match_count = 5,
                    last_attempt_operation_key = %s,
                    status = 'checked_no_structured_change',
                    resolution_code = 'checked_no_structured_change',
                    resolved_at = %s,
                    updated_at = %s
                WHERE instrument_id = %s AND status = 'pending'
                """,
                (idempotency_key, attempted, attempted, instrument_id),
            )

    def publication_state(self, idempotency_key: str) -> FinancialDiscoveryPublication:
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT discovery_baseline_session, prior_complete_through_session,
                       target_session, source_lineage_sha256, discovery_evidence
                FROM data.financial_daily_refresh_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if operation is None:
                raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_FOUND")
            if operation["discovery_evidence"] is None:
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")
            gap_rows = transaction.execute(
                """
                SELECT gap_id, unresolved_from_date
                FROM data.financial_discovery_gaps
                WHERE status = 'open' AND unresolved_from_date <= %s
                ORDER BY unresolved_from_date, gap_id
                """,
                (operation["target_session"],),
            ).fetchall()
            trigger_rows = transaction.execute(
                """
                SELECT announcement_id, instrument_id, source_published_date
                FROM data.financial_announcement_triggers
                WHERE status = 'pending' AND source_published_date <= %s
                ORDER BY source_published_date, announcement_id
                """,
                (operation["target_session"],),
            ).fetchall()
        gap_count = len(gap_rows)
        pending_count = len({str(row["instrument_id"]) for row in trigger_rows})
        readiness: Literal["ready", "ready_with_pending", "ready_with_gaps"] = "ready"
        if gap_count:
            readiness = "ready_with_gaps"
        elif pending_count:
            readiness = "ready_with_pending"
        unresolved_dates = [row["unresolved_from_date"] for row in gap_rows]
        unresolved_dates.extend(row["source_published_date"] for row in trigger_rows)
        source_lineage = _sha(
            {
                "discovery_source_lineage_sha256": str(
                    operation["source_lineage_sha256"]
                ),
                "open_gap_ids": [str(row["gap_id"]) for row in gap_rows],
                "pending_announcement_ids": [
                    str(row["announcement_id"]) for row in trigger_rows
                ],
            }
        )
        return FinancialDiscoveryPublication(
            baseline_session=operation["discovery_baseline_session"].isoformat(),
            attempted_through_session=operation["target_session"].isoformat(),
            complete_through_session=(
                operation["prior_complete_through_session"].isoformat()
                if gap_count
                else operation["target_session"].isoformat()
            ),
            source_lineage_sha256=source_lineage,
            readiness_status=readiness,
            pending_instrument_count=pending_count,
            discovery_gap_count=gap_count,
            earliest_unresolved_date=(
                None if not unresolved_dates else min(unresolved_dates).isoformat()
            ),
        )

    def inspect(self, idempotency_key: str) -> FinancialDailyRefreshInspection:
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT status, target_session
                FROM data.financial_daily_refresh_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if operation is None:
                raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_FOUND")
            trigger_counts = transaction.execute(
                """
                SELECT
                    count(*) FILTER (
                        WHERE status = 'matched'
                          AND last_attempt_operation_key = %s
                    ) AS matched_count,
                    count(*) FILTER (
                        WHERE status = 'pending'
                          AND source_published_date <= %s
                    ) AS pending_count,
                    count(*) FILTER (
                        WHERE status = 'checked_no_structured_change'
                          AND last_attempt_operation_key = %s
                    ) AS checked_count
                FROM data.financial_announcement_triggers
                """,
                (
                    idempotency_key,
                    operation["target_session"],
                    idempotency_key,
                ),
            ).fetchone()
            attempt_counts = transaction.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'accepted') AS accepted_count,
                    count(*) FILTER (WHERE status = 'failed') AS failed_count
                FROM data.financial_refresh_instrument_attempts
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        return FinancialDailyRefreshInspection(
            idempotency_key=idempotency_key,
            status=str(operation["status"]),
            target_session=operation["target_session"].isoformat(),
            matched_trigger_count=int(trigger_counts["matched_count"]),
            pending_trigger_count=int(trigger_counts["pending_count"]),
            checked_no_structured_change_count=int(trigger_counts["checked_count"]),
            accepted_instrument_count=int(attempt_counts["accepted_count"]),
            failed_instrument_count=int(attempt_counts["failed_count"]),
        )

    def operation(self, idempotency_key: str) -> dict[str, object]:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT *
                FROM data.financial_daily_refresh_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_FOUND")
        return dict(row)

    def earliest_open_gap_date(self) -> str | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT min(unresolved_from_date) AS earliest
                FROM data.financial_discovery_gaps
                WHERE status = 'open'
                """
            ).fetchone()
        return None if row["earliest"] is None else row["earliest"].isoformat()

    def record_candidate(
        self,
        idempotency_key: str,
        candidate_manifest_sha256: str,
        recorded_at: datetime,
    ) -> None:
        _require_sha256(candidate_manifest_sha256)
        recorded = _aware_clock(recorded_at)
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_daily_refresh_operations
                SET candidate_manifest_sha256 = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                  AND published_generation_manifest_sha256 IS NULL
                  AND (
                    candidate_manifest_sha256 IS NULL
                    OR candidate_manifest_sha256 = %s
                  )
                """,
                (
                    candidate_manifest_sha256,
                    recorded,
                    idempotency_key,
                    candidate_manifest_sha256,
                ),
            ).rowcount
        if changed != 1:
            raise FinancialDailyRefreshError("FINANCIAL_CANDIDATE_RECORD_CONFLICT")

    def record_composed_generation(
        self,
        idempotency_key: str,
        generation_manifest_sha256: str,
        prepared_at: datetime,
    ) -> None:
        _require_sha256(generation_manifest_sha256)
        prepared = _aware_clock(prepared_at)
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_daily_refresh_operations
                SET composed_generation_manifest_sha256 = %s,
                    publication_prepared_at = %s,
                    publication_head_moved_at = NULL,
                    updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                  AND candidate_manifest_sha256 IS NOT NULL
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (
                    generation_manifest_sha256,
                    prepared,
                    prepared,
                    idempotency_key,
                ),
            ).rowcount
        if changed != 1:
            raise FinancialDailyRefreshError("FINANCIAL_PUBLICATION_RECORD_CONFLICT")

    def record_head_moved(
        self,
        idempotency_key: str,
        generation_manifest_sha256: str,
        moved_at: datetime,
    ) -> None:
        _require_sha256(generation_manifest_sha256)
        moved = _aware_clock(moved_at)
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_daily_refresh_operations
                SET composed_generation_manifest_sha256 = %s,
                    publication_prepared_at = COALESCE(
                        publication_prepared_at, %s
                    ),
                    publication_head_moved_at = COALESCE(
                        publication_head_moved_at, %s
                    ),
                    updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                  AND candidate_manifest_sha256 IS NOT NULL
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (
                    generation_manifest_sha256,
                    moved,
                    moved,
                    moved,
                    idempotency_key,
                ),
            ).rowcount
        if changed != 1:
            raise FinancialDailyRefreshError("FINANCIAL_HEAD_MOVE_RECORD_CONFLICT")

    def complete_publication(
        self,
        *,
        idempotency_key: str,
        candidate_manifest_sha256: str,
        generation_manifest_sha256: str,
        publication: FinancialDiscoveryPublication,
        completed_at: datetime,
    ) -> str:
        _require_sha256(candidate_manifest_sha256)
        _require_sha256(generation_manifest_sha256)
        completed = _aware_clock(completed_at)
        status = {
            "ready": "succeeded",
            "ready_with_pending": "succeeded_with_pending",
            "ready_with_gaps": "succeeded_with_gaps",
        }[publication.readiness_status]
        outcome = {
            "candidate_manifest_sha256": candidate_manifest_sha256,
            "generation_manifest_sha256": generation_manifest_sha256,
            "attempted_through_session": publication.attempted_through_session,
            "complete_through_session": publication.complete_through_session,
            "readiness_status": publication.readiness_status,
            "pending_instrument_count": publication.pending_instrument_count,
            "discovery_gap_count": publication.discovery_gap_count,
        }
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_daily_refresh_operations
                SET status = %s, published_generation_manifest_sha256 = %s,
                    published_at = %s, published_outcome = %s,
                    finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                  AND candidate_manifest_sha256 = %s
                  AND publication_head_moved_at IS NOT NULL
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (
                    status,
                    generation_manifest_sha256,
                    completed,
                    Jsonb(outcome),
                    completed,
                    completed,
                    idempotency_key,
                    candidate_manifest_sha256,
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
                    (completed,),
                )
        if changed == 0:
            operation = self.operation(idempotency_key)
            if (
                operation["published_generation_manifest_sha256"]
                == generation_manifest_sha256
            ):
                return str(operation["status"])
        if changed != 1:
            raise FinancialDailyRefreshError("FINANCIAL_PUBLICATION_COMPLETION_CONFLICT")
        return status

    def fail(
        self,
        idempotency_key: str,
        code: str,
        failed_at: datetime,
    ) -> None:
        if not code:
            raise FinancialDailyRefreshError("FINANCIAL_FAILURE_CODE_INVALID")
        failed = _aware_clock(failed_at)
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.financial_daily_refresh_operations
                SET status = 'failed', failure_code = %s,
                    finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                  AND published_generation_manifest_sha256 IS NULL
                """,
                (code, failed, failed, idempotency_key),
            )

    def release(self, idempotency_key: str, released_at: datetime) -> None:
        released = _aware_clock(released_at)
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """
                UPDATE data.financial_daily_refresh_operations
                SET retention_released_at = COALESCE(retention_released_at, %s),
                    updated_at = %s
                WHERE idempotency_key = %s
                  AND status IN (
                      'succeeded', 'succeeded_with_pending', 'succeeded_with_gaps'
                  )
                """,
                (released, released, idempotency_key),
            ).rowcount
        if changed != 1:
            raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_RELEASABLE")

    def _require_running_discovery(self, idempotency_key: str) -> None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, discovery_evidence
                FROM data.financial_daily_refresh_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None or str(row["status"]) != "running":
            raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_RUNNING")
        if row["discovery_evidence"] is None:
            raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")


class DailyFinancialRefreshService:
    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        announcement_source: FinancialAnnouncementSource,
        financial_source: FinancialRawSource,
        *,
        clock: Callable[[], datetime] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._database = database
        self._root = Path(mount_root).resolve()
        self._announcement_source = announcement_source
        self._financial_source = financial_source
        self._clock = clock or (lambda: datetime.now(UTC))
        self._progress = progress or (lambda _event: None)
        self._store = FinancialDailyRefreshStore(database)
        self._candidates = FinancialCandidateStore(self._root)
        self._generations = MountedGenerationStore(self._root)
        self._lifecycle = DatasetLifecycle(database, self._root)

    def publish(
        self,
        *,
        idempotency_key: str,
        observation_through_session: str,
    ) -> FinancialDailyRefreshOutcome:
        target = _iso_date(observation_through_session)
        with self._database.session_advisory_lock("financial-daily-refresh"):
            existing = self._existing_outcome(idempotency_key, target)
            if existing is not None:
                return existing
            operation = self._operation_or_initialize(idempotency_key, target)
            try:
                candidate = self._build_candidate(idempotency_key, operation)
                return self._publish_candidate(idempotency_key, candidate)
            except FinancialDailyRefreshError as error:
                if error.code != "FINANCIAL_PUBLICATION_COMPLETION_PENDING":
                    self._store.fail(idempotency_key, error.code, self._validated_clock())
                raise
            except FinancialCandidateError as error:
                code = "FINANCIAL_CANDIDATE_INVALID"
                self._store.fail(idempotency_key, code, self._validated_clock())
                raise FinancialDailyRefreshError(code) from error
            except GenerationStoreError as error:
                code = "FINANCIAL_GENERATION_INVALID"
                self._store.fail(idempotency_key, code, self._validated_clock())
                raise FinancialDailyRefreshError(code) from error

    def inspect(self, idempotency_key: str) -> dict[str, object]:
        operation = self._store.operation(idempotency_key)
        inspection = self._store.inspect(idempotency_key)
        return {
            key: value.isoformat() if isinstance(value, (date, datetime)) else value
            for key, value in operation.items()
        } | {
            "matched_trigger_count": inspection.matched_trigger_count,
            "pending_trigger_count": inspection.pending_trigger_count,
            "checked_no_structured_change_count": (
                inspection.checked_no_structured_change_count
            ),
            "accepted_instrument_count": inspection.accepted_instrument_count,
            "failed_instrument_count": inspection.failed_instrument_count,
        }

    def release(self, idempotency_key: str) -> None:
        self._store.release(idempotency_key, self._validated_clock())

    def _operation_or_initialize(
        self,
        idempotency_key: str,
        target: str,
    ) -> dict[str, object]:
        try:
            operation = self._store.operation(idempotency_key)
        except FinancialDailyRefreshError as error:
            if error.code != "FINANCIAL_DAILY_REFRESH_NOT_FOUND":
                raise
        else:
            if operation["target_session"].isoformat() != target:
                raise FinancialDailyRefreshError("IDEMPOTENCY_KEY_REUSED")
            if str(operation["status"]) == "failed":
                raise FinancialDailyRefreshError(str(operation["failure_code"]))
            return operation
        pointer = self._lifecycle.current_pointer()
        if pointer is None:
            raise FinancialDailyRefreshError("FINANCIAL_DATASET_NOT_READY")
        generation = self._generations.inspect_root(pointer.generation_manifest_sha256)
        prior_manifest = generation.financial_candidate_manifest_sha256
        if prior_manifest is None:
            raise FinancialDailyRefreshError("FINANCIAL_DATASET_NOT_READY")
        prior = self._candidates.reopen(prior_manifest)
        if target not in generation.research_sessions:
            raise FinancialDailyRefreshError("FINANCIAL_TARGET_EXCEEDS_MARKET")
        prior_complete = (
            prior.discovery_complete_through_session
            or prior.observation_through_session
        )
        baseline = prior.discovery_baseline_session or prior.observation_through_session
        self._store.begin(
            idempotency_key=idempotency_key,
            source_generation_manifest_sha256=pointer.generation_manifest_sha256,
            prior_financial_manifest_sha256=prior_manifest,
            discovery_baseline_session=baseline,
            prior_attempted_through_session=prior.observation_through_session,
            prior_complete_through_session=prior_complete,
            target_session=target,
            started_at=self._validated_clock(),
        )
        return self._store.operation(idempotency_key)

    def _build_candidate(
        self,
        idempotency_key: str,
        operation: Mapping[str, object],
    ) -> FinancialFamilyCandidate:
        source_generation = str(operation["source_generation_manifest_sha256"])
        prior_manifest = str(operation["prior_financial_manifest_sha256"])
        target = operation["target_session"].isoformat()
        lifecycles = self._generations.read_historical_ordinary_a_share_lifecycles(
            source_generation
        )
        current_identities = tuple(
            HistoricalInstrumentIdentity(item.instrument_id, item.ts_code)
            for item in lifecycles
            if item.listed_from <= target and (not item.listed_to or item.listed_to >= target)
        )
        if operation["discovery_evidence"] is None:
            start, end = financial_discovery_window(
                complete_through_session=(
                    operation["prior_complete_through_session"].isoformat()
                ),
                target_session=target,
                earliest_unresolved_date=self._store.earliest_open_gap_date(),
            )
            self._progress(
                {
                    "event": "financial_refresh",
                    "phase": "discovery",
                    "status": "started",
                    "idempotency_key": idempotency_key,
                    "start_date": start,
                    "end_date": end,
                }
            )
            discovery = self._announcement_source.discover(
                start_date=start,
                end_date=end,
                allowed_ts_codes={item.ts_code for item in current_identities},
            )
            self._store.record_discovery(
                idempotency_key=idempotency_key,
                discovery=discovery,
                identities=current_identities,
                recorded_at=self._validated_clock(),
            )
            operation = self._store.operation(idempotency_key)
        candidate_sha = operation["candidate_manifest_sha256"]
        if candidate_sha is not None:
            return self._candidates.reopen(str(candidate_sha))
        attempted = self._store.attempted_instrument_ids(idempotency_key)
        remaining = tuple(
            identity
            for identity in self._store.pending_identities(idempotency_key)
            if identity.instrument_id not in attempted
        )
        contract = self._candidates.collection_contract(prior_manifest)
        collector = DailyFinancialStatementCollector(
            self._database,
            self._root,
            self._financial_source,
            clock=self._clock,
        )
        for identity in remaining:
            collection = collector.collect(
                idempotency_key=idempotency_key,
                generation_manifest_sha256=source_generation,
                contract=contract,
                identities=(identity,),
            )
            checkpoints = collection.snapshot.shards
            if checkpoints:
                try:
                    has_canonical_delta = self._candidates.validate_daily_instrument(
                        collection.snapshot,
                        prior_candidate_manifest_sha256=prior_manifest,
                        observation_through_session=target,
                    )
                except FinancialCandidateError as error:
                    if str(error) != "FINANCIAL_DAILY_INSTRUMENT_INVALID":
                        raise
                    self._store.record_instrument_attempt(
                        idempotency_key=idempotency_key,
                        instrument_id=identity.instrument_id,
                        status="failed",
                        matched_announcement_ids=(),
                        checkpoints=(),
                        failure_code="FINANCIAL_DAILY_INSTRUMENT_INVALID",
                        failure_endpoint="canonical_projection",
                        attempted_at=self._validated_clock(),
                    )
                    status = "failed"
                else:
                    pending_announcement_ids = self._store.pending_announcement_ids(
                        identity.instrument_id
                    )
                    self._store.record_instrument_attempt(
                        idempotency_key=idempotency_key,
                        instrument_id=identity.instrument_id,
                        status="accepted",
                        matched_announcement_ids=(
                            pending_announcement_ids if has_canonical_delta else ()
                        ),
                        checkpoints=checkpoints,
                        failure_code=None,
                        failure_endpoint=None,
                        attempted_at=self._validated_clock(),
                    )
                    status = "accepted"
            else:
                if len(collection.pending) != 1:
                    raise FinancialDailyRefreshError(
                        "FINANCIAL_INSTRUMENT_COLLECTION_INVALID"
                    )
                pending = collection.pending[0]
                self._store.record_instrument_attempt(
                    idempotency_key=idempotency_key,
                    instrument_id=pending.instrument_id,
                    status="failed",
                    matched_announcement_ids=(),
                    checkpoints=(),
                    failure_code=pending.failure_code,
                    failure_endpoint=pending.failure_endpoint,
                    attempted_at=self._validated_clock(),
                )
                status = "failed"
            self._progress(
                {
                    "event": "financial_refresh",
                    "phase": "instrument_checkpoint",
                    "status": status,
                    "idempotency_key": idempotency_key,
                    "instrument_id": identity.instrument_id,
                    "ts_code": identity.ts_code,
                }
            )
        checkpoints = self._store.accepted_checkpoints(idempotency_key)
        inspection = self._store.inspect(idempotency_key)
        finished_at = self._validated_clock()
        snapshot = CompletedFinancialCollection(
            idempotency_key=idempotency_key,
            generation_manifest_sha256=source_generation,
            contract=contract,
            finished_at=finished_at.isoformat(),
            target_count=len(checkpoints),
            shards=checkpoints,
        )
        publication = self._store.publication_state(idempotency_key)
        candidate = self._candidates.rebuild_daily(
            snapshot,
            prior_candidate_manifest_sha256=prior_manifest,
            discovery=publication,
        )
        self._store.record_candidate(
            idempotency_key,
            candidate.manifest_sha256,
            finished_at,
        )
        self._progress(
            {
                "event": "financial_refresh",
                "phase": "candidate",
                "status": "completed",
                "idempotency_key": idempotency_key,
                "candidate_manifest_sha256": candidate.manifest_sha256,
                "accepted_instrument_count": inspection.accepted_instrument_count,
                "failed_instrument_count": inspection.failed_instrument_count,
            }
        )
        return candidate

    def _publish_candidate(
        self,
        idempotency_key: str,
        candidate: FinancialFamilyCandidate,
    ) -> FinancialDailyRefreshOutcome:
        operation = self._store.operation(idempotency_key)
        fingerprint = str(operation["fingerprint"])
        prior = str(operation["prior_financial_manifest_sha256"])
        publication = self._store.publication_state(idempotency_key)
        for attempt in range(4):
            current = self._lifecycle.current_pointer()
            if current is None:
                raise FinancialDailyRefreshError("FINANCIAL_DATASET_NOT_READY")
            descriptor = self._generations.inspect_root(
                current.generation_manifest_sha256
            )
            if descriptor.financial_publication_coordinate == fingerprint:
                completed_at = self._validated_clock()
                self._store.record_head_moved(
                    idempotency_key,
                    descriptor.manifest_sha256,
                    completed_at,
                )
                status = self._store.complete_publication(
                    idempotency_key=idempotency_key,
                    candidate_manifest_sha256=candidate.manifest_sha256,
                    generation_manifest_sha256=descriptor.manifest_sha256,
                    publication=publication,
                    completed_at=completed_at,
                )
                return self._outcome(
                    idempotency_key,
                    status,
                    candidate,
                    descriptor.manifest_sha256,
                    publication,
                )
            current_financial = descriptor.financial_candidate_manifest_sha256
            if current_financial not in {prior, candidate.manifest_sha256}:
                raise FinancialDailyRefreshError("FINANCIAL_TARGET_CHANGED")
            prepared_at = self._validated_clock()
            operation_id = _publication_operation_id(idempotency_key, attempt)
            with mounted_data_mutation_lock(self._database):
                composed = self._generations._compose_prevalidated_financial_candidate(
                    current.generation_manifest_sha256,
                    candidate.manifest_sha256,
                    prepared_at=prepared_at,
                    publication_coordinate=fingerprint,
                )
                self._store.record_composed_generation(
                    idempotency_key,
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
                        candidate_generation_manifest_sha256=composed.manifest_sha256,
                        operation_id=operation_id,
                        prepared_at=prepared_at,
                        daily_financial_publication_key=idempotency_key,
                    )
                except DatasetHeadConflict:
                    self._lifecycle.release_candidate(operation_id=operation_id)
                    continue
                except Exception as error:
                    pointer = self._lifecycle.current_pointer()
                    if (
                        pointer is None
                        or pointer.generation_manifest_sha256
                        != composed.manifest_sha256
                    ):
                        self._lifecycle.release_candidate(operation_id=operation_id)
                        raise
                    raise FinancialDailyRefreshError(
                        "FINANCIAL_PUBLICATION_COMPLETION_PENDING"
                    ) from error
            self._store.record_head_moved(
                idempotency_key,
                moved.generation_manifest_sha256,
                prepared_at,
            )
            status = self._store.complete_publication(
                idempotency_key=idempotency_key,
                candidate_manifest_sha256=candidate.manifest_sha256,
                generation_manifest_sha256=moved.generation_manifest_sha256,
                publication=publication,
                completed_at=prepared_at,
            )
            return self._outcome(
                idempotency_key,
                status,
                candidate,
                moved.generation_manifest_sha256,
                publication,
            )
        raise FinancialDailyRefreshError("FINANCIAL_HEAD_CHANGED_REPEATEDLY")

    def _existing_outcome(
        self,
        idempotency_key: str,
        target: str,
    ) -> FinancialDailyRefreshOutcome | None:
        try:
            operation = self._store.operation(idempotency_key)
        except FinancialDailyRefreshError as error:
            if error.code == "FINANCIAL_DAILY_REFRESH_NOT_FOUND":
                return None
            raise
        if operation["target_session"].isoformat() != target:
            raise FinancialDailyRefreshError("IDEMPOTENCY_KEY_REUSED")
        status = str(operation["status"])
        if status == "failed":
            raise FinancialDailyRefreshError(str(operation["failure_code"]))
        published = operation["published_generation_manifest_sha256"]
        candidate_sha = operation["candidate_manifest_sha256"]
        if published is None or candidate_sha is None:
            return None
        candidate = self._candidates.reopen(str(candidate_sha))
        publication = _candidate_publication(candidate)
        return self._outcome(
            idempotency_key,
            status,
            candidate,
            str(published),
            publication,
        )

    def _outcome(
        self,
        idempotency_key: str,
        status: str,
        candidate: FinancialFamilyCandidate,
        generation_manifest_sha256: str,
        publication: FinancialDiscoveryPublication,
    ) -> FinancialDailyRefreshOutcome:
        inspection = self._store.inspect(idempotency_key)
        return FinancialDailyRefreshOutcome(
            idempotency_key=idempotency_key,
            status=status,
            candidate=candidate,
            generation_manifest_sha256=generation_manifest_sha256,
            attempted_through_session=publication.attempted_through_session,
            complete_through_session=publication.complete_through_session,
            accepted_instrument_count=inspection.accepted_instrument_count,
            failed_instrument_count=inspection.failed_instrument_count,
            pending_instrument_count=publication.pending_instrument_count,
            discovery_gap_count=publication.discovery_gap_count,
        )

    def _validated_clock(self) -> datetime:
        try:
            return _aware_clock(self._clock())
        except FinancialCollectionError as error:
            raise FinancialDailyRefreshError("FINANCIAL_REFRESH_CLOCK_INVALID") from error


def _identity_by_code(
    identities: Sequence[HistoricalInstrumentIdentity],
) -> dict[str, HistoricalInstrumentIdentity]:
    ordered = tuple(sorted(identities, key=lambda item: (item.ts_code, item.instrument_id)))
    if len({item.ts_code for item in ordered}) != len(ordered) or any(
        not item.instrument_id or not item.ts_code for item in ordered
    ):
        raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_IDENTITY_INVALID")
    return {item.ts_code: item for item in ordered}


def _discovery_evidence(discovery: FinancialAnnouncementDiscovery) -> dict[str, object]:
    return {
        "start_date": _iso_date(discovery.start_date),
        "end_date": _iso_date(discovery.end_date),
        "completed_categories": list(discovery.completed_categories),
        "announcements": [
            {
                "announcement_id": item.announcement_id,
                "category": item.category,
                "ts_code": item.ts_code,
                "name": item.name,
                "title": item.title,
                "source_published_date": _iso_date(item.source_published_date),
                "report_period": (
                    None if item.report_period is None else _iso_date(item.report_period)
                ),
                "url": item.url,
            }
            for item in discovery.announcements
        ],
        "gaps": [
            {
                "category": item.category,
                "start_date": _iso_date(item.start_date),
                "end_date": _iso_date(item.end_date),
                "failure_code": item.failure_code,
            }
            for item in discovery.gaps
        ],
        "source_lineage_sha256": discovery.source_lineage_sha256,
    }


def _insert_trigger(
    transaction: object,
    *,
    idempotency_key: str,
    identity: HistoricalInstrumentIdentity,
    announcement: FinancialAnnouncement,
    source_lineage_sha256: str,
    recorded_at: datetime,
) -> None:
    _require_sha256(announcement.announcement_id)
    if announcement.category not in FINANCIAL_ANNOUNCEMENT_CATEGORIES:
        raise FinancialDailyRefreshError("FINANCIAL_ANNOUNCEMENT_INVALID")
    published = _iso_date(announcement.source_published_date)
    report_period = (
        None if announcement.report_period is None else _iso_date(announcement.report_period)
    )
    transaction.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO data.financial_announcement_triggers (
            announcement_id, category, instrument_id, ts_code,
            instrument_name, title, source_published_date, report_period,
            source_url, source_lineage_sha256, status,
            first_seen_operation_key, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  'pending', %s, %s, %s)
        ON CONFLICT (announcement_id) DO NOTHING
        """,
        (
            announcement.announcement_id,
            announcement.category,
            identity.instrument_id,
            identity.ts_code,
            announcement.name,
            announcement.title,
            published,
            report_period,
            announcement.url,
            source_lineage_sha256,
            idempotency_key,
            recorded_at,
            recorded_at,
        ),
    )
    observed = transaction.execute(  # type: ignore[attr-defined]
        """
        SELECT category, instrument_id, ts_code, instrument_name, title,
               source_published_date, report_period, source_url
        FROM data.financial_announcement_triggers
        WHERE announcement_id = %s
        """,
        (announcement.announcement_id,),
    ).fetchone()
    expected = (
        announcement.category,
        identity.instrument_id,
        identity.ts_code,
        announcement.name,
        announcement.title,
        published,
        report_period,
        announcement.url,
    )
    actual = (
        str(observed["category"]),
        str(observed["instrument_id"]),
        str(observed["ts_code"]),
        str(observed["instrument_name"]),
        str(observed["title"]),
        observed["source_published_date"].isoformat(),
        None if observed["report_period"] is None else observed["report_period"].isoformat(),
        str(observed["source_url"]),
    )
    if actual != expected:
        raise FinancialDailyRefreshError("FINANCIAL_ANNOUNCEMENT_ID_COLLISION")


def _upsert_gap(
    transaction: object,
    *,
    idempotency_key: str,
    category: str,
    query_start_date: date,
    query_end_date: date,
    unresolved_from_date: date,
    failure_code: str,
    recorded_at: datetime,
) -> None:
    if category not in FINANCIAL_ANNOUNCEMENT_CATEGORIES or not failure_code:
        raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_GAP_INVALID")
    gap_id = _sha(
        {
            "category": category,
            "unresolved_from_date": unresolved_from_date.isoformat(),
        }
    )
    transaction.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO data.financial_discovery_gaps (
            gap_id, category, query_start_date, query_end_date,
            unresolved_from_date, failure_code, status,
            first_seen_operation_key, last_seen_operation_key,
            created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s, %s, %s)
        ON CONFLICT (gap_id) DO UPDATE
        SET query_start_date = LEAST(
                data.financial_discovery_gaps.query_start_date,
                EXCLUDED.query_start_date
            ),
            query_end_date = GREATEST(
                data.financial_discovery_gaps.query_end_date,
                EXCLUDED.query_end_date
            ),
            failure_code = EXCLUDED.failure_code,
            last_seen_operation_key = EXCLUDED.last_seen_operation_key,
            updated_at = EXCLUDED.updated_at
        WHERE data.financial_discovery_gaps.status = 'open'
        """,
        (
            gap_id,
            category,
            query_start_date,
            query_end_date,
            unresolved_from_date,
            failure_code,
            idempotency_key,
            idempotency_key,
            recorded_at,
            recorded_at,
        ),
    )


def _checkpoint_payload(checkpoint: FinancialShardCheckpoint) -> dict[str, object]:
    return {
        "ordinal": checkpoint.ordinal,
        "endpoint": checkpoint.endpoint,
        "instrument_id": checkpoint.instrument_id,
        "ts_code": checkpoint.ts_code,
        "shard": checkpoint.shard,
        "status": checkpoint.status,
        "batch_sha256": checkpoint.batch_sha256,
        "collected_at": checkpoint.collected_at,
        "first_observed_at": checkpoint.first_observed_at,
    }


def _checkpoint_from_payload(value: object) -> FinancialShardCheckpoint:
    if not isinstance(value, Mapping) or set(value) != {
        "ordinal",
        "endpoint",
        "instrument_id",
        "ts_code",
        "shard",
        "status",
        "batch_sha256",
        "collected_at",
        "first_observed_at",
    }:
        raise FinancialDailyRefreshError("FINANCIAL_ATTEMPT_CHECKPOINT_INVALID")
    checkpoint = FinancialShardCheckpoint(
        ordinal=int(value["ordinal"]),
        endpoint=str(value["endpoint"]),
        instrument_id=str(value["instrument_id"]),
        ts_code=str(value["ts_code"]),
        shard=str(value["shard"]),
        status=str(value["status"]),
        batch_sha256=(
            None if value["batch_sha256"] is None else str(value["batch_sha256"])
        ),
        collected_at=(
            None if value["collected_at"] is None else str(value["collected_at"])
        ),
        first_observed_at=(
            None
            if value["first_observed_at"] is None
            else str(value["first_observed_at"])
        ),
    )
    if (
        checkpoint.endpoint not in FINANCIAL_ENDPOINTS
        or checkpoint.status != "completed"
        or checkpoint.batch_sha256 is None
        or checkpoint.collected_at is None
        or checkpoint.first_observed_at is None
    ):
        raise FinancialDailyRefreshError("FINANCIAL_ATTEMPT_CHECKPOINT_INVALID")
    _require_sha256(checkpoint.batch_sha256)
    return checkpoint


def financial_discovery_window(
    *,
    complete_through_session: str,
    target_session: str,
    earliest_unresolved_date: str | None,
) -> tuple[str, str]:
    complete = _date(complete_through_session)
    target = _date(target_session)
    if target < complete:
        raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_TARGET_REGRESSION")
    start = complete - timedelta(days=6)
    if earliest_unresolved_date is not None:
        start = min(start, _date(earliest_unresolved_date))
    return start.isoformat(), target.isoformat()


def _candidate_publication(
    candidate: FinancialFamilyCandidate,
) -> FinancialDiscoveryPublication:
    if (
        candidate.discovery_baseline_session is None
        or candidate.discovery_complete_through_session is None
        or candidate.source_lineage_sha256 is None
        or candidate.readiness_status
        not in {"ready", "ready_with_pending", "ready_with_gaps"}
    ):
        raise FinancialDailyRefreshError("FINANCIAL_DAILY_CANDIDATE_INVALID")
    return FinancialDiscoveryPublication(
        baseline_session=candidate.discovery_baseline_session,
        attempted_through_session=candidate.observation_through_session,
        complete_through_session=candidate.discovery_complete_through_session,
        source_lineage_sha256=candidate.source_lineage_sha256,
        readiness_status=cast(
            Literal["ready", "ready_with_pending", "ready_with_gaps"],
            candidate.readiness_status,
        ),
        pending_instrument_count=candidate.pending_instrument_count,
        discovery_gap_count=candidate.discovery_gap_count,
        earliest_unresolved_date=candidate.earliest_unresolved_date,
    )


def _publication_operation_id(idempotency_key: str, attempt: int) -> str:
    identity = hashlib.sha256(f"{idempotency_key}:{attempt}".encode()).hexdigest()[:32]
    return f"daily-financial-refresh:{identity}"


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise FinancialDailyRefreshError("FINANCIAL_DATE_INVALID") from error


def _iso_date(value: str) -> str:
    return _date(value).isoformat()


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise FinancialDailyRefreshError("FINANCIAL_SHA256_INVALID")


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class FinancialPendingInstrument:
    instrument_id: str
    ts_code: str
    failure_code: str
    failure_endpoint: str


@dataclass(frozen=True)
class DailyFinancialCollectionOutcome:
    snapshot: CompletedFinancialCollection
    pending: tuple[FinancialPendingInstrument, ...]


@dataclass(frozen=True)
class _PreparedBatch:
    checkpoint: FinancialShardCheckpoint
    parameters: dict[str, object]
    response: RawSourceResponse
    content: bytes
    payload_sha256: str
    extent: tuple[str, str] | None


class DailyFinancialStatementCollector:
    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        source: FinancialRawSource,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._batches = RawFinancialBatchStore(mount_root)
        self._source = source
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(
        self,
        *,
        idempotency_key: str,
        generation_manifest_sha256: str,
        contract: FinancialCollectionContract,
        identities: Sequence[HistoricalInstrumentIdentity],
    ) -> DailyFinancialCollectionOutcome:
        _validate_request(
            idempotency_key,
            generation_manifest_sha256,
            contract,
            identities,
        )
        accepted: list[FinancialShardCheckpoint] = []
        pending: list[FinancialPendingInstrument] = []
        for identity in identities:
            prepared: list[_PreparedBatch] = []
            failed: FinancialPendingInstrument | None = None
            for endpoint in FINANCIAL_ENDPOINTS:
                checkpoint = FinancialShardCheckpoint(
                    ordinal=len(prepared),
                    endpoint=endpoint,
                    instrument_id=identity.instrument_id,
                    ts_code=identity.ts_code,
                    shard="complete-history",
                    status="pending",
                    batch_sha256=None,
                    collected_at=None,
                )
                parameters: dict[str, object] = {"ts_code": identity.ts_code}
                try:
                    response = self._source.query_raw(
                        endpoint,
                        params=parameters,
                        fields=dict(contract.endpoint_fields)[endpoint],
                    )
                    content, payload_sha256, extent = _raw_batch_content(
                        checkpoint=checkpoint,
                        parameters=parameters,
                        expected_fields=dict(contract.endpoint_fields)[endpoint],
                        response=response,
                        suspected_truncation_row_count=dict(
                            contract.suspected_truncation_row_counts
                        )[endpoint],
                    )
                except RawSourceError as error:
                    failed = FinancialPendingInstrument(
                        instrument_id=identity.instrument_id,
                        ts_code=identity.ts_code,
                        failure_code=_source_failure_code(error),
                        failure_endpoint=endpoint,
                    )
                    break
                except FinancialCollectionError as error:
                    failed = FinancialPendingInstrument(
                        instrument_id=identity.instrument_id,
                        ts_code=identity.ts_code,
                        failure_code=error.code,
                        failure_endpoint=endpoint,
                    )
                    break
                except Exception:
                    failed = FinancialPendingInstrument(
                        instrument_id=identity.instrument_id,
                        ts_code=identity.ts_code,
                        failure_code="SOURCE_FAILURE",
                        failure_endpoint=endpoint,
                    )
                    break
                prepared.append(
                    _PreparedBatch(
                        checkpoint=checkpoint,
                        parameters=parameters,
                        response=response,
                        content=content,
                        payload_sha256=payload_sha256,
                        extent=extent,
                    )
                )
            if failed is not None:
                pending.append(failed)
                continue
            accepted.extend(self._commit_instrument(prepared))
        finished_at = _aware_clock(self._clock())
        checkpoints = tuple(
            FinancialShardCheckpoint(
                ordinal=ordinal,
                endpoint=item.endpoint,
                instrument_id=item.instrument_id,
                ts_code=item.ts_code,
                shard=item.shard,
                status=item.status,
                batch_sha256=item.batch_sha256,
                collected_at=item.collected_at,
                first_observed_at=item.first_observed_at,
            )
            for ordinal, item in enumerate(accepted)
        )
        return DailyFinancialCollectionOutcome(
            snapshot=CompletedFinancialCollection(
                idempotency_key=idempotency_key,
                generation_manifest_sha256=generation_manifest_sha256,
                contract=contract,
                finished_at=finished_at.isoformat(),
                target_count=len(checkpoints),
                shards=checkpoints,
            ),
            pending=tuple(pending),
        )

    def _commit_instrument(
        self,
        prepared: Sequence[_PreparedBatch],
    ) -> tuple[FinancialShardCheckpoint, ...]:
        if tuple(item.checkpoint.endpoint for item in prepared) != FINANCIAL_ENDPOINTS:
            raise FinancialCollectionError("FINANCIAL_INSTRUMENT_COLLECTION_INCOMPLETE")
        collected_at = _aware_clock(self._clock())
        stored = [(item, self._batches.store(item.content)) for item in prepared]
        checkpoints: list[FinancialShardCheckpoint] = []
        with self._database.transaction() as transaction:
            for item, batch_sha256 in stored:
                transaction.execute(
                    """
                    INSERT INTO data.financial_raw_batches (
                        batch_sha256, payload_sha256, endpoint, parameters,
                        returned_fields, row_count, source_date_start,
                        source_date_end, byte_count, first_collected_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (batch_sha256) DO NOTHING
                    """,
                    (
                        batch_sha256,
                        item.payload_sha256,
                        item.checkpoint.endpoint,
                        Jsonb(item.parameters),
                        Jsonb(list(item.response.fields)),
                        len(item.response.items),
                        None if item.extent is None else item.extent[0],
                        None if item.extent is None else item.extent[1],
                        len(item.content),
                        collected_at,
                    ),
                )
                observed = transaction.execute(
                    """
                    SELECT first_collected_at
                    FROM data.financial_raw_batches
                    WHERE batch_sha256 = %s
                    """,
                    (batch_sha256,),
                ).fetchone()
                if observed is None:
                    raise FinancialCollectionError("RAW_BATCH_WRITE_FAILED")
                checkpoints.append(
                    FinancialShardCheckpoint(
                        ordinal=len(checkpoints),
                        endpoint=item.checkpoint.endpoint,
                        instrument_id=item.checkpoint.instrument_id,
                        ts_code=item.checkpoint.ts_code,
                        shard=item.checkpoint.shard,
                        status="completed",
                        batch_sha256=batch_sha256,
                        collected_at=collected_at.isoformat(),
                        first_observed_at=observed["first_collected_at"].isoformat(),
                    )
                )
        return tuple(checkpoints)


def _validate_request(
    idempotency_key: str,
    generation_manifest_sha256: str,
    contract: FinancialCollectionContract,
    identities: Sequence[HistoricalInstrumentIdentity],
) -> None:
    if not idempotency_key or idempotency_key != idempotency_key.strip():
        raise FinancialCollectionError("INVALID_IDEMPOTENCY_KEY")
    if len(generation_manifest_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in generation_manifest_sha256
    ):
        raise FinancialCollectionError("INVALID_GENERATION")
    try:
        FinancialCollectionContract.from_descriptor(contract.descriptor())
    except ValueError as error:
        raise FinancialCollectionError("INVALID_FINANCIAL_CONTRACT") from error
    identity_keys = [(item.instrument_id, item.ts_code) for item in identities]
    if identity_keys != sorted(set(identity_keys)):
        raise FinancialCollectionError("FINANCIAL_TARGET_IDENTITIES_INVALID")


def _aware_clock(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise FinancialCollectionError("COLLECTION_TIME_INVALID")
    return value.astimezone(UTC)


__all__ = (
    "DailyFinancialCollectionOutcome",
    "DailyFinancialRefreshService",
    "DailyFinancialStatementCollector",
    "FinancialDailyRefreshError",
    "FinancialDailyRefreshInspection",
    "FinancialDailyRefreshOutcome",
    "FinancialDailyRefreshStore",
    "FinancialPendingInstrument",
    "financial_discovery_window",
)

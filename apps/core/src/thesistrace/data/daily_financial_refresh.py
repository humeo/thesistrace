from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Literal, cast

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
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
from thesistrace.data.financial_disclosures import (
    FinancialDisclosureDiscovery,
    FinancialDisclosureSource,
    disclosure_periods,
)
from thesistrace.data.financial_report_progress import (
    reconciliation_ids,
    record_recheck,
)
from thesistrace.data.generation_files import AddressedFileError
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

if TYPE_CHECKING:
    from thesistrace.data.financial_indicator_collection import DailyIndicatorCollection
    from thesistrace.data.financial_indicator_source import FinancialIndicatorProvider


class FinancialDailyRefreshError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


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
    matched_trigger_count: int
    checked_no_structured_change_count: int
    canonical_changed: bool


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
        discovery: FinancialDisclosureDiscovery,
        identities: Sequence[HistoricalInstrumentIdentity],
        recorded_at: datetime,
    ) -> None:
        recorded = _aware_clock(recorded_at)
        identity_by_code = _identity_by_code(identities)
        expected = set(disclosure_periods(discovery.start_date, discovery.end_date))
        completed = set(discovery.completed_periods)
        missing = {gap.report_period for gap in discovery.gaps}
        if completed & missing or completed | missing != expected:
            raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_PERIOD_SET_INVALID")
        _require_sha256(discovery.source_lineage_sha256)
        evidence = _discovery_evidence(discovery) | {
            "instrument_ids": {code: item.instrument_id for code, item in identity_by_code.items()},
        }
        requirements = []
        for report in discovery.reports:
            identity = identity_by_code.get(report.ts_code)
            if (
                identity is None
                or report.report_period not in completed
                or not report.report_period <= report.actual_date <= discovery.end_date
            ):
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_REPORT_INVALID")
            requirements.extend(
                dict(
                    instrument_id=identity.instrument_id,
                    endpoint=endpoint,
                    report_period=report.report_period,
                    actual_date=report.actual_date,
                )
                for endpoint in (*FINANCIAL_ENDPOINTS, "fina_indicator")
            )
        with self._database.transaction() as tx:
            operation = tx.execute(
                "SELECT * FROM data.financial_daily_refresh_operations "
                "WHERE idempotency_key=%s FOR UPDATE",
                (idempotency_key,),
            ).fetchone()
            if operation is None or operation["status"] != "running":
                raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_RUNNING")
            if discovery.end_date != operation["target_session"].isoformat():
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_TARGET_MISMATCH")
            if operation["discovery_evidence"] is not None:
                if operation["discovery_evidence"] != evidence:
                    raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_REPLAY_MISMATCH")
                return
            tx.execute(
                """INSERT INTO data.financial_report_targets
                   (instrument_id, endpoint, report_period, actual_date)
                   SELECT instrument_id, endpoint, report_period, actual_date
                   FROM jsonb_to_recordset(%s) AS r(instrument_id text, endpoint text,
                                                   report_period date, actual_date date)
                   ON CONFLICT (instrument_id, endpoint, report_period) DO UPDATE
                   SET actual_date=LEAST(financial_report_targets.actual_date, EXCLUDED.actual_date)
                """,
                (Jsonb(requirements),),
            )
            tx.execute(
                """UPDATE data.financial_daily_refresh_operations
                   SET discovery_start_date=%s, discovery_end_date=%s, discovery_evidence=%s,
                       source_lineage_sha256=%s, updated_at=%s WHERE idempotency_key=%s""",
                (
                    discovery.start_date,
                    discovery.end_date,
                    Jsonb(evidence),
                    discovery.source_lineage_sha256,
                    recorded,
                    idempotency_key,
                ),
            )

    def prepare_reports(self, idempotency_key, observed_reports, recorded_at):
        with self._database.transaction() as tx:
            operation = tx.execute(
                "SELECT * FROM data.financial_daily_refresh_operations "
                "WHERE idempotency_key=%s FOR UPDATE",
                (idempotency_key,),
            ).fetchone()
            if operation is None or operation["discovery_evidence"] is None:
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")
            if operation["statement_instrument_ids"] is not None:
                return
            target = operation["target_session"].isoformat()
            identities = operation["discovery_evidence"]["instrument_ids"]
            # Reconcile against accepted published bytes, not a prior failed publication's ledger.
            inventory = []
            for endpoint, (digest, reports) in observed_reports.items():
                _require_sha256(digest)
                inventory.extend(
                    dict(
                        instrument_id=instrument,
                        endpoint=endpoint,
                        report_period=period,
                        evidence=digest,
                    )
                    for instrument, period in reports
                )
            ids = list(identities.values())
            tx.execute(
                "UPDATE data.financial_report_targets SET resolved_evidence_sha256=NULL "
                "WHERE instrument_id=ANY(%s::text[]) AND actual_date<=%s",
                (ids, target),
            )
            tx.execute(
                """UPDATE data.financial_report_targets AS target
                   SET resolved_evidence_sha256=inventory.evidence
                   FROM jsonb_to_recordset(%s) AS inventory(
                       instrument_id text, endpoint text, report_period date, evidence text)
                   WHERE target.instrument_id=inventory.instrument_id
                     AND target.endpoint=inventory.endpoint
                     AND target.report_period=inventory.report_period""",
                (Jsonb(inventory),),
            )
            pending = tx.execute(
                """SELECT DISTINCT instrument_id FROM data.financial_report_targets
                   WHERE endpoint<>'fina_indicator' AND actual_date<=%s
                     AND resolved_evidence_sha256 IS NULL AND instrument_id=ANY(%s::text[])
                   ORDER BY instrument_id""",
                (target, ids),
            ).fetchall()
            selected = tuple(
                dict.fromkeys(
                    [
                        *(str(row["instrument_id"]) for row in pending),
                        *reconciliation_ids(
                            tx, ids, "statements", exclude={row["instrument_id"] for row in pending}
                        ),
                    ]
                )
            )
            tx.execute(
                "UPDATE data.financial_daily_refresh_operations SET statement_instrument_ids=%s, "
                "updated_at=%s WHERE idempotency_key=%s",
                (Jsonb(selected), _aware_clock(recorded_at), idempotency_key),
            )

    def planned_identities(self, idempotency_key):
        operation = self.operation(idempotency_key)
        selected = set(operation["statement_instrument_ids"])
        return tuple(
            HistoricalInstrumentIdentity(instrument, code)
            for code, instrument in operation["discovery_evidence"]["instrument_ids"].items()
            if instrument in selected
        )

    def pending_identities(self, idempotency_key):
        self._require_running_discovery(idempotency_key)
        operation = self.operation(idempotency_key)
        with self._database.transaction() as tx:
            rows = tx.execute(
                "SELECT DISTINCT instrument_id FROM data.financial_report_targets "
                "WHERE endpoint<>'fina_indicator' AND resolved_evidence_sha256 IS NULL "
                "AND actual_date<=%s",
                (operation["target_session"],),
            ).fetchall()
        selected = {row["instrument_id"] for row in rows}
        return tuple(
            HistoricalInstrumentIdentity(instrument, code)
            for code, instrument in operation["discovery_evidence"]["instrument_ids"].items()
            if instrument in selected
        )

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
            _checkpoint_from_payload(item) for row in rows for item in row["checkpoints"]
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
        canonical_changed: bool,
        checkpoints: Sequence[FinancialShardCheckpoint],
        failure_code: str | None,
        failure_endpoint: str | None,
        attempted_at: datetime,
    ) -> None:
        attempted = _aware_clock(attempted_at)
        # The historical column remains audit storage. New processing supplies a Canonical
        # change flag, encoded as a nonempty marker for the retained receipt counters.
        matches = ("canonical-change",) if canonical_changed else ()
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
            record_recheck(transaction, instrument_id, "statements", failure_code)

    def publication_state(self, idempotency_key: str) -> FinancialDiscoveryPublication:
        operation = self.operation(idempotency_key)
        evidence = operation["discovery_evidence"]
        if evidence is None:
            raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")
        with self._database.transaction() as tx:
            pending = tx.execute(
                """SELECT instrument_id, min(actual_date) AS since
                   FROM data.financial_report_targets
                   WHERE endpoint<>'fina_indicator' AND resolved_evidence_sha256 IS NULL
                     AND actual_date<=%s GROUP BY instrument_id""",
                (operation["target_session"],),
            ).fetchall()
            failures = tx.execute(
                "SELECT instrument_id FROM data.financial_refresh_instrument_attempts "
                "WHERE idempotency_key=%s AND status='failed'",
                (idempotency_key,),
            ).fetchall()
        pending_ids = {row["instrument_id"] for row in (*pending, *failures)}
        gaps = evidence["gaps"]
        unresolved_dates = [row["since"] for row in pending]
        if gaps:
            unresolved_dates.append(operation["prior_complete_through_session"] + timedelta(days=1))
        if failures:
            unresolved_dates.append(operation["target_session"])
        return FinancialDiscoveryPublication(
            baseline_session=operation["discovery_baseline_session"].isoformat(),
            attempted_through_session=operation["target_session"].isoformat(),
            complete_through_session=(
                operation["prior_complete_through_session"] if gaps else operation["target_session"]
            ).isoformat(),
            source_lineage_sha256=_sha(
                {"discovery": operation["source_lineage_sha256"], "pending": sorted(pending_ids)}
            ),
            readiness_status=(
                "ready_with_gaps" if gaps else "ready_with_pending" if pending_ids else "ready"
            ),
            pending_instrument_count=len(pending_ids),
            discovery_gap_count=len(gaps),
            earliest_unresolved_date=min(unresolved_dates).isoformat()
            if unresolved_dates
            else None,
        )

    def candidate_publication_state(
        self,
        idempotency_key: str,
        received_reports: Mapping[str, set[tuple[str, str]]],
    ) -> FinancialDiscoveryPublication:
        """Derive readiness from the immutable candidate that would be published."""
        operation = self.operation(idempotency_key)
        evidence = operation["discovery_evidence"]
        if evidence is None:
            raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")
        accepted = {
            (instrument_id, endpoint, report_period)
            for endpoint in FINANCIAL_ENDPOINTS
            for instrument_id, report_period in received_reports.get(endpoint, set())
        }
        with self._database.transaction() as transaction:
            requirements = transaction.execute(
                """
                SELECT instrument_id, endpoint, report_period, actual_date
                FROM data.financial_report_targets
                WHERE endpoint <> 'fina_indicator' AND actual_date <= %s
                """,
                (operation["target_session"],),
            ).fetchall()
            failures = transaction.execute(
                """
                SELECT instrument_id
                FROM data.financial_refresh_instrument_attempts
                WHERE idempotency_key = %s AND status = 'failed'
                """,
                (idempotency_key,),
            ).fetchall()
        missing_since: dict[str, date] = {}
        for requirement in requirements:
            identity = (
                str(requirement["instrument_id"]),
                str(requirement["endpoint"]),
                requirement["report_period"].isoformat(),
            )
            if identity in accepted:
                continue
            instrument_id = identity[0]
            actual_date = requirement["actual_date"]
            previous = missing_since.get(instrument_id)
            if previous is None or actual_date < previous:
                missing_since[instrument_id] = actual_date
        pending_ids = set(missing_since)
        pending_ids.update(str(row["instrument_id"]) for row in failures)
        gaps = evidence["gaps"]
        unresolved_dates = list(missing_since.values())
        if gaps:
            unresolved_dates.append(
                operation["prior_complete_through_session"] + timedelta(days=1)
            )
        if failures:
            unresolved_dates.append(operation["target_session"])
        return FinancialDiscoveryPublication(
            baseline_session=operation["discovery_baseline_session"].isoformat(),
            attempted_through_session=operation["target_session"].isoformat(),
            complete_through_session=(
                operation["prior_complete_through_session"]
                if gaps
                else operation["target_session"]
            ).isoformat(),
            source_lineage_sha256=_sha(
                {"discovery": operation["source_lineage_sha256"], "pending": sorted(pending_ids)}
            ),
            readiness_status=(
                "ready_with_gaps"
                if gaps
                else "ready_with_pending"
                if pending_ids
                else "ready"
            ),
            pending_instrument_count=len(pending_ids),
            discovery_gap_count=len(gaps),
            earliest_unresolved_date=(
                min(unresolved_dates).isoformat() if unresolved_dates else None
            ),
        )

    def inspect(self, idempotency_key: str) -> FinancialDailyRefreshInspection:
        operation = self.operation(idempotency_key)
        with self._database.transaction() as tx:
            counts = tx.execute(
                """SELECT count(*) FILTER (WHERE status='accepted') AS accepted,
                   count(*) FILTER (WHERE status='failed') AS failed,
                   count(*) FILTER (WHERE status='accepted'
                       AND jsonb_array_length(matched_announcement_ids)>0) AS changed,
                   count(*) FILTER (WHERE status='accepted'
                       AND jsonb_array_length(matched_announcement_ids)=0) AS unchanged
                   FROM data.financial_refresh_instrument_attempts WHERE idempotency_key=%s""",
                (idempotency_key,),
            ).fetchone()
            pending = tx.execute(
                "SELECT count(DISTINCT (instrument_id, report_period)) n "
                "FROM data.financial_report_targets "
                "WHERE resolved_evidence_sha256 IS NULL AND actual_date<=%s",
                (operation["target_session"],),
            ).fetchone()["n"]
        return FinancialDailyRefreshInspection(
            idempotency_key,
            str(operation["status"]),
            operation["target_session"].isoformat(),
            int(counts["changed"]),
            int(pending),
            int(counts["unchanged"]),
            int(counts["accepted"]),
            int(counts["failed"]),
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

    def record_indicator_collection(
        self,
        idempotency_key: str,
        result: DailyIndicatorCollection,
        recorded_at: datetime,
    ) -> None:
        payload = asdict(result)
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """UPDATE data.financial_daily_refresh_operations
                   SET indicator_collection=COALESCE(indicator_collection, '{}'::jsonb) || %s,
                       updated_at=%s
                   WHERE idempotency_key=%s AND status='running'
                     AND (indicator_collection IS NULL
                          OR indicator_collection - 'candidate_diagnostic'=%s)""",
                (Jsonb(payload), _aware_clock(recorded_at), idempotency_key, Jsonb(payload)),
            ).rowcount
        if changed != 1:
            raise FinancialDailyRefreshError("FINANCIAL_INDICATOR_RESULT_CONFLICT")

    def record_indicator_retained(self, idempotency_key: str, recorded_at: datetime) -> None:
        """Persist diagnostic outcome without changing the immutable collection facts."""
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """UPDATE data.financial_daily_refresh_operations
                   SET indicator_collection=jsonb_set(indicator_collection,
                       '{candidate_diagnostic}', %s), updated_at=%s
                   WHERE idempotency_key=%s AND status='running'
                     AND indicator_collection IS NOT NULL
                     AND indicator_candidate_manifest_sha256 IS NULL
                     AND published_generation_manifest_sha256 IS NULL""",
                (
                    Jsonb({"retained_reason": "INDICATOR_COVERAGE_UNAVAILABLE"}),
                    _aware_clock(recorded_at),
                    idempotency_key,
                ),
            ).rowcount
        if changed != 1:
            raise FinancialDailyRefreshError("FINANCIAL_INDICATOR_CANDIDATE_CONFLICT")

    def record_indicator_candidate(
        self,
        idempotency_key: str,
        digest: str,
        recorded_at: datetime,
        *,
        received_reports: Sequence[tuple[str, str]],
    ) -> None:
        _require_sha256(digest)
        with self._database.transaction() as transaction:
            changed = transaction.execute(
                """UPDATE data.financial_daily_refresh_operations
                   SET indicator_candidate_manifest_sha256=%s, updated_at=%s,
                       indicator_collection=indicator_collection - 'candidate_diagnostic'
                   WHERE idempotency_key=%s AND status='running'
                     AND published_generation_manifest_sha256 IS NULL
                     AND (indicator_candidate_manifest_sha256 IS NULL
                          OR indicator_candidate_manifest_sha256=%s)
                   RETURNING target_session, discovery_evidence""",
                (digest, _aware_clock(recorded_at), idempotency_key, digest),
            ).fetchone()
            if changed is None:
                raise FinancialDailyRefreshError("FINANCIAL_INDICATOR_CANDIDATE_CONFLICT")
            # The merged candidate is authoritative: a later conflict can reopen a
            # report, while a response omitting an older accepted row cannot erase it.
            scope = list(changed["discovery_evidence"]["instrument_ids"].values())
            transaction.execute(
                """UPDATE data.financial_report_targets SET resolved_evidence_sha256=NULL
                   WHERE endpoint='fina_indicator' AND instrument_id=ANY(%s::text[])
                     AND actual_date<=%s""",
                (scope, changed["target_session"]),
            )
            transaction.execute(
                """UPDATE data.financial_report_targets AS target SET resolved_evidence_sha256=%s
                   FROM jsonb_to_recordset(%s) AS report(instrument_id text, report_period date)
                   WHERE target.endpoint='fina_indicator'
                     AND target.instrument_id=report.instrument_id
                     AND target.report_period=report.report_period
                     AND target.instrument_id=ANY(%s::text[]) AND target.actual_date<=%s""",
                (digest, Jsonb([dict(instrument_id=instrument, report_period=period)
                                for instrument, period in received_reports]),
                 scope, changed["target_session"]),
            )

    def record_candidate(
        self,
        idempotency_key: str,
        candidate_manifest_sha256: str,
        recorded_at: datetime,
        *,
        received_reports: Mapping[str, set[tuple[str, str]]],
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
                RETURNING target_session, discovery_evidence
                """,
                (
                    candidate_manifest_sha256,
                    recorded,
                    idempotency_key,
                    candidate_manifest_sha256,
                ),
            ).fetchone()
            if changed is None:
                raise FinancialDailyRefreshError("FINANCIAL_CANDIDATE_RECORD_CONFLICT")
            operation = changed
            if operation["discovery_evidence"] is None:
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")
            scope = list(operation["discovery_evidence"]["instrument_ids"].values())
            inventory = [
                {
                    "instrument_id": instrument_id,
                    "endpoint": endpoint,
                    "report_period": report_period,
                }
                for endpoint in FINANCIAL_ENDPOINTS
                for instrument_id, report_period in received_reports.get(endpoint, set())
            ]
            transaction.execute(
                """
                UPDATE data.financial_report_targets
                SET resolved_evidence_sha256 = NULL
                WHERE endpoint <> 'fina_indicator'
                  AND instrument_id = ANY(%s::text[]) AND actual_date <= %s
                """,
                (scope, operation["target_session"]),
            )
            transaction.execute(
                """
                UPDATE data.financial_report_targets AS target
                SET resolved_evidence_sha256 = %s
                FROM jsonb_to_recordset(%s) AS report(
                    instrument_id text, endpoint text, report_period date
                )
                WHERE target.instrument_id = report.instrument_id
                  AND target.endpoint = report.endpoint
                  AND target.report_period = report.report_period
                  AND target.instrument_id = ANY(%s::text[])
                  AND target.actual_date <= %s
                """,
                (
                    candidate_manifest_sha256,
                    Jsonb(inventory),
                    scope,
                    operation["target_session"],
                ),
            )

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
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                "SELECT indicator_collection, indicator_candidate_manifest_sha256, target_session "
                "FROM data.financial_daily_refresh_operations WHERE idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if operation is None:
                raise FinancialDailyRefreshError("FINANCIAL_DAILY_REFRESH_NOT_FOUND")
            pending_rows = transaction.execute(
                "SELECT DISTINCT instrument_id FROM data.financial_report_targets "
                "WHERE resolved_evidence_sha256 IS NULL AND actual_date<=%s",
                (operation["target_session"],),
            ).fetchall()
            failed_rows = transaction.execute(
                "SELECT instrument_id FROM data.financial_refresh_instrument_attempts "
                "WHERE idempotency_key=%s AND status='failed'",
                (idempotency_key,),
            ).fetchall()
            pending_ids = {str(row["instrument_id"]) for row in pending_rows}
            failed_ids = {str(row["instrument_id"]) for row in failed_rows}
            pending_ids.update(failed_ids)
            indicator = operation["indicator_collection"]
            if indicator is not None:
                indicator_failures = {str(item[0]) for item in indicator["failures"]}
                if operation["indicator_candidate_manifest_sha256"] is None:
                    pending_ids.update(indicator["pending_instrument_ids"])
                pending_ids.update(indicator_failures)
                failed_ids.update(indicator_failures)
            readiness = (
                "ready_with_gaps"
                if publication.discovery_gap_count
                else "ready_with_pending"
                if pending_ids
                else "ready"
            )
            status = {
                "ready": "succeeded",
                "ready_with_pending": "succeeded_with_pending",
                "ready_with_gaps": "succeeded_with_gaps",
            }[readiness]
            outcome = {
                "candidate_manifest_sha256": candidate_manifest_sha256,
                "generation_manifest_sha256": generation_manifest_sha256,
                "attempted_through_session": publication.attempted_through_session,
                "complete_through_session": publication.complete_through_session,
                "readiness_status": readiness,
                "pending_instrument_count": len(pending_ids),
                "failed_instrument_count": len(failed_ids),
                "pending_instrument_ids": sorted(pending_ids),
                "failed_instrument_ids": sorted(failed_ids),
                "discovery_gap_count": publication.discovery_gap_count,
            }
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
            if operation["published_generation_manifest_sha256"] == generation_manifest_sha256:
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
        disclosure_source: FinancialDisclosureSource,
        financial_source: FinancialRawSource,
        *,
        indicator_provider: FinancialIndicatorProvider,
        clock: Callable[[], datetime] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
        ownership_guard: Callable[[], None] | None = None,
        publication_guard: (
            Callable[
                [PostgresTransaction, str, str, datetime],
                AbstractContextManager[None],
            ]
            | None
        ) = None,
        publication_operation_id: str | None = None,
        publication_lease_seconds: float = 900,
        financial_source_window_selector: Callable[[str, str], None] | None = None,
    ) -> None:
        if publication_lease_seconds <= 0:
            raise ValueError("Financial publication lease must be positive")
        self._database = database
        self._root = Path(mount_root).resolve()
        self._disclosure_source = disclosure_source
        self._financial_source = financial_source
        self._indicator_provider = indicator_provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._progress = progress or (lambda _event: None)
        self._ownership_guard = ownership_guard or (lambda: None)
        self._publication_guard = publication_guard
        self._publication_operation_id = publication_operation_id
        self._publication_lease_seconds = publication_lease_seconds
        self._financial_source_window_selector = financial_source_window_selector
        self._store = FinancialDailyRefreshStore(database)
        self._candidates = FinancialCandidateStore(self._root)
        self._generations = MountedGenerationStore(self._root)
        self._lifecycle = DatasetLifecycle(database, self._root)

    def _completed_stage(self, key: str, phase: str, started: float, **counts: object) -> None:
        self._progress(
            {
                "event": "financial_refresh",
                "phase": phase,
                "status": "completed",
                "idempotency_key": key,
                "duration_ms": round((perf_counter() - started) * 1000),
                **counts,
            }
        )

    def publish(
        self,
        *,
        idempotency_key: str,
        observation_through_session: str,
    ) -> FinancialDailyRefreshOutcome:
        from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore

        target = _iso_date(observation_through_session)
        with self._database.session_advisory_lock("financial-daily-refresh"):
            self._ownership_guard()
            existing = self._existing_outcome(idempotency_key, target)
            if existing is not None:
                return existing
            operation = self._operation_or_initialize(idempotency_key, target)
            try:
                indicators = FinancialIndicatorCandidateStore(
                    self._root, progress=lambda event: self._progress({
                        "event": "financial_refresh", "idempotency_key": idempotency_key, **event,
                    }),
                )
                with indicators.validation_session():
                    candidate = self._build_candidate(idempotency_key, operation, indicators)
                    return self._publish_candidate(idempotency_key, candidate, indicators)
            except FinancialDailyRefreshError as error:
                if not error.retryable and not _daily_failure_is_retryable(error.code):
                    self._store.fail(idempotency_key, error.code, self._validated_clock())
                raise
            except FinancialCandidateError as error:
                retryable = _has_filesystem_failure(error)
                code = (
                    "REFRESH_INFRASTRUCTURE_FAILURE" if retryable else "FINANCIAL_CANDIDATE_INVALID"
                )
                if not retryable:
                    self._store.fail(idempotency_key, code, self._validated_clock())
                raise FinancialDailyRefreshError(code, retryable=retryable) from error
            except GenerationStoreError as error:
                retryable = _has_filesystem_failure(error)
                code = (
                    "REFRESH_INFRASTRUCTURE_FAILURE"
                    if retryable
                    else "FINANCIAL_GENERATION_INVALID"
                )
                if not retryable:
                    self._store.fail(idempotency_key, code, self._validated_clock())
                raise FinancialDailyRefreshError(code, retryable=retryable) from error

            finally:
                self._candidates.close()

    def inspect(self, idempotency_key: str) -> dict[str, object]:
        operation = self._store.operation(idempotency_key)
        inspection = self._store.inspect(idempotency_key)
        return {
            key: value.isoformat() if isinstance(value, (date, datetime)) else value
            for key, value in operation.items()
        } | {
            "matched_trigger_count": inspection.matched_trigger_count,
            "pending_trigger_count": inspection.pending_trigger_count,
            "checked_no_structured_change_count": (inspection.checked_no_structured_change_count),
            "accepted_instrument_count": inspection.accepted_instrument_count,
            "failed_instrument_count": (
                inspection.failed_instrument_count
                if operation["published_outcome"] is None
                else int(operation["published_outcome"]["failed_instrument_count"])
            ),
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
            prior.discovery_complete_through_session or prior.observation_through_session
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

    def _published_report_inventory(self, generation_digest, target, indicators):
        generation = self._generations.inspect_root(generation_digest)
        digest = generation.financial_candidate_manifest_sha256
        inventory = {
            endpoint: (digest, reports)
            for endpoint, reports in self._candidates.report_inventory(
                digest, through=target
            ).items()
        }
        for family in generation.families:
            if family.family_id == "equity.financial_indicator":
                inventory["fina_indicator"] = (
                    family.manifest_sha256,
                    indicators.report_inventory(
                        family.manifest_sha256,
                        through=target,
                    ),
                )
        return inventory

    def _build_candidate(
        self,
        idempotency_key: str,
        operation: Mapping[str, object],
        indicators,
    ) -> FinancialFamilyCandidate:
        source_generation = str(operation["source_generation_manifest_sha256"])
        prior_manifest = str(operation["prior_financial_manifest_sha256"])
        target = operation["target_session"].isoformat()
        lifecycles = self._generations.read_historical_ordinary_a_share_lifecycles(
            source_generation
        )
        discovery_identities = tuple(
            HistoricalInstrumentIdentity(item.instrument_id, item.ts_code)
            for item in lifecycles
            if item.listed_from <= target
        )
        if operation["discovery_evidence"] is None:
            start, end = financial_discovery_window(
                complete_through_session=(operation["prior_complete_through_session"].isoformat()),
                target_session=target,
                earliest_unresolved_date=None,
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
            self._ownership_guard()
            discovery_started = perf_counter()
            if self._financial_source_window_selector is not None:
                self._financial_source_window_selector(start, end)
            discovery = self._disclosure_source.discover(
                start_date=start,
                end_date=end,
                allowed_ts_codes={item.ts_code for item in discovery_identities},
            )
            self._store.record_discovery(
                idempotency_key=idempotency_key,
                discovery=discovery,
                identities=discovery_identities,
                recorded_at=self._validated_clock(),
            )
            self._completed_stage(
                idempotency_key,
                "discovery",
                discovery_started,
                report_count=len(discovery.reports),
                gap_count=len(discovery.gaps),
            )
            self._ownership_guard()
            operation = self._store.operation(idempotency_key)
        if operation["statement_instrument_ids"] is None:
            inventory_started = perf_counter()
            inventory = self._published_report_inventory(source_generation, target, indicators)
            self._completed_stage(idempotency_key, "published_inventory", inventory_started)
            planning_started = perf_counter()
            self._store.prepare_reports(
                idempotency_key,
                inventory,
                self._validated_clock(),
            )
            self._completed_stage(idempotency_key, "report_planning", planning_started)
            operation = self._store.operation(idempotency_key)
        if operation["indicator_collection"] is None:
            from thesistrace.data.financial_indicator_candidate import (
                FinancialIndicatorCandidateStore,
            )
            from thesistrace.data.financial_indicator_collection import (
                FinancialIndicatorDailyCollector,
            )

            generation = self._generations.inspect_root(source_generation)
            calendar = generation.research_sessions
            if target not in calendar:
                raise FinancialDailyRefreshError("FINANCIAL_TARGET_NOT_IN_CALENDAR")
            indicator_family = next(
                (
                    family
                    for family in generation.families
                    if family.family_id == "equity.financial_indicator"
                ),
                None,
            )
            initial_instrument_ids = ()
            if indicator_family is not None:
                covered = FinancialIndicatorCandidateStore(self._root).reopen(
                    indicator_family.manifest_sha256,
                )["instrument_ids"]
                initial_instrument_ids = tuple(
                    item.instrument_id
                    for item in lifecycles
                    if item.listed_from <= target and item.ts_code not in covered
                )
            indicator_collection_started = perf_counter()
            indicator_result = FinancialIndicatorDailyCollector(
                self._database,
                self._root,
                self._indicator_provider,
                clock=self._clock,
                ownership_guard=self._ownership_guard,
            ).collect(
                operation_key=idempotency_key,
                identities=tuple(
                    HistoricalInstrumentIdentity(item.instrument_id, item.ts_code)
                    for item in lifecycles
                    if item.listed_from <= target
                ),
                checked_through=target,
                research_session_index=calendar.index(target),
                initial_instrument_ids=initial_instrument_ids,
            )
            self._store.record_indicator_collection(
                idempotency_key,
                indicator_result,
                self._validated_clock(),
            )
            self._completed_stage(
                idempotency_key,
                "indicator_collection",
                indicator_collection_started,
                scheduled_count=len(indicator_result.scheduled_instrument_ids),
                collected_count=len(indicator_result.collection_evidence_sha256s),
                failed_count=len(indicator_result.failures),
            )
            operation = self._store.operation(idempotency_key)
        if operation["indicator_candidate_manifest_sha256"] is None:
            self._build_indicator_candidate(idempotency_key, operation, indicators)
            operation = self._store.operation(idempotency_key)
        candidate_sha = operation["candidate_manifest_sha256"]
        if candidate_sha is not None:
            return self._candidates.reopen(str(candidate_sha))
        if self._financial_source_window_selector is not None:
            evidence = operation["discovery_evidence"]
            if not isinstance(evidence, Mapping):
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_NOT_RECORDED")
            try:
                discovery_start = _iso_date(str(evidence["start_date"]))
                discovery_end = _iso_date(str(evidence["end_date"]))
            except (KeyError, ValueError) as error:
                raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_REPLAY_MISMATCH") from error
            self._financial_source_window_selector(discovery_start, discovery_end)
        attempted = self._store.attempted_instrument_ids(idempotency_key)
        planned = self._store.planned_identities(idempotency_key)
        remaining = tuple(
            identity
            for identity in planned
            if identity.instrument_id not in attempted
        )
        loading_started = perf_counter()
        self._candidates.prepare_instruments(
            prior_candidate_manifest_sha256=prior_manifest,
            generation_manifest_sha256=source_generation,
            observation_through_session=target,
            instrument_ids=frozenset(identity.instrument_id for identity in planned),
        )
        self._completed_stage(idempotency_key, "statement_values", loading_started)
        contract = self._candidates.collection_contract(prior_manifest)
        collector = DailyFinancialStatementCollector(
            self._database,
            self._root,
            self._financial_source,
            clock=self._clock,
        )
        statements_started = perf_counter()
        for identity in remaining:
            self._ownership_guard()
            collection = collector.collect(
                idempotency_key=idempotency_key,
                generation_manifest_sha256=source_generation,
                contract=contract,
                identities=(identity,),
            )
            checkpoints = collection.snapshot.shards
            if checkpoints:
                try:
                    validated = self._candidates.validate_daily_instrument(
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
                        canonical_changed=False,
                        checkpoints=(),
                        failure_code="FINANCIAL_DAILY_INSTRUMENT_INVALID",
                        failure_endpoint="canonical_projection",
                        attempted_at=self._validated_clock(),
                    )
                    status = "failed"
                else:
                    self._store.record_instrument_attempt(
                        idempotency_key=idempotency_key,
                        instrument_id=identity.instrument_id,
                        status="accepted",
                        canonical_changed=validated.canonical_changed,
                        checkpoints=checkpoints,
                        failure_code=None,
                        failure_endpoint=None,
                        attempted_at=self._validated_clock(),
                    )
                    status = "accepted"
            else:
                if len(collection.pending) != 1:
                    raise FinancialDailyRefreshError("FINANCIAL_INSTRUMENT_COLLECTION_INVALID")
                pending = collection.pending[0]
                self._store.record_instrument_attempt(
                    idempotency_key=idempotency_key,
                    instrument_id=pending.instrument_id,
                    status="failed",
                    canonical_changed=False,
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
            self._ownership_guard()
        self._completed_stage(
            idempotency_key,
            "statements",
            statements_started,
            scheduled_count=len(remaining),
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
        self._ownership_guard()
        candidate_started = perf_counter()
        prepared = self._candidates.prepare_daily(
            snapshot,
            prior_candidate_manifest_sha256=prior_manifest,
            discovery=publication,
        )
        self._completed_stage(idempotency_key, "candidate_prepare", candidate_started)
        reconcile_started = perf_counter()
        candidate_publication = self._store.candidate_publication_state(
            idempotency_key,
            prepared.received_reports,
        )
        self._completed_stage(idempotency_key, "candidate_reconcile", reconcile_started)
        finalize_started = perf_counter()
        candidate = self._candidates.finalize_daily(prepared, discovery=candidate_publication)
        received_reports = self._candidates.report_inventory(
            candidate.manifest_sha256, through=target,
        )
        self._completed_stage(idempotency_key, "candidate_finalize", finalize_started)
        self._store.record_candidate(
            idempotency_key,
            candidate.manifest_sha256,
            finished_at,
            received_reports=received_reports,
        )
        self._ownership_guard()
        self._progress(
            {
                "event": "financial_refresh",
                "phase": "candidate",
                "duration_ms": round((perf_counter() - candidate_started) * 1000),
                "status": "completed",
                "idempotency_key": idempotency_key,
                "candidate_manifest_sha256": candidate.manifest_sha256,
                "accepted_instrument_count": inspection.accepted_instrument_count,
                "failed_instrument_count": inspection.failed_instrument_count,
            }
        )
        return candidate

    def _build_indicator_candidate(
        self, key: str, operation: Mapping[str, object], candidates,
    ) -> None:
        source = str(operation["source_generation_manifest_sha256"])
        descriptor = self._generations.inspect_root(source)
        target = operation["target_session"].isoformat()
        identities = {
            item.ts_code: item.instrument_id
            for item in self._generations.read_financial_indicator_identities(
                source, through_session=target
            )
        }
        with mounted_data_mutation_lock(self._database):
            preflight_started = perf_counter()
            with self._database.transaction() as transaction:
                discoveries_rows = transaction.execute(
                    """SELECT discovery_evidence FROM data.financial_daily_refresh_operations
                       WHERE discovery_evidence IS NOT NULL AND discovery_evidence ? 'reports'
                         AND target_session<=%s""",
                    (operation["target_session"],),
                ).fetchall()
                rows = transaction.execute(
                    """SELECT observation_sha256 FROM data.financial_indicator_collections
                       WHERE instrument_id=ANY(%s::text[]) AND checked_through<=%s""",
                    (list(identities.values()), operation["target_session"]),
                ).fetchall()
            evidence = {str(row["observation_sha256"]) for row in rows}
            discoveries = set()
            for row in discoveries_rows:
                discovery = dict(row["discovery_evidence"])
                lineage = discovery.pop("source_lineage_sha256")
                discovery_scope = discovery.pop("instrument_ids")
                discoveries.add(
                    RawFinancialBatchStore(self._root).store(
                        canonical_json_bytes(
                            {
                                "source": "indicator-disclosure-check",
                                "instrument_ids": discovery_scope,
                                "discovery": discovery,
                                "source_lineage_sha256": lineage,
                            }
                        )
                    )
                )
            for family in descriptor.families:
                if family.family_id == "equity.financial_indicator":
                    # Read the addressed manifest to establish coverage before replaying
                    # its complete source history. Incremental build validates the
                    # old candidate before reusing its partitions.
                    previous = candidates.reopen(family.manifest_sha256)
                    evidence.update(previous["collection_evidence_sha256s"])
                    discoveries.update(previous["discovery_evidence_sha256s"])
            sessions = candidates.available_sessions(
                collection_evidence_sha256s=sorted(evidence),
                instrument_ids=identities,
                sessions=tuple(day for day in descriptor.research_sessions if day <= target),
                discovery_evidence_sha256s=sorted(discoveries),
            )
            self._progress(
                {
                    "event": "financial_refresh",
                    "phase": "indicator_coverage",
                    "status": "completed",
                    "idempotency_key": key,
                    "duration_ms": round((perf_counter() - preflight_started) * 1000),
                    "outcome": "available" if sessions else "retained",
                    "failure_code": None if sessions else "INDICATOR_COVERAGE_UNAVAILABLE",
                }
            )
            if not sessions:
                self._store.record_indicator_retained(key, self._validated_clock())
                return
            # Report readiness is derived from all retained disclosure and observation
            # evidence below; only failed source requests need an external pending marker.
            unresolved = {instrument: target
                          for instrument, _code in operation["indicator_collection"]["failures"]}
            build_started = perf_counter()
            digest = candidates.build(
                collection_evidence_sha256s=sorted(evidence),
                instrument_ids=identities,
                sessions=sessions,
                unresolved_sources=unresolved,
                discovery_evidence_sha256s=sorted(discoveries),
                published_base_reference=self._generations.published_indicator_reference(source),
            )
            self._progress(
                {
                    "event": "financial_refresh",
                    "phase": "indicator_build",
                    "status": "completed",
                    "idempotency_key": key,
                    "duration_ms": round((perf_counter() - build_started) * 1000),
                }
            )
            self._store.record_indicator_candidate(
                key, digest, self._validated_clock(),
                received_reports=sorted(candidates.report_inventory(digest, through=target)),
            )

    def _publish_candidate(
        self,
        idempotency_key: str,
        candidate: FinancialFamilyCandidate,
        indicators,
    ) -> FinancialDailyRefreshOutcome:
        operation = self._store.operation(idempotency_key)
        fingerprint = str(operation["fingerprint"])
        prior = str(operation["prior_financial_manifest_sha256"])
        publication = self._store.publication_state(idempotency_key)
        indicator_candidate = operation["indicator_candidate_manifest_sha256"]
        source = self._generations.inspect_root(str(operation["source_generation_manifest_sha256"]))
        prior_indicator = next(
            (
                family.manifest_sha256
                for family in source.families
                if family.family_id == "equity.financial_indicator"
            ),
            None,
        )
        for attempt in range(4):
            self._ownership_guard()
            current = self._lifecycle.current_pointer()
            if current is None:
                raise FinancialDailyRefreshError("FINANCIAL_DATASET_NOT_READY")
            descriptor = self._generations.inspect_root(current.generation_manifest_sha256)
            if (
                operation["publication_head_moved_at"] is not None
                or descriptor.financial_publication_coordinate == fingerprint
            ):
                composed = operation["composed_generation_manifest_sha256"]
                if composed is None:
                    raise FinancialDailyRefreshError("FINANCIAL_PUBLICATION_RECONCILIATION_INVALID")
                return reconcile_daily_financial_publication(
                    self._database,
                    self._root,
                    idempotency_key=idempotency_key,
                    generation_manifest_sha256=str(composed),
                    completed_at=self._validated_clock(),
                )
            current_indicator = next(
                (
                    family.manifest_sha256
                    for family in descriptor.families
                    if family.family_id == "equity.financial_indicator"
                ),
                None,
            )
            if indicator_candidate is not None and current_indicator not in {
                prior_indicator,
                indicator_candidate,
            }:
                raise FinancialDailyRefreshError("FINANCIAL_INDICATOR_TARGET_CHANGED")
            current_financial = descriptor.financial_candidate_manifest_sha256
            if current_financial not in {prior, candidate.manifest_sha256}:
                raise FinancialDailyRefreshError("FINANCIAL_TARGET_CHANGED")
            prepared_at = self._validated_clock()
            operation_id = (
                _publication_operation_id(idempotency_key, attempt)
                if self._publication_operation_id is None
                else f"{self._publication_operation_id}:{attempt}"
            )
            with mounted_data_mutation_lock(self._database):
                composition_started = perf_counter()
                self._candidates.verify_for_publication(candidate.manifest_sha256)
                composed = self._generations._compose_prevalidated_financial_candidate(
                    current.generation_manifest_sha256,
                    candidate.manifest_sha256,
                    prepared_at=prepared_at,
                    publication_coordinate=fingerprint,
                )
                if indicator_candidate is not None:
                    composed = self._generations._compose_incremental_indicator_candidate(
                        composed.manifest_sha256,
                        str(indicator_candidate),
                        published_generation_sha256=current.generation_manifest_sha256,
                        prepared_at=prepared_at,
                        indicator_store=indicators,
                    )
                self._completed_stage(idempotency_key, "composition", composition_started)
                publication_started = perf_counter()
                self._store.record_composed_generation(
                    idempotency_key,
                    composed.manifest_sha256,
                    prepared_at,
                )
                self._lifecycle.protect_prevalidated_candidate(
                    operation_id=operation_id,
                    generation_manifest_sha256=composed.manifest_sha256,
                    lease_seconds=self._publication_lease_seconds,
                )
                self._ownership_guard()
                try:
                    moved = self._lifecycle.compare_and_swap_head(
                        expected_generation_manifest_sha256=(current.generation_manifest_sha256),
                        candidate_generation_manifest_sha256=composed.manifest_sha256,
                        operation_id=operation_id,
                        prepared_at=prepared_at,
                        daily_financial_publication_key=idempotency_key,
                        publication_guard=self._selected_publication_guard(
                            current.generation_manifest_sha256,
                            composed.manifest_sha256,
                            prepared_at,
                        ),
                    )
                except DatasetHeadConflict:
                    self._lifecycle.release_candidate(operation_id=operation_id)
                    continue
                except Exception as error:
                    pointer = self._lifecycle.current_pointer()
                    if (
                        pointer is None
                        or pointer.generation_manifest_sha256 != composed.manifest_sha256
                    ):
                        self._lifecycle.release_candidate(operation_id=operation_id)
                        raise
                    raise FinancialDailyRefreshError(
                        "FINANCIAL_PUBLICATION_COMPLETION_PENDING"
                    ) from error
            try:
                self._store.record_head_moved(
                    idempotency_key,
                    moved.generation_manifest_sha256,
                    prepared_at,
                )
                self._ownership_guard()
                status = self._store.complete_publication(
                    idempotency_key=idempotency_key,
                    candidate_manifest_sha256=candidate.manifest_sha256,
                    generation_manifest_sha256=moved.generation_manifest_sha256,
                    publication=publication,
                    completed_at=prepared_at,
                )
            except Exception as error:
                pointer = self._lifecycle.current_pointer()
                if (
                    pointer is not None
                    and pointer.generation_manifest_sha256 == moved.generation_manifest_sha256
                ):
                    raise FinancialDailyRefreshError(
                        "FINANCIAL_PUBLICATION_COMPLETION_PENDING"
                    ) from error
                raise
            self._completed_stage(idempotency_key, "publication", publication_started)
            return self._outcome(
                idempotency_key,
                status,
                candidate,
                moved.generation_manifest_sha256,
                publication,
            )
        raise FinancialDailyRefreshError("FINANCIAL_HEAD_CHANGED_REPEATEDLY")

    def _selected_publication_guard(
        self,
        expected_manifest: str,
        candidate_manifest: str,
        prepared_at: datetime,
    ) -> Callable[[PostgresTransaction], AbstractContextManager[None]] | None:
        selected = self._publication_guard
        if selected is None:
            return None

        def guard(transaction: PostgresTransaction) -> AbstractContextManager[None]:
            return selected(
                transaction,
                expected_manifest,
                candidate_manifest,
                prepared_at,
            )

        return guard

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
        return _daily_financial_outcome(
            self._store,
            self._candidates,
            mount_root=self._root,
            idempotency_key=idempotency_key,
            status=status,
            candidate=candidate,
            generation_manifest_sha256=generation_manifest_sha256,
            publication=publication,
        )

    def _validated_clock(self) -> datetime:
        try:
            return _aware_clock(self._clock())
        except FinancialCollectionError as error:
            raise FinancialDailyRefreshError("FINANCIAL_REFRESH_CLOCK_INVALID") from error


def reconcile_daily_financial_publication(
    database: PostgresDatabase,
    mount_root: Path | str,
    *,
    idempotency_key: str,
    generation_manifest_sha256: str,
    completed_at: datetime,
) -> FinancialDailyRefreshOutcome:
    """Finish the durable Financial receipt after its Generation became Head."""
    store = FinancialDailyRefreshStore(database)
    candidates = FinancialCandidateStore(Path(mount_root).resolve())
    operation = store.operation(idempotency_key)
    status = str(operation["status"])
    if status == "failed":
        raise FinancialDailyRefreshError(str(operation["failure_code"]))
    candidate_sha = operation["candidate_manifest_sha256"]
    composed_sha = operation["composed_generation_manifest_sha256"]
    published_sha = operation["published_generation_manifest_sha256"]
    if candidate_sha is None or (
        composed_sha != generation_manifest_sha256 and published_sha != generation_manifest_sha256
    ):
        raise FinancialDailyRefreshError("FINANCIAL_PUBLICATION_RECONCILIATION_INVALID")
    descriptor = MountedGenerationStore(Path(mount_root)).inspect_root(generation_manifest_sha256)
    indicator_candidate = operation["indicator_candidate_manifest_sha256"]
    published_indicator = next(
        (
            family.manifest_sha256
            for family in descriptor.families
            if family.family_id == "equity.financial_indicator"
        ),
        None,
    )
    if (
        descriptor.financial_publication_coordinate != str(operation["fingerprint"])
        or descriptor.financial_candidate_manifest_sha256 != candidate_sha
        or (indicator_candidate is not None and published_indicator != indicator_candidate)
    ):
        raise FinancialDailyRefreshError("FINANCIAL_PUBLICATION_RECONCILIATION_INVALID")
    candidate = candidates.reopen(str(candidate_sha))
    publication = _candidate_publication(candidate)
    if status == "running":
        if operation["publication_head_moved_at"] is None:
            store.record_head_moved(
                idempotency_key,
                generation_manifest_sha256,
                completed_at,
            )
        status = store.complete_publication(
            idempotency_key=idempotency_key,
            candidate_manifest_sha256=candidate.manifest_sha256,
            generation_manifest_sha256=generation_manifest_sha256,
            publication=publication,
            completed_at=completed_at,
        )
    elif published_sha != generation_manifest_sha256:
        raise FinancialDailyRefreshError("FINANCIAL_PUBLICATION_RECONCILIATION_INVALID")
    return _daily_financial_outcome(
        store,
        candidates,
        mount_root=Path(mount_root),
        idempotency_key=idempotency_key,
        status=status,
        candidate=candidate,
        generation_manifest_sha256=generation_manifest_sha256,
        publication=publication,
    )


def _daily_financial_outcome(
    store: FinancialDailyRefreshStore,
    candidates: FinancialCandidateStore,
    *,
    mount_root: Path,
    idempotency_key: str,
    status: str,
    candidate: FinancialFamilyCandidate,
    generation_manifest_sha256: str,
    publication: FinancialDiscoveryPublication,
) -> FinancialDailyRefreshOutcome:
    inspection = store.inspect(idempotency_key)
    operation = store.operation(idempotency_key)
    prior_manifest = str(operation["prior_financial_manifest_sha256"])
    published_outcome = operation["published_outcome"]
    indicator_changed = False
    indicator_candidate = operation["indicator_candidate_manifest_sha256"]
    if indicator_candidate is not None:
        from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore

        source = MountedGenerationStore(mount_root).inspect_root(
            str(operation["source_generation_manifest_sha256"]),
        )
        prior_indicator = next(
            (
                family.manifest_sha256
                for family in source.families
                if family.family_id == "equity.financial_indicator"
            ),
            None,
        )
        indicators = FinancialIndicatorCandidateStore(mount_root)
        indicator_changed = prior_indicator is None or (
            indicators.canonical_projection_sha256(prior_indicator)
            != indicators.canonical_projection_sha256(str(indicator_candidate))
        )
    return FinancialDailyRefreshOutcome(
        idempotency_key=idempotency_key,
        status=status,
        candidate=candidate,
        generation_manifest_sha256=generation_manifest_sha256,
        attempted_through_session=publication.attempted_through_session,
        complete_through_session=publication.complete_through_session,
        accepted_instrument_count=inspection.accepted_instrument_count,
        failed_instrument_count=int(published_outcome["failed_instrument_count"]),
        pending_instrument_count=int(published_outcome["pending_instrument_count"]),
        discovery_gap_count=publication.discovery_gap_count,
        matched_trigger_count=inspection.matched_trigger_count,
        checked_no_structured_change_count=inspection.checked_no_structured_change_count,
        canonical_changed=(
            indicator_changed
            or candidates.canonical_projection_sha256(prior_manifest)
            != candidates.canonical_projection_sha256(candidate.manifest_sha256)
        ),
    )


def _identity_by_code(
    identities: Sequence[HistoricalInstrumentIdentity],
) -> dict[str, HistoricalInstrumentIdentity]:
    ordered = tuple(sorted(identities, key=lambda item: (item.ts_code, item.instrument_id)))
    if len({item.ts_code for item in ordered}) != len(ordered) or any(
        not item.instrument_id or not item.ts_code for item in ordered
    ):
        raise FinancialDailyRefreshError("FINANCIAL_DISCOVERY_IDENTITY_INVALID")
    return {item.ts_code: item for item in ordered}


def _discovery_evidence(discovery: FinancialDisclosureDiscovery) -> dict[str, object]:
    return {
        "start_date": discovery.start_date,
        "end_date": discovery.end_date,
        "completed_periods": list(discovery.completed_periods),
        "reports": [asdict(report) for report in discovery.reports],
        "gaps": [asdict(gap) for gap in discovery.gaps],
        "source_lineage_sha256": discovery.source_lineage_sha256,
    }


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
        batch_sha256=(None if value["batch_sha256"] is None else str(value["batch_sha256"])),
        collected_at=(None if value["collected_at"] is None else str(value["collected_at"])),
        first_observed_at=(
            None if value["first_observed_at"] is None else str(value["first_observed_at"])
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
        or candidate.readiness_status not in {"ready", "ready_with_pending", "ready_with_gaps"}
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


def _daily_failure_is_retryable(code: str) -> bool:
    return code in {
        "FINANCIAL_HEAD_CHANGED_REPEATEDLY",
        "FINANCIAL_PUBLICATION_COMPLETION_PENDING",
    }


def _has_filesystem_failure(error: BaseException) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, (AddressedFileError, OSError)):
            return True
        current = current.__cause__ or current.__context__
    return False


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

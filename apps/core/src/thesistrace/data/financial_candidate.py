from __future__ import annotations

import bisect
import hashlib
import json
import tempfile
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.data.fields import FINANCIAL_FIELDS
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    FINANCIAL_SOURCE_CONTRACT_VERSION,
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialCollectionError,
    FinancialDateShard,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.data.financial_disclosures import DISCOVERY_COVERAGE_KINDS
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_schema import (
    GENERATION_MANIFEST_MAX_BYTES,
    GENERATION_OBJECT_MAX_BYTES,
    GENERATION_ROW_PARTITION_COUNT,
    GENERATION_SESSION_PARTITION_COUNT,
)
from thesistrace.data.generation_store import (
    GenerationStoreError,
    HistoricalInstrumentLifecycle,
    MountedGenerationStore,
)
from thesistrace.data.io_metrics import record_parquet_scan
from thesistrace.publication.serialization import (
    ParquetContractError,
    ParquetWriterContract,
    canonical_json_bytes,
    canonicalize_parquet_rows,
    parquet_bytes,
)

_FAMILY_ID = "equity.financial_pit"
_SCHEMA_CONTRACT = "financial-pit-wide-v1"
_FAMILY_FORMAT = "thesistrace-financial-family-candidate"
_TABLE_FORMAT = "thesistrace-financial-version-table"
_EVIDENCE_INDEX_FORMAT = "thesistrace-financial-evidence-index"
_EVIDENCE_CHUNK_FORMAT = "thesistrace-financial-evidence-chunk"
_VERSION = 1
_EVIDENCE_CHUNK_SIZE = 512
_ENDPOINT_TABLES = {
    "income": "income_statement_versions",
    "balancesheet": "balance_sheet_versions",
    "cashflow": "cash_flow_statement_versions",
}
_TABLE_ENDPOINTS = {value: key for key, value in _ENDPOINT_TABLES.items()}
_METADATA_FIELDS = (
    "instrument_id",
    "source_endpoint",
    "source_report_period",
    "source_report_type",
    "source_company_type",
    "source_end_type",
    "source_published_date",
    "first_observed_at",
    "first_observed_session",
    "source_available_session",
    "effective_available_session",
    "availability_status",
    "revision_basis",
    "coverage_role",
    "logical_revision_group_sha256",
    "source_row_sha256",
    "source_batch_sha256",
)


class _PublishedFinancialRowIndex:
    """Task-local, disk-backed view of the latest published logical rows."""

    def __init__(self, root: Path) -> None:
        # Keep the current API/worker import graph free of optional task runtimes.
        # SQLite is loaded only while building or validating a financial candidate.
        import sqlite3

        self._temporary = tempfile.TemporaryDirectory(
            prefix=".financial-published-index-",
            dir=root,
        )
        self._connection = sqlite3.connect(
            str(Path(self._temporary.name) / "rows.sqlite3")
        )
        self._connection.execute("PRAGMA journal_mode=OFF")
        self._connection.execute("PRAGMA synchronous=OFF")
        self._connection.execute("PRAGMA temp_store=FILE")
        self._connection.executescript(
            """
            CREATE TABLE logical_rows (
                endpoint TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                source_row_sha256 TEXT NOT NULL,
                source_report_period TEXT NOT NULL,
                source_published_date TEXT NOT NULL,
                source_report_type TEXT NOT NULL,
                availability_status TEXT NOT NULL,
                row_json BLOB NOT NULL
            );
            CREATE TABLE delta_rows (
                endpoint TEXT NOT NULL,
                source_row_sha256 TEXT NOT NULL,
                effective_available_session TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                source_report_period TEXT NOT NULL,
                source_report_type TEXT NOT NULL,
                source_company_type TEXT NOT NULL,
                source_end_type TEXT NOT NULL,
                row_json BLOB NOT NULL,
                PRIMARY KEY (endpoint, source_row_sha256)
            ) WITHOUT ROWID;
            CREATE INDEX delta_rows_by_sort_key ON delta_rows (
                endpoint, effective_available_session, instrument_id,
                source_report_period, source_report_type,
                source_company_type, source_end_type, source_row_sha256
            );
            """
        )

    def add(self, endpoint: str, row: Mapping[str, object]) -> None:
        self._connection.execute(
            """
            INSERT INTO logical_rows(
                endpoint, instrument_id, source_row_sha256,
                source_report_period, source_published_date,
                source_report_type, availability_status, row_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                endpoint,
                str(row["instrument_id"]),
                str(row["source_row_sha256"]),
                str(row["source_report_period"]),
                str(row["source_published_date"]),
                str(row["source_report_type"]),
                str(row["availability_status"]),
                canonical_json_bytes(dict(row)),
            ),
        )

    def finish(self) -> None:
        # Loading is append-only. Building the lookup index after the scan avoids
        # hours of random B-tree maintenance while retaining bounded memory.
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS logical_rows_by_instrument
            ON logical_rows (endpoint, instrument_id)
            """
        )
        self._connection.commit()

    def rows(self, endpoint: str, instrument_id: str) -> tuple[dict[str, object], ...]:
        values = self._connection.execute(
            """
            SELECT row_json FROM logical_rows
            WHERE endpoint = ? AND instrument_id = ?
            ORDER BY source_row_sha256
            """,
            (endpoint, instrument_id),
        ).fetchall()
        return tuple(json.loads(bytes(value[0])) for value in values)

    def quarantined_hashes(self) -> set[str]:
        return {
            str(row[0])
            for row in self._connection.execute(
                """
                SELECT source_row_sha256 FROM logical_rows
                WHERE availability_status = 'quarantined'
                """
            )
        }

    def clear_deltas(self) -> None:
        self._connection.execute("DELETE FROM delta_rows")

    def add_delta(self, endpoint: str, row: Mapping[str, object]) -> None:
        self._connection.execute(
            """
            INSERT OR REPLACE INTO delta_rows(
                endpoint, source_row_sha256, effective_available_session,
                instrument_id, source_report_period, source_report_type,
                source_company_type, source_end_type, row_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                endpoint,
                str(row["source_row_sha256"]),
                str(row["effective_available_session"]),
                str(row["instrument_id"]),
                str(row["source_report_period"]),
                str(row["source_report_type"]),
                str(row["source_company_type"]),
                str(row["source_end_type"]),
                canonical_json_bytes(dict(row)),
            ),
        )

    def delta_count(self, endpoint: str) -> int:
        row = self._connection.execute(
            "SELECT count(*) FROM delta_rows WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def deltas(self, endpoint: str) -> Iterator[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT row_json FROM delta_rows
            WHERE endpoint = ?
            ORDER BY effective_available_session, instrument_id,
                     source_report_period, source_report_type,
                     source_company_type, source_end_type, source_row_sha256
            """,
            (endpoint,),
        )
        for row in rows:
            yield json.loads(bytes(row[0]))

    def report_inventory(self, endpoint: str, through: str) -> set[tuple[str, str]]:
        rows = (
            {
                "instrument_id": row[0],
                "source_report_period": row[1],
                "source_published_date": row[2],
                "source_report_type": row[3],
                "availability_status": row[4],
            }
            for row in self._connection.execute(
                """
                SELECT instrument_id, source_report_period, source_published_date,
                       source_report_type, availability_status
                FROM logical_rows WHERE endpoint = ?
                """,
                (endpoint,),
            )
        )
        return set(_statement_report_inventory(rows, through))

    def close(self) -> None:
        self._connection.close()
        self._temporary.cleanup()
_REQUIRED_SOURCE_FIELDS = {
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "update_flag",
}
_FINANCIAL_HISTORY_IDENTITY_FIELDS = (
    "instrument_id",
    "source_report_period",
    "source_report_type",
    "source_company_type",
    "source_end_type",
    "availability_status",
)
_FINANCIAL_HISTORY_VERSION_FIELDS = (
    "effective_available_session",
    "update_flag",
    "source_published_date",
    "ann_date",
    "first_observed_at",
    "source_row_sha256",
)


class FinancialCandidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class FinancialFamilyCandidate:
    manifest_sha256: str
    family_id: str
    schema_contract: str
    coverage_start: str
    observation_through_session: str
    reconciliation_status: str
    revision_coverage: str
    table_names: tuple[str, ...]
    row_count: int
    quarantined_row_count: int
    raw_batch_count: int
    discovery_baseline_session: str | None = None
    discovery_complete_through_session: str | None = None
    readiness_status: str = "ready"
    pending_instrument_count: int = 0
    discovery_gap_count: int = 0
    earliest_unresolved_date: str | None = None
    source_lineage_sha256: str | None = None


@dataclass(frozen=True)
class ValidatedFinancialInstrument:
    canonical_changed: bool
    report_periods: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class FinancialDiscoveryPublication:
    baseline_session: str
    attempted_through_session: str
    complete_through_session: str
    source_lineage_sha256: str
    readiness_status: Literal["ready", "ready_with_pending", "ready_with_gaps"]
    pending_instrument_count: int
    discovery_gap_count: int
    earliest_unresolved_date: str | None


@dataclass(frozen=True)
class FinancialSourceObservation:
    endpoint: str
    instrument_id: str
    ts_code: str
    source_fields: tuple[str, ...]
    source_values: tuple[object, ...]
    first_observed_at: str
    raw_batch_sha256: str

    def source(self) -> dict[str, object]:
        return dict(zip(self.source_fields, self.source_values, strict=True))


@dataclass(frozen=True)
class CanonicalFinancialVersion:
    endpoint: str
    instrument_id: str
    source_fields: tuple[str, ...]
    source_values: tuple[object, ...]
    source_published_date: str
    source_available_session: str
    first_observed_at: str
    first_observed_session: str
    logical_revision_group_sha256: str
    source_row_sha256: str
    raw_batch_sha256: str
    revision_basis: str = "source_version"
    coverage_role: str = "in_coverage"
    availability_status: str = "available"
    effective_available_session: str = ""

    def source(self) -> dict[str, object]:
        return dict(zip(self.source_fields, self.source_values, strict=True))


class FinancialVersionProjector:
    def project(
        self,
        observations: Sequence[FinancialSourceObservation],
        research_sessions: Sequence[str],
    ) -> tuple[CanonicalFinancialVersion, ...]:
        sessions = list(research_sessions)
        if sessions != sorted(set(sessions)):
            raise FinancialCandidateError("FINANCIAL_RESEARCH_SESSIONS_INVALID")
        exact: dict[str, CanonicalFinancialVersion] = {}
        for observation in observations:
            source = observation.source()
            if source.get("ts_code") != observation.ts_code:
                raise FinancialCandidateError("FINANCIAL_INSTRUMENT_IDENTITY_INVALID")
            normalized = tuple(_source_scalar(source[field]) for field in observation.source_fields)
            source = dict(zip(observation.source_fields, normalized, strict=True))
            published = _source_publication_date(source)
            report_period = _source_date(source.get("end_date"), required=True)
            observed_at = _aware_iso(observation.first_observed_at)
            observed_session = _next_session(sessions, _market_date(observed_at))
            available = "" if published == "" else _next_session(sessions, _iso_date(published))
            logical = {
                "endpoint": observation.endpoint,
                "instrument_id": observation.instrument_id,
                "report_period": report_period,
                "report_type": source.get("report_type"),
                "company_type": source.get("comp_type"),
                "end_type": source.get("end_type"),
            }
            row_identity = {
                **logical,
                "source_published_date": published,
                "source_payload": source,
            }
            version = CanonicalFinancialVersion(
                endpoint=observation.endpoint,
                instrument_id=observation.instrument_id,
                source_fields=observation.source_fields,
                source_values=tuple(source[field] for field in observation.source_fields),
                source_published_date=published,
                source_available_session=available,
                first_observed_at=observed_at,
                first_observed_session=observed_session,
                logical_revision_group_sha256=_sha(logical),
                source_row_sha256=_sha(row_identity),
                raw_batch_sha256=observation.raw_batch_sha256,
            )
            previous = exact.get(version.source_row_sha256)
            if previous is None or (version.first_observed_at, version.raw_batch_sha256) < (
                previous.first_observed_at,
                previous.raw_batch_sha256,
            ):
                exact[version.source_row_sha256] = version

        by_group: dict[tuple[str, str], list[CanonicalFinancialVersion]] = defaultdict(list)
        canonical: list[CanonicalFinancialVersion] = []
        for version in exact.values():
            if not version.source_published_date:
                canonical.append(
                    replace(
                        version,
                        availability_status="quarantined",
                        coverage_role="quarantined",
                    )
                )
            else:
                by_group[
                    (version.logical_revision_group_sha256, version.source_published_date)
                ].append(version)
        for group in by_group.values():
            ordered = sorted(
                group,
                key=lambda item: (
                    item.first_observed_at,
                    str(item.source().get("update_flag") or ""),
                    item.source_row_sha256,
                ),
            )
            earliest_observation = ordered[0].first_observed_at
            observations_by_time: dict[str, set[tuple[str, str]]] = defaultdict(set)
            latest_by_time: dict[str, set[tuple[str, str]]] = defaultdict(set)
            for version in ordered:
                # A supplier update marker is evidence, not a different financial value.
                content = {
                    key: value for key, value in version.source().items()
                    if key != "update_flag"
                }
                content_sha256 = _sha(content)
                candidate = (
                    _source_date(version.source().get("ann_date"), required=False),
                    content_sha256,
                )
                observations_by_time[version.first_observed_at].add(candidate)
                if str(version.source().get("update_flag") or "") == "1":
                    latest_by_time[version.first_observed_at].add(candidate)
            for version in ordered:
                # Preserve every source version. Query/seed selection already prefers
                # update_flag=1 and then the greatest ann_date at the same effective
                # session. Only conflicts tied at that ann_date remain ambiguous.
                candidates = (
                    latest_by_time[version.first_observed_at]
                    or observations_by_time[version.first_observed_at]
                )
                latest_ann_date = max(ann_date for ann_date, _content in candidates)
                competing = {
                    content for ann_date, content in candidates
                    if ann_date == latest_ann_date
                }
                if len(competing) > 1:
                    canonical.append(
                        replace(
                            version,
                            availability_status="quarantined",
                            coverage_role="quarantined",
                        )
                    )
                    continue
                revision_basis = (
                    "source_version"
                    if version.first_observed_at == earliest_observation
                    else "observed_correction"
                )
                if not version.source_available_session or (
                    revision_basis == "observed_correction" and not version.first_observed_session
                ):
                    canonical.append(
                        replace(
                            version,
                            revision_basis=revision_basis,
                            availability_status="pending_calendar",
                            coverage_role="pending_calendar",
                        )
                    )
                    continue
                effective_session = version.source_available_session
                if revision_basis == "observed_correction":
                    effective_session = max(effective_session, version.first_observed_session)
                canonical.append(
                    replace(
                        version,
                        revision_basis=revision_basis,
                        effective_available_session=effective_session,
                    )
                )
        return tuple(canonical)


class FinancialCandidateStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._files = AddressedFileStore(self._root)
        self._raw = RawFinancialBatchStore(self._root)
        self._market = MountedGenerationStore(self._root)
        self._daily_parent_evidence_cache_key: tuple[str, int, int] | None = None
        self._daily_parent_evidence_cache: list[dict[str, object]] = []
        self._published_index_manifest_sha256: str | None = None
        self._published_index: _PublishedFinancialRowIndex | None = None

    def close(self) -> None:
        if self._published_index is not None:
            self._published_index.close()
        self._published_index = None
        self._published_index_manifest_sha256 = None

    def _published_rows(
        self,
        manifest_sha256: str,
        endpoint_fields: Mapping[str, tuple[str, ...]],
        sessions: list[str],
    ) -> _PublishedFinancialRowIndex:
        if (
            self._published_index is not None
            and self._published_index_manifest_sha256 == manifest_sha256
        ):
            return self._published_index
        self.close()
        manifest = self._read_family(manifest_sha256)
        references = {
            _TABLE_ENDPOINTS[str(item["name"])]: item
            for item in manifest["tables"]
            if isinstance(item, Mapping) and str(item.get("name")) in _TABLE_ENDPOINTS
        }
        if tuple(references) != FINANCIAL_ENDPOINTS:
            raise FinancialCandidateError("FINANCIAL_TABLE_SET_INVALID")
        index = _PublishedFinancialRowIndex(self._root)
        try:
            for endpoint in FINANCIAL_ENDPOINTS:
                for row in self._iter_table_rows(
                    endpoint,
                    endpoint_fields[endpoint],
                    references[endpoint],
                    sessions,
                ):
                    index.add(endpoint, row)
            index.finish()
        except Exception:
            index.close()
            raise
        self._published_index_manifest_sha256 = manifest_sha256
        self._published_index = index
        return index

    def materialize(
        self,
        collection: CompletedFinancialCollection,
        *,
        observation_through_session: str,
    ) -> FinancialFamilyCandidate:
        return self._materialize(
            collection,
            observation_through_session=observation_through_session,
            prior_checkpoints=(),
            prior_shards=(),
        )

    def rebuild(
        self,
        collection: CompletedFinancialCollection,
        *,
        prior_candidate_manifest_sha256: str,
        observation_through_session: str,
    ) -> FinancialFamilyCandidate:
        prior = self.reopen(prior_candidate_manifest_sha256)
        if prior.observation_through_session > observation_through_session:
            raise FinancialCandidateError("FINANCIAL_REFRESH_CUTOFF_REGRESSION")
        prior_manifest = self._read_family(prior_candidate_manifest_sha256)
        prior_contract = self._manifest_collection_contract(prior_manifest)
        if not _compatible_collection_contracts(prior_contract, collection.contract):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CONTRACT_MISMATCH")
        current_sessions = self._validated_market_sessions(
            collection.generation_manifest_sha256,
            observation_through_session,
        )
        current_lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            collection.generation_manifest_sha256
        )
        self._validated_evidence(
            collection,
            {item.instrument_id: item.ts_code for item in current_lifecycles},
        )
        prior_sessions = self._validated_market_sessions(
            str(prior_manifest["source_generation_manifest_sha256"]),
            prior.observation_through_session,
        )
        if [item for item in current_sessions if item <= prior.observation_through_session] != (
            prior_sessions
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        prior_entries = self._read_daily_parent_evidence_index(
            prior_manifest["raw_evidence"]
        )
        self._require_evidence_present(prior_entries)
        prior_checkpoints = tuple(_checkpoint_from_evidence(item) for item in prior_entries)
        prior_shards = self._manifest_evidence_shards(prior_manifest)
        historical = {item.instrument_id: item.ts_code for item in current_lifecycles}
        self._validate_historical_identities(prior_checkpoints, historical)
        unchanged_evidence = _merge_evidence_checkpoints(
            (*prior_checkpoints, *collection.shards)
        ) == prior_checkpoints
        discovery = None
        if (
            unchanged_evidence and prior.discovery_baseline_session is not None
            and observation_through_session == prior.observation_through_session
        ):
            # Reprojecting retained receipts does not perform new reconciliation.
            # Preserve the actual discovery watermarks and unresolved source state.
            coverage = prior_manifest["dataset_coverage"]
            discovery = FinancialDiscoveryPublication(
                baseline_session=coverage["discovery_baseline_session"],
                attempted_through_session=coverage["discovery_attempted_through_session"],
                complete_through_session=coverage["discovery_complete_through_session"],
                source_lineage_sha256=coverage["source_lineage_sha256"],
                readiness_status=coverage["readiness_status"],
                pending_instrument_count=coverage["pending_instrument_count"],
                discovery_gap_count=coverage["discovery_gap_count"],
                earliest_unresolved_date=coverage["earliest_unresolved_date"],
            )
            return self.reproject_saved(
                prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
                generation_manifest_sha256=collection.generation_manifest_sha256,
                idempotency_key=collection.idempotency_key,
                finished_at=_aware_iso(collection.finished_at),
            )
        return self._materialize(
            collection,
            observation_through_session=observation_through_session,
            prior_checkpoints=prior_checkpoints,
            prior_shards=prior_shards,
            discovery=discovery,
            prior_candidate_manifest_sha256=(
                prior_candidate_manifest_sha256 if unchanged_evidence else None
            ),
        )

    def reproject_saved(
        self,
        *,
        prior_candidate_manifest_sha256: str,
        generation_manifest_sha256: str,
        idempotency_key: str,
        finished_at: datetime | str,
        discovery: FinancialDiscoveryPublication | None = None,
    ) -> FinancialFamilyCandidate:
        """Rebuild current projections from retained receipts without source I/O."""
        prior = self.reopen(prior_candidate_manifest_sha256)
        prior_manifest = self._read_family(prior_candidate_manifest_sha256)
        coverage = prior_manifest["dataset_coverage"]
        if not isinstance(coverage, Mapping):
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        _validated_discovery_coverage(coverage)
        contract = self._manifest_collection_contract(prior_manifest)
        _validate_contract(contract)
        prior_entries = self._read_evidence_index(prior_manifest["raw_evidence"])
        endpoint_fields = self._validate_evidence_entries(
            prior_entries,
            contract=contract,
            historical=True,
        )
        prior_checkpoints = tuple(
            _checkpoint_from_evidence(item) for item in prior_entries
        )
        current_sessions = self._prevalidated_market_sessions(
            generation_manifest_sha256,
            prior.observation_through_session,
        )
        prior_sessions = self._prevalidated_market_sessions(
            str(prior_manifest["source_generation_manifest_sha256"]),
            prior.observation_through_session,
        )
        if current_sessions != prior_sessions:
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            generation_manifest_sha256
        )
        historical = {item.instrument_id: item.ts_code for item in lifecycles}
        self._validate_historical_identities(prior_checkpoints, historical)
        selected_discovery = discovery or FinancialDiscoveryPublication(
            baseline_session=str(coverage["discovery_baseline_session"]),
            attempted_through_session=str(coverage["discovery_attempted_through_session"]),
            complete_through_session=str(coverage["discovery_complete_through_session"]),
            source_lineage_sha256=str(coverage["source_lineage_sha256"]),
            readiness_status=str(coverage["readiness_status"]),
            pending_instrument_count=int(coverage["pending_instrument_count"]),
            discovery_gap_count=int(coverage["discovery_gap_count"]),
            earliest_unresolved_date=(
                None
                if coverage["earliest_unresolved_date"] is None
                else str(coverage["earliest_unresolved_date"])
            ),
        )
        _validate_discovery_publication(selected_discovery)
        if (
            selected_discovery.baseline_session
            != str(coverage["discovery_baseline_session"])
            or selected_discovery.attempted_through_session
            != str(coverage["discovery_attempted_through_session"])
            or selected_discovery.complete_through_session
            != str(coverage["discovery_complete_through_session"])
            or selected_discovery.discovery_gap_count
            != int(coverage["discovery_gap_count"])
        ):
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        normalized_finished_at = (
            datetime.fromisoformat(_aware_iso(finished_at))
            if isinstance(finished_at, str)
            else finished_at
        )
        if normalized_finished_at.tzinfo is None:
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        collection = CompletedFinancialCollection(
            idempotency_key=idempotency_key,
            generation_manifest_sha256=generation_manifest_sha256,
            contract=contract,
            finished_at=normalized_finished_at.astimezone(UTC).isoformat(),
            target_count=len(prior_checkpoints),
            shards=prior_checkpoints,
        )
        return self._materialize_daily(
            collection,
            prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
            prior_manifest=prior_manifest,
            prior_checkpoints=prior_checkpoints,
            discovery=selected_discovery,
            endpoint_fields=endpoint_fields,
            current_sessions=current_sessions,
            prior_sessions=prior_sessions,
            current_lifecycles=lifecycles,
        )

    def rebuild_daily(
        self,
        collection: CompletedFinancialCollection,
        *,
        prior_candidate_manifest_sha256: str,
        discovery: FinancialDiscoveryPublication,
    ) -> FinancialFamilyCandidate:
        prior = self.reopen(prior_candidate_manifest_sha256)
        _validate_discovery_publication(discovery)
        if prior.observation_through_session > discovery.attempted_through_session:
            raise FinancialCandidateError("FINANCIAL_REFRESH_CUTOFF_REGRESSION")
        prior_manifest = self._read_family(prior_candidate_manifest_sha256)
        prior_contract = self._manifest_collection_contract(prior_manifest)
        if not _compatible_collection_contracts(prior_contract, collection.contract):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CONTRACT_MISMATCH")
        baseline = _coverage_baseline(prior_manifest)
        if baseline != discovery.baseline_session:
            raise FinancialCandidateError("FINANCIAL_DISCOVERY_BASELINE_MISMATCH")
        prior_complete = _coverage_complete_through(prior_manifest)
        if prior_complete > discovery.complete_through_session:
            raise FinancialCandidateError("FINANCIAL_DISCOVERY_COMPLETE_REGRESSION")
        current_sessions = self._prevalidated_market_sessions(
            collection.generation_manifest_sha256,
            discovery.attempted_through_session,
        )
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            collection.generation_manifest_sha256
        )
        historical = {item.instrument_id: item.ts_code for item in lifecycles}
        endpoint_fields = self._validated_evidence(
            collection,
            historical,
            targeted=True,
        )
        prior_sessions = self._prevalidated_market_sessions(
            str(prior_manifest["source_generation_manifest_sha256"]),
            prior.observation_through_session,
        )
        if [item for item in current_sessions if item <= prior.observation_through_session] != (
            prior_sessions
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        prior_entries = self._read_evidence_index(prior_manifest["raw_evidence"])
        prior_checkpoints = tuple(_checkpoint_from_evidence(item) for item in prior_entries)
        self._validate_historical_identities(prior_checkpoints, historical)
        return self._materialize_daily(
            collection,
            prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
            prior_manifest=prior_manifest,
            prior_checkpoints=prior_checkpoints,
            discovery=discovery,
            endpoint_fields=endpoint_fields,
            current_sessions=current_sessions,
            prior_sessions=prior_sessions,
            current_lifecycles=lifecycles,
        )

    def validate_daily_instrument(
        self,
        collection: CompletedFinancialCollection,
        *,
        prior_candidate_manifest_sha256: str,
        observation_through_session: str,
    ) -> ValidatedFinancialInstrument:
        """Return accepted report periods and Canonical changes from one validation."""
        if len({item.instrument_id for item in collection.shards}) != 1:
            raise FinancialCandidateError("FINANCIAL_DAILY_INSTRUMENT_INVALID")
        prior = self.reopen(prior_candidate_manifest_sha256)
        prior_manifest = self._read_family(prior_candidate_manifest_sha256)
        prior_contract = self._manifest_collection_contract(prior_manifest)
        if not _compatible_collection_contracts(prior_contract, collection.contract):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CONTRACT_MISMATCH")
        current_sessions = self._prevalidated_market_sessions(
            collection.generation_manifest_sha256,
            observation_through_session,
        )
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            collection.generation_manifest_sha256
        )
        historical = {item.instrument_id: item.ts_code for item in lifecycles}
        endpoint_fields = self._validated_evidence(
            collection,
            historical,
            targeted=True,
        )
        prior_sessions = self._prevalidated_market_sessions(
            str(prior_manifest["source_generation_manifest_sha256"]),
            prior.observation_through_session,
        )
        if [item for item in current_sessions if item <= prior.observation_through_session] != (
            prior_sessions
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        prior_checkpoints = tuple(
            _checkpoint_from_evidence(item)
            for item in self._read_daily_parent_evidence_index(
                prior_manifest["raw_evidence"]
            )
        )
        self._validate_historical_identities(prior_checkpoints, historical)
        delta_counts, _published, _quarantine_hashes, quarantine_added, reports = (
            self._daily_table_deltas(
            collection.shards,
            prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
            calendar_instruments=frozenset(),
            prior_checkpoints=prior_checkpoints,
            endpoint_fields=endpoint_fields,
            coverage_start=str(prior_manifest["dataset_coverage"]["start"]),
            current_sessions=current_sessions,
            prior_sessions=prior_sessions,
            current_lifecycles=lifecycles,
            )
        )
        if quarantine_added:
            raise FinancialCandidateError("FINANCIAL_DAILY_INSTRUMENT_INVALID")
        return ValidatedFinancialInstrument(
            any(delta_counts.values()), reports,
        )

    def _materialize_daily(
        self,
        collection: CompletedFinancialCollection,
        *,
        prior_candidate_manifest_sha256: str,
        prior_manifest: Mapping[str, object],
        prior_checkpoints: Sequence[FinancialShardCheckpoint],
        discovery: FinancialDiscoveryPublication,
        endpoint_fields: Mapping[str, tuple[str, ...]],
        current_sessions: list[str],
        prior_sessions: list[str],
        current_lifecycles: Sequence[HistoricalInstrumentLifecycle],
    ) -> FinancialFamilyCandidate:
        coverage_start = str(prior_manifest["dataset_coverage"]["start"])
        delta_counts, published, quarantine_hashes, quarantine_added, _reports = (
            self._daily_table_deltas(
            collection.shards,
            prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
            calendar_instruments=self._calendar_reprojection_instruments(
                prior_candidate_manifest_sha256, prior_sessions, current_sessions,
                frozenset(item.instrument_id for item in current_lifecycles),
            ),
            prior_checkpoints=prior_checkpoints,
            endpoint_fields=endpoint_fields,
            coverage_start=coverage_start,
            current_sessions=current_sessions,
            prior_sessions=prior_sessions,
            current_lifecycles=current_lifecycles,
            )
        )
        if quarantine_added:
            raise FinancialCandidateError("FINANCIAL_DAILY_QUARANTINE_CHANGE_UNSUPPORTED")
        prior_tables = {
            str(item["name"]): item
            for item in prior_manifest["tables"]
            if isinstance(item, Mapping)
        }
        table_references = [
            self._materialize_incremental_table(
                endpoint,
                endpoint_fields[endpoint],
                prior_tables[_ENDPOINT_TABLES[endpoint]],
                (() if published is None else published.deltas(endpoint)),
                delta_counts[endpoint],
                current_sessions,
            )
            for endpoint in FINANCIAL_ENDPOINTS
        ]
        historical_checkpoints = _merge_evidence_checkpoints(
            (*prior_checkpoints, *collection.shards)
        )
        current_evidence_reference = self._materialize_evidence_index(collection.shards)
        evidence_reference = (
            prior_manifest["raw_evidence"]
            if historical_checkpoints == tuple(prior_checkpoints)
            else self._materialize_evidence_index(historical_checkpoints)
        )
        evidence_shards = self._manifest_evidence_shards(prior_manifest)
        family = {
            "format": _FAMILY_FORMAT,
            "version": _VERSION,
            "family_id": _FAMILY_ID,
            "schema_contract": _SCHEMA_CONTRACT,
            "source_generation_manifest_sha256": collection.generation_manifest_sha256,
            "source_collection": {
                "idempotency_key": collection.idempotency_key,
                "contract": collection.contract.descriptor(),
                "finished_at": collection.finished_at,
                "prior_candidate_manifest_sha256": prior_candidate_manifest_sha256,
            },
            "evidence_shards": [
                _evidence_shard_descriptor(item) for item in evidence_shards
            ],
            "dataset_coverage": _discovery_coverage(coverage_start, discovery),
            "current_raw_evidence": current_evidence_reference,
            "raw_evidence": evidence_reference,
            "quarantine": (
                dict(prior_manifest["quarantine"])
                if quarantine_hashes is None
                else {
                    "row_count": len(quarantine_hashes),
                    "rows_sha256": _sha(list(quarantine_hashes)),
                }
            ),
            "validation_summary": {
                "status": "validated",
                "table_count": len(table_references),
                "row_count": sum(int(item["row_count"]) for item in table_references),
                "object_count": sum(
                    int(item["object_count"]) for item in table_references
                ),
                "raw_batch_count": len(historical_checkpoints),
            },
            "tables": table_references,
        }
        content = self._manifest_bytes(family)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store(self._manifest_path(sha256), sha256, content)
        return self.validate(sha256)

    def _daily_table_deltas(
        self,
        current_checkpoints: Sequence[FinancialShardCheckpoint],
        *,
        prior_candidate_manifest_sha256: str,
        calendar_instruments: frozenset[str],
        prior_checkpoints: Sequence[FinancialShardCheckpoint],
        endpoint_fields: Mapping[str, tuple[str, ...]],
        coverage_start: str,
        current_sessions: list[str],
        prior_sessions: list[str],
        current_lifecycles: Sequence[HistoricalInstrumentLifecycle],
    ) -> tuple[
        dict[str, int],
        _PublishedFinancialRowIndex | None,
        tuple[str, ...] | None,
        bool,
        dict[str, tuple[str, ...]],
    ]:
        affected = {item.instrument_id for item in current_checkpoints} | calendar_instruments
        if not affected:
            return (
                {endpoint: 0 for endpoint in FINANCIAL_ENDPOINTS},
                None,
                None,
                False,
                {},
            )
        prior_by_instrument: dict[
            tuple[str, str], list[FinancialShardCheckpoint]
        ] = defaultdict(list)
        current_by_instrument: dict[
            tuple[str, str], list[FinancialShardCheckpoint]
        ] = defaultdict(list)
        for checkpoint in prior_checkpoints:
            if checkpoint.instrument_id in affected:
                prior_by_instrument[(checkpoint.endpoint, checkpoint.instrument_id)].append(
                    checkpoint
                )
        for checkpoint in current_checkpoints:
            current_by_instrument[(checkpoint.endpoint, checkpoint.instrument_id)].append(
                checkpoint
            )
        current_in_scope = {
            item.instrument_id
            for item in current_lifecycles
            if item.listed_from <= coverage_start
            and (not item.listed_to or item.listed_to >= coverage_start)
        }
        reports: dict[str, tuple[str, ...]] = {}
        published = self._published_rows(
            prior_candidate_manifest_sha256,
            endpoint_fields,
            prior_sessions,
        )
        published.clear_deltas()
        quarantine_hashes = published.quarantined_hashes()
        prior_quarantine_hashes = set(quarantine_hashes)
        for endpoint in FINANCIAL_ENDPOINTS:
            report_periods: set[str] = set()
            for instrument_id in sorted(affected):
                key = (endpoint, instrument_id)
                prior_group = tuple(prior_by_instrument.get(key, ()))
                current_group = tuple(current_by_instrument.get(key, ()))
                if not prior_group and not current_group:
                    continue
                merged_group = _merge_evidence_checkpoints((*prior_group, *current_group))
                new_versions, _new_quarantine = self._canonical_versions(
                    merged_group,
                    endpoint_fields[endpoint],
                    current_sessions,
                )
                new_retained = self._retain_coverage_versions(
                    new_versions,
                    coverage_start,
                    {instrument_id} if instrument_id in current_in_scope else set(),
                )[endpoint]
                contract = _table_contract(
                    _ENDPOINT_TABLES[endpoint], endpoint_fields[endpoint]
                )
                old_rows = {
                    str(row["source_row_sha256"]): row
                    for row in published.rows(endpoint, instrument_id)
                }
                new_rows = {
                    str(row["source_row_sha256"]): row
                    for row in canonicalize_parquet_rows(
                        [
                            _version_row(version, endpoint_fields[endpoint])
                            for version in new_retained
                        ],
                        contract,
                    )
                }
                report_periods.update(
                    period for _instrument, period in _statement_report_inventory(
                        new_rows.values(), current_sessions[-1],
                    )
                )
                if not set(old_rows).issubset(new_rows):
                    raise FinancialCandidateError("FINANCIAL_DAILY_DELETE_REQUIRED")
                for source_row_sha256, row in new_rows.items():
                    if old_rows.get(source_row_sha256) != row:
                        published.add_delta(endpoint, row)
                quarantine_hashes.difference_update(
                    source_row_sha256
                    for source_row_sha256, row in old_rows.items()
                    if row["availability_status"] == "quarantined"
                )
                quarantine_hashes.update(
                    source_row_sha256
                    for source_row_sha256, row in new_rows.items()
                    if row["availability_status"] == "quarantined"
                )
            reports[endpoint] = tuple(sorted(report_periods))
        published.finish()
        return (
            {endpoint: published.delta_count(endpoint) for endpoint in FINANCIAL_ENDPOINTS},
            published,
            tuple(sorted(quarantine_hashes)),
            bool(quarantine_hashes - prior_quarantine_hashes),
            reports,
        )

    def _calendar_reprojection_instruments(
        self, prior_digest: str, prior_sessions: list[str], current_sessions: list[str],
        instrument_ids: frozenset[str],
    ) -> frozenset[str]:
        if current_sessions == prior_sessions:
            return frozenset()
        affected: set[str] = set()
        columns = (
            "instrument_id", "availability_status", "source_published_date",
            "first_observed_at", "source_available_session", "first_observed_session",
        )
        for endpoint in FINANCIAL_ENDPOINTS:
            table = self.read_financial_table(
                prior_digest, endpoint, columns, (prior_sessions[-1],), instrument_ids,
                compact_history=False,
            )
            pending = table.filter(pc.is_in(table["availability_status"], value_set=pa.array(
                ["pending_calendar", "quarantined"],
            )))
            for batch in pending.to_batches(max_chunksize=4096):
                for row in batch.to_pylist():
                    if not row["source_published_date"]:
                        continue
                    available = _next_session(
                        current_sessions, _iso_date(row["source_published_date"]),
                    )
                    observed = _next_session(
                        current_sessions, _market_date(row["first_observed_at"]),
                    )
                    if (available != row["source_available_session"]
                            or observed != row["first_observed_session"]):
                        affected.add(row["instrument_id"])
        return frozenset(affected)

    def _materialize_incremental_table(
        self,
        endpoint: str,
        source_fields: tuple[str, ...],
        prior_reference: Mapping[str, object],
        delta_rows: Iterator[dict[str, object]] | Sequence[dict[str, object]],
        delta_row_count: int,
        sessions: list[str],
    ) -> dict[str, object]:
        if delta_row_count == 0:
            return dict(prior_reference)
        table_name = _ENDPOINT_TABLES[endpoint]
        contract = _table_contract(table_name, source_fields)
        prior_manifest_sha256 = str(prior_reference.get("manifest_sha256"))
        prior_manifest = self._read_json(
            self._manifest_path(prior_manifest_sha256),
            prior_manifest_sha256,
            int(prior_reference.get("manifest_byte_count", -1)),
        )
        prior_objects = prior_manifest.get("objects")
        if (
            prior_manifest.get("format") != _TABLE_FORMAT
            or prior_manifest.get("version") != _VERSION
            or prior_manifest.get("table") != table_name
            or prior_manifest.get("source_endpoint") != endpoint
            or prior_manifest.get("source_fields") != list(source_fields)
            or prior_manifest.get("writer_contract") != contract.descriptor()
            or not isinstance(prior_objects, list)
        ):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        objects = [dict(item) for item in prior_objects if isinstance(item, Mapping)]
        if len(objects) != len(prior_objects):
            raise FinancialCandidateError("FINANCIAL_OBJECT_REFERENCE_INVALID")
        written_rows = 0
        for group in _iter_partitioned_financial_rows(delta_rows, sessions):
            objects.append(self._materialize_object(contract, group, len(objects)))
            written_rows += len(group)
        if written_rows != delta_row_count:
            raise FinancialCandidateError("FINANCIAL_INCREMENTAL_TABLE_INVALID")
        manifest = {
            "format": _TABLE_FORMAT,
            "version": _VERSION,
            "table": table_name,
            "source_endpoint": endpoint,
            "source_fields": list(source_fields),
            "writer_contract": contract.descriptor(),
            "partitioning": {
                "kind": "immutable-base-with-delta-objects",
                "session_count": GENERATION_SESSION_PARTITION_COUNT,
                "row_count": GENERATION_ROW_PARTITION_COUNT,
                "base_manifest_sha256": prior_manifest_sha256,
                "base_object_count": len(prior_objects),
            },
            "row_count": int(prior_reference["row_count"]) + delta_row_count,
            "objects": objects,
        }
        content = self._manifest_bytes(manifest)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store(self._manifest_path(sha256), sha256, content)
        return {
            "name": table_name,
            "manifest_sha256": sha256,
            "manifest_byte_count": len(content),
            "row_count": manifest["row_count"],
            "object_count": len(objects),
        }

    def _validate_incremental_table(
        self,
        endpoint: str,
        source_fields: tuple[str, ...],
        prior_reference: Mapping[str, object],
        reference: Mapping[str, object],
        delta_rows: Iterator[dict[str, object]] | Sequence[dict[str, object]],
        delta_row_count: int,
        sessions: list[str],
    ) -> None:
        table_name = _ENDPOINT_TABLES[endpoint]
        contract = _table_contract(table_name, source_fields)
        prior_manifest_sha256 = str(prior_reference.get("manifest_sha256"))
        prior_manifest = self._read_json(
            self._manifest_path(prior_manifest_sha256),
            prior_manifest_sha256,
            int(prior_reference.get("manifest_byte_count", -1)),
        )
        prior_objects = prior_manifest.get("objects")
        manifest_sha256 = str(reference.get("manifest_sha256"))
        manifest = self._read_json(
            self._manifest_path(manifest_sha256),
            manifest_sha256,
            int(reference.get("manifest_byte_count", -1)),
        )
        objects = manifest.get("objects")
        if not isinstance(prior_objects, list) or not isinstance(objects, list):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        partitioning = manifest.get("partitioning")
        if (
            manifest.get("format") != _TABLE_FORMAT
            or manifest.get("version") != _VERSION
            or manifest.get("table") != table_name
            or manifest.get("source_endpoint") != endpoint
            or manifest.get("source_fields") != list(source_fields)
            or manifest.get("writer_contract") != contract.descriptor()
            or partitioning
            != {
                "kind": "immutable-base-with-delta-objects",
                "session_count": GENERATION_SESSION_PARTITION_COUNT,
                "row_count": GENERATION_ROW_PARTITION_COUNT,
                "base_manifest_sha256": prior_manifest_sha256,
                "base_object_count": len(prior_objects),
            }
            or objects[: len(prior_objects)] != prior_objects
        ):
            raise FinancialCandidateError("FINANCIAL_INCREMENTAL_TABLE_INVALID")
        expected_delta_objects: list[dict[str, object]] = []
        validated_rows = 0
        for group in _iter_partitioned_financial_rows(delta_rows, sessions):
            content = parquet_bytes(group, contract)
            sha256 = hashlib.sha256(content).hexdigest()
            expected = {
                "ordinal": len(prior_objects) + len(expected_delta_objects),
                "sha256": sha256,
                "byte_count": len(content),
                "row_count": len(group),
                "first_sort_key": [group[0][key] for key in contract.sort_keys],
                "last_sort_key": [group[-1][key] for key in contract.sort_keys],
            }
            if self._read(
                self._object_path(sha256),
                sha256,
                len(content),
                GENERATION_OBJECT_MAX_BYTES,
            ) != content:
                raise FinancialCandidateError("FINANCIAL_OBJECT_ENCODING_INVALID")
            expected_delta_objects.append(expected)
            validated_rows += len(group)
        if validated_rows != delta_row_count:
            raise FinancialCandidateError("FINANCIAL_INCREMENTAL_TABLE_INVALID")
        if objects[len(prior_objects) :] != expected_delta_objects:
            raise FinancialCandidateError("FINANCIAL_INCREMENTAL_TABLE_INVALID")
        expected_reference = {
            "name": table_name,
            "manifest_sha256": manifest_sha256,
            "manifest_byte_count": int(reference.get("manifest_byte_count", -1)),
            "row_count": int(prior_reference["row_count"]) + delta_row_count,
            "object_count": len(objects),
        }
        if dict(reference) != expected_reference:
            raise FinancialCandidateError("FINANCIAL_TABLE_REFERENCE_INVALID")
        if manifest.get("row_count") != expected_reference["row_count"]:
            raise FinancialCandidateError("FINANCIAL_TABLE_ROW_COUNT_INVALID")

    def preflight_rebuild(
        self,
        *,
        prior_candidate_manifest_sha256: str,
        generation_manifest_sha256: str,
        contract: FinancialCollectionContract,
        observation_through_session: str,
    ) -> None:
        prior = self.reopen(prior_candidate_manifest_sha256)
        if prior.observation_through_session > observation_through_session:
            raise FinancialCandidateError("FINANCIAL_REFRESH_CUTOFF_REGRESSION")
        prior_manifest = self._read_family(prior_candidate_manifest_sha256)
        prior_contract = self._manifest_collection_contract(prior_manifest)
        if not _compatible_collection_contracts(prior_contract, contract):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CONTRACT_MISMATCH")
        _validate_contract(contract)
        current_sessions = self._validated_market_sessions(
            generation_manifest_sha256,
            observation_through_session,
        )
        current_lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            generation_manifest_sha256
        )
        prior_sessions = self._validated_market_sessions(
            str(prior_manifest["source_generation_manifest_sha256"]),
            prior.observation_through_session,
        )
        if [item for item in current_sessions if item <= prior.observation_through_session] != (
            prior_sessions
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        prior_entries = self._read_evidence_index(prior_manifest["raw_evidence"])
        self._require_evidence_present(prior_entries)
        prior_checkpoints = tuple(_checkpoint_from_evidence(item) for item in prior_entries)
        historical = {item.instrument_id: item.ts_code for item in current_lifecycles}
        self._validate_historical_identities(prior_checkpoints, historical)

    def _materialize(
        self,
        collection: CompletedFinancialCollection,
        *,
        observation_through_session: str,
        prior_checkpoints: Sequence[FinancialShardCheckpoint],
        prior_shards: Sequence[FinancialDateShard],
        discovery: FinancialDiscoveryPublication | None = None,
        prior_candidate_manifest_sha256: str | None = None,
        validated_endpoint_fields: Mapping[str, tuple[str, ...]] | None = None,
    ) -> FinancialFamilyCandidate:
        sessions = self._validated_market_sessions(
            collection.generation_manifest_sha256,
            observation_through_session,
        )
        coverage_start = next((session for session in sessions if session[:4] == "2010"), None)
        if coverage_start is None:
            raise FinancialCandidateError("FINANCIAL_COVERAGE_START_UNAVAILABLE")
        if _market_date(collection.finished_at) < observation_through_session:
            raise FinancialCandidateError("FINANCIAL_OBSERVATION_CUTOFF_INVALID")
        _validate_contract(collection.contract)
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            collection.generation_manifest_sha256
        )
        endpoint_fields = (
            dict(validated_endpoint_fields)
            if validated_endpoint_fields is not None
            else self._validated_evidence(
                collection,
                {item.instrument_id: item.ts_code for item in lifecycles},
            )
        )
        historical_checkpoints = _merge_evidence_checkpoints(
            (*prior_checkpoints, *collection.shards)
        )
        in_scope_at_start = {
            item.instrument_id
            for item in lifecycles
            if item.listed_from <= coverage_start
            and (not item.listed_to or item.listed_to >= coverage_start)
        }
        table_references: list[dict[str, object]] = []
        quarantine_hashes: list[str] = []
        checkpoints_by_instrument: dict[
            tuple[str, str], list[FinancialShardCheckpoint]
        ] = defaultdict(list)
        for checkpoint in historical_checkpoints:
            checkpoints_by_instrument[(checkpoint.endpoint, checkpoint.instrument_id)].append(
                checkpoint
            )
        workset = _PublishedFinancialRowIndex(self._root)
        try:
            for endpoint in FINANCIAL_ENDPOINTS:
                workset.clear_deltas()
                for (group_endpoint, instrument_id), grouped in sorted(
                    checkpoints_by_instrument.items()
                ):
                    if group_endpoint != endpoint:
                        continue
                    versions, quarantine = self._canonical_versions(
                        tuple(grouped),
                        endpoint_fields[endpoint],
                        sessions,
                    )
                    retained = self._retain_coverage_versions(
                        versions,
                        coverage_start,
                        {instrument_id} if instrument_id in in_scope_at_start else set(),
                    )[endpoint]
                    rows = canonicalize_parquet_rows(
                        [
                            _version_row(version, endpoint_fields[endpoint])
                            for version in retained
                        ],
                        _table_contract(_ENDPOINT_TABLES[endpoint], endpoint_fields[endpoint]),
                    )
                    for row in rows:
                        workset.add_delta(endpoint, row)
                    quarantine_hashes.extend(
                        item.source_row_sha256 for item in quarantine
                    )
                    del versions, retained, quarantine, rows
                workset.finish()
                row_count = workset.delta_count(endpoint)
                table_references.append(
                    self._materialize_table(
                        endpoint,
                        endpoint_fields[endpoint],
                        workset.deltas(endpoint),
                        row_count,
                        sessions,
                    )
                )
        finally:
            workset.close()
        current_evidence_reference = self._materialize_evidence_index(collection.shards)
        evidence_reference = self._materialize_evidence_index(historical_checkpoints)
        evidence_shards = _merge_evidence_shards((*prior_shards, *collection.contract.shards))
        coverage = (
            {
                "kind": "financial-observation-range",
                "start": coverage_start,
                "observation_through_session": observation_through_session,
                "expected_instrument_count": len(
                    {item.instrument_id for item in collection.shards}
                ),
                "expected_shard_count": collection.target_count,
                "completed_shard_count": collection.target_count,
                "reconciliation_status": "complete",
                "historical_reconciliation_watermark": observation_through_session,
                "revision_coverage": "source-dated-and-first-observed-corrections",
                "seed_policy": "annual-stock-and-ttm-dependency-seeds",
            }
            if discovery is None
            else _discovery_coverage(coverage_start, discovery)
        )
        family = {
            "format": _FAMILY_FORMAT,
            "version": _VERSION,
            "family_id": _FAMILY_ID,
            "schema_contract": _SCHEMA_CONTRACT,
            "source_generation_manifest_sha256": collection.generation_manifest_sha256,
            "source_collection": {
                "idempotency_key": collection.idempotency_key,
                "contract": collection.contract.descriptor(),
                "finished_at": collection.finished_at,
            },
            "evidence_shards": [_evidence_shard_descriptor(item) for item in evidence_shards],
            "dataset_coverage": coverage,
            "current_raw_evidence": current_evidence_reference,
            "raw_evidence": evidence_reference,
            "quarantine": {
                "row_count": len(quarantine_hashes),
                "rows_sha256": _sha(sorted(quarantine_hashes)),
            },
            "validation_summary": {
                "status": "validated",
                "table_count": len(table_references),
                "row_count": sum(int(item["row_count"]) for item in table_references),
                "object_count": sum(int(item["object_count"]) for item in table_references),
                "raw_batch_count": len(historical_checkpoints),
            },
            "tables": table_references,
        }
        if prior_candidate_manifest_sha256 is not None:
            prior_family = self._read_family(prior_candidate_manifest_sha256)
            if all(
                family[key] == prior_family[key]
                for key in ("schema_contract", "dataset_coverage", "quarantine", "tables")
            ):
                return self._descriptor(prior_candidate_manifest_sha256, prior_family)
        content = self._manifest_bytes(family)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store(self._manifest_path(sha256), sha256, content)
        return self.validate(sha256)

    def reopen(self, manifest_sha256: str) -> FinancialFamilyCandidate:
        manifest = self._read_family(manifest_sha256)
        return self._descriptor(manifest_sha256, manifest)

    def source_generation_manifest_sha256(self, manifest_sha256: str) -> str:
        manifest = self._read_family(manifest_sha256)
        source = manifest.get("source_generation_manifest_sha256")
        _require_sha256(source)
        return str(source)

    def collection_contract(
        self,
        manifest_sha256: str,
    ) -> FinancialCollectionContract:
        return self._manifest_collection_contract(self._read_family(manifest_sha256))

    def canonical_projection_sha256(self, manifest_sha256: str) -> str:
        """Identify the projected Financial tables without discovery metadata."""
        manifest = self._read_family(manifest_sha256)
        return _sha(manifest["tables"])

    def prior_candidate_manifest_sha256(self, manifest_sha256: str) -> str | None:
        manifest = self._read_family(manifest_sha256)
        source_collection = manifest.get("source_collection")
        if not isinstance(source_collection, Mapping):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        value = source_collection.get("prior_candidate_manifest_sha256")
        if value is None:
            return None
        _require_sha256(value)
        return str(value)

    def validate_against_market_generation(
        self,
        manifest_sha256: str,
        generation_manifest_sha256: str,
    ) -> FinancialFamilyCandidate:
        """Validate one immutable financial family against a compatible Market root."""
        candidate = self.validate(manifest_sha256)
        if self.source_generation_manifest_sha256(manifest_sha256) == (
            generation_manifest_sha256
        ):
            return candidate
        manifest = self._read_family(manifest_sha256)
        session_reader = (
            self._prevalidated_market_sessions
            if self.prior_candidate_manifest_sha256(manifest_sha256) is not None
            else self._validated_market_sessions
        )
        current_sessions = session_reader(
            generation_manifest_sha256,
            candidate.observation_through_session,
        )
        prior_sessions = session_reader(
            str(manifest["source_generation_manifest_sha256"]),
            candidate.observation_through_session,
        )
        if current_sessions != prior_sessions:
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        current_lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            generation_manifest_sha256
        )
        checkpoints = tuple(
            _checkpoint_from_evidence(item)
            for item in self._read_evidence_index(manifest["raw_evidence"])
        )
        self._validate_historical_identities(
            checkpoints,
            {item.instrument_id: item.ts_code for item in current_lifecycles},
        )
        return candidate

    def reopen_against_prevalidated_market_generation(
        self,
        manifest_sha256: str,
        generation_manifest_sha256: str,
    ) -> FinancialFamilyCandidate:
        """Rebind an immutable published Family to a separately validated Market root."""
        candidate = self.reopen(manifest_sha256)
        manifest = self._read_family(manifest_sha256)
        source_generation = str(manifest["source_generation_manifest_sha256"])
        if source_generation == generation_manifest_sha256:
            return candidate
        current = self._market.inspect_root(generation_manifest_sha256)
        prior = self._market.inspect_root(source_generation)
        current_sessions = [
            session
            for session in current.research_sessions
            if session <= candidate.observation_through_session
        ]
        prior_sessions = [
            session
            for session in prior.research_sessions
            if session <= candidate.observation_through_session
        ]
        if current_sessions != prior_sessions:
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        current_lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            generation_manifest_sha256
        )
        checkpoints = tuple(
            _checkpoint_from_evidence(item)
            for item in self._read_evidence_index(manifest["raw_evidence"])
        )
        self._validate_historical_identities(
            checkpoints,
            {item.instrument_id: item.ts_code for item in current_lifecycles},
        )
        return candidate

    def source_fields_by_endpoint(
        self,
        manifest_sha256: str,
    ) -> dict[str, frozenset[str]]:
        manifest = self._read_family(manifest_sha256)
        fields: dict[str, frozenset[str]] = {}
        for endpoint, table_name in _ENDPOINT_TABLES.items():
            reference = next(
                item
                for item in manifest["tables"]
                if isinstance(item, Mapping) and item.get("name") == table_name
            )
            table_manifest = self._read_json(
                self._manifest_path(str(reference["manifest_sha256"])),
                str(reference["manifest_sha256"]),
                int(reference["manifest_byte_count"]),
            )
            source_fields = table_manifest.get("source_fields")
            if not isinstance(source_fields, list) or not all(
                isinstance(value, str) and value for value in source_fields
            ):
                raise FinancialCandidateError("FINANCIAL_SOURCE_FIELDS_INVALID")
            fields[endpoint] = frozenset(source_fields)
        return fields

    def family_reference(self, manifest_sha256: str) -> dict[str, object]:
        manifest = self._read_family(manifest_sha256)
        descriptor = self._descriptor(manifest_sha256, manifest)
        content = self._read(
            self._manifest_path(manifest_sha256),
            manifest_sha256,
            None,
            GENERATION_MANIFEST_MAX_BYTES,
        )
        return {
            "family_id": descriptor.family_id,
            "schema_contract": descriptor.schema_contract,
            "dataset_coverage": dict(manifest["dataset_coverage"]),
            "validation_summary": {
                key: manifest["validation_summary"][key]
                for key in ("status", "table_count", "row_count", "object_count")
            },
            "table_names": list(descriptor.table_names),
            "manifest_sha256": manifest_sha256,
            "manifest_byte_count": len(content),
        }

    def validate_stored(self, manifest_sha256: str) -> FinancialFamilyCandidate:
        """Verify immutable stored facts without regenerating their projection."""
        manifest = self._read_family(manifest_sha256)
        descriptor = self._descriptor(manifest_sha256, manifest)
        contract = self._manifest_collection_contract(manifest)
        _validate_contract(contract)
        evidence = self._read_evidence_index(manifest["raw_evidence"])
        current = self._read_evidence_index(manifest["current_raw_evidence"])
        if len(evidence) != descriptor.raw_batch_count:
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_COUNT_INVALID")
        if _merge_evidence_descriptors(evidence) != _merge_evidence_descriptors(
            (*evidence, *current)
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_EVIDENCE_UNION_INVALID")
        endpoint_fields = self._validate_evidence_entries(
            evidence, contract=contract, historical=True
        )
        if current:
            self._validate_evidence_entries(current, contract=contract)
        sessions = self._validated_market_sessions(
            str(manifest["source_generation_manifest_sha256"]),
            descriptor.observation_through_session,
        )
        checkpoints = tuple(_checkpoint_from_evidence(item) for item in evidence)
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            str(manifest["source_generation_manifest_sha256"])
        )
        historical = {item.instrument_id: item.ts_code for item in lifecycles}
        self._validate_historical_identities(checkpoints, historical)
        self._validate_target_set(
            tuple(_checkpoint_from_evidence(item) for item in current), historical, contract,
            targeted=descriptor.discovery_baseline_session is not None,
        )
        source_collection = manifest["source_collection"]
        finished_at = _aware_iso(str(source_collection["finished_at"]))
        if _market_date(finished_at) < descriptor.observation_through_session or any(
            _aware_iso(item.collected_at) > finished_at for item in checkpoints
        ):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        if contract.shards != self._manifest_evidence_shards(manifest):
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_SHARD_SET_INVALID")
        coverage = manifest["dataset_coverage"]
        if not isinstance(coverage.get("seed_policy"), str) or not coverage["seed_policy"]:
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        if descriptor.discovery_baseline_session is None:
            if any(coverage.get(key) != value for key, value in {
                "expected_instrument_count": len(historical),
                "expected_shard_count": len(current), "completed_shard_count": len(current),
                "historical_reconciliation_watermark": descriptor.observation_through_session,
            }.items()):
                raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        else:
            _validated_discovery_coverage(coverage)
        if "prior_candidate_manifest_sha256" in source_collection:
            parent = self._read_family(str(source_collection["prior_candidate_manifest_sha256"]))
            parent_evidence = self._read_evidence_index(parent["raw_evidence"])
            if _merge_evidence_descriptors(evidence) != _merge_evidence_descriptors(
                (*parent_evidence, *current)
            ):
                raise FinancialCandidateError("FINANCIAL_REFRESH_EVIDENCE_UNION_INVALID")
        references = manifest["tables"]
        if [item.get("name") for item in references] != list(_ENDPOINT_TABLES.values()):
            raise FinancialCandidateError("FINANCIAL_TABLE_SET_INVALID")
        quarantine_hashes: list[str] = []
        projection_columns = {
            "availability_status", "revision_basis", "coverage_role", "effective_available_session",
            "first_observed_session", "source_available_session",
        }
        session_set = frozenset(sessions)
        for endpoint, reference in zip(FINANCIAL_ENDPOINTS, references, strict=True):
            fields = endpoint_fields[endpoint]
            # Keep only source-fact digests across instruments, never the complete
            # wide source history alongside the stored table's Python rows.
            originals = {
                bytes.fromhex(version.source_row_sha256): _stored_fact_digest(
                    _version_row(version, fields), projection_columns,
                )
                for version in self._iter_canonical_versions(
                    tuple(item for item in checkpoints if item.endpoint == endpoint),
                    fields, sessions,
                )
            }
            for row in self._iter_table_rows(endpoint, fields, reference, sessions):
                source_hash = str(row["source_row_sha256"])
                _require_sha256(source_hash)
                if originals.get(bytes.fromhex(source_hash)) != _stored_fact_digest(
                    row, projection_columns,
                ):
                    raise FinancialCandidateError("FINANCIAL_SOURCE_FACT_INVALID")
                for key, day in (
                    ("first_observed_session", _market_date(str(row["first_observed_at"]))),
                    ("source_available_session", (
                        _iso_date(str(row["source_published_date"]))
                        if row["source_published_date"] else ""
                    )),
                ):
                    if row[key] and (not day or row[key] != _next_session(sessions, day)):
                        raise FinancialCandidateError("FINANCIAL_STORED_AVAILABILITY_INVALID")
                status = row["availability_status"]
                effective = str(row["effective_available_session"])
                basis = row["revision_basis"]
                if basis not in {"source_version", "observed_correction"}:
                    raise FinancialCandidateError("FINANCIAL_STORED_AVAILABILITY_INVALID")
                if status == "available":
                    available = str(row["source_available_session"])
                    if not available or effective not in session_set or effective < available:
                        raise FinancialCandidateError("FINANCIAL_STORED_AVAILABILITY_INVALID")
                    if basis == "observed_correction" and (
                        not row["first_observed_session"]
                        or effective < row["first_observed_session"]
                    ):
                        raise FinancialCandidateError("FINANCIAL_STORED_AVAILABILITY_INVALID")
                    role = (
                        "pre_start_seed" if effective < descriptor.coverage_start else "in_coverage"
                    )
                    if row["coverage_role"] != role:
                        raise FinancialCandidateError("FINANCIAL_STORED_AVAILABILITY_INVALID")
                elif status in {"quarantined", "pending_calendar"}:
                    if effective or row["coverage_role"] != status:
                        raise FinancialCandidateError("FINANCIAL_STORED_AVAILABILITY_INVALID")
                    if status == "quarantined":
                        quarantine_hashes.append(str(row["source_row_sha256"]))
                else:
                    raise FinancialCandidateError("FINANCIAL_STORED_AVAILABILITY_INVALID")
            del originals
        expected_summary = {
            "status": "validated", "table_count": 3,
            "row_count": sum(int(item["row_count"]) for item in references),
            "object_count": sum(int(item["object_count"]) for item in references),
            "raw_batch_count": len(evidence),
        }
        if manifest["validation_summary"] != expected_summary:
            raise FinancialCandidateError("FINANCIAL_VALIDATION_SUMMARY_INVALID")
        if manifest["quarantine"] != {
            "row_count": len(quarantine_hashes), "rows_sha256": _sha(sorted(quarantine_hashes)),
        }:
            raise FinancialCandidateError("FINANCIAL_QUARANTINE_INVALID")
        return descriptor

    def validate(self, manifest_sha256: str) -> FinancialFamilyCandidate:
        manifest = self._read_family(manifest_sha256)
        descriptor = self._descriptor(manifest_sha256, manifest)
        source_collection = manifest["source_collection"]
        assert isinstance(source_collection, Mapping)
        if (
            descriptor.discovery_baseline_session is not None
            and "prior_candidate_manifest_sha256" in source_collection
        ):
            return self._validate_daily_family(manifest_sha256, manifest, descriptor)
        evidence = self._read_evidence_index(manifest["raw_evidence"])
        current_evidence = self._read_evidence_index(manifest["current_raw_evidence"])
        if len(evidence) != descriptor.raw_batch_count:
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_COUNT_INVALID")
        contract = self._manifest_collection_contract(manifest)
        evidence_shards = self._manifest_evidence_shards(manifest)
        if contract.shards != evidence_shards:
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_SHARD_SET_INVALID")
        daily = descriptor.discovery_baseline_session is not None
        canonical_evidence = _merge_evidence_descriptors(evidence)
        if canonical_evidence != _merge_evidence_descriptors((*evidence, *current_evidence)) or len(
            canonical_evidence
        ) != len(evidence):
            raise FinancialCandidateError("FINANCIAL_REFRESH_EVIDENCE_UNION_INVALID")
        _validate_contract(contract)
        current_fields = (
            self._validate_evidence_entries(current_evidence, contract=contract)
            if current_evidence
            else dict(contract.endpoint_fields)
        )
        endpoint_fields = self._validate_evidence_entries(
            evidence,
            contract=contract,
            historical=True,
        )
        if endpoint_fields != current_fields:
            raise FinancialCandidateError("FINANCIAL_SOURCE_SCHEMA_DRIFT")
        sessions = self._validated_market_sessions(
            str(manifest["source_generation_manifest_sha256"]),
            descriptor.observation_through_session,
        )
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            str(manifest["source_generation_manifest_sha256"])
        )
        checkpoints = tuple(_checkpoint_from_evidence(item) for item in evidence)
        current_checkpoints = tuple(_checkpoint_from_evidence(item) for item in current_evidence)
        source_collection = manifest["source_collection"]
        assert isinstance(source_collection, Mapping)
        finished_at = _aware_iso(str(source_collection["finished_at"]))
        if _market_date(finished_at) < descriptor.observation_through_session or any(
            _aware_iso(item.collected_at) > finished_at for item in checkpoints
        ):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        historical = {item.instrument_id: item.ts_code for item in lifecycles}
        self._validate_target_set(
            current_checkpoints,
            historical,
            contract,
            targeted=daily,
        )
        self._validate_historical_identities(checkpoints, historical)
        in_scope_at_start = {
            item.instrument_id
            for item in lifecycles
            if item.listed_from <= descriptor.coverage_start
            and (not item.listed_to or item.listed_to >= descriptor.coverage_start)
        }
        tables = manifest["tables"]
        assert isinstance(tables, list)
        references: dict[str, Mapping[str, object]] = {}
        for reference in tables:
            if not isinstance(reference, Mapping):
                raise FinancialCandidateError("FINANCIAL_TABLE_REFERENCE_INVALID")
            endpoint = _TABLE_ENDPOINTS.get(str(reference.get("name")))
            if endpoint is None or endpoint in references:
                raise FinancialCandidateError("FINANCIAL_TABLE_REFERENCE_INVALID")
            references[endpoint] = reference
        if tuple(references) != FINANCIAL_ENDPOINTS:
            raise FinancialCandidateError("FINANCIAL_TABLE_SET_INVALID")
        total_row_count = 0
        quarantine_hashes: list[str] = []
        checkpoints_by_instrument: dict[
            tuple[str, str], list[FinancialShardCheckpoint]
        ] = defaultdict(list)
        for checkpoint in checkpoints:
            checkpoints_by_instrument[(checkpoint.endpoint, checkpoint.instrument_id)].append(
                checkpoint
            )
        workset = _PublishedFinancialRowIndex(self._root)
        try:
            for endpoint in FINANCIAL_ENDPOINTS:
                workset.clear_deltas()
                for (group_endpoint, instrument_id), grouped in sorted(
                    checkpoints_by_instrument.items()
                ):
                    if group_endpoint != endpoint:
                        continue
                    versions, quarantine = self._canonical_versions(
                        tuple(grouped),
                        endpoint_fields[endpoint],
                        sessions,
                    )
                    retained = self._retain_coverage_versions(
                        versions,
                        descriptor.coverage_start,
                        {instrument_id} if instrument_id in in_scope_at_start else set(),
                    )[endpoint]
                    rows = canonicalize_parquet_rows(
                        [
                            _version_row(version, endpoint_fields[endpoint])
                            for version in retained
                        ],
                        _table_contract(_ENDPOINT_TABLES[endpoint], endpoint_fields[endpoint]),
                    )
                    for row in rows:
                        workset.add_delta(endpoint, row)
                    quarantine_hashes.extend(
                        item.source_row_sha256 for item in quarantine
                    )
                    del versions, retained, quarantine, rows
                workset.finish()
                row_count = workset.delta_count(endpoint)
                self._validate_materialized_table(
                    endpoint,
                    endpoint_fields[endpoint],
                    workset.deltas(endpoint),
                    row_count,
                    sessions,
                    references[endpoint],
                )
                total_row_count += row_count
        finally:
            workset.close()
        summary = manifest["validation_summary"]
        if not isinstance(summary, Mapping) or summary != {
            "status": "validated",
            "table_count": 3,
            "row_count": total_row_count,
            "object_count": sum(int(item["object_count"]) for item in tables),
            "raw_batch_count": len(evidence),
        }:
            raise FinancialCandidateError("FINANCIAL_VALIDATION_SUMMARY_INVALID")
        coverage = manifest["dataset_coverage"]
        assert isinstance(coverage, Mapping)
        if daily:
            _validated_discovery_coverage(coverage)
        elif coverage != {
            "kind": "financial-observation-range",
            "start": descriptor.coverage_start,
            "observation_through_session": descriptor.observation_through_session,
            "expected_instrument_count": len(historical),
            "expected_shard_count": len(current_evidence),
            "completed_shard_count": len(current_evidence),
            "reconciliation_status": "complete",
            "historical_reconciliation_watermark": descriptor.observation_through_session,
            "revision_coverage": "source-dated-and-first-observed-corrections",
            "seed_policy": "annual-stock-and-ttm-dependency-seeds",
        }:
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        quarantine_manifest = manifest["quarantine"]
        if not isinstance(quarantine_manifest, Mapping) or quarantine_manifest != {
            "row_count": len(quarantine_hashes),
            "rows_sha256": _sha(sorted(quarantine_hashes)),
        }:
            raise FinancialCandidateError("FINANCIAL_QUARANTINE_INVALID")
        return descriptor

    def _validate_daily_family(
        self,
        manifest_sha256: str,
        manifest: Mapping[str, object],
        descriptor: FinancialFamilyCandidate,
    ) -> FinancialFamilyCandidate:
        source_collection = manifest["source_collection"]
        assert isinstance(source_collection, Mapping)
        prior_manifest_sha256 = str(
            source_collection["prior_candidate_manifest_sha256"]
        )
        if prior_manifest_sha256 == manifest_sha256:
            raise FinancialCandidateError("FINANCIAL_DAILY_PARENT_INVALID")
        prior_manifest = self._read_family(prior_manifest_sha256)
        prior = self._descriptor(prior_manifest_sha256, prior_manifest)
        contract = self._manifest_collection_contract(manifest)
        if not _compatible_collection_contracts(
            self._manifest_collection_contract(prior_manifest), contract
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CONTRACT_MISMATCH")
        _validate_contract(contract)
        evidence = self._read_evidence_index(manifest["raw_evidence"])
        current_evidence = self._read_evidence_index(manifest["current_raw_evidence"])
        prior_evidence = self._read_daily_parent_evidence_index(
            prior_manifest["raw_evidence"]
        )
        canonical_evidence = _merge_evidence_descriptors(evidence)
        expected_evidence = _merge_evidence_descriptors(
            (*prior_evidence, *current_evidence)
        )
        if (
            canonical_evidence != expected_evidence
            or len(canonical_evidence) != len(evidence)
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_EVIDENCE_UNION_INVALID")
        current_fields = (
            self._validate_evidence_entries(current_evidence, contract=contract)
            if current_evidence
            else dict(contract.endpoint_fields)
        )
        endpoint_fields = dict(contract.endpoint_fields)
        if current_fields != endpoint_fields:
            raise FinancialCandidateError("FINANCIAL_SOURCE_SCHEMA_DRIFT")
        checkpoints = tuple(_checkpoint_from_evidence(item) for item in evidence)
        current_checkpoints = tuple(
            _checkpoint_from_evidence(item) for item in current_evidence
        )
        prior_checkpoints = tuple(
            _checkpoint_from_evidence(item) for item in prior_evidence
        )
        sessions = self._prevalidated_market_sessions(
            str(manifest["source_generation_manifest_sha256"]),
            descriptor.observation_through_session,
        )
        prior_sessions = self._prevalidated_market_sessions(
            str(prior_manifest["source_generation_manifest_sha256"]),
            prior.observation_through_session,
        )
        if [item for item in sessions if item <= prior.observation_through_session] != (
            prior_sessions
        ):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CALENDAR_MISMATCH")
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            str(manifest["source_generation_manifest_sha256"])
        )
        historical = {item.instrument_id: item.ts_code for item in lifecycles}
        self._validate_target_set(
            current_checkpoints,
            historical,
            contract,
            targeted=True,
        )
        self._validate_historical_identities(checkpoints, historical)
        finished_at = _aware_iso(str(source_collection["finished_at"]))
        if _market_date(finished_at) < descriptor.observation_through_session or any(
            _aware_iso(item.collected_at) > finished_at for item in current_checkpoints
        ):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        delta_counts, published, quarantine_hashes, quarantine_added, _reports = (
            self._daily_table_deltas(
            current_checkpoints,
            prior_candidate_manifest_sha256=prior_manifest_sha256,
            calendar_instruments=self._calendar_reprojection_instruments(
                str(source_collection["prior_candidate_manifest_sha256"]), prior_sessions, sessions,
                frozenset(historical),
            ),
            prior_checkpoints=prior_checkpoints,
            endpoint_fields=endpoint_fields,
            coverage_start=descriptor.coverage_start,
            current_sessions=sessions,
            prior_sessions=prior_sessions,
            current_lifecycles=lifecycles,
            )
        )
        if quarantine_added:
            raise FinancialCandidateError("FINANCIAL_QUARANTINE_INVALID")
        expected_quarantine = (
            dict(prior_manifest["quarantine"])
            if quarantine_hashes is None
            else {
                "row_count": len(quarantine_hashes),
                "rows_sha256": _sha(list(quarantine_hashes)),
            }
        )
        if manifest["quarantine"] != expected_quarantine:
            raise FinancialCandidateError("FINANCIAL_QUARANTINE_INVALID")
        prior_references = {
            str(item["name"]): item
            for item in prior_manifest["tables"]
            if isinstance(item, Mapping)
        }
        current_references = {
            str(item["name"]): item
            for item in manifest["tables"]
            if isinstance(item, Mapping)
        }
        if tuple(current_references) != tuple(_ENDPOINT_TABLES.values()):
            raise FinancialCandidateError("FINANCIAL_TABLE_SET_INVALID")
        for endpoint in FINANCIAL_ENDPOINTS:
            table_name = _ENDPOINT_TABLES[endpoint]
            if delta_counts[endpoint]:
                assert published is not None
                self._validate_incremental_table(
                    endpoint,
                    endpoint_fields[endpoint],
                    prior_references[table_name],
                    current_references[table_name],
                    published.deltas(endpoint),
                    delta_counts[endpoint],
                    sessions,
                )
            elif current_references[table_name] != prior_references[table_name]:
                raise FinancialCandidateError("FINANCIAL_TABLE_REFERENCE_INVALID")
        summary = manifest["validation_summary"]
        tables = manifest["tables"]
        assert isinstance(tables, list)
        if not isinstance(summary, Mapping) or summary != {
            "status": "validated",
            "table_count": 3,
            "row_count": sum(int(item["row_count"]) for item in tables),
            "object_count": sum(int(item["object_count"]) for item in tables),
            "raw_batch_count": len(evidence),
        }:
            raise FinancialCandidateError("FINANCIAL_VALIDATION_SUMMARY_INVALID")
        coverage = manifest["dataset_coverage"]
        if not isinstance(coverage, Mapping):
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        _validated_discovery_coverage(coverage)
        if (
            descriptor.discovery_baseline_session
            != (prior.discovery_baseline_session or prior.observation_through_session)
            or prior.observation_through_session > descriptor.observation_through_session
        ):
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        return descriptor

    def report_inventory(self, manifest_sha256: str, *, through: str):
        """Report presence is independent of field nulls and session availability."""
        manifest = self._read_family(manifest_sha256)
        descriptor = self._descriptor(manifest_sha256, manifest)
        endpoint_fields = dict(self._manifest_collection_contract(manifest).endpoint_fields)
        sessions = self._prevalidated_market_sessions(
            str(manifest["source_generation_manifest_sha256"]),
            descriptor.observation_through_session,
        )
        published = self._published_rows(manifest_sha256, endpoint_fields, sessions)
        return {
            endpoint: published.report_inventory(endpoint, through)
            for endpoint in FINANCIAL_ENDPOINTS
        }

    def read_table(self, manifest_sha256: str, table_name: str) -> tuple[dict[str, object], ...]:
        manifest = self._read_family(manifest_sha256)
        evidence = self._read_evidence_index(manifest["current_raw_evidence"])
        contract = self._manifest_collection_contract(manifest)
        fields = (
            self._validate_evidence_entries(evidence, contract=contract)
            if evidence
            else dict(contract.endpoint_fields)
        )
        endpoint = _TABLE_ENDPOINTS.get(table_name)
        if endpoint is None:
            raise FinancialCandidateError("FINANCIAL_TABLE_NOT_FOUND")
        reference = next(
            item
            for item in manifest["tables"]
            if isinstance(item, Mapping) and item.get("name") == table_name
        )
        descriptor = self._descriptor(manifest_sha256, manifest)
        sessions = self._validated_market_sessions(
            str(manifest["source_generation_manifest_sha256"]),
            descriptor.observation_through_session,
        )
        return tuple(self._open_table(endpoint, fields[endpoint], reference, sessions))

    def read_financial_rows(
        self,
        manifest_sha256: str,
        endpoint: str,
        source_columns: tuple[str, ...],
        sessions: tuple[str, ...],
        instrument_ids: frozenset[str],
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            self.read_financial_table(
                manifest_sha256,
                endpoint,
                source_columns,
                sessions,
                instrument_ids,
            ).to_pylist()
        )

    def read_financial_table(
        self,
        manifest_sha256: str,
        endpoint: str,
        source_columns: tuple[str, ...],
        sessions: tuple[str, ...],
        instrument_ids: frozenset[str],
        *,
        compact_history: bool = True,
    ) -> pa.Table:
        if endpoint not in FINANCIAL_ENDPOINTS:
            raise FinancialCandidateError("FINANCIAL_ENDPOINT_INVALID")
        manifest = self._read_family(manifest_sha256)
        descriptor = self._descriptor(manifest_sha256, manifest)
        through_session = sessions[-1] if sessions else ""
        if not sessions or not all(
            descriptor.coverage_start <= session <= descriptor.observation_through_session
            for session in sessions
        ):
            raise FinancialCandidateError("FINANCIAL_SERIES_COVERAGE_INVALID")
        try:
            market = self._market.inspect_root(str(manifest["source_generation_manifest_sha256"]))
        except GenerationStoreError as error:
            raise FinancialCandidateError("MARKET_GENERATION_INVALID") from error
        if sessions != tuple(sorted(set(sessions))) or any(
            session not in market.research_sessions for session in sessions
        ):
            raise FinancialCandidateError("FINANCIAL_SERIES_SESSION_INVALID")
        reference = next(
            (
                item
                for item in manifest["tables"]
                if isinstance(item, Mapping) and item.get("name") == _ENDPOINT_TABLES[endpoint]
            ),
            None,
        )
        if not isinstance(reference, Mapping):
            raise FinancialCandidateError("FINANCIAL_TABLE_NOT_FOUND")
        table_manifest_sha256 = str(reference.get("manifest_sha256"))
        table_manifest = self._read_json(
            self._manifest_path(table_manifest_sha256),
            table_manifest_sha256,
            int(reference.get("manifest_byte_count", -1)),
        )
        source_fields_value = table_manifest.get("source_fields")
        if not isinstance(source_fields_value, list) or not all(
            isinstance(value, str) and value for value in source_fields_value
        ):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        source_fields = tuple(source_fields_value)
        contract = _table_contract(_ENDPOINT_TABLES[endpoint], source_fields)
        if (
            table_manifest.get("format") != _TABLE_FORMAT
            or table_manifest.get("version") != _VERSION
            or table_manifest.get("table") != _ENDPOINT_TABLES[endpoint]
            or table_manifest.get("source_endpoint") != endpoint
            or table_manifest.get("writer_contract") != contract.descriptor()
            or not source_columns
            or len(set(source_columns)) != len(source_columns)
            or not set(source_columns).issubset(contract.schema.names)
        ):
            raise FinancialCandidateError("FINANCIAL_SERIES_PROJECTION_INVALID")
        objects = table_manifest.get("objects")
        if (
            not isinstance(objects, list)
            or table_manifest.get("object_count", len(objects)) != len(objects)
            or reference.get("object_count") != len(objects)
        ):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        expected_schema = pa.schema([contract.schema.field(name) for name in source_columns])
        query_columns = tuple(
            dict.fromkeys(
                (
                    *source_columns,
                    *_FINANCIAL_HISTORY_IDENTITY_FIELDS,
                    *_FINANCIAL_HISTORY_VERSION_FIELDS,
                    "logical_revision_group_sha256",
                    "source_available_session",
                    "first_observed_session",
                )
            )
        )
        query_schema = pa.schema([contract.schema.field(name) for name in query_columns])
        tables: list[pa.Table] = []
        for ordinal, object_ref in enumerate(objects):
            if not isinstance(object_ref, Mapping) or object_ref.get("ordinal") != ordinal:
                raise FinancialCandidateError("FINANCIAL_OBJECT_REFERENCE_INVALID")
            first_sort_key = object_ref.get("first_sort_key")
            if (
                isinstance(first_sort_key, list)
                and first_sort_key
                and str(first_sort_key[0])
                and str(first_sort_key[0]) > through_session
            ):
                continue
            content = self._read(
                self._object_path(str(object_ref.get("sha256"))),
                str(object_ref.get("sha256")),
                int(object_ref.get("byte_count", -1)),
                GENERATION_OBJECT_MAX_BYTES,
            )
            try:
                table = pq.read_table(
                    pa.BufferReader(content),
                    columns=list(query_columns),
                    filters=[
                        ("instrument_id", "in", sorted(instrument_ids)),
                        ("effective_available_session", "<=", through_session),
                    ],
                )
            except (ArrowException, TypeError, ValueError) as error:
                raise FinancialCandidateError("FINANCIAL_OBJECT_INVALID") from error
            record_parquet_scan(
                source="financial",
                row_count=table.num_rows,
                column_count=len(table.column_names),
            )
            if table.schema != query_schema:
                raise FinancialCandidateError("FINANCIAL_OBJECT_SCHEMA_INVALID")
            tables.append(table)
            del table, content
            pa.default_memory_pool().release_unused()
        if not tables:
            return pa.Table.from_batches([], schema=expected_schema)
        overlaid = _overlay_financial_table(pa.concat_tables(tables), query_schema)
        overlaid = _project_agreeing_financial_values(
            overlaid, tuple(name for name in source_columns
                            if name in source_fields and name not in _REQUIRED_SOURCE_FIELDS),
            through_session, descriptor.coverage_start,
        )
        compacted = (
            _compact_financial_history(overlaid, sessions[0]) if compact_history else overlaid
        )
        sort_columns = tuple(
            name
            for name in (
                "effective_available_session",
                "instrument_id",
                "source_report_period",
                "source_report_type",
                "source_company_type",
                "source_row_sha256",
            )
            if name in compacted.column_names
        )
        if sort_columns:
            compacted = compacted.sort_by([(name, "ascending") for name in sort_columns])
        return compacted.select(source_columns)

    def quarantined_row_count(self, manifest_sha256: str) -> int:
        manifest = self._read_family(manifest_sha256)
        quarantine = manifest["quarantine"]
        if not isinstance(quarantine, Mapping):
            raise FinancialCandidateError("FINANCIAL_QUARANTINE_INVALID")
        return int(quarantine["row_count"])

    def _validated_market_sessions(self, manifest_sha256: str, through: str) -> list[str]:
        try:
            descriptor = self._market.validate_market_generation(manifest_sha256)
            date.fromisoformat(through)
        except (GenerationStoreError, ValueError) as error:
            raise FinancialCandidateError("MARKET_GENERATION_INVALID") from error
        sessions = list(descriptor.research_sessions)
        if through not in sessions:
            raise FinancialCandidateError("FINANCIAL_OBSERVATION_CUTOFF_INVALID")
        return [session for session in sessions if session <= through]

    def _prevalidated_market_sessions(
        self,
        manifest_sha256: str,
        through: str,
    ) -> list[str]:
        """Read calendar coordinates from an immutable, already-published root."""
        try:
            descriptor = self._market.inspect_root(manifest_sha256)
            date.fromisoformat(through)
        except (GenerationStoreError, ValueError) as error:
            raise FinancialCandidateError("MARKET_GENERATION_INVALID") from error
        sessions = list(descriptor.research_sessions)
        if through not in sessions:
            raise FinancialCandidateError("FINANCIAL_OBSERVATION_CUTOFF_INVALID")
        return [session for session in sessions if session <= through]

    def _validated_evidence(
        self,
        collection: CompletedFinancialCollection,
        historical: Mapping[str, str],
        *,
        targeted: bool = False,
    ) -> dict[str, tuple[str, ...]]:
        if (
            (collection.target_count < 0 if targeted else collection.target_count < 3)
            or len(collection.shards) != collection.target_count
            or tuple(item.ordinal for item in collection.shards)
            != tuple(range(collection.target_count))
            or any(
                item.status != "completed"
                or item.batch_sha256 is None
                or item.collected_at is None
                or item.first_observed_at is None
                for item in collection.shards
            )
        ):
            raise FinancialCandidateError("FINANCIAL_COLLECTION_INCOMPLETE")
        try:
            finished_at = datetime.fromisoformat(collection.finished_at)
        except ValueError as error:
            raise FinancialCandidateError("FINANCIAL_COLLECTION_INVALID") from error
        if finished_at.tzinfo is None:
            raise FinancialCandidateError("FINANCIAL_COLLECTION_INVALID")
        if any(
            item.collected_at is None
            or item.first_observed_at is None
            or datetime.fromisoformat(item.collected_at) > finished_at
            or datetime.fromisoformat(item.first_observed_at)
            > datetime.fromisoformat(item.collected_at)
            for item in collection.shards
        ):
            raise FinancialCandidateError("FINANCIAL_COLLECTION_INVALID")
        instruments = {item.instrument_id for item in collection.shards}
        if (not targeted and instruments != set(historical)) or not instruments.issubset(
            historical
        ):
            raise FinancialCandidateError("FINANCIAL_COLLECTION_TARGET_SET_INVALID")
        self._validate_target_set(
            collection.shards,
            historical,
            collection.contract,
            targeted=targeted,
        )
        if not collection.shards:
            return dict(collection.contract.endpoint_fields)
        try:
            return self._validate_evidence_entries(
                [self._evidence_descriptor(checkpoint) for checkpoint in collection.shards],
                contract=collection.contract,
            )
        except (FinancialCollectionError, AddressedFileError) as error:
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID") from error

    @staticmethod
    def _validate_target_set(
        checkpoints: Sequence[FinancialShardCheckpoint],
        historical: Mapping[str, str],
        contract: FinancialCollectionContract,
        *,
        targeted: bool = False,
    ) -> None:
        instruments = (
            {item.instrument_id for item in checkpoints} if targeted else set(historical)
        )
        expected = {
            (endpoint, instrument, shard.name)
            for endpoint in FINANCIAL_ENDPOINTS
            for instrument in instruments
            for shard in contract.shards
        }
        actual = {(item.endpoint, item.instrument_id, item.shard) for item in checkpoints}
        if (
            actual != expected
            or len(actual) != len(checkpoints)
            or any(historical.get(item.instrument_id) != item.ts_code for item in checkpoints)
        ):
            raise FinancialCandidateError("FINANCIAL_COLLECTION_TARGET_SET_INVALID")

    @staticmethod
    def _validate_historical_identities(
        checkpoints: Sequence[FinancialShardCheckpoint],
        historical: Mapping[str, str],
    ) -> None:
        if any(historical.get(item.instrument_id) != item.ts_code for item in checkpoints):
            raise FinancialCandidateError("FINANCIAL_HISTORICAL_IDENTITY_INVALID")

    def _validate_evidence_entries(
        self,
        entries: Sequence[Mapping[str, object]],
        *,
        loaded_batches: Mapping[str | None, dict[str, object]] | None = None,
        contract: FinancialCollectionContract,
        historical: bool = False,
    ) -> dict[str, tuple[str, ...]]:
        endpoint_fields: dict[str, tuple[str, ...]] = {}
        seen: set[tuple[str, str, str]] = set()
        for ordinal, entry in enumerate(entries):
            if entry.get("ordinal") != ordinal:
                raise FinancialCandidateError("FINANCIAL_EVIDENCE_ORDER_INVALID")
            endpoint = str(entry.get("endpoint"))
            batch_sha256 = str(entry.get("batch_sha256"))
            batch = (
                loaded_batches.get(batch_sha256)
                if loaded_batches is not None
                else self._read_raw_batch(batch_sha256)
            )
            if batch is None:
                raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
            fields = self._validate_raw_batch(
                batch,
                entry,
                contract,
            )
            if dict(contract.endpoint_fields).get(endpoint) != fields:
                raise FinancialCandidateError("FINANCIAL_SOURCE_SCHEMA_DRIFT")
            previous = endpoint_fields.setdefault(endpoint, fields)
            if previous != fields:
                raise FinancialCandidateError("FINANCIAL_SOURCE_SCHEMA_DRIFT")
            identity = (
                endpoint,
                str(entry.get("instrument_id")),
                str(entry.get("shard")),
            )
            if identity in seen and not historical:
                raise FinancialCandidateError("FINANCIAL_EVIDENCE_DUPLICATE")
            seen.add(identity)
        if tuple(endpoint_fields) != FINANCIAL_ENDPOINTS:
            raise FinancialCandidateError("FINANCIAL_ENDPOINT_SET_INVALID")
        return endpoint_fields

    def _read_raw_batch(self, batch_sha256: str) -> dict[str, object]:
        try:
            return self._raw.read(batch_sha256)
        except FinancialCollectionError as error:
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID") from error

    def _require_evidence_present(self, entries: Sequence[Mapping[str, object]]) -> None:
        try:
            for entry in entries:
                self._raw.require_present(str(entry.get("batch_sha256")))
        except FinancialCollectionError as error:
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID") from error

    def _validate_raw_batch(
        self,
        batch: Mapping[str, object],
        entry: Mapping[str, object],
        contract: FinancialCollectionContract,
    ) -> tuple[str, ...]:
        if set(batch) != {
            "format",
            "version",
            "source_contract_version",
            "endpoint",
            "parameters",
            "returned_fields",
            "items",
            "row_count",
            "source_date_extent",
            "payload_sha256",
        }:
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
        if (
            batch.get("format") != "thesistrace-raw-financial-batch"
            or batch.get("version") != 1
            or batch.get("source_contract_version") != FINANCIAL_SOURCE_CONTRACT_VERSION
            or batch.get("endpoint") != entry.get("endpoint")
            or not isinstance(batch.get("parameters"), Mapping)
            or batch["parameters"].get("ts_code") != entry.get("ts_code")
        ):
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
        fields_value = batch.get("returned_fields")
        items = batch.get("items")
        if (
            not isinstance(fields_value, list)
            or not all(isinstance(value, str) and value for value in fields_value)
            or len(fields_value) != len(set(fields_value))
            or not _REQUIRED_SOURCE_FIELDS.issubset(fields_value)
            or set(fields_value).intersection(_METADATA_FIELDS)
            or not isinstance(items, list)
            or batch.get("row_count") != len(items)
            or any(not isinstance(item, list) or len(item) != len(fields_value) for item in items)
        ):
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
        payload = {"fields": fields_value, "items": items}
        if batch.get("payload_sha256") != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
        code_position = fields_value.index("ts_code")
        announcement_position = fields_value.index("ann_date")
        report_period_position = fields_value.index("end_date")
        final_position = fields_value.index("f_ann_date") if "f_ann_date" in fields_value else None
        publications: list[str] = []
        for item in items:
            if item[code_position] != entry.get("ts_code"):
                raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
            announcement = _source_date(item[announcement_position], required=False)
            final = (
                "" if final_position is None else _source_date(item[final_position], required=False)
            )
            _source_date(item[report_period_position], required=True)
            if final or announcement:
                publications.append(final or announcement)
        expected_extent = None if not publications else [min(publications), max(publications)]
        if batch.get("source_date_extent") != expected_extent:
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
        parameters = batch["parameters"]
        assert isinstance(parameters, Mapping)
        if (
            entry.get("shard") != "complete-history"
            or contract.shards != (FinancialDateShard("complete-history"),)
            or dict(parameters) != {"ts_code": entry.get("ts_code")}
        ):
            raise FinancialCandidateError("FINANCIAL_SHARD_PARAMETERS_INVALID")
        truncation_boundary = dict(contract.suspected_truncation_row_counts).get(
            str(entry.get("endpoint"))
        )
        if truncation_boundary is not None and len(items) >= truncation_boundary:
            raise FinancialCandidateError("FINANCIAL_SUSPECTED_TRUNCATION")
        return tuple(fields_value)

    def _canonical_versions(
        self,
        checkpoints: Sequence[FinancialShardCheckpoint],
        source_fields: tuple[str, ...],
        sessions: list[str],
    ) -> tuple[list[CanonicalFinancialVersion], list[CanonicalFinancialVersion]]:
        canonical = list(self._iter_canonical_versions(checkpoints, source_fields, sessions))
        quarantine = [
            version for version in canonical if version.availability_status == "quarantined"
        ]
        return canonical, quarantine

    def _iter_canonical_versions(
        self,
        checkpoints: Sequence[FinancialShardCheckpoint],
        source_fields: tuple[str, ...],
        sessions: list[str],
    ) -> Iterator[CanonicalFinancialVersion]:
        grouped: dict[tuple[str, str], list[FinancialShardCheckpoint]] = defaultdict(list)
        for checkpoint in checkpoints:
            grouped[(checkpoint.endpoint, checkpoint.instrument_id)].append(checkpoint)
        for group in grouped.values():
            observations: list[FinancialSourceObservation] = []
            for checkpoint in group:
                assert checkpoint.batch_sha256 is not None
                batch = self._read_raw_batch(checkpoint.batch_sha256)
                for item in batch["items"]:
                    assert isinstance(item, list)
                    observations.append(
                        FinancialSourceObservation(
                            endpoint=checkpoint.endpoint,
                            instrument_id=checkpoint.instrument_id,
                            ts_code=checkpoint.ts_code,
                            source_fields=source_fields,
                            source_values=tuple(item),
                            first_observed_at=_aware_iso(checkpoint.first_observed_at),
                            raw_batch_sha256=checkpoint.batch_sha256,
                        )
                    )
                del batch
            yield from FinancialVersionProjector().project(observations, sessions)

    def _retain_coverage_versions(
        self,
        versions: Sequence[CanonicalFinancialVersion],
        coverage_start: str,
        in_scope_at_start: set[str],
    ) -> dict[str, list[CanonicalFinancialVersion]]:
        retained: dict[str, list[CanonicalFinancialVersion]] = {
            endpoint: [] for endpoint in FINANCIAL_ENDPOINTS
        }
        seed_candidates: dict[
            tuple[str, str, str], list[CanonicalFinancialVersion]
        ] = defaultdict(list)
        selections = {
            (field.source_endpoint, field.report_period_selection) for field in FINANCIAL_FIELDS
        }
        for version in versions:
            if version.availability_status != "available":
                retained[version.endpoint].append(version)
                continue
            if version.effective_available_session >= coverage_start:
                retained[version.endpoint].append(version)
                continue
            if version.instrument_id not in in_scope_at_start:
                continue
            source = version.source()
            report_period = str(source["end_date"])
            if str(source.get("report_type") or "") != "1":
                continue
            for endpoint, selection in selections:
                if endpoint != version.endpoint or selection == "latest_visible_ttm":
                    continue
                if selection == "latest_visible_full_year" and not report_period.endswith("1231"):
                    continue
                seed_candidates[(endpoint, version.instrument_id, selection)].append(version)
        retained_seed_ids: set[tuple[str, str, str]] = set()
        for candidates in seed_candidates.values():
            latest = max(
                candidates,
                key=lambda item: (
                    str(item.source()["end_date"]),
                    item.effective_available_session,
                    str(item.source().get("update_flag") or ""),
                    item.source_published_date,
                    _source_date(item.source().get("ann_date"), required=False),
                    item.first_observed_at,
                    item.source_row_sha256,
                ),
            )
            seed_id = (latest.endpoint, latest.instrument_id, latest.source_row_sha256)
            if seed_id not in retained_seed_ids:
                retained[latest.endpoint].append(replace(latest, coverage_role="pre_start_seed"))
                retained_seed_ids.add(seed_id)
        ttm_endpoints = {endpoint for endpoint, selection in selections
                         if selection == "latest_visible_ttm"}
        for seed in _ttm_coverage_seeds(versions, coverage_start, ttm_endpoints):
            seed_id = (seed.endpoint, seed.instrument_id, seed.source_row_sha256)
            if seed_id not in retained_seed_ids:
                retained[seed.endpoint].append(replace(seed, coverage_role="pre_start_seed"))
                retained_seed_ids.add(seed_id)
        return retained

    def _materialize_table(
        self,
        endpoint: str,
        source_fields: tuple[str, ...],
        rows: Iterator[dict[str, object]] | Sequence[dict[str, object]],
        row_count: int,
        sessions: list[str],
    ) -> dict[str, object]:
        table_name = _ENDPOINT_TABLES[endpoint]
        contract = _table_contract(table_name, source_fields)
        objects: list[dict[str, object]] = []
        written_rows = 0
        for group in _iter_partitioned_financial_rows(rows, sessions):
            objects.append(self._materialize_object(contract, group, len(objects)))
            written_rows += len(group)
        if written_rows != row_count:
            raise FinancialCandidateError("FINANCIAL_CANONICAL_PROJECTION_INVALID")
        manifest = {
            "format": _TABLE_FORMAT,
            "version": _VERSION,
            "table": table_name,
            "source_endpoint": endpoint,
            "source_fields": list(source_fields),
            "writer_contract": contract.descriptor(),
            "partitioning": {
                "kind": "research-session-block-with-row-cap",
                "session_count": GENERATION_SESSION_PARTITION_COUNT,
                "row_count": GENERATION_ROW_PARTITION_COUNT,
            },
            "row_count": row_count,
            "objects": objects,
        }
        content = self._manifest_bytes(manifest)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store(self._manifest_path(sha256), sha256, content)
        return {
            "name": table_name,
            "manifest_sha256": sha256,
            "manifest_byte_count": len(content),
            "row_count": row_count,
            "object_count": len(objects),
        }

    def _validate_materialized_table(
        self,
        endpoint: str,
        source_fields: tuple[str, ...],
        rows: Iterator[dict[str, object]] | Sequence[dict[str, object]],
        row_count: int,
        sessions: list[str],
        reference: Mapping[str, object],
    ) -> int:
        table_name = _ENDPOINT_TABLES[endpoint]
        contract = _table_contract(table_name, source_fields)
        referenced_manifest_sha256 = str(reference.get("manifest_sha256"))
        referenced_manifest = self._read_json(
            self._manifest_path(referenced_manifest_sha256),
            referenced_manifest_sha256,
            int(reference.get("manifest_byte_count", -1)),
        )
        referenced_objects = referenced_manifest.get("objects")
        if not isinstance(referenced_objects, list):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        objects: list[dict[str, object]] = []
        validated_rows = 0
        for group in _iter_partitioned_financial_rows(rows, sessions):
            content = parquet_bytes(group, contract)
            if len(content) > GENERATION_OBJECT_MAX_BYTES:
                raise FinancialCandidateError("FINANCIAL_OBJECT_TOO_LARGE")
            sha256 = hashlib.sha256(content).hexdigest()
            expected_object = {
                "ordinal": len(objects),
                "sha256": sha256,
                "byte_count": len(content),
                "row_count": len(group),
                "first_sort_key": [group[0][key] for key in contract.sort_keys],
                "last_sort_key": [group[-1][key] for key in contract.sort_keys],
            }
            if (
                len(referenced_objects) <= len(objects)
                or referenced_objects[len(objects)] != expected_object
            ):
                raise FinancialCandidateError("FINANCIAL_CANONICAL_PROJECTION_INVALID")
            if self._read(
                self._object_path(sha256),
                sha256,
                len(content),
                GENERATION_OBJECT_MAX_BYTES,
            ) != content:
                raise FinancialCandidateError("FINANCIAL_OBJECT_ENCODING_INVALID")
            objects.append(expected_object)
            validated_rows += len(group)
        if validated_rows != row_count:
            raise FinancialCandidateError("FINANCIAL_CANONICAL_PROJECTION_INVALID")
        if len(referenced_objects) != len(objects):
            raise FinancialCandidateError("FINANCIAL_CANONICAL_PROJECTION_INVALID")
        manifest = {
            "format": _TABLE_FORMAT,
            "version": _VERSION,
            "table": table_name,
            "source_endpoint": endpoint,
            "source_fields": list(source_fields),
            "writer_contract": contract.descriptor(),
            "partitioning": {
                "kind": "research-session-block-with-row-cap",
                "session_count": GENERATION_SESSION_PARTITION_COUNT,
                "row_count": GENERATION_ROW_PARTITION_COUNT,
            },
            "row_count": row_count,
            "objects": objects,
        }
        manifest_content = self._manifest_bytes(manifest)
        manifest_sha256 = hashlib.sha256(manifest_content).hexdigest()
        expected_reference = {
            "name": table_name,
            "manifest_sha256": manifest_sha256,
            "manifest_byte_count": len(manifest_content),
            "row_count": row_count,
            "object_count": len(objects),
        }
        if dict(reference) != expected_reference:
            raise FinancialCandidateError("FINANCIAL_TABLE_REFERENCE_INVALID")
        if referenced_manifest != manifest:
            raise FinancialCandidateError("FINANCIAL_CANONICAL_PROJECTION_INVALID")
        return row_count

    def _materialize_object(
        self, contract: ParquetWriterContract, rows: list[dict[str, object]], ordinal: int
    ) -> dict[str, object]:
        content = parquet_bytes(rows, contract)
        if len(content) > GENERATION_OBJECT_MAX_BYTES:
            raise FinancialCandidateError("FINANCIAL_OBJECT_TOO_LARGE")
        sha256 = hashlib.sha256(content).hexdigest()
        self._store(self._object_path(sha256), sha256, content)
        return {
            "ordinal": ordinal,
            "sha256": sha256,
            "byte_count": len(content),
            "row_count": len(rows),
            "first_sort_key": [rows[0][key] for key in contract.sort_keys],
            "last_sort_key": [rows[-1][key] for key in contract.sort_keys],
        }

    def _open_table(
        self,
        endpoint: str,
        source_fields: tuple[str, ...],
        reference: Mapping[str, object],
        sessions: list[str],
    ) -> list[dict[str, object]]:
        return canonicalize_parquet_rows(
            list(self._iter_table_rows(endpoint, source_fields, reference, sessions)),
            _table_contract(_ENDPOINT_TABLES[endpoint], source_fields),
        )

    def _iter_table_rows(
        self,
        endpoint: str,
        source_fields: tuple[str, ...],
        reference: Mapping[str, object],
        sessions: list[str],
    ) -> Iterator[dict[str, object]]:
        manifest_sha256 = str(reference.get("manifest_sha256"))
        manifest = self._read_json(
            self._manifest_path(manifest_sha256),
            manifest_sha256,
            int(reference.get("manifest_byte_count", -1)),
        )
        table_name = _ENDPOINT_TABLES[endpoint]
        contract = _table_contract(table_name, source_fields)
        partitioning = manifest.get("partitioning")
        classic_partitioning = {
            "kind": "research-session-block-with-row-cap",
            "session_count": GENERATION_SESSION_PARTITION_COUNT,
            "row_count": GENERATION_ROW_PARTITION_COUNT,
        }
        layered = self._incremental_base_object_count(
            manifest,
            table_name=table_name,
            endpoint=endpoint,
            source_fields=source_fields,
            contract=contract,
        )
        if (
            manifest.get("format") != _TABLE_FORMAT
            or manifest.get("version") != _VERSION
            or manifest.get("table") != table_name
            or manifest.get("source_endpoint") != endpoint
            or manifest.get("source_fields") != list(source_fields)
            or manifest.get("writer_contract") != contract.descriptor()
            or (partitioning != classic_partitioning and layered is None)
        ):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        objects = manifest.get("objects")
        if not isinstance(objects, list):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        physical_row_count = 0
        seen: set[bytes] = set()
        # Reverse object order implements last-observation precedence with only
        # compact identities retained. Every physical object is still verified.
        boundaries: dict[int, tuple[int, int, tuple[object, ...], tuple[object, ...]]] = {}
        session_index = {session: index for index, session in enumerate(sessions)}
        for ordinal in reversed(range(len(objects))):
            object_ref = objects[ordinal]
            if not isinstance(object_ref, Mapping) or object_ref.get("ordinal") != ordinal:
                raise FinancialCandidateError("FINANCIAL_OBJECT_REFERENCE_INVALID")
            content = self._read(
                self._object_path(str(object_ref.get("sha256"))),
                str(object_ref.get("sha256")),
                int(object_ref.get("byte_count", -1)),
                GENERATION_OBJECT_MAX_BYTES,
            )
            try:
                table = pq.read_table(pa.BufferReader(content))
                if table.schema != contract.schema:
                    raise FinancialCandidateError("FINANCIAL_OBJECT_SCHEMA_INVALID")
                partition = canonicalize_parquet_rows(table.to_pylist(), contract)
                if parquet_bytes(partition, contract) != content:
                    raise FinancialCandidateError("FINANCIAL_OBJECT_ENCODING_INVALID")
            except (ArrowException, ParquetContractError, TypeError, ValueError) as error:
                raise FinancialCandidateError("FINANCIAL_OBJECT_INVALID") from error
            if (
                object_ref.get("row_count") != len(partition)
                or object_ref.get("first_sort_key")
                != ([partition[0][key] for key in contract.sort_keys] if partition else None)
                or object_ref.get("last_sort_key")
                != ([partition[-1][key] for key in contract.sort_keys] if partition else None)
            ):
                raise FinancialCandidateError("FINANCIAL_OBJECT_BOUNDARY_INVALID")
            physical_row_count += len(partition)
            if layered is None or ordinal >= layered:
                if not partition or _partition_financial_rows(partition, sessions) != [partition]:
                    raise FinancialCandidateError("FINANCIAL_TABLE_PARTITIONING_INVALID")
                session = str(partition[0]["effective_available_session"])
                block = (
                    session_index[session] // GENERATION_SESSION_PARTITION_COUNT if session else -1
                )
                boundaries[ordinal] = (
                    block, len(partition),
                    tuple(partition[0][key] for key in contract.sort_keys),
                    tuple(partition[-1][key] for key in contract.sort_keys),
                )
            for row in reversed(partition):
                if layered is not None:
                    source_hash = str(row["source_row_sha256"])
                    _require_sha256(source_hash)
                    identity = bytes.fromhex(source_hash)
                    if identity in seen:
                        continue
                    seen.add(identity)
                yield row
            del partition, table, content
        previous = None
        for ordinal in sorted(boundaries):
            block, count, first, last = boundaries[ordinal]
            if previous is not None:
                previous_block, previous_count, previous_last = previous
                if layered is None and previous_last >= first:
                    raise FinancialCandidateError("FINANCIAL_TABLE_ORDER_INVALID")
                if block < previous_block or (
                    block == previous_block and previous_count != GENERATION_ROW_PARTITION_COUNT
                ):
                    raise FinancialCandidateError("FINANCIAL_TABLE_PARTITIONING_INVALID")
            previous = (block, count, last)
        if (
            manifest.get("row_count") != physical_row_count
            or reference.get("row_count") != physical_row_count
        ):
            raise FinancialCandidateError("FINANCIAL_TABLE_ROW_COUNT_INVALID")
        if reference.get("object_count") != len(objects):
            raise FinancialCandidateError("FINANCIAL_TABLE_OBJECT_COUNT_INVALID")

    def _incremental_base_object_count(
        self,
        manifest: Mapping[str, object],
        *,
        table_name: str,
        endpoint: str,
        source_fields: tuple[str, ...],
        contract: ParquetWriterContract,
    ) -> int | None:
        partitioning = manifest.get("partitioning")
        if not isinstance(partitioning, Mapping) or partitioning.get("kind") != (
            "immutable-base-with-delta-objects"
        ):
            return None
        try:
            base_object_count = int(partitioning["base_object_count"])
            base_manifest_sha256 = str(partitioning["base_manifest_sha256"])
        except (KeyError, TypeError, ValueError) as error:
            raise FinancialCandidateError("FINANCIAL_INCREMENTAL_TABLE_INVALID") from error
        if dict(partitioning) != {
            "kind": "immutable-base-with-delta-objects",
            "session_count": GENERATION_SESSION_PARTITION_COUNT,
            "row_count": GENERATION_ROW_PARTITION_COUNT,
            "base_manifest_sha256": base_manifest_sha256,
            "base_object_count": base_object_count,
        }:
            raise FinancialCandidateError("FINANCIAL_INCREMENTAL_TABLE_INVALID")
        base_manifest = self._read_json(
            self._manifest_path(base_manifest_sha256),
            base_manifest_sha256,
        )
        base_objects = base_manifest.get("objects")
        objects = manifest.get("objects")
        if (
            base_manifest.get("format") != _TABLE_FORMAT
            or base_manifest.get("version") != _VERSION
            or base_manifest.get("table") != table_name
            or base_manifest.get("source_endpoint") != endpoint
            or base_manifest.get("source_fields") != list(source_fields)
            or base_manifest.get("writer_contract") != contract.descriptor()
            or not isinstance(base_objects, list)
            or not isinstance(objects, list)
            or base_object_count != len(base_objects)
            or objects[:base_object_count] != base_objects
        ):
            raise FinancialCandidateError("FINANCIAL_INCREMENTAL_TABLE_INVALID")
        return base_object_count

    def _materialize_evidence_index(
        self, shards: Sequence[FinancialShardCheckpoint]
    ) -> dict[str, object]:
        descriptors = [self._evidence_descriptor(item) for item in shards]
        chunks: list[dict[str, object]] = []
        for offset in range(0, len(descriptors), _EVIDENCE_CHUNK_SIZE):
            entries = descriptors[offset : offset + _EVIDENCE_CHUNK_SIZE]
            value = {
                "format": _EVIDENCE_CHUNK_FORMAT,
                "version": _VERSION,
                "first_ordinal": offset,
                "entries": entries,
            }
            content = self._manifest_bytes(value)
            sha256 = hashlib.sha256(content).hexdigest()
            self._store(self._manifest_path(sha256), sha256, content)
            chunks.append(
                {
                    "sha256": sha256,
                    "byte_count": len(content),
                    "entry_count": len(entries),
                    "first_ordinal": offset,
                }
            )
        index = {
            "format": _EVIDENCE_INDEX_FORMAT,
            "version": _VERSION,
            "entry_count": len(descriptors),
            "chunks": chunks,
        }
        content = self._manifest_bytes(index)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store(self._manifest_path(sha256), sha256, content)
        return {
            "manifest_sha256": sha256,
            "byte_count": len(content),
            "entry_count": len(descriptors),
        }

    def _read_evidence_index(self, reference: object) -> list[dict[str, object]]:
        if not isinstance(reference, Mapping):
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_REFERENCE_INVALID")
        sha256 = str(reference.get("manifest_sha256"))
        index = self._read_json(
            self._manifest_path(sha256), sha256, int(reference.get("byte_count", -1))
        )
        if index.get("format") != _EVIDENCE_INDEX_FORMAT or index.get("version") != _VERSION:
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_INDEX_INVALID")
        chunks = index.get("chunks")
        if not isinstance(chunks, list):
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_INDEX_INVALID")
        entries: list[dict[str, object]] = []
        for chunk_ref in chunks:
            if not isinstance(chunk_ref, Mapping):
                raise FinancialCandidateError("FINANCIAL_EVIDENCE_CHUNK_INVALID")
            chunk_sha = str(chunk_ref.get("sha256"))
            chunk = self._read_json(
                self._manifest_path(chunk_sha), chunk_sha, int(chunk_ref.get("byte_count", -1))
            )
            values = chunk.get("entries")
            if (
                chunk.get("format") != _EVIDENCE_CHUNK_FORMAT
                or chunk.get("version") != _VERSION
                or chunk.get("first_ordinal") != len(entries)
                or not isinstance(values, list)
                or chunk_ref.get("entry_count") != len(values)
            ):
                raise FinancialCandidateError("FINANCIAL_EVIDENCE_CHUNK_INVALID")
            entries.extend(values)
        if index.get("entry_count") != len(entries) or reference.get("entry_count") != len(entries):
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_COUNT_INVALID")
        return entries

    def _read_daily_parent_evidence_index(
        self,
        reference: object,
    ) -> list[dict[str, object]]:
        if isinstance(reference, Mapping):
            try:
                key = (
                    str(reference["manifest_sha256"]),
                    int(reference["byte_count"]),
                    int(reference["entry_count"]),
                )
            except (KeyError, TypeError, ValueError):
                key = None
            if key is not None and key == self._daily_parent_evidence_cache_key:
                return self._daily_parent_evidence_cache
        else:
            key = None
        entries = self._read_evidence_index(reference)
        if key is not None:
            self._daily_parent_evidence_cache_key = key
            self._daily_parent_evidence_cache = entries
        return entries

    @staticmethod
    def _evidence_descriptor(checkpoint: FinancialShardCheckpoint) -> dict[str, object]:
        return {
            "ordinal": checkpoint.ordinal,
            "endpoint": checkpoint.endpoint,
            "instrument_id": checkpoint.instrument_id,
            "ts_code": checkpoint.ts_code,
            "shard": checkpoint.shard,
            "batch_sha256": checkpoint.batch_sha256,
            "collected_at": checkpoint.collected_at,
            "first_observed_at": checkpoint.first_observed_at,
        }

    def _read_family(self, sha256: str) -> dict[str, object]:
        manifest = self._read_json(self._manifest_path(sha256), sha256)
        if (
            manifest.get("format") != _FAMILY_FORMAT
            or manifest.get("version") != _VERSION
            or manifest.get("family_id") != _FAMILY_ID
            or manifest.get("schema_contract") != _SCHEMA_CONTRACT
            or set(manifest)
            != {
                "format",
                "version",
                "family_id",
                "schema_contract",
                "source_generation_manifest_sha256",
                "source_collection",
                "evidence_shards",
                "dataset_coverage",
                "current_raw_evidence",
                "raw_evidence",
                "quarantine",
                "validation_summary",
                "tables",
            }
        ):
            raise FinancialCandidateError("FINANCIAL_FAMILY_MANIFEST_INVALID")
        return manifest

    @staticmethod
    def _manifest_evidence_shards(
        manifest: Mapping[str, object],
    ) -> tuple[FinancialDateShard, ...]:
        value = manifest.get("evidence_shards")
        if not isinstance(value, list):
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_SHARD_SET_INVALID")
        try:
            shards = tuple(_evidence_shard_from_descriptor(item) for item in value)
            if shards != (FinancialDateShard("complete-history"),):
                raise ValueError
        except (TypeError, ValueError) as error:
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_SHARD_SET_INVALID") from error
        return shards

    @staticmethod
    def _manifest_collection_contract(
        manifest: Mapping[str, object],
    ) -> FinancialCollectionContract:
        source_collection = manifest.get("source_collection")
        if not isinstance(source_collection, Mapping):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        try:
            return FinancialCollectionContract.from_descriptor(source_collection.get("contract"))
        except ValueError as error:
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID") from error

    def _descriptor(self, sha256: str, manifest: Mapping[str, object]) -> FinancialFamilyCandidate:
        coverage = manifest.get("dataset_coverage")
        summary = manifest.get("validation_summary")
        quarantine = manifest.get("quarantine")
        raw = manifest.get("raw_evidence")
        current_raw = manifest.get("current_raw_evidence")
        tables = manifest.get("tables")
        source_collection = manifest.get("source_collection")
        if (
            not all(
                isinstance(value, Mapping)
                for value in (coverage, summary, quarantine, raw, current_raw)
            )
            or not isinstance(tables, list)
            or not isinstance(source_collection, Mapping)
        ):
            raise FinancialCandidateError("FINANCIAL_FAMILY_MANIFEST_INVALID")
        assert isinstance(coverage, Mapping)
        assert isinstance(summary, Mapping)
        assert isinstance(quarantine, Mapping)
        assert isinstance(raw, Mapping)
        source_collection_keys = set(source_collection)
        if source_collection_keys not in (
            {"idempotency_key", "contract", "finished_at"},
            {
                "idempotency_key",
                "contract",
                "finished_at",
                "prior_candidate_manifest_sha256",
            },
        ):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        if (
            not isinstance(source_collection["idempotency_key"], str)
            or not source_collection["idempotency_key"].strip()
        ):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        self._manifest_collection_contract(manifest)
        _aware_iso(str(source_collection["finished_at"]))
        if "prior_candidate_manifest_sha256" in source_collection:
            _require_sha256(source_collection["prior_candidate_manifest_sha256"])
        if coverage.get("kind") == "financial-observation-range":
            if (
                coverage.get("reconciliation_status") != "complete"
                or coverage.get("revision_coverage")
                != "source-dated-and-first-observed-corrections"
            ):
                raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
            try:
                start = date.fromisoformat(str(coverage["start"])).isoformat()
                through = date.fromisoformat(
                    str(coverage["observation_through_session"])
                ).isoformat()
            except (KeyError, ValueError) as error:
                raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID") from error
            baseline = None
            complete = None
            readiness = "ready"
            pending_count = 0
            gap_count = 0
            earliest = None
            lineage = None
            reconciliation_status = "complete"
        else:
            normalized = _validated_discovery_coverage(coverage)
            start = str(normalized["start"])
            through = str(normalized["discovery_attempted_through_session"])
            baseline = str(normalized["discovery_baseline_session"])
            complete = str(normalized["discovery_complete_through_session"])
            readiness = str(normalized["readiness_status"])
            pending_count = int(normalized["pending_instrument_count"])
            gap_count = int(normalized["discovery_gap_count"])
            earliest_value = normalized["earliest_unresolved_date"]
            earliest = None if earliest_value is None else str(earliest_value)
            lineage = str(normalized["source_lineage_sha256"])
            reconciliation_status = "disclosure-checked"
        table_names = tuple(str(item.get("name")) for item in tables if isinstance(item, Mapping))
        if table_names != tuple(_ENDPOINT_TABLES.values()):
            raise FinancialCandidateError("FINANCIAL_TABLE_SET_INVALID")
        return FinancialFamilyCandidate(
            manifest_sha256=sha256,
            family_id=_FAMILY_ID,
            schema_contract=_SCHEMA_CONTRACT,
            coverage_start=start,
            observation_through_session=through,
            reconciliation_status=reconciliation_status,
            revision_coverage=str(coverage["revision_coverage"]),
            table_names=table_names,
            row_count=int(summary["row_count"]),
            quarantined_row_count=int(quarantine["row_count"]),
            raw_batch_count=int(raw["entry_count"]),
            discovery_baseline_session=baseline,
            discovery_complete_through_session=complete,
            readiness_status=readiness,
            pending_instrument_count=pending_count,
            discovery_gap_count=gap_count,
            earliest_unresolved_date=earliest,
            source_lineage_sha256=lineage,
        )

    def _manifest_bytes(self, value: object) -> bytes:
        content = canonical_json_bytes(value)
        if len(content) > GENERATION_MANIFEST_MAX_BYTES:
            raise FinancialCandidateError("FINANCIAL_MANIFEST_TOO_LARGE")
        return content

    def _read_json(
        self, path: Path, sha256: str, byte_count: int | None = None
    ) -> dict[str, object]:
        content = self._read(path, sha256, byte_count, GENERATION_MANIFEST_MAX_BYTES)
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FinancialCandidateError("FINANCIAL_MANIFEST_INVALID") from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != content:
            raise FinancialCandidateError("FINANCIAL_MANIFEST_INVALID")
        return value

    def _read(
        self,
        path: Path,
        sha256: str,
        byte_count: int | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        try:
            return self._files.read(
                path,
                sha256,
                expected_byte_count=byte_count,
                max_byte_count=max_bytes,
            )
        except (AddressedFileError, TypeError, ValueError) as error:
            raise FinancialCandidateError("FINANCIAL_ADDRESSED_FILE_INVALID") from error

    def _store(self, path: Path, sha256: str, content: bytes) -> None:
        try:
            self._files.store(path, sha256, content)
        except AddressedFileError as error:
            raise FinancialCandidateError("FINANCIAL_ADDRESSED_FILE_INVALID") from error

    def _manifest_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "manifests" / "sha256" / sha256[:2] / f"{sha256}.json"

    def _object_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "objects" / "sha256" / sha256[:2] / f"{sha256}.parquet"


def _stored_fact_digest(row: Mapping[str, object], projection_columns: set[str]) -> bytes:
    return hashlib.sha256(canonical_json_bytes({
        key: value for key, value in row.items() if key not in projection_columns
    })).digest()


def _table_contract(table_name: str, source_fields: tuple[str, ...]) -> ParquetWriterContract:
    schema = pa.schema(
        [pa.field(name, pa.string(), nullable=False) for name in _METADATA_FIELDS]
        + [pa.field(name, pa.string(), nullable=True) for name in source_fields]
    )
    return ParquetWriterContract(
        name=f"canonical-financial-{table_name}",
        version=1,
        schema=schema,
        sort_keys=(
            "effective_available_session",
            "instrument_id",
            "source_report_period",
            "source_report_type",
            "source_company_type",
            "source_end_type",
            "source_row_sha256",
        ),
    )


def _ttm_coverage_seeds(
    versions: Sequence[CanonicalFinancialVersion],
    coverage_start: str,
    endpoints: set[str],
) -> list[CanonicalFinancialVersion]:
    grouped: dict[tuple[str, str], list[CanonicalFinancialVersion]] = defaultdict(list)
    for version in versions:
        source = version.source()
        if (version.endpoint in endpoints and version.availability_status == "available"
                and source.get("report_type") == "1"
                and str(source.get("comp_type")) in {"1", "2", "3", "4"}
                and str(source["end_date"])[-4:] in {"0331", "0630", "0930", "1231"}):
            grouped[(version.endpoint, version.instrument_id)].append(version)
    seeds: list[CanonicalFinancialVersion] = []
    for group in grouped.values():
        before: dict[tuple[str, str], list[CanonicalFinancialVersion]] = defaultdict(list)
        targets: set[str] = set()
        for version in group:
            source = version.source()
            period = str(source["end_date"])
            if version.effective_available_session < coverage_start:
                before[(period, str(source["comp_type"]))].append(version)
            else:
                targets.add(period)
        if before:
            targets.add(max(period for period, _ in before))
        required = set(targets)
        for period in targets:
            if not period.endswith("1231"):
                previous_year = int(period[:4]) - 1
                required.update((f"{previous_year}1231", f"{previous_year}{period[4:]}"))
        for (period, _company_type), candidates in before.items():
            if period not in required:
                continue
            seeds.append(max(candidates, key=lambda item: (
                item.effective_available_session,
                str(item.source().get("update_flag") or "") == "1",
                item.source_published_date,
                _source_date(item.source().get("ann_date"), required=False),
                item.first_observed_at,
                item.source_row_sha256,
            )))
    return seeds


def _project_agreeing_financial_values(
    table: pa.Table, value_columns: tuple[str, ...], through_session: str, coverage_start: str,
) -> pa.Table:
    """Keep raw conflicts isolated; expose only fieldwise consensus in query output."""
    if not table.num_rows or not value_columns:
        return table
    conflicts = table.filter(pc.and_(
        pc.equal(table["availability_status"], "quarantined"),
        pc.not_equal(table["source_available_session"], ""),
    ))
    if not conflicts.num_rows:
        return table
    revision_keys = ["logical_revision_group_sha256", "source_published_date"]
    keys = [*revision_keys, "first_observed_at"]
    columns = [name for name in table.column_names if name not in keys]
    aggregates = [(name, "max" if name == "update_flag" else "min") for name in columns]
    aggregates += [(name, "count_distinct", pc.CountOptions(mode="all"))
                   for name in value_columns]
    aggregates.append(("source_row_sha256", "count"))
    consensus = conflicts.group_by(keys).aggregate(aggregates)
    consensus = consensus.rename_columns([
        name.removesuffix("_max").removesuffix("_min") + "_one"
        if name.endswith(("_min", "_max")) else name for name in consensus.column_names
    ])
    consensus = consensus.filter(pc.greater_equal(consensus["source_row_sha256_count"], 2))
    if not consensus.num_rows:
        return table
    earliest = table.group_by(revision_keys).aggregate([("first_observed_at", "min")])
    consensus = consensus.join(earliest, keys=revision_keys)
    correction = pc.greater(consensus["first_observed_at"], consensus["first_observed_at_min"])
    available = consensus["source_available_session_one"]
    observed = consensus["first_observed_session_one"]
    effective = pc.if_else(correction, pc.max_element_wise(available, observed), available)
    valid = pc.and_(pc.less_equal(effective, through_session),
                    pc.or_(pc.invert(correction), pc.not_equal(observed, "")))
    projected = {}
    for name in table.column_names:
        values = consensus[name if name in keys else name + "_one"]
        if name in value_columns:
            values = pc.if_else(pc.equal(consensus[name + "_count_distinct"], 1), values, None)
        elif name == "availability_status":
            values = pa.array(["available"] * consensus.num_rows)
        elif name == "effective_available_session":
            values = effective
        elif name == "revision_basis":
            values = pc.if_else(correction, "observed_correction", "source_version")
        elif name == "coverage_role":
            values = pc.if_else(pc.less(effective, coverage_start), "pre_start_seed", "in_coverage")
        projected[name] = values
    resolved = pa.table(projected, schema=table.schema).filter(valid)
    return pa.concat_tables((table, resolved))


def _compact_financial_history(table: pa.Table, start_session: str) -> pa.Table:
    """Keep one PIT seed per logical report plus every in-window version."""
    if table.num_rows == 0:
        return table
    before = table.filter(pc.less(table["effective_available_session"], start_session))
    within = table.filter(
        pc.greater_equal(table["effective_available_session"], start_session)
    )
    if before.num_rows == 0:
        return within
    before = before.append_column(
        "_update_order",
        pc.cast(
            pc.fill_null(pc.equal(before["update_flag"], "1"), False),
            pa.int8(),
        ),
    ).sort_by(
        [
            *((name, "ascending") for name in _FINANCIAL_HISTORY_IDENTITY_FIELDS),
            ("effective_available_session", "ascending"),
            ("_update_order", "ascending"),
            ("source_published_date", "ascending"),
            ("ann_date", "ascending"),
            ("first_observed_at", "ascending"),
            ("source_row_sha256", "ascending"),
        ]
    )
    if before.num_rows > 1:
        same_identity = pa.array([True] * (before.num_rows - 1))
        for name in _FINANCIAL_HISTORY_IDENTITY_FIELDS:
            same_identity = pc.and_kleene(
                same_identity,
                pc.equal(before[name].slice(0, before.num_rows - 1), before[name].slice(1)),
            )
        keep = pa.concat_arrays(
            [pc.invert(same_identity).combine_chunks(), pa.array([True])]
        )
        before = before.filter(keep)
    before = before.drop_columns(("_update_order",))
    return pa.concat_tables((before, within))


def _overlay_financial_rows(
    rows: Sequence[dict[str, object]],
    contract: ParquetWriterContract,
) -> list[dict[str, object]]:
    overlaid: dict[str, dict[str, object]] = {}
    for row in rows:
        source_row_sha256 = str(row["source_row_sha256"])
        _require_sha256(source_row_sha256)
        overlaid[source_row_sha256] = row
    return canonicalize_parquet_rows(overlaid.values(), contract)


def _overlay_financial_table(table: pa.Table, schema: pa.Schema) -> pa.Table:
    if table.num_rows == 0:
        return pa.Table.from_batches([], schema=schema)
    keys = table["source_row_sha256"]
    valid = pc.fill_null(pc.match_substring_regex(keys, "^[0-9a-f]{64}$"), False)
    if not pc.all(valid).as_py():
        raise FinancialCandidateError("FINANCIAL_SHA256_INVALID")
    positions = pa.table(
        {
            "source_row_sha256": keys,
            "_ordinal": pa.array(range(table.num_rows), type=pa.int64()),
        }
    )
    grouped = positions.group_by("source_row_sha256", use_threads=False).aggregate(
        [("_ordinal", "min"), ("_ordinal", "max")]
    )
    # Preserve first-key ordering and last-row precedence across immutable
    # objects without materializing each historical row as Python objects.
    ordered = grouped.sort_by([("_ordinal_min", "ascending")])
    return table.take(ordered["_ordinal_max"])


def _validate_contract(contract: FinancialCollectionContract) -> None:
    try:
        if FinancialCollectionContract.from_descriptor(contract.descriptor()) != contract:
            raise ValueError
    except ValueError as error:
        raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INVALID") from error


def _checkpoint_from_evidence(value: Mapping[str, object]) -> FinancialShardCheckpoint:
    if set(value) != {
        "ordinal",
        "endpoint",
        "instrument_id",
        "ts_code",
        "shard",
        "batch_sha256",
        "collected_at",
        "first_observed_at",
    }:
        raise FinancialCandidateError("FINANCIAL_EVIDENCE_ENTRY_INVALID")
    try:
        ordinal = int(value["ordinal"])
    except (TypeError, ValueError) as error:
        raise FinancialCandidateError("FINANCIAL_EVIDENCE_ENTRY_INVALID") from error
    if ordinal < 0:
        raise FinancialCandidateError("FINANCIAL_EVIDENCE_ENTRY_INVALID")
    endpoint = str(value["endpoint"])
    if endpoint not in FINANCIAL_ENDPOINTS:
        raise FinancialCandidateError("FINANCIAL_EVIDENCE_ENTRY_INVALID")
    for key in ("instrument_id", "ts_code", "shard"):
        if not isinstance(value[key], str) or not value[key]:
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_ENTRY_INVALID")
    _require_sha256(value["batch_sha256"])
    collected_at = _aware_iso(str(value["collected_at"]))
    first_observed_at = _aware_iso(str(value["first_observed_at"]))
    if first_observed_at > collected_at:
        raise FinancialCandidateError("FINANCIAL_EVIDENCE_ENTRY_INVALID")
    return FinancialShardCheckpoint(
        ordinal=ordinal,
        endpoint=endpoint,
        instrument_id=str(value["instrument_id"]),
        ts_code=str(value["ts_code"]),
        shard=str(value["shard"]),
        status="completed",
        batch_sha256=str(value["batch_sha256"]),
        collected_at=collected_at,
        first_observed_at=first_observed_at,
    )


def _compatible_collection_contracts(
    prior: FinancialCollectionContract,
    current: FinancialCollectionContract,
) -> bool:
    return prior.endpoint_fields == current.endpoint_fields


def _evidence_shard_descriptor(shard: FinancialDateShard) -> dict[str, str | None]:
    return {
        "name": shard.name,
        "start_date": shard.start_date,
        "end_date": shard.end_date,
    }


def _evidence_shard_from_descriptor(value: object) -> FinancialDateShard:
    if not isinstance(value, Mapping) or set(value) != {"name", "start_date", "end_date"}:
        raise ValueError("financial evidence shard descriptor is invalid")
    name = value["name"]
    start_date = value["start_date"]
    end_date = value["end_date"]
    if (
        not isinstance(name, str)
        or (start_date is not None and not isinstance(start_date, str))
        or (end_date is not None and not isinstance(end_date, str))
    ):
        raise ValueError("financial evidence shard descriptor is invalid")
    return FinancialDateShard(name=name, start_date=start_date, end_date=end_date)


def _merge_evidence_shards(
    shards: Sequence[FinancialDateShard],
) -> tuple[FinancialDateShard, ...]:
    complete = FinancialDateShard("complete-history")
    if not shards or any(shard != complete for shard in shards):
        raise FinancialCandidateError("FINANCIAL_EVIDENCE_SHARD_SET_INVALID")
    return (complete,)


def _merge_evidence_checkpoints(
    checkpoints: Sequence[FinancialShardCheckpoint],
) -> tuple[FinancialShardCheckpoint, ...]:
    exact: dict[tuple[str, str, str, str, str], FinancialShardCheckpoint] = {}
    for checkpoint in checkpoints:
        if checkpoint.batch_sha256 is None or checkpoint.first_observed_at is None:
            raise FinancialCandidateError("FINANCIAL_HISTORICAL_EVIDENCE_INVALID")
        key = (
            checkpoint.endpoint,
            checkpoint.instrument_id,
            checkpoint.shard,
            checkpoint.batch_sha256,
            _aware_iso(checkpoint.first_observed_at),
        )
        previous = exact.get(key)
        if previous is None or _aware_iso(checkpoint.collected_at) < _aware_iso(
            previous.collected_at
        ):
            exact[key] = checkpoint
    ordered = sorted(
        exact.values(),
        key=lambda item: (
            FINANCIAL_ENDPOINTS.index(item.endpoint),
            item.instrument_id,
            item.shard,
            _aware_iso(item.first_observed_at),
            str(item.batch_sha256),
        ),
    )
    return tuple(replace(item, ordinal=ordinal) for ordinal, item in enumerate(ordered))


def _merge_evidence_descriptors(
    entries: Sequence[Mapping[str, object]],
) -> tuple[tuple[object, ...], ...]:
    checkpoints = _merge_evidence_checkpoints(
        tuple(_checkpoint_from_evidence(entry) for entry in entries)
    )
    return tuple(
        (
            item.endpoint,
            item.instrument_id,
            item.ts_code,
            item.shard,
            item.batch_sha256,
            item.collected_at,
            item.first_observed_at,
        )
        for item in checkpoints
    )


def _validate_discovery_publication(value: FinancialDiscoveryPublication) -> None:
    try:
        baseline = date.fromisoformat(value.baseline_session).isoformat()
        attempted = date.fromisoformat(value.attempted_through_session).isoformat()
        complete = date.fromisoformat(value.complete_through_session).isoformat()
        earliest = (
            None
            if value.earliest_unresolved_date is None
            else date.fromisoformat(value.earliest_unresolved_date).isoformat()
        )
    except ValueError as error:
        raise FinancialCandidateError("FINANCIAL_DISCOVERY_COVERAGE_INVALID") from error
    if (
        baseline != value.baseline_session
        or attempted != value.attempted_through_session
        or complete != value.complete_through_session
        or complete < baseline
        or complete > attempted
        or len(value.source_lineage_sha256) != 64
        or any(character not in "0123456789abcdef" for character in value.source_lineage_sha256)
        or value.pending_instrument_count < 0
        or value.discovery_gap_count < 0
        or bool(value.pending_instrument_count or value.discovery_gap_count)
        != (earliest is not None)
        or (
            value.readiness_status == "ready"
            and (value.pending_instrument_count != 0 or value.discovery_gap_count != 0)
        )
        or (
            value.readiness_status == "ready_with_pending"
            and (value.pending_instrument_count == 0 or value.discovery_gap_count != 0)
        )
        or (
            value.readiness_status == "ready_with_gaps"
            and value.discovery_gap_count == 0
        )
    ):
        raise FinancialCandidateError("FINANCIAL_DISCOVERY_COVERAGE_INVALID")


def _discovery_coverage(
    coverage_start: str,
    discovery: FinancialDiscoveryPublication,
) -> dict[str, object]:
    _validate_discovery_publication(discovery)
    return {
        "kind": "financial-disclosure-observation-range",
        "start": coverage_start,
        "discovery_baseline_session": discovery.baseline_session,
        "discovery_attempted_through_session": discovery.attempted_through_session,
        "discovery_complete_through_session": discovery.complete_through_session,
        "historical_reconciliation_watermark": discovery.baseline_session,
        "revision_coverage": "tushare-disclosure-periods-with-rotating-reconciliation",
        "seed_policy": "annual-stock-and-ttm-dependency-seeds",
        "readiness_status": discovery.readiness_status,
        "pending_instrument_count": discovery.pending_instrument_count,
        "discovery_gap_count": discovery.discovery_gap_count,
        "earliest_unresolved_date": discovery.earliest_unresolved_date,
        "source_lineage_sha256": discovery.source_lineage_sha256,
    }


def _validated_discovery_coverage(coverage: Mapping[str, object]) -> dict[str, object]:
    expected_keys = {
        "kind",
        "start",
        "discovery_baseline_session",
        "discovery_attempted_through_session",
        "discovery_complete_through_session",
        "historical_reconciliation_watermark",
        "revision_coverage",
        "seed_policy",
        "readiness_status",
        "pending_instrument_count",
        "discovery_gap_count",
        "earliest_unresolved_date",
        "source_lineage_sha256",
    }
    if set(coverage) != expected_keys:
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
    try:
        publication = FinancialDiscoveryPublication(
            baseline_session=date.fromisoformat(
                str(coverage["discovery_baseline_session"])
            ).isoformat(),
            attempted_through_session=date.fromisoformat(
                str(coverage["discovery_attempted_through_session"])
            ).isoformat(),
            complete_through_session=date.fromisoformat(
                str(coverage["discovery_complete_through_session"])
            ).isoformat(),
            source_lineage_sha256=str(coverage["source_lineage_sha256"]),
            readiness_status=str(coverage["readiness_status"]),  # type: ignore[arg-type]
            pending_instrument_count=int(coverage["pending_instrument_count"]),
            discovery_gap_count=int(coverage["discovery_gap_count"]),
            earliest_unresolved_date=(
                None
                if coverage["earliest_unresolved_date"] is None
                else date.fromisoformat(str(coverage["earliest_unresolved_date"])).isoformat()
            ),
        )
        start = date.fromisoformat(str(coverage["start"])).isoformat()
        _validate_discovery_publication(publication)
    except (KeyError, TypeError, ValueError) as error:
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID") from error
    seed_policy = coverage["seed_policy"]
    if not isinstance(seed_policy, str) or not seed_policy.strip():
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
    normalized = _discovery_coverage(start, publication)
    if coverage["kind"] == "financial-announcement-observation-range":
        # Archived source provenance stays immutable when reopening an accepted Generation.
        normalized["kind"] = "financial-announcement-observation-range"
        normalized["revision_coverage"] = "cninfo-announcement-driven-tushare-observed"
    # Seed provenance describes the stored facts, not the currently active writer.
    # Field admission still uses the candidate's own declared projection contract.
    normalized["seed_policy"] = seed_policy
    if coverage.get("historical_reconciliation_watermark") != publication.baseline_session:
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
    if normalized != dict(coverage):
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
    return normalized


def _coverage_baseline(manifest: Mapping[str, object]) -> str:
    coverage = manifest.get("dataset_coverage")
    if not isinstance(coverage, Mapping):
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
    value = (
        coverage.get("discovery_baseline_session")
        if coverage.get("kind") in DISCOVERY_COVERAGE_KINDS
        else coverage.get("historical_reconciliation_watermark")
    )
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID") from error


def _coverage_complete_through(manifest: Mapping[str, object]) -> str:
    coverage = manifest.get("dataset_coverage")
    if not isinstance(coverage, Mapping):
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
    value = (
        coverage.get("discovery_complete_through_session")
        if coverage.get("kind") in DISCOVERY_COVERAGE_KINDS
        else coverage.get("observation_through_session")
    )
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID") from error


def _statement_report_inventory(rows, through):
    return {
        (row["instrument_id"], _iso_date(row["source_report_period"]))
        for row in rows
        if row["availability_status"] in {"available", "pending_calendar", "outside_calendar"}
        and row["source_report_type"] == "1"
        and row["source_report_period"] <= row["source_published_date"] <= through.replace("-", "")
    }


def _version_row(
    version: CanonicalFinancialVersion,
    source_fields: tuple[str, ...],
) -> dict[str, object]:
    source = version.source()
    return {
        "instrument_id": version.instrument_id,
        "source_endpoint": version.endpoint,
        "source_report_period": str(source.get("end_date") or ""),
        "source_report_type": str(source.get("report_type") or ""),
        "source_company_type": str(source.get("comp_type") or ""),
        "source_end_type": str(source.get("end_type") or ""),
        "source_published_date": version.source_published_date,
        "first_observed_at": version.first_observed_at,
        "first_observed_session": version.first_observed_session,
        "source_available_session": version.source_available_session,
        "effective_available_session": version.effective_available_session,
        "availability_status": version.availability_status,
        "revision_basis": version.revision_basis,
        "coverage_role": version.coverage_role,
        "logical_revision_group_sha256": version.logical_revision_group_sha256,
        "source_row_sha256": version.source_row_sha256,
        "source_batch_sha256": version.raw_batch_sha256,
        **{field: source[field] for field in source_fields},
    }


def _partition_financial_rows(
    rows: Sequence[dict[str, object]], sessions: Sequence[str]
) -> list[list[dict[str, object]]]:
    session_index = {session: index for index, session in enumerate(sessions)}
    partitioned: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        session = str(row["effective_available_session"])
        if not session:
            partitioned[-1].append(row)
            continue
        if session not in session_index:
            raise FinancialCandidateError("FINANCIAL_VERSION_OUTSIDE_CALENDAR")
        partitioned[session_index[session] // GENERATION_SESSION_PARTITION_COUNT].append(row)
    partitions: list[list[dict[str, object]]] = []
    for partition in sorted(partitioned):
        group = partitioned[partition]
        partitions.extend(
            group[offset : offset + GENERATION_ROW_PARTITION_COUNT]
            for offset in range(0, len(group), GENERATION_ROW_PARTITION_COUNT)
        )
    return partitions


def _iter_partitioned_financial_rows(
    rows: Iterator[dict[str, object]] | Sequence[dict[str, object]],
    sessions: Sequence[str],
) -> Iterator[list[dict[str, object]]]:
    session_index = {session: index for index, session in enumerate(sessions)}
    current_partition: int | None = None
    group: list[dict[str, object]] = []
    for row in rows:
        session = str(row["effective_available_session"])
        if session:
            if session not in session_index:
                raise FinancialCandidateError("FINANCIAL_VERSION_OUTSIDE_CALENDAR")
            partition = session_index[session] // GENERATION_SESSION_PARTITION_COUNT
        else:
            partition = -1
        if group and (
            partition != current_partition
            or len(group) == GENERATION_ROW_PARTITION_COUNT
        ):
            yield group
            group = []
        current_partition = partition
        group.append(row)
    if group:
        yield group


def _source_scalar(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    raise FinancialCandidateError("FINANCIAL_SOURCE_VALUE_INVALID")


def _source_publication_date(source: Mapping[str, object]) -> str:
    final = _source_date(source.get("f_ann_date"), required=False)
    announcement = _source_date(source.get("ann_date"), required=False)
    return final or announcement


def _source_date(value: object, *, required: bool) -> str:
    if value is None or value == "":
        if required:
            raise FinancialCandidateError("FINANCIAL_REPORT_PERIOD_INVALID")
        return ""
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise FinancialCandidateError("FINANCIAL_SOURCE_DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise FinancialCandidateError("FINANCIAL_SOURCE_DATE_INVALID") from error
    return value


def _iso_date(value: str) -> str:
    return datetime.strptime(value, "%Y%m%d").date().isoformat()


def _aware_iso(value: str | None) -> str:
    if value is None:
        raise FinancialCandidateError("FINANCIAL_OBSERVATION_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise FinancialCandidateError("FINANCIAL_OBSERVATION_TIME_INVALID") from error
    if parsed.tzinfo is None:
        raise FinancialCandidateError("FINANCIAL_OBSERVATION_TIME_INVALID")
    return parsed.astimezone(UTC).isoformat()


def _market_date(value: str | None) -> str:
    normalized = _aware_iso(value)
    market_time = datetime.fromisoformat(normalized).astimezone(ZoneInfo("Asia/Shanghai"))
    return market_time.date().isoformat()


def _next_session(sessions: Sequence[str], after_date: str) -> str:
    index = bisect.bisect_right(sessions, after_date)
    return "" if index == len(sessions) else sessions[index]


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FinancialCandidateError("FINANCIAL_SHA256_INVALID")


__all__ = (
    "FinancialCandidateError",
    "FinancialCandidateStore",
    "FinancialDiscoveryPublication",
    "FinancialFamilyCandidate",
)

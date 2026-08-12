from __future__ import annotations

import bisect
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    FINANCIAL_HISTORY_FLOOR,
    FINANCIAL_SOURCE_CONTRACT_VERSION,
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialCollectionError,
    FinancialDateShard,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_schema import (
    GENERATION_MANIFEST_MAX_BYTES,
    GENERATION_OBJECT_MAX_BYTES,
    GENERATION_ROW_PARTITION_COUNT,
    GENERATION_SESSION_PARTITION_COUNT,
)
from thesistrace.data.generation_store import GenerationStoreError, MountedGenerationStore
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
            for version in ordered:
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
            prior_candidate_manifest_sha256=None,
        )

    def rebuild(
        self,
        collection: CompletedFinancialCollection,
        *,
        prior_candidate_manifest_sha256: str,
        observation_through_session: str,
    ) -> FinancialFamilyCandidate:
        prior = self.validate(prior_candidate_manifest_sha256)
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
        prior_entries = self._read_evidence_index(prior_manifest["raw_evidence"])
        prior_checkpoints = tuple(_checkpoint_from_evidence(item) for item in prior_entries)
        historical = {item.instrument_id: item.ts_code for item in current_lifecycles}
        self._validate_historical_identities(prior_checkpoints, historical)
        historical_checkpoints = _merge_evidence_checkpoints(
            (*prior_checkpoints, *collection.shards)
        )
        if (
            observation_through_session == prior.observation_through_session
            and historical_checkpoints == prior_checkpoints
        ):
            return prior
        return self._materialize(
            collection,
            observation_through_session=observation_through_session,
            prior_checkpoints=prior_checkpoints,
            prior_candidate_manifest_sha256=prior_candidate_manifest_sha256,
        )

    def preflight_rebuild(
        self,
        *,
        prior_candidate_manifest_sha256: str,
        generation_manifest_sha256: str,
        contract: FinancialCollectionContract,
        observation_through_session: str,
    ) -> None:
        prior = self.validate(prior_candidate_manifest_sha256)
        if prior.observation_through_session > observation_through_session:
            raise FinancialCandidateError("FINANCIAL_REFRESH_CUTOFF_REGRESSION")
        prior_manifest = self._read_family(prior_candidate_manifest_sha256)
        prior_contract = self._manifest_collection_contract(prior_manifest)
        if not _compatible_collection_contracts(prior_contract, contract):
            raise FinancialCandidateError("FINANCIAL_REFRESH_CONTRACT_MISMATCH")
        _validate_contract_coverage(contract, observation_through_session)
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
        prior_checkpoints = tuple(_checkpoint_from_evidence(item) for item in prior_entries)
        historical = {item.instrument_id: item.ts_code for item in current_lifecycles}
        self._validate_historical_identities(prior_checkpoints, historical)

    def _materialize(
        self,
        collection: CompletedFinancialCollection,
        *,
        observation_through_session: str,
        prior_checkpoints: Sequence[FinancialShardCheckpoint],
        prior_candidate_manifest_sha256: str | None,
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
        _validate_contract_coverage(collection.contract, observation_through_session)
        lifecycles = self._market.read_historical_ordinary_a_share_lifecycles(
            collection.generation_manifest_sha256
        )
        current_evidence, endpoint_fields = self._validated_evidence(
            collection,
            {item.instrument_id: item.ts_code for item in lifecycles},
        )
        historical_evidence = [
            *(
                (checkpoint, self._read_raw_batch(str(checkpoint.batch_sha256)))
                for checkpoint in prior_checkpoints
            ),
            *current_evidence,
        ]
        historical_checkpoints = _merge_evidence_checkpoints(
            (*prior_checkpoints, *collection.shards)
        )
        versions, quarantine = self._canonical_versions(
            historical_evidence,
            endpoint_fields,
            sessions,
        )
        in_scope_at_start = {
            item.instrument_id
            for item in lifecycles
            if item.listed_from <= coverage_start
            and (not item.listed_to or item.listed_to >= coverage_start)
        }
        retained = self._retain_coverage_versions(
            versions,
            coverage_start,
            in_scope_at_start,
        )
        table_references: list[dict[str, object]] = []
        for endpoint in FINANCIAL_ENDPOINTS:
            table_references.append(
                self._materialize_table(
                    endpoint,
                    endpoint_fields[endpoint],
                    retained[endpoint],
                    sessions,
                )
            )
        current_evidence_reference = self._materialize_evidence_index(collection.shards)
        evidence_reference = self._materialize_evidence_index(historical_checkpoints)
        coverage = {
            "kind": "financial-observation-range",
            "start": coverage_start,
            "observation_through_session": observation_through_session,
            "expected_instrument_count": len({item.instrument_id for item in collection.shards}),
            "expected_shard_count": collection.target_count,
            "completed_shard_count": collection.target_count,
            "reconciliation_status": "complete",
            "historical_reconciliation_watermark": observation_through_session,
            "revision_coverage": "source-dated-and-first-observed-corrections",
            "seed_policy": "latest-pre-start-annual-flow-and-balance-facts",
        }
        family = {
            "format": _FAMILY_FORMAT,
            "version": _VERSION,
            "family_id": _FAMILY_ID,
            "schema_contract": _SCHEMA_CONTRACT,
            "source_generation_manifest_sha256": collection.generation_manifest_sha256,
            "prior_candidate_manifest_sha256": prior_candidate_manifest_sha256,
            "source_collection": {
                "idempotency_key": collection.idempotency_key,
                "contract": collection.contract.descriptor(),
                "finished_at": collection.finished_at,
            },
            "dataset_coverage": coverage,
            "current_raw_evidence": current_evidence_reference,
            "raw_evidence": evidence_reference,
            "quarantine": {
                "row_count": len(quarantine),
                "rows_sha256": _sha(sorted(item.source_row_sha256 for item in quarantine)),
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

    def validate(self, manifest_sha256: str) -> FinancialFamilyCandidate:
        manifest = self._read_family(manifest_sha256)
        descriptor = self._descriptor(manifest_sha256, manifest)
        evidence = self._read_evidence_index(manifest["raw_evidence"])
        current_evidence = self._read_evidence_index(manifest["current_raw_evidence"])
        if len(evidence) != descriptor.raw_batch_count:
            raise FinancialCandidateError("FINANCIAL_EVIDENCE_COUNT_INVALID")
        contract = self._manifest_collection_contract(manifest)
        prior_sha256 = manifest.get("prior_candidate_manifest_sha256")
        if prior_sha256 is not None:
            _require_sha256(prior_sha256)
            prior = self.validate(str(prior_sha256))
            prior_manifest = self._read_family(str(prior_sha256))
            prior_contract = self._manifest_collection_contract(prior_manifest)
            if (
                prior.observation_through_session > descriptor.observation_through_session
                or not _compatible_collection_contracts(prior_contract, contract)
            ):
                raise FinancialCandidateError("FINANCIAL_REFRESH_PROVENANCE_INVALID")
            prior_evidence = self._read_evidence_index(prior_manifest["raw_evidence"])
        else:
            prior_evidence = []
        expected_union = _merge_evidence_descriptors((*prior_evidence, *current_evidence))
        if _merge_evidence_descriptors(evidence) != expected_union:
            raise FinancialCandidateError("FINANCIAL_REFRESH_EVIDENCE_UNION_INVALID")
        _validate_contract_coverage(contract, descriptor.observation_through_session)
        current_fields = self._validate_evidence_entries(current_evidence, contract=contract)
        endpoint_fields = current_fields
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
        self._validate_target_set(current_checkpoints, historical, contract)
        self._validate_historical_identities(checkpoints, historical)
        current_source_evidence = [
            (checkpoint, self._read_raw_batch(str(checkpoint.batch_sha256)))
            for checkpoint in current_checkpoints
        ]
        prior_source_evidence = [
            (
                _checkpoint_from_evidence(item),
                self._read_raw_batch(str(item["batch_sha256"])),
            )
            for item in prior_evidence
        ]
        source_evidence = [*prior_source_evidence, *current_source_evidence]
        versions, quarantine = self._canonical_versions(
            source_evidence,
            endpoint_fields,
            sessions,
        )
        in_scope_at_start = {
            item.instrument_id
            for item in lifecycles
            if item.listed_from <= descriptor.coverage_start
            and (not item.listed_to or item.listed_to >= descriptor.coverage_start)
        }
        retained = self._retain_coverage_versions(
            versions,
            descriptor.coverage_start,
            in_scope_at_start,
        )
        tables = manifest["tables"]
        assert isinstance(tables, list)
        rows_by_endpoint: dict[str, list[dict[str, object]]] = {}
        for reference in tables:
            if not isinstance(reference, Mapping):
                raise FinancialCandidateError("FINANCIAL_TABLE_REFERENCE_INVALID")
            endpoint = _TABLE_ENDPOINTS.get(str(reference.get("name")))
            if endpoint is None:
                raise FinancialCandidateError("FINANCIAL_TABLE_REFERENCE_INVALID")
            rows_by_endpoint[endpoint] = self._open_table(
                endpoint, endpoint_fields[endpoint], reference, sessions
            )
            expected_rows = canonicalize_parquet_rows(
                [_version_row(item, endpoint_fields[endpoint]) for item in retained[endpoint]],
                _table_contract(_ENDPOINT_TABLES[endpoint], endpoint_fields[endpoint]),
            )
            if rows_by_endpoint[endpoint] != expected_rows:
                raise FinancialCandidateError("FINANCIAL_CANONICAL_PROJECTION_INVALID")
        if tuple(rows_by_endpoint) != FINANCIAL_ENDPOINTS:
            raise FinancialCandidateError("FINANCIAL_TABLE_SET_INVALID")
        summary = manifest["validation_summary"]
        if not isinstance(summary, Mapping) or summary != {
            "status": "validated",
            "table_count": 3,
            "row_count": sum(len(rows) for rows in rows_by_endpoint.values()),
            "object_count": sum(int(item["object_count"]) for item in tables),
            "raw_batch_count": len(evidence),
        }:
            raise FinancialCandidateError("FINANCIAL_VALIDATION_SUMMARY_INVALID")
        coverage = manifest["dataset_coverage"]
        assert isinstance(coverage, Mapping)
        if coverage != {
            "kind": "financial-observation-range",
            "start": descriptor.coverage_start,
            "observation_through_session": descriptor.observation_through_session,
            "expected_instrument_count": len(historical),
            "expected_shard_count": len(current_evidence),
            "completed_shard_count": len(current_evidence),
            "reconciliation_status": "complete",
            "historical_reconciliation_watermark": descriptor.observation_through_session,
            "revision_coverage": "source-dated-and-first-observed-corrections",
            "seed_policy": "latest-pre-start-annual-flow-and-balance-facts",
        }:
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        quarantine_manifest = manifest["quarantine"]
        if not isinstance(quarantine_manifest, Mapping) or quarantine_manifest != {
            "row_count": len(quarantine),
            "rows_sha256": _sha(sorted(item.source_row_sha256 for item in quarantine)),
        }:
            raise FinancialCandidateError("FINANCIAL_QUARANTINE_INVALID")
        return descriptor

    def read_table(self, manifest_sha256: str, table_name: str) -> tuple[dict[str, object], ...]:
        manifest = self._read_family(manifest_sha256)
        evidence = self._read_evidence_index(manifest["current_raw_evidence"])
        contract = self._manifest_collection_contract(manifest)
        fields = self._validate_evidence_entries(
            evidence,
            contract=contract,
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
        rows: list[dict[str, object]] = []
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
                table = pq.read_table(pa.BufferReader(content), columns=list(source_columns))
            except (ArrowException, TypeError, ValueError) as error:
                raise FinancialCandidateError("FINANCIAL_OBJECT_INVALID") from error
            if table.schema != expected_schema or table.num_rows != object_ref.get("row_count"):
                raise FinancialCandidateError("FINANCIAL_OBJECT_SCHEMA_INVALID")
            rows.extend(
                row
                for row in table.to_pylist()
                if str(row["instrument_id"]) in instrument_ids
                and str(row["effective_available_session"]) <= through_session
            )
        return tuple(rows)

    def quarantined_row_count(self, manifest_sha256: str) -> int:
        manifest = self._read_family(manifest_sha256)
        quarantine = manifest["quarantine"]
        if not isinstance(quarantine, Mapping):
            raise FinancialCandidateError("FINANCIAL_QUARANTINE_INVALID")
        return int(quarantine["row_count"])

    def _validated_market_sessions(self, manifest_sha256: str, through: str) -> list[str]:
        try:
            descriptor = self._market.validate_generation(manifest_sha256)
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
    ) -> tuple[
        list[tuple[FinancialShardCheckpoint, dict[str, object]]], dict[str, tuple[str, ...]]
    ]:
        if (
            collection.target_count < 3
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
        if instruments != set(historical):
            raise FinancialCandidateError("FINANCIAL_COLLECTION_TARGET_SET_INVALID")
        self._validate_target_set(collection.shards, historical, collection.contract)
        evidence: list[tuple[FinancialShardCheckpoint, dict[str, object]]] = []
        for checkpoint in collection.shards:
            assert checkpoint.batch_sha256 is not None
            try:
                batch = self._read_raw_batch(checkpoint.batch_sha256)
            except (FinancialCollectionError, AddressedFileError) as error:
                raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID") from error
            evidence.append((checkpoint, batch))
        fields = self._validate_evidence_entries(
            [self._evidence_descriptor(checkpoint) for checkpoint, _batch in evidence],
            loaded_batches={checkpoint.batch_sha256: batch for checkpoint, batch in evidence},
            contract=collection.contract,
        )
        return evidence, fields

    @staticmethod
    def _validate_target_set(
        checkpoints: Sequence[FinancialShardCheckpoint],
        historical: Mapping[str, str],
        contract: FinancialCollectionContract,
    ) -> None:
        expected = {
            (endpoint, instrument, shard.name)
            for endpoint in FINANCIAL_ENDPOINTS
            for instrument in historical
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
            fields = self._validate_raw_batch(batch, entry, contract)
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
            if identity in seen:
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
        shard = next(
            (item for item in contract.shards if item.name == entry.get("shard")),
            None,
        )
        if shard is None or dict(parameters) != {
            "ts_code": entry.get("ts_code"),
            **shard.parameters(),
        }:
            raise FinancialCandidateError("FINANCIAL_SHARD_PARAMETERS_INVALID")
        truncation_boundary = dict(contract.suspected_truncation_row_counts).get(
            str(entry.get("endpoint"))
        )
        if truncation_boundary is not None and len(items) >= truncation_boundary:
            raise FinancialCandidateError("FINANCIAL_SUSPECTED_TRUNCATION")
        start = parameters.get("start_date")
        end = parameters.get("end_date")
        if (start is None) != (end is None):
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
        if start is not None and (
            _source_date(start, required=True) > _source_date(end, required=True)
            or any(not (str(start) <= value <= str(end)) for value in publications)
        ):
            raise FinancialCandidateError("FINANCIAL_RAW_BATCH_INVALID")
        return tuple(fields_value)

    def _canonical_versions(
        self,
        evidence: Sequence[tuple[FinancialShardCheckpoint, dict[str, object]]],
        endpoint_fields: Mapping[str, tuple[str, ...]],
        sessions: list[str],
    ) -> tuple[list[CanonicalFinancialVersion], list[CanonicalFinancialVersion]]:
        observations: list[FinancialSourceObservation] = []
        for checkpoint, batch in evidence:
            fields = endpoint_fields[checkpoint.endpoint]
            for item in batch["items"]:
                assert isinstance(item, list)
                observations.append(
                    FinancialSourceObservation(
                        endpoint=checkpoint.endpoint,
                        instrument_id=checkpoint.instrument_id,
                        ts_code=checkpoint.ts_code,
                        source_fields=fields,
                        source_values=tuple(item),
                        first_observed_at=_aware_iso(checkpoint.first_observed_at),
                        raw_batch_sha256=str(checkpoint.batch_sha256),
                    )
                )
        canonical = list(FinancialVersionProjector().project(observations, sessions))
        quarantine = [
            version for version in canonical if version.availability_status == "quarantined"
        ]
        return canonical, quarantine

    def _retain_coverage_versions(
        self,
        versions: Sequence[CanonicalFinancialVersion],
        coverage_start: str,
        in_scope_at_start: set[str],
    ) -> dict[str, list[CanonicalFinancialVersion]]:
        retained: dict[str, list[CanonicalFinancialVersion]] = {
            endpoint: [] for endpoint in FINANCIAL_ENDPOINTS
        }
        seed_candidates: dict[tuple[str, str], list[CanonicalFinancialVersion]] = defaultdict(list)
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
            if version.endpoint != "balancesheet" and not report_period.endswith("1231"):
                continue
            seed_candidates[(version.endpoint, version.instrument_id)].append(version)
        for candidates in seed_candidates.values():
            latest = max(
                candidates,
                key=lambda item: (
                    str(item.source()["end_date"]),
                    item.effective_available_session,
                    str(item.source().get("update_flag") or ""),
                    item.source_row_sha256,
                ),
            )
            retained[latest.endpoint].append(replace(latest, coverage_role="pre_start_seed"))
        return retained

    def _materialize_table(
        self,
        endpoint: str,
        source_fields: tuple[str, ...],
        versions: Sequence[CanonicalFinancialVersion],
        sessions: list[str],
    ) -> dict[str, object]:
        table_name = _ENDPOINT_TABLES[endpoint]
        contract = _table_contract(table_name, source_fields)
        rows = canonicalize_parquet_rows(
            [_version_row(version, source_fields) for version in versions], contract
        )
        objects: list[dict[str, object]] = []
        for group in _partition_financial_rows(rows, sessions):
            objects.append(self._materialize_object(contract, group, len(objects)))
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
            "row_count": len(rows),
            "objects": objects,
        }
        content = self._manifest_bytes(manifest)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store(self._manifest_path(sha256), sha256, content)
        return {
            "name": table_name,
            "manifest_sha256": sha256,
            "manifest_byte_count": len(content),
            "row_count": len(rows),
            "object_count": len(objects),
        }

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
        manifest_sha256 = str(reference.get("manifest_sha256"))
        manifest = self._read_json(
            self._manifest_path(manifest_sha256),
            manifest_sha256,
            int(reference.get("manifest_byte_count", -1)),
        )
        table_name = _ENDPOINT_TABLES[endpoint]
        contract = _table_contract(table_name, source_fields)
        if (
            manifest.get("format") != _TABLE_FORMAT
            or manifest.get("version") != _VERSION
            or manifest.get("table") != table_name
            or manifest.get("source_endpoint") != endpoint
            or manifest.get("source_fields") != list(source_fields)
            or manifest.get("writer_contract") != contract.descriptor()
            or manifest.get("partitioning")
            != {
                "kind": "research-session-block-with-row-cap",
                "session_count": GENERATION_SESSION_PARTITION_COUNT,
                "row_count": GENERATION_ROW_PARTITION_COUNT,
            }
        ):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        objects = manifest.get("objects")
        if not isinstance(objects, list):
            raise FinancialCandidateError("FINANCIAL_TABLE_MANIFEST_INVALID")
        rows: list[dict[str, object]] = []
        partitions: list[list[dict[str, object]]] = []
        for ordinal, object_ref in enumerate(objects):
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
            rows.extend(partition)
            partitions.append(partition)
        if rows != canonicalize_parquet_rows(rows, contract):
            raise FinancialCandidateError("FINANCIAL_TABLE_ORDER_INVALID")
        if manifest.get("row_count") != len(rows) or reference.get("row_count") != len(rows):
            raise FinancialCandidateError("FINANCIAL_TABLE_ROW_COUNT_INVALID")
        if reference.get("object_count") != len(objects):
            raise FinancialCandidateError("FINANCIAL_TABLE_OBJECT_COUNT_INVALID")
        if partitions != _partition_financial_rows(rows, sessions):
            raise FinancialCandidateError("FINANCIAL_TABLE_PARTITIONING_INVALID")
        return rows

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
        ):
            raise FinancialCandidateError("FINANCIAL_FAMILY_MANIFEST_INVALID")
        return manifest

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
            or (
                manifest.get("prior_candidate_manifest_sha256") is not None
                and not isinstance(manifest.get("prior_candidate_manifest_sha256"), str)
            )
        ):
            raise FinancialCandidateError("FINANCIAL_FAMILY_MANIFEST_INVALID")
        assert isinstance(coverage, Mapping)
        assert isinstance(summary, Mapping)
        assert isinstance(quarantine, Mapping)
        assert isinstance(raw, Mapping)
        if set(source_collection) != {"idempotency_key", "contract", "finished_at"}:
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        if (
            not isinstance(source_collection["idempotency_key"], str)
            or not source_collection["idempotency_key"].strip()
        ):
            raise FinancialCandidateError("FINANCIAL_SOURCE_COLLECTION_INVALID")
        self._manifest_collection_contract(manifest)
        _aware_iso(str(source_collection["finished_at"]))
        if (
            coverage.get("kind") != "financial-observation-range"
            or coverage.get("reconciliation_status") != "complete"
            or coverage.get("revision_coverage") != "source-dated-and-first-observed-corrections"
        ):
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID")
        try:
            start = date.fromisoformat(str(coverage["start"])).isoformat()
            through = date.fromisoformat(str(coverage["observation_through_session"])).isoformat()
        except (KeyError, ValueError) as error:
            raise FinancialCandidateError("FINANCIAL_COVERAGE_INVALID") from error
        table_names = tuple(str(item.get("name")) for item in tables if isinstance(item, Mapping))
        if table_names != tuple(_ENDPOINT_TABLES.values()):
            raise FinancialCandidateError("FINANCIAL_TABLE_SET_INVALID")
        return FinancialFamilyCandidate(
            manifest_sha256=sha256,
            family_id=_FAMILY_ID,
            schema_contract=_SCHEMA_CONTRACT,
            coverage_start=start,
            observation_through_session=through,
            reconciliation_status="complete",
            revision_coverage=str(coverage["revision_coverage"]),
            table_names=table_names,
            row_count=int(summary["row_count"]),
            quarantined_row_count=int(quarantine["row_count"]),
            raw_batch_count=int(raw["entry_count"]),
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


def _validate_contract_coverage(
    contract: FinancialCollectionContract,
    observation_through_session: str,
) -> None:
    try:
        if FinancialCollectionContract.from_descriptor(contract.descriptor()) != contract:
            raise ValueError
    except ValueError as error:
        raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INVALID") from error
    bounded = [shard for shard in contract.shards if shard.start_date is not None]
    if not bounded:
        if contract.shards != (FinancialDateShard("complete-history"),):
            raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INVALID")
        return
    if len(bounded) != len(contract.shards):
        raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INVALID")
    ordered = sorted(bounded, key=lambda shard: str(shard.start_date))
    if ordered[0].start_date != FINANCIAL_HISTORY_FLOOR:
        raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INVALID")
    if any(
        (
            datetime.strptime(str(shard.end_date), "%Y%m%d").date()
            - datetime.strptime(str(shard.start_date), "%Y%m%d").date()
        ).days
        > 365
        for shard in ordered
    ):
        raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INVALID")
    for previous, current in zip(ordered, ordered[1:], strict=False):
        previous_end = datetime.strptime(str(previous.end_date), "%Y%m%d").date()
        current_start = datetime.strptime(str(current.start_date), "%Y%m%d").date()
        if current_start != previous_end + timedelta(days=1):
            raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INVALID")
    through = date.fromisoformat(observation_through_session).strftime("%Y%m%d")
    if str(ordered[-1].end_date) < through:
        raise FinancialCandidateError("FINANCIAL_SHARD_CONTRACT_INCOMPLETE")


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
    "FinancialFamilyCandidate",
)

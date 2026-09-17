from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from sys import intern

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.data.daily_basic_evidence import (
    MARKET_SOURCE_RECEIPT_DIRECTORY,
    DailyBasicCheckpoint,
    daily_basic_evidence_path,
)
from thesistrace.data.fields import field_definitions
from thesistrace.data.generation_family import (
    CORE_MARKET_FAMILY_SPECS,
    DAILY_BASIC_FAMILY_SPEC,
    INDUSTRY_FAMILY_SPEC,
    NON_FINANCIAL_FAMILY_SPECS,
    FamilyManifestError,
    MountedDatasetFamilyDescriptor,
    MountedFamilyGenerationDescriptor,
    build_family_coverage,
    get_family_spec,
    ordered_non_financial_specs,
    validate_family_coverage,
    validate_generation_coverages,
    validate_preparation,
    validate_summary,
    validation_summary,
)
from thesistrace.data.generation_family import (
    DatasetFamilySpec as _DatasetFamilySpec,
)
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_schema import (
    GENERATION_MANIFEST_MAX_BYTES,
    GENERATION_OBJECT_MAX_BYTES,
    GENERATION_ROW_PARTITION_COUNT,
    GENERATION_SESSION_PARTITION_COUNT,
    MARKET_CANDIDATE_TABLE_SPECS,
)
from thesistrace.data.generation_schema import (
    TABLE_SPECS as _TABLE_SPECS,
)
from thesistrace.data.generation_schema import (
    TableSpec as _TableSpec,
)
from thesistrace.data.generation_validation import (
    UNIVERSE_NAMES,
    GenerationValidationError,
    validate_canonical_generation,
)
from thesistrace.data.io_metrics import record_parquet_scan
from thesistrace.data.market_series import (
    MarketSeriesError,
    align_market_research_data,
    market_field_column_bindings,
    market_field_columns,
)
from thesistrace.data.source import (
    CanonicalBootstrapStream,
    CanonicalColumnarSessionPartition,
    CanonicalSessionPartition,
    CanonicalSourceBatch,
    DataSourceError,
)
from thesistrace.data.validation import validate_bootstrap_batch
from thesistrace.publication.serialization import (
    ParquetContractError,
    canonical_json_bytes,
    canonicalize_parquet_rows,
    parquet_bytes,
    parquet_table_bytes,
    validate_parquet_table,
)
from thesistrace.research_series import AlignedResearchData, ttm_window_column

_FAMILY_GENERATION_FORMAT = "thesistrace-family-generation"
_FAMILY_MANIFEST_FORMAT = "thesistrace-dataset-family"
_TABLE_MANIFEST_FORMAT = "thesistrace-canonical-table"
_MANIFEST_VERSION = 1
_UNIVERSE_NAMES = UNIVERSE_NAMES
_MARKET_CANDIDATE_TABLE_SPEC_BY_NAME = {spec.name: spec for spec in MARKET_CANDIDATE_TABLE_SPECS}
_FINANCIAL_PERFORMANCE_EVIDENCE = (
    "financial-io-2010-baseline.json#sha256="
    "6f053d3a506e0e345a254c6caf0bdd17664500bb6ce812ff5e0b66608608f2e6"
)
_COLUMNAR_RECORD_BATCH_ROWS = 65_536


class GenerationStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class MountedGenerationAdmission:
    generation: MountedFamilyGenerationDescriptor
    research_calendar: tuple[str, ...]
    financial_observation_through_session: str | None
    financial_research_readiness: str | None
    industry_observation_through_session: str | None


@dataclass(frozen=True)
class MountedRefreshBase:
    generation: MountedFamilyGenerationDescriptor
    canonical: dict[str, object]


@dataclass(frozen=True)
class MountedMarketSeries:
    generation: MountedFamilyGenerationDescriptor
    research_data: AlignedResearchData


@dataclass(frozen=True, order=True)
class HistoricalInstrumentIdentity:
    instrument_id: str
    ts_code: str


@dataclass(frozen=True, order=True)
class HistoricalInstrumentLifecycle:
    instrument_id: str
    ts_code: str
    listed_from: str
    listed_to: str


@dataclass(frozen=True, order=True)
class GenerationFileRef:
    kind: str
    sha256: str


class MountedGenerationStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._files = AddressedFileStore(self._root)

    @property
    def root(self) -> Path:
        return self._root

    def storage_is_available(self) -> bool:
        descriptor: int | None = None
        try:
            descriptor = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
            return True
        except OSError:
            return False
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def materialize(
        self,
        canonical: Mapping[str, object],
        *,
        prepared_at: datetime,
        source_name: str,
        source_lineage: Mapping[str, object],
    ) -> MountedFamilyGenerationDescriptor:
        normalized = _normalize_canonical(canonical)
        _validate_generation(normalized)
        calendar = normalized["research_calendar"]
        assert isinstance(calendar, list)
        table_references = {
            spec.name: self._materialize_table(
                spec,
                _table_rows(normalized, spec.name),
                calendar,
            )
            for spec in MARKET_CANDIDATE_TABLE_SPECS
            if spec.name not in {"industry_membership", "daily_basic", "daily_basic_sessions"}
            or spec.name in normalized
        }
        family_references = [
            self._materialize_market_family(
                family_spec,
                table_references=table_references,
                canonical=normalized,
                calendar=calendar,
                source_evidence=(
                    self._collected_daily_basic_evidence(source_name, source_lineage)
                    if family_spec == DAILY_BASIC_FAMILY_SPEC else ()
                ),
            )
            for family_spec in _non_financial_specs_for_canonical(normalized)
        ]
        field_availability = tuple(
            sorted(str(row["field_id"]) for row in normalized["field_catalog"])
        )
        identity = {
            "schema_contract": "canonical-research",
            "data_through_session": str(calendar[-1]),
            "research_sessions": [str(session) for session in calendar],
            "field_availability": list(field_availability),
            "families": family_references,
            "financial_research_readiness": None,
        }
        data_identity = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        preparation = _preparation(prepared_at, source_name, source_lineage)
        root_manifest = {
            "format": _FAMILY_GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": data_identity,
            **identity,
            "financial_publication_coordinate": None,
            "industry_publication_coordinate": None,
            "preparation": preparation,
        }
        root_bytes = _bounded_manifest_bytes(root_manifest)
        root_sha256 = hashlib.sha256(root_bytes).hexdigest()
        self._store_addressed(self._manifest_path(root_sha256), root_sha256, root_bytes)
        return _family_generation_descriptor_from_root(root_sha256, root_manifest)

    def materialize_bootstrap_stream(
        self,
        stream: CanonicalBootstrapStream,
        *,
        prepared_at: datetime,
    ) -> MountedFamilyGenerationDescriptor:
        static = dict(stream.static)
        required_static = {
            "schema_version",
            "research_calendar",
            "instruments",
            "field_catalog",
        }
        if not required_static <= set(static) or set(static) - required_static - {
            "industry_membership", "daily_basic_sessions",
        }:
            raise GenerationStoreError("Streaming Bootstrap static table set is incompatible")
        calendar_value = static["research_calendar"]
        if not isinstance(calendar_value, list) or not calendar_value:
            raise GenerationStoreError("Streaming Bootstrap Research Calendar is invalid")
        calendar = [str(value) for value in calendar_value]
        if calendar != sorted(set(calendar)) or stream.covered_session_range != (
            calendar[0],
            calendar[-1],
        ):
            raise GenerationStoreError("Streaming Bootstrap Research Calendar is invalid")

        session_specs = tuple(
            spec
            for spec in MARKET_CANDIDATE_TABLE_SPECS
            if spec.session_field is not None and spec.name != "research_calendar"
            and (spec.name not in {"daily_basic", "daily_basic_sessions"}
                 or "daily_basic_sessions" in static)
        )
        table_references: dict[str, dict[str, object]] = {}
        for spec in MARKET_CANDIDATE_TABLE_SPECS:
            if spec in session_specs:
                continue
            if spec.name in {"industry_membership", "daily_basic", "daily_basic_sessions"} and (
                spec.name not in static
            ):
                continue
            table_references[spec.name] = self._materialize_table(
                spec,
                _table_rows(static, spec.name),
                calendar,
            )

        objects_by_table: dict[str, list[dict[str, object]]] = {
            spec.name: [] for spec in session_specs
        }
        row_counts = {spec.name: 0 for spec in session_specs}
        consumed_sessions: list[str] = []
        for ordinal, partition in enumerate(stream.partitions()):
            if not isinstance(
                partition,
                CanonicalSessionPartition | CanonicalColumnarSessionPartition,
            ):
                raise GenerationStoreError("Streaming Bootstrap partition is incompatible")
            expected_sessions = calendar[
                ordinal * GENERATION_SESSION_PARTITION_COUNT : (ordinal + 1)
                * GENERATION_SESSION_PARTITION_COUNT
            ]
            if list(partition.sessions) != expected_sessions:
                raise GenerationStoreError("Streaming Bootstrap partition ordering is invalid")
            if isinstance(partition, CanonicalSessionPartition):
                block = {
                    **static,
                    **dict(partition.canonical),
                    "research_calendar": list(partition.sessions),
                }
                try:
                    validate_bootstrap_batch(
                        CanonicalSourceBatch(
                            source_name=stream.source_name,
                            collection_kind="bootstrap",
                            source_lineage=dict(stream.source_lineage),
                            canonical=block,
                            covered_session_range=(
                                partition.sessions[0],
                                partition.sessions[-1],
                            ),
                        )
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise GenerationStoreError(
                        "Streaming Bootstrap partition is invalid"
                    ) from error
                for spec in session_specs:
                    rows = _table_rows(block, spec.name)
                    canonical_rows = canonicalize_parquet_rows(rows, spec.contract)
                    objects_by_table[spec.name].append(
                        self._materialize_partition(spec, canonical_rows, ordinal)
                    )
                    row_counts[spec.name] += len(canonical_rows)
            else:
                expected_tables = {spec.name for spec in session_specs}
                if set(partition.tables) != expected_tables:
                    raise GenerationStoreError(
                        "Columnar Bootstrap partition table set is incompatible"
                    )
                for spec in session_specs:
                    table = partition.tables[spec.name]
                    self._validate_columnar_session_extent(
                        spec,
                        table,
                        partition.sessions,
                    )
                _validate_columnar_candidate_semantics(
                    partition.tables,
                    partition.sessions,
                    static,
                )
                for spec in session_specs:
                    table = partition.tables[spec.name]
                    objects_by_table[spec.name].append(
                        self._materialize_columnar_partition(spec, table, ordinal)
                    )
                    row_counts[spec.name] += table.num_rows
            consumed_sessions.extend(partition.sessions)
        if consumed_sessions != calendar:
            raise GenerationStoreError("Streaming Bootstrap partition coverage is incomplete")
        for spec in session_specs:
            table_references[spec.name] = self._materialize_table_manifest(
                spec,
                objects_by_table[spec.name],
                row_counts[spec.name],
            )

        family_references = [
            self._materialize_market_family(
                family_spec,
                table_references=table_references,
                canonical=static,
                calendar=calendar,
                source_evidence=(
                    self._collected_daily_basic_evidence(stream.source_name, stream.source_lineage)
                    if family_spec == DAILY_BASIC_FAMILY_SPEC else ()
                ),
            )
            for family_spec in _non_financial_specs_for_canonical(static)
        ]
        field_catalog_value = static["field_catalog"]
        assert isinstance(field_catalog_value, list)
        field_availability = tuple(sorted(str(row["field_id"]) for row in field_catalog_value))
        identity = {
            "schema_contract": "canonical-research",
            "data_through_session": calendar[-1],
            "research_sessions": calendar,
            "field_availability": list(field_availability),
            "families": family_references,
            "financial_research_readiness": None,
        }
        data_identity = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        root_manifest = {
            "format": _FAMILY_GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": data_identity,
            **identity,
            "financial_publication_coordinate": None,
            "industry_publication_coordinate": None,
            "preparation": _preparation(
                prepared_at,
                stream.source_name,
                stream.source_lineage,
            ),
        }
        root_bytes = _bounded_manifest_bytes(root_manifest)
        root_sha256 = hashlib.sha256(root_bytes).hexdigest()
        self._store_addressed(self._manifest_path(root_sha256), root_sha256, root_bytes)
        return _family_generation_descriptor_from_root(root_sha256, root_manifest)

    def inspect_root(
        self,
        manifest_sha256: str,
    ) -> MountedFamilyGenerationDescriptor:
        root = self._read_family_generation_root(manifest_sha256)
        return _family_generation_descriptor_from_root(manifest_sha256, root)

    def published_indicator_reference(self, manifest_sha256: str) -> dict[str, object] | None:
        """Read a Family reference from the caller's accepted published Generation.

        The caller owns publication authority (Head or a persisted refresh source).
        Reading an arbitrary candidate root does not confer that authority.
        """
        root = self._read_family_generation_root(manifest_sha256)
        reference = _family_reference(root, "equity.financial_indicator")
        return None if reference is None else dict(reference)

    def validate_generation(
        self,
        manifest_sha256: str,
    ) -> MountedFamilyGenerationDescriptor:
        descriptor = self.validate_market_generation(manifest_sha256)
        root = self._read_family_generation_root(manifest_sha256)
        indicator = _family_reference(root, "equity.financial_indicator")
        if indicator is not None:
            from thesistrace.data.financial_indicator_candidate import (
                FinancialIndicatorCandidateStore,
            )

            indicator_store = FinancialIndicatorCandidateStore(self._root)
            if (
                indicator_store.family_reference(str(indicator["manifest_sha256"]))
                != indicator
            ):
                raise GenerationStoreError("Indicator family differs from its candidate")
        if descriptor.financial_candidate_manifest_sha256 is None:
            return descriptor
        root = self._read_family_generation_root(manifest_sha256)
        from thesistrace.data.financial_candidate import (
            FinancialCandidateError,
            FinancialCandidateStore,
        )

        financial_store = FinancialCandidateStore(self._root)
        try:
            financial = financial_store.validate_stored(
                descriptor.financial_candidate_manifest_sha256
            )
            expected_reference = financial_store.family_reference(
                descriptor.financial_candidate_manifest_sha256
            )
        except FinancialCandidateError as error:
            raise GenerationStoreError("Financial Dataset Family is invalid") from error
        financial_reference = _family_reference(root, "equity.financial_pit")
        if not isinstance(financial_reference, Mapping) or dict(financial_reference) != (
            expected_reference
        ):
            raise GenerationStoreError(
                "Financial Dataset Family reference does not match its manifest"
            )
        if financial.observation_through_session > descriptor.data_through_session:
            raise GenerationStoreError("Financial candidate exceeds Market Coverage")
        return descriptor

    def validate_market_generation(
        self,
        manifest_sha256: str,
    ) -> MountedFamilyGenerationDescriptor:
        """Validate Market and Industry Families without reopening Financial PIT."""
        root = self._read_family_generation_root(manifest_sha256)
        references = root["families"]
        assert isinstance(references, list)
        table_references: dict[str, Mapping[str, object]] = {}
        daily_evidence_dates: frozenset[str] | None = None
        for reference in references:
            if not isinstance(reference, Mapping):
                raise GenerationStoreError("Dataset Family reference is incompatible")
            if reference.get("family_id") in {"equity.financial_pit", "equity.financial_indicator"}:
                continue
            family_spec = _family_spec_for_reference(reference)
            family_manifest = self._read_family_manifest(family_spec, reference)
            if family_spec == DAILY_BASIC_FAMILY_SPEC:
                verified_dates = self._verify_daily_basic_evidence(
                    family_manifest["source_evidence"],
                )
                if family_manifest["source_evidence"]:
                    daily_evidence_dates = verified_dates
            family_table_references = family_manifest["tables"]
            assert isinstance(family_table_references, list)
            for table_reference, table_name in zip(
                family_table_references,
                family_spec.table_names,
                strict=True,
            ):
                if not isinstance(table_reference, Mapping):
                    raise GenerationStoreError("Dataset Family table reference is incompatible")
                table_references[table_name] = table_reference
        canonical = self._validate_market_tables_streaming(table_references)
        if daily_evidence_dates is not None and daily_evidence_dates != {
            str(row["session"]) for row in canonical["daily_basic_sessions"]
        }:
            raise GenerationStoreError("Daily basic source evidence does not match collected dates")
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        _validate_candidate_projection(descriptor, canonical)
        return descriptor

    def _validate_market_tables_streaming(
        self,
        table_references: Mapping[str, Mapping[str, object]],
    ) -> dict[str, object]:
        required = {
            table_name for family in CORE_MARKET_FAMILY_SPECS for table_name in family.table_names
        }
        actual = set(table_references)
        if not required <= actual or actual - required - {
            "industry_membership", "daily_basic", "daily_basic_sessions",
        } or (("daily_basic" in actual) != ("daily_basic_sessions" in actual)):
            raise GenerationStoreError("Dataset Family table set is incomplete")
        calendar_spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME["research_calendar"]
        calendar_rows = self._open_table(
            calendar_spec,
            table_references["research_calendar"],
            None,
        )
        calendar = [str(row["session"]) for row in calendar_rows]
        static_tables: dict[str, list[dict[str, object]]] = {
            "research_calendar": calendar_rows,
        }
        session_manifests: dict[str, dict[str, object]] = {}
        for spec in MARKET_CANDIDATE_TABLE_SPECS:
            if spec.name == "research_calendar" or spec.name not in table_references:
                continue
            reference = table_references[spec.name]
            if spec.session_field is None:
                static_tables[spec.name] = self._open_table(spec, reference, calendar)
            else:
                session_manifests[spec.name] = self._read_table_manifest(spec, reference)

        partition_count = (
            len(calendar) + GENERATION_SESSION_PARTITION_COUNT - 1
        ) // GENERATION_SESSION_PARTITION_COUNT
        sparse_partition_counts: set[int] = set()
        for name, manifest in session_manifests.items():
            objects = manifest["objects"]
            spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[name]
            if not isinstance(objects, list) or not 0 < len(objects) <= partition_count:
                raise GenerationStoreError("Generation table partitioning is invalid")
            if spec.allows_sparse_sessions:
                sparse_partition_counts.add(len(objects))
            elif len(objects) != partition_count:
                raise GenerationStoreError("Generation table partitioning is invalid")
        if len(sparse_partition_counts) > 1:
            raise GenerationStoreError("Daily basic tables have different partition extents")

        opened_row_counts = {name: 0 for name in session_manifests}
        daily_basic_sessions: list[dict[str, object]] = []
        for ordinal in range(partition_count):
            start = ordinal * GENERATION_SESSION_PARTITION_COUNT
            block_calendar = calendar[start : start + GENERATION_SESSION_PARTITION_COUNT]
            block_tables: dict[str, pa.Table] = {}
            try:
                for name, manifest in session_manifests.items():
                    spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[name]
                    objects = manifest["objects"]
                    assert isinstance(objects, list)
                    # A preserved family can end before the current price calendar.
                    # Its own row counts and Coverage are still verified below.
                    table = (
                        self._open_canonical_partition_table(spec, objects[ordinal], ordinal)
                        if ordinal < len(objects)
                        else pa.Table.from_pylist([], schema=spec.contract.schema)
                    )
                    opened_row_counts[name] += table.num_rows
                    self._validate_columnar_session_extent(spec, table, tuple(block_calendar))
                    block_tables[name] = table
                    if name == "daily_basic_sessions":
                        daily_basic_sessions.extend(table.to_pylist())
                _validate_columnar_candidate_semantics(
                    block_tables,
                    tuple(block_calendar),
                    {
                        "schema_version": "canonical-eod",
                        "research_calendar": calendar,
                        "instruments": static_tables["instruments"],
                        "field_catalog": static_tables["field_catalog"],
                        **(
                            {"industry_membership": static_tables["industry_membership"]}
                            if "industry_membership" in static_tables
                            else {}
                        ),
                    },
                )
            finally:
                block_tables.clear()
                table = None
                _release_arrow_partition_memory()

        if any(
            opened_row_counts[name] != manifest["row_count"]
            for name, manifest in session_manifests.items()
        ):
            raise GenerationStoreError("Generation table row count is invalid")

        instruments = static_tables["instruments"]
        fields = static_tables["field_catalog"]
        return {
            "schema_version": "canonical-eod",
            "research_calendar": calendar,
            "instruments": instruments,
            "prices": [],
            "trading_states": [],
            "price_limits": [],
            "base_pool": [],
            "liquidity_universes": {name: [] for name in _UNIVERSE_NAMES},
            "field_catalog": fields,
            **({"daily_basic_sessions": daily_basic_sessions}
               if "daily_basic_sessions" in session_manifests else {}),
            **(
                {"industry_membership": static_tables["industry_membership"]}
                if "industry_membership" in static_tables
                else {}
            ),
        }

    def compose_financial_candidate(
        self,
        market_generation_manifest_sha256: str,
        financial_candidate_manifest_sha256: str,
        *,
        prepared_at: datetime,
        publication_coordinate: str | None = None,
    ) -> MountedFamilyGenerationDescriptor:
        from thesistrace.data.financial_candidate import FinancialCandidateStore

        financial_store = FinancialCandidateStore(self._root)
        prior_candidate = financial_store.prior_candidate_manifest_sha256(
            financial_candidate_manifest_sha256
        )
        if prior_candidate is None:
            self.validate_generation(market_generation_manifest_sha256)
        else:
            current = self.inspect_root(market_generation_manifest_sha256)
            if current.financial_candidate_manifest_sha256 != prior_candidate:
                raise GenerationStoreError(
                    "Incremental Financial candidate does not extend the current Family"
                )
        financial_store.validate_against_market_generation(
            financial_candidate_manifest_sha256,
            market_generation_manifest_sha256,
        )
        return self._compose_prevalidated_financial_candidate(
            market_generation_manifest_sha256,
            financial_candidate_manifest_sha256,
            prepared_at=prepared_at,
            publication_coordinate=publication_coordinate,
        )

    def _compose_prevalidated_financial_candidate(
        self,
        market_generation_manifest_sha256: str,
        financial_candidate_manifest_sha256: str,
        *,
        prepared_at: datetime,
        publication_coordinate: str | None,
    ) -> MountedFamilyGenerationDescriptor:
        from thesistrace.data.fields import FINANCIAL_FIELDS
        from thesistrace.data.financial_candidate import FinancialCandidateStore

        market = self.inspect_root(market_generation_manifest_sha256)
        financial_store = FinancialCandidateStore(self._root)
        financial = financial_store.reopen(financial_candidate_manifest_sha256)
        financial_reference = financial_store.family_reference(
            financial_candidate_manifest_sha256
        )
        source_fields = financial_store.source_fields_by_endpoint(
            financial_candidate_manifest_sha256
        )
        if (
            financial.coverage_start < market.research_sessions[0]
            or financial.observation_through_session > market.data_through_session
            or any(
                field.source_column not in source_fields.get(field.source_endpoint, ())
                for field in FINANCIAL_FIELDS
            )
        ):
            raise GenerationStoreError("Financial candidate is incompatible with Market Data")
        root = self._read_family_generation_root(market_generation_manifest_sha256)
        family_references = _replace_family_references(
            root["families"], {"equity.financial_pit": financial_reference},
        )
        market_field_ids = {
            str(field_id)
            for field_id in root["field_availability"]
            if str(field_id) not in {field.field_id for field in FINANCIAL_FIELDS}
        }
        identity = {
            "schema_contract": root["schema_contract"],
            "data_through_session": root["data_through_session"],
            "research_sessions": root["research_sessions"],
            "field_availability": sorted(
                {*market_field_ids, *(field.field_id for field in FINANCIAL_FIELDS)}
            ),
            "families": family_references,
            "financial_research_readiness": _financial_readiness_declaration(
                financial_reference["dataset_coverage"],
                field_ids=[field.field_id for field in FINANCIAL_FIELDS],
            ),
        }
        manifest = {
            "format": _FAMILY_GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
            **identity,
            "financial_publication_coordinate": (
                publication_coordinate or financial_candidate_manifest_sha256
            ),
            "industry_publication_coordinate": root.get(
                "industry_publication_coordinate"
            ),
            "preparation": _preparation(
                prepared_at,
                "financial-composition",
                {
                    "market_generation_manifest_sha256": market_generation_manifest_sha256,
                    "financial_candidate_manifest_sha256": financial_candidate_manifest_sha256,
                },
            ),
        }
        content = _bounded_manifest_bytes(manifest)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store_addressed(self._manifest_path(sha256), sha256, content)
        return _family_generation_descriptor_from_root(sha256, manifest)

    def compose_with_indicator_candidate(
        self,
        market_manifest_sha256: str,
        candidate_sha256: str,
        *,
        prepared_at: datetime,
    ) -> MountedFamilyGenerationDescriptor:
        from thesistrace.data.financial_indicator_candidate import (
            FinancialIndicatorCandidateStore,
        )

        market = self.validate_generation(market_manifest_sha256)
        store = FinancialIndicatorCandidateStore(self._root)
        candidate, reference = store.validate_with_reference(candidate_sha256)
        return self._compose_validated_indicator(
            market, candidate_sha256, candidate, reference, prepared_at=prepared_at,
        )

    def _compose_incremental_indicator_candidate(
        self, prevalidated_generation_sha256: str, candidate_sha256: str, *,
        published_generation_sha256: str, prepared_at: datetime,
        indicator_store,
    ) -> MountedFamilyGenerationDescriptor:

        # The financial refresh owns both authorities: a Head read and a market
        # Generation already composed/checked against that same Head.
        published = self.published_indicator_reference(published_generation_sha256)
        if self.published_indicator_reference(prevalidated_generation_sha256) != published:
            raise GenerationStoreError("Indicator composition predecessor differs from Head")
        candidate, reference = indicator_store.validate_incremental_with_reference(
            candidate_sha256, published_base_reference=published,
        )
        return self._compose_validated_indicator(
            self.inspect_root(prevalidated_generation_sha256), candidate_sha256,
            candidate, reference, prepared_at=prepared_at,
        )

    def _compose_validated_indicator(
        self, market, candidate_sha256, candidate, reference, *, prepared_at,
    ) -> MountedFamilyGenerationDescriptor:
        from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore

        market_manifest_sha256 = market.manifest_sha256
        store = FinancialIndicatorCandidateStore(self._root)
        sessions = candidate["research_sessions"]
        identities = {
            item.ts_code: item.instrument_id
            for item in self.read_financial_indicator_identities(
                market_manifest_sha256, through_session=sessions[-1]
            )
        }
        if candidate["instrument_ids"] != identities:
            raise GenerationStoreError("Indicator candidate historical identities differ")
        if sessions != [
            day for day in market.research_sessions if sessions[0] <= day <= sessions[-1]
        ]:
            raise GenerationStoreError("Indicator candidate calendar differs")
        root = self._read_family_generation_root(market_manifest_sha256)
        previous = _family_reference(root, "equity.financial_indicator")
        if previous is not None:
            prior = store.reopen(str(previous["manifest_sha256"]))
            if not set(prior["observation_sha256s"]) <= set(
                candidate["observation_sha256s"]
            ):
                raise GenerationStoreError(
                    "Indicator candidate drops retained observations"
                )
            if not set(prior["discovery_evidence_sha256s"]) <= set(
                candidate["discovery_evidence_sha256s"]
            ):
                raise GenerationStoreError("Indicator candidate drops retained discovery evidence")
        identity = {
            key: root[key]
            for key in (
                "schema_contract",
                "data_through_session",
                "research_sessions",
                "financial_research_readiness",
            )
        }
        identity["families"] = _replace_family_references(
            root["families"], {"equity.financial_indicator": reference}
        )
        identity["field_availability"] = sorted(
            set(root["field_availability"]) | set(reference["field_ids"])
        )
        manifest = {
            **root,
            **identity,
            "data_identity": hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
            "preparation": _preparation(
                prepared_at,
                "indicator-composition",
                {
                    "source_generation": market_manifest_sha256,
                    "indicator_candidate": candidate_sha256,
                },
            ),
        }
        content = _bounded_manifest_bytes(manifest)
        digest = hashlib.sha256(content).hexdigest()
        self._store_addressed(self._manifest_path(digest), digest, content)
        return _family_generation_descriptor_from_root(digest, manifest)

    def materialize_daily_basic_history(
        self,
        source_manifest_sha256: str,
        partitions: Iterable[CanonicalSessionPartition],
        *,
        source_evidence: Sequence[Mapping[str, str]],
        prepared_at: datetime,
    ) -> MountedFamilyGenerationDescriptor:
        """Add complete daily history in bounded blocks, reusing all other families.

        This prepares an immutable root only. Publication still checks the source
        family against the current Head through the ordinary publication owner.
        """
        from thesistrace.data.canonical_mapping import daily_basic_field_catalog
        from thesistrace.data.canonical_mapping import field_catalog as market_field_catalog

        source = self.inspect_root(source_manifest_sha256)
        calendar = list(source.research_sessions)
        if self._verify_daily_basic_evidence(source_evidence) != frozenset(calendar):
            raise GenerationStoreError(
                "Daily basic history evidence must cover the source calendar"
            )
        allowed = {identity.instrument_id for identity in
                   self.read_historical_ordinary_a_share_identities(source_manifest_sha256)}
        root = self._read_family_generation_root(source_manifest_sha256)
        names = DAILY_BASIC_FAMILY_SPEC.table_names
        objects: dict[str, list[dict[str, object]]] = {name: [] for name in names}
        row_counts = dict.fromkeys(names, 0)
        offset = 0
        for ordinal, partition in enumerate(partitions):
            expected = tuple(calendar[offset:offset + GENERATION_SESSION_PARTITION_COUNT])
            if not expected or partition.sessions != expected or set(partition.canonical) != set(
                names
            ):
                raise GenerationStoreError("Daily basic history partition scope is incompatible")
            normalized = {}
            for name in names:
                spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[name]
                try:
                    normalized[name] = canonicalize_parquet_rows(
                        _table_rows(partition.canonical, name), spec.contract,
                    )
                except ParquetContractError as error:
                    raise GenerationStoreError(
                        "Daily basic history table is incompatible"
                    ) from error
            rows = normalized["daily_basic"]
            coordinates = {(row["session"], row["instrument_id"]) for row in rows}
            if (
                normalized["daily_basic_sessions"] != [{"session": day} for day in expected]
                or len(coordinates) != len(rows)
                or any(day not in expected or instrument not in allowed
                       for day, instrument in coordinates)
            ):
                raise GenerationStoreError("Daily basic history observed coordinates are invalid")
            for name in names:
                spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[name]
                objects[name].append(self._materialize_partition(spec, normalized[name], ordinal))
                row_counts[name] += len(normalized[name])
            offset += len(expected)
        if offset != len(calendar):
            raise GenerationStoreError("Daily basic history partitions are incomplete")
        tables = {
            name: self._materialize_table_manifest(
                _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[name], objects[name], row_counts[name],
            ) for name in names
        }
        retained_evidence = {
            item["sha256"]: dict(item) for item in (
                *self.daily_basic_source_evidence(source_manifest_sha256), *source_evidence,
            )
        }
        daily_reference = self._materialize_market_family(
            DAILY_BASIC_FAMILY_SPEC, table_references=tables,
            canonical={"daily_basic_sessions": [{"session": day} for day in calendar]},
            calendar=calendar, source_evidence=tuple(retained_evidence.values()),
        )
        catalog_spec, catalog_reference = self._family_table_reference(
            root, "data.field_catalog", "field_catalog",
        )
        catalog = {
            str(row["field_id"]): row
            for row in self._open_table(catalog_spec, catalog_reference, calendar)
        }
        catalog.update({str(row["field_id"]): row for row in (
            *market_field_catalog(calendar[-1]), *daily_basic_field_catalog(calendar[-1]),
        )})
        catalog_rows = list(catalog.values())
        catalog_table = self._materialize_table(catalog_spec, catalog_rows, calendar)
        catalog_family = get_family_spec("data.field_catalog")
        assert catalog_family is not None
        catalog_reference = self._materialize_market_family(
            catalog_family, table_references={"field_catalog": catalog_table},
            canonical={"field_catalog": catalog_rows}, calendar=calendar,
        )
        identity = {key: root[key] for key in (
            "schema_contract", "data_through_session", "research_sessions",
            "financial_research_readiness",
        )}
        identity["families"] = _replace_family_references(root["families"], {
            DAILY_BASIC_FAMILY_SPEC.family_id: daily_reference,
            "data.field_catalog": catalog_reference,
        })
        identity["field_availability"] = sorted(set(root["field_availability"]) | set(catalog))
        manifest = {
            **root, **identity,
            "data_identity": hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
            "preparation": _preparation(prepared_at, "daily-basic-history", {
                "source_generation": source_manifest_sha256,
            }),
        }
        content = _bounded_manifest_bytes(manifest)
        digest = hashlib.sha256(content).hexdigest()
        self._store_addressed(self._manifest_path(digest), digest, content)
        return self.validate_market_generation(digest)

    def materialize_industry_candidate(
        self,
        market_generation_manifest_sha256: str,
        rows: list[dict[str, object]],
        *,
        observation_through_session: str,
    ) -> MountedDatasetFamilyDescriptor:
        market = self.inspect_root(market_generation_manifest_sha256)
        try:
            through = date.fromisoformat(observation_through_session).isoformat()
        except ValueError as error:
            raise GenerationStoreError("Industry Coverage is invalid") from error
        if through not in market.research_sessions:
            raise GenerationStoreError("Industry Coverage exceeds Market Coverage")
        allowed = {
            identity.instrument_id
            for identity in self.read_historical_ordinary_a_share_identities(
                market_generation_manifest_sha256
            )
        }
        if any(str(row.get("instrument_id")) not in allowed for row in rows):
            raise GenerationStoreError("Industry instrument identity is incompatible")
        calendar = list(
            market.research_sessions[: market.research_sessions.index(through) + 1]
        )
        table = self._materialize_table(
            _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME["industry_membership"],
            rows,
            calendar,
        )
        reference = self._materialize_market_family(
            INDUSTRY_FAMILY_SPEC,
            table_references={"industry_membership": table},
            canonical={"industry_membership": rows},
            calendar=calendar,
        )
        return _family_descriptor_from_reference(reference, INDUSTRY_FAMILY_SPEC)

    def compose_industry_candidate(
        self,
        generation_manifest_sha256: str,
        industry_candidate_manifest_sha256: str,
        *,
        prepared_at: datetime,
        publication_coordinate: str,
    ) -> MountedFamilyGenerationDescriptor:
        current = self.inspect_root(generation_manifest_sha256)
        _require_sha256(publication_coordinate)
        root = self._read_family_generation_root(generation_manifest_sha256)
        candidate_reference = self._industry_family_reference(
            industry_candidate_manifest_sha256
        )
        coverage = candidate_reference["dataset_coverage"]
        if (
            str(coverage["start"]) < current.research_sessions[0]
            or str(coverage["end"]) > current.data_through_session
        ):
            raise GenerationStoreError("Industry candidate is incompatible with Market Data")
        family_references = _replace_family_references(
            root["families"], {INDUSTRY_FAMILY_SPEC.family_id: candidate_reference},
        )
        identity = {
            "schema_contract": root["schema_contract"],
            "data_through_session": root["data_through_session"],
            "research_sessions": root["research_sessions"],
            "field_availability": root["field_availability"],
            "families": family_references,
            "financial_research_readiness": root["financial_research_readiness"],
        }
        manifest = {
            "format": _FAMILY_GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
            **identity,
            "financial_publication_coordinate": root["financial_publication_coordinate"],
            "industry_publication_coordinate": publication_coordinate,
            "preparation": _preparation(
                prepared_at,
                "industry-composition",
                {
                    "source_generation_manifest_sha256": generation_manifest_sha256,
                    "industry_candidate_manifest_sha256": (
                        industry_candidate_manifest_sha256
                    ),
                },
            ),
        }
        content = _bounded_manifest_bytes(manifest)
        sha256 = hashlib.sha256(content).hexdigest()
        self._store_addressed(self._manifest_path(sha256), sha256, content)
        return _family_generation_descriptor_from_root(sha256, manifest)

    def open_industry_candidate(
        self,
        manifest_sha256: str,
    ) -> MountedDatasetFamilyDescriptor:
        return _family_descriptor_from_reference(
            self._industry_family_reference(manifest_sha256),
            INDUSTRY_FAMILY_SPEC,
        )

    def _industry_family_reference(self, manifest_sha256: str) -> dict[str, object]:
        _require_sha256(manifest_sha256)
        manifest = self._read_manifest(manifest_sha256)
        if (
            manifest.get("format") != _FAMILY_MANIFEST_FORMAT
            or manifest.get("version") != _MANIFEST_VERSION
            or manifest.get("family_id") != INDUSTRY_FAMILY_SPEC.family_id
            or manifest.get("schema_contract") != INDUSTRY_FAMILY_SPEC.schema_contract
        ):
            raise GenerationStoreError("Industry candidate is incompatible")
        tables = manifest.get("tables")
        if not isinstance(tables, list):
            raise GenerationStoreError("Industry candidate is incompatible")
        content = _bounded_manifest_bytes(manifest)
        reference = {
            "family_id": INDUSTRY_FAMILY_SPEC.family_id,
            "schema_contract": INDUSTRY_FAMILY_SPEC.schema_contract,
            "dataset_coverage": manifest.get("dataset_coverage"),
            "validation_summary": manifest.get("validation_summary"),
            "manifest_sha256": manifest_sha256,
            "manifest_byte_count": len(content),
            "table_names": list(INDUSTRY_FAMILY_SPEC.table_names),
        }
        self._read_family_manifest(INDUSTRY_FAMILY_SPEC, reference)
        return reference

    def read_historical_ordinary_a_share_identities(
        self,
        manifest_sha256: str,
    ) -> tuple[HistoricalInstrumentIdentity, ...]:
        return tuple(
            HistoricalInstrumentIdentity(item.instrument_id, item.ts_code)
            for item in self.read_historical_ordinary_a_share_lifecycles(manifest_sha256)
        )

    def read_financial_indicator_identities(
        self,
        manifest_sha256: str,
        *,
        through_session: str,
    ) -> tuple[HistoricalInstrumentIdentity, ...]:
        """Require stocks listed by the coverage boundary, including delisted stocks."""
        return tuple(
            HistoricalInstrumentIdentity(item.instrument_id, item.ts_code)
            for item in self.read_historical_ordinary_a_share_lifecycles(manifest_sha256)
            if item.listed_from <= through_session
        )

    def read_historical_ordinary_a_share_lifecycles(
        self,
        manifest_sha256: str,
    ) -> tuple[HistoricalInstrumentLifecycle, ...]:
        root = self._read_family_generation_root(manifest_sha256)
        spec, reference = self._family_table_reference(
            root,
            "market.instrument_identity",
            "instruments",
        )
        research_sessions = root["research_sessions"]
        if not isinstance(research_sessions, list):
            raise GenerationStoreError("Research Session projection is incompatible")
        rows = self._open_table(
            spec,
            reference,
            [str(session) for session in research_sessions],
        )
        identities = tuple(
            HistoricalInstrumentLifecycle(
                instrument_id=str(row["instrument_id"]),
                ts_code=str(row["ts_code"]),
                listed_from=str(row["listed_from"]),
                listed_to=str(row["listed_to"]),
            )
            for row in rows
            if row["asset_type"] == "ordinary_a_share"
        )
        if not identities:
            raise GenerationStoreError("Historical ordinary A-share identity set is empty")
        return identities

    def read_market_slice(
        self,
        manifest_sha256: str,
        *,
        sessions: list[str],
        universe_name: str,
        neutralization: str,
        field_bindings: Mapping[str, str],
        require_industry: bool = False,
    ) -> MountedMarketSeries:
        if not sessions or sessions != sorted(set(sessions)):
            raise GenerationStoreError("Market Series sessions are invalid")
        if universe_name not in _UNIVERSE_NAMES:
            raise GenerationStoreError("Market Series Universe is invalid")
        if neutralization not in {"none", "industry"}:
            raise GenerationStoreError("Market Series Neutralization is invalid")
        try:
            requested_columns = market_field_columns(field_bindings)
        except MarketSeriesError as error:
            raise GenerationStoreError(str(error)) from error
        root = self._read_family_generation_root(manifest_sha256)
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        if set(field_bindings) - set(descriptor.field_availability):
            raise GenerationStoreError("Market Series field unavailable in Generation")
        full_calendar = list(descriptor.research_sessions)
        if any(session not in full_calendar for session in sessions):
            raise GenerationStoreError("Market Series sessions are outside Coverage")
        selected = set(sessions)
        universe_spec, universe_reference = self._family_table_reference(
            root,
            "equity.liquidity_universe",
            "liquidity_universes",
        )
        universe_rows = [
            row
            for row in self._open_table_sessions(
                universe_spec,
                universe_reference,
                selected_sessions=selected,
            )
            if row["universe"] == universe_name
        ]
        if [str(row["session"]) for row in universe_rows] != sessions:
            raise GenerationStoreError("Market Series Universe is incomplete")
        instrument_ids = frozenset(
            str(instrument_id) for row in universe_rows for instrument_id in row["instrument_ids"]
        )
        tables: dict[str, list[dict[str, object]]] = {
            "research_calendar": [{"session": session} for session in sessions],
            "liquidity_universes": universe_rows,
            "base_pool": [],
            "industry_membership": [],
        }
        required_families = {
            "market.instrument_identity",
            "equity.eod_price",
            "equity.trading_state",
            "equity.price_limit",
        }
        if neutralization == "industry" or require_industry:
            required_families.add("equity.industry_membership")
        for family in descriptor.families:
            if family.family_id not in required_families:
                continue
            for table_name in family.table_names:
                spec, reference = self._family_table_reference(root, family.family_id, table_name)
                if spec.session_field is not None:
                    if not instrument_ids:
                        tables[table_name] = []
                        continue
                    columns = None
                    if table_name == "eod_prices":
                        columns = {
                            "session_date",
                            "instrument_id",
                            "open_raw",
                            "open_adj",
                            "turnover_amount_cny",
                            *requested_columns,
                        }
                    rows = self._open_table_sessions(
                        spec,
                        reference,
                        selected_sessions=selected,
                        columns=columns,
                        instrument_ids=instrument_ids,
                    )
                else:
                    columns = (
                        {"instrument_id", "board", "listed_to"}
                        if table_name == "instruments"
                        else {"instrument_id", "active_from", "active_to", "sw2021_l1"}
                    )
                    rows = self._open_table_instruments(
                        spec,
                        reference,
                        instrument_ids=instrument_ids,
                        columns=columns,
                    )
                tables[table_name] = rows
        try:
            research_data = align_market_research_data(
                sessions=sessions,
                instruments=tables["instruments"],
                eod_prices=tables["eod_prices"],
                universe_rows=tables["liquidity_universes"],
                trading_states=tables["trading_states"],
                price_limits=tables["price_limits"],
                industry_membership=tables["industry_membership"],
                field_bindings=field_bindings,
                neutralization=neutralization,
                require_industry=require_industry,
            )
        except MarketSeriesError as error:
            raise GenerationStoreError(str(error)) from error
        return MountedMarketSeries(generation=descriptor, research_data=research_data)

    def read_composite_slice(
        self,
        manifest_sha256: str,
        *,
        sessions: list[str],
        universe_name: str,
        neutralization: str,
        field_bindings: Mapping[str, str],
        require_industry: bool = False,
    ) -> MountedMarketSeries:
        """Resolve one storage-independent market/financial calculation slice."""
        bindings = _field_family_bindings(field_bindings, neutralization)
        market_bindings = bindings.pop("equity.eod_price", {})
        market = self.read_market_slice(
            manifest_sha256,
            sessions=sessions,
            universe_name=universe_name,
            neutralization=neutralization,
            require_industry=require_industry,
            field_bindings=market_bindings,
        )
        if set(field_bindings) - set(market.generation.field_availability):
            raise GenerationStoreError("Composite Series field unavailable in Generation")
        fields = dict(market.research_data.fields)
        windows = dict(market.research_data.ttm_windows)
        for family_id, family_bindings in bindings.items():
            reader, family_manifest = self._series_family_reader(market.generation, family_id)
            table = reader.resolve_table(
                manifest_sha256=family_manifest,
                field_ids=tuple(family_bindings), sessions=tuple(sessions),
                instrument_ids=tuple(sorted(market.research_data.instruments)),
            )
            coordinates = tuple(zip(table["session"].to_pylist(),
                                    table["instrument_id"].to_pylist(), strict=True))
            present = (
                table["source_row_present"].to_pylist()
                if "source_row_present" in table.column_names else [False] * len(coordinates)
            )
            for field_id in family_bindings:
                fields[field_id] = {coordinate: value for coordinate, value, source_present in zip(
                    coordinates, table[field_id].to_pylist(), present, strict=True,
                ) if value is not None or source_present}
                column = ttm_window_column(field_id)
                if column in table.column_names:
                    windows[field_id] = {coordinate: value for coordinate, value in zip(
                        coordinates, table[column].to_pylist(), strict=True,
                    ) if value is not None}
        return MountedMarketSeries(
            generation=market.generation,
            research_data=replace(market.research_data, fields=fields, ttm_windows=windows),
        )

    def _series_family_reader(self, generation: MountedFamilyGenerationDescriptor, family_id: str):
        from thesistrace.data.financial_candidate import FinancialCandidateStore
        from thesistrace.data.financial_series import FinancialSeriesResolver

        readers = {
            "equity.daily_basic": lambda: self._daily_basic_series_reader(generation),
            "equity.financial_indicator": lambda: self._indicator_series_reader(generation),
            "equity.financial_pit": lambda: FinancialSeriesResolver(
                FinancialCandidateStore(self._root)
            ),
        }
        reference = next(
            (item for item in generation.families if item.family_id == family_id), None,
        )
        if reference is None or family_id not in readers:
            raise GenerationStoreError(f"Research Series family is unavailable: {family_id}")
        return readers[family_id](), reference.manifest_sha256

    def _indicator_series_reader(self, generation: MountedFamilyGenerationDescriptor):
        from thesistrace.data.financial_indicator_candidate import (
            FinancialIndicatorCandidateStore,
        )
        from thesistrace.data.financial_indicator_series import (
            FinancialIndicatorSeriesResolver,
        )

        family = next(
            f for f in generation.families if f.family_id == "equity.financial_indicator"
        )
        store = FinancialIndicatorCandidateStore(self._root)
        return FinancialIndicatorSeriesResolver(
            family.manifest_sha256,
            lambda columns, instruments, through: store.read_table(
                family.manifest_sha256,
                columns=columns,
                instrument_ids=instruments,
                through=through,
            ),
        )

    def _daily_basic_series_reader(self, generation: MountedFamilyGenerationDescriptor):
        from thesistrace.data.daily_basic_series import DailyBasicSeriesResolver

        root = self._read_family_generation_root(generation.manifest_sha256)
        reference = _family_reference(root, DAILY_BASIC_FAMILY_SPEC.family_id)
        if reference is None:
            raise GenerationStoreError("Daily basic family is unavailable")
        family = self._read_family_manifest(DAILY_BASIC_FAMILY_SPEC, reference)
        table_reference = next(
            table for table in family["tables"] if table["name"] == "daily_basic"
        )
        spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME["daily_basic"]

        def read_table(sessions: set[str], instruments: frozenset[str], columns: set[str]):
            return self._open_table_sessions_columnar(
                spec, table_reference, selected_sessions=sessions,
                columns=columns, instrument_ids=instruments,
            )

        return DailyBasicSeriesResolver(str(reference["manifest_sha256"]), read_table)

    def read_columnar_slice(
        self,
        manifest_sha256: str,
        *,
        sessions: list[str],
        universe_name: str,
        neutralization: str,
        field_bindings: Mapping[str, str],
        require_industry: bool = False,
        fact_instrument_ids: frozenset[str],
    ):
        from thesistrace.data.columnar_series import ColumnarResearchData

        if not sessions or sessions != sorted(set(sessions)):
            raise GenerationStoreError("Columnar Research sessions are invalid")
        if universe_name not in _UNIVERSE_NAMES:
            raise GenerationStoreError("Columnar Research Universe is invalid")
        if neutralization not in {"none", "industry"}:
            raise GenerationStoreError("Columnar Research Neutralization is invalid")
        bindings = _field_family_bindings(field_bindings, neutralization)
        market_bindings = bindings.pop("equity.eod_price", {})
        requested_columns = market_field_columns(market_bindings)
        root = self._read_family_generation_root(manifest_sha256)
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        if any(session not in descriptor.research_sessions for session in sessions):
            raise GenerationStoreError("Columnar Research sessions are outside Coverage")
        if set(field_bindings) - set(descriptor.field_availability):
            raise GenerationStoreError("Columnar Research field unavailable in Generation")
        selected = set(sessions)
        universe_spec, universe_reference = self._family_table_reference(
            root,
            "equity.liquidity_universe",
            "liquidity_universes",
        )
        universes = self._open_table_sessions_columnar(
            universe_spec,
            universe_reference,
            selected_sessions=selected,
            columns={"session", "universe", "instrument_ids"},
        )
        universes = universes.filter(pc.equal(universes["universe"], universe_name))
        actual_sessions = tuple(
            str(universes["session"][index].as_py()) for index in range(universes.num_rows)
        )
        if actual_sessions != tuple(sessions):
            raise GenerationStoreError("Columnar Research Universe is incomplete")
        instrument_ids = (
            frozenset(
                str(instrument_id)
                for index in range(universes.num_rows)
                for instrument_id in universes["instrument_ids"][index].as_py()
            )
            | fact_instrument_ids
        )
        tables: dict[str, pa.Table] = {}
        required_families = {
            "market.instrument_identity",
            "equity.eod_price",
            "equity.trading_state",
            "equity.price_limit",
        }
        if neutralization == "industry" or require_industry:
            required_families.add("equity.industry_membership")
        for family in descriptor.families:
            if family.family_id not in required_families:
                continue
            for table_name in family.table_names:
                spec, reference = self._family_table_reference(root, family.family_id, table_name)
                if spec.session_field is not None:
                    columns = None
                    if table_name == "eod_prices":
                        columns = {
                            "session_date",
                            "instrument_id",
                            "open_raw",
                            "open_adj",
                            "turnover_amount_cny",
                            *requested_columns,
                        }
                    tables[table_name] = self._open_table_sessions_columnar(
                        spec,
                        reference,
                        selected_sessions=selected,
                        columns=columns,
                        instrument_ids=instrument_ids,
                    )
                else:
                    columns = (
                        {"instrument_id", "board", "listed_to"}
                        if table_name == "instruments"
                        else {"instrument_id", "active_from", "active_to", "sw2021_l1"}
                    )
                    tables[table_name] = self._open_table_instruments_columnar(
                        spec,
                        reference,
                        instrument_ids=instrument_ids,
                        columns=columns,
                    )
        industries = tables.get(
            "industry_membership",
            pa.table(
                {
                    name: pa.array([], type=pa.string())
                    for name in ("instrument_id", "active_from", "active_to", "sw2021_l1")
                }
            ),
        )
        family_values = None
        for family_id, family_bindings in bindings.items():
            reader, family_manifest = self._series_family_reader(descriptor, family_id)
            values = reader.resolve_table(
                manifest_sha256=family_manifest,
                field_ids=tuple(family_bindings), sessions=tuple(sessions),
                instrument_ids=tuple(sorted(instrument_ids)),
            )
            if family_values is None:
                family_values = values
            else:
                coordinates = ("session", "instrument_id")
                if not family_values.select(coordinates).equals(values.select(coordinates)):
                    raise GenerationStoreError("Research Series family coordinates disagree")
                for column in values.column_names:
                    if column not in coordinates:
                        family_values = family_values.append_column(column, values[column])
        return ColumnarResearchData(
            sessions=tuple(sessions),
            _instruments=tables["instruments"],
            _eod_prices=tables["eod_prices"],
            _universes=universes,
            _trading_states=tables["trading_states"],
            _price_limits=tables["price_limits"],
            _industries=industries,
            _family_values=family_values,
            _field_columns={
                **market_field_column_bindings(market_bindings),
                **{field_id: field_id for family in bindings.values() for field_id in family},
            },
        )

    def open_admission(self, manifest_sha256: str) -> MountedGenerationAdmission:
        root = self._read_family_generation_root(manifest_sha256)
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        calendar = descriptor.research_sessions
        calendar_coverage = descriptor.families[0].dataset_coverage
        if not calendar or calendar_coverage != {
            "kind": "research-session-range",
            "start": calendar[0],
            "end": calendar[-1],
            "session_count": len(calendar),
        }:
            raise GenerationStoreError("Generation admission projection is incompatible")
        financial_through: str | None = None
        financial_readiness: str | None = None
        if descriptor.financial_candidate_manifest_sha256 is not None:
            try:
                financial_family = next(
                    family
                    for family in descriptor.families
                    if family.family_id == "equity.financial_pit"
                )
                coverage = financial_family.dataset_coverage
                value = (
                    coverage["discovery_attempted_through_session"]
                    if coverage.get("kind")
                    == "financial-announcement-observation-range"
                    else coverage["observation_through_session"]
                )
                financial_through = date.fromisoformat(str(value)).isoformat()
                readiness = descriptor.financial_research_readiness
                if readiness is None:
                    raise KeyError("financial_research_readiness")
                financial_readiness = str(readiness["status"])
            except (KeyError, StopIteration, ValueError) as error:
                raise GenerationStoreError("Financial admission projection is invalid") from error
        industry_through: str | None = None
        industry_family = next(
            (
                family
                for family in descriptor.families
                if family.family_id == "equity.industry_membership"
            ),
            None,
        )
        if industry_family is not None:
            try:
                value = industry_family.dataset_coverage["end"]
                industry_through = date.fromisoformat(str(value)).isoformat()
            except (KeyError, ValueError) as error:
                raise GenerationStoreError("Industry admission projection is invalid") from error
        return MountedGenerationAdmission(
            generation=descriptor,
            research_calendar=calendar,
            financial_observation_through_session=financial_through,
            financial_research_readiness=financial_readiness,
            industry_observation_through_session=industry_through,
        )

    def maximum_universe_cardinality(
        self,
        manifest_sha256: str,
        *,
        universe: str,
        start_session: str,
        end_session: str,
    ) -> int:
        if universe not in _UNIVERSE_NAMES or start_session > end_session:
            raise ValueError("Universe calculation window is invalid")
        root = self._read_family_generation_root(manifest_sha256)
        spec, reference = self._family_table_reference(
            root,
            "equity.liquidity_universe",
            "liquidity_universes",
        )
        manifest = self._read_table_manifest(spec, reference)
        objects = manifest["objects"]
        assert isinstance(objects, list)
        cardinalities: list[int] = []
        for ordinal, object_ref in enumerate(objects):
            _validate_object_reference(object_ref, ordinal)
            assert isinstance(object_ref, Mapping)
            statistics = object_ref["statistics"]
            assert isinstance(statistics, Mapping)
            values = statistics.get("universe_cardinalities")
            if not isinstance(values, list):
                raise GenerationStoreError("Liquidity Universe statistics are invalid")
            for value in values:
                if (
                    not isinstance(value, list)
                    or len(value) != 5
                    or not all(
                        isinstance(item, int) and not isinstance(item, bool) and item >= 0
                        for item in value[1:]
                    )
                ):
                    raise GenerationStoreError("Liquidity Universe statistics are invalid")
                session = str(value[0])
                if start_session <= session <= end_session:
                    cardinalities.append(int(value[_UNIVERSE_NAMES.index(universe) + 1]))
        return max(cardinalities, default=0)

    def universe_member_union_cardinalities(
        self,
        manifest_sha256: str,
        *,
        universe: str,
        session_windows: Sequence[Sequence[str]],
    ) -> tuple[int, ...]:
        if (
            universe not in _UNIVERSE_NAMES
            or not session_windows
            or any(
                not window or tuple(window) != tuple(sorted(set(window)))
                for window in session_windows
            )
        ):
            raise ValueError("Universe member union windows are invalid")
        selected_sessions = {session for window in session_windows for session in window}
        root = self._read_family_generation_root(manifest_sha256)
        spec, reference = self._family_table_reference(
            root,
            "equity.liquidity_universe",
            "liquidity_universes",
        )
        universes = self._open_table_sessions_columnar(
            spec,
            reference,
            selected_sessions=selected_sessions,
            columns={"session", "universe", "instrument_ids"},
        )
        universes = universes.filter(pc.equal(universes["universe"], universe))
        instrument_bits: dict[str, int] = {}
        members_by_session: dict[str, int] = {}
        for index in range(universes.num_rows):
            session = str(universes["session"][index].as_py())
            if session in members_by_session:
                raise GenerationStoreError("Liquidity Universe session is duplicated")
            member_mask = 0
            for instrument_id_value in universes["instrument_ids"][index].as_py():
                instrument_id = str(instrument_id_value)
                bit = instrument_bits.get(instrument_id)
                if bit is None:
                    bit = 1 << len(instrument_bits)
                    instrument_bits[instrument_id] = bit
                member_mask |= bit
            members_by_session[session] = member_mask
        if set(members_by_session) != selected_sessions:
            raise GenerationStoreError("Liquidity Universe member union is incomplete")
        cardinalities: list[int] = []
        for window in session_windows:
            union_mask = 0
            for session in window:
                union_mask |= members_by_session[session]
            cardinalities.append(union_mask.bit_count())
        return tuple(cardinalities)

    def open_refresh_base(
        self,
        manifest_sha256: str,
        *,
        overlap_session_count: int = 20,
        universe_lookback_session_count: int = 19,
    ) -> MountedRefreshBase:
        if overlap_session_count <= 0 or universe_lookback_session_count < 0:
            raise ValueError("Refresh window policy is invalid")
        root = self._read_family_generation_root(manifest_sha256)
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        calendar_spec, calendar_reference = self._family_table_reference(
            root,
            "market.research_calendar",
            "research_calendar",
        )
        calendar_rows = self._open_table(calendar_spec, calendar_reference, None)
        full_calendar = [str(row["session"]) for row in calendar_rows]
        window_count = overlap_session_count + universe_lookback_session_count
        window_start = full_calendar[max(0, len(full_calendar) - window_count)]
        candidate_tables: dict[str, list[dict[str, object]]] = {
            "research_calendar": [
                row for row in calendar_rows if str(row["session"]) >= window_start
            ]
        }
        present_family_ids = {
            str(reference.get("family_id"))
            for reference in root["families"]
            if isinstance(reference, Mapping)
        }
        for family_spec in ordered_non_financial_specs(present_family_ids)[1:]:
            for table_name in family_spec.table_names:
                spec, reference = self._family_table_reference(
                    root,
                    family_spec.family_id,
                    table_name,
                )
                candidate_tables[table_name] = (
                    self._open_table(spec, reference, full_calendar)
                    if spec.session_field is None
                    else self._open_table_window(
                        spec,
                        reference,
                        start_session=window_start,
                    )
                )
                if (
                    {"eod_prices", "adjustment_factors", "trading_states"}
                    <= candidate_tables.keys()
                ):
                    _consume_refresh_prices(candidate_tables)
        canonical = _validate_refresh_tables(candidate_tables)
        expected_calendar = [str(row["session"]) for row in candidate_tables["research_calendar"]]
        if canonical["research_calendar"] != expected_calendar:
            raise GenerationStoreError("Generation refresh window is invalid")
        return MountedRefreshBase(generation=descriptor, canonical=canonical)

    def materialize_refresh(
        self,
        *,
        predecessor_manifest_sha256: str,
        replacement_canonical: Mapping[str, object],
        replace_from_session: str,
        prepared_at: datetime,
        source_name: str,
        source_lineage: Mapping[str, object],
    ) -> MountedFamilyGenerationDescriptor:
        _validate_generation(replacement_canonical)
        normalized = replacement_canonical
        replacement_calendar = [str(value) for value in normalized["research_calendar"]]
        if replace_from_session not in replacement_calendar:
            raise GenerationStoreError("Refresh replacement boundary is outside Coverage")
        predecessor_root = self._read_family_generation_root(predecessor_manifest_sha256)
        calendar_spec, calendar_reference = self._family_table_reference(
            predecessor_root,
            "market.research_calendar",
            "research_calendar",
        )
        predecessor_calendar_rows = self._open_table(
            calendar_spec,
            calendar_reference,
            None,
        )
        predecessor_calendar = [str(row["session"]) for row in predecessor_calendar_rows]
        if replace_from_session not in predecessor_calendar:
            raise GenerationStoreError("Refresh boundary is outside predecessor Coverage")
        boundary_index = predecessor_calendar.index(replace_from_session)
        rewrite_start_index = (
            boundary_index // GENERATION_SESSION_PARTITION_COUNT
        ) * GENERATION_SESSION_PARTITION_COUNT
        rewrite_start_session = predecessor_calendar[rewrite_start_index]
        new_calendar = [
            session for session in predecessor_calendar if session < replace_from_session
        ] + [session for session in replacement_calendar if session >= replace_from_session]
        if not new_calendar or new_calendar != sorted(set(new_calendar)):
            raise GenerationStoreError("Refresh Research Calendar is invalid")

        catalog_spec, catalog_reference = self._family_table_reference(
            predecessor_root, "data.field_catalog", "field_catalog"
        )
        prior_catalog = self._open_table(catalog_spec, catalog_reference, predecessor_calendar)
        owner_by_field = {field.field_id: field.family_id for field in field_definitions()}
        owned_specs = (
            *CORE_MARKET_FAMILY_SPECS,
            *((DAILY_BASIC_FAMILY_SPEC,) if "daily_basic" in normalized else ()),
        )
        owned_families = {spec.family_id for spec in owned_specs}
        retained_catalog = {
            str(row["field_id"]): row for row in prior_catalog
            if owner_by_field.get(str(row["field_id"])) is not None
            and owner_by_field[str(row["field_id"])] not in owned_families
        }
        refreshed_catalog = {str(row["field_id"]): row for row in normalized["field_catalog"]}
        normalized = {**normalized, "field_catalog": [
            row for _field_id, row in sorted({**retained_catalog, **refreshed_catalog}.items())
        ]}

        table_references: dict[str, dict[str, object]] = {}
        for family_spec in owned_specs:
            for table_name in family_spec.table_names:
                if _family_reference(predecessor_root, family_spec.family_id) is None:
                    spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[table_name]
                    table_references[table_name] = self._materialize_table(
                        spec, _table_rows(normalized, table_name), new_calendar,
                    )
                    continue
                spec, predecessor_reference = self._family_table_reference(
                    predecessor_root, family_spec.family_id, table_name,
                )
                table_references[table_name] = (
                    self._materialize_table(
                        spec,
                        _table_rows(normalized, table_name),
                        new_calendar,
                    )
                    if spec.session_field is None
                    else self._materialize_refresh_table(
                        spec,
                        predecessor_reference,
                        replacement_rows=_iter_table_rows(normalized, table_name),
                        replace_from_session=replace_from_session,
                        rewrite_start_session=rewrite_start_session,
                        new_calendar=new_calendar,
                    )
                )

        if "daily_basic" in normalized:
            normalized = {**normalized, "daily_basic_sessions": self._open_table(
                _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME["daily_basic_sessions"],
                table_references["daily_basic_sessions"], new_calendar,
            )}

        daily_evidence = []
        if "daily_basic" in normalized:
            daily_evidence = list(self.daily_basic_source_evidence(predecessor_manifest_sha256))
            daily_evidence.extend(self._collected_daily_basic_evidence(source_name, source_lineage))
            daily_evidence = list({
                str(item["sha256"]): item for item in daily_evidence
            }.values())

        refreshed_family_references = {
            family_spec.family_id: self._materialize_market_family(
                family_spec,
                table_references=table_references,
                canonical=normalized,
                calendar=new_calendar,
                source_evidence=daily_evidence if family_spec == DAILY_BASIC_FAMILY_SPEC else (),
            )
            for family_spec in owned_specs
        }
        # Refresh replaces the supplied market families. Preserve every other
        # reference and its declared fields without requalifying it against a
        # newer supported catalog.
        family_references = _replace_family_references(
            predecessor_root["families"], refreshed_family_references,
        )
        catalog_spec, catalog_reference = self._family_table_reference(
            predecessor_root, "data.field_catalog", "field_catalog"
        )
        prior_market_fields = {
            str(row["field_id"])
            for row in self._open_table(catalog_spec, catalog_reference, predecessor_calendar)
        }
        retained_fields = set(predecessor_root["field_availability"]) - prior_market_fields
        field_availability = tuple(sorted(
            retained_fields | {str(row["field_id"]) for row in normalized["field_catalog"]}
        ))
        identity = {
            "schema_contract": "canonical-research",
            "data_through_session": new_calendar[-1],
            "research_sessions": list(new_calendar),
            "field_availability": list(field_availability),
            "families": family_references,
            "financial_research_readiness": predecessor_root["financial_research_readiness"],
        }
        data_identity = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        preparation = _preparation(prepared_at, source_name, source_lineage)
        root_manifest = {
            "format": _FAMILY_GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": data_identity,
            **identity,
            "financial_publication_coordinate": predecessor_root[
                "financial_publication_coordinate"
            ],
            "industry_publication_coordinate": predecessor_root.get(
                "industry_publication_coordinate"
            ),
            "preparation": preparation,
        }
        root_bytes = _bounded_manifest_bytes(root_manifest)
        root_sha256 = hashlib.sha256(root_bytes).hexdigest()
        self._store_addressed(self._manifest_path(root_sha256), root_sha256, root_bytes)
        market_generation = _family_generation_descriptor_from_root(root_sha256, root_manifest)
        prior_financial_reference = _family_reference(
            predecessor_root,
            "equity.financial_pit",
        )
        if prior_financial_reference is None:
            return market_generation
        if not isinstance(prior_financial_reference, Mapping):
            raise GenerationStoreError("Financial Dataset Family reference is incompatible")
        from thesistrace.data.financial_candidate import FinancialCandidateStore

        prior_candidate = str(prior_financial_reference["manifest_sha256"])
        financial_store = FinancialCandidateStore(self._root)
        financial_store.reopen_against_prevalidated_market_generation(
            prior_candidate, market_generation.manifest_sha256
        )
        if dict(prior_financial_reference) != financial_store.family_reference(prior_candidate):
            raise GenerationStoreError("Financial Dataset Family reference is incompatible")
        return market_generation

    def _family_table_reference(
        self,
        root: Mapping[str, object],
        family_id: str,
        table_name: str,
    ) -> tuple[_TableSpec, Mapping[str, object]]:
        selected_spec = get_family_spec(family_id)
        reference = _family_reference(root, family_id)
        if selected_spec is None or reference is None:
            raise GenerationStoreError("Dataset Family is unavailable")
        family = self._read_family_manifest(selected_spec, reference)
        table_references = family["tables"]
        assert isinstance(table_references, list)
        table_index = selected_spec.table_names.index(table_name)
        table_reference = table_references[table_index]
        if not isinstance(table_reference, Mapping):
            raise GenerationStoreError("Dataset Family table reference is incompatible")
        return _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[table_name], table_reference

    def referenced_files(self, manifest_sha256: str) -> frozenset[GenerationFileRef]:
        self.inspect_root(manifest_sha256)
        root = self._read_family_generation_root(manifest_sha256)
        references = {GenerationFileRef("manifest", manifest_sha256)}
        families = root["families"]
        assert isinstance(families, list)
        for family in families:
            assert isinstance(family, Mapping)
            family_sha256 = str(family["manifest_sha256"])
            if family.get("family_id") == "equity.financial_indicator":
                references.update(self.indicator_candidate_referenced_files(family_sha256))
                continue
            if family.get("family_id") == "equity.financial_pit":
                references.update(self._financial_referenced_files(family_sha256))
                continue
            references.add(GenerationFileRef("manifest", family_sha256))
            family_manifest = self._read_manifest(family_sha256)
            tables = family_manifest["tables"]
            assert isinstance(tables, list)
            for table in tables:
                assert isinstance(table, Mapping)
                table_sha256 = str(table["manifest_sha256"])
                references.add(GenerationFileRef("manifest", table_sha256))
                table_manifest = self._read_manifest(table_sha256)
                objects = table_manifest["objects"]
                assert isinstance(objects, list)
                references.update(
                    GenerationFileRef("object", str(object_ref["sha256"]))
                    for object_ref in objects
                    if isinstance(object_ref, Mapping)
                )
        return frozenset(references)

    def daily_basic_source_evidence(self, manifest_sha256: str) -> tuple[dict[str, str], ...]:
        """Return the immutable source indexes retained by the daily basic family."""
        root = self._read_family_generation_root(manifest_sha256)
        reference = _family_reference(root, DAILY_BASIC_FAMILY_SPEC.family_id)
        if reference is None:
            return ()
        family = self._read_family_manifest(DAILY_BASIC_FAMILY_SPEC, reference)
        return tuple(dict(item) for item in family["source_evidence"])

    def _collected_daily_basic_evidence(
        self, source_name: str, lineage: Mapping[str, object],
    ) -> tuple[dict[str, str], ...]:
        reference = lineage.get("daily_basic_evidence")
        if reference is None and source_name != "tushare":
            # Deterministic, source-neutral fixtures do not claim supplier observations.
            return ()
        if not isinstance(reference, Mapping):
            raise GenerationStoreError("Daily basic source evidence is required")
        key = lineage.get("daily_basic_collection_key")
        evidence = {"collection_key": key, **dict(reference)}
        self._verify_daily_basic_evidence([evidence])
        return (evidence,)

    def _verify_daily_basic_evidence(self, evidence: object) -> frozenset[str]:
        _validate_daily_basic_evidence_references(evidence)
        dates: set[str] = set()
        try:
            for item in evidence:
                checkpoint = DailyBasicCheckpoint(
                    self._root / MARKET_SOURCE_RECEIPT_DIRECTORY,
                    collection_key=item["collection_key"],
                )
                dates.update(checkpoint.verify_evidence({
                    "path": item["path"], "sha256": item["sha256"],
                }))
        except DataSourceError as error:
            raise GenerationStoreError("Daily basic source evidence is invalid") from error
        return frozenset(dates)

    def indicator_checkpoint_referenced_files(self) -> frozenset[GenerationFileRef]:
        """Protect resumable observations, including capped parent responses."""
        from thesistrace.data.financial_collection import (
            FinancialCollectionError,
            RawFinancialBatchStore,
        )
        from thesistrace.data.financial_indicator_evidence import (
            FinancialIndicatorObservationStore,
        )

        references: set[GenerationFileRef] = set()
        observations = FinancialIndicatorObservationStore(RawFinancialBatchStore(self._root))
        directory = self._root / ".operator" / "indicator-requests"
        try:
            for path in directory.glob("*/*/*.json"):
                receipt = json.loads(AddressedFileStore(self._root).read(
                    path, path.stem, max_byte_count=1024 * 1024,
                ))
                if (
                    not isinstance(receipt, dict)
                    or set(receipt) != {"collection_key", "request", "observation_sha256"}
                    or not isinstance(receipt["collection_key"], str)
                    or not receipt["collection_key"]
                    or hashlib.sha256(receipt["collection_key"].encode()).hexdigest()
                    != path.parent.parent.name
                    or hashlib.sha256(canonical_json_bytes(receipt["request"])).hexdigest()
                    != path.parent.name
                ):
                    raise ValueError("Invalid indicator checkpoint scope")
                digest = receipt["observation_sha256"]
                observations.read(digest)
                references.add(GenerationFileRef("raw_financial", digest))
        except (ValueError, TypeError, AddressedFileError, FinancialCollectionError) as error:
            raise GenerationStoreError("Indicator checkpoint evidence is invalid") from error
        return frozenset(references)

    def indicator_collection_referenced_files(self, digest: str) -> frozenset[GenerationFileRef]:
        from thesistrace.data.financial_collection import (
            FinancialCollectionError,
            RawFinancialBatchStore,
        )
        from thesistrace.data.financial_indicator_evidence import (
            validate_indicator_collection_evidence,
        )

        try:
            evidence = validate_indicator_collection_evidence(
                RawFinancialBatchStore(self._root), digest,
            )
        except (ValueError, TypeError, FinancialCollectionError) as error:
            raise GenerationStoreError("Indicator collection evidence is invalid") from error
        return frozenset({
            GenerationFileRef("raw_financial", digest),
            *(GenerationFileRef("raw_financial", item["observation_sha256"])
              for item in evidence["completed_requests"]),
        })

    def indicator_candidate_referenced_files(self, digest: str) -> frozenset[GenerationFileRef]:
        from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore

        manifest = FinancialIndicatorCandidateStore(self._root).validate(digest)
        return frozenset({
            GenerationFileRef("manifest", digest),
            *(GenerationFileRef("object", partition["sha256"])
              for partition in manifest["partitions"]),
            *(GenerationFileRef("raw_financial", reference)
              for reference in manifest["observation_sha256s"]),
            *(GenerationFileRef("raw_financial", reference)
              for reference in manifest["collection_evidence_sha256s"]),
            *(GenerationFileRef("raw_financial", reference)
              for reference in manifest["discovery_evidence_sha256s"]),
        })

    def financial_candidate_referenced_files(
        self,
        manifest_sha256: str,
    ) -> frozenset[GenerationFileRef]:
        from thesistrace.data.financial_candidate import (
            FinancialCandidateError,
            FinancialCandidateStore,
        )

        try:
            FinancialCandidateStore(self._root).validate_stored(manifest_sha256)
        except FinancialCandidateError as error:
            raise GenerationStoreError("Financial retained candidate is invalid") from error
        return frozenset(self._financial_referenced_files(manifest_sha256))

    def industry_candidate_referenced_files(
        self,
        manifest_sha256: str,
    ) -> frozenset[GenerationFileRef]:
        reference = self._industry_family_reference(manifest_sha256)
        manifest = self._read_family_manifest(INDUSTRY_FAMILY_SPEC, reference)
        references = {GenerationFileRef("manifest", manifest_sha256)}
        for table in manifest["tables"]:
            if not isinstance(table, Mapping):
                raise GenerationStoreError("Industry retained candidate is invalid")
            table_sha256 = str(table["manifest_sha256"])
            references.add(GenerationFileRef("manifest", table_sha256))
            table_manifest = self._read_manifest(table_sha256)
            objects = table_manifest.get("objects")
            if not isinstance(objects, list):
                raise GenerationStoreError("Industry retained candidate is invalid")
            references.update(
                GenerationFileRef("object", str(item["sha256"]))
                for item in objects
                if isinstance(item, Mapping)
            )
        return frozenset(references)

    def validate_raw_financial_batch(self, sha256: str) -> None:
        from thesistrace.data.financial_collection import (
            FinancialCollectionError,
            RawFinancialBatchStore,
        )

        try:
            RawFinancialBatchStore(self._root).read(sha256)
        except FinancialCollectionError as error:
            raise GenerationStoreError("Financial retained raw batch is invalid") from error

    def validate_raw_industry_batch(self, sha256: str) -> None:
        _require_sha256(sha256)
        try:
            self._files.read(
                self._raw_industry_path(sha256),
                sha256,
                max_byte_count=128 * 1024 * 1024,
            )
        except AddressedFileError as error:
            raise GenerationStoreError("Industry retained raw batch is invalid") from error

    def _financial_referenced_files(
        self,
        manifest_sha256: str,
    ) -> set[GenerationFileRef]:
        references = {GenerationFileRef("manifest", manifest_sha256)}
        manifest = self._read_manifest(manifest_sha256)
        source_collection = manifest.get("source_collection")
        if isinstance(source_collection, Mapping):
            prior_candidate = source_collection.get("prior_candidate_manifest_sha256")
            if isinstance(prior_candidate, str):
                references.add(GenerationFileRef("manifest", prior_candidate))
        source_generation = manifest.get("source_generation_manifest_sha256")
        if isinstance(source_generation, str):
            references.update(self.referenced_files(source_generation))
        tables = manifest.get("tables")
        if isinstance(tables, list):
            for table in tables:
                if not isinstance(table, Mapping):
                    continue
                table_sha256 = str(table.get("manifest_sha256"))
                references.add(GenerationFileRef("manifest", table_sha256))
                table_manifest = self._read_manifest(table_sha256)
                base_sha256 = _financial_base_table_manifest_sha256(table_manifest)
                seen_base_manifests: set[str] = set()
                while base_sha256 is not None:
                    if base_sha256 in seen_base_manifests:
                        raise GenerationStoreError(
                            "Financial retained candidate has a cyclic table base"
                        )
                    seen_base_manifests.add(base_sha256)
                    references.add(GenerationFileRef("manifest", base_sha256))
                    base_manifest = self._read_manifest(base_sha256)
                    base_sha256 = _financial_base_table_manifest_sha256(base_manifest)
                objects = table_manifest.get("objects")
                if isinstance(objects, list):
                    references.update(
                        GenerationFileRef("object", str(item["sha256"]))
                        for item in objects
                        if isinstance(item, Mapping)
                    )
        for key in ("current_raw_evidence", "raw_evidence"):
            evidence = manifest.get(key)
            if not isinstance(evidence, Mapping):
                continue
            index_sha256 = str(evidence.get("manifest_sha256"))
            references.add(GenerationFileRef("manifest", index_sha256))
            index = self._read_manifest(index_sha256)
            chunks = index.get("chunks")
            if isinstance(chunks, list):
                for chunk_reference in chunks:
                    if not isinstance(chunk_reference, Mapping):
                        continue
                    chunk_sha256 = str(chunk_reference["sha256"])
                    references.add(GenerationFileRef("manifest", chunk_sha256))
                    chunk = self._read_manifest(chunk_sha256)
                    entries = chunk.get("entries")
                    if isinstance(entries, list):
                        references.update(
                            GenerationFileRef("raw_financial", str(entry["batch_sha256"]))
                            for entry in entries
                            if isinstance(entry, Mapping)
                        )
        return references

    def inventory(self) -> frozenset[GenerationFileRef]:
        references = {
            GenerationFileRef("manifest", sha256)
            for sha256 in _inventory_sha256(self._root, "manifests", ".json")
        }
        references.update(
            GenerationFileRef("object", sha256)
            for sha256 in _inventory_sha256(self._root, "objects", ".parquet")
        )
        references.update(
            GenerationFileRef("raw_financial", sha256)
            for sha256 in _inventory_sha256(self._root, "financial/raw", ".json")
        )
        references.update(
            GenerationFileRef("raw_industry", sha256)
            for sha256 in _inventory_sha256(self._root, "industry/raw", ".json")
        )
        return frozenset(references)

    def delete_file(self, reference: GenerationFileRef) -> bool:
        if reference.kind == "manifest":
            target = self._manifest_path(reference.sha256)
        elif reference.kind == "object":
            target = self._object_path(reference.sha256)
        elif reference.kind == "raw_financial":
            target = self._raw_financial_path(reference.sha256)
        elif reference.kind == "raw_industry":
            target = self._raw_industry_path(reference.sha256)
        else:
            raise GenerationStoreError("Generation file kind is invalid")
        try:
            return self._files.delete(target)
        except AddressedFileError as error:
            raise GenerationStoreError("Generation file deletion failed or is unsafe") from error

    def _read_family_generation_root(self, manifest_sha256: str) -> dict[str, object]:
        root = self._read_manifest(manifest_sha256)
        if (
            root.get("format") != _FAMILY_GENERATION_FORMAT
            or root.get("version") != _MANIFEST_VERSION
        ):
            raise GenerationStoreError("Family Generation candidate is incompatible")
        expected_keys = {
            "format",
            "version",
            "data_identity",
            "schema_contract",
            "data_through_session",
            "research_sessions",
            "field_availability",
            "families",
            "financial_research_readiness",
            "financial_publication_coordinate",
            "preparation",
        }
        if set(root) not in (expected_keys, {*expected_keys, "industry_publication_coordinate"}):
            raise GenerationStoreError("Family Generation candidate schema is incompatible")
        families = root["families"]
        family_ids = (
            [entry.get("family_id") for entry in families if isinstance(entry, Mapping)]
            if isinstance(families, list)
            else []
        )
        if not _valid_generation_family_ids(family_ids):
            raise GenerationStoreError("Family Generation candidate set is incompatible")
        identity = {
            "schema_contract": root["schema_contract"],
            "data_through_session": root["data_through_session"],
            "research_sessions": root["research_sessions"],
            "field_availability": root["field_availability"],
            "families": families,
            "financial_research_readiness": root["financial_research_readiness"],
        }
        if root["data_identity"] != hashlib.sha256(canonical_json_bytes(identity)).hexdigest():
            raise GenerationStoreError("Family Generation candidate identity is invalid")
        _family_generation_descriptor_from_root(manifest_sha256, root)
        return root

    def _read_family_manifest(
        self,
        family_spec: _DatasetFamilySpec,
        reference: Mapping[str, object],
    ) -> dict[str, object]:
        descriptor = _family_descriptor_from_reference(reference, family_spec)
        content = self._read_addressed(
            self._manifest_path(descriptor.manifest_sha256),
            descriptor.manifest_sha256,
            expected_byte_count=_required_byte_count(
                reference["manifest_byte_count"],
                "Dataset Family manifest",
            ),
            max_byte_count=GENERATION_MANIFEST_MAX_BYTES,
        )
        manifest = _parse_manifest(content)
        if (
            manifest.get("format") != _FAMILY_MANIFEST_FORMAT
            or manifest.get("version") != _MANIFEST_VERSION
            or manifest.get("family_id") != family_spec.family_id
            or manifest.get("schema_contract") != family_spec.schema_contract
            or manifest.get("dataset_coverage") != descriptor.dataset_coverage
            or manifest.get("validation_summary") != descriptor.validation_summary
            or set(manifest)
            != {
                "format",
                "version",
                "family_id",
                "schema_contract",
                "dataset_coverage",
                "validation_summary",
                "tables",
                *({"source_evidence"} if family_spec == DAILY_BASIC_FAMILY_SPEC else ()),
            }
        ):
            raise GenerationStoreError("Dataset Family manifest is incompatible")
        if family_spec == DAILY_BASIC_FAMILY_SPEC:
            _validate_daily_basic_evidence_references(manifest["source_evidence"])
        tables = manifest["tables"]
        if not isinstance(tables, list) or [
            table.get("name") for table in tables if isinstance(table, Mapping)
        ] != list(family_spec.table_names):
            raise GenerationStoreError("Dataset Family table set is incompatible")
        try:
            validate_summary(manifest["validation_summary"], tables)
        except FamilyManifestError as error:
            raise GenerationStoreError(str(error)) from error
        return manifest

    def _read_table_manifest(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
    ) -> dict[str, object]:
        if (
            set(reference)
            != {
                "name",
                "manifest_sha256",
                "manifest_byte_count",
                "row_count",
                "object_count",
            }
            or reference["name"] != spec.name
        ):
            raise GenerationStoreError("Generation table reference is incompatible")
        manifest_sha256 = str(reference["manifest_sha256"])
        content = self._read_addressed(
            self._manifest_path(manifest_sha256),
            manifest_sha256,
            expected_byte_count=_required_byte_count(
                reference["manifest_byte_count"], "Generation table manifest"
            ),
            max_byte_count=GENERATION_MANIFEST_MAX_BYTES,
        )
        manifest = _parse_manifest(content)
        if (
            manifest.get("format") != _TABLE_MANIFEST_FORMAT
            or manifest.get("version") != _MANIFEST_VERSION
            or manifest.get("table") != spec.name
            or manifest.get("writer_contract") != spec.contract.descriptor()
            or manifest.get("partitioning") != spec.partitioning
            or set(manifest)
            != {
                "format",
                "version",
                "table",
                "writer_contract",
                "partitioning",
                "row_count",
                "objects",
            }
        ):
            raise GenerationStoreError("Generation table manifest is incompatible")
        objects = manifest["objects"]
        if not isinstance(objects, list) or reference["object_count"] != len(objects):
            raise GenerationStoreError("Generation table object set is invalid")
        if manifest["row_count"] != reference["row_count"]:
            raise GenerationStoreError("Generation table row count is invalid")
        return manifest

    def _open_table_window(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
        *,
        start_session: str,
    ) -> list[dict[str, object]]:
        if spec.session_field is None:
            raise ValueError("Refresh window requires a session-partitioned table")
        manifest = self._read_table_manifest(spec, reference)
        objects = manifest["objects"]
        assert isinstance(objects, list)
        tables: list[pa.Table] = []
        for ordinal, object_ref in enumerate(objects):
            _validate_object_reference(object_ref, ordinal)
            assert isinstance(object_ref, Mapping)
            last_key = object_ref["last_sort_key"]
            if last_key is None:
                continue
            if not isinstance(last_key, list) or not last_key:
                raise GenerationStoreError("Generation table object boundary is invalid")
            if str(last_key[0]) < start_session:
                continue
            # Keep the window columnar through cross-partition validation, so
            # Python row dictionaries are allocated only once.
            table = self._open_canonical_partition_table(spec, object_ref, ordinal)
            session_column = table[spec.session_field]
            boundary = pa.scalar(start_session).cast(session_column.type)
            selected = table.filter(pc.greater_equal(session_column, boundary))
            tables.append(selected)
            del selected, session_column, table
        try:
            if not tables:
                return []
            window = pa.concat_tables(tables)
            del tables
            window = window.take(pc.sort_indices(
                window, sort_keys=[(key, "ascending") for key in spec.contract.sort_keys],
            ))
            validate_parquet_table(window, spec.contract)
            if spec.name == "daily_basic":
                # Refresh consumers use canonical decimal text. Project in Arrow
                # rather than allocating a full Decimal grid and then copying it.
                for index, field in enumerate(window.schema):
                    if pa.types.is_decimal(field.type):
                        # Arrow's string cast may use scientific notation (0E-10).
                        # Normalize one column at a time with the canonical formatter.
                        values = pa.array(
                            [None if value is None else _daily_basic_decimal_text(value)
                             for value in window[field.name].to_pylist()],
                            type=pa.string(),
                        )
                        window = window.set_column(index, field.name, values)
            rows = []
            for batch in window.to_batches(max_chunksize=4096):
                for row in batch.to_pylist():
                    # These bounded domain labels repeat for every session and
                    # family. Share their strings, not arbitrary financial values.
                    for name in ("session", "session_date", "instrument_id", "state"):
                        value = row.get(name)
                        if isinstance(value, str):
                            row[name] = intern(value)
                    if "instrument_ids" in row:
                        row["instrument_ids"] = [intern(value) for value in row["instrument_ids"]]
                    rows.append(row)
            return rows
        except (ArrowException, ParquetContractError) as error:
            raise GenerationStoreError("Generation refresh window is incompatible") from error

    def _open_table_sessions(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
        *,
        selected_sessions: set[str],
        columns: set[str] | None = None,
        instrument_ids: frozenset[str] | None = None,
    ) -> list[dict[str, object]]:
        if spec.session_field is None:
            raise ValueError("Selected-session read requires a session table")
        manifest = self._read_table_manifest(spec, reference)
        objects = manifest["objects"]
        assert isinstance(objects, list)
        first_session = min(selected_sessions)
        last_session = max(selected_sessions)
        rows: list[dict[str, object]] = []
        for ordinal, object_ref in enumerate(objects):
            _validate_object_reference(object_ref, ordinal)
            assert isinstance(object_ref, Mapping)
            first_key = object_ref["first_sort_key"]
            last_key = object_ref["last_sort_key"]
            if first_key is None or last_key is None:
                continue
            if not isinstance(first_key, list) or not isinstance(last_key, list):
                raise GenerationStoreError("Generation table object boundary is invalid")
            if str(last_key[0]) < first_session or str(first_key[0]) > last_session:
                continue
            partition = self._open_partition_projection(
                spec,
                object_ref,
                ordinal,
                columns=columns,
                instrument_ids=instrument_ids,
            )
            rows.extend(
                row
                for row in partition
                if str(row[spec.session_field]) in selected_sessions
                and (instrument_ids is None or str(row.get("instrument_id", "")) in instrument_ids)
            )
        if columns is not None:
            return sorted(rows, key=lambda row: tuple(row[key] for key in spec.contract.sort_keys))
        try:
            return canonicalize_parquet_rows(rows, spec.contract)
        except ParquetContractError as error:
            raise GenerationStoreError("Market Series rows are incompatible") from error

    def _open_table_sessions_columnar(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
        *,
        selected_sessions: set[str],
        columns: set[str] | None,
        instrument_ids: frozenset[str] | None = None,
    ) -> pa.Table:
        if spec.session_field is None:
            raise ValueError("Selected-session read requires a session table")
        manifest = self._read_table_manifest(spec, reference)
        objects = manifest["objects"]
        assert isinstance(objects, list)
        first_session = min(selected_sessions)
        last_session = max(selected_sessions)
        tables: list[pa.Table] = []
        for ordinal, object_ref in enumerate(objects):
            _validate_object_reference(object_ref, ordinal)
            assert isinstance(object_ref, Mapping)
            first_key = object_ref["first_sort_key"]
            last_key = object_ref["last_sort_key"]
            if first_key is None or last_key is None:
                continue
            if str(last_key[0]) < first_session or str(first_key[0]) > last_session:
                continue
            table = self._open_partition_table(
                spec,
                object_ref,
                ordinal,
                columns=columns,
                instrument_ids=instrument_ids,
            )
            mask = pc.is_in(
                table[spec.session_field],
                value_set=pa.array(sorted(selected_sessions)),
            )
            tables.append(table.filter(mask))
        if not tables:
            raise GenerationStoreError("Columnar Research table has no selected rows")
        table = pa.concat_tables(tables)
        sort_keys = [
            (key, "ascending") for key in spec.contract.sort_keys if key in table.column_names
        ]
        return table.take(pc.sort_indices(table, sort_keys=sort_keys))

    def _open_table_instruments(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
        *,
        instrument_ids: frozenset[str],
        columns: set[str],
    ) -> list[dict[str, object]]:
        if not spec.contract.sort_keys or spec.contract.sort_keys[0] != "instrument_id":
            raise GenerationStoreError("Instrument projection contract is invalid")
        manifest = self._read_table_manifest(spec, reference)
        objects = manifest["objects"]
        assert isinstance(objects, list)
        rows: list[dict[str, object]] = []
        for ordinal, object_ref in enumerate(objects):
            _validate_object_reference(object_ref, ordinal)
            assert isinstance(object_ref, Mapping)
            first_key = object_ref["first_sort_key"]
            last_key = object_ref["last_sort_key"]
            if first_key is None or last_key is None:
                continue
            if not isinstance(first_key, list) or not isinstance(last_key, list):
                raise GenerationStoreError("Generation table object boundary is invalid")
            first_instrument = str(first_key[0])
            last_instrument = str(last_key[0])
            if not any(
                first_instrument <= instrument_id <= last_instrument
                for instrument_id in instrument_ids
            ):
                continue
            rows.extend(
                self._open_partition_projection(
                    spec,
                    object_ref,
                    ordinal,
                    columns=columns,
                    instrument_ids=instrument_ids,
                )
            )
        return sorted(rows, key=lambda row: tuple(row[key] for key in spec.contract.sort_keys))

    def _open_table_instruments_columnar(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
        *,
        instrument_ids: frozenset[str],
        columns: set[str],
    ) -> pa.Table:
        manifest = self._read_table_manifest(spec, reference)
        objects = manifest["objects"]
        assert isinstance(objects, list)
        tables = [
            self._open_partition_table(
                spec,
                object_ref,
                ordinal,
                columns=columns,
                instrument_ids=instrument_ids,
            )
            for ordinal, object_ref in enumerate(objects)
        ]
        if not tables:
            raise GenerationStoreError("Columnar Research instrument table is empty")
        table = pa.concat_tables(tables)
        return table.take(pc.sort_indices(table, sort_keys=[("instrument_id", "ascending")]))

    def _open_partition_projection(
        self,
        spec: _TableSpec,
        object_ref: object,
        ordinal: int,
        *,
        columns: set[str] | None,
        instrument_ids: frozenset[str] | None,
    ) -> list[dict[str, object]]:
        return self._open_partition_table(
            spec,
            object_ref,
            ordinal,
            columns=columns,
            instrument_ids=instrument_ids,
        ).to_pylist()

    def _open_partition_table(
        self,
        spec: _TableSpec,
        object_ref: object,
        ordinal: int,
        *,
        columns: set[str] | None,
        instrument_ids: frozenset[str] | None,
    ) -> pa.Table:
        _validate_object_reference(object_ref, ordinal)
        assert isinstance(object_ref, Mapping)
        sha256 = str(object_ref["sha256"])
        content = self._read_addressed(
            self._object_path(sha256),
            sha256,
            expected_byte_count=_required_byte_count(object_ref["byte_count"], "Generation object"),
            max_byte_count=GENERATION_OBJECT_MAX_BYTES,
        )
        try:
            parquet = pq.ParquetFile(pa.BufferReader(content))
            batches: list[pa.RecordBatch] = []
            projected_columns = None if columns is None else sorted(columns)
            instrument_values = (
                None
                if instrument_ids is None
                else pa.array(sorted(instrument_ids), type=pa.string())
            )
            for batch in parquet.iter_batches(
                batch_size=_COLUMNAR_RECORD_BATCH_ROWS,
                columns=projected_columns,
            ):
                if instrument_values is not None:
                    batch = batch.filter(
                        pc.is_in(batch.column("instrument_id"), value_set=instrument_values)
                    )
                batches.append(batch)
            schema = (
                parquet.schema_arrow
                if projected_columns is None
                else pa.schema([parquet.schema_arrow.field(column) for column in projected_columns])
            )
            table = pa.Table.from_batches(batches, schema=schema)
            record_parquet_scan(
                source="market",
                row_count=table.num_rows,
                column_count=len(table.column_names),
            )
        except (ArrowException, TypeError, ValueError) as error:
            raise GenerationStoreError("Generation object projection is incompatible") from error
        return table

    def _materialize_refresh_table(
        self,
        spec: _TableSpec,
        predecessor_reference: Mapping[str, object],
        *,
        replacement_rows: Iterable[Mapping[str, object]],
        replace_from_session: str,
        rewrite_start_session: str,
        new_calendar: list[str],
    ) -> dict[str, object]:
        assert spec.session_field is not None
        predecessor_manifest = self._read_table_manifest(spec, predecessor_reference)
        predecessor_objects = predecessor_manifest["objects"]
        assert isinstance(predecessor_objects, list)
        preserved_objects: list[dict[str, object]] = []
        by_partition: dict[int, list[dict[str, object]]] = {}
        session_index = {session: index for index, session in enumerate(new_calendar)}

        def retain(row: Mapping[str, object]) -> None:
            session = str(row[spec.session_field])
            if session not in session_index:
                raise GenerationStoreError(f"Canonical {spec.name} session is outside Coverage")
            partition = session_index[session] // GENERATION_SESSION_PARTITION_COUNT
            by_partition.setdefault(partition, []).append(dict(row))

        sparse_daily = spec.allows_sparse_sessions
        rewrite_partition = (
            session_index[rewrite_start_session] // GENERATION_SESSION_PARTITION_COUNT
        )
        for ordinal, object_ref in enumerate(predecessor_objects):
            _validate_object_reference(object_ref, ordinal)
            assert isinstance(object_ref, Mapping)
            if sparse_daily and ordinal < rewrite_partition:
                preserved_objects.append(dict(object_ref))
                continue
            last_key = object_ref["last_sort_key"]
            first_key = object_ref["first_sort_key"]
            if last_key is None or first_key is None:
                continue
            if not isinstance(last_key, list) or not isinstance(first_key, list):
                raise GenerationStoreError("Generation table object boundary is invalid")
            if str(last_key[0]) < rewrite_start_session:
                preserved_objects.append(dict(object_ref))
                continue
            if str(first_key[0]) >= replace_from_session:
                continue
            for row in self._open_partition(spec, object_ref, ordinal):
                if rewrite_start_session <= str(row[spec.session_field]) < replace_from_session:
                    retain(row)
        for row in replacement_rows:
            if str(row[spec.session_field]) >= replace_from_session:
                retain(row)
        objects = preserved_objects
        rewritten_partitions = (
            range(rewrite_partition,
                  (len(new_calendar) + GENERATION_SESSION_PARTITION_COUNT - 1)
                  // GENERATION_SESSION_PARTITION_COUNT)
            if sparse_daily else sorted(by_partition)
        )
        for partition in rewritten_partitions:
            rows = canonicalize_parquet_rows(by_partition.get(partition, []), spec.contract)
            table = pa.Table.from_pylist(rows, schema=spec.contract.schema)
            objects.append(self._materialize_columnar_partition(spec, table, len(objects)))
        for ordinal, object_ref in enumerate(objects):
            object_ref["ordinal"] = ordinal
        row_count = sum(int(object_ref["row_count"]) for object_ref in objects)
        return self._materialize_table_manifest(spec, objects, row_count)

    def _materialize_table(
        self,
        spec: _TableSpec,
        rows: list[dict[str, object]],
        calendar: list[object],
    ) -> dict[str, object]:
        canonical_rows = canonicalize_parquet_rows(rows, spec.contract)
        partitions = _partition_rows(spec, canonical_rows, [str(value) for value in calendar])
        objects = [
            self._materialize_partition(spec, partition, ordinal)
            for ordinal, partition in enumerate(partitions)
        ]
        return self._materialize_table_manifest(spec, objects, len(canonical_rows))

    def _materialize_market_family(
        self,
        family_spec: _DatasetFamilySpec,
        *,
        table_references: Mapping[str, dict[str, object]],
        canonical: Mapping[str, object],
        calendar: list[object],
        source_evidence: Sequence[Mapping[str, str]] = (),
    ) -> dict[str, object]:
        try:
            coverage = build_family_coverage(
                family_spec,
                canonical=canonical,
                calendar=calendar,
            )
        except FamilyManifestError as error:
            raise GenerationStoreError(str(error)) from error
        tables = [table_references[name] for name in family_spec.table_names]
        summary = validation_summary(tables)
        family_manifest = {
            "format": _FAMILY_MANIFEST_FORMAT,
            "version": _MANIFEST_VERSION,
            "family_id": family_spec.family_id,
            "schema_contract": family_spec.schema_contract,
            "dataset_coverage": coverage,
            "validation_summary": summary,
            "tables": tables,
        }
        if family_spec == DAILY_BASIC_FAMILY_SPEC:
            family_manifest["source_evidence"] = sorted(
                (dict(item) for item in source_evidence), key=lambda item: item["sha256"],
            )
        manifest_bytes = _bounded_manifest_bytes(family_manifest)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        self._store_addressed(
            self._manifest_path(manifest_sha256),
            manifest_sha256,
            manifest_bytes,
        )
        return {
            "family_id": family_spec.family_id,
            "schema_contract": family_spec.schema_contract,
            "dataset_coverage": coverage,
            "validation_summary": summary,
            "manifest_sha256": manifest_sha256,
            "manifest_byte_count": len(manifest_bytes),
            "table_names": list(family_spec.table_names),
        }

    def _materialize_partition(
        self,
        spec: _TableSpec,
        partition: list[dict[str, object]],
        ordinal: int,
    ) -> dict[str, object]:
        content = parquet_bytes(partition, spec.contract)
        if len(content) > GENERATION_OBJECT_MAX_BYTES:
            raise GenerationStoreError("Generation object exceeds its byte bound")
        sha256 = hashlib.sha256(content).hexdigest()
        self._store_addressed(self._object_path(sha256), sha256, content)
        first_key, last_key = _partition_boundaries(partition, spec.contract.sort_keys)
        return {
            "ordinal": ordinal,
            "sha256": sha256,
            "byte_count": len(content),
            "row_count": len(partition),
            "first_sort_key": first_key,
            "last_sort_key": last_key,
            "statistics": _partition_statistics(spec, partition),
        }

    def _materialize_columnar_partition(
        self,
        spec: _TableSpec,
        table: pa.Table,
        ordinal: int,
    ) -> dict[str, object]:
        content = parquet_table_bytes(table, spec.contract)
        if len(content) > GENERATION_OBJECT_MAX_BYTES:
            raise GenerationStoreError("Generation object exceeds its byte bound")
        sha256 = hashlib.sha256(content).hexdigest()
        self._store_addressed(self._object_path(sha256), sha256, content)
        first_key = ([_manifest_scalar(table[key][0].as_py()) for key in spec.contract.sort_keys]
                     if table.num_rows else None)
        last_key = [
            _manifest_scalar(table[key][table.num_rows - 1].as_py())
            for key in spec.contract.sort_keys
        ] if table.num_rows else None
        return {
            "ordinal": ordinal,
            "sha256": sha256,
            "byte_count": len(content),
            "row_count": table.num_rows,
            "first_sort_key": first_key,
            "last_sort_key": last_key,
            "statistics": _columnar_partition_statistics(spec, table),
        }

    def _validate_columnar_session_extent(
        self,
        spec: _TableSpec,
        table: pa.Table,
        sessions: tuple[str, ...],
    ) -> None:
        if spec.allows_sparse_sessions:
            if table.schema != spec.contract.schema:
                raise GenerationStoreError(f"Columnar Bootstrap {spec.name} schema is incompatible")
            if not set(table["session"].to_pylist()) <= set(sessions):
                raise GenerationStoreError("Daily basic session extent is incompatible")
            return
        if table.num_rows == 0:
            raise GenerationStoreError(f"Columnar Bootstrap {spec.name} partition is empty")
        if table.schema != spec.contract.schema or spec.session_field is None:
            raise GenerationStoreError(f"Columnar Bootstrap {spec.name} schema is incompatible")
        minimum = pc.min(table[spec.session_field]).as_py()
        maximum = pc.max(table[spec.session_field]).as_py()
        minimum_text = minimum.isoformat() if isinstance(minimum, date) else str(minimum)
        maximum_text = maximum.isoformat() if isinstance(maximum, date) else str(maximum)
        if minimum_text != sessions[0] or maximum_text != sessions[-1]:
            raise GenerationStoreError(
                f"Columnar Bootstrap {spec.name} session extent is incompatible"
            )

    def _materialize_table_manifest(
        self,
        spec: _TableSpec,
        objects: list[dict[str, object]],
        row_count: int,
    ) -> dict[str, object]:
        table_manifest = {
            "format": _TABLE_MANIFEST_FORMAT,
            "version": _MANIFEST_VERSION,
            "table": spec.name,
            "writer_contract": spec.contract.descriptor(),
            "partitioning": spec.partitioning,
            "row_count": row_count,
            "objects": objects,
        }
        manifest_bytes = _bounded_manifest_bytes(table_manifest)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        self._store_addressed(self._manifest_path(manifest_sha256), manifest_sha256, manifest_bytes)
        return {
            "name": spec.name,
            "manifest_sha256": manifest_sha256,
            "manifest_byte_count": len(manifest_bytes),
            "row_count": row_count,
            "object_count": len(objects),
        }

    def _open_table(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
        calendar: list[str] | None,
    ) -> list[dict[str, object]]:
        manifest = self._read_table_manifest(spec, reference)
        objects = manifest["objects"]
        assert isinstance(objects, list)
        rows: list[dict[str, object]] = []
        partitions: list[list[dict[str, object]]] = []
        for ordinal, object_ref in enumerate(objects):
            partition = self._open_partition(spec, object_ref, ordinal)
            partitions.append(partition)
            rows.extend(partition)
        try:
            if rows != canonicalize_parquet_rows(rows, spec.contract):
                raise GenerationStoreError("Generation table ordering is invalid")
        except ParquetContractError as error:
            raise GenerationStoreError("Generation table ordering is invalid") from error
        if manifest["row_count"] != len(rows) or reference["row_count"] != len(rows):
            raise GenerationStoreError("Generation table row count is invalid")
        partition_calendar = calendar
        if spec.name == "research_calendar":
            partition_calendar = [str(row["session"]) for row in rows]
        if partition_calendar is None or partitions != _partition_rows(
            spec, rows, partition_calendar
        ):
            raise GenerationStoreError("Generation table partitioning is invalid")
        return rows

    def _open_partition(
        self,
        spec: _TableSpec,
        object_ref: object,
        ordinal: int,
    ) -> list[dict[str, object]]:
        table = self._open_canonical_partition_table(spec, object_ref, ordinal)
        try:
            return canonicalize_parquet_rows(table.to_pylist(), spec.contract)
        except (ParquetContractError, TypeError, ValueError) as error:
            raise GenerationStoreError("Generation object is incompatible") from error

    def _open_canonical_partition_table(
        self,
        spec: _TableSpec,
        object_ref: object,
        ordinal: int,
    ) -> pa.Table:
        _validate_object_reference(object_ref, ordinal)
        assert isinstance(object_ref, Mapping)
        sha256 = str(object_ref["sha256"])
        content = self._read_addressed(
            self._object_path(sha256),
            sha256,
            expected_byte_count=_required_byte_count(object_ref["byte_count"], "Generation object"),
            max_byte_count=GENERATION_OBJECT_MAX_BYTES,
        )
        try:
            table = pq.read_table(pa.BufferReader(content))
            record_parquet_scan(
                source="market",
                row_count=table.num_rows,
                column_count=len(table.column_names),
            )
            if table.schema != spec.contract.schema:
                raise GenerationStoreError("Generation object schema is incompatible")
            canonical_content = (
                parquet_bytes(table.to_pylist(), spec.contract)
                if any(pa.types.is_list(field.type) for field in table.schema)
                else parquet_table_bytes(table, spec.contract)
            )
            if canonical_content != content:
                raise GenerationStoreError("Generation object encoding is non-canonical")
        except (ArrowException, ParquetContractError, TypeError, ValueError) as error:
            raise GenerationStoreError("Generation object is incompatible") from error
        first_key = (
            [_manifest_scalar(table[key][0].as_py()) for key in spec.contract.sort_keys]
            if table.num_rows
            else None
        )
        last_key = (
            [
                _manifest_scalar(table[key][table.num_rows - 1].as_py())
                for key in spec.contract.sort_keys
            ]
            if table.num_rows
            else None
        )
        if (
            object_ref["row_count"] != table.num_rows
            or object_ref["first_sort_key"] != first_key
            or object_ref["last_sort_key"] != last_key
        ):
            raise GenerationStoreError("Generation object boundaries are invalid")
        return table

    def _read_manifest(self, sha256: str) -> dict[str, object]:
        return _parse_manifest(
            self._read_addressed(
                self._manifest_path(sha256),
                sha256,
                max_byte_count=GENERATION_MANIFEST_MAX_BYTES,
            )
        )

    def _read_addressed(
        self,
        path: Path,
        expected_sha256: str,
        *,
        expected_byte_count: int | None = None,
        max_byte_count: int | None = None,
    ) -> bytes:
        _require_sha256(expected_sha256)
        try:
            return self._files.read(
                path,
                expected_sha256,
                expected_byte_count=expected_byte_count,
                max_byte_count=max_byte_count,
            )
        except AddressedFileError as error:
            raise GenerationStoreError(f"Generation object or manifest {error}") from error

    def _store_addressed(self, target: Path, sha256: str, content: bytes) -> None:
        try:
            self._files.store(target, sha256, content)
        except AddressedFileError as error:
            raise GenerationStoreError(f"Generation {error}") from error

    def _manifest_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "manifests" / "sha256" / sha256[:2] / f"{sha256}.json"

    def _object_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "objects" / "sha256" / sha256[:2] / f"{sha256}.parquet"

    def _raw_financial_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "financial" / "raw" / "sha256" / sha256[:2] / f"{sha256}.json"

    def _raw_industry_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "industry" / "raw" / "sha256" / sha256[:2] / f"{sha256}.json"


def _inventory_sha256(root: Path, directory: str, suffix: str) -> tuple[str, ...]:
    base = root / directory / "sha256"
    try:
        with os.scandir(base) as entries:
            prefixes = sorted(entries, key=lambda entry: entry.name)
    except FileNotFoundError:
        return ()
    except OSError as error:
        raise GenerationStoreError("Generation inventory is unreadable or unsafe") from error
    sha256s: list[str] = []
    for prefix in prefixes:
        if (
            len(prefix.name) != 2
            or any(character not in "0123456789abcdef" for character in prefix.name)
            or not prefix.is_dir(follow_symlinks=False)
        ):
            raise GenerationStoreError("Generation inventory is unreadable or unsafe")
        try:
            with os.scandir(prefix.path) as directory_entries:
                entries = sorted(directory_entries, key=lambda entry: entry.name)
        except OSError as error:
            raise GenerationStoreError("Generation inventory is unreadable or unsafe") from error
        for entry in entries:
            if entry.name.startswith(".candidate-"):
                continue
            if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(suffix):
                raise GenerationStoreError("Generation inventory is unreadable or unsafe")
            sha256 = entry.name[: -len(suffix)]
            _require_sha256(sha256)
            if sha256[:2] != prefix.name:
                raise GenerationStoreError("Generation inventory is unreadable or unsafe")
            sha256s.append(sha256)
    return tuple(sha256s)


def _non_financial_specs_for_canonical(
    canonical: Mapping[str, object],
) -> tuple[_DatasetFamilySpec, ...]:
    family_ids = {spec.family_id for spec in CORE_MARKET_FAMILY_SPECS}
    if "industry_membership" in canonical:
        family_ids.add(INDUSTRY_FAMILY_SPEC.family_id)
    if "daily_basic_sessions" in canonical:
        family_ids.add(DAILY_BASIC_FAMILY_SPEC.family_id)
    return ordered_non_financial_specs(frozenset(family_ids))


def _family_reference(
    root: Mapping[str, object],
    family_id: str,
) -> Mapping[str, object] | None:
    references = root.get("families")
    if not isinstance(references, list):
        raise GenerationStoreError("Family Generation candidate set is incompatible")
    matches = [
        reference
        for reference in references
        if isinstance(reference, Mapping) and reference.get("family_id") == family_id
    ]
    if len(matches) > 1:
        raise GenerationStoreError("Family Generation candidate set is incompatible")
    return None if not matches else matches[0]


def _family_spec_for_reference(
    reference: Mapping[str, object],
) -> _DatasetFamilySpec:
    selected = get_family_spec(str(reference.get("family_id")))
    if selected is None:
        raise GenerationStoreError("Dataset Family reference is incompatible")
    return selected


def _field_family_bindings(
    field_bindings: Mapping[str, str], neutralization: str,
) -> dict[str, dict[str, str]]:
    from thesistrace.data.dependencies import resolve_data_dependencies

    try:
        dependencies = resolve_data_dependencies(
            field_ids=frozenset(field_bindings), neutralization=neutralization,
        )
    except ValueError as error:
        raise GenerationStoreError("Research Series field binding is unsupported") from error
    return {
        family_id: {field_id: field_bindings[field_id] for field_id in sorted(field_ids)}
        for family_id, field_ids in dependencies.field_ids_by_family.items()
    }


def _generation_family_order() -> tuple[str, ...]:
    return (
        *(spec.family_id for spec in NON_FINANCIAL_FAMILY_SPECS),
        "equity.financial_pit",
        "equity.financial_indicator",
    )


def _valid_generation_family_ids(family_ids: list[object]) -> bool:
    if not all(isinstance(family_id, str) for family_id in family_ids):
        return False
    selected = set(family_ids)
    required = {spec.family_id for spec in CORE_MARKET_FAMILY_SPECS}
    order = _generation_family_order()
    return (
        required <= selected <= set(order)
        and family_ids == [family_id for family_id in order if family_id in selected]
    )


def _replace_family_references(
    references: Sequence[Mapping[str, object]],
    replacements: Mapping[str, Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Replace only owned families, retaining every other validated reference."""
    combined = {str(reference["family_id"]): reference for reference in references}
    if len(combined) != len(references) or any(
        family_id != reference.get("family_id")
        for family_id, reference in replacements.items()
    ):
        raise GenerationStoreError("Family Generation candidate set is incompatible")
    combined.update(replacements)
    order = _generation_family_order()
    family_ids = [family_id for family_id in order if family_id in combined]
    if set(combined) != set(family_ids) or not _valid_generation_family_ids(family_ids):
        raise GenerationStoreError("Family Generation candidate set is incompatible")
    return [combined[family_id] for family_id in family_ids]


def _family_generation_descriptor_from_root(
    manifest_sha256: str,
    root: Mapping[str, object],
) -> MountedFamilyGenerationDescriptor:
    _require_sha256(manifest_sha256)
    if root.get("schema_contract") != "canonical-research":
        raise GenerationStoreError("Family Generation schema contract is incompatible")
    data_identity = root.get("data_identity")
    _require_sha256(data_identity)
    try:
        data_through_session = date.fromisoformat(
            str(root["data_through_session"])
        ).isoformat()
    except (KeyError, TypeError, ValueError) as error:
        raise GenerationStoreError(
            "Family Generation data-through session is invalid"
        ) from error
    research_sessions = root.get("research_sessions")
    if (
        not isinstance(research_sessions, list)
        or not research_sessions
        or not all(isinstance(value, str) for value in research_sessions)
        or research_sessions != sorted(set(research_sessions))
        or research_sessions[-1] != data_through_session
    ):
        raise GenerationStoreError("Family Generation Research Sessions are invalid")
    try:
        normalized_sessions = tuple(
            date.fromisoformat(value).isoformat() for value in research_sessions
        )
    except ValueError as error:
        raise GenerationStoreError(
            "Family Generation Research Sessions are invalid"
        ) from error
    field_availability = root.get("field_availability")
    if (
        not isinstance(field_availability, list)
        or not all(isinstance(value, str) and value for value in field_availability)
        or field_availability != sorted(set(field_availability))
    ):
        raise GenerationStoreError("Family Generation field availability is invalid")
    try:
        preparation = validate_preparation(root.get("preparation"))
    except FamilyManifestError as error:
        raise GenerationStoreError(str(error)) from error
    family_references = root.get("families")
    family_ids = (
        [
            entry.get("family_id")
            for entry in family_references
            if isinstance(entry, Mapping)
        ]
        if isinstance(family_references, list)
        else []
    )
    if not isinstance(family_references, list) or not _valid_generation_family_ids(
        family_ids
    ):
        raise GenerationStoreError("Family Generation candidate set is incompatible")
    families: list[MountedDatasetFamilyDescriptor] = []
    financial_candidate: str | None = None
    financial_coverage: Mapping[str, object] | None = None
    for reference in family_references:
        if not isinstance(reference, Mapping):
            raise GenerationStoreError("Dataset Family reference is incompatible")
        if reference.get("family_id") == "equity.financial_indicator":
            indicator_family = _indicator_family_descriptor_from_reference(reference)
            if not set(reference["field_ids"]) <= set(field_availability):
                raise GenerationStoreError(
                    "Indicator field declarations differ from Generation"
                )
            coverage = indicator_family.dataset_coverage
            if (
                coverage["start"] < normalized_sessions[0]
                or coverage["end"] > normalized_sessions[-1]
            ):
                raise GenerationStoreError("Indicator Coverage exceeds Market Coverage")
            families.append(indicator_family)
            continue
        if reference.get("family_id") == "equity.financial_pit":
            financial_family = _financial_family_descriptor_from_reference(reference)
            financial_candidate = financial_family.manifest_sha256
            financial_coverage = financial_family.dataset_coverage
            families.append(financial_family)
            continue
        families.append(
            _family_descriptor_from_reference(
                reference,
                _family_spec_for_reference(reference),
            )
        )
    readiness = root.get("financial_research_readiness")
    coordinate = root.get("financial_publication_coordinate")
    industry_coordinate = root.get("industry_publication_coordinate")
    if financial_candidate is None:
        readiness_valid = readiness is None and coordinate is None
    else:
        from thesistrace.data.fields import FINANCIAL_FIELDS

        declared_financial_fields = sorted(
            set(field_availability) & {field.field_id for field in FINANCIAL_FIELDS}
        )
        readiness_valid = (
            financial_coverage is not None
            and bool(declared_financial_fields)
            and readiness
            == _financial_readiness_declaration(
                financial_coverage, field_ids=declared_financial_fields
            )
            and isinstance(coordinate, str)
            and len(coordinate) == 64
            and all(character in "0123456789abcdef" for character in coordinate)
        )
    if not readiness_valid:
        raise GenerationStoreError("Financial Research Readiness is incompatible")
    if industry_coordinate is not None:
        _require_sha256(industry_coordinate)
    try:
        validate_generation_coverages(
            tuple(
                family
                for family in families
                if family.family_id
                not in {"equity.financial_pit", "equity.financial_indicator"}
            ),
            data_through_session=data_through_session,
        )
    except FamilyManifestError as error:
        raise GenerationStoreError(str(error)) from error
    if families[0].dataset_coverage != {
        "kind": "research-session-range",
        "start": normalized_sessions[0],
        "end": normalized_sessions[-1],
        "session_count": len(normalized_sessions),
    }:
        raise GenerationStoreError(
            "Family Generation Research Sessions are incompatible"
        )
    return MountedFamilyGenerationDescriptor(
        manifest_sha256=manifest_sha256,
        data_identity=str(data_identity),
        schema_contract="canonical-research",
        data_through_session=data_through_session,
        research_sessions=normalized_sessions,
        field_availability=tuple(field_availability),
        preparation=preparation,
        families=tuple(families),
        financial_candidate_manifest_sha256=(
            None if financial_candidate is None else str(financial_candidate)
        ),
        financial_research_readiness=(None if readiness is None else dict(readiness)),
        financial_publication_coordinate=(
            None if coordinate is None else str(coordinate)
        ),
        industry_publication_coordinate=(
            None if industry_coordinate is None else str(industry_coordinate)
        ),
    )


def _financial_readiness_declaration(
    coverage: Mapping[str, object],
    *,
    field_ids: Sequence[str],
) -> dict[str, object]:
    common = {
        "field_ids": sorted(field_ids),
        "series_reader": "session-aligned-financial-fields",
        "research_run": "composite-alpha",
        "daily_track": "batch-incremental-composite-alpha",
        "performance_evidence": _FINANCIAL_PERFORMANCE_EVIDENCE,
    }
    if coverage.get("kind") == "financial-observation-range":
        return {
            "status": "ready",
            **common,
        }
    if coverage.get("kind") != "financial-announcement-observation-range":
        raise GenerationStoreError("Financial Research Readiness is incompatible")
    status = str(coverage.get("readiness_status"))
    attempted = str(coverage.get("discovery_attempted_through_session"))
    complete = str(coverage.get("discovery_complete_through_session"))
    pending_count = coverage.get("pending_instrument_count")
    gap_count = coverage.get("discovery_gap_count")
    earliest = coverage.get("earliest_unresolved_date")
    if (
        status not in {"ready", "ready_with_pending", "ready_with_gaps"}
        or not isinstance(pending_count, int)
        or isinstance(pending_count, bool)
        or pending_count < 0
        or not isinstance(gap_count, int)
        or isinstance(gap_count, bool)
        or gap_count < 0
    ):
        raise GenerationStoreError("Financial Research Readiness is incompatible")
    try:
        attempted = date.fromisoformat(attempted).isoformat()
        complete = date.fromisoformat(complete).isoformat()
        normalized_earliest = (
            None if earliest is None else date.fromisoformat(str(earliest)).isoformat()
        )
    except ValueError as error:
        raise GenerationStoreError("Financial Research Readiness is incompatible") from error
    return {
        "status": status,
        "attempted_through_session": attempted,
        "complete_through_session": complete,
        "pending_instrument_count": pending_count,
        "discovery_gap_count": gap_count,
        "earliest_unresolved_date": normalized_earliest,
        **common,
    }


def _family_descriptor_from_reference(
    reference: Mapping[str, object],
    family_spec: _DatasetFamilySpec,
) -> MountedDatasetFamilyDescriptor:
    if set(reference) != {
        "family_id",
        "schema_contract",
        "dataset_coverage",
        "validation_summary",
        "manifest_sha256",
        "manifest_byte_count",
        "table_names",
    }:
        raise GenerationStoreError("Dataset Family reference is incompatible")
    table_names = reference["table_names"]
    coverage = reference["dataset_coverage"]
    if (
        reference["family_id"] != family_spec.family_id
        or reference["schema_contract"] != family_spec.schema_contract
        or not isinstance(table_names, list)
        or table_names != list(family_spec.table_names)
        or not isinstance(coverage, Mapping)
    ):
        raise GenerationStoreError("Dataset Family reference is incompatible")
    try:
        validated_coverage = validate_family_coverage(family_spec, coverage)
    except FamilyManifestError as error:
        raise GenerationStoreError(str(error)) from error
    summary = reference["validation_summary"]
    if (
        not isinstance(summary, Mapping)
        or set(summary) != {"status", "table_count", "row_count", "object_count"}
        or summary.get("status") != "validated"
        or any(
            not isinstance(summary.get(key), int)
            or isinstance(summary.get(key), bool)
            or int(summary[key]) < 0
            for key in ("table_count", "row_count", "object_count")
        )
    ):
        raise GenerationStoreError("Dataset Family validation summary is incompatible")
    manifest_sha256 = reference["manifest_sha256"]
    _require_sha256(manifest_sha256)
    _required_byte_count(reference["manifest_byte_count"], "Dataset Family manifest")
    return MountedDatasetFamilyDescriptor(
        family_id=family_spec.family_id,
        schema_contract=family_spec.schema_contract,
        dataset_coverage=validated_coverage,
        validation_summary={
            "status": "validated",
            "table_count": int(summary["table_count"]),
            "row_count": int(summary["row_count"]),
            "object_count": int(summary["object_count"]),
        },
        manifest_sha256=str(manifest_sha256),
        table_names=tuple(table_names),
    )


def _financial_family_descriptor_from_reference(
    reference: Mapping[str, object],
) -> MountedDatasetFamilyDescriptor:
    expected_keys = {
        "family_id",
        "schema_contract",
        "dataset_coverage",
        "validation_summary",
        "manifest_sha256",
        "manifest_byte_count",
        "table_names",
    }
    coverage = reference.get("dataset_coverage")
    table_names = reference.get("table_names")
    if (
        set(reference) != expected_keys
        or reference.get("family_id") != "equity.financial_pit"
        or reference.get("schema_contract") != "financial-pit-wide-v1"
        or table_names
        != [
            "income_statement_versions",
            "balance_sheet_versions",
            "cash_flow_statement_versions",
        ]
        or not isinstance(coverage, Mapping)
        or coverage.get("kind")
        not in {
            "financial-observation-range",
            "financial-announcement-observation-range",
        }
    ):
        raise GenerationStoreError("Financial Dataset Family reference is incompatible")
    summary = reference.get("validation_summary")
    if (
        not isinstance(summary, Mapping)
        or set(summary) != {"status", "table_count", "row_count", "object_count"}
        or summary.get("status") != "validated"
        or any(
            isinstance(summary.get(key), bool)
            or not isinstance(summary.get(key), int)
            or int(summary[key]) < 0
            for key in ("table_count", "row_count", "object_count")
        )
    ):
        raise GenerationStoreError("Financial Dataset Family summary is incompatible")
    manifest_sha256 = reference.get("manifest_sha256")
    _require_sha256(manifest_sha256)
    _required_byte_count(reference.get("manifest_byte_count"), "Financial Family manifest")
    return MountedDatasetFamilyDescriptor(
        family_id="equity.financial_pit",
        schema_contract="financial-pit-wide-v1",
        dataset_coverage=dict(coverage),
        validation_summary=dict(summary),
        manifest_sha256=str(manifest_sha256),
        table_names=tuple(str(value) for value in table_names),
    )


def _validate_object_reference(object_ref: object, ordinal: int) -> None:
    if (
        not isinstance(object_ref, Mapping)
        or set(object_ref)
        != {
            "ordinal",
            "sha256",
            "byte_count",
            "row_count",
            "first_sort_key",
            "last_sort_key",
            "statistics",
        }
        or object_ref["ordinal"] != ordinal
    ):
        raise GenerationStoreError("Generation table object reference is invalid")
    _require_sha256(object_ref["sha256"])
    _required_byte_count(object_ref["byte_count"], "Generation object")
    row_count = object_ref["row_count"]
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
        raise GenerationStoreError("Generation object row count is invalid")
    if not isinstance(object_ref["statistics"], Mapping):
        raise GenerationStoreError("Generation object statistics are invalid")


def _normalize_canonical(canonical: Mapping[str, object]) -> dict[str, object]:
    required = {
        "schema_version",
        "research_calendar",
        "instruments",
        "prices",
        "trading_states",
        "price_limits",
        "base_pool",
        "liquidity_universes",
        "field_catalog",
    }
    optional = {"industry_membership", "daily_basic", "daily_basic_sessions"}
    if not required <= set(canonical) or set(canonical) - required - optional:
        raise GenerationStoreError("Canonical Generation table set is incompatible")
    if ("daily_basic" in canonical) != ("daily_basic_sessions" in canonical):
        raise GenerationStoreError("Canonical Generation table set is incompatible")
    normalized_rows: dict[str, list[dict[str, object]]] = {}
    for spec in _TABLE_SPECS:
        if spec.name in {"industry_membership", "daily_basic", "daily_basic_sessions"} and (
            spec.name not in canonical
        ):
            continue
        try:
            normalized_rows[spec.name] = canonicalize_parquet_rows(
                _table_rows(canonical, spec.name),
                spec.contract,
            )
        except ParquetContractError as error:
            raise GenerationStoreError(f"Canonical table is incompatible: {spec.name}") from error
    return _canonical_from_rows(normalized_rows)


def _validate_columnar_candidate_semantics(
    tables: Mapping[str, pa.Table],
    sessions: tuple[str, ...],
    static: Mapping[str, object],
) -> None:
    required = {
        spec.name
        for spec in MARKET_CANDIDATE_TABLE_SPECS
        if spec.session_field is not None and spec.name != "research_calendar"
        and spec.name not in {"daily_basic", "daily_basic_sessions"}
    }
    if not required <= set(tables) or set(tables) - required - {
        "daily_basic", "daily_basic_sessions",
    } or (("daily_basic" in tables) != ("daily_basic_sessions" in tables)):
        raise GenerationStoreError("Dataset Family table set is incomplete")
    instruments = static.get("instruments")
    if not isinstance(instruments, list) or any(
        not isinstance(row, Mapping) for row in instruments
    ):
        raise GenerationStoreError("Canonical instrument identities are invalid")
    instrument_ids = {str(row["instrument_id"]) for row in instruments}
    if not instrument_ids or len(instrument_ids) != len(instruments):
        raise GenerationStoreError("Canonical instrument identities are invalid")

    if "daily_basic" in tables:
        observations = tables["daily_basic"]
        collected = tables["daily_basic_sessions"]["session"].to_pylist()
        keys = _columnar_position_keys(observations, "session")
        if (
            collected != sorted(set(collected)) or not set(collected) <= set(sessions)
            or not set(observations["session"].to_pylist()) <= set(collected)
            or not set(observations["instrument_id"].to_pylist()) <= instrument_ids
            or pc.count_distinct(keys).as_py() != observations.num_rows
        ):
            raise GenerationStoreError("Daily basic observed coordinates are invalid")

    base = tables["base_pool"]
    if base["session"].to_pylist() != list(sessions):
        raise GenerationStoreError("Canonical Base Pool coverage is invalid")
    base_members = base["instrument_ids"].to_pylist()
    if any(
        members != sorted(set(members)) or not set(members) <= instrument_ids
        for members in base_members
    ):
        raise GenerationStoreError("Canonical Base Pool membership is invalid")
    parent_indices = pc.list_parent_indices(base["instrument_ids"])
    base_position_table = pa.table(
        {
            "session": pc.take(base["session"], parent_indices),
            "instrument_id": pc.list_flatten(base["instrument_ids"]),
        }
    )
    states = tables["trading_states"]
    if not states["session"].equals(base_position_table["session"]) or not states[
        "instrument_id"
    ].equals(base_position_table["instrument_id"]):
        raise GenerationStoreError("Canonical Trading State coverage is invalid")
    allowed_states = pa.array(
        (
            "normal",
            "full_session_suspension",
            "partial_opening_suspension",
            "after_open_suspension",
            "data_unavailable",
        )
    )
    if pc.all(pc.is_in(states["state"], value_set=allowed_states)).as_py() is not True:
        raise GenerationStoreError("Canonical Trading State coverage is invalid")

    state_keys = _columnar_position_keys(states, "session")
    required_mask = pc.invert(
        pc.is_in(
            states["state"],
            value_set=pa.array(("full_session_suspension", "data_unavailable")),
        )
    )
    allowed_mask = pc.not_equal(states["state"], "full_session_suspension")
    required_keys = pc.filter(state_keys, required_mask)
    allowed_keys = pc.filter(state_keys, allowed_mask)
    prices = tables["eod_prices"]
    price_keys = _columnar_position_keys(prices, "session_date")
    if not _columnar_keys_cover(price_keys, required_keys, allowed_keys):
        raise GenerationStoreError("Canonical Price coverage is invalid")

    factors = tables["adjustment_factors"]
    factor_keys = _columnar_position_keys(factors, "session_date")
    if not factor_keys.equals(price_keys) or not factors["source_adjustment_factor"].equals(
        prices["adjustment_scale"]
    ):
        raise GenerationStoreError("Market Dataset Families are not synchronized")
    positive_factors = pc.greater(factors["source_adjustment_factor"], Decimal(0))
    if pc.all(positive_factors).as_py() is not True:
        raise GenerationStoreError("Canonical Price adjustment factor is invalid")
    for field in ("open", "high", "low", "close"):
        raw = pc.cast(prices[f"{field}_raw"], pa.float64())
        factor = pc.cast(prices["adjustment_scale"], pa.float64())
        adjusted = pc.cast(prices[f"{field}_adj"], pa.float64())
        difference = pc.abs(pc.subtract(pc.multiply(raw, factor), adjusted))
        if pc.all(pc.less_equal(difference, 0.00000001)).as_py() is not True:
            raise GenerationStoreError("Canonical adjusted Price derivation is inconsistent")

    limits = tables["price_limits"]
    limit_keys = _columnar_position_keys(limits, "session")
    if not _columnar_keys_cover(limit_keys, required_keys, price_keys):
        raise GenerationStoreError("Canonical Price Limit coverage is invalid")

    liquidity = tables["liquidity_universes"]
    expected_names = ("top1000", "top2000", "top300", "top3000")
    expected_sessions = [session for session in sessions for _name in expected_names]
    expected_universes = [name for _session in sessions for name in expected_names]
    if (
        liquidity["session"].to_pylist() != expected_sessions
        or liquidity["universe"].to_pylist() != expected_universes
        or pc.all(pc.equal(liquidity["status"], "available")).as_py() is not True
    ):
        raise GenerationStoreError("Canonical Liquidity Universe coverage is invalid")
    liquidity_members = liquidity["instrument_ids"].to_pylist()
    maximum_by_name = {"top300": 300, "top1000": 1000, "top2000": 2000, "top3000": 3000}
    for session_index, base_ids in enumerate(base_members):
        by_name = {
            name: liquidity_members[session_index * len(expected_names) + offset]
            for offset, name in enumerate(expected_names)
        }
        prior: list[str] = []
        for name in ("top300", "top1000", "top2000", "top3000"):
            members = by_name[name]
            if (
                len(members) > maximum_by_name[name]
                or len(members) != len(set(members))
                or not set(members) <= set(base_ids)
                or prior != members[: len(prior)]
            ):
                raise GenerationStoreError("Canonical Liquidity Universe membership is invalid")
            prior = members


def _release_arrow_partition_memory() -> None:
    pa.default_memory_pool().release_unused()


def _columnar_position_keys(table: pa.Table, session_field: str) -> pa.Array:
    sessions = pc.cast(table[session_field], pa.string())
    return pc.binary_join_element_wise(sessions, table["instrument_id"], "|")


def _columnar_keys_cover(
    actual: pa.Array | pa.ChunkedArray,
    required: pa.Array | pa.ChunkedArray,
    allowed: pa.Array | pa.ChunkedArray,
) -> bool:
    return (
        pc.all(pc.is_in(required, value_set=actual)).as_py() is True
        and pc.all(pc.is_in(actual, value_set=allowed)).as_py() is True
    )


def _consume_refresh_prices(candidate_tables: dict[str, list[dict[str, object]]]) -> None:
    """Transfer owned prices early, before loading additional wide families."""
    factors = {
        (str(row["session_date"]), str(row["instrument_id"])): row["source_adjustment_factor"]
        for row in candidate_tables.pop("adjustment_factors")
    }
    states = {
        (str(row["session"]), str(row["instrument_id"])): row["state"]
        for row in candidate_tables["trading_states"]
    }
    prices = candidate_tables.pop("eod_prices")
    for row in prices:
        position = (intern(str(row["session_date"])), intern(str(row["instrument_id"])))
        factor = factors.get(position)
        state = states.get(position)
        if (
            factor is None
            or state is None
            or Decimal(str(row["adjustment_scale"])) != Decimal(str(factor))
        ):
            raise GenerationStoreError("Market Dataset Families are not synchronized")
        projected = {
            "session": position[0],
            "instrument_id": position[1],
            "open_raw": _decimal_text(row["open_raw"], 4),
            "high_raw": _decimal_text(row["high_raw"], 4),
            "low_raw": _decimal_text(row["low_raw"], 4),
            "close_raw": _decimal_text(row["close_raw"], 4),
            "pre_close_raw": _decimal_text(row["pre_close_reference_raw"], 4),
            "change_raw": _decimal_text(row["price_change_raw"], 4),
            "pct_change_raw": _decimal_text(
                Decimal(str(row["pct_change_ratio"])) * Decimal(100), 6
            ),
            "volume_shares": str(row["volume_shares"]),
            "turnover_cny": _decimal_text(row["turnover_amount_cny"], 2),
            "adjustment_factor": _decimal_text(factor, 6),
            "open_adj": _decimal_text(row["open_adj"], 8),
            "high_adj": _decimal_text(row["high_adj"], 8),
            "low_adj": _decimal_text(row["low_adj"], 8),
            "close_adj": _decimal_text(row["close_adj"], 8),
            "trading_state": str(state),
        }
        row.clear()
        row.update(projected)
    del factors, states
    candidate_tables["prices"] = prices


def _validate_refresh_tables(
    candidate_tables: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    required = {
        table_name for family in CORE_MARKET_FAMILY_SPECS for table_name in family.table_names
    } - {"eod_prices", "adjustment_factors"} | {"prices"}
    if set(candidate_tables) not in (
        required,
        {*required, "industry_membership"},
        {*required, "daily_basic", "daily_basic_sessions"},
        {*required, "industry_membership", "daily_basic", "daily_basic_sessions"},
    ):
        raise GenerationStoreError("Dataset Family table set is incomplete")
    daily_basic = candidate_tables.pop("daily_basic", None)
    canonical = _canonical_from_rows(candidate_tables)
    if daily_basic is not None:
        canonical["daily_basic"] = daily_basic
        canonical["daily_basic_sessions"] = candidate_tables["daily_basic_sessions"]
    _validate_generation(canonical)
    return canonical


def _validate_candidate_projection(
    descriptor: MountedFamilyGenerationDescriptor,
    canonical: Mapping[str, object],
) -> None:
    calendar = canonical["research_calendar"]
    field_catalog = canonical["field_catalog"]
    assert isinstance(calendar, list)
    assert isinstance(field_catalog, list)
    actual_fields = {str(row["field_id"]) for row in field_catalog}
    for family in descriptor.families:
        actual_fields.update(family.field_ids)
    if descriptor.financial_research_readiness is not None:
        actual_fields.update(descriptor.financial_research_readiness["field_ids"])
    if (
        descriptor.data_through_session != str(calendar[-1])
        or descriptor.research_sessions != tuple(str(session) for session in calendar)
        or descriptor.field_availability != tuple(sorted(actual_fields))
    ):
        raise GenerationStoreError("Family Generation root projection is incompatible")
    for family in descriptor.families:
        spec = get_family_spec(family.family_id)
        if spec is None:
            continue
        if spec == INDUSTRY_FAMILY_SPEC:
            rows = canonical.get("industry_membership")
            if not isinstance(rows, list) or family.dataset_coverage.get("membership_count") != len(
                rows
            ):
                raise GenerationStoreError("Dataset Family Coverage projection is incompatible")
            continue
        try:
            actual_coverage = build_family_coverage(
                spec,
                canonical=canonical,
                calendar=calendar,
            )
        except FamilyManifestError as error:
            raise GenerationStoreError(str(error)) from error
        if family.dataset_coverage != actual_coverage:
            raise GenerationStoreError("Dataset Family Coverage projection is incompatible")


def _decimal_text(value: object, scale: int) -> str:
    quantum = Decimal(1).scaleb(-scale)
    return format(Decimal(str(value)).quantize(quantum), "f")


def _table_rows(canonical: Mapping[str, object], table: str) -> list[dict[str, object]]:
    return list(_iter_table_rows(canonical, table))


def _iter_table_rows(
    canonical: Mapping[str, object],
    table: str,
) -> Iterable[dict[str, object]]:
    if table == "daily_basic":
        for row in canonical[table]:
            yield {name: value if name in {"session", "instrument_id"} or value is None
                   else Decimal(str(value)) for name, value in row.items()}
        return
    if table == "research_calendar":
        for session in canonical[table]:
            yield {"session": str(session)}
        return
    if table == "eod_prices":
        for row in _iter_table_rows(canonical, "prices"):
            yield {
                "session_date": date.fromisoformat(str(row["session"])),
                "instrument_id": str(row["instrument_id"]),
                "open_raw": Decimal(str(row["open_raw"])),
                "high_raw": Decimal(str(row["high_raw"])),
                "low_raw": Decimal(str(row["low_raw"])),
                "close_raw": Decimal(str(row["close_raw"])),
                "pre_close_reference_raw": Decimal(str(row["pre_close_raw"])),
                "price_change_raw": Decimal(str(row["change_raw"])),
                "pct_change_ratio": Decimal(str(row["pct_change_raw"])) / Decimal(100),
                "volume_shares": int(str(row["volume_shares"])),
                "turnover_amount_cny": Decimal(str(row["turnover_cny"])),
                "adjustment_scale": Decimal(str(row["adjustment_factor"])),
                "open_adj": Decimal(str(row["open_adj"])),
                "high_adj": Decimal(str(row["high_adj"])),
                "low_adj": Decimal(str(row["low_adj"])),
                "close_adj": Decimal(str(row["close_adj"])),
            }
        return
    if table == "adjustment_factors":
        for row in _iter_table_rows(canonical, "prices"):
            yield {
                "session_date": date.fromisoformat(str(row["session"])),
                "instrument_id": str(row["instrument_id"]),
                "source_adjustment_factor": Decimal(str(row["adjustment_factor"])),
            }
        return
    if table == "liquidity_universes":
        universes = canonical[table]
        if not isinstance(universes, Mapping):
            raise GenerationStoreError("Canonical Liquidity Universes are incompatible")
        for universe, rows in universes.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                yield {"universe": universe, **dict(row)}
        return
    rows = canonical[table]
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise GenerationStoreError(f"Canonical table is incompatible: {table}")
    for source in rows:
        row = dict(source)
        if table == "base_pool":
            instrument_ids = row.get("instrument_ids")
            if isinstance(instrument_ids, list):
                row["instrument_ids"] = sorted(str(item) for item in instrument_ids)
        yield row


def _canonical_from_rows(tables: Mapping[str, list[dict[str, object]]]) -> dict[str, object]:
    universes: dict[str, list[dict[str, object]]] = {name: [] for name in _UNIVERSE_NAMES}
    for row in tables["liquidity_universes"]:
        value = dict(row)
        universe = str(value.pop("universe"))
        if universe not in universes:
            raise GenerationStoreError("Canonical Liquidity Universe identity is incompatible")
        universes[universe].append(value)
    return {
        "schema_version": "canonical-eod",
        "research_calendar": [row["session"] for row in tables["research_calendar"]],
        "instruments": tables["instruments"],
        "prices": tables["prices"],
        "trading_states": tables["trading_states"],
        "price_limits": tables["price_limits"],
        "base_pool": tables["base_pool"],
        "liquidity_universes": universes,
        "field_catalog": tables["field_catalog"],
        **({
            "daily_basic": [{name: value if name in {"session", "instrument_id"} or value is None
                             else _daily_basic_decimal_text(value) for name, value in row.items()}
                            for row in tables["daily_basic"]],
            "daily_basic_sessions": tables["daily_basic_sessions"],
        } if "daily_basic" in tables else {}),
        **(
            {"industry_membership": tables["industry_membership"]}
            if "industry_membership" in tables
            else {}
        ),
    }


def _daily_basic_decimal_text(value: Decimal) -> str:
    # Match source normalization without Decimal.normalize's context rounding.
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _partition_rows(
    spec: _TableSpec,
    rows: list[dict[str, object]],
    calendar: list[str],
) -> list[list[dict[str, object]]]:
    if spec.session_field is None:
        return [
            rows[start : start + GENERATION_ROW_PARTITION_COUNT]
            for start in range(0, len(rows), GENERATION_ROW_PARTITION_COUNT)
        ] or [[]]
    session_index = {session: index for index, session in enumerate(calendar)}
    by_partition: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        session = str(row[spec.session_field])
        if session not in session_index:
            raise GenerationStoreError(f"Canonical {spec.name} session is outside Coverage")
        ordinal = session_index[session] // GENERATION_SESSION_PARTITION_COUNT
        by_partition.setdefault(ordinal, []).append(row)
    ordinals = (
        range((len(calendar) + GENERATION_SESSION_PARTITION_COUNT - 1)
              // GENERATION_SESSION_PARTITION_COUNT)
        if spec.allows_sparse_sessions else sorted(by_partition)
    )
    return [
        canonicalize_parquet_rows(by_partition.get(ordinal, []), spec.contract)
        for ordinal in ordinals
    ] or [[]]


def _partition_boundaries(
    rows: list[dict[str, object]],
    sort_keys: tuple[str, ...],
) -> tuple[list[object] | None, list[object] | None]:
    if not rows:
        return None, None
    return (
        [_manifest_scalar(rows[0][key]) for key in sort_keys],
        [_manifest_scalar(rows[-1][key]) for key in sort_keys],
    )


def _partition_statistics(
    spec: _TableSpec,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    if spec.name != "liquidity_universes":
        return {}
    by_session: dict[str, dict[str, int]] = {}
    for row in rows:
        members = row["instrument_ids"]
        if not isinstance(members, list):
            raise GenerationStoreError("Liquidity Universe statistics are invalid")
        by_session.setdefault(str(row["session"]), {})[str(row["universe"])] = len(
            set(map(str, members))
        )
    try:
        values = [
            [session, *(by_session[session][name] for name in _UNIVERSE_NAMES)]
            for session in sorted(by_session)
        ]
    except KeyError as error:
        raise GenerationStoreError("Liquidity Universe statistics are invalid") from error
    return {"universe_cardinalities": values}


def _columnar_partition_statistics(
    spec: _TableSpec,
    table: pa.Table,
) -> dict[str, object]:
    if spec.name != "liquidity_universes":
        return {}
    return _partition_statistics(spec, table.to_pylist())


def _manifest_scalar(value: object) -> object:
    if isinstance(value, (date, Decimal)):
        return str(value)
    return value


def _validate_daily_basic_evidence_references(evidence: object) -> None:
    if not isinstance(evidence, list):
        raise GenerationStoreError("Daily basic source evidence is invalid")
    seen: set[str] = set()
    for item in evidence:
        if (
            not isinstance(item, dict) or set(item) != {"collection_key", "path", "sha256"}
            or not all(isinstance(value, str) and value for value in item.values())
        ):
            raise GenerationStoreError("Daily basic source evidence reference is invalid")
        _require_sha256(item["sha256"])
        expected_path = str(daily_basic_evidence_path(item["collection_key"], item["sha256"]))
        if item["path"] != expected_path or item["sha256"] in seen:
            raise GenerationStoreError("Daily basic source evidence address is invalid")
        seen.add(item["sha256"])


def _preparation(
    prepared_at: datetime,
    source_name: str,
    source_lineage: Mapping[str, object],
) -> dict[str, str]:
    normalized_source = source_name.strip()
    if not normalized_source or prepared_at.tzinfo is None:
        raise GenerationStoreError("Generation preparation metadata is invalid")
    lineage_bytes = canonical_json_bytes(source_lineage)
    return {
        "prepared_at": prepared_at.astimezone(UTC).isoformat(),
        "source_name": normalized_source,
        "source_lineage_sha256": hashlib.sha256(lineage_bytes).hexdigest(),
    }


def _bounded_manifest_bytes(value: Mapping[str, object]) -> bytes:
    content = canonical_json_bytes(value)
    if len(content) > GENERATION_MANIFEST_MAX_BYTES:
        raise GenerationStoreError("Generation manifest exceeds its byte bound")
    return content


def _parse_manifest(content: bytes) -> dict[str, object]:
    if len(content) > GENERATION_MANIFEST_MAX_BYTES:
        raise GenerationStoreError("Generation manifest exceeds its byte bound")
    try:
        value = json.loads(content)
    except (TypeError, ValueError) as error:
        raise GenerationStoreError("Generation manifest is incompatible") from error
    if not isinstance(value, dict) or canonical_json_bytes(value) != content:
        raise GenerationStoreError("Generation manifest is non-canonical or incompatible")
    return value


def _require_sha256(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GenerationStoreError("Generation identity is incompatible")


def _validate_generation(canonical: Mapping[str, object]) -> None:
    try:
        validate_canonical_generation(canonical)
    except GenerationValidationError as error:
        raise GenerationStoreError(str(error)) from error


def _required_byte_count(value: object, subject: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GenerationStoreError(f"{subject} byte count is invalid")
    return value


def _financial_base_table_manifest_sha256(
    manifest: Mapping[str, object],
) -> str | None:
    partitioning = manifest.get("partitioning")
    if not isinstance(partitioning, Mapping) or partitioning.get("kind") != (
        "immutable-base-with-delta-objects"
    ):
        return None
    value = partitioning.get("base_manifest_sha256")
    _require_sha256(value)
    return str(value)


__all__ = (
    "GENERATION_MANIFEST_MAX_BYTES",
    "GENERATION_SESSION_PARTITION_COUNT",
    "GenerationStoreError",
    "GenerationFileRef",
    "MountedDatasetFamilyDescriptor",
    "MountedFamilyGenerationDescriptor",
    "MountedGenerationAdmission",
    "MountedGenerationStore",
)


def _indicator_family_descriptor_from_reference(
    reference: Mapping[str, object],
) -> MountedDatasetFamilyDescriptor:
    from thesistrace.data.fields import FINANCIAL_INDICATOR_FIELDS

    if (
        set(reference)
        != {
            "family_id",
            "schema_contract",
            "dataset_coverage",
            "validation_summary",
            "manifest_sha256",
            "manifest_byte_count",
            "table_names",
            "field_ids",
        }
        or reference["family_id"] != "equity.financial_indicator"
        or reference["schema_contract"] != "financial-indicator-wide"
        or reference["table_names"] != ["financial_indicator_versions"]
    ):
        raise GenerationStoreError("Indicator family reference is incompatible")
    fields = reference["field_ids"]
    if (
        not isinstance(fields, list)
        or not fields
        or fields != sorted(set(fields))
        or not set(fields) <= {field.field_id for field in FINANCIAL_INDICATOR_FIELDS}
    ):
        raise GenerationStoreError("Indicator field declaration is incompatible")
    coverage = reference["dataset_coverage"]
    if (
        not isinstance(coverage, dict)
        or set(coverage)
        != {"kind", "start", "end", "revision_coverage", "instrument_count",
            "pending_instrument_count", "readiness_status", "complete_through_session"}
        or coverage["kind"] != "financial-indicator-observation-range"
        or coverage["revision_coverage"]
        != "announcement-aligned-with-observed-revisions"
        or type(coverage["instrument_count"]) is not int
        or coverage["instrument_count"] < 1
        or type(coverage["pending_instrument_count"]) is not int
        or not 0 <= coverage["pending_instrument_count"] <= coverage["instrument_count"]
        or coverage["readiness_status"] != (
            "ready_with_pending" if coverage["pending_instrument_count"] else "ready"
        )
    ):
        raise GenerationStoreError("Indicator coverage is incompatible")
    if date.fromisoformat(coverage["start"]) > date.fromisoformat(coverage["end"]):
        raise GenerationStoreError("Indicator coverage dates are invalid")
    complete = coverage["complete_through_session"]
    if (
        (not coverage["pending_instrument_count"] and complete != coverage["end"])
        or (complete is not None and not
            date.fromisoformat(coverage["start"]) <= date.fromisoformat(complete)
            <= date.fromisoformat(coverage["end"]))
    ):
        raise GenerationStoreError("Indicator complete coverage is invalid")
    summary = reference["validation_summary"]
    if (
        not isinstance(summary, dict)
        or set(summary) != {"status", "table_count", "row_count", "object_count"}
        or summary["status"] != "validated"
        or summary["table_count"] != 1
        or any(
            type(summary[key]) is not int or summary[key] < 0
            for key in ("row_count", "object_count")
        )
    ):
        raise GenerationStoreError("Indicator validation summary is incompatible")
    _require_sha256(reference["manifest_sha256"])
    _required_byte_count(reference["manifest_byte_count"], "Indicator Family manifest")
    return MountedDatasetFamilyDescriptor(
        family_id="equity.financial_indicator",
        schema_contract="financial-indicator-wide",
        dataset_coverage=coverage,
        validation_summary=summary,
        manifest_sha256=reference["manifest_sha256"],
        table_names=("financial_indicator_versions",),
        field_ids=tuple(fields),
    )

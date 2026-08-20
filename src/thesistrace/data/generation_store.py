from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.data.generation_family import (
    CORE_MARKET_FAMILY_SPECS,
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
)
from thesistrace.data.validation import validate_bootstrap_batch
from thesistrace.publication.serialization import (
    ParquetContractError,
    canonical_json_bytes,
    canonicalize_parquet_rows,
    parquet_bytes,
    parquet_table_bytes,
)
from thesistrace.research_series import AlignedResearchData

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
            if spec.name != "industry_membership" or spec.name in normalized
        }
        family_references = [
            self._materialize_market_family(
                family_spec,
                table_references=table_references,
                canonical=normalized,
                calendar=calendar,
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
        if set(static) not in (
            required_static,
            {*required_static, "industry_membership"},
        ):
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
        )
        table_references: dict[str, dict[str, object]] = {}
        for spec in MARKET_CANDIDATE_TABLE_SPECS:
            if spec in session_specs:
                continue
            if spec.name == "industry_membership" and spec.name not in static:
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

    def validate_generation(
        self,
        manifest_sha256: str,
    ) -> MountedFamilyGenerationDescriptor:
        root = self._read_family_generation_root(manifest_sha256)
        references = root["families"]
        assert isinstance(references, list)
        table_references: dict[str, Mapping[str, object]] = {}
        for reference in references:
            if not isinstance(reference, Mapping):
                raise GenerationStoreError("Dataset Family reference is incompatible")
            if reference.get("family_id") == "equity.financial_pit":
                continue
            family_spec = _family_spec_for_reference(reference)
            family_manifest = self._read_family_manifest(family_spec, reference)
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
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        if descriptor.financial_candidate_manifest_sha256 is not None:
            from thesistrace.data.financial_candidate import (
                FinancialCandidateError,
                FinancialCandidateStore,
            )

            financial_store = FinancialCandidateStore(self._root)
            try:
                financial = financial_store.validate(descriptor.financial_candidate_manifest_sha256)
                expected_reference = financial_store.family_reference(
                    descriptor.financial_candidate_manifest_sha256
                )
            except FinancialCandidateError as error:
                raise GenerationStoreError("Financial Dataset Family is invalid") from error
            financial_reference = references[-1]
            if not isinstance(financial_reference, Mapping) or dict(financial_reference) != (
                expected_reference
            ):
                raise GenerationStoreError(
                    "Financial Dataset Family reference does not match its manifest"
                )
            if financial.observation_through_session > descriptor.data_through_session:
                raise GenerationStoreError("Financial candidate exceeds Market Coverage")
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
        if actual not in (required, {*required, "industry_membership"}):
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
        for manifest in session_manifests.values():
            objects = manifest["objects"]
            if not isinstance(objects, list) or len(objects) != partition_count:
                raise GenerationStoreError("Generation table partitioning is invalid")

        opened_row_counts = {name: 0 for name in session_manifests}
        for ordinal in range(partition_count):
            start = ordinal * GENERATION_SESSION_PARTITION_COUNT
            block_calendar = calendar[start : start + GENERATION_SESSION_PARTITION_COUNT]
            block_tables: dict[str, pa.Table] = {}
            for name, manifest in session_manifests.items():
                spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[name]
                objects = manifest["objects"]
                assert isinstance(objects, list)
                table = self._open_canonical_partition_table(spec, objects[ordinal], ordinal)
                opened_row_counts[name] += table.num_rows
                self._validate_columnar_session_extent(spec, table, tuple(block_calendar))
                block_tables[name] = table
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
        from thesistrace.data.fields import FINANCIAL_FIELDS
        from thesistrace.data.financial_candidate import FinancialCandidateStore

        market = self.validate_generation(market_generation_manifest_sha256)
        financial_store = FinancialCandidateStore(self._root)
        financial = financial_store.validate_against_market_generation(
            financial_candidate_manifest_sha256,
            market_generation_manifest_sha256,
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
        market_families = [
            reference
            for reference in root["families"]
            if isinstance(reference, Mapping)
            and reference.get("family_id") != "equity.financial_pit"
        ]
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
            "families": [
                *market_families,
                financial_store.family_reference(financial_candidate_manifest_sha256),
            ],
            "financial_research_readiness": _financial_readiness_declaration(),
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
        return self.validate_generation(sha256)

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
        non_financial = {
            str(reference["family_id"]): dict(reference)
            for reference in root["families"]
            if isinstance(reference, Mapping)
            and reference.get("family_id") != "equity.financial_pit"
            and reference.get("family_id") != INDUSTRY_FAMILY_SPEC.family_id
        }
        non_financial[INDUSTRY_FAMILY_SPEC.family_id] = candidate_reference
        family_references = [
            non_financial[spec.family_id]
            for spec in ordered_non_financial_specs(frozenset(non_financial))
        ]
        financial_reference = _family_reference(root, "equity.financial_pit")
        if financial_reference is not None:
            family_references.append(dict(financial_reference))
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
        return self.validate_generation(sha256)

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
        if neutralization == "industry":
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
    ) -> MountedMarketSeries:
        """Resolve one storage-independent market/financial calculation slice."""
        from thesistrace.data.fields import FINANCIAL_FIELDS, MARKET_FIELDS
        from thesistrace.data.financial_candidate import (
            FinancialCandidateError,
            FinancialCandidateStore,
        )
        from thesistrace.data.financial_series import (
            FinancialSeriesError,
            FinancialSeriesResolver,
        )

        market_field_ids = {field.field_id for field in MARKET_FIELDS}
        financial_field_ids = {field.field_id for field in FINANCIAL_FIELDS}
        unknown = set(field_bindings) - market_field_ids - financial_field_ids
        if unknown:
            raise GenerationStoreError("Composite Series field binding is unsupported")
        market_bindings = {
            field_id: evaluation_name
            for field_id, evaluation_name in field_bindings.items()
            if field_id in market_field_ids
        }
        financial_bindings = {
            field_id: evaluation_name
            for field_id, evaluation_name in field_bindings.items()
            if field_id in financial_field_ids
        }
        market = self.read_market_slice(
            manifest_sha256,
            sessions=sessions,
            universe_name=universe_name,
            neutralization=neutralization,
            field_bindings=market_bindings,
        )
        if not financial_bindings:
            return market
        financial_manifest = market.generation.financial_candidate_manifest_sha256
        if financial_manifest is None:
            raise GenerationStoreError("Composite Series lacks Financial Data")
        try:
            financial_values = FinancialSeriesResolver(FinancialCandidateStore(self._root)).resolve(
                manifest_sha256=financial_manifest,
                field_ids=tuple(financial_bindings),
                sessions=tuple(sessions),
                instrument_ids=tuple(sorted(market.research_data.instruments)),
            )
        except (FinancialCandidateError, FinancialSeriesError) as error:
            raise GenerationStoreError(str(error)) from error
        return MountedMarketSeries(
            generation=market.generation,
            research_data=replace(
                market.research_data,
                fields={**market.research_data.fields, **financial_values},
            ),
        )

    def read_columnar_slice(
        self,
        manifest_sha256: str,
        *,
        sessions: list[str],
        universe_name: str,
        neutralization: str,
        field_bindings: Mapping[str, str],
        fact_instrument_ids: frozenset[str],
    ):
        from thesistrace.data.columnar_series import ColumnarResearchData
        from thesistrace.data.fields import FINANCIAL_FIELDS, MARKET_FIELDS
        from thesistrace.data.financial_candidate import FinancialCandidateStore
        from thesistrace.data.financial_series import FinancialSeriesResolver

        if not sessions or sessions != sorted(set(sessions)):
            raise GenerationStoreError("Columnar Research sessions are invalid")
        if universe_name not in _UNIVERSE_NAMES:
            raise GenerationStoreError("Columnar Research Universe is invalid")
        if neutralization not in {"none", "industry"}:
            raise GenerationStoreError("Columnar Research Neutralization is invalid")
        market_field_ids = {field.field_id for field in MARKET_FIELDS}
        financial_field_ids = {field.field_id for field in FINANCIAL_FIELDS}
        unknown = set(field_bindings) - market_field_ids - financial_field_ids
        if unknown:
            raise GenerationStoreError("Columnar Research field binding is unsupported")
        market_bindings = {
            field_id: evaluation_name
            for field_id, evaluation_name in field_bindings.items()
            if field_id in market_field_ids
        }
        financial_bindings = tuple(
            field_id for field_id in field_bindings if field_id in financial_field_ids
        )
        requested_columns = market_field_columns(market_bindings)
        root = self._read_family_generation_root(manifest_sha256)
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        if any(session not in descriptor.research_sessions for session in sessions):
            raise GenerationStoreError("Columnar Research sessions are outside Coverage")
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
        if neutralization == "industry":
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
        financial_values = None
        if financial_bindings:
            financial_manifest = descriptor.financial_candidate_manifest_sha256
            if financial_manifest is None:
                raise GenerationStoreError("Columnar Research lacks Financial Data")
            financial_values = FinancialSeriesResolver(
                FinancialCandidateStore(self._root)
            ).resolve_table(
                manifest_sha256=financial_manifest,
                field_ids=financial_bindings,
                sessions=tuple(sessions),
                instrument_ids=tuple(sorted(instrument_ids)),
            )
        return ColumnarResearchData(
            sessions=tuple(sessions),
            _instruments=tables["instruments"],
            _eod_prices=tables["eod_prices"],
            _universes=universes,
            _trading_states=tables["trading_states"],
            _price_limits=tables["price_limits"],
            _industries=industries,
            _financial_values=financial_values,
            _field_columns={
                **market_field_column_bindings(market_bindings),
                **{field_id: field_id for field_id in financial_bindings},
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
        if descriptor.financial_candidate_manifest_sha256 is not None:
            try:
                financial_family = next(
                    family
                    for family in descriptor.families
                    if family.family_id == "equity.financial_pit"
                )
                value = financial_family.dataset_coverage["observation_through_session"]
                financial_through = date.fromisoformat(str(value)).isoformat()
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
        canonical = _validate_candidate_semantics(candidate_tables)
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
        normalized = _normalize_canonical(replacement_canonical)
        _validate_generation(normalized)
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

        table_references: dict[str, dict[str, object]] = {}
        for family_spec in CORE_MARKET_FAMILY_SPECS:
            for table_name in family_spec.table_names:
                spec, predecessor_reference = self._family_table_reference(
                    predecessor_root,
                    family_spec.family_id,
                    table_name,
                )
                rows = _table_rows(normalized, table_name)
                table_references[table_name] = (
                    self._materialize_table(spec, rows, new_calendar)
                    if spec.session_field is None
                    else self._materialize_refresh_table(
                        spec,
                        predecessor_reference,
                        replacement_rows=rows,
                        replace_from_session=replace_from_session,
                        rewrite_start_session=rewrite_start_session,
                        new_calendar=new_calendar,
                    )
                )

        refreshed_family_references = {
            family_spec.family_id: self._materialize_market_family(
                family_spec,
                table_references=table_references,
                canonical=normalized,
                calendar=new_calendar,
            )
            for family_spec in CORE_MARKET_FAMILY_SPECS
        }
        predecessor_industry_reference = _family_reference(
            predecessor_root,
            INDUSTRY_FAMILY_SPEC.family_id,
        )
        if predecessor_industry_reference is not None:
            refreshed_family_references[INDUSTRY_FAMILY_SPEC.family_id] = dict(
                predecessor_industry_reference
            )
        family_references = [
            refreshed_family_references[spec.family_id]
            for spec in ordered_non_financial_specs(frozenset(refreshed_family_references))
        ]
        field_availability = tuple(
            sorted(str(row["field_id"]) for row in normalized["field_catalog"])
        )
        identity = {
            "schema_contract": "canonical-research",
            "data_through_session": new_calendar[-1],
            "research_sessions": list(new_calendar),
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
        financial = FinancialCandidateStore(self._root).validate_against_market_generation(
            prior_candidate,
            market_generation.manifest_sha256,
        )
        return self.compose_financial_candidate(
            market_generation.manifest_sha256,
            financial.manifest_sha256,
            prepared_at=prepared_at,
            publication_coordinate=str(predecessor_root["financial_publication_coordinate"]),
        )

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

    def financial_candidate_referenced_files(
        self,
        manifest_sha256: str,
    ) -> frozenset[GenerationFileRef]:
        from thesistrace.data.financial_candidate import (
            FinancialCandidateError,
            FinancialCandidateStore,
        )

        try:
            FinancialCandidateStore(self._root).validate(manifest_sha256)
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
            }
        ):
            raise GenerationStoreError("Dataset Family manifest is incompatible")
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
        rows: list[dict[str, object]] = []
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
            rows.extend(
                row
                for row in self._open_partition(spec, object_ref, ordinal)
                if str(row[spec.session_field]) >= start_session
            )
        try:
            return canonicalize_parquet_rows(rows, spec.contract)
        except ParquetContractError as error:
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
        replacement_rows: list[dict[str, object]],
        replace_from_session: str,
        rewrite_start_session: str,
        new_calendar: list[str],
    ) -> dict[str, object]:
        assert spec.session_field is not None
        predecessor_manifest = self._read_table_manifest(spec, predecessor_reference)
        predecessor_objects = predecessor_manifest["objects"]
        assert isinstance(predecessor_objects, list)
        preserved_objects: list[dict[str, object]] = []
        prefix_rows: list[dict[str, object]] = []
        for ordinal, object_ref in enumerate(predecessor_objects):
            _validate_object_reference(object_ref, ordinal)
            assert isinstance(object_ref, Mapping)
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
            prefix_rows.extend(
                row
                for row in self._open_partition(spec, object_ref, ordinal)
                if rewrite_start_session <= str(row[spec.session_field]) < replace_from_session
            )
        affected_rows = [
            *prefix_rows,
            *(
                row
                for row in replacement_rows
                if str(row[spec.session_field]) >= replace_from_session
            ),
        ]
        canonical_rows = canonicalize_parquet_rows(affected_rows, spec.contract)
        session_index = {session: index for index, session in enumerate(new_calendar)}
        by_partition: dict[int, list[dict[str, object]]] = {}
        for row in canonical_rows:
            session = str(row[spec.session_field])
            if session not in session_index:
                raise GenerationStoreError(f"Canonical {spec.name} session is outside Coverage")
            partition = session_index[session] // GENERATION_SESSION_PARTITION_COUNT
            by_partition.setdefault(partition, []).append(row)
        objects = preserved_objects
        for partition in sorted(by_partition):
            rows = canonicalize_parquet_rows(by_partition[partition], spec.contract)
            objects.append(self._materialize_partition(spec, rows, len(objects)))
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
        first_key = [_manifest_scalar(table[key][0].as_py()) for key in spec.contract.sort_keys]
        last_key = [
            _manifest_scalar(table[key][table.num_rows - 1].as_py())
            for key in spec.contract.sort_keys
        ]
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


def _valid_generation_family_ids(family_ids: list[object]) -> bool:
    core_ids = {spec.family_id for spec in CORE_MARKET_FAMILY_SPECS}
    without_industry = [
        spec.family_id for spec in NON_FINANCIAL_FAMILY_SPECS if spec.family_id in core_ids
    ]
    with_industry = [spec.family_id for spec in NON_FINANCIAL_FAMILY_SPECS]
    return family_ids in (
        without_industry,
        [*without_industry, "equity.financial_pit"],
        with_industry,
        [*with_industry, "equity.financial_pit"],
    )


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
        data_through_session = date.fromisoformat(str(root["data_through_session"])).isoformat()
    except (KeyError, TypeError, ValueError) as error:
        raise GenerationStoreError("Family Generation data-through session is invalid") from error
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
        raise GenerationStoreError("Family Generation Research Sessions are invalid") from error
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
        [entry.get("family_id") for entry in family_references if isinstance(entry, Mapping)]
        if isinstance(family_references, list)
        else []
    )
    if not isinstance(family_references, list) or not _valid_generation_family_ids(family_ids):
        raise GenerationStoreError("Family Generation candidate set is incompatible")
    families: list[MountedDatasetFamilyDescriptor] = []
    financial_candidate: str | None = None
    for reference in family_references:
        if not isinstance(reference, Mapping):
            raise GenerationStoreError("Dataset Family reference is incompatible")
        if reference.get("family_id") == "equity.financial_pit":
            financial_family = _financial_family_descriptor_from_reference(reference)
            financial_candidate = financial_family.manifest_sha256
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
        readiness_valid = (
            readiness == _financial_readiness_declaration()
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
            tuple(family for family in families if family.family_id != "equity.financial_pit"),
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
        raise GenerationStoreError("Family Generation Research Sessions are incompatible")
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
        financial_publication_coordinate=(None if coordinate is None else str(coordinate)),
        industry_publication_coordinate=(
            None if industry_coordinate is None else str(industry_coordinate)
        ),
    )


def _financial_readiness_declaration() -> dict[str, object]:
    from thesistrace.data.fields import FINANCIAL_FIELDS

    return {
        "status": "ready",
        "field_ids": sorted(field.field_id for field in FINANCIAL_FIELDS),
        "series_reader": "session-aligned-financial-fields",
        "research_run": "composite-alpha",
        "daily_track": "batch-incremental-composite-alpha",
        "performance_evidence": _FINANCIAL_PERFORMANCE_EVIDENCE,
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
        or coverage.get("kind") != "financial-observation-range"
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
    if set(canonical) not in (required, {*required, "industry_membership"}):
        raise GenerationStoreError("Canonical Generation table set is incompatible")
    normalized_rows: dict[str, list[dict[str, object]]] = {}
    for spec in _TABLE_SPECS:
        if spec.name == "industry_membership" and spec.name not in canonical:
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
    }
    if set(tables) != required:
        raise GenerationStoreError("Dataset Family table set is incomplete")
    instruments = static.get("instruments")
    if not isinstance(instruments, list) or any(
        not isinstance(row, Mapping) for row in instruments
    ):
        raise GenerationStoreError("Canonical instrument identities are invalid")
    instrument_ids = {str(row["instrument_id"]) for row in instruments}
    if not instrument_ids or len(instrument_ids) != len(instruments):
        raise GenerationStoreError("Canonical instrument identities are invalid")

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


def _validate_candidate_semantics(
    candidate_tables: Mapping[str, list[dict[str, object]]],
) -> dict[str, object]:
    required = {
        table_name for family in CORE_MARKET_FAMILY_SPECS for table_name in family.table_names
    }
    if set(candidate_tables) not in (
        required,
        {*required, "industry_membership"},
    ):
        raise GenerationStoreError("Dataset Family table set is incomplete")
    factors = {
        (str(row["session_date"]), str(row["instrument_id"])): row["source_adjustment_factor"]
        for row in candidate_tables["adjustment_factors"]
    }
    states = {
        (str(row["session"]), str(row["instrument_id"])): row["state"]
        for row in candidate_tables["trading_states"]
    }
    prices: list[dict[str, object]] = []
    for row in candidate_tables["eod_prices"]:
        position = (str(row["session_date"]), str(row["instrument_id"]))
        factor = factors.get(position)
        state = states.get(position)
        if (
            factor is None
            or state is None
            or Decimal(str(row["adjustment_scale"])) != Decimal(str(factor))
        ):
            raise GenerationStoreError("Market Dataset Families are not synchronized")
        prices.append(
            {
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
        )
    legacy_tables = {
        name: rows
        for name, rows in candidate_tables.items()
        if name not in {"eod_prices", "adjustment_factors"}
    }
    legacy_tables["prices"] = prices
    canonical = _canonical_from_rows(legacy_tables)
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
    if descriptor.financial_candidate_manifest_sha256 is not None:
        from thesistrace.data.fields import FINANCIAL_FIELDS

        actual_fields.update(field.field_id for field in FINANCIAL_FIELDS)
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
    if table == "research_calendar":
        return [{"session": str(session)} for session in canonical[table]]
    if table == "eod_prices":
        return [
            {
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
            for row in _table_rows(canonical, "prices")
        ]
    if table == "adjustment_factors":
        return [
            {
                "session_date": date.fromisoformat(str(row["session"])),
                "instrument_id": str(row["instrument_id"]),
                "source_adjustment_factor": Decimal(str(row["adjustment_factor"])),
            }
            for row in _table_rows(canonical, "prices")
        ]
    if table == "liquidity_universes":
        universes = canonical[table]
        if not isinstance(universes, Mapping):
            raise GenerationStoreError("Canonical Liquidity Universes are incompatible")
        result: list[dict[str, object]] = []
        for universe, rows in universes.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                value = {"universe": universe, **dict(row)}
                result.append(value)
        return result
    rows = canonical[table]
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise GenerationStoreError(f"Canonical table is incompatible: {table}")
    result = [dict(row) for row in rows]
    if table == "base_pool":
        for row in result:
            instrument_ids = row.get("instrument_ids")
            if isinstance(instrument_ids, list):
                row["instrument_ids"] = sorted(str(item) for item in instrument_ids)
    return result


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
        **(
            {"industry_membership": tables["industry_membership"]}
            if "industry_membership" in tables
            else {}
        ),
    }


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
    return [
        canonicalize_parquet_rows(by_partition[ordinal], spec.contract)
        for ordinal in sorted(by_partition)
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

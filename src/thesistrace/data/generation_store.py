from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.data.generation_family import (
    MARKET_FAMILY_SPECS,
    FamilyManifestError,
    MountedDatasetFamilyDescriptor,
    MountedFamilyGenerationDescriptor,
    build_family_coverage,
    validate_family_coverage,
    validate_preparation,
    validate_summary,
    validate_synchronized_coverages,
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
from thesistrace.data.market_series import (
    MarketSeriesError,
    align_market_research_data,
    market_field_columns,
)
from thesistrace.publication.serialization import (
    ParquetContractError,
    canonical_json_bytes,
    canonicalize_parquet_rows,
    parquet_bytes,
)
from thesistrace.research_series import AlignedResearchData

_FAMILY_GENERATION_FORMAT = "thesistrace-family-generation"
_FAMILY_MANIFEST_FORMAT = "thesistrace-dataset-family"
_TABLE_MANIFEST_FORMAT = "thesistrace-canonical-table"
_MANIFEST_VERSION = 1
_UNIVERSE_NAMES = UNIVERSE_NAMES
_MARKET_CANDIDATE_TABLE_SPEC_BY_NAME = {spec.name: spec for spec in MARKET_CANDIDATE_TABLE_SPECS}


class GenerationStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class MountedGenerationAdmission:
    generation: MountedFamilyGenerationDescriptor
    research_calendar: tuple[str, ...]


@dataclass(frozen=True)
class MountedRefreshBase:
    generation: MountedFamilyGenerationDescriptor
    canonical: dict[str, object]


@dataclass(frozen=True)
class MountedMarketSeries:
    generation: MountedFamilyGenerationDescriptor
    research_data: AlignedResearchData


@dataclass(frozen=True, order=True)
class GenerationFileRef:
    kind: str
    sha256: str


class MountedGenerationStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._files = AddressedFileStore(self._root)

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
        }
        family_references = [
            self._materialize_market_family(
                family_spec,
                table_references=table_references,
                canonical=normalized,
                calendar=calendar,
            )
            for family_spec in MARKET_FAMILY_SPECS
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
        }
        data_identity = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        preparation = _preparation(prepared_at, source_name, source_lineage)
        root_manifest = {
            "format": _FAMILY_GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": data_identity,
            **identity,
            "preparation": preparation,
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
        candidate_tables: dict[str, list[dict[str, object]]] = {}
        calendar: list[str] | None = None
        for reference, family_spec in zip(references, MARKET_FAMILY_SPECS, strict=True):
            if not isinstance(reference, Mapping):
                raise GenerationStoreError("Dataset Family reference is incompatible")
            family_manifest = self._read_family_manifest(family_spec, reference)
            table_references = family_manifest["tables"]
            assert isinstance(table_references, list)
            for table_reference, table_name in zip(
                table_references,
                family_spec.table_names,
                strict=True,
            ):
                if not isinstance(table_reference, Mapping):
                    raise GenerationStoreError("Dataset Family table reference is incompatible")
                spec = _MARKET_CANDIDATE_TABLE_SPEC_BY_NAME[table_name]
                rows = self._open_table(
                    spec,
                    table_reference,
                    calendar,
                )
                candidate_tables[table_name] = rows
                if table_name == "research_calendar":
                    calendar = [str(row["session"]) for row in rows]
        canonical = _validate_candidate_semantics(candidate_tables)
        descriptor = _family_generation_descriptor_from_root(manifest_sha256, root)
        _validate_candidate_projection(descriptor, canonical)
        return descriptor

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
        return MountedGenerationAdmission(
            generation=descriptor,
            research_calendar=calendar,
        )

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
        for family_spec in MARKET_FAMILY_SPECS[1:]:
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
        for family_spec in MARKET_FAMILY_SPECS:
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

        family_references = [
            self._materialize_market_family(
                family_spec,
                table_references=table_references,
                canonical=normalized,
                calendar=new_calendar,
            )
            for family_spec in MARKET_FAMILY_SPECS
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
        }
        data_identity = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        preparation = _preparation(prepared_at, source_name, source_lineage)
        root_manifest = {
            "format": _FAMILY_GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": data_identity,
            **identity,
            "preparation": preparation,
        }
        root_bytes = _bounded_manifest_bytes(root_manifest)
        root_sha256 = hashlib.sha256(root_bytes).hexdigest()
        self._store_addressed(self._manifest_path(root_sha256), root_sha256, root_bytes)
        return _family_generation_descriptor_from_root(root_sha256, root_manifest)

    def _family_table_reference(
        self,
        root: Mapping[str, object],
        family_id: str,
        table_name: str,
    ) -> tuple[_TableSpec, Mapping[str, object]]:
        references = root["families"]
        assert isinstance(references, list)
        family_index = next(
            (
                index
                for index, spec in enumerate(MARKET_FAMILY_SPECS)
                if spec.family_id == family_id
            ),
            None,
        )
        if family_index is None:
            raise GenerationStoreError("Dataset Family is unavailable")
        reference = references[family_index]
        if not isinstance(reference, Mapping):
            raise GenerationStoreError("Dataset Family reference is incompatible")
        family = self._read_family_manifest(MARKET_FAMILY_SPECS[family_index], reference)
        table_references = family["tables"]
        assert isinstance(table_references, list)
        table_index = MARKET_FAMILY_SPECS[family_index].table_names.index(table_name)
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

    def inventory(self) -> frozenset[GenerationFileRef]:
        references = {
            GenerationFileRef("manifest", sha256)
            for sha256 in _inventory_sha256(self._root, "manifests", ".json")
        }
        references.update(
            GenerationFileRef("object", sha256)
            for sha256 in _inventory_sha256(self._root, "objects", ".parquet")
        )
        return frozenset(references)

    def delete_file(self, reference: GenerationFileRef) -> bool:
        if reference.kind == "manifest":
            target = self._manifest_path(reference.sha256)
        elif reference.kind == "object":
            target = self._object_path(reference.sha256)
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
        if set(root) != {
            "format",
            "version",
            "data_identity",
            "schema_contract",
            "data_through_session",
            "research_sessions",
            "field_availability",
            "families",
            "preparation",
        }:
            raise GenerationStoreError("Family Generation candidate schema is incompatible")
        families = root["families"]
        if not isinstance(families, list) or [
            entry.get("family_id") for entry in families if isinstance(entry, Mapping)
        ] != [spec.family_id for spec in MARKET_FAMILY_SPECS]:
            raise GenerationStoreError("Family Generation candidate set is incompatible")
        identity = {
            "schema_contract": root["schema_contract"],
            "data_through_session": root["data_through_session"],
            "research_sessions": root["research_sessions"],
            "field_availability": root["field_availability"],
            "families": families,
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

    def _open_partition_projection(
        self,
        spec: _TableSpec,
        object_ref: object,
        ordinal: int,
        *,
        columns: set[str] | None,
        instrument_ids: frozenset[str] | None,
    ) -> list[dict[str, object]]:
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
            table = pq.read_table(
                pa.BufferReader(content),
                columns=None if columns is None else sorted(columns),
                filters=(
                    None
                    if instrument_ids is None
                    else [("instrument_id", "in", sorted(instrument_ids))]
                ),
            )
        except (ArrowException, TypeError, ValueError) as error:
            raise GenerationStoreError("Generation object projection is incompatible") from error
        return table.to_pylist()

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
        }

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
            if table.schema != spec.contract.schema:
                raise GenerationStoreError("Generation object schema is incompatible")
            rows = canonicalize_parquet_rows(table.to_pylist(), spec.contract)
            if parquet_bytes(rows, spec.contract) != content:
                raise GenerationStoreError("Generation object encoding is non-canonical")
        except (ArrowException, ParquetContractError, TypeError, ValueError) as error:
            raise GenerationStoreError("Generation object is incompatible") from error
        first_key, last_key = _partition_boundaries(rows, spec.contract.sort_keys)
        if (
            object_ref["row_count"] != len(rows)
            or object_ref["first_sort_key"] != first_key
            or object_ref["last_sort_key"] != last_key
        ):
            raise GenerationStoreError("Generation object boundaries are invalid")
        return rows

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
    if not isinstance(family_references, list) or len(family_references) != len(
        MARKET_FAMILY_SPECS
    ):
        raise GenerationStoreError("Family Generation candidate set is incompatible")
    families: list[MountedDatasetFamilyDescriptor] = []
    for reference, family_spec in zip(
        family_references,
        MARKET_FAMILY_SPECS,
        strict=True,
    ):
        if not isinstance(reference, Mapping):
            raise GenerationStoreError("Dataset Family reference is incompatible")
        families.append(_family_descriptor_from_reference(reference, family_spec))
    try:
        validate_synchronized_coverages(
            tuple(families),
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
    )


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
        }
        or object_ref["ordinal"] != ordinal
    ):
        raise GenerationStoreError("Generation table object reference is invalid")
    _require_sha256(object_ref["sha256"])
    _required_byte_count(object_ref["byte_count"], "Generation object")
    row_count = object_ref["row_count"]
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
        raise GenerationStoreError("Generation object row count is invalid")


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
        "industry_membership",
        "field_catalog",
    }
    if set(canonical) != required:
        raise GenerationStoreError("Canonical Generation table set is incompatible")
    normalized_rows: dict[str, list[dict[str, object]]] = {}
    for spec in _TABLE_SPECS:
        try:
            normalized_rows[spec.name] = canonicalize_parquet_rows(
                _table_rows(canonical, spec.name),
                spec.contract,
            )
        except ParquetContractError as error:
            raise GenerationStoreError(f"Canonical table is incompatible: {spec.name}") from error
    return _canonical_from_rows(normalized_rows)


def _validate_candidate_semantics(
    candidate_tables: Mapping[str, list[dict[str, object]]],
) -> dict[str, object]:
    required = {spec.name for spec in MARKET_CANDIDATE_TABLE_SPECS}
    if set(candidate_tables) != required:
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
    actual_fields = tuple(sorted(str(row["field_id"]) for row in field_catalog))
    if (
        descriptor.data_through_session != str(calendar[-1])
        or descriptor.research_sessions != tuple(str(session) for session in calendar)
        or descriptor.field_availability != actual_fields
    ):
        raise GenerationStoreError("Family Generation root projection is incompatible")
    for family, spec in zip(descriptor.families, MARKET_FAMILY_SPECS, strict=True):
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
        "industry_membership": tables["industry_membership"],
        "field_catalog": tables["field_catalog"],
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

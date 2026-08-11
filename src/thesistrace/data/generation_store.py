from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_schema import (
    GENERATION_MANIFEST_MAX_BYTES,
    GENERATION_OBJECT_MAX_BYTES,
    GENERATION_ROW_PARTITION_COUNT,
    GENERATION_SESSION_PARTITION_COUNT,
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
from thesistrace.publication.serialization import (
    ParquetContractError,
    canonical_json_bytes,
    canonicalize_parquet_rows,
    parquet_bytes,
)

_GENERATION_FORMAT = "thesistrace-canonical-generation"
_TABLE_MANIFEST_FORMAT = "thesistrace-canonical-table"
_MANIFEST_VERSION = 1
_UNIVERSE_NAMES = UNIVERSE_NAMES


class GenerationStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class MountedGeneration:
    manifest_sha256: str
    data_identity: str
    dataset_coverage: dict[str, object]
    data_through_session: str
    field_availability: tuple[str, ...]
    preparation: dict[str, str]
    canonical: dict[str, object]


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
    ) -> MountedGeneration:
        normalized = _normalize_canonical(canonical)
        _validate_generation(normalized)
        calendar = normalized["research_calendar"]
        assert isinstance(calendar, list)
        table_entries: list[dict[str, object]] = []
        for spec in _TABLE_SPECS:
            rows = _table_rows(normalized, spec.name)
            table_manifest = self._materialize_table(spec, rows, calendar)
            table_entries.append(table_manifest)
        field_availability = tuple(
            sorted(str(row["field_id"]) for row in normalized["field_catalog"])
        )
        coverage = {
            "start": str(calendar[0]),
            "end": str(calendar[-1]),
            "session_count": len(calendar),
        }
        identity = {
            "schema_contract": "canonical-eod",
            "dataset_coverage": coverage,
            "data_through_session": str(calendar[-1]),
            "field_availability": list(field_availability),
            "tables": table_entries,
        }
        data_identity = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        preparation = _preparation(prepared_at, source_name, source_lineage)
        root_manifest = {
            "format": _GENERATION_FORMAT,
            "version": _MANIFEST_VERSION,
            "data_identity": data_identity,
            **identity,
            "preparation": preparation,
        }
        root_bytes = _bounded_manifest_bytes(root_manifest)
        root_sha256 = hashlib.sha256(root_bytes).hexdigest()
        self._store_addressed(self._manifest_path(root_sha256), root_sha256, root_bytes)
        return MountedGeneration(
            manifest_sha256=root_sha256,
            data_identity=data_identity,
            dataset_coverage=coverage,
            data_through_session=str(calendar[-1]),
            field_availability=field_availability,
            preparation=preparation,
            canonical=normalized,
        )

    def open_generation(self, manifest_sha256: str) -> MountedGeneration:
        root = self._read_manifest(manifest_sha256)
        if root.get("format") != _GENERATION_FORMAT or root.get("version") != _MANIFEST_VERSION:
            raise GenerationStoreError("Generation manifest is incompatible")
        if set(root) != {
            "format",
            "version",
            "data_identity",
            "schema_contract",
            "dataset_coverage",
            "data_through_session",
            "field_availability",
            "tables",
            "preparation",
        }:
            raise GenerationStoreError("Generation manifest schema is incompatible")
        tables = root["tables"]
        if not isinstance(tables, list) or [
            entry.get("name") for entry in tables if isinstance(entry, Mapping)
        ] != [spec.name for spec in _TABLE_SPECS]:
            raise GenerationStoreError("Generation table manifest set is incompatible")
        table_rows: dict[str, list[dict[str, object]]] = {}
        calendar: list[str] | None = None
        for entry, spec in zip(tables, _TABLE_SPECS, strict=True):
            if not isinstance(entry, Mapping):
                raise GenerationStoreError("Generation table reference is incompatible")
            table_rows[spec.name] = self._open_table(spec, entry, calendar)
            if spec.name == "research_calendar":
                calendar = [str(row["session"]) for row in table_rows[spec.name]]
        canonical = _canonical_from_rows(table_rows)
        _validate_generation(canonical)
        identity = {
            "schema_contract": root["schema_contract"],
            "dataset_coverage": root["dataset_coverage"],
            "data_through_session": root["data_through_session"],
            "field_availability": root["field_availability"],
            "tables": tables,
        }
        expected_identity = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        if root["data_identity"] != expected_identity:
            raise GenerationStoreError("Generation data identity is invalid")
        _validate_root_projection(root, canonical)
        preparation = root["preparation"]
        if not isinstance(preparation, dict):
            raise GenerationStoreError("Generation preparation metadata is incompatible")
        return MountedGeneration(
            manifest_sha256=manifest_sha256,
            data_identity=expected_identity,
            dataset_coverage=dict(root["dataset_coverage"]),
            data_through_session=str(root["data_through_session"]),
            field_availability=tuple(str(value) for value in root["field_availability"]),
            preparation={str(key): str(value) for key, value in preparation.items()},
            canonical=canonical,
        )

    def referenced_files(self, manifest_sha256: str) -> frozenset[GenerationFileRef]:
        self.open_generation(manifest_sha256)
        root = self._read_manifest(manifest_sha256)
        references = {GenerationFileRef("manifest", manifest_sha256)}
        tables = root["tables"]
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

    def _materialize_table(
        self,
        spec: _TableSpec,
        rows: list[dict[str, object]],
        calendar: list[object],
    ) -> dict[str, object]:
        canonical_rows = canonicalize_parquet_rows(rows, spec.contract)
        partitions = _partition_rows(spec, canonical_rows, [str(value) for value in calendar])
        objects: list[dict[str, object]] = []
        for ordinal, partition in enumerate(partitions):
            content = parquet_bytes(partition, spec.contract)
            if len(content) > GENERATION_OBJECT_MAX_BYTES:
                raise GenerationStoreError("Generation object exceeds its byte bound")
            sha256 = hashlib.sha256(content).hexdigest()
            self._store_addressed(self._object_path(sha256), sha256, content)
            first_key, last_key = _partition_boundaries(partition, spec.contract.sort_keys)
            objects.append(
                {
                    "ordinal": ordinal,
                    "sha256": sha256,
                    "byte_count": len(content),
                    "row_count": len(partition),
                    "first_sort_key": first_key,
                    "last_sort_key": last_key,
                }
            )
        table_manifest = {
            "format": _TABLE_MANIFEST_FORMAT,
            "version": _MANIFEST_VERSION,
            "table": spec.name,
            "writer_contract": spec.contract.descriptor(),
            "partitioning": spec.partitioning,
            "row_count": len(canonical_rows),
            "objects": objects,
        }
        manifest_bytes = _bounded_manifest_bytes(table_manifest)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        self._store_addressed(self._manifest_path(manifest_sha256), manifest_sha256, manifest_bytes)
        return {
            "name": spec.name,
            "manifest_sha256": manifest_sha256,
            "manifest_byte_count": len(manifest_bytes),
            "row_count": len(canonical_rows),
            "object_count": len(objects),
        }

    def _open_table(
        self,
        spec: _TableSpec,
        reference: Mapping[str, object],
        calendar: list[str] | None,
    ) -> list[dict[str, object]]:
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
    normalized = json.loads(canonical_json_bytes(canonical))
    base_pool = normalized.get("base_pool")
    if isinstance(base_pool, list):
        for row in base_pool:
            if isinstance(row, dict) and isinstance(row.get("instrument_ids"), list):
                row["instrument_ids"] = sorted(str(value) for value in row["instrument_ids"])
    normalized_rows: dict[str, list[dict[str, object]]] = {}
    for spec in _TABLE_SPECS:
        try:
            normalized_rows[spec.name] = canonicalize_parquet_rows(
                _table_rows(normalized, spec.name),
                spec.contract,
            )
        except ParquetContractError as error:
            raise GenerationStoreError(f"Canonical table is incompatible: {spec.name}") from error
    return _canonical_from_rows(normalized_rows)


def _table_rows(canonical: Mapping[str, object], table: str) -> list[dict[str, object]]:
    if table == "research_calendar":
        return [{"session": str(session)} for session in canonical[table]]
    if table == "liquidity_universes":
        universes = canonical[table]
        if not isinstance(universes, Mapping):
            raise GenerationStoreError("Canonical Liquidity Universes are incompatible")
        return [
            {"universe": universe, **dict(row)}
            for universe, rows in universes.items()
            if isinstance(rows, list)
            for row in rows
            if isinstance(row, Mapping)
        ]
    rows = canonical[table]
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise GenerationStoreError(f"Canonical table is incompatible: {table}")
    return [dict(row) for row in rows]


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
        [rows[0][key] for key in sort_keys],
        [rows[-1][key] for key in sort_keys],
    )


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


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise GenerationStoreError("Generation identity is incompatible")


def _validate_root_projection(root: Mapping[str, object], canonical: Mapping[str, object]) -> None:
    calendar = canonical["research_calendar"]
    fields = canonical["field_catalog"]
    assert isinstance(calendar, list)
    assert isinstance(fields, list)
    expected_coverage = {
        "start": calendar[0],
        "end": calendar[-1],
        "session_count": len(calendar),
    }
    expected_fields = sorted(str(row["field_id"]) for row in fields)
    preparation = root["preparation"]
    if (
        root["schema_contract"] != "canonical-eod"
        or root["dataset_coverage"] != expected_coverage
        or root["data_through_session"] != calendar[-1]
        or root["field_availability"] != expected_fields
        or not isinstance(preparation, Mapping)
        or set(preparation) != {"prepared_at", "source_name", "source_lineage_sha256"}
    ):
        raise GenerationStoreError("Generation manifest projection is incompatible")
    try:
        prepared_at = datetime.fromisoformat(str(preparation["prepared_at"]))
        _require_sha256(str(preparation["source_lineage_sha256"]))
    except ValueError as error:
        raise GenerationStoreError("Generation preparation metadata is incompatible") from error
    if prepared_at.tzinfo is None or not str(preparation["source_name"]):
        raise GenerationStoreError("Generation preparation metadata is incompatible")


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
    "MountedGeneration",
    "MountedGenerationStore",
)

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.publication.serialization import (
    ParquetContractError,
    ParquetWriterContract,
    canonical_json_bytes,
    canonicalize_parquet_rows,
    parquet_bytes,
)

GENERATION_MANIFEST_MAX_BYTES = 1_048_576
GENERATION_SESSION_PARTITION_COUNT = 64
GENERATION_ROW_PARTITION_COUNT = 4_096

_GENERATION_FORMAT = "thesistrace-canonical-generation"
_TABLE_MANIFEST_FORMAT = "thesistrace-canonical-table"
_MANIFEST_VERSION = 1
_UNIVERSE_NAMES = ("top300", "top1000", "top2000", "top3000")


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


@dataclass(frozen=True)
class _TableSpec:
    name: str
    contract: ParquetWriterContract
    session_field: str | None = None

    @property
    def partitioning(self) -> dict[str, object]:
        if self.session_field is not None:
            return {
                "kind": "research-session-block",
                "session_count": GENERATION_SESSION_PARTITION_COUNT,
            }
        return {"kind": "row-block", "row_count": GENERATION_ROW_PARTITION_COUNT}


def _contract(
    name: str,
    fields: Sequence[tuple[str, pa.DataType]],
    sort_keys: tuple[str, ...],
) -> ParquetWriterContract:
    return ParquetWriterContract(
        name=f"canonical-generation-{name}",
        version=1,
        schema=pa.schema([pa.field(field, kind, nullable=False) for field, kind in fields]),
        sort_keys=sort_keys,
    )


_STRING = pa.string()
_STRING_LIST = pa.list_(pa.field("item", pa.string(), nullable=False))
_TABLE_SPECS = (
    _TableSpec(
        "research_calendar",
        _contract("research-calendar", (("session", _STRING),), ("session",)),
        "session",
    ),
    _TableSpec(
        "instruments",
        _contract(
            "instruments",
            tuple(
                (name, _STRING)
                for name in (
                    "instrument_id",
                    "ts_code",
                    "asset_type",
                    "exchange",
                    "board",
                    "listed_from",
                    "listed_to",
                )
            ),
            ("instrument_id",),
        ),
    ),
    _TableSpec(
        "prices",
        _contract(
            "prices",
            tuple(
                (name, _STRING)
                for name in (
                    "session",
                    "instrument_id",
                    "open_raw",
                    "high_raw",
                    "low_raw",
                    "close_raw",
                    "pre_close_raw",
                    "change_raw",
                    "pct_change_raw",
                    "volume_shares",
                    "turnover_cny",
                    "adjustment_factor",
                    "adjustment_anchor_factor",
                    "open_adj",
                    "high_adj",
                    "low_adj",
                    "close_adj",
                    "trading_state",
                )
            ),
            ("session", "instrument_id"),
        ),
        "session",
    ),
    _TableSpec(
        "trading_states",
        _contract(
            "trading-states",
            (("session", _STRING), ("instrument_id", _STRING), ("state", _STRING)),
            ("session", "instrument_id"),
        ),
        "session",
    ),
    _TableSpec(
        "price_limits",
        _contract(
            "price-limits",
            (
                ("session", _STRING),
                ("instrument_id", _STRING),
                ("upper", _STRING),
                ("lower", _STRING),
            ),
            ("session", "instrument_id"),
        ),
        "session",
    ),
    _TableSpec(
        "adjustment_anchors",
        _contract(
            "adjustment-anchors",
            (
                ("instrument_id", _STRING),
                ("anchor_session", _STRING),
                ("anchor_factor", _STRING),
            ),
            ("instrument_id",),
        ),
    ),
    _TableSpec(
        "base_pool",
        _contract(
            "base-pool",
            (("session", _STRING), ("instrument_ids", _STRING_LIST)),
            ("session",),
        ),
        "session",
    ),
    _TableSpec(
        "liquidity_universes",
        _contract(
            "liquidity-universes",
            (
                ("session", _STRING),
                ("universe", _STRING),
                ("instrument_ids", _STRING_LIST),
                ("status", _STRING),
            ),
            ("session", "universe"),
        ),
        "session",
    ),
    _TableSpec(
        "industry_membership",
        _contract(
            "industry-membership",
            tuple(
                (name, _STRING)
                for name in (
                    "instrument_id",
                    "active_from",
                    "active_to",
                    "sw2021_l1",
                    "sw2021_l2",
                    "sw2021_l3",
                )
            ),
            ("instrument_id", "active_from"),
        ),
    ),
    _TableSpec(
        "st_designations",
        _contract(
            "st-designations",
            tuple(
                (name, _STRING)
                for name in (
                    "trade_date",
                    "instrument_id",
                    "ts_code",
                    "name",
                    "type",
                    "type_name",
                )
            ),
            ("trade_date", "instrument_id"),
        ),
        "trade_date",
    ),
    _TableSpec(
        "field_catalog",
        _contract(
            "field-catalog",
            (
                ("field_id", _STRING),
                ("name", _STRING),
                ("definition", _STRING),
                ("unit", _STRING),
                ("time_semantics", _STRING),
                ("alpha_authorable", pa.bool_()),
                ("release_available_from", _STRING),
                ("coverage", _STRING),
            ),
            ("field_id",),
        ),
    ),
)
_TABLE_SPEC_BY_NAME = {spec.name: spec for spec in _TABLE_SPECS}


class MountedGenerationStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def materialize(
        self,
        canonical: Mapping[str, object],
        *,
        prepared_at: datetime,
        source_name: str,
        source_lineage: Mapping[str, object],
    ) -> MountedGeneration:
        normalized = _normalize_canonical(canonical)
        _validate_canonical(normalized)
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
            "schema_contract": "canonical-eod-v1",
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
        _validate_canonical(canonical)
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
        content = self._read_addressed(self._manifest_path(manifest_sha256), manifest_sha256)
        if reference["manifest_byte_count"] != len(content):
            raise GenerationStoreError("Generation table manifest byte count is invalid")
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
        content = self._read_addressed(self._object_path(sha256), sha256)
        if object_ref["byte_count"] != len(content):
            raise GenerationStoreError("Generation object byte count is invalid")
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
        return _parse_manifest(self._read_addressed(self._manifest_path(sha256), sha256))

    def _read_addressed(self, path: Path, expected_sha256: str) -> bytes:
        _require_sha256(expected_sha256)
        try:
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise GenerationStoreError("Generation object or manifest is missing") from error
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise GenerationStoreError("Generation object or manifest checksum is invalid")
        return content

    def _store_addressed(self, target: Path, sha256: str, content: bytes) -> None:
        if hashlib.sha256(content).hexdigest() != sha256:
            raise GenerationStoreError("Generation addressed content checksum is invalid")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise GenerationStoreError("Generation immutable content conflicts")
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=".candidate-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != content:
                    raise GenerationStoreError("Generation immutable content conflicts") from None
        finally:
            temporary.unlink(missing_ok=True)

    def _manifest_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "manifests" / "sha256" / sha256[:2] / f"{sha256}.json"

    def _object_path(self, sha256: str) -> Path:
        _require_sha256(sha256)
        return self._root / "objects" / "sha256" / sha256[:2] / f"{sha256}.parquet"


def _normalize_canonical(canonical: Mapping[str, object]) -> dict[str, object]:
    required = {
        "schema_version",
        "research_calendar",
        "instruments",
        "prices",
        "trading_states",
        "price_limits",
        "adjustment_anchors",
        "base_pool",
        "liquidity_universes",
        "industry_membership",
        "field_catalog",
    }
    if not required <= set(canonical) or not set(canonical) <= required | {"st_designations"}:
        raise GenerationStoreError("Canonical Generation table set is incompatible")
    normalized = json.loads(canonical_json_bytes(canonical))
    normalized.setdefault("st_designations", [])
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
        "schema_version": "canonical-eod-v1",
        "research_calendar": [row["session"] for row in tables["research_calendar"]],
        "instruments": tables["instruments"],
        "prices": tables["prices"],
        "trading_states": tables["trading_states"],
        "price_limits": tables["price_limits"],
        "adjustment_anchors": tables["adjustment_anchors"],
        "base_pool": tables["base_pool"],
        "liquidity_universes": universes,
        "industry_membership": tables["industry_membership"],
        "st_designations": tables["st_designations"],
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
        root["schema_contract"] != "canonical-eod-v1"
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


def _validate_canonical(canonical: Mapping[str, object]) -> None:
    if canonical.get("schema_version") != "canonical-eod-v1":
        raise GenerationStoreError("Canonical Generation schema is incompatible")
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or not calendar or calendar != sorted(set(calendar)):
        raise GenerationStoreError("Canonical Research Calendar is invalid")
    try:
        parsed_calendar = [date.fromisoformat(str(session)) for session in calendar]
    except ValueError as error:
        raise GenerationStoreError("Canonical Research Calendar is invalid") from error
    if any(session.weekday() >= 5 for session in parsed_calendar):
        raise GenerationStoreError("Canonical Research Calendar is invalid")
    calendar_set = set(map(str, calendar))

    instruments = _rows(canonical, "instruments")
    instrument_ids = [str(row["instrument_id"]) for row in instruments]
    instrument_set = set(instrument_ids)
    if not instrument_ids or len(instrument_ids) != len(instrument_set):
        raise GenerationStoreError("Canonical instrument identities are invalid")
    for row in instruments:
        listed_from = _iso_date(row["listed_from"], "Canonical Instrument.listed_from")
        listed_to = row["listed_to"]
        if listed_to and _iso_date(listed_to, "Canonical Instrument.listed_to") < listed_from:
            raise GenerationStoreError("Canonical instrument lifecycle is invalid")

    base_pool = _rows(canonical, "base_pool")
    if [str(row["session"]) for row in base_pool] != list(map(str, calendar)):
        raise GenerationStoreError("Canonical Base Pool coverage is invalid")
    base_positions: set[tuple[str, str]] = set()
    base_by_session: dict[str, set[str]] = {}
    for row in base_pool:
        members = row["instrument_ids"]
        if not isinstance(members, list):
            raise GenerationStoreError("Canonical Base Pool membership is invalid")
        member_ids = [str(value) for value in members]
        if len(member_ids) != len(set(member_ids)) or not set(member_ids) <= instrument_set:
            raise GenerationStoreError("Canonical Base Pool membership is invalid")
        session = str(row["session"])
        base_by_session[session] = set(member_ids)
        base_positions.update((session, instrument_id) for instrument_id in member_ids)

    states = _rows(canonical, "trading_states")
    state_by_position = _unique_positions(states, "session", "Canonical Trading State")
    if set(state_by_position) != base_positions or any(
        row["state"]
        not in {
            "normal",
            "full_session_suspension",
            "partial_opening_suspension",
            "after_open_suspension",
        }
        for row in states
    ):
        raise GenerationStoreError("Canonical Trading State coverage is invalid")

    prices = _rows(canonical, "prices")
    price_by_position = _unique_positions(prices, "session", "Canonical Price")
    expected_trade_positions = {
        position
        for position, row in state_by_position.items()
        if row["state"] != "full_session_suspension"
    }
    if set(price_by_position) != expected_trade_positions:
        raise GenerationStoreError("Canonical Price coverage is invalid")
    for position, row in price_by_position.items():
        if row["trading_state"] != state_by_position[position]["state"]:
            raise GenerationStoreError("Canonical Price trading state is invalid")
        for field in (
            "open_raw",
            "high_raw",
            "low_raw",
            "close_raw",
            "pre_close_raw",
            "change_raw",
            "pct_change_raw",
            "volume_shares",
            "turnover_cny",
            "adjustment_factor",
            "adjustment_anchor_factor",
            "open_adj",
            "high_adj",
            "low_adj",
            "close_adj",
        ):
            _finite_decimal(row[field], f"Canonical Price.{field}")

    limits = _rows(canonical, "price_limits")
    limit_by_position = _unique_positions(limits, "session", "Canonical Price Limit")
    if set(limit_by_position) != expected_trade_positions:
        raise GenerationStoreError("Canonical Price Limit coverage is invalid")
    for row in limits:
        _finite_decimal(row["upper"], "Canonical Price Limit.upper")
        _finite_decimal(row["lower"], "Canonical Price Limit.lower")

    anchors = _rows(canonical, "adjustment_anchors")
    if {str(row["instrument_id"]) for row in anchors} != instrument_set or len(anchors) != len(
        instrument_set
    ):
        raise GenerationStoreError("Canonical Adjustment Anchor coverage is invalid")
    for row in anchors:
        if (
            str(row["anchor_session"]) not in calendar_set
            or _finite_decimal(row["anchor_factor"], "Canonical Adjustment Anchor.factor") <= 0
        ):
            raise GenerationStoreError("Canonical Adjustment Anchor is invalid")

    universes = canonical.get("liquidity_universes")
    if not isinstance(universes, Mapping) or set(universes) != set(_UNIVERSE_NAMES):
        raise GenerationStoreError("Canonical Liquidity Universes are invalid")
    universe_members: dict[str, list[list[str]]] = {}
    for name in _UNIVERSE_NAMES:
        rows = universes[name]
        if not isinstance(rows, list) or [str(row["session"]) for row in rows] != list(
            map(str, calendar)
        ):
            raise GenerationStoreError("Canonical Liquidity Universe coverage is invalid")
        universe_members[name] = []
        for row in rows:
            members = row["instrument_ids"]
            if (
                not isinstance(members, list)
                or len(members) != len(set(map(str, members)))
                or not set(map(str, members)) <= base_by_session[str(row["session"])]
                or row["status"] != "available"
            ):
                raise GenerationStoreError("Canonical Liquidity Universe membership is invalid")
            universe_members[name].append([str(value) for value in members])
    for session_index in range(len(calendar)):
        prior: list[str] = []
        for name, maximum_size in zip(_UNIVERSE_NAMES, (300, 1000, 2000, 3000), strict=True):
            members = universe_members[name][session_index]
            if len(members) > maximum_size or prior != members[: len(prior)]:
                raise GenerationStoreError("Canonical Liquidity Universe nesting is invalid")
            prior = members

    industries = _rows(canonical, "industry_membership")
    prior_end_by_instrument: dict[str, date] = {}
    for row in industries:
        instrument_id = str(row["instrument_id"])
        active_from = _iso_date(row["active_from"], "Canonical Industry.active_from")
        active_to = (
            _iso_date(row["active_to"], "Canonical Industry.active_to")
            if row["active_to"]
            else date.max
        )
        if (
            instrument_id not in instrument_set
            or active_to < active_from
            or active_from < prior_end_by_instrument.get(instrument_id, date.min)
            or not all(row[field] for field in ("sw2021_l1", "sw2021_l2", "sw2021_l3"))
        ):
            raise GenerationStoreError("Canonical Industry Membership is invalid")
        prior_end_by_instrument[instrument_id] = active_to
    st_designations = _rows(canonical, "st_designations")
    if any(
        str(row["instrument_id"]) not in instrument_set
        or str(row["trade_date"]) not in calendar_set
        for row in st_designations
    ):
        raise GenerationStoreError("Canonical ST Designation is invalid")
    fields = _rows(canonical, "field_catalog")
    field_ids = [str(row["field_id"]) for row in fields]
    if not field_ids or len(field_ids) != len(set(field_ids)):
        raise GenerationStoreError("Canonical Field Catalog is invalid")


def _rows(canonical: Mapping[str, object], name: str) -> list[dict[str, object]]:
    value = canonical.get(name)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise GenerationStoreError(f"Canonical table is invalid: {name}")
    return value


def _unique_positions(
    rows: list[dict[str, object]],
    session_field: str,
    name: str,
) -> dict[tuple[str, str], dict[str, object]]:
    result = {(str(row[session_field]), str(row["instrument_id"])): row for row in rows}
    if len(result) != len(rows):
        raise GenerationStoreError(f"{name} identities are invalid")
    return result


def _finite_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str) or not value:
        raise GenerationStoreError(f"{name} is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise GenerationStoreError(f"{name} is invalid") from error
    if not result.is_finite():
        raise GenerationStoreError(f"{name} is invalid")
    return result


def _iso_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise GenerationStoreError(f"{name} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise GenerationStoreError(f"{name} is invalid") from error


__all__ = (
    "GENERATION_MANIFEST_MAX_BYTES",
    "GENERATION_SESSION_PARTITION_COUNT",
    "GenerationStoreError",
    "MountedGeneration",
    "MountedGenerationStore",
)

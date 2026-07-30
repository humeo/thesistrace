import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

PINNED_PYARROW_VERSION = "25.0.0"
PINNED_ARROW_CPP_VERSION = "25.0.0"
PINNED_ZSTD_VERSION = "1.5.7"
PARQUET_FORMAT_VERSION = "2.6"
PARQUET_DATA_PAGE_VERSION = "2.0"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ParquetContractError(ValueError):
    pass


@dataclass(frozen=True)
class ParquetWriterContract:
    name: str
    version: int
    schema: pa.Schema
    sort_keys: tuple[str, ...]
    compression_level: int = 9

    def __post_init__(self) -> None:
        if not self.name or "/" in self.name:
            raise ParquetContractError("Parquet contract name must be non-empty and path-safe")
        if self.version < 1:
            raise ParquetContractError("Parquet contract version must be positive")
        if not self.schema.names or len(set(self.schema.names)) != len(self.schema.names):
            raise ParquetContractError("Parquet schema field names must be non-empty and unique")
        if self.schema.metadata is not None or any(
            field.metadata is not None for field in self.schema
        ):
            raise ParquetContractError("Parquet schema metadata is not canonical in V1")
        if not self.sort_keys or len(set(self.sort_keys)) != len(self.sort_keys):
            raise ParquetContractError("Parquet sort keys must be non-empty and unique")
        fields = {field.name: field for field in self.schema}
        for key in self.sort_keys:
            if key not in fields:
                raise ParquetContractError(f"Parquet sort key is missing from schema: {key}")
            if fields[key].nullable:
                raise ParquetContractError(f"Parquet sort key must be non-nullable: {key}")
        if not 1 <= self.compression_level <= 22:
            raise ParquetContractError("ZSTD compression level must be between 1 and 22")

    @property
    def identifier(self) -> str:
        digest = hashlib.sha256(canonical_json_bytes(self._descriptor_core())).hexdigest()
        return f"{self.name}/v{self.version}/{digest[:20]}"

    def descriptor(self) -> dict[str, object]:
        return {"id": self.identifier, **self._descriptor_core()}

    def _descriptor_core(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "schema": [
                {
                    "name": field.name,
                    "logical_type": str(field.type),
                    "nullable": field.nullable,
                }
                for field in self.schema
            ],
            "sort_keys": list(self.sort_keys),
            "writer": {
                "implementation": "pyarrow",
                "implementation_version": PINNED_PYARROW_VERSION,
                "arrow_cpp_version": PINNED_ARROW_CPP_VERSION,
            },
            "parquet": {
                "format_version": PARQUET_FORMAT_VERSION,
                "data_page_version": PARQUET_DATA_PAGE_VERSION,
                "row_groups": 1,
                "use_dictionary": False,
                "write_statistics": True,
                "column_encoding": "PLAIN",
                "use_byte_stream_split": False,
                "write_page_index": False,
                "write_page_checksum": False,
                "store_schema": True,
                "store_decimal_as_integer": False,
                "write_time_adjusted_to_utc": False,
            },
            "compression": {
                "codec": "zstd",
                "codec_version": PINNED_ZSTD_VERSION,
                "level": self.compression_level,
            },
        }


class ImmutableObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put_json(self, value: object) -> dict[str, object]:
        payload = canonical_json_bytes(value)
        digest = self._put_payload(payload, suffix=".json")
        return {"sha256": digest, "bytes": len(payload)}

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]:
        payload = parquet_bytes(rows, contract)
        digest = self._put_payload(payload, suffix=".parquet")
        return {
            "format": "parquet",
            "sha256": digest,
            "bytes": len(payload),
            "writer_contract_id": contract.identifier,
            "writer_contract": contract.descriptor(),
        }

    def put_manifest(self, release_id: str, value: object) -> None:
        destination = self.root / "manifests" / f"{release_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return
        temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
        temporary.write_bytes(canonical_json_bytes(value))
        os.replace(temporary, destination)

    def path_for(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.json"

    def parquet_path_for(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.parquet"

    def read_json(self, digest: str) -> object:
        return json.loads(self.path_for(digest).read_text(encoding="utf-8"))

    def read_parquet_bytes(self, digest: str) -> bytes:
        return self.parquet_path_for(digest).read_bytes()

    def read_parquet(self, digest: str, contract: ParquetWriterContract) -> pa.Table:
        require_pinned_writer_runtime()
        payload = self.read_parquet_bytes(digest)
        table = pq.read_table(pa.BufferReader(payload))
        if not table.schema.equals(contract.schema, check_metadata=True):
            raise ParquetContractError("Parquet object schema does not match writer contract")
        metadata = pq.ParquetFile(pa.BufferReader(payload)).metadata
        if metadata.num_row_groups != 1:
            raise ParquetContractError("Parquet object must contain exactly one row group")
        return table

    def _put_payload(self, payload: bytes, *, suffix: str) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        destination = self.root / "sha256" / digest[:2] / f"{digest}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        return digest


def parquet_bytes(
    rows: Sequence[Mapping[str, object]],
    contract: ParquetWriterContract,
) -> bytes:
    require_pinned_writer_runtime()
    canonical_rows = canonicalize_parquet_rows(rows, contract)
    table = pa.Table.from_pylist(canonical_rows, schema=contract.schema)
    sorting_columns = pq.SortingColumn.from_ordering(
        contract.schema,
        [(key, "ascending") for key in contract.sort_keys],
    )
    output = pa.BufferOutputStream()
    pq.write_table(
        table,
        output,
        row_group_size=table.num_rows,
        version=PARQUET_FORMAT_VERSION,
        use_dictionary=False,
        compression="zstd",
        write_statistics=True,
        use_deprecated_int96_timestamps=False,
        coerce_timestamps="us",
        allow_truncated_timestamps=False,
        data_page_size=1024 * 1024,
        compression_level=contract.compression_level,
        use_byte_stream_split=False,
        column_encoding="PLAIN",
        data_page_version=PARQUET_DATA_PAGE_VERSION,
        use_compliant_nested_type=True,
        write_batch_size=1024,
        store_schema=True,
        write_page_index=False,
        write_page_checksum=False,
        sorting_columns=sorting_columns,
        store_decimal_as_integer=False,
        write_time_adjusted_to_utc=False,
    )
    return output.getvalue().to_pybytes()


def canonicalize_parquet_rows(
    rows: Sequence[Mapping[str, object]],
    contract: ParquetWriterContract,
) -> list[dict[str, object]]:
    if not rows:
        raise ParquetContractError("Parquet Physical Data Objects must contain at least one row")
    expected_fields = set(contract.schema.names)
    validated: list[dict[str, object]] = []
    identities: set[tuple[object, ...]] = set()
    for index, source in enumerate(rows):
        row = dict(source)
        if set(row) != expected_fields:
            raise ParquetContractError(
                f"Parquet row {index} fields do not match the declared schema"
            )
        for field in contract.schema:
            value = row[field.name]
            if value is None and not field.nullable:
                raise ParquetContractError(
                    f"Parquet row {index} has null for required field: {field.name}"
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise ParquetContractError(
                    f"Parquet row {index} has non-finite value: {field.name}"
                )
        identity = tuple(row[key] for key in contract.sort_keys)
        if any(value is None for value in identity):
            raise ParquetContractError(f"Parquet row {index} has a null sort key")
        try:
            duplicate = identity in identities
            identities.add(identity)
        except TypeError as error:
            raise ParquetContractError("Parquet sort keys must be scalar and hashable") from error
        if duplicate:
            raise ParquetContractError("Parquet sort keys must form a unique row identity")
        validated.append(row)
    try:
        return sorted(
            validated,
            key=lambda row: tuple(row[key] for key in contract.sort_keys),
        )
    except TypeError as error:
        raise ParquetContractError("Parquet sort keys must have one canonical order") from error


def require_pinned_writer_runtime() -> None:
    if pa.__version__ != PINNED_PYARROW_VERSION:
        raise ParquetContractError(
            f"PyArrow {PINNED_PYARROW_VERSION} is required, found {pa.__version__}"
        )
    if pa.cpp_build_info.version != PINNED_ARROW_CPP_VERSION:
        raise ParquetContractError(
            f"Arrow C++ {PINNED_ARROW_CPP_VERSION} is required, "
            f"found {pa.cpp_build_info.version}"
        )

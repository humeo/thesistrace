import fcntl
import hashlib
import json
import math
import os
import shutil
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
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
        try:
            temporary.write_bytes(canonical_json_bytes(value))
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def stage(self, run_id: str, attempt_id: str) -> "StagedObjectStore":
        return StagedObjectStore(self, run_id=run_id, attempt_id=attempt_id)

    @contextmanager
    def publication_guard(self, run_id: str) -> Iterator[None]:
        staging_root = self.root / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        lock_bucket = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:2]
        with (staging_root / f".run-{lock_bucket}.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def recover_staged_publication(
        self,
        run_id: str,
        *,
        committed_manifest_sha256: str | None,
    ) -> None:
        staging_root = self.root / "staging"
        if not staging_root.exists():
            return
        lock_path = staging_root / ".publication.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as publication_lock:
            fcntl.flock(publication_lock.fileno(), fcntl.LOCK_EX)
            try:
                run_root = staging_root / run_id
                for stage_root in sorted(run_root.glob("*")):
                    stage_lock_path = stage_root / ".stage.lock"
                    with stage_lock_path.open("a+b") as stage_lock:
                        try:
                            fcntl.flock(
                                stage_lock.fileno(),
                                fcntl.LOCK_EX | fcntl.LOCK_NB,
                            )
                        except BlockingIOError:
                            continue
                        journal_path = stage_root / ".publication.json"
                        if journal_path.exists():
                            journal = _read_stage_json(journal_path)
                            if (
                                journal.get("manifest_sha256")
                                != committed_manifest_sha256
                            ):
                                self._remove_uncommitted_private_paths(journal)
                        shutil.rmtree(stage_root, ignore_errors=True)
                if run_root.exists() and not any(run_root.iterdir()):
                    run_root.rmdir()
            finally:
                fcntl.flock(publication_lock.fileno(), fcntl.LOCK_UN)

    def _remove_uncommitted_private_paths(
        self,
        journal: dict[str, object],
    ) -> None:
        private_paths = journal.get("private_paths")
        if not isinstance(private_paths, list):
            raise ParquetContractError("staged publication journal is invalid")
        for relative in reversed(private_paths):
            if not isinstance(relative, str):
                raise ParquetContractError("staged publication path is invalid")
            destination = self.root / relative
            destination.unlink(missing_ok=True)

    def path_for(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.json"

    def parquet_path_for(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.parquet"

    def read_json(self, digest: str) -> object:
        return json.loads(self.path_for(digest).read_text(encoding="utf-8"))

    def read_parquet_bytes(self, digest: str) -> bytes:
        payload = self.parquet_path_for(digest).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ParquetContractError("Parquet object checksum does not match its identity")
        return payload

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
            try:
                temporary.write_bytes(payload)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return digest


class StagedObjectStore:
    def __init__(
        self,
        destination: ImmutableObjectStore,
        *,
        run_id: str,
        attempt_id: str,
    ) -> None:
        self.destination = destination
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.stage_lock = None
        self.promotion_started = False
        self.promotion_resolved = False
        self.writer = ImmutableObjectStore(
            destination.root / "staging" / run_id / attempt_id
        )
        self.root = self.writer.root

    def __enter__(self) -> "StagedObjectStore":
        self.root.mkdir(parents=True, exist_ok=True)
        _write_stage_json(
            self.root / ".stage.json",
            {"run_id": self.run_id, "attempt_id": self.attempt_id},
        )
        self.stage_lock = (self.root / ".stage.lock").open("a+b")
        fcntl.flock(self.stage_lock.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        if not self.promotion_started or self.promotion_resolved:
            shutil.rmtree(self.root, ignore_errors=True)
        if self.stage_lock is not None:
            fcntl.flock(self.stage_lock.fileno(), fcntl.LOCK_UN)
            self.stage_lock.close()
            self.stage_lock = None

    def put_json(self, value: object) -> dict[str, object]:
        return self.writer.put_json(value)

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]:
        return self.writer.put_parquet_rows(rows, contract)

    def put_manifest(self, resource_id: str, value: object) -> None:
        self.writer.put_manifest(resource_id, value)

    @contextmanager
    def publication(self, *, manifest_sha256: str) -> Iterator[None]:
        self.destination.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.destination.root / "staging" / ".publication.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                sources = sorted(
                    path
                    for path in self.root.rglob("*")
                    if path.is_file() and not path.name.startswith(".")
                )
                private_paths = [
                    str(source.relative_to(self.root))
                    for source in sources
                    if source.relative_to(self.root).parts[0] == "manifests"
                    if not (
                        self.destination.root / source.relative_to(self.root)
                    ).exists()
                ]
                journal = {
                    "run_id": self.run_id,
                    "attempt_id": self.attempt_id,
                    "manifest_sha256": manifest_sha256,
                    "private_paths": private_paths,
                }
                _write_stage_json(self.root / ".publication.json", journal)
                self.promotion_started = True
                for source in sources:
                    destination = self.destination.root / source.relative_to(self.root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        continue
                    os.replace(source, destination)
                yield
                self.promotion_resolved = True
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_stage_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParquetContractError("staged publication metadata is invalid") from error
    if not isinstance(value, dict):
        raise ParquetContractError("staged publication metadata is invalid")
    return value


def _write_stage_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            output.write(canonical_json_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
        row_group_size=max(1, table.num_rows),
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

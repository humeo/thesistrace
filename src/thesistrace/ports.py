from collections.abc import Mapping, Sequence
from typing import Protocol

import pyarrow as pa

from thesistrace.objects import ParquetWriterContract


class ControlMetadataPort(Protocol):
    def initialize(self) -> None: ...

    def connect(self): ...


class ObjectStorePort(Protocol):
    def put_json(self, value: object) -> dict[str, object]: ...

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]: ...

    def put_manifest(self, resource_id: str, value: object) -> None: ...

    def read_json(self, digest: str) -> object: ...

    def read_parquet_bytes(self, digest: str) -> bytes: ...

    def read_parquet(
        self,
        digest: str,
        contract: ParquetWriterContract,
    ) -> pa.Table: ...


class WorkingCachePort(Protocol):
    def list_track_ids(self) -> list[str]: ...

    def delete(self, track_id: str) -> None: ...


class ExecutionDispatchPort(Protocol):
    def dispatch(self, resource_kind: str, resource_id: str) -> None: ...


class LocalWorkerDispatch:
    """Local Worker polls durable metadata, so notification is intentionally a no-op."""

    def dispatch(self, resource_kind: str, resource_id: str) -> None:
        del resource_kind, resource_id

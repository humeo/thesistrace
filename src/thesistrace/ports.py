from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

import pyarrow as pa

from thesistrace.objects import ParquetWriterContract


class ControlMetadataPort(Protocol):
    def initialize(self) -> None: ...

    def connect(self): ...


class ObjectWriterPort(Protocol):
    def put_json(self, value: object) -> dict[str, object]: ...

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]: ...

    def put_manifest(self, resource_id: str, value: object) -> None: ...


class ObjectStoreStagePort(ObjectWriterPort, Protocol):
    def __enter__(self) -> "ObjectStoreStagePort": ...

    def __exit__(self, exc_type, exc_value, traceback) -> None: ...

    def publication(self, *, manifest_sha256: str) -> AbstractContextManager[None]: ...


class ObjectStorePort(ObjectWriterPort, Protocol):
    def stage(self, run_id: str, attempt_id: str) -> ObjectStoreStagePort: ...

    def publication_guard(self, run_id: str) -> AbstractContextManager[None]: ...

    def recover_staged_publication(
        self,
        run_id: str,
        *,
        committed_manifest_sha256: str | None,
    ) -> None: ...

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

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

import pyarrow as pa

from thesistrace.objects import ParquetWriterContract


class ControlMetadataPort(Protocol):
    def initialize(self) -> None: ...

    def connect(self): ...

    def lock_daily_track_activation(
        self,
        connection,
    ) -> None: ...

    def lock_daily_track(self, connection, track_id: str) -> None: ...

    def storage_mutation_fence(
        self,
    ) -> AbstractContextManager[None]: ...

    def request_resource_deletion(
        self,
        *,
        resource_kind: str,
        resource_id: str,
        actor: str,
        deleted_at: str,
    ) -> dict[str, object] | None: ...

    def pending_resource_cleanups(self) -> list[dict[str, object]]: ...

    def resource_cleanup_candidates(self, tombstone_id: str) -> list[str]: ...

    def complete_resource_cleanup(
        self,
        tombstone_id: str,
        completed_at: str,
    ) -> None: ...

    def fail_resource_cleanup(
        self,
        tombstone_id: str,
        error: str,
    ) -> None: ...

    def commit_private_storage_references(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int: ...

    def commit_platform_storage_references(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int: ...

    def publish_dataset_release_with_storage(
        self,
        release: dict[str, object],
        idempotency_key: str,
        storage_objects: list[dict[str, object]],
    ) -> tuple[dict[str, object], bool]: ...


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

    def read_json(self, digest: str) -> object: ...

    def read_parquet_bytes(self, digest: str) -> bytes: ...

    def read_parquet(
        self,
        digest: str,
        contract: ParquetWriterContract,
    ) -> pa.Table: ...


class ObjectStorePort(ObjectWriterPort, Protocol):
    def probe(self) -> bool: ...

    def stage(
        self,
        run_id: str,
        attempt_id: str,
        *,
        cleanup_uncommitted_payloads: bool = False,
    ) -> ObjectStoreStagePort: ...

    def publication_guard(self, run_id: str) -> AbstractContextManager[None]: ...

    def recover_staged_publication(
        self,
        run_id: str,
        *,
        committed_manifest_sha256: str | None,
    ) -> bool: ...

    def staged_publication_ids(self, *, prefix: str) -> list[str]: ...

    def wait_for_staged_publication(self, run_id: str) -> None: ...

    def delete_storage_object(self, object_key: str) -> bool: ...

    def read_json(self, digest: str) -> object: ...

    def read_parquet_bytes(self, digest: str) -> bytes: ...

    def read_parquet(
        self,
        digest: str,
        contract: ParquetWriterContract,
    ) -> pa.Table: ...


class ExecutionDispatchPort(Protocol):
    def dispatch(self, resource_kind: str, resource_id: str) -> None: ...


class LocalWorkerDispatch:
    """Local Worker polls durable metadata, so notification is intentionally a no-op."""

    def dispatch(self, resource_kind: str, resource_id: str) -> None:
        del resource_kind, resource_id

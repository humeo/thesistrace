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

    def active_daily_track_limit(self, connection) -> int: ...

    def lock_daily_track(self, connection, track_id: str) -> None: ...

    def daily_track_head_manifest_sha256(
        self,
        track_id: str,
    ) -> str | None: ...

    def daily_track_activation_reservation_ids(self) -> list[str]: ...

    def delete_daily_track_activation_reservation(
        self,
        track_id: str,
    ) -> bool: ...

    def daily_track_cache_states(
        self,
        track_ids: list[str],
    ) -> dict[str, tuple[str, int]]: ...

    def pending_working_cache_deletions(
        self,
        track_id: str | None = None,
    ) -> list[dict[str, object]]: ...

    def fail_working_cache_deletion(
        self,
        track_id: str,
        error: str,
    ) -> None: ...

    def complete_working_cache_deletion(
        self,
        track_id: str,
        completed_at: str,
    ) -> None: ...

    def active_daily_track_refs(
        self,
        *,
        after_workspace_id: str | None = None,
        after_track_id: str | None = None,
        through_workspace_id: str | None = None,
        through_track_id: str | None = None,
        limit: int = 101,
    ) -> list[dict[str, str]]: ...

    def active_daily_track_scan_bound(
        self,
    ) -> dict[str, str] | None: ...

    def next_dataset_release_on_path(
        self,
        ancestor_id: str,
        descendant_id: str,
    ) -> dict[str, object] | None: ...

    def enqueue_tracking_advance_execution(
        self,
        connection,
        *,
        track_id: str,
        advance_id: str,
        created_at: str,
    ) -> None: ...

    def bind_tracking_generation_rebuild(
        self,
        connection,
        *,
        rebuild_id: str,
        track_id: str,
        basis_generation_id: str,
        basis_head_checkpoint_id: str,
        generation_id: str,
        advance_id: str,
        updated_at: str,
    ) -> None: ...


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

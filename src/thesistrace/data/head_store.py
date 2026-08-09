from __future__ import annotations

import fcntl
import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from thesistrace.data.generation_store import MountedGeneration, MountedGenerationStore
from thesistrace.publication.serialization import canonical_json_bytes

HEAD_MANIFEST_MAX_BYTES = 65_536
_HEAD_FORMAT = "thesistrace-dataset-head"
_HEAD_VERSION = 1
_HEAD_NAME = "HEAD.json"
_LOCK_NAME = ".head.lock"


class DatasetHeadError(RuntimeError):
    pass


class DatasetHeadConflict(DatasetHeadError):
    pass


@dataclass(frozen=True)
class DatasetHead:
    generation_manifest_sha256: str
    data_identity: str
    dataset_coverage: dict[str, object]
    data_through_session: str
    prepared_at: str
    generation: MountedGeneration


@dataclass(frozen=True)
class DatasetHeadPointer:
    generation_manifest_sha256: str
    data_identity: str
    dataset_coverage: dict[str, object]
    data_through_session: str
    prepared_at: str


class MountedDatasetHeadStore:
    """One atomic mutable pointer to immutable mounted Generation content."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._generations = MountedGenerationStore(self._root)

    def current(self) -> DatasetHead | None:
        pointer = self.current_pointer()
        return None if pointer is None else self.resolve(pointer)

    def current_pointer(self) -> DatasetHeadPointer | None:
        root_fd = self._open_root()
        try:
            try:
                content = _read_optional_entry(root_fd, _HEAD_NAME)
            except OSError as error:
                raise DatasetHeadError("Dataset Head filesystem read failed") from error
        finally:
            os.close(root_fd)
        if content is None:
            return None
        return _pointer_from_manifest(_parse_head(content))

    def open_generation(self, manifest_sha256: str) -> MountedGeneration:
        return self._generations.open_generation(manifest_sha256)

    def resolve(self, pointer: DatasetHeadPointer) -> DatasetHead:
        try:
            generation = self._generations.open_generation(pointer.generation_manifest_sha256)
        except RuntimeError as error:
            raise DatasetHeadError("Dataset Head Generation is missing or invalid") from error
        expected = _head_from_generation(generation)
        if pointer != _pointer_from_head(expected):
            raise DatasetHeadError("Dataset Head projection is incompatible")
        return expected

    def compare_and_swap(
        self,
        *,
        expected_generation_manifest_sha256: str | None,
        candidate_generation_manifest_sha256: str,
    ) -> DatasetHead:
        candidate = self._generations.open_generation(candidate_generation_manifest_sha256)
        return self.compare_and_swap_generation(
            expected_generation_manifest_sha256=expected_generation_manifest_sha256,
            candidate=candidate,
        )

    def compare_and_swap_generation(
        self,
        *,
        expected_generation_manifest_sha256: str | None,
        candidate: MountedGeneration,
    ) -> DatasetHead:
        candidate_head = _head_from_generation(candidate)
        content = _head_bytes(candidate_head)
        root_fd = self._open_root()
        lock_fd: int | None = None
        try:
            lock_fd = _open_lock(root_fd)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            current_content = _read_optional_entry(root_fd, _HEAD_NAME)
            current = (
                None
                if current_content is None
                else _pointer_from_manifest(_parse_head(current_content))
            )
            current_identity = None if current is None else current.generation_manifest_sha256
            if current_identity != expected_generation_manifest_sha256:
                raise DatasetHeadConflict("Dataset Head changed before compare-and-swap")
            _replace_entry(root_fd, _HEAD_NAME, content)
            return candidate_head
        except DatasetHeadError:
            raise
        except OSError as error:
            raise DatasetHeadError("Dataset Head filesystem operation failed") from error
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(root_fd)

    def _open_root(self) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            return os.open(self._root, flags)
        except OSError as error:
            raise DatasetHeadError("Mounted Canonical Data Store is missing or unsafe") from error


def _head_from_generation(generation: MountedGeneration) -> DatasetHead:
    prepared_at = generation.preparation.get("prepared_at", "")
    if not prepared_at:
        raise DatasetHeadError("Dataset Head preparation metadata is missing")
    return DatasetHead(
        generation_manifest_sha256=generation.manifest_sha256,
        data_identity=generation.data_identity,
        dataset_coverage=dict(generation.dataset_coverage),
        data_through_session=generation.data_through_session,
        prepared_at=prepared_at,
        generation=generation,
    )


def _pointer_from_head(head: DatasetHead) -> DatasetHeadPointer:
    return DatasetHeadPointer(
        generation_manifest_sha256=head.generation_manifest_sha256,
        data_identity=head.data_identity,
        dataset_coverage=dict(head.dataset_coverage),
        data_through_session=head.data_through_session,
        prepared_at=head.prepared_at,
    )


def _pointer_from_manifest(manifest: dict[str, object]) -> DatasetHeadPointer:
    coverage = manifest["dataset_coverage"]
    if (
        not isinstance(coverage, dict)
        or set(coverage) != {"start", "end", "session_count"}
        or not isinstance(coverage["session_count"], int)
        or isinstance(coverage["session_count"], bool)
        or coverage["session_count"] <= 0
    ):
        raise DatasetHeadError("Dataset Head projection is incompatible")
    try:
        start = date.fromisoformat(str(coverage["start"]))
        end = date.fromisoformat(str(coverage["end"]))
        prepared_at = datetime.fromisoformat(str(manifest["prepared_at"]))
        _require_sha256(str(manifest["generation_manifest_sha256"]))
        _require_sha256(str(manifest["data_identity"]))
    except ValueError as error:
        raise DatasetHeadError("Dataset Head projection is incompatible") from error
    if (
        start > end
        or str(manifest["data_through_session"]) != end.isoformat()
        or prepared_at.tzinfo is None
    ):
        raise DatasetHeadError("Dataset Head projection is incompatible")
    return DatasetHeadPointer(
        generation_manifest_sha256=str(manifest["generation_manifest_sha256"]),
        data_identity=str(manifest["data_identity"]),
        dataset_coverage=dict(coverage),
        data_through_session=str(manifest["data_through_session"]),
        prepared_at=str(manifest["prepared_at"]),
    )


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid sha256")


def _head_projection(head: DatasetHead) -> dict[str, object]:
    return {
        "format": _HEAD_FORMAT,
        "version": _HEAD_VERSION,
        "generation_manifest_sha256": head.generation_manifest_sha256,
        "data_identity": head.data_identity,
        "dataset_coverage": head.dataset_coverage,
        "data_through_session": head.data_through_session,
        "prepared_at": head.prepared_at,
    }


def _head_bytes(head: DatasetHead) -> bytes:
    content = canonical_json_bytes(_head_projection(head))
    if len(content) > HEAD_MANIFEST_MAX_BYTES:
        raise DatasetHeadError("Dataset Head manifest exceeds its byte bound")
    return content


def _parse_head(content: bytes) -> dict[str, object]:
    if len(content) > HEAD_MANIFEST_MAX_BYTES:
        raise DatasetHeadError("Dataset Head manifest exceeds its byte bound")
    try:
        value = json.loads(content)
    except (TypeError, ValueError) as error:
        raise DatasetHeadError("Dataset Head manifest is malformed") from error
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "format",
            "version",
            "generation_manifest_sha256",
            "data_identity",
            "dataset_coverage",
            "data_through_session",
            "prepared_at",
        }
        or value.get("format") != _HEAD_FORMAT
        or value.get("version") != _HEAD_VERSION
        or canonical_json_bytes(value) != content
    ):
        raise DatasetHeadError("Dataset Head manifest is incompatible")
    return value


def _read_optional_entry(root_fd: int, name: str) -> bytes | None:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=root_fd)
    except FileNotFoundError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise DatasetHeadError("Dataset Head manifest is not a regular file")
        if metadata.st_size > HEAD_MANIFEST_MAX_BYTES:
            raise DatasetHeadError("Dataset Head manifest exceeds its byte bound")
        content = bytearray()
        while chunk := os.read(descriptor, 64 * 1024):
            content.extend(chunk)
        if len(content) != metadata.st_size:
            raise DatasetHeadError("Dataset Head changed while reading")
        return bytes(content)
    except OSError as error:
        raise DatasetHeadError("Dataset Head manifest could not be read") from error
    finally:
        os.close(descriptor)


def _open_lock(root_fd: int) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(_LOCK_NAME, flags, 0o600, dir_fd=root_fd)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise DatasetHeadError("Dataset Head lock is not a regular file")
    return descriptor


def _replace_entry(root_fd: int, name: str, content: bytes) -> None:
    temporary_name = f".head-candidate-{secrets.token_hex(12)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary_name, flags, 0o600, dir_fd=root_fd)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(
            temporary_name,
            name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
        )
        os.fsync(root_fd)
    finally:
        try:
            os.unlink(temporary_name, dir_fd=root_fd)
        except FileNotFoundError:
            pass


__all__ = (
    "DatasetHead",
    "DatasetHeadConflict",
    "DatasetHeadError",
    "DatasetHeadPointer",
    "HEAD_MANIFEST_MAX_BYTES",
    "MountedDatasetHeadStore",
)

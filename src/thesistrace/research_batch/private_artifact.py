from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel.research_chunks import (
    AlphaFactorChunkOutcome,
    AlphaFactorExecutionBinding,
    validated_alpha_factor_continuation,
)

PRIVATE_ARTIFACT_SCHEMA_VERSION = "research-batch-private-alpha-factor-v2"
PRIVATE_ARTIFACT_PUBLICATION_KIND = "research-batch-private-alpha-factor"
PRIVATE_ARTIFACT_MEDIA_TYPE = "application/vnd.thesistrace.alpha-factor-artifact"
PRIVATE_ARTIFACT_SERIALIZATION = {
    "format": "streaming-length-framed-canonical-json",
    "schema_version": PRIVATE_ARTIFACT_SCHEMA_VERSION,
}
_MAGIC = b"TTPAF2\n"
_FRAME_LENGTH_BYTES = 8
_MAX_FRAME_HEADER_BYTES = 16 * 1024**2


@dataclass(frozen=True)
class PrivateAlphaFactorChunk:
    first_session: str
    last_session: str
    outcome_payload: bytes
    completed_research_sessions: int
    final: bool


@dataclass(frozen=True)
class PrivateAlphaFactorArtifactMetadata:
    sha256: str
    byte_size: int
    chunk_count: int


class PrivateAlphaFactorArtifactWriter:
    """Write one complete private artifact without retaining prior Chunk payloads."""

    def __init__(
        self,
        path: Path,
        *,
        batch_id: str,
        binding: AlphaFactorExecutionBinding,
        maximum_chunk_payload_bytes: int,
    ) -> None:
        if (
            not batch_id
            or isinstance(maximum_chunk_payload_bytes, bool)
            or maximum_chunk_payload_bytes <= 0
        ):
            raise ValueError("Private Alpha-and-Factor artifact is invalid")
        self._path = path
        self._partial_path = path.with_name(f"{path.name}.partial")
        if path.exists() or self._partial_path.exists():
            raise ValueError("Private Alpha-and-Factor artifact path is not empty")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._partial_path.open("xb")
        self._binding = binding
        self._maximum_chunk_payload_bytes = maximum_chunk_payload_bytes
        self._digest = hashlib.sha256()
        self._byte_size = 0
        self._chunk_count = 0
        self._completed_research_sessions = 0
        self._final_seen = False
        self._closed = False
        try:
            self._write(_MAGIC)
            self._write_frame(
                {
                    "frame": "header",
                    "schema_version": PRIVATE_ARTIFACT_SCHEMA_VERSION,
                    "batch_id": batch_id,
                    "binding": binding.value_snapshot(),
                    "binding_checksum": binding.checksum,
                }
            )
        except Exception:
            self.abort()
            raise

    @property
    def partial_path(self) -> Path:
        return self._partial_path

    def append(self, chunk: PrivateAlphaFactorChunk) -> None:
        if self._closed or self._final_seen:
            raise ValueError("Private Alpha-and-Factor artifact is already complete")
        try:
            if (
                not chunk.first_session
                or not chunk.last_session
                or chunk.first_session > chunk.last_session
                or not chunk.outcome_payload
                or len(chunk.outcome_payload) > self._maximum_chunk_payload_bytes
            ):
                raise ValueError
            outcome = AlphaFactorChunkOutcome.from_compact_for_reuse(
                chunk.outcome_payload,
                binding=self._binding,
            )
            if (
                chunk.completed_research_sessions <= self._completed_research_sessions
                or outcome.completed_research_session_count != chunk.completed_research_sessions
            ):
                raise ValueError
            self._write_frame(
                {
                    "frame": "chunk",
                    "ordinal": self._chunk_count + 1,
                    "first_session": chunk.first_session,
                    "last_session": chunk.last_session,
                    "completed_research_sessions": chunk.completed_research_sessions,
                    "final": chunk.final,
                    "byte_size": len(chunk.outcome_payload),
                    "sha256": hashlib.sha256(chunk.outcome_payload).hexdigest(),
                },
                chunk.outcome_payload,
            )
            self._chunk_count += 1
            self._completed_research_sessions = chunk.completed_research_sessions
            self._final_seen = chunk.final
        except (ArithmeticError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("Private Alpha-and-Factor artifact Chunk is invalid") from None

    def complete(
        self,
        *,
        final_alpha_continuation: Mapping[str, object],
    ) -> PrivateAlphaFactorArtifactMetadata:
        if self._closed:
            raise ValueError("Private Alpha-and-Factor artifact writer is closed")
        try:
            continuation = validated_alpha_factor_continuation(final_alpha_continuation)
            if (
                not self._final_seen
                or self._chunk_count <= 0
                or continuation["binding_checksum"] != self._binding.checksum
                or int(continuation["completed_research_session_count"])
                != self._completed_research_sessions
            ):
                raise ValueError
            self._write_frame(
                {
                    "frame": "trailer",
                    "chunk_count": self._chunk_count,
                    "final_alpha_continuation": continuation,
                }
            )
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._closed = True
            os.replace(self._partial_path, self._path)
            return PrivateAlphaFactorArtifactMetadata(
                sha256=self._digest.hexdigest(),
                byte_size=self._byte_size,
                chunk_count=self._chunk_count,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.abort()
            raise ValueError("Private Alpha-and-Factor artifact is incomplete") from None

    def abort(self) -> None:
        if not self._closed:
            self._file.close()
            self._closed = True
        self._partial_path.unlink(missing_ok=True)

    def _write_frame(
        self,
        descriptor: Mapping[str, object],
        payload: bytes = b"",
    ) -> None:
        encoded = canonical_json_bytes(descriptor)
        if not 0 < len(encoded) <= _MAX_FRAME_HEADER_BYTES:
            raise ValueError("Private Alpha-and-Factor frame header is invalid")
        self._write(len(encoded).to_bytes(_FRAME_LENGTH_BYTES, "big"))
        self._write(encoded)
        if payload:
            self._write(payload)

    def _write(self, content: bytes) -> None:
        self._file.write(content)
        self._digest.update(content)
        self._byte_size += len(content)


class PrivateAlphaFactorArtifactReader:
    """Validate and iterate one private artifact while retaining one Chunk payload."""

    def __init__(
        self,
        path: Path,
        *,
        expected_batch_id: str,
        expected_binding: AlphaFactorExecutionBinding,
        maximum_chunk_payload_bytes: int,
    ) -> None:
        if isinstance(maximum_chunk_payload_bytes, bool) or maximum_chunk_payload_bytes <= 0:
            raise ValueError("Private Alpha-and-Factor artifact is invalid")
        self._path = path
        self._expected_batch_id = expected_batch_id
        self._expected_binding = expected_binding
        self._maximum_chunk_payload_bytes = maximum_chunk_payload_bytes
        self._file = None
        self._digest = hashlib.sha256()
        self._byte_size = 0
        self._chunk_count = 0
        self._completed_research_sessions = 0
        self._final_seen = False
        self._finished = False
        self._iterated = False
        self._final_alpha_continuation: dict[str, object] | None = None

    def __enter__(self) -> PrivateAlphaFactorArtifactReader:
        try:
            self._file = self._path.open("rb")
            if self._read_exact(len(_MAGIC)) != _MAGIC:
                raise ValueError
            header = self._read_frame_descriptor()
            if (
                set(header)
                != {
                    "frame",
                    "schema_version",
                    "batch_id",
                    "binding",
                    "binding_checksum",
                }
                or header["frame"] != "header"
                or header["schema_version"] != PRIVATE_ARTIFACT_SCHEMA_VERSION
                or header["batch_id"] != self._expected_batch_id
                or header["binding"] != self._expected_binding.value_snapshot()
                or header["binding_checksum"] != self._expected_binding.checksum
            ):
                raise ValueError
            return self
        except (OSError, ArithmeticError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            if self._file is not None:
                self._file.close()
            raise ValueError("Private Alpha-and-Factor artifact is invalid") from None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._file is not None:
            self._file.close()
        if exc_type is None and not self._finished:
            raise ValueError("Private Alpha-and-Factor artifact was not fully consumed")

    def __iter__(self) -> Iterator[PrivateAlphaFactorChunk]:
        if self._file is None or self._iterated:
            raise ValueError("Private Alpha-and-Factor artifact reader is invalid")
        self._iterated = True
        try:
            while True:
                descriptor = self._read_frame_descriptor()
                frame = descriptor.get("frame")
                if frame == "trailer":
                    self._finish(descriptor)
                    return
                if (
                    frame != "chunk"
                    or set(descriptor)
                    != {
                        "frame",
                        "ordinal",
                        "first_session",
                        "last_session",
                        "completed_research_sessions",
                        "final",
                        "byte_size",
                        "sha256",
                    }
                    or descriptor["ordinal"] != self._chunk_count + 1
                    or not isinstance(descriptor["first_session"], str)
                    or not descriptor["first_session"]
                    or not isinstance(descriptor["last_session"], str)
                    or not descriptor["last_session"]
                    or descriptor["first_session"] > descriptor["last_session"]
                    or not isinstance(descriptor["completed_research_sessions"], int)
                    or isinstance(descriptor["completed_research_sessions"], bool)
                    or not isinstance(descriptor["final"], bool)
                    or not isinstance(descriptor["byte_size"], int)
                    or isinstance(descriptor["byte_size"], bool)
                    or descriptor["byte_size"] <= 0
                    or descriptor["byte_size"] > self._maximum_chunk_payload_bytes
                    or not isinstance(descriptor["sha256"], str)
                    or self._final_seen
                ):
                    raise ValueError
                payload = self._read_exact(int(descriptor["byte_size"]))
                if hashlib.sha256(payload).hexdigest() != descriptor["sha256"]:
                    raise ValueError
                outcome = AlphaFactorChunkOutcome.from_compact_for_reuse(
                    payload,
                    binding=self._expected_binding,
                )
                completed = int(descriptor["completed_research_sessions"])
                if (
                    completed <= self._completed_research_sessions
                    or outcome.completed_research_session_count != completed
                ):
                    raise ValueError
                # Do not suspend the frame iterator while retaining a second
                # decoded Chunk.  The consumer may decode the yielded payload
                # for Strategy execution, so only the canonical bytes cross
                # the yield boundary.
                del outcome
                self._chunk_count += 1
                self._completed_research_sessions = completed
                self._final_seen = bool(descriptor["final"])
                yield PrivateAlphaFactorChunk(
                    first_session=str(descriptor["first_session"]),
                    last_session=str(descriptor["last_session"]),
                    outcome_payload=payload,
                    completed_research_sessions=completed,
                    final=self._final_seen,
                )
        except (OSError, ArithmeticError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("Private Alpha-and-Factor artifact is invalid") from None

    @property
    def final_alpha_continuation(self) -> dict[str, object]:
        if self._final_alpha_continuation is None:
            raise ValueError("Private Alpha-and-Factor artifact is not complete")
        return dict(self._final_alpha_continuation)

    @property
    def metadata(self) -> PrivateAlphaFactorArtifactMetadata:
        if not self._finished:
            raise ValueError("Private Alpha-and-Factor artifact is not complete")
        return PrivateAlphaFactorArtifactMetadata(
            sha256=self._digest.hexdigest(),
            byte_size=self._byte_size,
            chunk_count=self._chunk_count,
        )

    def _finish(self, descriptor: Mapping[str, object]) -> None:
        if (
            set(descriptor) != {"frame", "chunk_count", "final_alpha_continuation"}
            or not isinstance(descriptor["chunk_count"], int)
            or isinstance(descriptor["chunk_count"], bool)
            or descriptor["chunk_count"] != self._chunk_count
            or not self._final_seen
        ):
            raise ValueError
        continuation = validated_alpha_factor_continuation(descriptor["final_alpha_continuation"])
        if (
            continuation["binding_checksum"] != self._expected_binding.checksum
            or int(continuation["completed_research_session_count"])
            != self._completed_research_sessions
            or self._read_optional_byte()
        ):
            raise ValueError
        self._final_alpha_continuation = continuation
        self._finished = True

    def _read_frame_descriptor(self) -> dict[str, object]:
        encoded_size = self._read_exact(_FRAME_LENGTH_BYTES)
        size = int.from_bytes(encoded_size, "big")
        if not 0 < size <= _MAX_FRAME_HEADER_BYTES:
            raise ValueError
        encoded = self._read_exact(size)
        value = json.loads(encoded)
        if not isinstance(value, dict) or canonical_json_bytes(value) != encoded:
            raise ValueError
        return value

    def _read_exact(self, size: int) -> bytes:
        assert self._file is not None
        content = self._file.read(size)
        if len(content) != size:
            raise ValueError
        self._digest.update(content)
        self._byte_size += len(content)
        return content

    def _read_optional_byte(self) -> bytes:
        assert self._file is not None
        content = self._file.read(1)
        if content:
            self._digest.update(content)
            self._byte_size += 1
        return content


def validate_private_alpha_factor_artifact(
    path: Path,
    *,
    expected_batch_id: str,
    expected_binding: AlphaFactorExecutionBinding,
    maximum_chunk_payload_bytes: int,
) -> PrivateAlphaFactorArtifactMetadata:
    with PrivateAlphaFactorArtifactReader(
        path,
        expected_batch_id=expected_batch_id,
        expected_binding=expected_binding,
        maximum_chunk_payload_bytes=maximum_chunk_payload_bytes,
    ) as reader:
        for _chunk in reader:
            pass
        return reader.metadata

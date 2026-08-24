from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel.research_chunks import (
    AlphaFactorChunkOutcome,
    AlphaFactorExecutionBinding,
    validated_alpha_factor_continuation,
)

PRIVATE_ARTIFACT_SCHEMA_VERSION = "research-batch-private-alpha-factor-v1"
PRIVATE_ARTIFACT_PUBLICATION_KIND = "research-batch-private-alpha-factor"
PRIVATE_ARTIFACT_MEDIA_TYPE = "application/vnd.thesistrace.alpha-factor-artifact"
PRIVATE_ARTIFACT_SERIALIZATION = {
    "format": "length-framed-canonical-json",
    "schema_version": PRIVATE_ARTIFACT_SCHEMA_VERSION,
}
_MAGIC = b"TTPAF1\n"
_HEADER_LENGTH_BYTES = 8


@dataclass(frozen=True)
class PrivateAlphaFactorChunk:
    outcome_payload: bytes
    completed_research_sessions: int
    final: bool


@dataclass(frozen=True)
class PrivateAlphaFactorArtifact:
    batch_id: str
    binding: AlphaFactorExecutionBinding
    chunks: tuple[PrivateAlphaFactorChunk, ...]
    final_alpha_continuation: dict[str, object]
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def encode_private_alpha_factor_artifact(
    *,
    batch_id: str,
    binding: AlphaFactorExecutionBinding,
    chunks: Sequence[PrivateAlphaFactorChunk],
    final_alpha_continuation: Mapping[str, object],
) -> bytes:
    if not batch_id or not chunks or not chunks[-1].final:
        raise ValueError("Private Alpha-and-Factor artifact is incomplete")
    if any(chunk.final for chunk in chunks[:-1]):
        raise ValueError("Private Alpha-and-Factor artifact has an early final Chunk")
    continuation = validated_alpha_factor_continuation(final_alpha_continuation)
    if continuation["binding_checksum"] != binding.checksum:
        raise ValueError("Private Alpha-and-Factor continuation binding is invalid")
    descriptors: list[dict[str, object]] = []
    payloads: list[bytes] = []
    previous = 0
    for ordinal, chunk in enumerate(chunks, start=1):
        outcome = AlphaFactorChunkOutcome.from_compact_for_reuse(
            chunk.outcome_payload,
            binding=binding,
        )
        if (
            chunk.completed_research_sessions <= previous
            or outcome.completed_research_session_count != chunk.completed_research_sessions
        ):
            raise ValueError("Private Alpha-and-Factor Chunk progress is invalid")
        previous = chunk.completed_research_sessions
        descriptors.append(
            {
                "ordinal": ordinal,
                "completed_research_sessions": chunk.completed_research_sessions,
                "final": chunk.final,
                "byte_size": len(chunk.outcome_payload),
                "sha256": hashlib.sha256(chunk.outcome_payload).hexdigest(),
            }
        )
        payloads.append(chunk.outcome_payload)
        del outcome
    if int(continuation["completed_research_session_count"]) != previous:
        raise ValueError("Private Alpha-and-Factor final progress is invalid")
    header = canonical_json_bytes(
        {
            "schema_version": PRIVATE_ARTIFACT_SCHEMA_VERSION,
            "batch_id": batch_id,
            "binding": binding.value_snapshot(),
            "binding_checksum": binding.checksum,
            "chunks": descriptors,
            "final_alpha_continuation": continuation,
        }
    )
    return b"".join(
        (
            _MAGIC,
            len(header).to_bytes(_HEADER_LENGTH_BYTES, "big"),
            header,
            *payloads,
        )
    )


def decode_private_alpha_factor_artifact(
    content: bytes,
    *,
    expected_batch_id: str,
    expected_binding: AlphaFactorExecutionBinding,
) -> PrivateAlphaFactorArtifact:
    try:
        header, payload_offset = _read_header(content)
        if (
            set(header)
            != {
                "schema_version",
                "batch_id",
                "binding",
                "binding_checksum",
                "chunks",
                "final_alpha_continuation",
            }
            or header["schema_version"] != PRIVATE_ARTIFACT_SCHEMA_VERSION
            or header["batch_id"] != expected_batch_id
            or header["binding"] != expected_binding.value_snapshot()
            or header["binding_checksum"] != expected_binding.checksum
            or not isinstance(header["chunks"], list)
        ):
            raise ValueError
        chunks: list[PrivateAlphaFactorChunk] = []
        offset = payload_offset
        previous = 0
        for ordinal, raw in enumerate(header["chunks"], start=1):
            if (
                not isinstance(raw, dict)
                or set(raw)
                != {
                    "ordinal",
                    "completed_research_sessions",
                    "final",
                    "byte_size",
                    "sha256",
                }
                or raw["ordinal"] != ordinal
                or not isinstance(raw["completed_research_sessions"], int)
                or not isinstance(raw["final"], bool)
                or not isinstance(raw["byte_size"], int)
                or raw["byte_size"] <= 0
                or not isinstance(raw["sha256"], str)
            ):
                raise ValueError
            end = offset + raw["byte_size"]
            payload = content[offset:end]
            if (
                len(payload) != raw["byte_size"]
                or hashlib.sha256(payload).hexdigest() != raw["sha256"]
            ):
                raise ValueError
            outcome = AlphaFactorChunkOutcome.from_compact_for_reuse(
                payload,
                binding=expected_binding,
            )
            if (
                raw["completed_research_sessions"] <= previous
                or outcome.completed_research_session_count != raw["completed_research_sessions"]
            ):
                raise ValueError
            previous = raw["completed_research_sessions"]
            chunks.append(
                PrivateAlphaFactorChunk(
                    outcome_payload=payload,
                    completed_research_sessions=raw["completed_research_sessions"],
                    final=raw["final"],
                )
            )
            del outcome
            offset = end
        if offset != len(content):
            raise ValueError
        continuation = validated_alpha_factor_continuation(header["final_alpha_continuation"])
        if (
            not chunks
            or not chunks[-1].final
            or any(chunk.final for chunk in chunks[:-1])
            or continuation["binding_checksum"] != expected_binding.checksum
            or int(continuation["completed_research_session_count"]) != previous
        ):
            raise ValueError
        return PrivateAlphaFactorArtifact(
            batch_id=expected_batch_id,
            binding=expected_binding,
            chunks=tuple(chunks),
            final_alpha_continuation=continuation,
            content=content,
        )
    except (ArithmeticError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("Private Alpha-and-Factor artifact is invalid") from None


def _read_header(content: bytes) -> tuple[dict[str, object], int]:
    prefix_size = len(_MAGIC) + _HEADER_LENGTH_BYTES
    if len(content) <= prefix_size or content[: len(_MAGIC)] != _MAGIC:
        raise ValueError
    header_size = int.from_bytes(content[len(_MAGIC) : prefix_size], "big")
    header_end = prefix_size + header_size
    if header_size <= 0 or header_end >= len(content):
        raise ValueError
    header_bytes = content[prefix_size:header_end]
    header = json.loads(header_bytes)
    if not isinstance(header, dict) or canonical_json_bytes(header) != header_bytes:
        raise ValueError
    return header, header_end

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from thesistrace.objects import (
    ParquetContractError,
    ParquetWriterContract,
    canonical_json_bytes,
    parquet_bytes,
)

MANIFEST_SCHEMA_VERSION = 1
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class PublicationPreparationError(ValueError):
    pass


class PublicationVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class JsonPayload:
    value: object


@dataclass(frozen=True)
class ParquetRowsPayload:
    rows: Sequence[Mapping[str, object]]
    contract: ParquetWriterContract


type PublicationPayload = JsonPayload | ParquetRowsPayload


@dataclass(frozen=True)
class PreparedPublication:
    manifest_sha256: str
    _manifest_bytes: bytes = field(repr=False)

    @property
    def kind(self) -> str:
        return str(_load_manifest(self._manifest_bytes, self.manifest_sha256)["kind"])

    @property
    def object_count(self) -> int:
        return len(_manifest_objects(_load_manifest(self._manifest_bytes, self.manifest_sha256)))

    @property
    def payload_sha256s(self) -> dict[str, str]:
        return {
            str(item["name"]): str(item["sha256"])
            for item in _manifest_objects(
                _load_manifest(self._manifest_bytes, self.manifest_sha256)
            )
        }


@dataclass(frozen=True)
class VerifiedPayload:
    media_type: str
    content: bytes
    serialization: Mapping[str, object]


@dataclass(frozen=True)
class VerifiedBundle:
    kind: str
    manifest_sha256: str
    provenance: object
    payloads: Mapping[str, VerifiedPayload]


class Publication:
    def __init__(self, s3: BaseClient, *, bucket: str) -> None:
        if not bucket:
            raise ValueError("Publication bucket is required")
        self._s3 = s3
        self._bucket = bucket

    def prepare(
        self,
        *,
        kind: str,
        payloads: Mapping[str, PublicationPayload],
        provenance: object,
    ) -> PreparedPublication:
        _require_identifier(kind, subject="publication kind")
        if not payloads:
            raise PublicationPreparationError("a publication requires at least one payload")
        canonical_provenance = _canonical_json_value(provenance, subject="provenance")
        self._ensure_bucket()

        manifest_objects: list[dict[str, object]] = []
        for name in sorted(payloads):
            _require_identifier(name, subject="payload name")
            content, media_type, serialization = _serialize_payload(payloads[name])
            digest = hashlib.sha256(content).hexdigest()
            self._put_immutable(digest, content, media_type=media_type)
            manifest_objects.append(
                {
                    "bytes": len(content),
                    "media_type": media_type,
                    "name": name,
                    "serialization": serialization,
                    "sha256": digest,
                }
            )

        manifest = {
            "kind": kind,
            "objects": manifest_objects,
            "provenance": canonical_provenance,
            "schema_version": MANIFEST_SCHEMA_VERSION,
        }
        manifest_bytes = canonical_json_bytes(manifest)
        return PreparedPublication(
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            _manifest_bytes=manifest_bytes,
        )

    def verify_prepared(self, prepared: PreparedPublication) -> VerifiedBundle:
        manifest = _load_manifest(prepared._manifest_bytes, prepared.manifest_sha256)
        objects = _manifest_objects(manifest)
        verified_payloads: dict[str, VerifiedPayload] = {}
        for item in objects:
            name, digest, expected_bytes, media_type, serialization = _object_descriptor(item)
            content = self._read_verified(digest, expected_bytes)
            verified_payloads[name] = VerifiedPayload(
                media_type=media_type,
                content=content,
                serialization=serialization,
            )
        return VerifiedBundle(
            kind=str(manifest["kind"]),
            manifest_sha256=prepared.manifest_sha256,
            provenance=manifest["provenance"],
            payloads=verified_payloads,
        )

    def _ensure_bucket(self) -> None:
        try:
            self._s3.head_bucket(Bucket=self._bucket)
            return
        except ClientError as error:
            if _error_code(error) not in {"404", "NoSuchBucket", "NotFound"}:
                raise PublicationPreparationError("Publication bucket is unavailable") from error
        try:
            self._s3.create_bucket(Bucket=self._bucket)
        except ClientError as error:
            if _error_code(error) not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                raise PublicationPreparationError(
                    "Publication bucket could not be created"
                ) from error

    def _put_immutable(self, digest: str, content: bytes, *, media_type: str) -> None:
        if self._object_exists(digest):
            self._verify_existing(digest, content)
            return
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=_object_key(digest),
                Body=content,
                ContentLength=len(content),
                ContentType=media_type,
                IfNoneMatch="*",
                Metadata={"sha256": digest},
            )
        except ClientError as error:
            if _error_code(error) not in {
                "409",
                "412",
                "ConditionalRequestConflict",
                "PreconditionFailed",
            }:
                raise PublicationPreparationError("Publication object upload failed") from error
        self._verify_existing(digest, content)

    def _object_exists(self, digest: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=_object_key(digest))
            return True
        except ClientError as error:
            if _error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise PublicationPreparationError("Publication object lookup failed") from error

    def _verify_existing(self, digest: str, expected: bytes) -> None:
        try:
            actual = self._s3.get_object(
                Bucket=self._bucket,
                Key=_object_key(digest),
            )["Body"].read()
        except ClientError as error:
            raise PublicationVerificationError("Publication object is missing") from error
        if actual != expected or hashlib.sha256(actual).hexdigest() != digest:
            raise PublicationVerificationError(
                "Publication content address contains different bytes"
            )

    def _read_verified(self, digest: str, expected_bytes: int) -> bytes:
        try:
            content = self._s3.get_object(
                Bucket=self._bucket,
                Key=_object_key(digest),
            )["Body"].read()
        except ClientError as error:
            raise PublicationVerificationError("Publication object is missing") from error
        if len(content) != expected_bytes:
            raise PublicationVerificationError("Publication object length is invalid")
        if hashlib.sha256(content).hexdigest() != digest:
            raise PublicationVerificationError("Publication object checksum is invalid")
        return content


def _serialize_payload(
    payload: PublicationPayload,
) -> tuple[bytes, str, dict[str, object]]:
    if isinstance(payload, JsonPayload):
        try:
            content = canonical_json_bytes(payload.value)
        except (TypeError, ValueError) as error:
            raise PublicationPreparationError("JSON payload is not canonicalizable") from error
        return content, "application/json", {"format": "canonical-json", "version": 1}
    if isinstance(payload, ParquetRowsPayload):
        try:
            content = parquet_bytes(payload.rows, payload.contract)
        except ParquetContractError as error:
            raise PublicationPreparationError("Parquet payload violates its contract") from error
        return (
            content,
            "application/vnd.apache.parquet",
            {"format": "canonical-parquet", "writer_contract": payload.contract.descriptor()},
        )
    raise PublicationPreparationError("unsupported Publication payload type")


def _canonical_json_value(value: object, *, subject: str) -> object:
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise PublicationPreparationError(f"{subject} is not canonicalizable JSON") from error


def _require_identifier(value: str, *, subject: str) -> None:
    if not isinstance(value, str) or IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise PublicationPreparationError(f"{subject} must be a stable identifier")


def _object_key(digest: str) -> str:
    return f"publication/v1/sha256/{digest[:2]}/{digest}"


def _load_manifest(payload: bytes, expected_sha256: str) -> dict[str, Any]:
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise PublicationVerificationError("Publication manifest checksum is invalid")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationVerificationError("Publication manifest is invalid JSON") from error
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise PublicationVerificationError("Publication manifest is not canonical")
    if value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise PublicationVerificationError("Publication manifest schema is unsupported")
    if not isinstance(value.get("kind"), str) or "provenance" not in value:
        raise PublicationVerificationError("Publication manifest is incomplete")
    return value


def _manifest_objects(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects:
        raise PublicationVerificationError("Publication manifest objects are invalid")
    if not all(isinstance(item, dict) for item in objects):
        raise PublicationVerificationError("Publication manifest object is invalid")
    return objects


def _object_descriptor(
    item: Mapping[str, Any],
) -> tuple[str, str, int, str, Mapping[str, object]]:
    if set(item) != {"bytes", "media_type", "name", "serialization", "sha256"}:
        raise PublicationVerificationError("Publication object descriptor is malformed")
    name = item["name"]
    digest = item["sha256"]
    expected_bytes = item["bytes"]
    media_type = item["media_type"]
    serialization = item["serialization"]
    if (
        not isinstance(name, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
        or not isinstance(media_type, str)
        or not isinstance(serialization, dict)
    ):
        raise PublicationVerificationError("Publication object descriptor is invalid")
    return name, digest, expected_bytes, media_type, serialization


def _error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))

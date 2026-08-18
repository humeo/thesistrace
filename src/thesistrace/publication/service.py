from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from botocore.client import BaseClient
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    ReadTimeoutError,
)
from pyarrow import ArrowException

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.publication.serialization import (
    ParquetContractError,
    ParquetWriterContract,
    canonical_json_bytes,
    parquet_bytes,
)

MANIFEST_SCHEMA_VERSION = 1
OBJECT_READ_ATTEMPTS = 3
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
PUBLICATION_MUTATION_LOCK = "thesistrace-publication-mutation"
TRANSIENT_S3_ERRORS = (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    ReadTimeoutError,
)


class PublicationPreparationError(ValueError):
    pass


class PublicationVerificationError(ValueError):
    pass


class PublicationUnavailableError(
    PublicationPreparationError,
    PublicationVerificationError,
):
    """The object store could not complete an otherwise valid operation."""


class PublicationNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class JsonPayload:
    value: object


@dataclass(frozen=True)
class ParquetRowsPayload:
    rows: Sequence[Mapping[str, object]]
    contract: ParquetWriterContract


@dataclass(frozen=True)
class StagedPayload:
    sha256: str
    byte_size: int
    media_type: str
    serialization: Mapping[str, object]


type PublicationPayload = JsonPayload | ParquetRowsPayload | StagedPayload
type StagingAuthority = Callable[[], AbstractContextManager[None]]


def _staging_authority(
    authority: StagingAuthority | None,
) -> AbstractContextManager[None]:
    return nullcontext() if authority is None else authority()


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

    @property
    def exact_bytes(self) -> int:
        manifest = _load_manifest(self._manifest_bytes, self.manifest_sha256)
        return len(self._manifest_bytes) + sum(
            int(item["bytes"]) for item in _manifest_objects(manifest)
        )


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


@dataclass(frozen=True)
class PublishedRef:
    manifest_sha256: str
    kind: str
    provenance: object


def lock_publication_mutation(transaction: PostgresTransaction) -> None:
    """Take the publication fence before any product-row locks in a write transaction."""
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (PUBLICATION_MUTATION_LOCK,),
    )


class Publication:
    def __init__(
        self,
        database: PostgresDatabase,
        s3: BaseClient,
        *,
        bucket: str,
    ) -> None:
        if not bucket:
            raise ValueError("Publication bucket is required")
        self._database = database
        self._s3 = s3
        self._bucket = bucket
        self._bucket_ready = False

    def storage_is_available(self) -> bool:
        try:
            return self._s3.list_buckets()["ResponseMetadata"]["HTTPStatusCode"] == 200
        except ClientError:
            return False

    def prepare(
        self,
        *,
        kind: str,
        payloads: Mapping[str, PublicationPayload],
        provenance: object,
        staging_authority: StagingAuthority | None = None,
    ) -> PreparedPublication:
        _require_identifier(kind, subject="publication kind")
        if not payloads:
            raise PublicationPreparationError("a publication requires at least one payload")
        canonical_provenance = _canonical_json_value(provenance, subject="provenance")
        serialized: list[tuple[str, bytes, str, dict[str, object]]] = []
        staged: list[tuple[str, StagedPayload]] = []
        for name in sorted(payloads):
            with _staging_authority(staging_authority):
                pass
            _require_identifier(name, subject="payload name")
            payload = payloads[name]
            if isinstance(payload, StagedPayload):
                self._read_verified(
                    payload.sha256,
                    payload.byte_size,
                    staging_authority=staging_authority,
                )
                staged.append((name, payload))
            else:
                content, media_type, serialization = _serialize_payload(payload)
                serialized.append((name, content, media_type, serialization))

        self._ensure_bucket(staging_authority=staging_authority)
        manifest_objects: list[dict[str, object]] = []
        for name, content, media_type, serialization in serialized:
            digest = hashlib.sha256(content).hexdigest()
            self._put_immutable(
                digest,
                content,
                media_type=media_type,
                staging_authority=staging_authority,
            )
            manifest_objects.append(
                {
                    "bytes": len(content),
                    "media_type": media_type,
                    "name": name,
                    "serialization": serialization,
                    "sha256": digest,
                }
            )
        manifest_objects.extend(
            {
                "bytes": payload.byte_size,
                "media_type": payload.media_type,
                "name": name,
                "serialization": dict(payload.serialization),
                "sha256": payload.sha256,
            }
            for name, payload in staged
        )
        manifest_objects.sort(key=lambda item: str(item["name"]))

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

    def stage(
        self,
        payload: JsonPayload | ParquetRowsPayload,
        *,
        staging_authority: StagingAuthority | None = None,
    ) -> StagedPayload:
        content, media_type, serialization = _serialize_payload(payload)
        self._ensure_bucket(staging_authority=staging_authority)
        digest = hashlib.sha256(content).hexdigest()
        self._put_immutable(
            digest,
            content,
            media_type=media_type,
            staging_authority=staging_authority,
        )
        return StagedPayload(
            sha256=digest,
            byte_size=len(content),
            media_type=media_type,
            serialization=serialization,
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

    def record(
        self,
        transaction: PostgresTransaction,
        prepared: PreparedPublication,
    ) -> PublishedRef:
        lock_publication_mutation(transaction)
        self.verify_prepared(prepared)
        manifest = _load_manifest(prepared._manifest_bytes, prepared.manifest_sha256)
        objects = _manifest_objects(manifest)

        for item in objects:
            _name, digest, byte_size, _media_type, _serialization = _object_descriptor(item)
            transaction.execute(
                """
                INSERT INTO publication.objects (sha256, byte_size)
                VALUES (%s, %s)
                ON CONFLICT (sha256) DO NOTHING
                """,
                (digest, byte_size),
            )
            stored = transaction.execute(
                "SELECT byte_size FROM publication.objects WHERE sha256 = %s",
                (digest,),
            ).fetchone()
            if stored != {"byte_size": byte_size}:
                raise PublicationVerificationError("Publication object record conflicts")

        transaction.execute(
            """
            INSERT INTO publication.manifests (
                sha256,
                schema_version,
                kind,
                manifest_bytes
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (sha256) DO NOTHING
            """,
            (
                prepared.manifest_sha256,
                manifest["schema_version"],
                manifest["kind"],
                prepared._manifest_bytes,
            ),
        )
        stored_manifest = transaction.execute(
            """
            SELECT schema_version, kind, manifest_bytes
            FROM publication.manifests
            WHERE sha256 = %s
            """,
            (prepared.manifest_sha256,),
        ).fetchone()
        if stored_manifest is None or (
            stored_manifest["schema_version"] != manifest["schema_version"]
            or stored_manifest["kind"] != manifest["kind"]
            or bytes(stored_manifest["manifest_bytes"]) != prepared._manifest_bytes
        ):
            raise PublicationVerificationError("Publication manifest record conflicts")

        for ordinal, item in enumerate(objects):
            name, digest, _byte_size, _media_type, _serialization = _object_descriptor(item)
            transaction.execute(
                """
                INSERT INTO publication.manifest_objects (
                    manifest_sha256,
                    ordinal,
                    logical_name,
                    object_sha256
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (prepared.manifest_sha256, ordinal, name, digest),
            )
        self._verify_recorded_links(transaction, prepared.manifest_sha256, objects)
        return PublishedRef(
            manifest_sha256=prepared.manifest_sha256,
            kind=str(manifest["kind"]),
            provenance=manifest["provenance"],
        )

    def read(self, published_ref: PublishedRef) -> VerifiedBundle:
        with self._database.transaction() as transaction:
            return self.read_in_transaction(transaction, published_ref)

    def read_in_transaction(
        self,
        transaction: PostgresTransaction,
        published_ref: PublishedRef,
    ) -> VerifiedBundle:
        row = transaction.execute(
            """
            SELECT schema_version, kind, manifest_bytes
            FROM publication.manifests
            WHERE sha256 = %s
            """,
            (published_ref.manifest_sha256,),
        ).fetchone()
        if row is None:
            raise PublicationNotFoundError("Publication is not committed")
        manifest_bytes = bytes(row["manifest_bytes"])
        manifest = _load_manifest(manifest_bytes, published_ref.manifest_sha256)
        objects = _manifest_objects(manifest)
        self._verify_recorded_links(transaction, published_ref.manifest_sha256, objects)
        if row["schema_version"] != manifest["schema_version"]:
            raise PublicationVerificationError(
                "Publication manifest schema record does not match manifest"
            )
        if row["kind"] != published_ref.kind or manifest["kind"] != published_ref.kind:
            raise PublicationVerificationError("PublishedRef kind does not match manifest")
        if canonical_json_bytes(manifest["provenance"]) != canonical_json_bytes(
            published_ref.provenance
        ):
            raise PublicationVerificationError("PublishedRef provenance does not match manifest")
        return self.verify_prepared(
            PreparedPublication(
                manifest_sha256=published_ref.manifest_sha256,
                _manifest_bytes=manifest_bytes,
            )
        )

    def find_orphan_sha256s(self, *, uploaded_before: datetime) -> tuple[str, ...]:
        if uploaded_before.tzinfo is None or uploaded_before.utcoffset() is None:
            raise ValueError("orphan cutoff must be timezone-aware")
        uploaded: set[str] = set()
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix="publication/v1/sha256/"):
            for item in page.get("Contents", []):
                last_modified = item.get("LastModified")
                if not isinstance(last_modified, datetime):
                    raise PublicationVerificationError(
                        "Publication object listing has no modification time"
                    )
                if last_modified > uploaded_before:
                    continue
                digest = _digest_from_object_key(str(item["Key"]))
                if digest is not None:
                    uploaded.add(digest)
        # Read committed truth after the object snapshot to narrow the race with
        # a concurrent record. Cleanup must still use an aged cutoff and recheck.
        with self._database.transaction() as transaction:
            recorded = {
                str(row["sha256"])
                for row in transaction.execute("SELECT sha256 FROM publication.objects").fetchall()
            }
        return tuple(sorted(uploaded - recorded))

    def release_manifest_in_transaction(
        self,
        transaction: PostgresTransaction,
        manifest_sha256: str,
        *,
        still_referenced: bool,
    ) -> None:
        """Release one product reference and enqueue only newly unreferenced bytes."""
        lock_publication_mutation(transaction)
        if still_referenced:
            return
        objects = transaction.execute(
            """
            SELECT object_sha256
            FROM publication.manifest_objects
            WHERE manifest_sha256 = %s
            """,
            (manifest_sha256,),
        ).fetchall()
        transaction.execute(
            "DELETE FROM publication.manifest_objects WHERE manifest_sha256 = %s",
            (manifest_sha256,),
        )
        transaction.execute(
            "DELETE FROM publication.manifests WHERE sha256 = %s",
            (manifest_sha256,),
        )
        for row in objects:
            digest = str(row["object_sha256"])
            transaction.execute(
                """
                INSERT INTO publication.object_deletions (object_sha256)
                SELECT %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM publication.manifest_objects
                    WHERE object_sha256 = %s
                )
                ON CONFLICT (object_sha256) DO NOTHING
                """,
                (digest, digest),
            )

    def collect_one_pending_deletion(self) -> bool:
        """Delete one unreferenced immutable object with a durable retry record."""
        with self._database.transaction() as transaction:
            lock_publication_mutation(transaction)
            row = transaction.execute(
                """
                SELECT object_sha256
                FROM publication.object_deletions
                ORDER BY created_at, object_sha256
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return False
            digest = str(row["object_sha256"])
            referenced = transaction.execute(
                """
                SELECT 1
                FROM publication.manifest_objects
                WHERE object_sha256 = %s
                LIMIT 1
                """,
                (digest,),
            ).fetchone()
            if referenced is not None:
                transaction.execute(
                    "DELETE FROM publication.object_deletions WHERE object_sha256 = %s",
                    (digest,),
                )
                return True
            self._delete_immutable(digest)
            transaction.execute(
                "DELETE FROM publication.object_deletions WHERE object_sha256 = %s",
                (digest,),
            )
            transaction.execute(
                """
                DELETE FROM publication.objects
                WHERE sha256 = %s
                  AND NOT EXISTS (
                    SELECT 1
                    FROM publication.manifest_objects
                    WHERE object_sha256 = %s
                  )
                """,
                (digest, digest),
            )
        return True

    @staticmethod
    def _verify_recorded_links(
        transaction: PostgresTransaction,
        manifest_sha256: str,
        objects: Sequence[Mapping[str, Any]],
    ) -> None:
        rows = transaction.execute(
            """
            SELECT
                mo.ordinal,
                mo.logical_name,
                mo.object_sha256,
                o.byte_size
            FROM publication.manifest_objects AS mo
            JOIN publication.objects AS o ON o.sha256 = mo.object_sha256
            WHERE mo.manifest_sha256 = %s
            ORDER BY mo.ordinal
            """,
            (manifest_sha256,),
        ).fetchall()
        expected = []
        for ordinal, item in enumerate(objects):
            name, digest, byte_size, _media_type, _serialization = _object_descriptor(item)
            expected.append(
                {
                    "ordinal": ordinal,
                    "logical_name": name,
                    "object_sha256": digest,
                    "byte_size": byte_size,
                }
            )
        if rows != expected:
            raise PublicationVerificationError("Publication manifest-object records conflict")

    def _ensure_bucket(self, *, staging_authority: StagingAuthority | None) -> None:
        if self._bucket_ready:
            return
        try:
            with _staging_authority(staging_authority):
                self._s3.head_bucket(Bucket=self._bucket)
            self._bucket_ready = True
            return
        except ClientError as error:
            if _error_code(error) not in {"404", "NoSuchBucket", "NotFound"}:
                if _client_error_is_transient(error):
                    raise PublicationUnavailableError(
                        "Publication bucket is temporarily unavailable"
                    ) from error
                raise PublicationPreparationError("Publication bucket is unavailable") from error
        except TRANSIENT_S3_ERRORS as error:
            raise PublicationUnavailableError(
                "Publication bucket is temporarily unavailable"
            ) from error
        try:
            with _staging_authority(staging_authority):
                self._s3.create_bucket(Bucket=self._bucket)
        except ClientError as error:
            if _error_code(error) not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                if _client_error_is_transient(error):
                    raise PublicationUnavailableError(
                        "Publication bucket could not be reached"
                    ) from error
                raise PublicationPreparationError(
                    "Publication bucket could not be created"
                ) from error
        except TRANSIENT_S3_ERRORS as error:
            raise PublicationUnavailableError("Publication bucket could not be reached") from error
        self._bucket_ready = True

    def _delete_immutable(self, digest: str) -> None:
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=_object_key(digest))
        except ClientError as error:
            if _client_error_is_transient(error):
                raise PublicationUnavailableError(
                    "Publication object deletion is temporarily unavailable"
                ) from error
            raise PublicationPreparationError("Publication object deletion failed") from error
        except TRANSIENT_S3_ERRORS as error:
            raise PublicationUnavailableError(
                "Publication object deletion is temporarily unavailable"
            ) from error

    def _put_immutable(
        self,
        digest: str,
        content: bytes,
        *,
        media_type: str,
        staging_authority: StagingAuthority | None,
    ) -> None:
        try:
            with _staging_authority(staging_authority):
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
                if _client_error_is_transient(error):
                    raise PublicationUnavailableError(
                        "Publication object upload is temporarily unavailable"
                    ) from error
                raise PublicationPreparationError("Publication object upload failed") from error
        except TRANSIENT_S3_ERRORS as error:
            raise PublicationUnavailableError(
                "Publication object upload is temporarily unavailable"
            ) from error
        self._verify_existing(
            digest,
            content,
            staging_authority=staging_authority,
        )

    def _verify_existing(
        self,
        digest: str,
        expected: bytes,
        *,
        staging_authority: StagingAuthority | None,
    ) -> None:
        actual = self._read_object_bytes(
            digest,
            unavailable_message="Publication object verification is temporarily unavailable",
            missing_message="Publication object is missing",
            staging_authority=staging_authority,
        )
        if actual != expected or hashlib.sha256(actual).hexdigest() != digest:
            raise PublicationVerificationError(
                "Publication content address contains different bytes"
            )

    def _read_verified(
        self,
        digest: str,
        expected_bytes: int,
        *,
        staging_authority: StagingAuthority | None = None,
    ) -> bytes:
        content = self._read_object_bytes(
            digest,
            unavailable_message="Publication object read is temporarily unavailable",
            missing_message="Publication object is missing",
            staging_authority=staging_authority,
        )
        if len(content) != expected_bytes:
            raise PublicationVerificationError("Publication object length is invalid")
        if hashlib.sha256(content).hexdigest() != digest:
            raise PublicationVerificationError("Publication object checksum is invalid")
        return content

    def _read_object_bytes(
        self,
        digest: str,
        *,
        unavailable_message: str,
        missing_message: str,
        staging_authority: StagingAuthority | None = None,
    ) -> bytes:
        last_transient_error: Exception | None = None
        for _attempt in range(OBJECT_READ_ATTEMPTS):
            try:
                with _staging_authority(staging_authority):
                    body = self._s3.get_object(
                        Bucket=self._bucket,
                        Key=_object_key(digest),
                    )["Body"]
                    try:
                        return bytes(body.read())
                    finally:
                        body.close()
            except ClientError as error:
                if not _client_error_is_transient(error):
                    raise PublicationVerificationError(missing_message) from error
                last_transient_error = error
            except TRANSIENT_S3_ERRORS as error:
                last_transient_error = error
        raise PublicationUnavailableError(unavailable_message) from last_transient_error


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
        except (ArrowException, ParquetContractError, TypeError, OverflowError) as error:
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


def _digest_from_object_key(key: str) -> str | None:
    parts = key.split("/")
    if len(parts) != 5 or parts[:3] != ["publication", "v1", "sha256"]:
        return None
    digest = parts[4]
    if parts[3] != digest[:2]:
        return None
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return None
    return digest


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


def _client_error_is_transient(error: ClientError) -> bool:
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return (
        isinstance(status, int)
        and status >= 500
        or _error_code(error)
        in {
            "500",
            "502",
            "503",
            "504",
            "InternalError",
            "RequestTimeout",
            "ServiceUnavailable",
            "SlowDown",
        }
    )

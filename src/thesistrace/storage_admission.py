import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from thesistrace.objects import canonical_json_bytes

DEFAULT_PERSISTENT_DISK_BYTES = 200_000_000_000
DEFAULT_DISK_WARNING_PERCENT = 70
DEFAULT_PRIVATE_WRITE_REJECTION_PERCENT = 80
DEFAULT_ALL_WRITE_REJECTION_PERCENT = 90


class StorageAdmissionError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        dimension: str | None = None,
        limit: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.dimension = dimension
        self.limit = limit


@dataclass(frozen=True)
class DiskPressureDecision:
    projected_bytes: int
    projected_percent: float
    warning: bool


class DiskPressurePolicy:
    def __init__(
        self,
        capacity_bytes: int = DEFAULT_PERSISTENT_DISK_BYTES,
        warning_percent: int = DEFAULT_DISK_WARNING_PERCENT,
        private_write_rejection_percent: int = (
            DEFAULT_PRIVATE_WRITE_REJECTION_PERCENT
        ),
        all_write_rejection_percent: int = (
            DEFAULT_ALL_WRITE_REJECTION_PERCENT
        ),
    ) -> None:
        if capacity_bytes <= 0:
            raise ValueError("persistent disk capacity must be positive")
        if not (
            0
            < warning_percent
            < private_write_rejection_percent
            < all_write_rejection_percent
            <= 100
        ):
            raise ValueError(
                "disk pressure thresholds must be strictly increasing "
                "percentages between 0 and 100"
            )
        self.capacity_bytes = capacity_bytes
        self.warning_percent = warning_percent
        self.private_write_rejection_percent = (
            private_write_rejection_percent
        )
        self.all_write_rejection_percent = all_write_rejection_percent

    def evaluate(
        self,
        *,
        used_bytes: int,
        candidate_bytes: int,
        private_growth: bool,
    ) -> DiskPressureDecision:
        if used_bytes < 0 or candidate_bytes < 0:
            raise ValueError("disk byte counts cannot be negative")
        projected_bytes = used_bytes + candidate_bytes
        projected_percent = (
            projected_bytes * 100 / self.capacity_bytes
        )
        if projected_percent >= self.all_write_rejection_percent:
            raise StorageAdmissionError(
                "DISK_PRESSURE",
                "persistent disk rejects all payload growth",
                dimension="disk_usage",
                limit=self.all_write_rejection_percent,
            )
        if (
            private_growth
            and projected_percent >= self.private_write_rejection_percent
        ):
            raise StorageAdmissionError(
                "DISK_PRESSURE",
                "persistent disk rejects private payload growth",
                dimension="disk_usage",
                limit=self.private_write_rejection_percent,
            )
        return DiskPressureDecision(
            projected_bytes=projected_bytes,
            projected_percent=projected_percent,
            warning=projected_percent >= self.warning_percent,
        )


def publication_storage_objects(
    manifest: Mapping[str, object],
    *,
    manifest_object: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    resource_id = manifest.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        raise StorageAdmissionError(
            "STORAGE_INDEX_INVALID",
            "published manifest has no resource identity",
        )
    indexed: dict[str, dict[str, object]] = {}

    def collect(value: object) -> None:
        if isinstance(value, Mapping):
            digest = value.get("sha256")
            byte_count = value.get("bytes")
            if isinstance(digest, str) and isinstance(byte_count, int):
                add_content_object(indexed, digest, byte_count)
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(manifest)
    if manifest_object is not None:
        digest = manifest_object.get("sha256")
        byte_count = manifest_object.get("bytes")
        if not isinstance(digest, str) or not isinstance(byte_count, int):
            raise StorageAdmissionError(
                "STORAGE_INDEX_INVALID",
                "content-addressed manifest identity is invalid",
            )
        add_content_object(indexed, digest, byte_count)

    manifest_bytes = canonical_json_bytes(dict(manifest))
    indexed[f"manifest:{resource_id}"] = {
        "object_key": f"manifest:{resource_id}",
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "bytes": len(manifest_bytes),
        "kind": "manifest",
    }
    return [indexed[key] for key in sorted(indexed)]


def add_content_object(
    indexed: dict[str, dict[str, object]],
    digest: str,
    byte_count: int,
) -> None:
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or isinstance(byte_count, bool)
        or byte_count < 0
    ):
        raise StorageAdmissionError(
            "STORAGE_INDEX_INVALID",
            "published object identity is invalid",
        )
    key = f"sha256:{digest}"
    entry = {
        "object_key": key,
        "sha256": digest,
        "bytes": byte_count,
        "kind": "content",
    }
    existing = indexed.get(key)
    if existing is not None and existing != entry:
        raise StorageAdmissionError(
            "STORAGE_INDEX_INVALID",
            "published object byte accounting conflicts",
        )
    indexed[key] = entry

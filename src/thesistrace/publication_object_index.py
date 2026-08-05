import hashlib
from collections.abc import Mapping

from thesistrace.objects import canonical_json_bytes


class PublicationObjectIndexError(ValueError):
    pass


def publication_storage_objects(
    manifest: Mapping[str, object],
    *,
    manifest_object: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    resource_id = manifest.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        raise PublicationObjectIndexError("published manifest has no resource identity")
    indexed: dict[str, dict[str, object]] = {}

    def collect(value: object) -> None:
        if isinstance(value, Mapping):
            digest = value.get("sha256")
            byte_count = value.get("bytes")
            if isinstance(digest, str) and isinstance(byte_count, int):
                _add_content_object(indexed, digest, byte_count)
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
            raise PublicationObjectIndexError("content-addressed manifest identity is invalid")
        _add_content_object(indexed, digest, byte_count)

    manifest_bytes = canonical_json_bytes(dict(manifest))
    indexed[f"manifest:{resource_id}"] = {
        "object_key": f"manifest:{resource_id}",
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "bytes": len(manifest_bytes),
        "kind": "manifest",
    }
    return [indexed[key] for key in sorted(indexed)]


def _add_content_object(
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
        raise PublicationObjectIndexError("published object identity is invalid")
    key = f"sha256:{digest}"
    entry = {
        "object_key": key,
        "sha256": digest,
        "bytes": byte_count,
        "kind": "content",
    }
    existing = indexed.get(key)
    if existing is not None and existing != entry:
        raise PublicationObjectIndexError("published object byte accounting conflicts")
    indexed[key] = entry

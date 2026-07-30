import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ImmutableObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put_json(self, value: object) -> dict[str, object]:
        payload = canonical_json_bytes(value)
        digest = hashlib.sha256(payload).hexdigest()
        destination = self.path_for(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        return {"sha256": digest, "bytes": len(payload)}

    def put_manifest(self, release_id: str, value: object) -> None:
        destination = self.root / "manifests" / f"{release_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return
        temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
        temporary.write_bytes(canonical_json_bytes(value))
        os.replace(temporary, destination)

    def path_for(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.json"

    def read_json(self, digest: str) -> object:
        return json.loads(self.path_for(digest).read_text(encoding="utf-8"))

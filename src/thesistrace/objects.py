import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.publication.serialization import (
    ParquetContractError,
    ParquetWriterContract,
    canonical_json_bytes,
    parquet_bytes,
    require_pinned_writer_runtime,
)


class ImmutableObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put_json(self, value: object) -> dict[str, object]:
        payload = canonical_json_bytes(value)
        digest = self._put_payload(payload, suffix=".json")
        return {"sha256": digest, "bytes": len(payload)}

    def probe(self) -> bool:
        probe_path = self.root / f".health-{uuid4()}"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe_path.write_bytes(b"ok")
            available = probe_path.read_bytes() == b"ok"
        except OSError:
            return False
        try:
            probe_path.unlink(missing_ok=True)
        except OSError:
            return False
        return available

    def ready(self) -> bool:
        candidate = self.root
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        if not candidate.is_dir():
            return False
        required = os.R_OK | os.X_OK
        if candidate != self.root:
            required |= os.W_OK
        return os.access(candidate, required)

    def put_canonical_json_bytes(
        self,
        payload: bytes,
    ) -> dict[str, object]:
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ParquetContractError("JSON object payload is invalid") from error
        if canonical_json_bytes(value) != payload:
            raise ParquetContractError("JSON object payload is not canonical")
        digest = self._put_payload(payload, suffix=".json")
        return {"sha256": digest, "bytes": len(payload)}

    def put_parquet_bytes(
        self,
        payload: bytes,
    ) -> dict[str, object]:
        require_pinned_writer_runtime()
        try:
            parquet_file = pq.ParquetFile(pa.BufferReader(payload))
        except (pa.ArrowException, OSError) as error:
            raise ParquetContractError("Parquet object payload is invalid") from error
        if parquet_file.metadata.num_row_groups != 1:
            raise ParquetContractError("Parquet object must contain exactly one row group")
        digest = self._put_payload(payload, suffix=".parquet")
        return {
            "format": "parquet",
            "sha256": digest,
            "bytes": len(payload),
        }

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]:
        payload = parquet_bytes(rows, contract)
        digest = self._put_payload(payload, suffix=".parquet")
        return {
            "format": "parquet",
            "sha256": digest,
            "bytes": len(payload),
            "writer_contract_id": contract.identifier,
            "writer_contract": contract.descriptor(),
        }

    def put_manifest(self, release_id: str, value: object) -> None:
        destination = self.root / "manifests" / f"{release_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return
        temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
        try:
            temporary.write_bytes(canonical_json_bytes(value))
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def stage(
        self,
        run_id: str,
        attempt_id: str,
        *,
        cleanup_uncommitted_payloads: bool = False,
    ) -> "StagedObjectStore":
        return StagedObjectStore(
            self,
            run_id=run_id,
            attempt_id=attempt_id,
            cleanup_uncommitted_payloads=cleanup_uncommitted_payloads,
        )

    @contextmanager
    def publication_guard(self, run_id: str) -> Iterator[None]:
        staging_root = self.root / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        lock_bucket = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:2]
        with (staging_root / f".run-{lock_bucket}.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def recover_staged_publication(
        self,
        run_id: str,
        *,
        committed_manifest_sha256: str | None,
    ) -> bool:
        staging_root = self.root / "staging"
        if not staging_root.exists():
            return True
        recovered = True
        lock_path = staging_root / ".publication.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as publication_lock:
            fcntl.flock(publication_lock.fileno(), fcntl.LOCK_EX)
            try:
                run_root = staging_root / run_id
                for stage_root in sorted(run_root.glob("*")):
                    stage_lock_path = stage_root / ".stage.lock"
                    with stage_lock_path.open("a+b") as stage_lock:
                        try:
                            fcntl.flock(
                                stage_lock.fileno(),
                                fcntl.LOCK_EX | fcntl.LOCK_NB,
                            )
                        except BlockingIOError:
                            recovered = False
                            continue
                        journal_path = stage_root / ".publication.json"
                        if journal_path.exists():
                            journal = _read_stage_json(journal_path)
                            if journal.get("manifest_sha256") != committed_manifest_sha256:
                                self._remove_uncommitted_paths(journal)
                        shutil.rmtree(stage_root, ignore_errors=True)
                if run_root.exists() and not any(run_root.iterdir()):
                    run_root.rmdir()
            finally:
                fcntl.flock(publication_lock.fileno(), fcntl.LOCK_UN)
        return recovered

    def staged_publication_ids(self, *, prefix: str) -> list[str]:
        staging_root = self.root / "staging"
        if not staging_root.exists():
            return []
        return sorted(
            path.name
            for path in staging_root.iterdir()
            if path.is_dir() and path.name.startswith(prefix)
        )

    def wait_for_staged_publication(self, run_id: str) -> None:
        run_root = self.root / "staging" / run_id
        if not run_root.exists():
            return
        for stage_root in sorted(run_root.glob("*")):
            try:
                stage_lock = (stage_root / ".stage.lock").open("a+b")
            except FileNotFoundError:
                continue
            with stage_lock:
                fcntl.flock(stage_lock.fileno(), fcntl.LOCK_EX)
                fcntl.flock(stage_lock.fileno(), fcntl.LOCK_UN)

    def delete_storage_object(self, object_key: str) -> bool:
        paths: list[Path]
        if object_key.startswith("sha256:"):
            digest = object_key.removeprefix("sha256:")
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ParquetContractError("storage object key is invalid")
            bucket = self.root / "sha256" / digest[:2]
            paths = [bucket / f"{digest}.json", bucket / f"{digest}.parquet"]
        elif object_key.startswith("manifest:"):
            resource_id = object_key.removeprefix("manifest:")
            if not resource_id or "/" in resource_id or resource_id in {".", ".."}:
                raise ParquetContractError("storage object key is invalid")
            paths = [self.root / "manifests" / f"{resource_id}.json"]
        else:
            raise ParquetContractError("storage object key is invalid")

        lock_path = self.root / "staging" / ".publication.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deleted = False
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                for path in paths:
                    if path.exists():
                        path.unlink()
                        deleted = True
                        try:
                            path.parent.rmdir()
                        except OSError:
                            pass
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return deleted

    def staged_publication_active(self, run_id: str) -> bool:
        run_root = self.root / "staging" / run_id
        if not run_root.exists():
            return False
        for stage_root in sorted(run_root.glob("*")):
            try:
                stage_lock = (stage_root / ".stage.lock").open("a+b")
            except FileNotFoundError:
                continue
            with stage_lock:
                try:
                    fcntl.flock(
                        stage_lock.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                except BlockingIOError:
                    return True
                fcntl.flock(stage_lock.fileno(), fcntl.LOCK_UN)
        return False

    def _remove_uncommitted_paths(
        self,
        journal: dict[str, object],
    ) -> None:
        private_paths = journal.get("private_paths")
        if not isinstance(private_paths, list):
            raise ParquetContractError("staged publication journal is invalid")
        for relative in reversed(private_paths):
            if not isinstance(relative, str):
                raise ParquetContractError("staged publication path is invalid")
            destination = self.root / relative
            destination.unlink(missing_ok=True)
        candidate_paths = journal.get("candidate_paths", [])
        if not isinstance(candidate_paths, list):
            raise ParquetContractError("staged publication journal is invalid")
        referenced_digests = self._committed_object_digests()
        for relative in reversed(candidate_paths):
            if not isinstance(relative, str):
                raise ParquetContractError("staged publication path is invalid")
            parts = Path(relative).parts
            if len(parts) != 3 or parts[0] != "sha256":
                raise ParquetContractError("staged candidate path is invalid")
            digest = Path(parts[-1]).stem
            if digest not in referenced_digests:
                (self.root / relative).unlink(missing_ok=True)

    def _committed_object_digests(self) -> set[str]:
        digests: set[str] = set()
        manifests_root = self.root / "manifests"
        if not manifests_root.exists():
            return digests

        def collect(value: object) -> None:
            if isinstance(value, dict):
                digest = value.get("sha256")
                if isinstance(digest, str):
                    digests.add(digest)
                for nested in value.values():
                    collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)

        for manifest_path in manifests_root.glob("*.json"):
            collect(_read_stage_json(manifest_path))
        return digests

    def path_for(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.json"

    def parquet_path_for(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.parquet"

    def read_json(self, digest: str) -> object:
        return json.loads(self.path_for(digest).read_text(encoding="utf-8"))

    def read_parquet_bytes(self, digest: str) -> bytes:
        payload = self.parquet_path_for(digest).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ParquetContractError("Parquet object checksum does not match its identity")
        return payload

    def read_parquet(self, digest: str, contract: ParquetWriterContract) -> pa.Table:
        require_pinned_writer_runtime()
        payload = self.read_parquet_bytes(digest)
        table = pq.read_table(pa.BufferReader(payload))
        if not table.schema.equals(contract.schema, check_metadata=True):
            raise ParquetContractError("Parquet object schema does not match writer contract")
        metadata = pq.ParquetFile(pa.BufferReader(payload)).metadata
        if metadata.num_row_groups != 1:
            raise ParquetContractError("Parquet object must contain exactly one row group")
        return table

    def _put_payload(self, payload: bytes, *, suffix: str) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        destination = self.root / "sha256" / digest[:2] / f"{digest}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
            try:
                temporary.write_bytes(payload)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return digest


class StagedObjectStore:
    def __init__(
        self,
        destination: ImmutableObjectStore,
        *,
        run_id: str,
        attempt_id: str,
        cleanup_uncommitted_payloads: bool,
    ) -> None:
        self.destination = destination
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.cleanup_uncommitted_payloads = cleanup_uncommitted_payloads
        self.stage_lock = None
        self.promotion_started = False
        self.promotion_resolved = False
        self.writer = ImmutableObjectStore(destination.root / "staging" / run_id / attempt_id)
        self.root = self.writer.root

    def __enter__(self) -> "StagedObjectStore":
        self.root.mkdir(parents=True, exist_ok=True)
        _write_stage_json(
            self.root / ".stage.json",
            {"run_id": self.run_id, "attempt_id": self.attempt_id},
        )
        self.stage_lock = (self.root / ".stage.lock").open("a+b")
        fcntl.flock(self.stage_lock.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        if not self.promotion_started or self.promotion_resolved:
            shutil.rmtree(self.root, ignore_errors=True)
            try:
                self.root.parent.rmdir()
            except OSError:
                pass
        if self.stage_lock is not None:
            fcntl.flock(self.stage_lock.fileno(), fcntl.LOCK_UN)
            self.stage_lock.close()
            self.stage_lock = None

    def put_json(self, value: object) -> dict[str, object]:
        return self.writer.put_json(value)

    def put_parquet_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        contract: ParquetWriterContract,
    ) -> dict[str, object]:
        return self.writer.put_parquet_rows(rows, contract)

    def put_manifest(self, resource_id: str, value: object) -> None:
        self.writer.put_manifest(resource_id, value)

    def read_json(self, digest: str) -> object:
        return self.destination.read_json(digest)

    def read_parquet_bytes(self, digest: str) -> bytes:
        return self.destination.read_parquet_bytes(digest)

    def read_parquet(
        self,
        digest: str,
        contract: ParquetWriterContract,
    ) -> pa.Table:
        return self.destination.read_parquet(digest, contract)

    @contextmanager
    def publication(self, *, manifest_sha256: str) -> Iterator[None]:
        self.promote(manifest_sha256=manifest_sha256)
        yield
        self.resolve_publication()

    def promote(
        self,
        *,
        manifest_sha256: str,
        before_move: Callable[[], None] | None = None,
    ) -> None:
        self.destination.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.destination.root / "staging" / ".publication.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                sources = sorted(
                    path
                    for path in self.root.rglob("*")
                    if path.is_file() and not path.name.startswith(".")
                )
                private_paths = [
                    str(source.relative_to(self.root))
                    for source in sources
                    if source.relative_to(self.root).parts[0] == "manifests"
                    if not (self.destination.root / source.relative_to(self.root)).exists()
                ]
                candidate_paths = (
                    [
                        str(source.relative_to(self.root))
                        for source in sources
                        if source.relative_to(self.root).parts[0] == "sha256"
                        if not (self.destination.root / source.relative_to(self.root)).exists()
                    ]
                    if self.cleanup_uncommitted_payloads
                    else []
                )
                if before_move is not None:
                    before_move()
                journal = {
                    "run_id": self.run_id,
                    "attempt_id": self.attempt_id,
                    "manifest_sha256": manifest_sha256,
                    "private_paths": private_paths,
                    "candidate_paths": candidate_paths,
                }
                _write_stage_json(self.root / ".publication.json", journal)
                self.promotion_started = True
                for source in sources:
                    destination = self.destination.root / source.relative_to(self.root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        continue
                    os.replace(source, destination)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def resolve_publication(self) -> None:
        if not self.promotion_started:
            raise ParquetContractError("staged publication was not promoted")
        self.promotion_resolved = True


def _read_stage_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParquetContractError("staged publication metadata is invalid") from error
    if not isinstance(value, dict):
        raise ParquetContractError("staged publication metadata is invalid")
    return value


def _write_stage_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            output.write(canonical_json_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

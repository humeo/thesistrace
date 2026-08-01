from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from psycopg.rows import dict_row

from thesistrace.hosted.release_operations import RECOVERY_MAGIC, open_recovery_bundle
from thesistrace.objects import canonical_json_bytes

BACKUP_MAGIC = b"TTSB1"
BACKUP_FORMAT = "thesistrace-coordinated-backup-v1"
BACKUP_TARGET_FORMAT = "thesistrace-off-node-backup-target-v1"
BACKUP_TARGET_MARKER = ".thesistrace-backup-target.json"
BACKUP_STATUS_FORMAT = "thesistrace-backup-status-v1"
RECOVERY_SELECTION_FORMAT = "thesistrace-authenticated-recovery-selection-v1"
BACKUP_INTERVAL_SECONDS = 6 * 60 * 60
BACKUP_RETENTION = timedelta(days=7)
GCM_TAG_BYTES = 16
HEADER_BYTES = len(BACKUP_MAGIC) + 16 + 12
WORKFLOW_PROBE_ID = re.compile(r"recovery-probe-[0-9A-Za-z_-]{1,96}")
SOURCE_LAYOUT = {
    "postgres-data": "volumes/postgres-data",
    "temporal-data": "volumes/temporal-data",
    "immutable-objects": "volumes/immutable-objects",
    "insforge-storage": "volumes/insforge-storage",
    "release-state": "metadata/release-state",
    "secret-recovery": "secrets",
}


class BackupOperationError(RuntimeError):
    pass


class RestoreVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoverySet:
    artifact_path: Path
    manifest_path: Path
    manifest: dict[str, object]


class _EncryptingWriter:
    def __init__(self, destination: io.BufferedWriter, encryptor: object) -> None:
        self.destination = destination
        self.encryptor = encryptor

    def write(self, payload: bytes) -> int:
        encrypted = self.encryptor.update(payload)
        if encrypted:
            self.destination.write(encrypted)
        return len(payload)

    def flush(self) -> None:
        self.destination.flush()


class _DecryptingReader(io.RawIOBase):
    def __init__(self, source: io.BufferedReader, decryptor: object, remaining: int) -> None:
        self.source = source
        self.decryptor = decryptor
        self.remaining = remaining
        self.buffer = bytearray()
        self.finalized = False

    def readable(self) -> bool:
        return True

    def readinto(self, output: bytearray) -> int:
        requested = len(output)
        while len(self.buffer) < requested and not self.finalized:
            if self.remaining == 0:
                self.buffer.extend(self.decryptor.finalize())
                self.finalized = True
                break
            chunk = self.source.read(min(1024 * 1024, self.remaining))
            if not chunk:
                raise BackupOperationError("encrypted recovery set is truncated")
            self.remaining -= len(chunk)
            self.buffer.extend(self.decryptor.update(chunk))
        delivered = min(requested, len(self.buffer))
        output[:delivered] = self.buffer[:delivered]
        del self.buffer[:delivered]
        return delivered


def _backup_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 16:
        raise BackupOperationError("backup passphrase must contain at least 16 characters")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    entry = tarfile.TarInfo(name)
    entry.size = len(payload)
    entry.mode = 0o600
    archive.addfile(entry, io.BytesIO(payload))


def _require_sources(sources: Mapping[str, Path]) -> dict[str, Path]:
    if set(sources) != set(SOURCE_LAYOUT):
        missing = sorted(set(SOURCE_LAYOUT) - set(sources))
        extra = sorted(set(sources) - set(SOURCE_LAYOUT))
        raise BackupOperationError(
            f"recovery sources are incomplete: missing={missing}, extra={extra}"
        )
    normalized = {name: Path(path) for name, path in sources.items()}
    missing_paths = sorted(name for name, path in normalized.items() if not path.is_dir())
    if missing_paths:
        raise BackupOperationError(
            "recovery source directories are missing: " + ", ".join(missing_paths)
        )
    return normalized


def _validate_coordinated_sources(
    sources: Mapping[str, Path],
    release_bundle_id: str,
) -> None:
    required = (
        sources["postgres-data"] / "PG_VERSION",
        sources["temporal-data"] / "PG_VERSION",
        sources["secret-recovery"] / "current.recovery",
        sources["release-state"] / "current.json",
        sources["release-state"] / "bundles" / release_bundle_id / "bundle.json",
    )
    if any(not path.is_file() or path.stat().st_size == 0 for path in required):
        raise BackupOperationError("coordinated source is incomplete")
    if not (sources["secret-recovery"] / "current.recovery").read_bytes().startswith(
        RECOVERY_MAGIC
    ):
        raise BackupOperationError("coordinated source secret recovery is invalid")
    try:
        pointer = json.loads((sources["release-state"] / "current.json").read_bytes())
        bundle = json.loads(
            (
                sources["release-state"]
                / "bundles"
                / release_bundle_id
                / "bundle.json"
            ).read_bytes()
        )
    except json.JSONDecodeError as error:
        raise BackupOperationError("coordinated source metadata is invalid") from error
    if (
        not isinstance(pointer, dict)
        or pointer.get("bundle_id") != release_bundle_id
        or not isinstance(bundle, dict)
        or bundle.get("bundle_id") != release_bundle_id
    ):
        raise BackupOperationError("coordinated source Release Bundle does not match")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _off_node_path(
    target: Path,
    *,
    repository_root: Path,
    state_root: Path,
) -> Path:
    if not target.is_absolute():
        raise BackupOperationError("off-node backup target must be an absolute path")
    resolved = target.resolve()
    repository = repository_root.resolve()
    state = state_root.resolve()
    if _is_within(resolved, repository) or _is_within(resolved, state):
        raise BackupOperationError(
            "off-node backup target must remain outside the repository and host state"
        )
    return resolved


def initialize_backup_target(
    target: Path,
    *,
    repository_root: Path,
    state_root: Path,
) -> Path:
    resolved = _off_node_path(
        target,
        repository_root=repository_root,
        state_root=state_root,
    )
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = resolved / BACKUP_TARGET_MARKER
    _write_status(
        marker,
        {
            "format": BACKUP_TARGET_FORMAT,
            "target_id": uuid4().hex,
        },
    )
    marker.chmod(0o600)
    return resolved


def validate_backup_target(
    target: Path,
    *,
    repository_root: Path,
    state_root: Path,
) -> Path:
    resolved = _off_node_path(
        target,
        repository_root=repository_root,
        state_root=state_root,
    )
    require_initialized_backup_target(resolved)
    if not os.access(resolved, os.R_OK | os.W_OK | os.X_OK):
        raise BackupOperationError("off-node backup target is not writable")
    return resolved


def require_initialized_backup_target(target: Path) -> Path:
    marker = target / BACKUP_TARGET_MARKER
    try:
        value = json.loads(marker.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise BackupOperationError("off-node backup target is not initialized") from error
    if (
        not isinstance(value, dict)
        or value.get("format") != BACKUP_TARGET_FORMAT
        or not isinstance(value.get("target_id"), str)
        or len(value["target_id"]) != 32
    ):
        raise BackupOperationError("off-node backup target marker is invalid")
    if not os.access(target, os.R_OK | os.W_OK | os.X_OK):
        raise BackupOperationError("off-node backup target is not writable")
    return target


def _read_status(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("format") != BACKUP_STATUS_FORMAT:
        return {}
    return dict(value)


def _write_status(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json_bytes(dict(value)))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    path.chmod(0o644)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def perform_backup(
    *,
    target: Path,
    sources: Mapping[str, Path],
    release_bundle_id: str,
    passphrase: str,
    status_path: Path,
    now: datetime | None = None,
    workflow_probe_id: str | None = None,
) -> RecoverySet:
    attempted_at = (now or datetime.now(UTC)).astimezone(UTC)
    previous = _read_status(status_path)
    try:
        expire_recovery_sets(target, now=attempted_at)
        created = create_recovery_set(
            target=target,
            sources=sources,
            release_bundle_id=release_bundle_id,
            passphrase=passphrase,
            now=attempted_at,
            workflow_probe_id=workflow_probe_id,
        )
    except Exception:
        _write_status(
            status_path,
            {
                "format": BACKUP_STATUS_FORMAT,
                "last_attempt_at": attempted_at.isoformat(),
                "last_attempt_status": "failed",
                "last_success_at": previous.get("last_success_at"),
                "last_success_backup_id": previous.get("last_success_backup_id"),
                "failure_reason": "BACKUP_FAILED",
            },
        )
        raise
    _write_status(
        status_path,
        {
            "format": BACKUP_STATUS_FORMAT,
            "last_attempt_at": attempted_at.isoformat(),
            "last_attempt_status": "succeeded",
            "last_success_at": attempted_at.isoformat(),
            "last_success_backup_id": created.manifest["backup_id"],
            "failure_reason": None,
        },
    )
    return created


def expire_recovery_sets(
    target: Path,
    *,
    now: datetime | None = None,
) -> list[str]:
    cutoff = (now or datetime.now(UTC)).astimezone(UTC) - BACKUP_RETENTION
    expired: list[str] = []
    for manifest_path in sorted(target.glob("backup_*.json")):
        try:
            manifest = _read_manifest(manifest_path)
            created_at = datetime.fromisoformat(str(manifest["created_at"])).astimezone(UTC)
        except (BackupOperationError, KeyError, ValueError):
            continue
        if created_at >= cutoff:
            continue
        artifact_path = target / str(manifest["artifact"])
        if artifact_path.parent != target or artifact_path.name != manifest["artifact"]:
            raise BackupOperationError("recovery set artifact path is invalid")
        artifact_path.unlink(missing_ok=True)
        manifest_path.unlink()
        expired.append(str(manifest["backup_id"]))
    return expired


def read_backup_health(
    status_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, float | bool]:
    status = _read_status(status_path)
    attempted_success = status.get("last_attempt_status") == "succeeded"
    last_success = status.get("last_success_at")
    age = -1.0
    if isinstance(last_success, str):
        try:
            observed = datetime.fromisoformat(last_success).astimezone(UTC)
            age = max(
                0.0,
                ((now or datetime.now(UTC)).astimezone(UTC) - observed).total_seconds(),
            )
        except ValueError:
            age = -1.0
    return {
        "healthy": attempted_success and 0.0 <= age <= BACKUP_INTERVAL_SECONDS,
        "last_attempt_succeeded": attempted_success,
        "last_success_age_seconds": age,
    }


def create_recovery_set(
    *,
    target: Path,
    sources: Mapping[str, Path],
    release_bundle_id: str,
    passphrase: str,
    now: datetime | None = None,
    workflow_probe_id: str | None = None,
) -> RecoverySet:
    source_paths = _require_sources(sources)
    if not release_bundle_id:
        raise BackupOperationError("release Bundle identity is required")
    if workflow_probe_id and not WORKFLOW_PROBE_ID.fullmatch(workflow_probe_id):
        raise BackupOperationError("Workflow recovery probe ID is invalid")
    _validate_coordinated_sources(source_paths, release_bundle_id)
    created_at = (now or datetime.now(UTC)).astimezone(UTC)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_id = (
        "backup_"
        + created_at.strftime("%Y%m%dT%H%M%SZ")
        + "_"
        + uuid4().hex[:12]
    )
    artifact_path = target / f"{backup_id}.ttsb"
    manifest_path = target / f"{backup_id}.json"
    temporary = target / f".{backup_id}.{os.getpid()}.tmp"
    salt = os.urandom(16)
    nonce = os.urandom(12)
    manifest_temporary: Path | None = None
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as raw:
            raw.write(BACKUP_MAGIC + salt + nonce)
            encryptor = Cipher(
                algorithms.AES(_backup_key(passphrase, salt)),
                modes.GCM(nonce),
            ).encryptor()
            encryptor.authenticate_additional_data(BACKUP_MAGIC)
            encrypted = _EncryptingWriter(raw, encryptor)
            with tarfile.open(fileobj=encrypted, mode="w|gz") as archive:
                _add_bytes(
                    archive,
                    "metadata/recovery-set.json",
                    canonical_json_bytes(
                        {
                            "format": BACKUP_FORMAT,
                            "backup_id": backup_id,
                            "created_at": created_at.isoformat(),
                            "release_bundle_id": release_bundle_id,
                        }
                    ),
                )
                for source_name, archive_name in SOURCE_LAYOUT.items():
                    archive.add(
                        source_paths[source_name],
                        arcname=archive_name,
                        recursive=True,
                    )
            final = encryptor.finalize()
            if final:
                raw.write(final)
            raw.write(encryptor.tag)
            raw.flush()
            os.fsync(raw.fileno())
        temporary.replace(artifact_path)
        artifact_path.chmod(0o600)
        manifest = {
            "format": BACKUP_FORMAT,
            "backup_id": backup_id,
            "status": "complete",
            "created_at": created_at.isoformat(),
            "release_bundle_id": release_bundle_id,
            "artifact": artifact_path.name,
            "artifact_bytes": artifact_path.stat().st_size,
            "artifact_sha256": _file_sha256(artifact_path),
        }
        if workflow_probe_id:
            manifest["workflow_probe_id"] = workflow_probe_id
        manifest_temporary = target / f".{backup_id}.json.{os.getpid()}.tmp"
        manifest_descriptor = os.open(
            manifest_temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(manifest_descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        manifest_temporary.replace(manifest_path)
        return RecoverySet(artifact_path, manifest_path, manifest)
    except Exception:
        temporary.unlink(missing_ok=True)
        if manifest_temporary is not None:
            manifest_temporary.unlink(missing_ok=True)
        artifact_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise BackupOperationError("recovery set manifest is invalid") from error
    if (
        not isinstance(value, dict)
        or value.get("format") != BACKUP_FORMAT
        or value.get("status") != "complete"
        or not isinstance(value.get("backup_id"), str)
        or not isinstance(value.get("artifact"), str)
        or not isinstance(value.get("artifact_sha256"), str)
        or re.fullmatch(r"backup_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{12}", value["backup_id"])
        is None
        or value["artifact"] != f"{value['backup_id']}.ttsb"
        or re.fullmatch(r"[0-9a-f]{64}", value["artifact_sha256"]) is None
    ):
        raise BackupOperationError("recovery set manifest is invalid")
    return dict(value)


def _artifact_details(
    manifest_path: Path,
) -> tuple[dict[str, object], Path, int]:
    manifest = _read_manifest(manifest_path)
    artifact_path = manifest_path.parent / str(manifest["artifact"])
    try:
        artifact_size = artifact_path.stat().st_size
    except OSError as error:
        raise BackupOperationError("recovery set artifact is missing") from error
    if artifact_size < HEADER_BYTES + GCM_TAG_BYTES:
        raise BackupOperationError("encrypted recovery set is truncated")
    if _file_sha256(artifact_path) != manifest["artifact_sha256"]:
        raise BackupOperationError("recovery set checksum does not match its manifest")
    return manifest, artifact_path, artifact_size


def _decrypted_reader(
    artifact_path: Path,
    artifact_size: int,
    passphrase: str,
) -> tuple[io.BufferedReader, io.BufferedReader]:
    source = artifact_path.open("rb")
    try:
        header = source.read(HEADER_BYTES)
        if not header.startswith(BACKUP_MAGIC):
            raise BackupOperationError("encrypted recovery set has an invalid header")
        salt = header[len(BACKUP_MAGIC) : len(BACKUP_MAGIC) + 16]
        nonce = header[len(BACKUP_MAGIC) + 16 : HEADER_BYTES]
        source.seek(-GCM_TAG_BYTES, os.SEEK_END)
        tag = source.read(GCM_TAG_BYTES)
        source.seek(HEADER_BYTES)
        encrypted_bytes = artifact_size - HEADER_BYTES - GCM_TAG_BYTES
        decryptor = Cipher(
            algorithms.AES(_backup_key(passphrase, salt)),
            modes.GCM(nonce, tag),
        ).decryptor()
        decryptor.authenticate_additional_data(BACKUP_MAGIC)
        reader = io.BufferedReader(
            _DecryptingReader(source, decryptor, encrypted_bytes),
            buffer_size=1024 * 1024,
        )
        return source, reader
    except Exception:
        source.close()
        raise


def verify_recovery_set(
    *,
    manifest_path: Path,
    passphrase: str,
) -> dict[str, object]:
    manifest, artifact_path, artifact_size = _artifact_details(manifest_path)
    source: io.BufferedReader | None = None
    reader: io.BufferedReader | None = None
    authenticated_metadata: dict[str, object] | None = None
    try:
        source, reader = _decrypted_reader(artifact_path, artifact_size, passphrase)
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                tarfile.data_filter(member, "/restore")
                payload = archive.extractfile(member) if member.isfile() else None
                if payload is not None:
                    if member.name == "metadata/recovery-set.json":
                        if authenticated_metadata is not None or member.size > 4096:
                            raise BackupOperationError(
                                "authenticated recovery metadata is invalid"
                            )
                        try:
                            value = json.loads(payload.read(4097))
                        except json.JSONDecodeError as error:
                            raise BackupOperationError(
                                "authenticated recovery metadata is invalid"
                            ) from error
                        if not isinstance(value, dict):
                            raise BackupOperationError(
                                "authenticated recovery metadata is invalid"
                            )
                        authenticated_metadata = dict(value)
                    else:
                        while payload.read(1024 * 1024):
                            pass
        while reader.read(1024 * 1024):
            pass
    except BackupOperationError:
        raise
    except (InvalidTag, tarfile.TarError, OSError) as error:
        raise BackupOperationError(
            "recovery set authentication or archive validation failed"
        ) from error
    finally:
        if reader is not None:
            reader.close()
        if source is not None:
            source.close()
    if authenticated_metadata is None:
        raise BackupOperationError("authenticated recovery metadata is missing")
    authenticated_fields = (
        "format",
        "backup_id",
        "created_at",
        "release_bundle_id",
    )
    if any(
        authenticated_metadata.get(field) != manifest.get(field)
        for field in authenticated_fields
    ):
        raise BackupOperationError(
            "recovery set manifest does not match authenticated metadata"
        )
    return manifest


def extract_recovery_set(
    *,
    manifest_path: Path,
    destination: Path,
    passphrase: str,
    _cleanup_on_failure: bool = True,
) -> dict[str, object]:
    manifest, artifact_path, artifact_size = _artifact_details(manifest_path)
    if (
        _cleanup_on_failure
        and destination.exists()
        and any(destination.iterdir())
    ):
        raise BackupOperationError("restore destination must be empty")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        source, reader = _decrypted_reader(artifact_path, artifact_size, passphrase)
        try:
            with tarfile.open(fileobj=reader, mode="r|gz") as archive:
                archive.extractall(
                    destination,
                    members=(
                        member
                        for member in archive
                        if member.name != "metadata/recovery-set.json"
                    ),
                    filter="data",
                )
        finally:
            reader.close()
            source.close()
    except BackupOperationError:
        if _cleanup_on_failure:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    except (InvalidTag, tarfile.TarError, OSError) as error:
        if _cleanup_on_failure:
            shutil.rmtree(destination, ignore_errors=True)
        raise BackupOperationError(
            "recovery set authentication or archive validation failed"
        ) from error
    except Exception:
        if _cleanup_on_failure:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    return manifest


def _clear_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise BackupOperationError(f"restore target is not a directory: {path}")
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def restore_release_configuration_modes(release_state: Path) -> int:
    try:
        pointer = json.loads((release_state / "current.json").read_bytes())
        bundle_id = pointer["bundle_id"]
        bundle = json.loads(
            (release_state / "bundles" / bundle_id / "bundle.json").read_bytes()
        )
    except (KeyError, json.JSONDecodeError, OSError, TypeError):
        return 0
    paths = bundle.get("configuration_paths")
    modes = bundle.get("configuration_modes")
    if paths is None and modes is None:
        return 0
    if not isinstance(paths, list) or not isinstance(modes, dict):
        raise BackupOperationError("restored Release Bundle modes are invalid")
    configuration_root = release_state / "bundles" / bundle_id / "configuration"
    for relative in paths:
        expected_mode = modes.get(relative)
        if not isinstance(relative, str) or not isinstance(expected_mode, int):
            raise BackupOperationError("restored Release Bundle modes are invalid")
        path = (configuration_root / relative).resolve()
        try:
            path.relative_to(configuration_root.resolve())
        except ValueError as error:
            raise BackupOperationError(
                "restored Release Bundle path escapes its configuration root"
            ) from error
        if not path.is_file():
            raise BackupOperationError("restored Release Bundle file is missing")
        path.chmod(expected_mode)
    return len(paths)


def restore_recovery_set(
    *,
    manifest_path: Path,
    restore_root: Path,
    working_cache: Path,
    passphrase: str,
    incident_at: datetime | None = None,
    selection_output: Path | None = None,
) -> dict[str, object]:
    manifest = verify_recovery_set(
        manifest_path=manifest_path,
        passphrase=passphrase,
    )
    selection = authenticated_recovery_selection(
        manifest,
        manifest_sha256=_file_sha256(manifest_path),
        incident_at=incident_at or datetime.now(UTC),
    )
    required_targets = [
        restore_root / archive_name for archive_name in SOURCE_LAYOUT.values()
    ]
    for target in required_targets:
        if not target.is_dir() or target.is_symlink():
            raise BackupOperationError(
                f"restore target is not mounted: {target.relative_to(restore_root)}"
            )
    if not working_cache.is_dir() or working_cache.is_symlink():
        raise BackupOperationError("Working Cache restore target is not mounted")
    for target in required_targets:
        _clear_directory(target)
    _clear_directory(working_cache)
    extracted_manifest = extract_recovery_set(
        manifest_path=manifest_path,
        destination=restore_root,
        passphrase=passphrase,
        _cleanup_on_failure=False,
    )
    restore_release_configuration_modes(restore_root / "metadata/release-state")
    if extracted_manifest != manifest:
        raise BackupOperationError("authenticated recovery manifest changed during restore")
    if selection_output is not None:
        _write_status(selection_output, selection)
    return manifest


def authenticated_recovery_selection(
    manifest: Mapping[str, object],
    *,
    manifest_sha256: str,
    incident_at: datetime,
) -> dict[str, object]:
    try:
        created_at = datetime.fromisoformat(str(manifest["created_at"])).astimezone(UTC)
        incident = incident_at.astimezone(UTC)
        backup_id = str(manifest["backup_id"])
        release_bundle_id = str(manifest["release_bundle_id"])
    except (KeyError, ValueError) as error:
        raise BackupOperationError("recovery selection metadata is invalid") from error
    if incident < created_at:
        raise BackupOperationError("recovery incident precedes the selected backup")
    state_loss = int((incident - created_at).total_seconds())
    if state_loss > BACKUP_INTERVAL_SECONDS:
        raise BackupOperationError("selected recovery set exceeds the six-hour RPO")
    if re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None:
        raise BackupOperationError("recovery selection manifest identity is invalid")
    return {
        "format": RECOVERY_SELECTION_FORMAT,
        "backup_id": backup_id,
        "release_bundle_id": release_bundle_id,
        "backup_created_at": created_at.isoformat(),
        "incident_at": incident.isoformat(),
        "committed_state_loss_bound_seconds": state_loss,
        "manifest_sha256": manifest_sha256,
        "authenticated": True,
    }


def verify_authenticated_recovery_selection(
    selection: Mapping[str, object],
    *,
    expected_backup_id: str,
) -> dict[str, object]:
    try:
        backup_id = str(selection["backup_id"])
        created_at = datetime.fromisoformat(
            str(selection["backup_created_at"])
        ).astimezone(UTC)
        incident_at = datetime.fromisoformat(str(selection["incident_at"])).astimezone(UTC)
        state_loss = int(selection["committed_state_loss_bound_seconds"])
    except (KeyError, TypeError, ValueError) as error:
        raise RestoreVerificationError(
            "authenticated recovery selection is invalid"
        ) from error
    calculated_loss = int((incident_at - created_at).total_seconds())
    if (
        selection.get("format") != RECOVERY_SELECTION_FORMAT
        or selection.get("authenticated") is not True
        or backup_id != expected_backup_id
        or calculated_loss < 0
        or state_loss != calculated_loss
        or re.fullmatch(r"[0-9a-f]{64}", str(selection.get("manifest_sha256", "")))
        is None
    ):
        raise RestoreVerificationError("authenticated recovery selection is invalid")
    if state_loss > BACKUP_INTERVAL_SECONDS:
        raise RestoreVerificationError("authenticated recovery set exceeds the six-hour RPO")
    return {
        "backup_id": backup_id,
        "recovery_set_authenticated": True,
        "committed_state_loss_bound_seconds": state_loss,
    }


def restore_secret_recovery_bundle(
    recovery_bundle: Path,
    *,
    secret_root: Path,
    passphrase: str,
) -> list[str]:
    try:
        values = open_recovery_bundle(recovery_bundle, passphrase=passphrase)
    except Exception as error:
        raise BackupOperationError("secret recovery bundle authentication failed") from error
    if not values or any(
        not name or name in {".", ".."} or Path(name).name != name
        for name in values
    ):
        raise BackupOperationError("secret recovery bundle contains invalid file names")
    secret_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _clear_directory(secret_root)
    for name, value in sorted(values.items()):
        path = secret_root / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(value)
        path.chmod(0o600)
    secret_root.chmod(0o700)
    return sorted(values)


def _indexed_object_path(root: Path, row: Mapping[str, object]) -> Path:
    object_key = row.get("object_key")
    digest = row.get("sha256")
    object_kind = row.get("object_kind")
    if (
        not isinstance(object_key, str)
        or not isinstance(digest, str)
        or len(digest) != 64
    ):
        raise RestoreVerificationError("restored object index is invalid")
    if object_kind == "content" and object_key == f"sha256:{digest}":
        candidates = [
            root / "sha256" / digest[:2] / f"{digest}.json",
            root / "sha256" / digest[:2] / f"{digest}.parquet",
        ]
        existing = [path for path in candidates if path.is_file()]
        if len(existing) != 1:
            raise RestoreVerificationError(
                f"indexed content object is missing or ambiguous: {object_key}"
            )
        return existing[0]
    if object_kind == "manifest" and object_key.startswith("manifest:"):
        resource_id = object_key.removeprefix("manifest:")
        if not resource_id or Path(resource_id).name != resource_id:
            raise RestoreVerificationError("restored manifest index is invalid")
        path = root / "manifests" / f"{resource_id}.json"
        if path.is_file():
            return path
        raise RestoreVerificationError(f"indexed manifest is missing: {object_key}")
    raise RestoreVerificationError("restored object index is invalid")


def verify_restored_state(
    *,
    object_root: Path,
    snapshot: Mapping[str, object],
) -> dict[str, object]:
    pending = int(snapshot.get("pending_cleanup_count", -1))
    tombstone_references = int(snapshot.get("tombstone_reference_count", -1))
    resurrected = int(snapshot.get("resurrected_resource_count", -1))
    if pending or tombstone_references or resurrected:
        raise RestoreVerificationError(
            "Resource Tombstone reconciliation is incomplete"
        )
    if int(snapshot.get("unreferenced_index_count", -1)) != 0:
        raise RestoreVerificationError("restored object index contains unreferenced entries")
    if int(snapshot.get("rls_missing_count", -1)) != 0:
        raise RestoreVerificationError("Personal Workspace RLS contract is incomplete")
    latest_release = snapshot.get("latest_dataset_release_id")
    if not isinstance(latest_release, str) or not latest_release:
        raise RestoreVerificationError("latest valid Dataset Release is missing")
    rows = snapshot.get("objects")
    if not isinstance(rows, list):
        raise RestoreVerificationError("restored object index is unavailable")
    for value in rows:
        if not isinstance(value, Mapping):
            raise RestoreVerificationError("restored object index is invalid")
        path = _indexed_object_path(object_root, value)
        expected_bytes = int(value.get("compressed_bytes", -1))
        if path.stat().st_size != expected_bytes:
            raise RestoreVerificationError(
                f"restored object size does not match its index: {value['object_key']}"
            )
        if _file_sha256(path) != value["sha256"]:
            raise RestoreVerificationError(
                f"restored object checksum does not match its index: {value['object_key']}"
            )
    return {
        "latest_dataset_release_id": latest_release,
        "verified_objects": len(rows),
    }


def load_restore_snapshot(database_url: str) -> dict[str, object]:
    with psycopg.connect(
        database_url,
        connect_timeout=5,
        row_factory=dict_row,
    ) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*)
                 FROM thesistrace_control.resource_cleanup_jobs
                 WHERE status = 'pending') AS pending_cleanup_count,
                (SELECT count(*)
                 FROM thesistrace_control.storage_references
                 WHERE resource_kind = 'resource_tombstone')
                    AS tombstone_reference_count,
                (SELECT count(*)
                 FROM thesistrace_control.resource_tombstones AS tombstone
                 WHERE (
                     tombstone.resource_kind = 'research_run'
                     AND EXISTS (
                         SELECT 1
                         FROM thesistrace_product.research_runs AS run
                         WHERE run.workspace_id = tombstone.workspace_id
                           AND run.id = tombstone.resource_id
                     )
                 ) OR (
                     tombstone.resource_kind = 'daily_track'
                     AND EXISTS (
                         SELECT 1
                         FROM thesistrace_product.daily_tracks AS track
                         WHERE track.workspace_id = tombstone.workspace_id
                           AND track.id = tombstone.resource_id
                     )
                 )) AS resurrected_resource_count,
                (SELECT count(*)
                 FROM thesistrace_control.stored_objects AS stored
                 WHERE NOT EXISTS (
                     SELECT 1
                     FROM thesistrace_control.storage_references AS reference
                     WHERE reference.object_key = stored.object_key
                 )) AS unreferenced_index_count,
                (SELECT count(*)
                 FROM information_schema.columns AS column_definition
                 JOIN pg_catalog.pg_namespace AS namespace
                   ON namespace.nspname = column_definition.table_schema
                 JOIN pg_catalog.pg_class AS relation
                   ON relation.relnamespace = namespace.oid
                  AND relation.relname = column_definition.table_name
                 WHERE column_definition.table_schema = 'thesistrace_product'
                   AND column_definition.column_name = 'workspace_id'
                   AND (NOT relation.relrowsecurity OR NOT relation.relforcerowsecurity))
                    AS rls_missing_count,
                (SELECT pointer.release_id
                 FROM thesistrace_product.dataset_release_pointer AS pointer
                 JOIN thesistrace_product.dataset_releases AS release
                   ON release.id = pointer.release_id
                 WHERE pointer.singleton = 1) AS latest_dataset_release_id
            """
        ).fetchone()
        objects = connection.execute(
            """
            SELECT object_key, sha256, compressed_bytes, object_kind
            FROM thesistrace_control.stored_objects
            ORDER BY object_key
            """
        ).fetchall()
    if counts is None:
        raise RestoreVerificationError("restored metadata snapshot is unavailable")
    return {**dict(counts), "objects": [dict(row) for row in objects]}


def write_recovery_exercise(
    *,
    manifest_path: Path,
    evidence_dir: Path,
    incident_at: datetime,
    detected_at: datetime,
    restore_started_at: datetime,
    restore_completed_at: datetime,
    verification: Mapping[str, object],
    public_origin_smoke: bool,
) -> Path:
    manifest = _read_manifest(manifest_path)
    try:
        backup_created_at = datetime.fromisoformat(
            str(manifest["created_at"])
        ).astimezone(UTC)
    except (KeyError, ValueError) as error:
        raise BackupOperationError("recovery exercise backup time is invalid") from error
    incident = incident_at.astimezone(UTC)
    detected = detected_at.astimezone(UTC)
    started = restore_started_at.astimezone(UTC)
    completed = restore_completed_at.astimezone(UTC)
    if not backup_created_at <= incident <= detected <= started <= completed:
        raise BackupOperationError("recovery exercise timeline is invalid")
    state_loss = int((incident - backup_created_at).total_seconds())
    detection = int((detected - incident).total_seconds())
    execution = int((completed - started).total_seconds())
    latest_release = verification.get("latest_dataset_release_id")
    verified_objects = verification.get("verified_objects")
    if (
        not isinstance(latest_release, str)
        or not latest_release
        or not isinstance(verified_objects, int)
        or verified_objects < 0
    ):
        raise BackupOperationError("recovery exercise verification is invalid")
    objectives = {
        "committed_state_loss_within_6h": state_loss <= BACKUP_INTERVAL_SECONDS,
        "detection_within_24h": detection <= 24 * 60 * 60,
        "recovery_execution_within_8h": execution <= 8 * 60 * 60,
        "public_origin_smoke": bool(public_origin_smoke),
    }
    workflow_probe_id = manifest.get("workflow_probe_id")
    if workflow_probe_id is not None:
        objectives["workflow_recovery"] = bool(
            verification.get("workflow_recovery_verified") is True
            and verification.get("workflow_probe_id") == workflow_probe_id
        )
    evidence = {
        "format": "thesistrace-recovery-exercise-v1",
        "backup_id": manifest["backup_id"],
        "release_bundle_id": manifest["release_bundle_id"],
        "backup_created_at": backup_created_at.isoformat(),
        "incident_at": incident.isoformat(),
        "detected_at": detected.isoformat(),
        "restore_started_at": started.isoformat(),
        "restore_completed_at": completed.isoformat(),
        "committed_state_loss_bound_seconds": state_loss,
        "detection_seconds": detection,
        "recovery_execution_seconds": execution,
        "latest_dataset_release_id": latest_release,
        "verified_objects": verified_objects,
        **(
            {"workflow_probe_id": workflow_probe_id}
            if workflow_probe_id is not None
            else {}
        ),
        "objectives": objectives,
        "status": "passed" if all(objectives.values()) else "failed",
    }
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = evidence_dir / (
        f"recovery_{manifest['backup_id']}_{completed.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    _write_status(path, evidence)
    path.chmod(0o600)
    return path

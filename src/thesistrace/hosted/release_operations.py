import base64
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

RELEASE_MANIFEST_VERSION = 1
RECOVERY_MAGIC = b"TTSR1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")


class ReleaseOperationError(RuntimeError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_paths(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for relative in paths:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as error:
            raise ReleaseOperationError("release source path escapes repository") from error
        if candidate.is_dir():
            files.extend(
                path
                for path in candidate.rglob("*")
                if path.is_file()
                and not {"__pycache__", "node_modules", "dist"}.intersection(
                    path.parts
                )
                and path.suffix not in {".pyc", ".pyo"}
            )
        elif candidate.is_file():
            files.append(candidate)
        else:
            raise ReleaseOperationError(f"release source path is missing: {relative}")
    for path in sorted(set(files)):
        relative = path.relative_to(root.resolve()).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


@dataclass(frozen=True)
class ReleaseBundle:
    version: str
    compatibility_epoch: str
    components: dict[str, dict[str, str]]
    content_sha256: str
    manifest_sha256: str

    @classmethod
    def from_manifest(
        cls,
        manifest_path: Path,
        repository_root: Path,
        *,
        version_override: str | None = None,
        compatibility_epoch_override: str | None = None,
    ) -> "ReleaseBundle":
        source = json.loads(manifest_path.read_text())
        if source.get("manifest_version") != RELEASE_MANIFEST_VERSION:
            raise ReleaseOperationError("unsupported release manifest version")
        version = version_override or str(source["version"])
        compatibility_epoch = (
            compatibility_epoch_override or str(source["compatibility_epoch"])
        )
        if not IDENTIFIER.fullmatch(version) or not IDENTIFIER.fullmatch(
            compatibility_epoch
        ):
            raise ReleaseOperationError("release identifiers are invalid")
        component_sources = source.get("components")
        if not isinstance(component_sources, dict) or not component_sources:
            raise ReleaseOperationError("release components are required")
        component_templates: dict[str, dict[str, str]] = {}
        for name, value in sorted(component_sources.items()):
            if not isinstance(value, dict):
                raise ReleaseOperationError(f"invalid release component: {name}")
            paths = value.get("source_paths")
            if not isinstance(paths, list) or not all(
                isinstance(path, str) for path in paths
            ):
                raise ReleaseOperationError(f"component source paths are required: {name}")
            artifact = str(value["artifact"])
            if not artifact:
                raise ReleaseOperationError(f"component artifact is required: {name}")
            component_templates[str(name)] = {
                "version": str(value["version"]),
                "artifact": artifact,
                "source_sha256": sha256_paths(repository_root, paths),
            }
        content_body = {
            "manifest_version": RELEASE_MANIFEST_VERSION,
            "version": version,
            "compatibility_epoch": compatibility_epoch,
            "components": component_templates,
        }
        content_sha256 = hashlib.sha256(canonical_json(content_body)).hexdigest()
        bundle_id = f"{version}-{content_sha256[:16]}"
        try:
            components = {
                name: {
                    **component,
                    "artifact": component["artifact"].format(bundle_id=bundle_id),
                }
                for name, component in component_templates.items()
            }
        except (KeyError, ValueError) as error:
            raise ReleaseOperationError("release artifact template is invalid") from error
        body = {
            "manifest_version": RELEASE_MANIFEST_VERSION,
            "version": version,
            "compatibility_epoch": compatibility_epoch,
            "content_sha256": content_sha256,
            "components": components,
        }
        return cls(
            version=version,
            compatibility_epoch=compatibility_epoch,
            components=components,
            content_sha256=content_sha256,
            manifest_sha256=hashlib.sha256(canonical_json(body)).hexdigest(),
        )

    @property
    def bundle_id(self) -> str:
        return f"{self.version}-{self.content_sha256[:16]}"

    def as_dict(self) -> dict[str, object]:
        return {
            "manifest_version": RELEASE_MANIFEST_VERSION,
            "bundle_id": self.bundle_id,
            "version": self.version,
            "compatibility_epoch": self.compatibility_epoch,
            "content_sha256": self.content_sha256,
            "components": self.components,
            "manifest_sha256": self.manifest_sha256,
        }


def read_pointer(state_root: Path, name: str) -> dict[str, str] | None:
    path = state_root / f"{name}.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    return {"bundle_id": str(value["bundle_id"])}


def write_pointer(state_root: Path, name: str, bundle_id: str) -> None:
    temporary = state_root / f".{name}.{os.getpid()}.tmp"
    temporary.write_bytes(canonical_json({"bundle_id": bundle_id}) + b"\n")
    temporary.chmod(0o644)
    temporary.replace(state_root / f"{name}.json")


def read_bundle(state_root: Path, bundle_id: str) -> dict[str, object]:
    path = state_root / "bundles" / bundle_id / "bundle.json"
    if not path.is_file():
        raise ReleaseOperationError(f"release bundle is unavailable: {bundle_id}")
    return dict(json.loads(path.read_text()))


def store_release_bundle(state_root: Path, bundle: ReleaseBundle) -> str:
    state_root.mkdir(parents=True, exist_ok=True, mode=0o755)
    state_root.chmod(0o755)
    bundles = state_root / "bundles"
    bundles.mkdir(mode=0o755, exist_ok=True)
    bundles.chmod(0o755)
    target = bundles / bundle.bundle_id
    payload = canonical_json(bundle.as_dict()) + b"\n"
    try:
        target.mkdir(mode=0o755)
        bundle_path = target / "bundle.json"
        bundle_path.write_bytes(payload)
        bundle_path.chmod(0o444)
    except FileExistsError:
        if (target / "bundle.json").read_bytes() != payload:
            raise ReleaseOperationError("immutable release bundle changed") from None
    return bundle.bundle_id


def stage_release_bundle(state_root: Path, bundle: ReleaseBundle) -> str:
    bundle_id = store_release_bundle(state_root, bundle)
    write_pointer(state_root, "candidate", bundle_id)
    return bundle_id


def activate_candidate_release(state_root: Path) -> dict[str, str]:
    candidate = read_pointer(state_root, "candidate")
    if candidate is None:
        raise ReleaseOperationError("a staged release candidate is unavailable")
    bundle_id = candidate["bundle_id"]
    read_bundle(state_root, bundle_id)
    current = read_pointer(state_root, "current")
    if current and current["bundle_id"] != bundle_id:
        write_pointer(state_root, "previous", current["bundle_id"])
    write_pointer(state_root, "current", bundle_id)
    (state_root / "candidate.json").unlink()
    return {"status": "activated", "bundle_id": bundle_id}


def install_release_bundle(state_root: Path, bundle: ReleaseBundle) -> str:
    bundle_id = stage_release_bundle(state_root, bundle)
    activate_candidate_release(state_root)
    return bundle_id


def activate_previous_release(state_root: Path) -> dict[str, str]:
    current_pointer = read_pointer(state_root, "current")
    previous_pointer = read_pointer(state_root, "previous")
    if current_pointer is None or previous_pointer is None:
        raise ReleaseOperationError("an immediately preceding release is unavailable")
    current = read_bundle(state_root, current_pointer["bundle_id"])
    previous = read_bundle(state_root, previous_pointer["bundle_id"])
    if current["compatibility_epoch"] != previous["compatibility_epoch"]:
        return {
            "status": "restore_required",
            "reason": "persisted-data compatibility epoch changed",
        }
    write_pointer(state_root, "current", previous_pointer["bundle_id"])
    write_pointer(state_root, "previous", current_pointer["bundle_id"])
    (state_root / "candidate.json").unlink(missing_ok=True)
    return {"status": "activated", "bundle_id": previous_pointer["bundle_id"]}


class MaintenanceGate(Protocol):
    def is_enabled(self) -> bool: ...

    def set_enabled(self, enabled: bool) -> None: ...


class PostgresMaintenanceGate:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def is_enabled(self) -> bool:
        with psycopg.connect(self.database_url, connect_timeout=2) as connection:
            row = connection.execute(
                "SELECT thesistrace_control.maintenance_enabled()"
            ).fetchone()
        return bool(row and row[0])

    def set_enabled(self, enabled: bool) -> None:
        with psycopg.connect(self.database_url, connect_timeout=3) as connection:
            connection.execute(
                "SELECT thesistrace_control.set_platform_maintenance(%s)",
                (enabled,),
            )


class ScheduleControl(Protocol):
    def pause(self) -> None: ...

    def resume(self) -> None: ...


class ActivityMonitor(Protocol):
    def running_count(self) -> int: ...


class WorkerControl(Protocol):
    def stop_normally(self) -> None: ...

    def start(self) -> None: ...


@dataclass(frozen=True)
class MaintenanceResult:
    drained: bool
    remaining_activities: int
    interrupted_activity_state: str


class MaintenanceCoordinator:
    def __init__(
        self,
        *,
        gate: MaintenanceGate,
        schedules: ScheduleControl,
        activities: ActivityMonitor,
        workers: WorkerControl,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.gate = gate
        self.schedules = schedules
        self.activities = activities
        self.workers = workers
        self.clock = clock
        self.sleep = sleep

    def enter(
        self,
        *,
        max_drain_seconds: int = 900,
        poll_interval: float = 1.0,
    ) -> MaintenanceResult:
        if not 1 <= max_drain_seconds <= 900:
            raise ReleaseOperationError("maintenance drain must be between 1 and 900 seconds")
        if poll_interval <= 0:
            raise ReleaseOperationError("maintenance poll interval must be positive")
        self.gate.set_enabled(True)
        self.schedules.pause()
        deadline = self.clock() + max_drain_seconds
        remaining = self.activities.running_count()
        while remaining > 0 and self.clock() < deadline:
            self.sleep(min(poll_interval, deadline - self.clock()))
            remaining = self.activities.running_count()
        self.workers.stop_normally()
        return MaintenanceResult(
            drained=remaining == 0,
            remaining_activities=remaining,
            interrupted_activity_state=(
                "none" if remaining == 0 else "nonterminal_redelivery"
            ),
        )

    def exit(self) -> None:
        self.workers.start()
        self.schedules.resume()
        self.gate.set_enabled(False)


def provision_role_secrets(
    secret_root: Path,
    values: Mapping[str, str],
) -> dict[str, Path]:
    secret_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret_root.chmod(0o700)
    paths: dict[str, Path] = {}
    for name, value in sorted(values.items()):
        if not IDENTIFIER.fullmatch(name) or not value:
            raise ReleaseOperationError("secret names and values must be nonempty")
        path = secret_root / name
        if path.exists() and path.read_text() != value:
            raise ReleaseOperationError(f"refusing to overwrite role secret: {name}")
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(value)
        path.chmod(0o600)
        paths[name] = path
    return paths


def recovery_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 16:
        raise ReleaseOperationError("recovery passphrase must contain at least 16 characters")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def seal_recovery_bundle(
    path: Path,
    values: Mapping[str, str],
    *,
    passphrase: str,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    ciphertext = AESGCM(recovery_key(passphrase, salt)).encrypt(
        nonce,
        canonical_json(dict(values)),
        RECOVERY_MAGIC,
    )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(RECOVERY_MAGIC + salt + nonce + base64.b64encode(ciphertext))
    temporary.replace(path)
    path.chmod(0o600)
    return path


def open_recovery_bundle(path: Path, *, passphrase: str) -> dict[str, str]:
    payload = path.read_bytes()
    if not payload.startswith(RECOVERY_MAGIC) or len(payload) < 33:
        raise ReleaseOperationError("invalid recovery bundle")
    salt = payload[5:21]
    nonce = payload[21:33]
    ciphertext = base64.b64decode(payload[33:], validate=True)
    plaintext = AESGCM(recovery_key(passphrase, salt)).decrypt(
        nonce,
        ciphertext,
        RECOVERY_MAGIC,
    )
    values = json.loads(plaintext)
    if not isinstance(values, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in values.items()
    ):
        raise ReleaseOperationError("invalid recovery secret payload")
    return dict(values)

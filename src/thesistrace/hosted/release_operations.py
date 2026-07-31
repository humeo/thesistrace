import base64
import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

RELEASE_MANIFEST_VERSION = 1
RECOVERY_MAGIC = b"TTSR1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_TEMPLATE = re.compile(r"^[a-z0-9._/-]+:\{bundle_id\}$")


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


def source_files(root: Path, paths: list[str]) -> list[Path]:
    files: list[Path] = []
    resolved_root = root.resolve()
    for relative in paths:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(resolved_root)
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
    return sorted(set(files))


def sha256_files(root: Path, files: list[Path]) -> str:
    resolved_root = root.resolve()
    return sha256_named_payloads(
        {
            path.relative_to(resolved_root).as_posix(): path.read_bytes()
            for path in files
        }
    )


def sha256_named_payloads(payloads: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, payload in sorted(payloads.items()):
        relative = name.encode("utf-8")
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
    source_sha256: str
    bundle_state: str
    image_tag: str
    image_ids: dict[str, str]
    custom_images: tuple[str, ...]
    configuration_files: dict[str, bytes]
    configuration_modes: dict[str, int]

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
        custom_image_templates = source.get("custom_images")
        if not isinstance(custom_image_templates, list) or not all(
            isinstance(image, str) and IMAGE_TEMPLATE.fullmatch(image)
            for image in custom_image_templates
        ) or len(set(custom_image_templates)) != len(custom_image_templates):
            raise ReleaseOperationError("custom release images are required")
        component_templates: dict[str, dict[str, str]] = {}
        configuration_files: dict[str, bytes] = {}
        configuration_modes: dict[str, int] = {}
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
            component_source_files = source_files(repository_root, paths)
            component_templates[str(name)] = {
                "version": str(value["version"]),
                "artifact": artifact,
                "source_sha256": sha256_files(
                    repository_root,
                    component_source_files,
                ),
            }
            if name == "configuration":
                resolved_root = repository_root.resolve()
                configuration_files = {
                    path.relative_to(resolved_root).as_posix(): path.read_bytes()
                    for path in component_source_files
                }
                configuration_modes = {
                    path.relative_to(resolved_root).as_posix(): (
                        0o555 if path.stat().st_mode & 0o111 else 0o444
                    )
                    for path in component_source_files
                }
        if not configuration_files:
            raise ReleaseOperationError("release configuration snapshot is required")
        configuration_paths = tuple(sorted(configuration_files))
        content_body = {
            "manifest_version": RELEASE_MANIFEST_VERSION,
            "version": version,
            "compatibility_epoch": compatibility_epoch,
            "components": component_templates,
            "custom_images": custom_image_templates,
            "configuration_paths": configuration_paths,
            "configuration_modes": configuration_modes,
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
            custom_images = tuple(
                image.format(bundle_id=bundle_id)
                for image in custom_image_templates
            )
        except (KeyError, ValueError) as error:
            raise ReleaseOperationError("release artifact template is invalid") from error
        body = {
            "manifest_version": RELEASE_MANIFEST_VERSION,
            "version": version,
            "compatibility_epoch": compatibility_epoch,
            "source_sha256": content_sha256,
            "bundle_state": "staged",
            "content_sha256": content_sha256,
            "components": components,
            "image_tag": bundle_id,
            "image_ids": {},
            "custom_images": custom_images,
            "configuration_paths": configuration_paths,
            "configuration_modes": configuration_modes,
        }
        return cls(
            version=version,
            compatibility_epoch=compatibility_epoch,
            components=components,
            content_sha256=content_sha256,
            manifest_sha256=hashlib.sha256(canonical_json(body)).hexdigest(),
            source_sha256=content_sha256,
            bundle_state="staged",
            image_tag=bundle_id,
            image_ids={},
            custom_images=custom_images,
            configuration_files=configuration_files,
            configuration_modes=configuration_modes,
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
            "source_sha256": self.source_sha256,
            "bundle_state": self.bundle_state,
            "content_sha256": self.content_sha256,
            "components": self.components,
            "image_tag": self.image_tag,
            "image_ids": self.image_ids,
            "custom_images": self.custom_images,
            "configuration_paths": tuple(sorted(self.configuration_files)),
            "configuration_modes": self.configuration_modes,
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
    if not IDENTIFIER.fullmatch(bundle_id):
        raise ReleaseOperationError("release bundle identity is invalid")
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
        for relative, contents in sorted(bundle.configuration_files.items()):
            snapshot = target / "configuration" / relative
            snapshot.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            snapshot.write_bytes(contents)
            snapshot.chmod(bundle.configuration_modes[relative])
    except FileExistsError:
        if (target / "bundle.json").read_bytes() != payload:
            raise ReleaseOperationError("immutable release bundle changed") from None
        for relative, contents in bundle.configuration_files.items():
            snapshot = target / "configuration" / relative
            if not snapshot.is_file() or snapshot.read_bytes() != contents:
                raise ReleaseOperationError(
                    "immutable release configuration changed"
                ) from None
            if (snapshot.stat().st_mode & 0o777) != bundle.configuration_modes[
                relative
            ]:
                raise ReleaseOperationError(
                    "immutable release configuration mode changed"
                ) from None
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
    verify_release_configuration(state_root, bundle_id)
    verify_release_image_lock(state_root, bundle_id)
    current = read_pointer(state_root, "current")
    if current and current["bundle_id"] != bundle_id:
        write_pointer(state_root, "previous", current["bundle_id"])
    write_pointer(state_root, "current", bundle_id)
    (state_root / "candidate.json").unlink()
    return {"status": "activated", "bundle_id": bundle_id}


def image_lock_path(state_root: Path, bundle_id: str) -> Path:
    return state_root / "bundles" / bundle_id / "image-lock.json"


def verify_release_configuration(
    state_root: Path,
    bundle_id: str,
) -> dict[str, object]:
    bundle = read_bundle(state_root, bundle_id)
    configuration_root = state_root / "bundles" / bundle_id / "configuration"
    try:
        paths = bundle["configuration_paths"]
        modes = bundle["configuration_modes"]
        expected = bundle["components"]["configuration"]["source_sha256"]
        if not isinstance(paths, list) or not paths or not isinstance(modes, dict):
            raise ValueError
        payloads: dict[str, bytes] = {}
        for relative in paths:
            if not isinstance(relative, str):
                raise ValueError
            path = (configuration_root / relative).resolve()
            path.relative_to(configuration_root.resolve())
            if not path.is_file():
                raise ValueError
            if (path.stat().st_mode & 0o777) != modes.get(relative):
                raise ValueError
            payloads[relative] = path.read_bytes()
        if sha256_named_payloads(payloads) != expected:
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise ReleaseOperationError("release configuration snapshot is invalid") from error
    return bundle


def image_lock_payload(bundle_id: str, images: Mapping[str, str]) -> bytes:
    if not images or not all(
        name and IMAGE_DIGEST.fullmatch(digest)
        for name, digest in images.items()
    ):
        raise ReleaseOperationError("release image names and SHA-256 IDs are required")
    body: dict[str, object] = {
        "bundle_id": bundle_id,
        "images": dict(sorted(images.items())),
    }
    body["lock_sha256"] = hashlib.sha256(canonical_json(body)).hexdigest()
    return canonical_json(body) + b"\n"


def finalized_content_sha256(
    source_sha256: str,
    image_ids: Mapping[str, str],
) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256) or not image_ids:
        raise ReleaseOperationError("release source and image identities are required")
    if not all(
        isinstance(name, str)
        and name
        and isinstance(digest, str)
        and IMAGE_DIGEST.fullmatch(digest)
        for name, digest in image_ids.items()
    ):
        raise ReleaseOperationError("release image names and SHA-256 IDs are required")
    repositories: dict[str, str] = {}
    for name, digest in image_ids.items():
        repository, separator, tag = name.rpartition(":")
        if not separator or not repository or not tag or repository in repositories:
            raise ReleaseOperationError("release image names must have unique tags")
        repositories[repository] = digest
    return hashlib.sha256(
        canonical_json(
            {
                "source_sha256": source_sha256,
                "image_ids_by_repository": dict(sorted(repositories.items())),
            }
        )
    ).hexdigest()


def finalized_release_bundle(
    state_root: Path,
    staged_bundle_id: str,
    images: Mapping[str, str],
) -> ReleaseBundle:
    staged = verify_release_configuration(state_root, staged_bundle_id)
    source_sha256 = str(staged.get("source_sha256", ""))
    if staged.get("bundle_state") != "staged":
        raise ReleaseOperationError("release bundle is not staged")
    content_sha256 = finalized_content_sha256(source_sha256, images)
    version = str(staged["version"])
    final_bundle_id = f"{version}-{content_sha256[:16]}"
    image_ids_by_repository = {
        name.rpartition(":")[0]: digest for name, digest in images.items()
    }
    final_image_ids = {
        f"{repository}:{final_bundle_id}": digest
        for repository, digest in sorted(image_ids_by_repository.items())
    }
    components = {
        str(name): {
            **dict(component),
            "artifact": str(component["artifact"]).replace(
                f":{staged_bundle_id}",
                f":{final_bundle_id}",
            ),
        }
        for name, component in dict(staged["components"]).items()
    }
    configuration_root = (
        state_root / "bundles" / staged_bundle_id / "configuration"
    )
    configuration_paths = staged["configuration_paths"]
    configuration_modes = staged["configuration_modes"]
    if not isinstance(configuration_paths, list) or not isinstance(
        configuration_modes, dict
    ):
        raise ReleaseOperationError("release configuration snapshot is invalid")
    configuration_files = {
        str(relative): (configuration_root / str(relative)).read_bytes()
        for relative in configuration_paths
    }
    body = {
        "manifest_version": RELEASE_MANIFEST_VERSION,
        "version": version,
        "compatibility_epoch": str(staged["compatibility_epoch"]),
        "source_sha256": source_sha256,
        "bundle_state": "finalized",
        "content_sha256": content_sha256,
        "components": components,
        "image_tag": final_bundle_id,
        "image_ids": final_image_ids,
        "custom_images": tuple(final_image_ids),
        "configuration_paths": configuration_paths,
        "configuration_modes": configuration_modes,
    }
    finalized = ReleaseBundle(
        version=version,
        compatibility_epoch=str(staged["compatibility_epoch"]),
        components=components,
        content_sha256=content_sha256,
        manifest_sha256=hashlib.sha256(canonical_json(body)).hexdigest(),
        source_sha256=source_sha256,
        bundle_state="finalized",
        image_tag=final_bundle_id,
        image_ids=final_image_ids,
        custom_images=tuple(final_image_ids),
        configuration_files=configuration_files,
        configuration_modes={
            str(relative): int(mode)
            for relative, mode in configuration_modes.items()
        },
    )
    if finalized.bundle_id != final_bundle_id:
        raise ReleaseOperationError("final release bundle identity is invalid")
    return finalized


def lock_release_images(
    state_root: Path,
    bundle_id: str,
    images: Mapping[str, str],
) -> dict[str, object]:
    bundle = read_bundle(state_root, bundle_id)
    if set(images) != set(bundle.get("custom_images", [])):
        raise ReleaseOperationError("release image set does not match the bundle")
    if bundle.get("bundle_state") == "finalized":
        if dict(bundle["image_ids"]) != dict(images):
            raise ReleaseOperationError("immutable image lock changed")
        return verify_release_image_lock(state_root, bundle_id, images)
    finalized = finalized_release_bundle(state_root, bundle_id, images)
    final_bundle_id = store_release_bundle(state_root, finalized)
    path = image_lock_path(state_root, final_bundle_id)
    payload = image_lock_payload(final_bundle_id, finalized.image_ids)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ReleaseOperationError("immutable image lock changed") from None
    write_pointer(state_root, "candidate", final_bundle_id)
    if final_bundle_id != bundle_id:
        shutil.rmtree(state_root / "bundles" / bundle_id)
    return verify_release_image_lock(state_root, final_bundle_id)


def verify_release_image_lock(
    state_root: Path,
    bundle_id: str,
    actual_images: Mapping[str, str] | None = None,
) -> dict[str, object]:
    bundle = read_bundle(state_root, bundle_id)
    path = image_lock_path(state_root, bundle_id)
    if not path.is_file():
        raise ReleaseOperationError("release image lock is unavailable")
    try:
        lock = json.loads(path.read_text())
        images = lock["images"]
        expected_checksum = lock["lock_sha256"]
        if lock["bundle_id"] != bundle_id or not isinstance(images, dict):
            raise ValueError
        if bundle.get("bundle_state") != "finalized":
            raise ValueError
        if set(images) != set(bundle.get("custom_images", [])):
            raise ValueError
        if dict(images) != bundle.get("image_ids"):
            raise ValueError
        if finalized_content_sha256(
            str(bundle.get("source_sha256", "")),
            images,
        ) != bundle.get("content_sha256"):
            raise ValueError
        body = {"bundle_id": bundle_id, "images": images}
        if hashlib.sha256(canonical_json(body)).hexdigest() != expected_checksum:
            raise ValueError
        if not all(
            isinstance(name, str)
            and isinstance(digest, str)
            and IMAGE_DIGEST.fullmatch(digest)
            for name, digest in images.items()
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise ReleaseOperationError("release image lock is invalid") from error
    if actual_images is not None and dict(images) != dict(actual_images):
        raise ReleaseOperationError("release image IDs do not match the immutable lock")
    return dict(lock)


def validate_previous_release(state_root: Path) -> dict[str, str]:
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
    verify_release_configuration(state_root, previous_pointer["bundle_id"])
    verify_release_image_lock(state_root, previous_pointer["bundle_id"])
    return {"status": "compatible", "bundle_id": previous_pointer["bundle_id"]}


def activate_previous_release(state_root: Path) -> dict[str, str]:
    validation = validate_previous_release(state_root)
    if validation["status"] == "restore_required":
        return validation
    current_pointer = read_pointer(state_root, "current")
    previous_pointer = read_pointer(state_root, "previous")
    if current_pointer is None or previous_pointer is None:
        raise ReleaseOperationError("an immediately preceding release is unavailable")
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

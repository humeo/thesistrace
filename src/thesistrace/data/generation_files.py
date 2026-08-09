from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path


class AddressedFileError(RuntimeError):
    pass


class AddressedFileStore:
    """Crash-safe, content-addressed files below one owned mount root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def read(
        self,
        path: Path,
        expected_sha256: str,
        *,
        expected_byte_count: int | None = None,
        max_byte_count: int | None = None,
    ) -> bytes:
        _require_within_root(path, self._root)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except (FileNotFoundError, OSError) as error:
            raise AddressedFileError("addressed file is missing or unsafe") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise AddressedFileError("addressed file is not a regular file")
            if expected_byte_count is not None and metadata.st_size != expected_byte_count:
                raise AddressedFileError("addressed file byte count is invalid")
            if max_byte_count is not None and metadata.st_size > max_byte_count:
                raise AddressedFileError("addressed file exceeds its byte bound")
            content = bytearray()
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                content.extend(chunk)
                digest.update(chunk)
            if len(content) != metadata.st_size:
                raise AddressedFileError("addressed file changed while reading")
            if digest.hexdigest() != expected_sha256:
                raise AddressedFileError("addressed file checksum is invalid")
            return bytes(content)
        finally:
            os.close(descriptor)

    def store(self, target: Path, sha256: str, content: bytes) -> None:
        _require_within_root(target, self._root)
        if hashlib.sha256(content).hexdigest() != sha256:
            raise AddressedFileError("addressed content checksum is invalid")
        self._ensure_parent(target.parent)
        try:
            existing = self.read(
                target,
                sha256,
                expected_byte_count=len(content),
                max_byte_count=len(content),
            )
        except AddressedFileError as error:
            if target.exists() or target.is_symlink():
                try:
                    raced = self.read(
                        target,
                        sha256,
                        expected_byte_count=len(content),
                        max_byte_count=len(content),
                    )
                except AddressedFileError as raced_error:
                    raise AddressedFileError(
                        "immutable addressed content conflicts"
                    ) from raced_error
                if raced == content:
                    return
                raise AddressedFileError("immutable addressed content conflicts") from error
        else:
            if existing != content:
                raise AddressedFileError("immutable addressed content conflicts")
            return

        descriptor, temporary_name = tempfile.mkstemp(prefix=".candidate-", dir=target.parent)
        temporary = Path(temporary_name)
        installed = False
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target, follow_symlinks=False)
                installed = True
            except FileExistsError:
                existing = self.read(
                    target,
                    sha256,
                    expected_byte_count=len(content),
                    max_byte_count=len(content),
                )
                if existing != content:
                    raise AddressedFileError("immutable addressed content conflicts") from None
            if installed:
                _fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _ensure_parent(self, parent: Path) -> None:
        parent.mkdir(parents=True, exist_ok=True)
        current = parent
        while True:
            _fsync_directory(current)
            if current == self._root:
                return
            if self._root not in current.parents:
                raise AddressedFileError("addressed path escapes its mount root")
            current = current.parent


def _require_within_root(path: Path, root: Path) -> None:
    if path == root or root not in path.parents:
        raise AddressedFileError("addressed path escapes its mount root")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ("AddressedFileError", "AddressedFileStore")

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class AddressedFileError(RuntimeError):
    pass


class _EntryMissing(FileNotFoundError):
    pass


class AddressedFileStore:
    """Crash-safe addressed files accessed beneath a symlink-safe mount root."""

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
        try:
            with self._open_parent(path, create=False) as (parent_fd, name):
                return _read_entry(
                    parent_fd,
                    name,
                    expected_sha256,
                    expected_byte_count=expected_byte_count,
                    max_byte_count=max_byte_count,
                )
        except AddressedFileError:
            raise
        except FileNotFoundError as error:
            raise AddressedFileError("addressed file is missing") from error
        except OSError as error:
            raise AddressedFileError("addressed filesystem read failed or is unsafe") from error

    def store(self, target: Path, sha256: str, content: bytes) -> None:
        if hashlib.sha256(content).hexdigest() != sha256:
            raise AddressedFileError("addressed content checksum is invalid")
        try:
            with self._open_parent(target, create=True) as (parent_fd, name):
                self._store_entry(parent_fd, name, sha256, content)
        except AddressedFileError:
            raise
        except OSError as error:
            raise AddressedFileError("addressed filesystem write failed or is unsafe") from error

    def _store_entry(
        self,
        parent_fd: int,
        name: str,
        sha256: str,
        content: bytes,
    ) -> None:
        try:
            existing = _read_entry(
                parent_fd,
                name,
                sha256,
                expected_byte_count=len(content),
                max_byte_count=len(content),
            )
        except _EntryMissing:
            pass
        except AddressedFileError as error:
            raise AddressedFileError("immutable addressed content conflicts") from error
        else:
            if existing != content:
                raise AddressedFileError("immutable addressed content conflicts")
            return

        temporary_name, descriptor = _create_temporary(parent_fd)
        installed = False
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                installed = True
            except FileExistsError:
                try:
                    raced = _read_entry(
                        parent_fd,
                        name,
                        sha256,
                        expected_byte_count=len(content),
                        max_byte_count=len(content),
                    )
                except (AddressedFileError, _EntryMissing) as error:
                    raise AddressedFileError("immutable addressed content conflicts") from error
                if raced != content:
                    raise AddressedFileError("immutable addressed content conflicts") from None
            if installed:
                _fsync_directory(parent_fd)
        finally:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
                _fsync_directory(parent_fd)
            except FileNotFoundError:
                pass

    @contextmanager
    def _open_parent(self, path: Path, *, create: bool) -> Iterator[tuple[int, str]]:
        relative = _relative_address(path, self._root)
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self._root, flags)
        try:
            for component in relative.parts[:-1]:
                if create:
                    try:
                        os.mkdir(component, mode=0o755, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    else:
                        _fsync_directory(descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            yield descriptor, relative.name
        finally:
            os.close(descriptor)


def _read_entry(
    parent_fd: int,
    name: str,
    expected_sha256: str,
    *,
    expected_byte_count: int | None,
    max_byte_count: int | None,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError as error:
        raise _EntryMissing(name) from error
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


def _create_temporary(parent_fd: int) -> tuple[str, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    while True:
        name = f".candidate-{secrets.token_hex(12)}"
        try:
            return name, os.open(name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            continue


def _relative_address(path: Path, root: Path) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise AddressedFileError("addressed path escapes its mount root") from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise AddressedFileError("addressed path escapes its mount root")
    return relative


def _fsync_directory(descriptor: int) -> None:
    os.fsync(descriptor)


__all__ = ("AddressedFileError", "AddressedFileStore")

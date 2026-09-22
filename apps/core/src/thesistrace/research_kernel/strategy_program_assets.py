"""Install the pinned Python guest as an explicit dependency setup operation."""

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

PYTHON_VERSION = "3.14.7"
WASMTIME_VERSION = "49.0.0"
ARCHIVE_SHA256 = "2e064d3fb8172471d39d741348efa722349c40b96301f69968dff714999c584b"
ARCHIVE_BYTES = 14_291_017
ARCHIVE_URL = (
    "https://github.com/brettcannon/cpython-wasi-build/releases/download/v3.14.7/"
    "python-3.14.7-wasi_sdk-24.zip"
)


class StrategyRuntimeUnavailable(RuntimeError):
    pass


def runtime_archive_path() -> Path:
    return Path(sys.prefix) / "share" / "thesistrace" / "cpython-wasi.zip"


def verified_archive(path: Path) -> bytes:
    try:
        if path.stat().st_size != ARCHIVE_BYTES:
            raise StrategyRuntimeUnavailable("Python Strategy runtime archive has the wrong size")
        content = path.read_bytes()
    except OSError as error:
        raise StrategyRuntimeUnavailable(
            "Python Strategy runtime is missing; run the explicit runtime installation command"
        ) from error
    if hashlib.sha256(content).hexdigest() != ARCHIVE_SHA256:
        raise StrategyRuntimeUnavailable("Python Strategy runtime archive checksum differs")
    return content


def unpack_runtime(content: bytes, destination: Path) -> bytes:
    """Expose only pinned standard-library files; compile the guest from verified bytes."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        wasm = archive.read("python.wasm")
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts:
                raise StrategyRuntimeUnavailable("Python Strategy runtime archive path is invalid")
            if not item.filename.startswith("lib/") or item.is_dir():
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
            os.utime(target, (0, 0))
        for directory in sorted(destination.rglob("*"), reverse=True):
            if directory.is_dir():
                os.utime(directory, (0, 0))
    return wasm


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded pinned archive")
    args = parser.parse_args()
    destination = runtime_archive_path()
    if destination.exists():
        verified_archive(destination)
        print(json.dumps({
            "status": "verified", "python": PYTHON_VERSION, "sha256": ARCHIVE_SHA256,
        }))
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            if args.archive is not None:
                temporary.write(verified_archive(args.archive))
            else:
                with urllib.request.urlopen(ARCHIVE_URL, timeout=60) as response:
                    content = response.read(ARCHIVE_BYTES + 1)
                temporary.write(content)
            temporary.flush()
            verified_archive(temporary_path)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    print(json.dumps({
        "status": "installed", "python": PYTHON_VERSION, "sha256": ARCHIVE_SHA256,
    }))


if __name__ == "__main__":
    main()

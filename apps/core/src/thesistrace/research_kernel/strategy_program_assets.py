"""Verify the packaged Python + NumPy component; never fetch code during execution."""

import gzip
import hashlib
import io
import json
from pathlib import Path

_ASSETS = Path(__file__).with_name("python_runtime")
_MANIFEST = json.loads((_ASSETS / "manifest.json").read_text())
PYTHON_VERSION = _MANIFEST["python"]
NUMPY_VERSION = _MANIFEST["numpy"]
WASMTIME_VERSION = _MANIFEST["wasmtime"]
ARCHIVE_SHA256 = _MANIFEST["archive_sha256"]


class StrategyRuntimeUnavailable(RuntimeError):
    pass


def verified_component() -> bytes:
    """Bind the verified component to the trusted source that initialized it."""
    try:
        for name, digest in _MANIFEST["source_sha256"].items():
            if hashlib.sha256((_ASSETS / name).read_bytes()).hexdigest() != digest:
                raise StrategyRuntimeUnavailable(
                    "Python runtime source requires an explicit rebuild",
                )
        archive = (_ASSETS / "prepared.wasm.gz").read_bytes()
        if (len(archive) != _MANIFEST["archive_bytes"]
                or hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256):
            raise StrategyRuntimeUnavailable("Python runtime component archive checksum differs")
        with gzip.GzipFile(fileobj=io.BytesIO(archive)) as stream:
            wasm = stream.read(_MANIFEST["wasm_bytes"] + 1)
        if (len(wasm) != _MANIFEST["wasm_bytes"]
                or hashlib.sha256(wasm).hexdigest() != _MANIFEST["wasm_sha256"]):
            raise StrategyRuntimeUnavailable("Python runtime component checksum differs")
        return wasm
    except (OSError, EOFError) as error:
        raise StrategyRuntimeUnavailable(
            "Python runtime component is missing or corrupt",
        ) from error


def main() -> None:
    # Image setup populates Wasmtime's supported compilation cache on the target
    # architecture. Execution still verifies the portable component before use.
    from thesistrace.research_kernel.python_execution import PreparedPythonEnvironment

    with PreparedPythonEnvironment(""):
        pass
    print(json.dumps({"status": "verified", "python": PYTHON_VERSION,
                      "numpy": NUMPY_VERSION, "sha256": ARCHIVE_SHA256}))


if __name__ == "__main__":
    main()

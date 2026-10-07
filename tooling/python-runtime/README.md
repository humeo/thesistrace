# Portable Python numerical runtime

The shipped `apps/core/src/thesistrace/research_kernel/python_runtime/` component
contains only initialized trusted CPython and NumPy libraries. Researcher source,
market data, account and continuation state are supplied after a fresh instance
has been created. Runtime behavior and limits are in
[the Python strategy contract](../../docs/python-strategy.md); verification
selection and commands belong to [AGENTS.md](../../AGENTS.md#testing).

`manifest.json` binds the compressed component to its source, versions and build
inputs. Core image setup verifies it and warms Wasmtime's supported compiled-code
cache on the target architecture. The portable WASM is verified before use even
when compiled code is cached. No serialized native artifact is loaded directly.

## Explicit rebuild

From the repository root, use:

```sh
uv run --project apps/core python tooling/python-runtime/build.py
```

The builder downloads only checksum-pinned inputs into `.local/python-runtime-build`.
Its Linux amd64 toolchain image is pinned by manifest and image-config SHA-256.
Once fetched, compilation runs in a network-disabled Docker container with two
CPUs, 4 GiB memory and no swap. Build resources are separate from the production
worker's 2 GiB ceiling. NumPy and Python are compiled for WASI, so the output runs
on any qualified Wasmtime host architecture. Source/recipe changes require an
explicit rebuild, a new execution identity and qualification.

We reuse the NumPy cross-build recipe from `actpkg/python-env` at the locked
revision. Its WASM exception-handling flags and NumPy platform patches are
retained. The local changes restrict inputs to the verified offline wheelhouse,
limit compiler parallelism, set `PYTHONHASHSEED=0` during component initialization,
and remove the Windows path probe from the Linux-only component builder. All
changes are visible in `patches.py`; the upstream sources and build dependencies
are recorded in `inputs.lock.json`.

The componentize-py toolchain embeds its CPython 3.14.0 WASI fork. This differs
from the previous 3.14.7 runtime and is recorded in the current environment rather
than hidden by a compatibility shim. NumPy uses WASI array kernels without an
external BLAS/LAPACK library or host CPU dispatch. Only the existing bounded
history capability exposes application data; importing NumPy grants no files,
network or access to host native libraries.

Third-party notices are distributed with the component under `licenses/`.
The source archive, upstream recipe, patched component builder and runtime
artifact are separately identifiable; benchmark conclusions must use the actual
shipped component and a complete, unchanged strategy replay.

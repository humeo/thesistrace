"""Small build-only changes against the exact locked Linux toolchain and recipes."""

import json
import subprocess
from pathlib import Path

lock = json.loads(Path("/recipe/inputs.lock.json").read_text())
componentize = Path("/opt/toolchain/componentize-py")
revision = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=componentize, text=True,
).strip()
if revision != lock["componentize_py"]:
    raise ValueError("Component builder revision differs")

source = componentize / "src/lib.rs"
text = source.read_text()
anchor = '.env("PYTHONUNBUFFERED", "1")'
assert text.count(anchor) == 1
source.write_text(text.replace(anchor, anchor + '\n            .env("PYTHONHASHSEED", "0")'))

# This image is Linux-only. Avoid the Windows cygpath probe under emulation;
# keep the actual Linux directory unchanged.
source = componentize / "build.rs"
text = source.read_text()
start = text.index('    let mut cpython_wasi_dir = repo_dir.join("cpython/builddir/wasi");',
                   text.index("fn make_pyo3_config"))
end = text.index("    let mut pyo3_config =", start)
replacement = '    let cpython_wasi_dir = repo_dir.join("cpython/builddir/wasi");\n\n'
source.write_text(text[:start] + replacement + text[end:])

source = Path("/work/sci/wheels/libs/numpy.sh")
text = source.read_text()
start, end = text.index("fetch_source() {"), text.index("# Called by build-wheel.sh")
source.write_text(text[:start] + '''fetch_source() {
  tar xf /work/numpy-2.5.0.tar.gz -C "$SRC" --strip-components=1
}
BUILD_CMD_EXTRA_ARGS+=("-Ccompile-args=-j2")

''' + text[end:])

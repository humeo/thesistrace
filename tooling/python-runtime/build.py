"""Explicit, pinned, offline-container build of the portable Python/NumPy image."""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPE = Path(__file__).resolve().parent
ASSETS = ROOT / "apps/core/src/thesistrace/research_kernel/python_runtime"
LOCK = json.loads((RECIPE / "inputs.lock.json").read_text())


def fetch(item, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        url = item.get("url")
        if url is None:
            endpoint = f'https://pypi.org/pypi/{item["package"]}/{item["version"]}/json'
            with urllib.request.urlopen(endpoint, timeout=60) as response:
                release = json.load(response)
            url = next(entry["url"] for entry in release["urls"]
                       if entry["filename"] == target.name)
        with urllib.request.urlopen(url, timeout=60) as response:
            temporary = target.with_suffix(target.suffix + ".download")
            with temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(target)
    data = target.read_bytes()
    if (hashlib.sha256(data).hexdigest() != item["sha256"]
            or ("size" in item and len(data) != item["size"])):
        raise ValueError(f"Build input checksum differs: {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/python-runtime-build")
    args = parser.parse_args()
    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    for item in LOCK["inputs"]:
        fetch(item, cache / "inputs" / item["file"])
        target = cache / item["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cache / "inputs" / item["file"], target)
    image = LOCK["toolchain_image"]
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode:
        subprocess.run(["docker", "pull", "--platform", "linux/amd64",
                        image], check=True)
        subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.DEVNULL)
    prepared = cache / "prepared"
    prepared.mkdir(exist_ok=True)
    for name in ("prepared.py", "execution.wit"):
        shutil.copyfile(ASSETS / name, prepared / name)
    subprocess.run([
        "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
        "--cpus", "2", "--memory", "4g", "--memory-swap", "4g",
        "--mount", f"type=bind,src={cache},dst=/work",
        "--mount", f"type=bind,src={prepared},dst=/prototype",
        "--mount", f"type=bind,src={RECIPE},dst=/recipe,readonly",
        "--entrypoint", "bash", image, "/recipe/build.sh",
    ], check=True)
    wasm = (prepared / "prepared.wasm").read_bytes()
    archive = gzip.compress(wasm, mtime=0)
    manifest = json.loads((ASSETS / "manifest.json").read_text())
    manifest.update(
        wasm_bytes=len(wasm), wasm_sha256=hashlib.sha256(wasm).hexdigest(),
        archive_bytes=len(archive), archive_sha256=hashlib.sha256(archive).hexdigest(),
        source_sha256={name: hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()
                       for name in ("prepared.py", "execution.wit")},
        build_recipe_sha256={
            name: hashlib.sha256((RECIPE / name).read_bytes()).hexdigest()
            for name in ("build.py", "build.sh", "patches.py", "inputs.lock.json")
        },
    )
    (ASSETS / "prepared.wasm.gz").write_bytes(archive)
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copytree(prepared / "licenses", ASSETS / "licenses", dirs_exist_ok=True)
    wheel = next((cache / "dist").glob("numpy-*-wasi_0_0_0_wasm32.whl"))
    with zipfile.ZipFile(wheel) as package:
        for name in package.namelist():
            if ".dist-info/licenses/" in name and not name.endswith("/"):
                relative = Path(name.split(".dist-info/licenses/", 1)[1])
                target = ASSETS / "licenses/numpy" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(name))
    print(json.dumps({"status": "built", "manifest": str(ASSETS / "manifest.json"),
                      "wasm_sha256": manifest["wasm_sha256"]}))


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail
export WASI_SDK_PATH=/opt/wasi-sdk PIP_NO_INDEX=1 PIP_FIND_LINKS=/work/wheelhouse
python3 /recipe/patches.py
bash /work/sci/wheels/build-wheel.sh numpy
cd /opt/toolchain/componentize-py
cargo build --release --offline --locked -j 2
install target/release/componentize-py /opt/toolchain/bin/componentize-py
python3 -m pip install --break-system-packages --no-index --platform wasi_0_0_0_wasm32 \
  --python-version 3.14 --target /tmp/thesistrace-numpy --only-binary=:all: \
  --no-deps /work/dist/numpy-2.5.0-cp314-cp314-wasi_0_0_0_wasm32.whl
cd /prototype
componentize-py -d execution.wit -w execution componentize \
  -p /tmp/thesistrace-numpy -p /prototype prepared -o /prototype/prepared.wasm
mkdir -p licenses
cp /opt/toolchain/componentize-py/LICENSE licenses/componentize-py.txt
cp /opt/toolchain/componentize-py/cpython/LICENSE licenses/CPython.txt
cp /work/licenses/*.txt licenses/
cp /opt/toolchain/src/zlib-1.3.1/LICENSE licenses/zlib.txt

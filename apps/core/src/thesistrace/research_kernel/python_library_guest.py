"""Load prepared standard-library bytecode through an immutable host capability."""

import importlib.util
import json
import marshal
import os
import sys


class PreparedLibrary:
    def find_spec(self, fullname, path=None, target=None):
        os.write(5, fullname.encode())
        chunks = []
        while chunk := os.pread(5, 65536, 0):
            chunks.append(chunk)
        response = b"".join(chunks)
        if not response:
            return None
        metadata, code = response.split(b"\0", 1)
        metadata = json.loads(metadata)
        loader = PreparedModule(code)
        spec = importlib.util.spec_from_loader(
            fullname, loader, origin=metadata["origin"], is_package=metadata["package"],
        )
        spec.has_location = True
        if metadata["package"]:
            spec.submodule_search_locations = [metadata["origin"].rsplit("/", 1)[0]]
        return spec


class PreparedModule:
    def __init__(self, code):
        self.code = code

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(marshal.loads(self.code), module.__dict__)


sys.meta_path.insert(0, PreparedLibrary())

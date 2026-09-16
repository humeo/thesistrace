"""Read only glibc main-heap chunk headers; never dump allocation contents."""
import collections
import json
import os
import pathlib
import struct
import subprocess
import time

container = "thesistrace-data-operator-worker-1"
pid = int(subprocess.check_output(
    ["docker", "top", container, "-eo", "pid,comm"], text=True
).splitlines()[-1].split()[0])

def inspect():
    maps = pathlib.Path(f"/proc/{pid}/maps").read_text()
    bounds = next(line.split()[0] for line in maps.splitlines() if line.endswith("[heap]"))
    start, end = (int(value, 16) for value in bounds.split("-"))
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    started = time.monotonic()
    position = start
    totals = collections.Counter()
    counts = collections.Counter()
    largest = {"free": [], "in_use_or_tcache": []}
    def header(address):
        data = os.pread(fd, 16, address)
        if len(data) != 16:
            raise RuntimeError("short chunk header")
        return struct.unpack("<QQ", data)
    try:
        while position < end:
            if time.monotonic() - started > 10:
                raise RuntimeError("ten-second traversal limit")
            _, flags = header(position)
            size = flags & ~7
            if size < 32 or size % 16 or position + size > end or flags & 6:
                raise RuntimeError("chunk layout validation failed")
            following = position + size
            if following == end:
                state = "free_top"
            else:
                previous_size, next_flags = header(following)
                state = "in_use_or_tcache" if next_flags & 1 else "free"
                if state == "free" and previous_size != size:
                    raise RuntimeError("free chunk footer validation failed")
            totals[state] += size
            counts[state] += 1
            if state in largest:
                largest[state].append(size)
            position = following
    finally:
        os.close(fd)
    after = next(line.split()[0] for line in pathlib.Path(f"/proc/{pid}/maps").read_text().splitlines() if line.endswith("[heap]"))
    if bounds != after:
        raise RuntimeError("heap bounds changed during inspection")
    return {
        "pid": pid, "timestamp_unix": time.time(), "heap_bytes": end-start,
        "bytes": dict(totals), "chunks": dict(counts),
        "largest_chunk_bytes": {k: sorted(v, reverse=True)[:5] for k,v in largest.items()},
        "walk_seconds": round(time.monotonic()-started, 3), "validated_end": position == end,
    }

for _ in range(2):
    print(json.dumps(inspect()), flush=True)

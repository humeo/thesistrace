"""Exercise allocator retention/release in the final Linux application image."""
import gc
import json
from pathlib import Path

from thesistrace._memory import release_unused_memory

def rss():
    line = next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmRSS:'))
    return int(line.split()[1]) * 1024

release_unused_memory()
initial = rss()
cycles = []
for _ in range(3):
    blocks = [bytearray(b'x' * 65536) for _ in range(4096)]
    # A few live allocations keep the heap fragmented after the bulk is freed.
    retained = blocks[::512]
    del blocks
    gc.collect()
    before = rss()
    release_unused_memory()
    after = rss()
    assert before - after > 128 * 1024**2, (before, after)
    assert after - initial < 32 * 1024**2, (initial, after)
    cycles.append({'before_release_bytes': before, 'after_release_bytes': after, 'returned_bytes': before - after})
    del retained
    release_unused_memory()
print(json.dumps({'initial_rss_bytes': initial, 'cycles': cycles, 'passed': True}))

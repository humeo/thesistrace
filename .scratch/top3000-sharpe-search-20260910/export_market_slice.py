"""Read-only export of pinned immutable market objects for an offline capital probe.

Run inside the existing local API container with this file on stdin. No writes to
the container or its volumes. The archive is a PARTIAL research-only replica; it
must never be published as a Dataset Release or installed as a Dataset Head.
"""
import argparse
import hashlib
import json
import pathlib
import sys
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--root', default='/var/lib/thesistrace/canonical-data')
parser.add_argument('--generation', default='4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f')
parser.add_argument('--end', default='2026-08-27')
parser.add_argument('--archive', action='store_true')
args = parser.parse_args()
ROOT = pathlib.Path(args.root)
GENERATION = args.generation
START, END = '2025-08-01', args.end
FAMILIES = {
    'market.research_calendar', 'market.instrument_identity',
    'equity.eod_price', 'equity.trading_state', 'equity.price_limit',
    'equity.liquidity_universe', 'equity.industry_membership',
}
files = {}

def addressed(sha, kind):
    suffix = '.json' if kind == 'manifests' else '.parquet'
    p = ROOT / kind / 'sha256' / sha[:2] / (sha + suffix)
    assert p.is_file() and not p.is_symlink(), str(p)
    return p

def read_manifest(sha):
    p = addressed(sha, 'manifests')
    b = p.read_bytes()
    assert hashlib.sha256(b).hexdigest() == sha
    files[p] = len(b)
    return json.loads(b)

root = read_manifest(GENERATION)
assert root['data_through_session'] == END
assert root['format'] == 'thesistrace-family-generation'
table_summary = []
for family in root['families']:
    fm = read_manifest(family['manifest_sha256'])
    if family['family_id'] not in FAMILIES:
        continue
    for table in fm['tables']:
        tm = read_manifest(table['manifest_sha256'])
        objects = tm['objects']
        if tm['partitioning']['kind'] == 'research-session-block':
            objects = [o for o in objects if o['last_sort_key'][0] >= START and o['first_sort_key'][0] <= END]
        for obj in objects:
            p = addressed(obj['sha256'], 'objects')
            assert p.stat().st_size == obj['byte_count']
            files[p] = obj['byte_count']
        table_summary.append({'table':table['name'], 'selected_objects':len(objects), 'bytes':sum(o['byte_count'] for o in objects)})
inventory = {'generation_manifest_sha256':GENERATION, 'source_data_through_session':END,
             'requested_start':START, 'requested_end':END, 'partial_replica':True,
             'files':len(files), 'bytes':sum(files.values()), 'tables':table_summary}
assert inventory['bytes'] < 200 * 1024 * 1024, inventory
if not args.archive:
    print(json.dumps(inventory, indent=2))
    raise SystemExit(0)
print(json.dumps(inventory), file=sys.stderr)
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    for path, size in files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == path.stem
        archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)

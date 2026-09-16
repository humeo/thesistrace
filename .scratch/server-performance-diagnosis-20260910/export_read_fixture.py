"""Export one immutable financial table for offline diagnostics, read only."""
import json
import pathlib
import sys
import tarfile

root = pathlib.Path('/var/lib/docker/volumes/thesistrace_canonical-data/_data')
financial_sha = 'cea82fc459da39fd7757f6e700dbf23d28d09ae6825b8ca9c48ecc62cc4a0d0f'
def path(sha, kind='manifests'):
    suffix = '.json' if kind == 'manifests' else '.parquet'
    return root / kind / 'sha256' / sha[:2] / (sha + suffix)
family_path = path(financial_sha)
family = json.loads(family_path.read_text())
table = next(t for t in family['tables'] if t['name'] == 'income_statement_versions')
table_path = path(table['manifest_sha256'])
manifest = json.loads(table_path.read_text())
files = [family_path, path(family['source_generation_manifest_sha256']), table_path]
files.extend(path(obj['sha256'], 'objects') for obj in manifest['objects'])
size = sum(p.stat().st_size for p in files)
assert size < 150 * 1024 * 1024
assert all(p.is_file() and not p.is_symlink() for p in files)
print(json.dumps({'files':len(files),'bytes':size,'financial_sha':financial_sha}), file=sys.stderr)
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    for p in files:
        archive.add(p, arcname=str(p.relative_to(root)), recursive=False)

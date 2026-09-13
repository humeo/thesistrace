"""Verify a copied immutable source graph before independent candidate preparation."""
import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.benchmark import BenchmarkSnapshotStore, validate_independent_benchmark_mount
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import MountedDatasetHeadStore

parser = argparse.ArgumentParser()
parser.add_argument('--data-root', type=Path, required=True)
parser.add_argument('--benchmark-root', type=Path, required=True)
parser.add_argument('--expected-head', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
started = time.monotonic()
store = MountedGenerationStore(args.data_root)
heads = MountedDatasetHeadStore(args.data_root)
head = heads.current_pointer()
assert head is not None and head.generation_manifest_sha256 == args.expected_head
print('Validating copied Generation', args.expected_head, flush=True)
generation = store.validate_generation(args.expected_head)
print('Current-contract Generation validation passed', flush=True)
references = sorted(store.referenced_files(args.expected_head))
paths = {
    'manifest': store._manifest_path,
    'object': store._object_path,
    'raw_financial': store._raw_financial_path,
    'raw_industry': store._raw_industry_path,
}
byte_count = 0
for index, reference in enumerate(references, 1):
    path = paths[reference.kind](reference.sha256)
    assert not path.is_symlink(), path
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            byte_count += len(block)
    assert digest.hexdigest() == reference.sha256, path
    if index % 5000 == 0:
        print('Verified referenced files', index, '/', len(references), flush=True)
identities = store.read_historical_ordinary_a_share_lifecycles(args.expected_head)
benchmark_root = validate_independent_benchmark_mount(args.data_root, args.benchmark_root)
benchmark = BenchmarkSnapshotStore(benchmark_root).read()
assert benchmark is not None
sessions = store._read_manifest(args.expected_head)['research_sessions']
assert benchmark.coverage_start_session <= sessions[0]
assert benchmark.coverage_end_session >= sessions[-1]
assert set(sessions) <= set(benchmark.level_by_session)
assert heads.current_pointer() == head
report = {
    'verified_at': datetime.now(UTC).isoformat(),
    'source_head': asdict(head),
    'source_families': [asdict(family) for family in generation.families],
    'verified_reference_count': len(references),
    'verified_reference_kinds': dict(Counter(ref.kind for ref in references)),
    'verified_bytes': byte_count,
    'instrument_count': len(identities),
    'delisted_identity_count': sum(bool(item.listed_to) for item in identities),
    'historical_identities': [asdict(item) for item in identities],
    'benchmark': {key: value for key, value in asdict(benchmark).items() if key != 'levels'},
    'head_unchanged': True,
    'elapsed_seconds': time.monotonic() - started,
    'scope': 'Copied source graph integrity and source coverage only; not expanded candidate qualification.',
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print({key: report[key] for key in ('verified_reference_count', 'verified_bytes',
                                  'instrument_count', 'delisted_identity_count', 'elapsed_seconds')},
      flush=True)

"""Build and independently validate the indicator family from retained receipts."""
import argparse
import json
import time
from pathlib import Path

from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--collection', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
started = time.monotonic()
collection = json.loads(args.collection.read_text())
assert collection['status'] == 'source_collection_complete'
assert collection['completed_instrument_count'] == collection['expected_instrument_count']
market = MountedGenerationStore(args.root)
head = collection['source_head']
source = market.inspect_root(head)
identities = {item.ts_code: item.instrument_id
              for item in market.read_historical_ordinary_a_share_identities(head)}
records = collection['collections']
assert len(records) == len(identities)
assert {item['identity']['ts_code']: item['identity']['instrument_id']
        for item in records} == identities
assert all(not item['pending_reports'] for item in records)
evidence = [item['evidence_sha256'] for item in records]
assert len(set(evidence)) == len(evidence)
store = FinancialIndicatorCandidateStore(args.root)
print('Building indicator partitions for', len(identities), 'identities', flush=True)
digest = store.build(collection_evidence_sha256s=evidence, instrument_ids=identities,
                     sessions=source.research_sessions)
print('Validating retained source projection', digest, flush=True)
reopened = FinancialIndicatorCandidateStore(args.root).validate(digest)
assert len(reopened['field_ids']) == 163
assert reopened['instrument_ids'] == identities
assert not reopened['unresolved_sources']
assert market.inspect_root(head) == source
report = {
    'source_generation': head, 'indicator_candidate': digest,
    'source_requests': 0, 'collection_count': len(evidence),
    'partition_count': len(reopened['partitions']),
    'row_count': sum(item['row_count'] for item in reopened['partitions']),
    'field_ids': reopened['field_ids'],
    'research_start': source.research_sessions[0],
    'research_end': source.research_sessions[-1],
    'elapsed_seconds': time.monotonic() - started,
    'scope': 'Complete retained-source projection validation; per-field research coverage pending.',
    'revision_evidence': 'Historical backfill is announcement-aligned; original historical versions are not proven.',
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Indicator family validated', digest, flush=True)

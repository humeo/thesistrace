"""Reproject retained statement history into the current field contract; no source calls."""
import argparse
import json
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from thesistrace.data.fields import alpha_field_catalog
from thesistrace.data.financial_candidate import (
    FinancialCandidateStore, FinancialDiscoveryPublication, _checkpoint_from_evidence,
)
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS, CompletedFinancialCollection, FinancialShardCheckpoint,
)
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--source-integrity', type=Path, required=True)
parser.add_argument('--gap-collection', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
verified = json.loads(args.source_integrity.read_text())
head = verified['source_head']['generation_manifest_sha256']
through = verified['source_head']['data_through_session']
market = MountedGenerationStore(args.root)
generation = market.inspect_root(head)
assert generation.data_through_session == through
store = FinancialCandidateStore(args.root)
prior = generation.financial_candidate_manifest_sha256
assert prior is not None
family = store._read_family(prior)
contract = store._manifest_collection_contract(family)
entries = store._read_evidence_index(family['raw_evidence'])
fields = store.source_fields_by_endpoint(prior)
missing = [field.alpha.identifier for field in alpha_field_catalog()
           if field.family_id == 'equity.financial_pit'
           and field.source_column not in fields[field.source_endpoint]]
assert not missing, {'missing_retained_source_columns': missing}
# The rebuild retains every prior observation. This selection only supplies one
# completed request per collection target; it never selects a winning report value.
groups = defaultdict(list)
for entry in entries:
    groups[(entry['endpoint'], entry['instrument_id'], entry['shard'])].append(entry)
selected = []
for key in sorted(groups):
    latest = max(datetime.fromisoformat(row['collected_at']) for row in groups[key])
    candidates = [row for row in groups[key]
                  if datetime.fromisoformat(row['collected_at']) == latest]
    assert len({row['batch_sha256'] for row in candidates}) == 1, {
        'ambiguous_latest_collection_receipt': key,
    }
    selected.append(replace(_checkpoint_from_evidence(candidates[0]), ordinal=len(selected)))
supplement = json.loads(args.gap_collection.read_text())
assert supplement['source_head'] == head
assert supplement['status'] == 'source_collection_complete'
assert len(supplement['checkpoints']) == supplement['expected_target_count']
selected.extend(FinancialShardCheckpoint(**item) for item in supplement['checkpoints'])
selected.sort(key=lambda item: (FINANCIAL_ENDPOINTS.index(item.endpoint), item.instrument_id, item.shard))
selected = [replace(item, ordinal=index) for index, item in enumerate(selected)]
assert len({(item.endpoint, item.instrument_id, item.shard) for item in selected}) == len(selected)
collection = CompletedFinancialCollection(
    idempotency_key='field-expansion-retained-statements-' + head,
    generation_manifest_sha256=head, contract=contract,
    finished_at=supplement['finished_at'],
    target_count=len(selected), shards=tuple(selected),
)
print('Rebuilding retained statements', len(entries), 'receipts', len(selected), 'targets', flush=True)
# Reuse the ordinary materializer, including full target/raw validation. The
# existing announcement ledger is passed explicitly: these 24 receipts do not
# represent a fresh discovery/reconciliation of every historical security.
coverage = family['dataset_coverage']
discovery = FinancialDiscoveryPublication(
    baseline_session=coverage['discovery_baseline_session'],
    attempted_through_session=coverage['discovery_attempted_through_session'],
    complete_through_session=coverage['discovery_complete_through_session'],
    source_lineage_sha256=coverage['source_lineage_sha256'],
    readiness_status=coverage['readiness_status'],
    pending_instrument_count=coverage['pending_instrument_count'],
    discovery_gap_count=coverage['discovery_gap_count'],
    earliest_unresolved_date=coverage['earliest_unresolved_date'],
)
assert discovery.attempted_through_session == through
rebuilt = store._materialize(
    collection, observation_through_session=through,
    prior_checkpoints=tuple(_checkpoint_from_evidence(item) for item in entries),
    prior_shards=store._manifest_evidence_shards(family), discovery=discovery,
    prior_candidate_manifest_sha256=prior,
)
# The materializer already completed full source/table validation. Reopen through
# an independent store; research-date and old-value verification is a separate job.
reopened = FinancialCandidateStore(args.root).reopen(rebuilt.manifest_sha256)
assert reopened == rebuilt
rebuilt_family = store._read_family(rebuilt.manifest_sha256)
rebuilt_entries = store._read_evidence_index(rebuilt_family['raw_evidence'])
prior_coverage = family['dataset_coverage']
rebuilt_coverage = rebuilt_family['dataset_coverage']
assert {key: value for key, value in prior_coverage.items() if key != 'seed_policy'} == {
    key: value for key, value in rebuilt_coverage.items() if key != 'seed_policy'
}, 'Retained projection must preserve actual source discovery coverage'
assert {row['batch_sha256'] for row in entries} <= {
    row['batch_sha256'] for row in rebuilt_entries
}
assert market.inspect_root(head) == generation
report = {
    'source_generation': head, 'source_statement_candidate': prior,
    'statement_candidate': asdict(rebuilt),
    'retained_evidence_before': len(entries), 'retained_evidence_after': len(rebuilt_entries),
    'collection_target_count': len(selected), 'source_requests': 0,
    'supplement_target_count': len(supplement['checkpoints']),
    'source_coverage': prior_coverage, 'rebuilt_coverage': rebuilt_coverage,
    'scope': 'Retained statement reprojection and evidence preservation; full mixed candidate pending.',
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Rebuilt statement candidate', rebuilt.manifest_sha256, flush=True)

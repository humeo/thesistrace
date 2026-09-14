"""Collect only proven missing retained historical targets, with durable raw receipts."""
import argparse
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS, FinancialShardCheckpoint, RawFinancialBatchStore, _raw_batch_content,
)
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--gap-report', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
gap = json.loads(args.gap_report.read_text())
head = gap['source_head']
market = MountedGenerationStore(args.root)
source = market.inspect_root(head)
store = FinancialCandidateStore(args.root)
family = store._read_family(source.financial_candidate_manifest_sha256)
contract = store._manifest_collection_contract(family)
assert len(contract.shards) == 1 and contract.shards[0].name == 'complete-history'
assert contract.shards[0].start_date is None
identities = {item.instrument_id: item.ts_code
              for item in market.read_historical_ordinary_a_share_identities(head)}
retained = store._read_evidence_index(family['raw_evidence'])
actual_missing = {endpoint: sorted(set(identities) - {
    row['instrument_id'] for row in retained if row['endpoint'] == endpoint
}) for endpoint in FINANCIAL_ENDPOINTS}
assert actual_missing == gap['missing_historical_targets']
targets = [(endpoint, instrument) for endpoint in FINANCIAL_ENDPOINTS
           for instrument in actual_missing[endpoint]]
report = json.loads(args.output.read_text()) if args.output.exists() else {
    'source_head': head, 'expected_target_count': len(targets), 'checkpoints': [],
    'source_row_counts': [], 'status': 'collecting',
}
assert report['source_head'] == head and report['expected_target_count'] == len(targets)
raw_store = RawFinancialBatchStore(args.root)
for ordinal, item in enumerate(report['checkpoints']):
    assert (item['endpoint'], item['instrument_id']) == targets[ordinal]
    assert item['status'] == 'completed' and item['ordinal'] == ordinal
    raw_store.read(item['batch_sha256'])
config = {}
for line in Path('../../.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key.strip() in {'THESISTRACE_TUSHARE_TOKEN', 'THESISTRACE_TUSHARE_ENDPOINT'}:
        config[key.strip()] = value.strip().strip('"').strip("'")
endpoint = config.get('THESISTRACE_TUSHARE_ENDPOINT', 'https://api.tushare.pro')
assert urlparse(endpoint).hostname == 'api.tushare.pro'
transport = HttpTushareTransport(endpoint=endpoint, timeout_seconds=30)
provider = TushareAdapter(token=config['THESISTRACE_TUSHARE_TOKEN'],
                          transport=transport, max_attempts=3)


def save():
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(args.output)


try:
    for ordinal in range(len(report['checkpoints']), len(targets)):
        api, instrument = targets[ordinal]
        fields = dict(contract.endpoint_fields)[api]
        params = {'ts_code': identities[instrument]}
        checkpoint = FinancialShardCheckpoint(ordinal, api, instrument,
            identities[instrument], 'complete-history', 'pending', None, None)
        response = provider.query_raw(api, params=params, fields=fields)
        # Conservative preparation guard; never label a possibly capped response complete.
        known_cap = dict(contract.suspected_truncation_row_counts)[api]
        cap = min(100, known_cap) if known_cap is not None else 100
        content, _, _ = _raw_batch_content(checkpoint=checkpoint, parameters=params,
            expected_fields=fields, response=response, suspected_truncation_row_count=cap)
        observed = datetime.now(UTC).isoformat()
        completed = replace(checkpoint, status='completed',
            batch_sha256=raw_store.store(content), collected_at=observed,
            first_observed_at=observed)
        report['checkpoints'].append(asdict(completed))
        report['source_row_counts'].append(len(response.items))
        report['status'] = 'collecting'
        report.pop('failure', None)
        save()
        print('Missing statement target', ordinal + 1, '/', len(targets),
              api, identities[instrument], len(response.items), 'rows', flush=True)
    report['status'] = 'source_collection_complete'
    report['finished_at'] = datetime.now(UTC).isoformat()
    assert market.inspect_root(head) == source
    save()
except Exception as error:
    report['status'] = 'incomplete'
    report['failure'] = {'error_type': type(error).__name__,
                         'code': getattr(error, 'code', None)}
    save()
    raise
finally:
    transport.close()

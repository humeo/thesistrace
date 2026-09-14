"""Count actual supplier indicator values by report year without inferring company type."""
import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from thesistrace.data.fields import FINANCIAL_INDICATOR_FIELDS
from thesistrace.data.financial_collection import RawFinancialBatchStore
from thesistrace.data.financial_indicator_evidence import FinancialIndicatorObservationStore
from thesistrace.data.financial_indicator_series import normalize_indicator_value
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--collection', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
started = time.monotonic()
source = json.loads(args.collection.read_text())
head = source['source_head']
market = MountedGenerationStore(args.root)
identities = {item.ts_code: item.instrument_id
              for item in market.read_historical_ordinary_a_share_identities(head)}
assert len(identities) == source['expected_instrument_count']
assert len(source['collections']) == source['completed_instrument_count']
complete = (source['status'] == 'source_collection_complete'
            and len(source['collections']) == len(identities))
observations = FinancialIndicatorObservationStore(RawFinancialBatchStore(args.root))
counts = defaultdict(Counter)
totals = Counter()
examples = {}
empty_instruments = []
seen_observations = set()
completed_codes = set()
for index, receipt in enumerate(source['collections'], 1):
    code = receipt['identity']['ts_code']
    assert code not in completed_codes
    assert identities[code] == receipt['identity']['instrument_id']
    assert not receipt['pending_reports']
    completed_codes.add(code)
    row_count = 0
    for digest in receipt['observation_sha256s']:
        if digest in seen_observations:
            continue
        seen_observations.add(digest)
        payload = observations.read(digest)
        columns = {name: position for position, name in enumerate(payload['fields'])}
        assert all(field.source_column in columns for field in FINANCIAL_INDICATOR_FIELDS)
        for row in payload['items']:
            assert row[columns['ts_code']] == code
            period = str(row[columns['end_date']])
            assert len(period) == 8 and period.isdigit()
            year = period[:4]
            row_count += 1
            for field in FINANCIAL_INDICATOR_FIELDS:
                value = row[columns[field.source_column]]
                normalized = normalize_indicator_value(value, source_unit=field.source_unit)
                count = counts[(field.field_id, year)]
                count['source_observation_rows'] += 1
                count['source_null' if normalized is None else 'source_non_null'] += 1
                if normalized is not None:
                    totals[field.field_id] += 1
                    examples.setdefault(field.field_id, {
                        'ts_code': code, 'report_period': period,
                        'source_value': value, 'normalized_value': normalized,
                        'source_unit': field.source_unit, 'unit': field.unit,
                        'observation_sha256': digest,
                    })
    if not row_count:
        empty_instruments.append(code)
    if index % 250 == 0:
        print('Qualified indicator source receipts', index, '/', len(source['collections']), flush=True)

csv_path = args.output.with_suffix('.csv')
names = ['field_id', 'identifier', 'report_year', 'company_type',
         'source_observation_rows', 'source_non_null', 'source_null']
by_id = {field.field_id: field for field in FINANCIAL_INDICATOR_FIELDS}
with csv_path.open('w', newline='') as destination:
    writer = csv.DictWriter(destination, fieldnames=names)
    writer.writeheader()
    for (field_id, year), values in sorted(counts.items()):
        writer.writerow({'field_id': field_id, 'identifier': by_id[field_id].alpha.identifier,
                         'report_year': year, 'company_type': 'not_provided_by_source',
                         **{name: values[name] for name in names[4:]}})
report = {
    'source_head': head,
    'status': 'source_statistics_complete' if complete else 'partial_source_statistics',
    'expected_instrument_count': len(identities),
    'completed_instrument_count': len(completed_codes),
    'uncollected_instruments': sorted(set(identities) - completed_codes),
    'complete_collection_without_rows': empty_instruments,
    'observation_count': len(seen_observations),
    'company_type': 'not_provided_by_source',
    'counting_basis': 'Retained source observation rows grouped by report year; not daily DSL availability.',
    'revision_evidence': 'Historical backfill does not prove original historical revision values.',
    'source_null_reason': 'Supplier returned null; inapplicability cannot be inferred without source evidence.',
    'csv': str(csv_path),
    'fields': [{
        'field_id': field.field_id, 'identifier': field.alpha.identifier,
        'source_column': field.source_column,
        'non_null_observations': totals[field.field_id],
        'example': examples.get(field.field_id),
        'source_status': ('non_null_observed' if totals[field.field_id]
                          else 'no_non_null_observation_requires_review'),
    } for field in FINANCIAL_INDICATOR_FIELDS],
    'elapsed_seconds': time.monotonic() - started,
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(report['status'], 'fields with non-null observations', len(examples), '/', 163, flush=True)

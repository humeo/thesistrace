"""Report daily-basic field coverage from the completed, sealed collection ledger."""
import argparse
import csv
import json
from pathlib import Path

from thesistrace.data.fields import DAILY_BASIC_FIELDS

parser = argparse.ArgumentParser()
parser.add_argument('--collection', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
collection = json.loads(args.collection.read_text())
assert collection['status'] == 'source_collection_complete'
assert collection['expected_session_count'] == collection['completed_session_count']
years = collection['per_year_observed_rows_and_non_null_values']
field_rows = []
totals = {field.field_id: 0 for field in DAILY_BASIC_FIELDS}
for year, counts in sorted(years.items()):
    observed = counts['observed_rows']
    assert observed >= 0
    for field in DAILY_BASIC_FIELDS:
        non_null = counts[field.source_column]
        assert 0 <= non_null <= observed
        totals[field.field_id] += non_null
        field_rows.append({
            'field_id': field.field_id, 'identifier': field.alpha.identifier,
            'year': year, 'company_type': 'not_applicable_market_observation',
            'observed_security_sessions': observed, 'non_null': non_null,
            'source_null': observed - non_null,
            'non_null_ratio_of_returned_rows': non_null / observed if observed else None,
        })
csv_path = args.output.with_suffix('.csv')
with csv_path.open('w', newline='') as destination:
    writer = csv.DictWriter(destination, fieldnames=list(field_rows[0]))
    writer.writeheader()
    writer.writerows(field_rows)
report = {
    'source_head': collection['source_head'], 'status': 'source_statistics_complete',
    'collected_sessions': collection['completed_session_count'],
    'coverage_start': collection['coverage_start'], 'coverage_end': collection['coverage_end'],
    'historical_instrument_count': collection['historical_instrument_count'],
    'empty_source_sessions': collection['empty_source_sessions'],
    'source_request_failures': collection['failure'],
    'company_type': 'not_applicable_market_observation',
    'counting_basis': 'Exact-date returned rows inside the pinned SSE/SZSE historical identity scope.',
    'null_reason': 'Value absent in an observed supplier row; no zero fill or older-value substitution.',
    'scope': 'Source statistics; independent candidate validation proves sealed receipts and DSL projections.',
    'csv': str(csv_path),
    'fields': [{
        'field_id': field.field_id, 'identifier': field.alpha.identifier,
        'source_column': field.source_column, 'source_unit': field.source_unit,
        'unit': field.unit, 'non_null_security_sessions': totals[field.field_id],
        'source_status': ('non_null_observed' if totals[field.field_id]
                          else 'no_non_null_observation_requires_review'),
    } for field in DAILY_BASIC_FIELDS],
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Daily source statistics', len(field_rows), 'field/year rows', flush=True)

"""Inspect retained pilot observations without choosing among source revisions."""
import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parent
inventory = json.loads((root / 'dsl-field-inventory-226.json').read_text())
fields = [field for field in inventory['fields'] if field['source_endpoint'] == 'fina_indicator']
assert len(fields) == len({field['source_column'] for field in fields}) == 163
source_files = ('indicator-pilot-source-observations.json',
                'indicator-catalog-additional-observations.json',
                'indicator-cashflow-sample-observations.json')
records = [dict(record, evidence_file=filename) for filename in source_files
           for record in json.loads((root / filename).read_text())['records']
           if record['endpoint'] == 'fina_indicator' and record['status'] == 'returned']
ledger = []
for field in fields:
    scopes = []
    for record in records:
        assert field['source_column'] in record['fields']
        rows = [dict(zip(record['fields'], row, strict=True)) for row in record['items']]
        periods = {}
        for row in rows:
            periods.setdefault(row['end_date'], []).append(row[field['source_column']])
        by_period = []
        for period, values in sorted(periods.items()):
            present = {value for value in values if value is not None}
            by_period.append({'period': period, 'rows': len(values),
                'nonnull_rows': sum(value is not None for value in values),
                'distinct_nonnull_values': len(present), 'contains_null': None in values})
        scopes.append({'security': record['params']['ts_code'],
            'evidence_file': record['evidence_file'], 'periods': by_period,
            'nonnull_rows': sum(row[field['source_column']] is not None for row in rows),
            'total_rows': len(rows)})
    ledger.append({'dsl_identifier': field['dsl_identifier'], 'source_column': field['source_column'],
        'label': field['label'], 'scope': scopes,
        'evidence_status': 'observed_nonnull' if any(s['nonnull_rows'] for s in scopes)
        else 'all_null_in_retained_sample',
        'qualification': 'coverage_only_units_period_and_applicability_require_separate_evidence'})
output = {'sources': source_files,
    'scope': 'Five securities, 2015–2018 and 2023–2025; distinct values preserved, no revision winner selected',
    'fields': ledger, 'counts': dict(Counter(x['evidence_status'] for x in ledger))}
(root / 'indicator-catalog-coverage.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
print(output['counts'])
print('All-null fields:', ', '.join(x['source_column'] for x in ledger
                                   if x['evidence_status']=='all_null_in_retained_sample'))

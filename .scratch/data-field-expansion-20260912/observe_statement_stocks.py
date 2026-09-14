"""Bounded statement qualification; does not write a Dataset Head."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter

config = {}
for line in Path('../../.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key.strip() in {'THESISTRACE_TUSHARE_TOKEN', 'THESISTRACE_TUSHARE_ENDPOINT'}:
        config[key.strip()] = value.strip().strip('"').strip("'")
token = os.environ.get('THESISTRACE_TUSHARE_TOKEN') or config.get('THESISTRACE_TUSHARE_TOKEN')
if not token:
    raise SystemExit('Token unavailable')
transport = HttpTushareTransport(
    endpoint=config.get('THESISTRACE_TUSHARE_ENDPOINT', 'https://api.tushare.pro'),
    timeout_seconds=20,
)
provider = TushareAdapter(token=token, transport=transport, max_attempts=1)
records = []
inventory = json.loads(Path('.scratch/data-field-expansion-20260912/statement-extension-32.json').read_text())
stocks = [field for field in inventory['fields'] if field['period_kind'] == 'stock']
metadata = ('ts_code', 'ann_date', 'f_ann_date', 'end_date', 'report_type', 'comp_type', 'end_type', 'update_flag')
try:
    for code in ('600519.SH', '000001.SZ', '601318.SH', '600030.SH'):
        for period in ('20251231', '20260331'):
            for endpoint in ('balancesheet', 'cashflow'):
                columns = tuple(field['source_column'] for field in stocks if field['source_endpoint'] == endpoint)
                fields = (*metadata, *columns)
                record = {'endpoint': endpoint, 'ts_code': code, 'period': period}
                try:
                    raw = provider.query_raw(
                        endpoint, params={'ts_code': code, 'period': period, 'report_type': '1'},
                        fields=fields,
                    )
                    record['fields'] = raw.fields
                    record['items'] = raw.items
                    record['status'] = 'observed'
                    record['missing_columns'] = sorted(set(fields) - set(raw.fields))
                except Exception as error:
                    record['status'] = 'failed'
                    record['error_type'] = type(error).__name__
                    record['reason_code'] = getattr(error, 'reason_code', None)
                records.append(record)
finally:
    transport.close()
output = Path('.scratch/data-field-expansion-20260912/statement-stock-source-observations.json')
output.write_text(json.dumps({
    'observed_at': datetime.now(UTC).isoformat(),
    'scope': '4 company categories x 2 report periods x 2 endpoints; 16 bounded read-only requests',
    'evidence_limit': 'Source column and non-null observations only; not proof of complete history or full unit qualification',
    'records': records,
}, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'output': str(output), 'statuses': [record['status'] for record in records]}))

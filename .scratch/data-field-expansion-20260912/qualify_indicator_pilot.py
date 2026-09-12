"""Bounded source qualification; existing adapter, no credential serialization."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from thesistrace.data.financial_indicator_source import FINANCIAL_INDICATOR_SOURCE_FIELDS
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter

config = {}
for line in Path('../../.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key.strip() in {'THESISTRACE_TUSHARE_TOKEN', 'THESISTRACE_TUSHARE_ENDPOINT'}:
        config[key.strip()] = value.strip().strip('"').strip("'")
token = os.environ.get('THESISTRACE_TUSHARE_TOKEN') or config.get('THESISTRACE_TUSHARE_TOKEN')
endpoint = config.get('THESISTRACE_TUSHARE_ENDPOINT', 'https://api.tushare.pro')
if not token or urlsplit(endpoint).hostname != 'api.tushare.pro':
    raise SystemExit('Official endpoint/token configuration unavailable')
transport = HttpTushareTransport(endpoint=endpoint, timeout_seconds=20)
provider = TushareAdapter(token=token, transport=transport, max_attempts=1)
metadata = ('ts_code', 'ann_date', 'f_ann_date', 'end_date', 'report_type', 'comp_type', 'update_flag')
requests = (
    ('fina_indicator', FINANCIAL_INDICATOR_SOURCE_FIELDS),
    ('income', (*metadata, 'basic_eps', 'n_income_attr_p', 'n_income')),
    ('balancesheet', (*metadata, 'total_share', 'total_cur_assets', 'total_cur_liab',
                     'total_hldr_eqy_exc_min_int', 'oth_eqt_tools_p_shr')),
)
output = Path('.scratch/data-field-expansion-20260912/indicator-pilot-source-observations.json')
records = []
try:
    for code in ('600519.SH', '000001.SZ'):
        for api, fields in requests:
            params = {'ts_code': code, 'start_date': '20230101', 'end_date': '20251231'}
            if api != 'fina_indicator':
                params['report_type'] = '1'
            record = {'endpoint': api, 'params': params, 'requested_fields': fields,
                      'observed_at': datetime.now(UTC).isoformat()}
            try:
                response = provider.query_raw(api, params=params, fields=fields)
                record.update(fields=response.fields, items=response.items,
                              status='returned' if response.items else 'empty',
                              row_count=len(response.items))
            except Exception as error:
                record.update(status='failed', error_type=type(error).__name__,
                              reason_code=getattr(error, 'reason_code', None))
            records.append(record)
            output.write_text(json.dumps({'scope': 'six read-only requests; two securities; 2023-2025',
                'documentation': 'https://tushare.pro/document/2?doc_id=79',
                'records': records}, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps({'endpoint': api, 'security': code, 'status': record['status'],
                              'rows': record.get('row_count')}, ensure_ascii=False), flush=True)
finally:
    transport.close()

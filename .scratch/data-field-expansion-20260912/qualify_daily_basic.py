"""Eight bounded, read-only source requests; never serialize credentials."""
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from thesistrace.adapters.tushare_daily_basic import DAILY_BASIC_SOURCE_FIELDS
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
try:
    for code in ('600519.SH', '000001.SZ'):
        for session in ('20180726', '20260909'):
            record = {'ts_code': code, 'trade_date': session, 'responses': {}}
            try:
                for endpoint, fields in (
                    ('daily_basic', DAILY_BASIC_SOURCE_FIELDS),
                    ('daily', ('ts_code', 'trade_date', 'close', 'vol')),
                ):
                    raw = provider.query_raw(endpoint, params={'ts_code': code, 'trade_date': session}, fields=fields)
                    record['responses'][endpoint] = {'fields': raw.fields, 'items': raw.items}
                basic_raw = record['responses']['daily_basic']
                daily_raw = record['responses']['daily']
                if len(basic_raw['items']) != 1 or len(daily_raw['items']) != 1:
                    record['status'] = 'missing_or_ambiguous'
                else:
                    basic = dict(zip(basic_raw['fields'], basic_raw['items'][0], strict=True))
                    daily = dict(zip(daily_raw['fields'], daily_raw['items'][0], strict=True))
                    dec = lambda name: Decimal(str(basic[name]))
                    traded_shares = Decimal(str(daily['vol'])) * 100
                    checks = {
                        'close_matches_daily': dec('close') == Decimal(str(daily['close'])),
                        'total_mv_wan_cny': abs(dec('total_mv') - dec('close') * dec('total_share')) <= Decimal('1'),
                        'circ_mv_wan_cny': abs(dec('circ_mv') - dec('close') * dec('float_share')) <= Decimal('1'),
                        'turnover_rate_percent': abs(dec('turnover_rate') - traded_shares / (dec('float_share') * 10000) * 100) <= Decimal('0.0001'),
                        'turnover_rate_f_percent': abs(dec('turnover_rate_f') - traded_shares / (dec('free_share') * 10000) * 100) <= Decimal('0.0001'),
                    }
                    record['checks'] = checks
                    record['status'] = 'qualified' if all(checks.values()) else 'needs_investigation'
            except Exception as error:
                record['status'] = 'failed'
                record['error_type'] = type(error).__name__
                record['reason_code'] = getattr(error, 'reason_code', None)
            records.append(record)
finally:
    transport.close()
output = Path('.scratch/data-field-expansion-20260912/daily-basic-unit-qualification.json')
output.write_text(json.dumps({'observed_at': datetime.now(UTC).isoformat(), 'scope': '2 securities x 2 sessions; 8 read-only requests', 'documentation': 'https://tushare.pro/document/2?doc_id=32', 'records': records}, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'output': str(output), 'statuses': [r['status'] for r in records], 'checks': [r.get('checks') for r in records]}, indent=2))

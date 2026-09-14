"""Retain one rejected whole-day response for explicit identity investigation."""
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from thesistrace.adapters.tushare_daily_basic import DAILY_BASIC_SOURCE_FIELDS, _SECURITY_CODE_CHANGES
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.data.generation_store import MountedGenerationStore

base = Path('.scratch/data-field-expansion-20260912')
failure = json.loads((base / 'issue07-daily-basic-history.json').read_text())
session = failure['failure']['next_session']
store = MountedGenerationStore('.local/field-expansion-226-candidate/candidate-data')
assert session in store.inspect_root(failure['source_head']).research_sessions
known = {item.ts_code for item in store.read_historical_ordinary_a_share_identities(failure['source_head'])}
config = {}
for line in Path('../../.env').read_text().splitlines():
    key, sep, value = line.partition('=')
    if sep and key.strip() in {'THESISTRACE_TUSHARE_TOKEN', 'THESISTRACE_TUSHARE_ENDPOINT'}:
        config[key.strip()] = value.strip().strip('"').strip("'")
endpoint = config.get('THESISTRACE_TUSHARE_ENDPOINT', 'https://api.tushare.pro')
assert urlparse(endpoint).hostname == 'api.tushare.pro'
transport = HttpTushareTransport(endpoint=endpoint, timeout_seconds=30)
provider = TushareAdapter(token=config['THESISTRACE_TUSHARE_TOKEN'], transport=transport, max_attempts=1)
try:
    raw = provider.query_raw('daily_basic', params={'trade_date': session.replace('-', '')},
                             fields=DAILY_BASIC_SOURCE_FIELDS)
    rows = [dict(zip(raw.fields, item, strict=True)) for item in raw.items]
    counts = Counter(row['ts_code'] for row in rows)
    report = {
        'source_head': failure['source_head'], 'session': session,
        'observed_at': datetime.now(UTC).isoformat(), 'row_count': len(rows),
        'unknown_codes': sorted(set(counts) - known),
        'duplicate_codes': {code: count for code, count in counts.items() if count > 1},
        'dates': sorted({row['trade_date'] for row in rows}),
        'raw': {'fields': raw.fields, 'items': raw.items},
    }
    (base / f'issue07-daily-basic-scope-{session}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    )
    (base / f'issue07-daily-basic-history-{session}-failure.json').write_text(
        json.dumps(failure, ensure_ascii=False, indent=2) + '\n'
    )
    print({key: value for key, value in report.items() if key != 'raw'})
    changed = {code for old, current, _ in _SECURITY_CODE_CHANGES for code in (old, current)}
    print([row for row in rows if row['ts_code'] in changed | set(report['unknown_codes'])])
finally:
    transport.close()

"""Collect pinned historical sessions with the existing bounded, resumable source."""
import argparse
import json
import os
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from thesistrace.adapters.tushare_daily_basic import (
    DAILY_BASIC_MULTIPLIERS,
    TushareDailyBasicSource,
    normalize_daily_basic,
)
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.data.daily_basic_evidence import (
    MARKET_SOURCE_RECEIPT_DIRECTORY,
    DailyBasicCheckpoint,
)
from thesistrace.data.generation_store import MountedGenerationStore

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--source-scope', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
verified = json.loads(args.source_scope.read_text())
head = verified['source_head']['generation_manifest_sha256']
store = MountedGenerationStore(args.root)
generation = store.inspect_root(head)
identities = store.read_historical_ordinary_a_share_identities(head)
instrument_ids = {item.ts_code: item.instrument_id for item in identities}
assert len(instrument_ids) == verified['instrument_count']
sessions = generation.research_sessions
config = {}
for line in Path('../../.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key.strip() in {'THESISTRACE_TUSHARE_TOKEN', 'THESISTRACE_TUSHARE_ENDPOINT'}:
        config[key.strip()] = value.strip().strip('"').strip("'")
token = os.environ.get('THESISTRACE_TUSHARE_TOKEN') or config.get('THESISTRACE_TUSHARE_TOKEN')
endpoint = config.get('THESISTRACE_TUSHARE_ENDPOINT', 'https://api.tushare.pro')
assert token and urlparse(endpoint).hostname == 'api.tushare.pro'
transport = HttpTushareTransport(endpoint=endpoint, timeout_seconds=30)
provider = TushareAdapter(token=token, transport=transport, max_attempts=3)
source = TushareDailyBasicSource(provider)
evidence = []
counts = defaultdict(Counter)
empty_sessions = []
started = time.monotonic()
completed = 0


def save(status, failure=None):
    report = {
        'source_head': head, 'source': 'daily_basic', 'status': status,
        'coverage_start': sessions[0], 'coverage_end': sessions[-1],
        'historical_instrument_count': len(instrument_ids),
        'expected_session_count': len(sessions), 'completed_session_count': completed,
        'sealed_source_evidence': evidence,
        'per_year_observed_rows_and_non_null_values': dict(counts),
        'empty_source_sessions': empty_sessions, 'failure': failure,
        'observed_at': datetime.now(UTC).isoformat(),
        'elapsed_seconds': time.monotonic() - started,
        'scope': 'Retained source collection only; candidate field admission requires independent validation.',
    }
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(args.output)


try:
    for start in range(0, len(sessions), 64):
        block = sessions[start:start + 64]
        collection_key = f'field-expansion-daily-basic-{head}-{block[0]}-{block[-1]}'
        checkpoint = DailyBasicCheckpoint(
            args.root / MARKET_SOURCE_RECEIPT_DIRECTORY,
            collection_key=collection_key,
        )
        for session in block:
            raw = source.collect_session(
                session=session, instrument_codes=tuple(instrument_ids), checkpoint=checkpoint,
            )
            rows = normalize_daily_basic(raw, instrument_ids=instrument_ids)
            if not rows:
                empty_sessions.append(session)
            year = session[:4]
            counts[year]['observed_rows'] += len(rows)
            for name in DAILY_BASIC_MULTIPLIERS:
                counts[year][name] += sum(row[name] is not None for row in rows)
            completed += 1
            if completed % 10 == 0:
                print('daily_basic completed', completed, '/', len(sessions), session, flush=True)
        reference = checkpoint.seal(block)
        assert checkpoint.verify_evidence(reference) == tuple(block)
        evidence.append({'collection_key': collection_key, **reference})
        save('collecting')
    save('source_collection_complete')
except Exception as error:
    save('incomplete', {
        'error_type': type(error).__name__,
        'reason_code': getattr(error, 'reason_code', None),
        'detail_code': getattr(error, 'detail_code', None),
        'next_session': sessions[completed] if completed < len(sessions) else None,
    })
    raise
finally:
    transport.close()

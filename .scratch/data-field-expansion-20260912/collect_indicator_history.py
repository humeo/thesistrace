"""Run the existing indicator collector against an isolated preparation database."""
import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter
from thesistrace.data.financial_collection import FINANCIAL_HISTORY_FLOOR
from thesistrace.data.financial_indicator_collection import FinancialIndicatorCollector
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
assert len(identities) == verified['instrument_count']
config = {}
for line in Path('../../.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key.strip() in {'THESISTRACE_TUSHARE_TOKEN', 'THESISTRACE_TUSHARE_ENDPOINT'}:
        config[key.strip()] = value.strip().strip('"').strip("'")
# The isolated dependency runner supplies deterministic environment values. Read
# this expressly authorized real-source credential only from the existing file.
token = config.get('THESISTRACE_TUSHARE_TOKEN')
endpoint = config.get('THESISTRACE_TUSHARE_ENDPOINT', 'https://api.tushare.pro')
assert token and urlparse(endpoint).hostname == 'api.tushare.pro'
database_url = os.environ['THESISTRACE_DATABASE_URL']
assert urlparse(database_url).hostname in {'127.0.0.1', 'localhost'}
database = PostgresDatabase(database_url)
database.open()
transport = HttpTushareTransport(endpoint=endpoint, timeout_seconds=30)
provider = TushareAdapter(token=token, transport=transport, max_attempts=3)
collector = FinancialIndicatorCollector(database, args.root, provider)
completed = []
started = time.monotonic()


def save(status, failure=None):
    report = {
        'source_head': head, 'source': 'fina_indicator', 'status': status,
        'report_collection_start': FINANCIAL_HISTORY_FLOOR,
        'report_collection_end': generation.data_through_session,
        'research_start': generation.research_sessions[0],
        'expected_instrument_count': len(identities),
        'completed_instrument_count': len(completed), 'collections': completed,
        'failure': failure, 'observed_at': datetime.now(UTC).isoformat(),
        'elapsed_seconds': time.monotonic() - started,
        'scope': 'Bounded report-range receipts; historical backfill has limited revision evidence.',
    }
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(args.output)


try:
    for identity in identities:
        result = collector.collect(
            collection_key=f'field-expansion-indicator-{head}-{identity.instrument_id}',
            identity=identity, start_date=FINANCIAL_HISTORY_FLOOR,
            end_date=generation.data_through_session.replace('-', ''),
            checked_through=generation.data_through_session, required_reports=(),
        )
        assert not result.pending_reports
        completed.append({'identity': asdict(identity), **asdict(result)})
        save('collecting')
        if len(completed) % 10 == 0:
            print('fina_indicator completed', len(completed), '/', len(identities),
                  identity.ts_code, flush=True)
    save('source_collection_complete')
except Exception as error:
    save('incomplete', {
        'error_type': type(error).__name__,
        'reason_code': getattr(error, 'reason_code', None),
        'detail_code': getattr(error, 'detail_code', None),
        'next_identity': asdict(identities[len(completed)])
        if len(completed) < len(identities) else None,
    })
    raise
finally:
    transport.close()
    database.close()

"""Build the daily family from sealed source receipts without provider access."""
import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.adapters.tushare_daily_basic import TushareDailyBasicSource, normalize_daily_basic
from thesistrace.data.daily_basic_evidence import MARKET_SOURCE_RECEIPT_DIRECTORY, DailyBasicCheckpoint
from thesistrace.data.generation_store import GENERATION_SESSION_PARTITION_COUNT, MountedGenerationStore
from thesistrace.data.source import CanonicalSessionPartition

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--collection', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
report = json.loads(args.collection.read_text())
assert report['status'] == 'source_collection_complete'
assert report['completed_session_count'] == report['expected_session_count']
store = MountedGenerationStore(args.root)
head = report['source_head']
original = store.inspect_root(head)
sessions = original.research_sessions
assert len(sessions) == report['completed_session_count']
identities = {item.ts_code: item.instrument_id
              for item in store.read_historical_ordinary_a_share_identities(head)}
evidence = report['sealed_source_evidence']
assert len(evidence) == (len(sessions) + GENERATION_SESSION_PARTITION_COUNT - 1) // (
    GENERATION_SESSION_PARTITION_COUNT
)


class OfflineProvider:
    def query_raw(self, *args, **kwargs):
        raise RuntimeError('Offline candidate assembly found a missing retained source receipt')


def partitions():
    for ordinal, start in enumerate(range(0, len(sessions), GENERATION_SESSION_PARTITION_COUNT)):
        block = sessions[start:start + GENERATION_SESSION_PARTITION_COUNT]
        item = evidence[ordinal]
        checkpoint = DailyBasicCheckpoint(
            args.root / MARKET_SOURCE_RECEIPT_DIRECTORY, collection_key=item['collection_key'],
        )
        reference = {key: item[key] for key in ('path', 'sha256')}
        assert checkpoint.verify_evidence(reference) == block
        source = TushareDailyBasicSource(OfflineProvider())
        rows = []
        for day in block:
            raw = source.collect_session(
                session=day, instrument_codes=tuple(identities), checkpoint=checkpoint,
            )
            rows.extend(normalize_daily_basic(raw, instrument_ids=identities))
        assert checkpoint.seal(block) == reference
        yield CanonicalSessionPartition(sessions=block, canonical={
            'daily_basic': rows, 'daily_basic_sessions': [{'session': day} for day in block],
        })
        print('Materialized daily history block', ordinal + 1, '/', len(evidence), flush=True)


candidate = store.materialize_daily_basic_history(
    head, partitions(), source_evidence=evidence, prepared_at=datetime.now(UTC),
)
before = {family.family_id: family for family in original.families}
after = {family.family_id: family for family in candidate.families}
assert all(after[name] == family for name, family in before.items()
           if name not in {'equity.daily_basic', 'data.field_catalog'})
assert store.inspect_root(head) == original
args.output.write_text(json.dumps({
    'source_generation': head, 'candidate': asdict(candidate),
    'source_requests': 0, 'collected_session_count': len(sessions),
    'scope': 'Daily family assembly and market validation; combined financial candidate pending.',
}, ensure_ascii=False, indent=2) + '\n')
print('Daily history candidate', candidate.manifest_sha256, flush=True)

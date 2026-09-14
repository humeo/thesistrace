"""Pin checksum-verified calendar/identities independently of financial validation."""
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import MountedDatasetHeadStore
from thesistrace.publication.serialization import canonical_json_bytes

root = Path('.local/field-expansion-226-candidate/candidate-data')
expected = json.loads(Path(
    '.scratch/data-field-expansion-20260912/issue07-source-after-copy.json'
).read_text())['generation_manifest_sha256']
head = MountedDatasetHeadStore(root).current_pointer()
assert head is not None and head.generation_manifest_sha256 == expected
store = MountedGenerationStore(root)
generation = store.inspect_root(expected)
identities = store.read_historical_ordinary_a_share_lifecycles(expected)
# Public identity reader verifies each addressed manifest/object it opens.
calendar_spec, calendar_reference = store._family_table_reference(
    store._read_family_generation_root(expected), 'market.research_calendar', 'research_calendar',
)
calendar = [row['session'] for row in store._open_table(calendar_spec, calendar_reference, None)]
assert tuple(calendar) == generation.research_sessions
assert len(identities) == len({item.instrument_id for item in identities})
report = {
    'source_head': asdict(head), 'instrument_count': len(identities),
    'session_count': len(calendar), 'research_start': calendar[0], 'research_end': calendar[-1],
    'identity_sha256': hashlib.sha256(canonical_json_bytes([asdict(i) for i in identities])).hexdigest(),
    'calendar_sha256': hashlib.sha256(canonical_json_bytes(calendar)).hexdigest(),
    'verified_at': datetime.now(UTC).isoformat(),
    'scope': 'Collection calendar and historical identities only; full source graph validation is separate.',
}
output = Path('.scratch/data-field-expansion-20260912/issue07-collection-scope.json')
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))

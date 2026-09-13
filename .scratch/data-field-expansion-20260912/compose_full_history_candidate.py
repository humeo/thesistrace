"""Compose independently prepared families; never publish or mutate Dataset Head."""
import argparse
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.data.fields import alpha_field_catalog
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.head_store import MountedDatasetHeadStore
from thesistrace.data.overview import describe_family_fields

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--daily', type=Path, required=True)
parser.add_argument('--statements', type=Path, required=True)
parser.add_argument('--indicators', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
daily, statements, indicators = (
    json.loads(path.read_text()) for path in (args.daily, args.statements, args.indicators)
)
source_head = daily['source_generation']
assert statements['source_generation'] == indicators['source_generation'] == source_head
store = MountedGenerationStore(args.root)
heads = MountedDatasetHeadStore(args.root)
original_head = heads.current_pointer()
assert original_head.generation_manifest_sha256 == source_head
source = store.inspect_root(source_head)
daily_root = daily['candidate']['manifest_sha256']
print('Composing retained statement projection', flush=True)
statement_root = store.compose_financial_candidate(
    daily_root, statements['statement_candidate']['manifest_sha256'],
    prepared_at=datetime.now(UTC),
)
intermediate = args.output.with_name(args.output.stem + '-statement-root.json')
intermediate.write_text(json.dumps(asdict(statement_root), indent=2) + '\n')
print('Composing indicator projection', flush=True)
complete = store.compose_with_indicator_candidate(
    statement_root.manifest_sha256, indicators['indicator_candidate'],
    prepared_at=datetime.now(UTC),
)
assert heads.current_pointer() == original_head
expected = {field.field_id for field in alpha_field_catalog()}
assert len(expected) == 226
assert expected <= set(complete.field_availability)
available_families = describe_family_fields(complete)
assert {field_id for family in available_families for field_id in family.available_field_ids} == expected
assert all(family.readiness == 'ready' for family in available_families)
before = {family.family_id: family for family in source.families}
after = {family.family_id: family for family in complete.families}
changed = {'equity.daily_basic', 'equity.financial_pit', 'equity.financial_indicator',
           'data.field_catalog'}
assert all(after[name] == family for name, family in before.items() if name not in changed)
assert source.research_sessions == complete.research_sessions
report = {
    'source_generation': source_head, 'candidate': asdict(complete),
    'intermediate_statement_generation': statement_root.manifest_sha256,
    'author_field_count': len(expected),
    'author_fields_by_family': dict(Counter(field.family_id for field in alpha_field_catalog())),
    'actual_family_availability': [family.model_dump(mode='json') for family in available_families],
    'ttm_count': sum(field.report_period_selection == 'latest_visible_ttm'
                     for field in alpha_field_catalog()),
    'unchanged_families': sorted(set(before) - changed),
    'head_unchanged': True,
    'scope': 'Family composition with unchanged references; coverage qualification and release remain separate.',
}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('Complete candidate assembled', complete.manifest_sha256, flush=True)

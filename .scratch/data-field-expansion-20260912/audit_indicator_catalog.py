"""Audit current public definitions against the independent qualification ledger."""
import json
from pathlib import Path

from thesistrace.alpha_language import alpha_language
from thesistrace.data.fields import FINANCIAL_INDICATOR_FIELDS
from thesistrace.data.financial_indicator_source import FINANCIAL_INDICATOR_SOURCE_FIELDS

root = Path(__file__).resolve().parent
ledger = json.loads((root/'indicator-field-qualification-ledger.json').read_text())['fields']
by_author = {row['dsl_identifier']: row for row in ledger}
assert len(by_author) == len(ledger) == 163
pilot = {
    'eps': ('CNY/share', 'CNY/share', 'latest_visible_report_cumulative'),
    'bps': ('CNY/share', 'CNY/share', 'latest_visible_report_end'),
    'current_ratio': ('multiple', 'multiple', 'latest_visible_report_end'),
    'roe': ('percent', 'ratio', 'latest_visible_supplier_report'),
    'q_roe': ('percent', 'ratio', 'latest_visible_single_quarter'),
    'netprofit_yoy': ('percent', 'ratio', 'latest_visible_report_yoy'),
}
checks = []
for field in FINANCIAL_INDICATOR_FIELDS:
    name = field.alpha.identifier
    row = by_author[name]
    decision = row['semantic_decision']
    expected = pilot[name] if name in pilot else (
        decision['source_unit'], decision['canonical_unit'], decision['period'])
    actual = (field.source_unit, field.unit, field.report_period_selection)
    problems = []
    if actual != expected:
        problems.append({'semantic_contract': {'expected': expected, 'actual': actual}})
    if field.source_column != row['source_column']:
        problems.append({'source_column': field.source_column})
    if field.source_column not in FINANCIAL_INDICATOR_SOURCE_FIELDS:
        problems.append({'not_in_retained_source_schema': field.source_column})
    if name not in pilot and not (root/decision['evidence_file']).is_file():
        problems.append({'missing_evidence': decision['evidence_file']})
    compiled = alpha_language.compile(f'rank({name})')
    if compiled.field_ids_by_identifier != {name: field.field_id}:
        problems.append({'authoring_identity': compiled.field_ids_by_identifier})
    checks.append({'identifier': name, 'field_id': field.field_id,
                   'source_column': field.source_column, 'problems': problems})
assert len({x['field_id'] for x in checks}) == len(checks)
implemented = {x['identifier'] for x in checks}
report = {
    'scope': 'Current implemented indicator mapping, retained schema and recorded semantics only; not independent proof every qualification is sufficient.',
    'implemented': len(checks), 'target': 163,
    'remaining': sorted(set(by_author)-implemented),
    'checks': checks,
}
(root/'indicator-catalog-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print({'implemented': len(checks), 'remaining': report['remaining'],
       'mismatches': [x for x in checks if x['problems']]})
assert not any(x['problems'] for x in checks)

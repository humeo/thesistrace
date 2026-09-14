"""Read-only manifest and bounded raw-batch evidence for field expansion."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.head_store import MountedDatasetHeadStore

root = Path('/var/lib/thesistrace/canonical-data')
heads = MountedDatasetHeadStore(root)
pointer = heads.current_pointer()
generation = heads.resolve_descriptor(pointer)
financial = FinancialCandidateStore(root)
financial_sha = generation.financial_candidate_manifest_sha256
fields = financial.source_fields_by_endpoint(financial_sha)
family = financial._read_family(financial_sha)
evidence = financial._read_evidence_index(family['raw_evidence'])
samples = []
for endpoint in ('income', 'balancesheet', 'cashflow'):
    for ts_code in ('000001.SZ', '600519.SH'):
        matches = [e for e in evidence if e['endpoint'] == endpoint and e['ts_code'] == ts_code]
        if not matches:
            samples.append({'endpoint': endpoint, 'ts_code': ts_code, 'status': 'no_evidence'})
            continue
        entry = min(matches, key=lambda e: (e.get('first_observed_at') or e['collected_at']))
        batch = financial._read_raw_batch(entry['batch_sha256'])
        rows = [dict(zip(batch['returned_fields'], values)) for values in batch['items']]
        before = [r for r in rows if (r.get('f_ann_date') or r.get('ann_date') or '') < '20100104' and (r.get('f_ann_date') or r.get('ann_date'))]
        samples.append({
            'endpoint': endpoint, 'ts_code': ts_code,
            'batch_sha256': entry['batch_sha256'],
            'first_observed_at': entry.get('first_observed_at'),
            'row_count': len(rows),
            'pre_2010_published_row_count': len(before),
            'pre_2010_report_type_counts': dict(Counter(str(r['report_type']) for r in before)),
            'pre_2010_report_type_1_periods': sorted({str(r['end_date']) for r in before if str(r['report_type']) == '1'}),
            'report_period_extent': [min(str(r['end_date']) for r in rows), max(str(r['end_date']) for r in rows)] if rows else None,
        })
print(json.dumps({
    'inspected_at': datetime.now(timezone.utc).isoformat(),
    'generation_manifest_sha256': generation.manifest_sha256,
    'financial_manifest_sha256': financial_sha,
    'data_through_session': generation.data_through_session,
    'field_availability': list(generation.field_availability),
    'families': [{'family_id': f.family_id, 'manifest_sha256': f.manifest_sha256, 'dataset_coverage': f.dataset_coverage} for f in generation.families],
    'financial_source_fields': {k: {'count': len(v), 'fields': sorted(v)} for k, v in fields.items()},
    'raw_evidence_entry_count': len(evidence),
    'raw_samples': samples,
    'head_unchanged': heads.current_pointer() == pointer,
}, ensure_ascii=False, indent=2))

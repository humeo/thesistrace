"""Verify the completed executable QS28 cohort and write a new immutable checkpoint."""
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

D = Path(__file__).parent
read = lambda p: json.loads(p.read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
parse_time = lambda t: datetime.fromisoformat(t.replace('Z', '+00:00'))
target = D / 'round28-segment3-checkpoint-verification.json'
assert not target.exists(), 'Preserve prior checkpoint evidence'
plan = read(D / 'round28-plan.json')
state = read(D / 'round28-execution-state.json')
baseline = read(D / 'round28-segment2-checkpoint-verification.json')
context = read(D / 'round28-segment3-final-context.json')['data_overview']
assert context['data_through_session'] == plan['end_date']
assert context['market_research_readiness'] and context['industry_research_readiness'] and context['benchmark_research_readiness']
assert context['financial_research_readiness'] == 'ready'
assert context['financial_coverage']['pending_instrument_count'] == context['financial_coverage']['discovery_gap_count'] == 0
assert context['benchmark_snapshot_sha256'] == plan['benchmark_snapshot_sha256']
assert state['status'] in {'finite_audit_account_phase_complete', 'finite_audit_executable_phase_complete_with_unresolved'}
assert not any(state[k] for k in ('pending_ids', 'unobserved_ids', 'succeeded_uncollected', 'unsubmitted_year_cases', 'submitted_unfinished_year_cases'))
assert not any(f['status'] == 'required' for f in state['followups'])
assert sha(D / 'round28-plan.json') == state['plan_sha256'] == baseline['plan_sha256']
for source in plan['source_manifest']:
    assert sha(D / source['file']) == source['sha256']
review = read(D / 'round28-segment3-review.json')
assert not review['errors'] and all(f['correction_verified'] for f in review['findings'])
corrected = {f['file']: f['corrected_file_sha256'] for f in review['findings']}
for name, expected in review['file_sha256'].items():
    assert sha(D / name) == corrected.get(name, expected), name
new_submissions = [read(p) for p in (D / 'submissions').glob('r28-*.json')
    if parse_time(read(p)['submitted_at']) > parse_time(baseline['checked_at'])]
new_ids = []
for sub in new_submissions:
    response = sub['response']
    if response['outcome'] != 'accepted':
        continue
    if 'batch_id' in response:
        batch = read(D / 'batches' / (response['batch_id'] + '.json'))
        assert batch['status'] in {'succeeded', 'failed', 'cancelled'}
        new_ids.extend(i['research_run_id'] for i in batch['items'])
    else:
        new_ids.append(response['run_id'])
assert len(new_ids) == len(set(new_ids))
completed, failed = [], []
for rid in new_ids:
    run = read(D / 'runs' / (rid + '.json'))
    assert run['status'] in {'succeeded', 'failed', 'cancelled'}
    if run['status'] == 'succeeded':
        result = read(D / 'results' / (rid + '.json'))
        assert result['run'] == run and result['provenance']['authoring_input'] == run['input']
        assert result['provenance']['data'] == plan['data']
        assert run['progress']['completed_research_sessions'] == run['progress']['total_research_sessions'] == 242
        assert run['input']['holdings_count'] in (10, 20) and run['input']['rebalance_every_sessions'] == 20
        assert re.search(rf"H{run['input']['holdings_count']} R20$", run['name'])
        completed.append(result)
    else:
        assert not run['result_available'] and not (D / 'results' / (rid + '.json')).exists()
        failed.append(rid)
assert len(completed) == state['collected_year_cases'] - baseline['fixed_cases_completed']
assert state['collected_year_cases'] + len(state['execution_unresolved_year_cases']) == state['fixed_year_cases']
strategies = list(csv.DictReader((D / 'strategies.csv').open()))
navs = list(csv.DictReader((D / 'nav-audit.csv').open()))
links_checked = 0
for name in ['REPORT.md', 'ROUND28_RESULTS.md', 'ROUND28_SCALE_PROOF.md', 'ROUND28_SEGMENT3_DIAGNOSTICS.md',
        'ROUND28_SEGMENT3_REVIEW.md', 'ROUND28_INVENTORY_REVIEW.md', 'NEXT_CAPITAL_AUDIT_PREFLIGHT.md',
        'CAPITAL_REPLAY.md', 'product-audit/REPORT.md', 'product-audit/issues/09-batch-capacity-diagnostics.md',
        'product-audit/issues/12-factor-to-strategy-lineage.md']:
    page = D / name
    for link in re.findall(r'\]\(([^)]+)\)', page.read_text()):
        if link.startswith(('http:', 'https:', '#')):
            continue
        path = Path(link) if link.startswith('/') else page.parent / link.split('#')[0]
        assert path.exists(), (name, link)
        links_checked += 1
metrics = [r['summary']['metrics'] for r in completed]
checkpoint = {'checked_at': datetime.now(timezone.utc).isoformat(), 'turn_classification': 'progress',
    'goal_status': 'active', 'scope': 'The executable phase of the fixed109-definition audit is complete; execution-unresolved cases remain separate. This does not complete the broader open-ended research goal.',
    'baseline_checkpoint': 'round28-segment2-checkpoint-verification.json', 'plan_sha256': state['plan_sha256'],
    'latest_data_through_session': context['data_through_session'],
    'latest_financial_pending_instruments': context['financial_coverage']['pending_instrument_count'],
    'source_manifest_files_verified': len(plan['source_manifest']),
    'new_batches': sum('batch_id' in s['response'] for s in new_submissions),
    'new_single_runs': sum('run_id' in s['response'] for s in new_submissions),
    'new_admission_rejections': sum(s['response']['outcome'] == 'rejected' for s in new_submissions),
    'new_accepted_account_attempts': len(new_ids), 'new_strategy_results': len(completed),
    'new_failed_run_attempts': failed,
    'new_not_dispatched_after_failure_cases': len(state['execution_unresolved_year_cases']) - baseline['unresolved_year_cases'] - len(failed),
    'fixed_cases_completed': state['collected_year_cases'], 'fixed_cases_total': state['fixed_year_cases'],
    'new_round28_results_total': state['new_year_results'], 'reused_results': state['reused_year_results'],
    'unsubmitted_year_cases': 0, 'submitted_unfinished_year_cases': 0,
    'unresolved_year_cases': len(state['execution_unresolved_year_cases']),
    'native_year_passes': len(state['native_year_passes']),
    'new_sharpe_range': [min(m['sharpe'] for m in metrics), max(m['sharpe'] for m in metrics)],
    'new_drawdown_range': [min(m['maximum_drawdown']['value'] for m in metrics), max(m['maximum_drawdown']['value'] for m in metrics)],
    'all_collected_strategies': len(strategies), 'all_result_records': len(list((D / 'results').glob('*.json'))),
    'all_full_nav_audits': len(navs), 'new_full_nav_audits': len(navs) - baseline['all_full_nav_audits'],
    'new_100k_replays': 0, 'new_screenshots': 0, 'screenshots_total': len(list((D / 'product-audit/screenshots').glob('*'))),
    'product_issues_total': len(list((D / 'product-audit/issues').glob('*.md'))), 'current_segment_metadata_edits': 0,
    'reviewed_evidence_file_hashes': len(review['file_sha256']), 'review_findings_resolved': len(review['findings']),
    'local_links_checked': links_checked, 'raw_market_transfer_executed': False, 'pending_ids': [],
    'next_action': 'Preserve QS28 fixed results and unresolved execution cases. Review NEXT_CAPITAL_AUDIT_PREFLIGHT for a separately frozen, same-local-date paired-capital audit; no new replay has yet been executed. Latest raw export and brokerage access remain unanswered, with no permission assumption.',
    'evidence': {name: sha(D / name) for name in ['round28-plan.json', 'round28-execution-state.json',
        'round28-segment3-review.json', 'round28-inventory-review.json', 'round28-nav-audits.json',
        'round28-admission-resolutions.json', 'next-capital-audit-preflight.json', 'round28-segment3-final-context.json']}}
target.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(checkpoint, ensure_ascii=False))

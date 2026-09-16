"""Validate explicitly reviewed QS28 admission decisions without changing the frozen plan."""
import hashlib
import json
from pathlib import Path

D = Path(__file__).parent
plan_path = D / 'round28-plan.json'
plan = json.loads(plan_path.read_text())
plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
path = D / 'round28-admission-resolutions.json'
resolutions = json.loads(path.read_text()) if path.exists() else {}
definitions = {e['key']: e for e in plan['definitions']}
for key, decision in resolutions.items():
    source = D / 'submissions' / (key + '.json')
    sub = json.loads(source.read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == decision['rejected_submission_sha256']
    assert decision['source_plan_sha256'] == sub['source_plan_sha256'] == plan_sha
    assert sub['key'] == key and sub['definition_key'] == decision['definition_key']
    response = sub['response']
    assert response['outcome'] == 'rejected' and not response.get('run_id') and not response.get('batch_id')
    assert [i['code'] for i in response['issues']] == [decision['rejection_code']]
    assert decision['decision'] in {'one_exact_single_per_holdings', 'terminal_admission_unresolved'}
    entry = definitions[decision['definition_key']]
    cfg = sub['input']
    assert cfg['start_date'] == plan['start_date'] and cfg['end_date'] == plan['end_date']
    assert cfg['universe'] == 'top3000' and cfg['neutralization'] == entry['neutralization']
    if decision['decision'] == 'one_exact_single_per_holdings':
        assert decision['rejection_code'] == 'RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY'
        assert cfg['alpha']['formula'] == entry['formula']
        assert cfg['alpha']['hypothesis'] == entry['hypothesis']
        assert sorted((s['holdings_count'], s['rebalance_every_sessions']) for s in cfg['strategies']) == sorted(
            (c['holdings_count'], c['rebalance_every_sessions']) for c in plan['cases']
            if c['definition_key'] == entry['key'] and c['status_at_freeze'] == 'planned')
    else:
        assert cfg['formula'] == entry['formula']
        assert decision['prior_batch_resolution'] in resolutions
        assert resolutions[decision['prior_batch_resolution']]['definition_key'] == entry['key']
print(json.dumps(resolutions))

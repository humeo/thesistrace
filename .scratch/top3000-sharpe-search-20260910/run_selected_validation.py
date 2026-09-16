"""Run only the eight saved recent/account checks on two selected configurations."""
import json
import subprocess
import sys
from pathlib import Path
BASE=Path(__file__).resolve().parent
plan=json.loads((BASE/'selected-recent-plan.json').read_text())
for case in plan['cases']:
    print(json.dumps({'validation_input':case}),flush=True)
    subprocess.run([sys.executable,str(BASE/'capital_replay.py'),'--source','local',
        '--market-gate','breadth20','--extra-cost-bps','10','--board',case['board'],
        '--start',case['start'],'--holdings',str(case['holdings']),
        '--rebalance',str(case['rebalance']),'lowamount_none_h10r10'],check=True)

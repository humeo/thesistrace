"""Execute the saved, bounded cash-gate sensitivity plan serially."""
import json
import subprocess
import sys
from pathlib import Path

BASE=Path(__file__).resolve().parent
plan=json.loads((BASE/'market-gate-sensitivity-plan.json').read_text())
cases=[{'holdings':x['holdings'],'rebalance':x['rebalance'],'start':'2025-09-10','board':'all'} for x in plan['same_window_neighbors']]
cases += [{'holdings':10,'rebalance':10,'start':start,'board':'all'} for start in plan['independent_restart_starts']]
cases += [{'holdings':10,'rebalance':10,'start':'2025-09-10','board':'main'}]
for i,case in enumerate(cases):
    cmd=[sys.executable,str(BASE/'capital_replay.py'),'--source','local',
         '--market-gate','breadth20','--extra-cost-bps','10','--board',case['board'],
         '--start',case['start'],'--holdings',str(case['holdings']),
         '--rebalance',str(case['rebalance']),'lowamount_none_h10r10']
    print(json.dumps({'case':i+1,'total':len(cases),'input':case}),flush=True)
    subprocess.run(cmd,check=True)

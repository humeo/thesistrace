"""Replay the authored MCP formula at 100k and compare two frozen cash-gate cases."""
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from thesistrace.alpha_language import alpha_language
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.research_kernel.alpha import evaluate_columnar_alpha_matrix
from thesistrace.research_kernel import strategy

BASE=Path(__file__).resolve().parent
root=BASE/'offline-market'; out=BASE/'loo-capital';out.mkdir(exist_ok=True)
plan=json.loads((BASE/'loo-breadth-plan.json').read_text())
sha='4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f'
calendar=json.loads((root/'manifests/sha256'/sha[:2]/(sha+'.json')).read_text())['research_sessions']
compiled=alpha_language.compile(plan['formula']);start='2025-09-10';end='2026-08-27'
sessions=calendar[calendar.index(start)-compiled.effective_lookback:calendar.index(end)+1]
data=MountedGenerationStore(root).read_columnar_slice(sha,sessions=sessions,
    universe_name='top3000',neutralization='none',
    field_bindings={field:identifier for identifier,field in compiled.field_ids_by_identifier.items()},
    fact_instrument_ids=frozenset())
alpha=evaluate_columnar_alpha_matrix(data,compiled_alpha=compiled,neutralization='none',cancellation_check=lambda:None)
base_cost=strategy.transaction_cost
def stressed_cost(raw_notional,side,costs):
    return strategy.money(base_cost(raw_notional,side,costs)+raw_notional*Decimal('0.001'))
checks=[]
for h,r in [(10,5),(20,10)]:
    previous=BASE/'capital-replay'/f'lowamount_none_h10r10_100000_extra10bp_breadth20_h{h}r{r}_start{start}.json'
    reference=json.loads(previous.read_text());ledger=[]
    with patch.object(strategy,'INITIAL_CASH',Decimal(100000)),patch.object(strategy,'transaction_cost',stressed_cost):
        result=strategy.run_strategy(data,alpha,reference['definition'],origin_session=start,ledger=ledger)
    fields=['daily','positions','orders','child_orders','fills','rebalance_events','rejections','diagnostics','metrics']
    equal={field:result[field]==reference['result'][field] for field in fields}
    assert all(equal.values()),(h,r,equal)
    assert ledger==reference['ledger'],(h,r,'ledger mismatch')
    record={'experiment':'authored_loo_formula_equivalence','formula':plan['formula'],
            'capital_cny':100000,'holdings':h,'rebalance':r,'start':start,'end':end,
            'extra_cost_bps_per_fill':10,'source_generation':sha,
            'reference_file':str(previous.relative_to(BASE)),
            'all_result_fields_equal_except_formula_checksum':equal,'full_ledger_equal':True,
            'result':result,'ledger':ledger}
    (out/f'h{h}r{r}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    check={k:v for k,v in record.items() if k not in ('result','ledger')};checks.append(check)
    print(json.dumps({'holdings':h,'rebalance':r,'all_behavior_equal':True,'sharpe':result['metrics']['sharpe']}),flush=True)
(BASE/'loo-capital-equivalence.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')

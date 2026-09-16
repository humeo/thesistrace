"""Exercise the real strategy consumer with every Alpha input field unavailable."""
import json
import pathlib
import sys
from dataclasses import replace

directory = pathlib.Path(__file__).resolve().parent
repository = directory.parents[1]
sys.path.insert(0, str(repository/'apps/core/tests/kernel'))
from test_research_chunk_continuation import _minimal_alpha_factor_case, _alpha_factor_binding, _forward_labels, _strategy_input
from thesistrace.alpha_language import alpha_language
from thesistrace.research_kernel.kernel_run import RunInput
from thesistrace.research_kernel.research_chunks import execute_alpha_factor_chunk, execute_strategy_chunk_from_alpha_factor_outcome, empty_alpha_factor_continuation, empty_strategy_continuation

fixture, template = _minimal_alpha_factor_case()
compiled = alpha_language.compile('rank(revenue)')
financial_field = next(iter(compiled.field_ids_by_identifier.values()))
fixture = replace(fixture, matrices={**fixture.matrices, financial_field:fixture.matrices['price.close.adjusted'].copy()})
factor = RunInput(research_data=fixture, alpha_expression=compiled.expression, field_bindings={field:identifier for identifier,field in compiled.field_ids_by_identifier.items()}, effective_alpha_lookback=compiled.effective_lookback, universe=template.universe, neutralization=template.neutralization, research_kind='factor_evaluation', strategy=None, research_start_session=fixture.sessions[0], research_end_session=fixture.sessions[-1])
binding = _alpha_factor_binding(factor)
shared = execute_alpha_factor_chunk(run_input=factor,binding=binding,research_data=fixture,forward_labels=_forward_labels(fixture),research_sessions=fixture.sessions,final_chunk=True,continuation=empty_alpha_factor_continuation(),cancellation_check=lambda:None)

class NoAlphaFields:
    def __init__(self, base):
        self.base = base
    def __getattr__(self, name):
        return getattr(self.base, name)
    def snapshot(self):
        return self
    def slice_sessions(self, sessions):
        return NoAlphaFields(self.base.slice_sessions(sessions))
    def numeric_field_matrices(self, *args, **kwargs):
        raise AssertionError('Strategy attempted to read Alpha input fields')

depleted = NoAlphaFields(replace(fixture,matrices={}))
results = []
for holdings, interval in [(3,2),(5,5),(12,7)]:
    strategy = _strategy_input(factor,holdings_count=holdings,rebalance_interval=interval)
    reduced_input = RunInput(research_data=depleted,alpha_expression=strategy.alpha_expression_snapshot(),field_bindings=strategy.field_bindings_snapshot(),effective_alpha_lookback=strategy.alpha_execution_plan().effective_lookback,universe=strategy.universe,neutralization=strategy.neutralization,research_kind='strategy_backtest',strategy=strategy.strategy,research_start_session=strategy.research_start_session,research_end_session=strategy.research_end_session)
    def consume(run_input,data):
        return execute_strategy_chunk_from_alpha_factor_outcome(run_input=run_input,binding=binding,alpha_factor_outcome=shared,research_data=data,final_chunk=True,continuation=empty_strategy_continuation(),cancellation_check=lambda:None)
    before = consume(strategy,fixture)
    after = consume(reduced_input,depleted)
    assert before.final_values_snapshot()==after.final_values_snapshot()
    assert before.daily_observations_snapshot()==after.daily_observations_snapshot()
    assert before.continuation_snapshot()==after.continuation_snapshot()
    results.append({'holdings':holdings,'rebalance_interval':interval,'all_alpha_fields_unavailable':True,'same_result':True,'same_daily_observations':True,'same_continuation':True})
(directory/'strategy-field-dependency.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results))

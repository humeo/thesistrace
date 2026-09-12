import pytest

from thesistrace.alpha_language import FormulaCompilationError, ValueType, alpha_language
from thesistrace.research_kernel.alpha_expression import validate_normalized_exposure
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_series_execution_plan,
)


@pytest.mark.parametrize('source,lookback', [
    ('universe_advancing_fraction()', 1),
    ('if_else(universe_return() > 0, 1, 0.3)', 1),
    ('if_else(ts_mean(industry_return(801010), 3) > 0, 0.7, 0)', 3),
])
def test_shared_daily_exposure_compiles_in_account_scope(source, lookback):
    compiled = alpha_language.compile(source, context='exposure')
    assert compiled.context == 'exposure'
    assert compiled.result_type is ValueType.COMMON_NUMERIC_SERIES
    assert compiled.effective_lookback == lookback
    normalized = validate_normalized_exposure(compiled.expression)
    assert normalized.effective_lookback == lookback
    assert normalized.field_ids == ('price.close.adjusted',)


@pytest.mark.parametrize('source', [
    'close', 'rank(close)', 'rank(universe_return())',
    'if_else(universe_return() > 0, close, 0)',
    'universe_return() > 0', 'cash', 'position', 'drawdown',
])
def test_daily_exposure_rejects_stock_or_account_state_and_boolean_root(source):
    with pytest.raises(FormulaCompilationError):
        alpha_language.compile(source, context='exposure')


def test_daily_exposure_uses_shared_unknown_and_conditional_semantics():
    compiled = alpha_language.compile(
        'if_else(universe_return() > 0, 0.7, 1 / 0)', context='exposure',
    )
    result = evaluate_series_execution_plan(
        build_series_execution_plan(compiled), {"price.close.adjusted": [10, 11, None]}, length=3,
        common_values={('universe_return', None): (0.1, -0.1, None)},
    )
    assert result == [0.7, None, None]

from decimal import Decimal

import pytest

from thesistrace.research_kernel.portfolio_weighting import inverse_volatility_selection


def candidates(*names):
    return [{'instrument_id': name, 'value': len(names) - index}
            for index, name in enumerate(names)]


def test_inverse_volatility_uses_population_returns_and_normalizes():
    # Returns A=(0,.2), B=(0,.4): population sigma .1 and .2.
    selected, weights, excluded = inverse_volatility_selection(
        candidates('a', 'b'), 2,
        {'a': [Decimal(100), Decimal(100), Decimal(120)],
         'b': [Decimal(100), Decimal(100), Decimal(140)]}, 2,
    )
    assert [row['instrument_id'] for row in selected] == ['a', 'b']
    assert weights == {'a': '2/3', 'b': '1/3'}
    assert excluded == []


def test_ineligible_candidates_are_replaced_in_signal_order():
    selected, weights, excluded = inverse_volatility_selection(
        candidates('zero', 'short', 'missing', 'a', 'b'), 2,
        {'zero': [100, 100, 100], 'short': [100, 110],
         'missing': [100, None, 120], 'a': [100, 100, 120], 'b': [100, 100, 140]}, 2,
    )
    assert [row['instrument_id'] for row in selected] == ['a', 'b']
    assert weights == {'a': '2/3', 'b': '1/3'}
    assert excluded == [
        {'instrument_id': 'zero', 'reason': 'zero_volatility'},
        {'instrument_id': 'short', 'reason': 'insufficient_history'},
        {'instrument_id': 'missing', 'reason': 'unavailable_return'},
    ]


@pytest.mark.parametrize('closes', [[100, 100], [100, 120]])
def test_one_return_window_has_zero_population_volatility(closes):
    selected, weights, excluded = inverse_volatility_selection(
        candidates('a'), 1, {'a': closes}, 1,
    )
    assert selected == [] and weights == {}
    assert excluded == [{'instrument_id': 'a', 'reason': 'zero_volatility'}]


def test_window_uses_only_last_requested_returns_and_remaining_valid_candidate():
    selected, weights, excluded = inverse_volatility_selection(
        candidates('a', 'b'), 3,
        {'a': [None, 100, 100, 120], 'b': [100, 100, 100, 100]}, 2,
    )
    assert [row['instrument_id'] for row in selected] == ['a']
    assert weights == {'a': '1'}
    assert excluded == [{'instrument_id': 'b', 'reason': 'zero_volatility'}]


@pytest.mark.parametrize('window', [0, 253, True, 1.5])
def test_inverse_volatility_rejects_invalid_windows(window):
    with pytest.raises(ValueError, match='window'):
        inverse_volatility_selection([], 1, {}, window)


@pytest.mark.parametrize('bad_close', [0, -1, float('nan'), float('inf')])
def test_invalid_close_is_unavailable_return(bad_close):
    selected, weights, excluded = inverse_volatility_selection(
        candidates('a'), 1, {'a': [100, bad_close, 120]}, 2,
    )
    assert selected == [] and weights == {}
    assert excluded == [{'instrument_id': 'a', 'reason': 'unavailable_return'}]


def test_missing_data_access_entry_is_not_silently_excluded():
    with pytest.raises(KeyError, match='a'):
        inverse_volatility_selection(candidates('a'), 1, {}, 2)


def test_weighting_requirements_add_close_and_prior_return_observation():
    from thesistrace.alpha_language import alpha_language
    from thesistrace.alpha_language.requirements import expression_requirements

    signal = alpha_language.compile('volume')
    requirements = expression_requirements(
        signal, weighting='inverse_volatility', volatility_window=252,
    )
    assert requirements.field_bindings['price.close.adjusted'] == 'close'
    assert requirements.effective_lookback == 252
    assert requirements.estimated_work > signal.estimated_work
    assert expression_requirements(signal).effective_lookback == 0


@pytest.mark.parametrize('window', [0, 253, True, 1.5, '20'])
def test_public_strategy_rejects_invalid_volatility_window(window):
    from pydantic import ValidationError

    from thesistrace.research_run.models import StrategyBacktestSpec

    with pytest.raises(ValidationError, match='volatility_window'):
        StrategyBacktestSpec.model_validate({
            'research_kind': 'strategy_backtest', 'formula': 'close',
            'start_date': '2026-08-03', 'end_date': '2026-08-05',
            'universe': 'top300', 'neutralization': 'none',
            'initial_cash_cny': '100000', 'holdings_count': 3,
            'selection_every_sessions': 5, 'weighting': 'inverse_volatility',
            'volatility_window': window,
        })


def test_hundred_stock_inverse_weights_have_bounded_numeric_representation():
    from fractions import Fraction

    names = [f'stock{index}' for index in range(100)]
    closes = {
        name: [Decimal('100'), Decimal('101'), Decimal(103 + index), Decimal(107 + index * 2)]
        for index, name in enumerate(names)
    }
    selected, weights, excluded = inverse_volatility_selection(candidates(*names), 100, closes, 3)
    assert len(selected) == 100 and excluded == []
    assert sum(Fraction(value) for value in weights.values()) == 1
    # Frozen state must scale with the numeric precision, not products of 100 denominators.
    assert sum(len(value) for value in weights.values()) < 10000


def test_population_volatility_uses_n_observations_not_sample_n_minus_one():
    from thesistrace.research_kernel.portfolio_weighting import population_return_volatility

    # Returns 0 and .2 have population variance .01, not sample variance .02.
    assert population_return_volatility([Decimal(100), Decimal(100), Decimal(120)]) == Decimal('.1')
    assert population_return_volatility([Decimal(100), Decimal(120)]) == Decimal(0)

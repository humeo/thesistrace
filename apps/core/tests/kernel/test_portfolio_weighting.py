from fractions import Fraction

import pytest

from thesistrace.research_kernel.portfolio_weighting import select_portfolio


@pytest.mark.parametrize("scores,count,expected", [
    ([('a', 3), ('b', 2), ('c', 1)], 3,
     {'a': Fraction(1, 2), 'b': Fraction(1, 3), 'c': Fraction(1, 6)}),
    ([('a', 3), ('b', 3), ('c', 1)], 3,
     {'a': Fraction(5, 12), 'b': Fraction(5, 12), 'c': Fraction(1, 6)}),
    ([('d', 2), ('c', 2), ('b', 2), ('a', 3)], 3,
     {'a': Fraction(1, 2), 'b': Fraction(1, 4), 'c': Fraction(1, 4)}),
    ([('b', 2), ('a', 3)], 10, {'a': Fraction(2, 3), 'b': Fraction(1, 3)}),
    ([('a', -3)], 3, {'a': Fraction(1)}),
    ([], 3, {}),
    ([('c', 0), ('b', 0), ('a', 0)], 3,
     {'a': Fraction(1, 3), 'b': Fraction(1, 3), 'c': Fraction(1, 3)}),
])
def test_rank_weights_use_only_final_selected_ranks(scores, count, expected):
    candidates = [{'instrument_id': name, 'value': score} for name, score in scores]
    selected, weights = select_portfolio(candidates, count, 'rank_weight')
    assert [row['instrument_id'] for row in selected] == list(expected)
    assert weights == {name: str(value) for name, value in expected.items()}
    assert sum(Fraction(value) for value in weights.values()) == pytest.approx(1 if expected else 0)
    assert candidates == [{'instrument_id': name, 'value': score} for name, score in scores]


def test_equal_weights_keep_current_selection_order():
    selected, weights = select_portfolio([
        {'instrument_id': 'c', 'value': 1},
        {'instrument_id': 'b', 'value': 2},
        {'instrument_id': 'a', 'value': 2},
    ], 2, 'equal_weight')
    assert [row['instrument_id'] for row in selected] == ['a', 'b']
    assert weights == {'a': '1/2', 'b': '1/2'}


def test_weighting_rejects_an_unimplemented_model():
    with pytest.raises(ValueError, match='weighting'):
        select_portfolio([], 2, 'optimized_weight')


@pytest.mark.parametrize('weighting', [None, 'equal_weight', 'rank_weight', 'inverse_volatility'])
def test_strategy_spec_normalizes_the_public_weighting_default(weighting):
    from thesistrace.research_run.models import StrategyBacktestSpec

    command = {
        'research_kind': 'strategy_backtest', 'formula': 'close',
        'start_date': '2026-08-03', 'end_date': '2026-08-05',
        'universe': 'top300', 'neutralization': 'none',
        'initial_cash_cny': '100000', 'holdings_count': 3,
        'selection_every_sessions': 5,
    }
    if weighting is not None:
        command['weighting'] = weighting
    spec = StrategyBacktestSpec.model_validate(command)
    assert spec.model_dump()['weighting'] == (weighting or 'equal_weight')


def test_factor_spec_does_not_accept_portfolio_weighting():
    from pydantic import ValidationError

    from thesistrace.research_run.models import FactorEvaluationSpec

    with pytest.raises(ValidationError, match='weighting'):
        FactorEvaluationSpec.model_validate({"volatility_window": 20,
            'research_kind': 'factor_evaluation', 'formula': 'close',
            'start_date': '2026-08-03', 'end_date': '2026-08-05',
            'universe': 'top300', 'neutralization': 'none', 'weighting': 'rank_weight',
        })

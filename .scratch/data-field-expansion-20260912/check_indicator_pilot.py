"""Independent operand cross-checks; never choose among distinct supplier values."""
import json
from decimal import Decimal
from pathlib import Path

root = Path('.scratch/data-field-expansion-20260912')
source = json.loads((root/'indicator-pilot-source-observations.json').read_text())
records = {(r['params']['ts_code'], r['endpoint']):
           [dict(zip(r['fields'], item, strict=True)) for item in r['items']]
           for r in source['records'] if r['status'] == 'returned'}


def value(code, endpoint, period, field):
    values = {row[field] for row in records[(code, endpoint)] if row['end_date'] == period}
    if len(values) != 1 or None in values:
        return None
    return Decimal(str(values.pop()))


checks = []
for code in ('600519.SH', '000001.SZ'):
    for period in ('20240331', '20240630', '20240930', '20241231', '20250331', '20250630'):
        year = int(period[:4])
        previous_year = str(year-1)+period[4:]
        previous_quarter = {'0331': str(year-1)+'1231', '0630': str(year)+'0331',
                            '0930': str(year)+'0630', '1231': str(year)+'0930'}[period[4:]]
        get = lambda endpoint, field, p=period: value(code, endpoint, p, field)
        income = get('income', 'n_income_attr_p')
        equity = get('balancesheet', 'total_hldr_eqy_exc_min_int')
        start_equity = get('balancesheet', 'total_hldr_eqy_exc_min_int', str(year-1)+'1231')
        prior_equity = get('balancesheet', 'total_hldr_eqy_exc_min_int', previous_quarter)
        prior_income = Decimal(0) if period.endswith('0331') else get('income', 'n_income_attr_p', previous_quarter)
        prior_year_income = get('income', 'n_income_attr_p', previous_year)
        formulas = {
            'eps': ('income.basic_eps', [get('income', 'basic_eps')], lambda x: x[0]),
            'bps': ('parent_equity / shares (industrial sample only)',
                    [equity, get('balancesheet', 'total_share')] if code == '600519.SH' else [None],
                    lambda x: x[0]/x[1]),
            'current_ratio': ('current_assets / current_liabilities',
                              [get('balancesheet', 'total_cur_assets'), get('balancesheet', 'total_cur_liab')],
                              lambda x: x[0]/x[1]),
            'roe': ('cumulative_parent_profit / mean(start_year_equity,end_equity) * 100',
                    [income, start_equity, equity], lambda x: x[0]/((x[1]+x[2])/2)*100),
            'q_roe': ('quarter_parent_profit / mean(prior_quarter_equity,end_equity) * 100',
                      [income, prior_income, prior_equity, equity], lambda x: (x[0]-x[1])/((x[2]+x[3])/2)*100),
            'netprofit_yoy': ('(parent_profit / prior_year_same_period_profit - 1) * 100',
                              [income, prior_year_income], lambda x: (x[0]/x[1]-1)*100),
        }
        for field, (formula, operands, calculate) in formulas.items():
            actual = get('fina_indicator', field)
            entry = {'security': code, 'period': period, 'field': field, 'formula': formula,
                     'operands': [None if x is None else str(x) for x in operands],
                     'supplier_value': None if actual is None else str(actual)}
            if actual is None or any(x is None for x in operands):
                entry['status'] = 'missing_or_ambiguous_operand'
            else:
                computed = calculate(operands)
                difference = abs(actual-computed)
                entry.update(computed=str(computed), absolute_difference=str(difference),
                             status='matches_within_0.0001' if difference <= Decimal('0.0001') else 'does_not_match')
            checks.append(entry)
report = {'source': 'indicator-pilot-source-observations.json',
          'scope': 'independent sample unit comparisons, not production fallback formulas or universal definitions',
          'checks': checks}
(root/'indicator-pilot-unit-crosschecks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
for field in ('eps','bps','current_ratio','roe','q_roe','netprofit_yoy'):
    group=[x for x in checks if x['field']==field]
    print(field, {status:sum(x['status']==status for x in group) for status in sorted({x['status'] for x in group})})
    for x in group:
        if x['status']=='does_not_match': print(x)

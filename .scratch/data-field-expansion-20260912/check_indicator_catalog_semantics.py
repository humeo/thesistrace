"""Compare ambiguous indicator definitions against independent statement operands."""
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

root = Path(__file__).resolve().parent
source = json.loads((root / 'indicator-catalog-additional-observations.json').read_text())
records = {(r['params']['ts_code'], r['endpoint']):
           [dict(zip(r['fields'], item, strict=True)) for item in r['items']]
           for r in source['records'] if r['status'] == 'returned'}
checks = []


def get(code, endpoint, period, field):
    values = {row.get(field) for row in records[code, endpoint] if row['end_date'] == period}
    if len(values) != 1 or None in values:
        return None
    return Decimal(str(values.pop()))


def compare(code, period, field, hypothesis, operands, calculate, tolerance):
    actual = get(code, 'fina_indicator', period, field)
    entry = dict(security=code, period=period, field=field, hypothesis=hypothesis,
                 operands={key: None if value is None else str(value)
                           for key, value in operands.items()},
                 actual=None if actual is None else str(actual))
    if actual is None or any(value is None for value in operands.values()):
        entry['status'] = 'missing_or_ambiguous_operand'
    else:
        try:
            expected = calculate(operands)
            difference = abs(actual - expected)
            entry.update(expected=str(expected), difference=str(difference),
                         tolerance=str(tolerance),
                         status='matches' if difference <= tolerance else 'differs')
        except ZeroDivisionError:
            entry['status'] = 'zero_denominator'
    checks.append(entry)


for code in ('600019.SH', '000002.SZ'):
    periods = sorted({row['end_date'] for row in records[code, 'fina_indicator']})
    for period in periods:
        year = int(period[:4])
        prior = f'{year - 1}{period[4:]}'
        annual = f'{year - 1}1231'
        prior_quarter = {'0331': annual, '0630': f'{year}0331',
                         '0930': f'{year}0630', '1231': f'{year}0930'}[period[4:]]
        flow = lambda field, p=period: get(code, 'income', p, field)
        losses = {'current_loss': flow('assets_impair_loss'),
                  'current_revenue': flow('total_revenue')}
        compare(code, period, 'impai_ttm', 'YTD impairment / YTD total revenue * 100',
                losses, lambda x: x['current_loss'] / x['current_revenue'] * 100,
                Decimal('.0001'))
        ttm = dict(losses, prior_loss=flow('assets_impair_loss', prior),
                   prior_revenue=flow('total_revenue', prior),
                   annual_loss=flow('assets_impair_loss', annual),
                   annual_revenue=flow('total_revenue', annual))
        compare(code, period, 'impai_ttm', 'TTM impairment / TTM total revenue * 100',
                ttm, lambda x: (x['current_loss'] + x['annual_loss'] - x['prior_loss']) /
                (x['current_revenue'] + x['annual_revenue'] - x['prior_revenue']) * 100,
                Decimal('.0001'))
        quarter = dict(losses,
            previous_loss=Decimal(0) if period.endswith('0331')
            else flow('assets_impair_loss', prior_quarter),
            previous_revenue=Decimal(0) if period.endswith('0331')
            else flow('total_revenue', prior_quarter))
        for field in ('impai_ttm', 'q_impair_to_gr_ttm'):
            compare(code, period, field, 'single-quarter impairment / revenue * 100',
                    quarter, lambda x: (x['current_loss'] - x['previous_loss']) /
                    (x['current_revenue'] - x['previous_revenue']) * 100, Decimal('.0001'))
        compare(code, period, 'gross_margin', 'YTD operating revenue minus cost in CNY',
                {'revenue': flow('revenue'), 'cost': flow('oper_cost')},
                lambda x: x['revenue'] - x['cost'], Decimal('.02'))
        for column, scope in [('total_hldr_eqy_inc_min_int', 'consolidated'),
                              ('total_hldr_eqy_exc_min_int', 'parent')]:
            compare(code, period, 'equity_yoy', f'{scope} equity same-period YoY * 100',
                    {'current': get(code, 'balancesheet', period, column),
                     'prior': get(code, 'balancesheet', prior, column)},
                    lambda x: (x['current'] / x['prior'] - 1) * 100, Decimal('.0001'))
summary = {hypothesis: dict(Counter(item['status'] for item in checks
                                  if (item['field'], item['hypothesis']) == hypothesis))
           for hypothesis in {(item['field'], item['hypothesis']) for item in checks}}
report = {'source': 'indicator-catalog-additional-observations.json',
          'scope': 'Independent sampled hypotheses, not runtime fallback calculations',
          'checks': checks,
          'summary': [{'field': key[0], 'hypothesis': key[1], 'counts': value}
                      for key, value in sorted(summary.items())]}
(root / 'indicator-catalog-semantic-crosschecks.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + '\n')
for row in report['summary']:
    print(row)

"""Explicit independent ratio hypotheses; evidence only, never runtime formulas."""
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

root = Path(__file__).resolve().parent
sources = ('indicator-catalog-additional-observations.json',
           'indicator-catalog-operand-observations.json',
           'indicator-catalog-stock-operand-observations.json',
           'indicator-catalog-final-operand-observations.json',
           'indicator-cashflow-sample-observations.json',
           'indicator-cashflow-bridge-observations.json')
records = {}
metadata = ('ts_code', 'ann_date', 'f_ann_date', 'end_date', 'report_type', 'comp_type', 'update_flag')
join_conflicts = []
for filename in sources:
    for record in json.loads((root / filename).read_text())['records']:
        if record['status'] != 'returned':
            continue
        key = (record['params']['ts_code'], record['endpoint'])
        grouped = records.setdefault(key, {})
        for item in record['items']:
            row = dict(zip(record['fields'], item, strict=True))
            identity = tuple(row.get(field) for field in metadata)
            values = grouped.setdefault(identity, {})
            for field, cell in row.items():
                values.setdefault(field, set()).add(cell)
join_conflicts = [dict(security=key[0], endpoint=key[1], metadata=list(identity),
                       field=field, values=sorted(values, key=str))
                  for key, groups in records.items() for identity, cells in groups.items()
                  for field, values in cells.items() if len(values) > 1]
records = {key: [
    {field: next(iter(values)) if len(values) == 1 else None
     for field, values in cells.items()}
    for identity, cells in groups.items()]
    for key, groups in records.items()}
# Joining never selects a conflicting cell; None causes operand comparisons to skip.

# Each tuple identifies distinct numerator and denominator facts, not a name heuristic.
pairs = {
    'netprofit_margin': ('p.n_income', 'p.revenue'),
    'profit_to_gr': ('p.n_income', 'p.total_revenue'),
    'cogs_of_sales': ('p.oper_cost', 'p.revenue'),
    'saleexp_to_gr': ('p.sell_exp', 'p.total_revenue'),
    'adminexp_of_gr': ('p.admin_exp', 'p.total_revenue'),
    'finaexp_of_gr': ('p.fin_exp', 'p.total_revenue'),
    'gc_of_gr': ('p.total_cogs', 'p.total_revenue'),
    'op_of_gr': ('p.operate_profit', 'p.total_revenue'),
    'ebit_of_gr': ('i.ebit', 'p.total_revenue'),
    'opincome_of_ebt': ('i.op_income', 'p.total_profit'),
    'investincome_of_ebt': ('i.valuechange_income', 'p.total_profit'),
    'tax_to_ebt': ('p.income_tax', 'p.total_profit'),
    'dtprofit_to_profit': ('i.profit_dedt', 'p.n_income_attr_p'),
    'op_to_ebt': ('p.operate_profit', 'p.total_profit'),
    'nop_to_ebt': ('i.non_op_profit', 'p.total_profit'),
    'profit_to_op': ('p.total_profit', 'p.revenue'),
    'salescash_to_or': ('c.c_fr_sale_sg', 'p.revenue'),
    'ocf_to_or': ('c.n_cashflow_act', 'p.revenue'),
    'ocf_to_opincome': ('c.n_cashflow_act', 'i.op_income'),
    'capitalized_to_da': ('c.c_pay_acq_const_fiolta', 'i.daa'),
    'ocf_to_profit': ('c.n_cashflow_act', 'p.operate_profit'),
    'current_ratio': ('b.total_cur_assets', 'b.total_cur_liab'),
    'debt_to_assets': ('b.total_liab', 'b.total_assets'),
    'assets_to_eqt': ('b.total_assets', 'b.total_hldr_eqy_inc_min_int'),
    'dp_assets_to_eqt': ('b.total_assets', 'b.total_hldr_eqy_exc_min_int'),
    'ca_to_assets': ('b.total_cur_assets', 'b.total_assets'),
    'nca_to_assets': ('b.total_nca', 'b.total_assets'),
    'tbassets_to_totalassets': ('i.tangible_asset', 'b.total_assets'),
    'int_to_talcap': ('i.interestdebt', 'i.invest_capital'),
    'eqt_to_talcapital': ('b.total_hldr_eqy_exc_min_int', 'i.invest_capital'),
    'currentdebt_to_debt': ('b.total_cur_liab', 'b.total_liab'),
    'longdeb_to_debt': ('b.total_ncl', 'b.total_liab'),
    'ocf_to_shortdebt': ('c.n_cashflow_act', 'b.total_cur_liab'),
    'debt_to_eqt': ('b.total_liab', 'b.total_hldr_eqy_inc_min_int'),
    'eqt_to_debt': ('b.total_hldr_eqy_exc_min_int', 'b.total_liab'),
    'eqt_to_interestdebt': ('b.total_hldr_eqy_exc_min_int', 'i.interestdebt'),
    'tangibleasset_to_debt': ('i.tangible_asset', 'b.total_liab'),
    'tangasset_to_intdebt': ('i.tangible_asset', 'i.interestdebt'),
    'tangibleasset_to_netdebt': ('i.tangible_asset', 'i.netdebt'),
    'ocf_to_debt': ('c.n_cashflow_act', 'b.total_liab'),
    'ocf_to_interestdebt': ('c.n_cashflow_act', 'i.interestdebt'),
    'ocf_to_netdebt': ('c.n_cashflow_act', 'i.netdebt'),
    'ebitda_to_debt': ('i.ebitda', 'b.total_liab'),
    'cash_to_liqdebt': ('b.money_cap', 'b.total_cur_liab'),
    'op_to_liqdebt': ('p.operate_profit', 'b.total_cur_liab'),
    'op_to_debt': ('p.operate_profit', 'b.total_liab'),
}
pairs.update({
    'profit_to_op#total_revenue': ('p.total_profit', 'p.total_revenue'),
    'dp_assets_to_eqt#year_mean_parent': ('mean:b.total_assets', 'mean:b.total_hldr_eqy_exc_min_int'),
    'q_netprofit_margin': ('quarter:p.n_income', 'quarter:p.revenue'),
    'q_profit_to_gr': ('quarter:p.n_income', 'quarter:p.total_revenue'),
    'q_saleexp_to_gr': ('quarter:p.sell_exp', 'quarter:p.total_revenue'),
    'q_adminexp_to_gr': ('quarter:p.admin_exp', 'quarter:p.total_revenue'),
    'q_finaexp_to_gr': ('quarter:p.fin_exp', 'quarter:p.total_revenue'),
    'q_gc_to_gr': ('quarter:p.total_cogs', 'quarter:p.total_revenue'),
    'q_op_to_gr': ('quarter:p.operate_profit', 'quarter:p.total_revenue'),
    'q_opincome_to_ebt': ('i.q_opincome', 'quarter:p.total_profit'),
    'q_investincome_to_ebt': ('i.q_investincome', 'quarter:p.total_profit'),
    'q_dtprofit_to_profit': ('i.q_dtprofit', 'quarter:p.n_income_attr_p'),
    'q_salescash_to_or': ('quarter:c.c_fr_sale_sg', 'quarter:p.revenue'),
    'q_ocf_to_sales': ('quarter:c.n_cashflow_act', 'quarter:p.revenue'),
    'q_ocf_to_or': ('quarter:c.n_cashflow_act', 'i.q_opincome'),
})
pairs.update({
    'total_revenue_ps': ('p.total_revenue', 'b.total_share'),
    'revenue_ps': ('p.revenue', 'b.total_share'),
    'capital_rese_ps': ('b.cap_rese', 'b.total_share'),
    'surplus_rese_ps': ('b.surplus_rese', 'b.total_share'),
    'undist_profit_ps': ('b.undistr_porfit', 'b.total_share'),
    'diluted2_eps': ('p.n_income_attr_p', 'b.total_share'),
    'ocfps': ('c.n_cashflow_act', 'b.total_share'),
    'retainedps': ('i.retained_earnings', 'b.total_share'),
    'cfps': ('c.n_incr_cash_cash_equ', 'b.total_share'),
    'ebit_ps': ('i.ebit', 'b.total_share'),
    'fcff_ps': ('i.fcff', 'b.total_share'),
    'fcfe_ps': ('i.fcfe', 'b.total_share'),
    'q_eps': ('quarter:p.n_income_attr_p', 'b.total_share'),
})
pairs.update({
    'grossprofit_margin': ('i.gross_margin', 'p.revenue'),
    'q_gsprofit_margin': ('quarter:i.gross_margin', 'quarter:p.revenue'),
    'expense_of_sales': ('sum:p.sell_exp/p.admin_exp/p.fin_exp', 'p.revenue'),
    'q_exp_to_sales': ('quarter:sum:p.sell_exp/p.admin_exp/p.fin_exp', 'quarter:p.revenue'),
    'n_op_profit_of_ebt': ('subtract:p.non_oper_income/p.non_oper_exp', 'p.total_profit'),
    'roe_dt': ('i.profit_dedt', 'mean:b.total_hldr_eqy_exc_min_int'),
    'roa': ('i.ebit', 'mean:b.total_assets'),
    'npta': ('p.n_income', 'mean:b.total_assets'),
    'roa_dp': ('p.n_income_attr_p', 'mean:b.total_assets'),
    'q_dt_roe': ('i.q_dtprofit', 'quarter_mean:b.total_hldr_eqy_exc_min_int'),
    'q_npta': ('quarter:p.n_income', 'quarter_mean:b.total_assets'),
    'roe_yearly': ('annual:p.n_income_attr_p', 'mean:b.total_hldr_eqy_exc_min_int'),
    'roa2_yearly': ('annual:i.ebit', 'mean:b.total_assets'),
    'roa_yearly': ('annual:p.n_income', 'mean:b.total_assets'),
    'quick_ratio': ('subtract:b.total_cur_assets/b.inventories', 'b.total_cur_liab'),
    'ebit_to_interest': ('i.ebit', 'c.finan_exp'),
    'longdebt_to_workingcapital': ('b.total_ncl', 'i.working_capital'),
    'inv_turn': ('p.oper_cost', 'mean:b.inventories'),
    'ar_turn': ('p.revenue', 'mean:b.accounts_receiv'),
    'ca_turn': ('p.revenue', 'mean:b.total_cur_assets'),
    'fa_turn': ('p.revenue', 'mean:b.fix_assets'),
    'assets_turn': ('p.revenue', 'mean:b.total_assets'),
    'total_fa_trun': ('p.revenue', 'mean:i.fixed_assets'),
})
pairs.update({
    'ca_turn#total_revenue': ('p.total_revenue', 'mean:b.total_cur_assets'),
    'fa_turn#total_revenue': ('p.total_revenue', 'mean:b.fix_assets'),
    'assets_turn#total_revenue': ('p.total_revenue', 'mean:b.total_assets'),
    'total_fa_trun#total_revenue': ('p.total_revenue', 'mean:i.fixed_assets'),
    'ebit_to_interest#income_interest': ('i.ebit', 'p.fin_exp_int_exp'),
    'ebit_to_interest#indicator_interest': ('i.ebit', 'i.interst_income'),
})
pairs.update({
    'cash_ratio#liquid_receivables': ('sum:b.money_cap/b.accounts_receiv/b.oth_receiv', 'b.total_cur_liab'),
    'cash_ratio#liquid_notes_trading': ('sum:b.money_cap/b.trad_asset/b.notes_receiv/b.accounts_receiv/b.oth_receiv', 'b.total_cur_liab'),
    'cash_to_liqdebt_withinterest': ('b.money_cap', 'subtract:b.total_cur_liab/i.current_exint'),
})
pairs.update({
    'adminexp_of_gr#including_rd': ('sum:p.admin_exp/p.rd_exp', 'p.total_revenue'),
    'q_adminexp_to_gr#including_rd': ('quarter:sum:p.admin_exp/p.rd_exp', 'quarter:p.total_revenue'),
    'roic': ('i.after_tax_ebit', 'mean:i.invest_capital'),
    'roic#end_capital': ('i.after_tax_ebit', 'i.invest_capital'),
    'roic_yearly': ('annual:i.after_tax_ebit', 'mean:i.invest_capital'),
})
pairs.update({
    'invturn_days': ('period_days:mean:b.inventories', 'p.oper_cost'),
    'arturn_days': ('period_days:mean:b.accounts_receiv', 'p.revenue'),
})
pairs.update({
    'invturn_days#rounded_turnover': ('period_day_count', 'i.inv_turn'),
    'arturn_days#rounded_turnover': ('period_day_count', 'i.ar_turn'),
})
endpoints = {'i': 'fina_indicator', 'p': 'income', 'b': 'balancesheet', 'c': 'cashflow'}
checks = []


def value(code, period, ref):
    if ref == 'period_day_count':
        return Decimal(int(period[4:6]) * 30)
    if ref == 'i.tangible_deductions':
        return value(code, period, 'sum:b.intan_assets/b.goodwill/b.lt_amor_exp/b.defer_tax_assets')
    if ref == 'i.operating_cash_deductions':
        return value(code, period, 'sum:b.money_cap/i.current_exint')
    if ref.startswith('period_days:'):
        current = value(code, period, ref.removeprefix('period_days:'))
        return None if current is None else current * int(period[4:6]) * 30
    if ref == 'i.after_tax_ebit':
        ebit, tax, profit = (value(code, period, field)
                             for field in ('i.ebit', 'p.income_tax', 'p.total_profit'))
        return None if ebit is None or tax is None or profit in (None, 0) else ebit * (1 - tax / profit)
    if ref == 'i.noninterest_total':
        return value(code, period, 'sum:i.current_exint/i.noncurrent_exint')
    if ref.startswith(('sum:', 'subtract:', 'multiply:')):
        operation, operands = ref.split(':', 1)
        values = [value(code, period, operand) for operand in operands.split('/')]
        if None in values:
            return None
        return (sum(values) if operation == 'sum' else
                values[0] * values[1] if operation == 'multiply' else values[0] - values[1])
    if ref.startswith('annual:'):
        current = value(code, period, ref.removeprefix('annual:'))
        return None if current is None else current * 12 / int(period[4:6])
    if ref.startswith('divide:'):
        numerator, denominator = ref.removeprefix('divide:').split('/')
        top, bottom = value(code, period, numerator), value(code, period, denominator)
        return None if top is None or bottom in (None, 0) else top / bottom
    if ':' in ref:
        operation, operand = ref.split(':', 1)
        current = value(code, period, operand)
        year = int(period[:4])
        previous = f'{year-1}1231' if operation == 'mean' else {
            '0331': f'{year-1}1231' if operation == 'quarter_mean' else None, '0630': f'{year}0331', '0930': f'{year}0630',
            '1231': f'{year}0930',
        }[period[4:]]
        prior = Decimal(0) if previous is None else value(code, previous, operand)
        if current is None or prior is None:
            return None
        return (current + prior) / 2 if operation in {'mean', 'quarter_mean'} else current - prior
    endpoint, field = ref.split('.')
    values = {row.get(field) for row in records[code, endpoints[endpoint]]
              if row['end_date'] == period}
    if len(values) != 1 or None in values:
        return None
    return Decimal(str(values.pop()))


for field, (numerator, denominator) in pairs.items():
    for code in ('600019.SH', '000002.SZ'):
        periods = sorted({row['end_date'] for row in records[code, 'fina_indicator']})
        for period in periods:
            actual = value(code, period, 'i.' + field.split('#')[0])
            top, bottom = value(code, period, numerator), value(code, period, denominator)
            entry = dict(field=field, security=code, period=period,
                         numerator=numerator, denominator=denominator,
                         actual=None if actual is None else str(actual),
                         numerator_value=None if top is None else str(top),
                         denominator_value=None if bottom is None else str(bottom))
            if actual is None or top is None or bottom is None:
                entry['status'] = 'missing_or_ambiguous_operand'
            elif bottom == 0:
                entry['status'] = 'zero_denominator'
            else:
                ratio = top / bottom
                scales = [scale for scale in (1, 100)
                          if abs(actual - ratio * scale) <= (Decimal('.005')
                              if field in {'ocfps', 'cfps'} else Decimal('.0001'))]
                entry.update(ratio=str(ratio), matching_scales=scales,
                             tolerance='.005' if field in {'ocfps', 'cfps'} else '.0001',
                             status='matches' if len(scales) == 1 else
                             'ambiguous_scale' if scales else 'differs')
            checks.append(entry)
growth = {
    'basic_eps_yoy': ('i.eps', 'year'),
    'dt_eps_yoy': ('i.dt_eps', 'year'),
    'cfps_yoy': ('i.ocfps', 'year'),
    'op_yoy': ('p.operate_profit', 'year'),
    'ebt_yoy': ('p.total_profit', 'year'),
    'netprofit_yoy': ('p.n_income_attr_p', 'year'),
    'dt_netprofit_yoy': ('i.profit_dedt', 'year'),
    'ocf_yoy': ('c.n_cashflow_act', 'year'),
    'roe_yoy': ('i.roe', 'year'),
    'roe_yoy#end_equity': ('divide:p.n_income_attr_p/b.total_hldr_eqy_exc_min_int', 'year'),
    'dt_netprofit_yoy#two_decimal_rounding': ('i.profit_dedt', 'year'),
    'tr_yoy': ('p.total_revenue', 'year'),
    'or_yoy': ('p.revenue', 'year'),
    'equity_yoy': ('b.total_hldr_eqy_exc_min_int', 'year'),
    'bps_yoy': ('i.bps', 'year_start'),
    'assets_yoy': ('b.total_assets', 'year_start'),
    'eqt_yoy': ('b.total_hldr_eqy_exc_min_int', 'year_start'),
    'q_gr_yoy': ('quarter:p.total_revenue', 'year'),
    'q_gr_qoq': ('quarter:p.total_revenue', 'quarter'),
    'q_sales_yoy': ('quarter:p.revenue', 'year'),
    'q_sales_qoq': ('quarter:p.revenue', 'quarter'),
    'q_op_yoy': ('quarter:p.operate_profit', 'year'),
    'q_op_qoq': ('quarter:p.operate_profit', 'quarter'),
    'q_profit_yoy': ('quarter:p.n_income', 'year'),
    'q_profit_qoq': ('quarter:p.n_income', 'quarter'),
    'q_netprofit_yoy': ('quarter:p.n_income_attr_p', 'year'),
    'q_netprofit_qoq': ('quarter:p.n_income_attr_p', 'quarter'),
}
for field, (operand, comparison) in growth.items():
    for code in ('600019.SH', '000002.SZ'):
        periods = sorted({row['end_date'] for row in records[code, 'fina_indicator']})
        for period in periods:
            year = int(period[:4])
            prior = (f'{year-1}{period[4:]}' if comparison == 'year' else
                     f'{year-1}1231' if comparison == 'year_start' else
                     {'0331': f'{year-1}1231', '0630': f'{year}0331',
                      '0930': f'{year}0630', '1231': f'{year}0930'}[period[4:]])
            actual = value(code, period, 'i.' + field.split('#')[0])
            current, previous = value(code, period, operand), value(code, prior, operand)
            entry = dict(field=field, security=code, period=period, prior_period=prior,
                         operand=operand, comparison=comparison,
                         actual=None if actual is None else str(actual),
                         current=None if current is None else str(current),
                         previous=None if previous is None else str(previous))
            if actual is None or current is None or previous is None:
                entry['status'] = 'missing_or_ambiguous_operand'
            elif previous == 0:
                entry['status'] = 'zero_denominator'
            else:
                ratio = current / previous - 1
                tolerance = Decimal('.005') if field.endswith('#two_decimal_rounding') else Decimal('.0001')
                scales = [scale for scale in (1, 100)
                          if abs(actual - ratio * scale) <= tolerance]
                entry.update(ratio=str(ratio), matching_scales=scales, tolerance=str(tolerance),
                             status='matches' if len(scales) == 1 else
                             'ambiguous_scale' if scales else 'differs')
            checks.append(entry)
amounts = {
    'dt_eps': ('p.diluted_eps', '.0001'),
    'extra_item': ('subtract:p.n_income_attr_p/i.profit_dedt', '.02'),
    'profit_dedt': ('subtract:p.n_income_attr_p/i.extra_item', '.02'),
    'op_income': ('subtract:p.operate_profit/i.valuechange_income', '.02'),
    'valuechange_income': ('sum:p.invest_income/p.fv_value_chg_gain', '.02'),
    'interst_income': ('subtract:i.ebit/p.total_profit', '.02'),
    'daa': ('sum:c.depr_fa_coga_dpba/c.amort_intang_assets/c.lt_amort_deferred_exp', '.02'),
    'ebit': ('sum:p.total_profit/i.interst_income', '.02'),
    'ebitda': ('sum:i.ebit/i.daa', '.02'),
    'profit_prefin_exp': ('sum:p.operate_profit/p.fin_exp', '.02'),
    'non_op_profit': ('subtract:p.non_oper_income/p.non_oper_exp', '.02'),
    'tangible_asset': ('subtract:b.total_hldr_eqy_exc_min_int/i.tangible_deductions', '.02'),
    'networking_capital': ('subtract:b.total_cur_assets/i.operating_cash_deductions', '.02'),
    'working_capital': ('subtract:b.total_cur_assets/b.total_cur_liab', '.02'),
    'invest_capital': ('sum:b.total_hldr_eqy_inc_min_int/i.interestdebt', '.02'),
    'retained_earnings': ('sum:b.surplus_rese/b.undistr_porfit', '.02'),
    'fixed_assets': ('b.fix_assets_total', '.02'),
    'fixed_assets#construction_investment': ('sum:b.fix_assets/b.cip/b.invest_real_estate', '.02'),
    'fixed_assets#construction_materials_investment': ('sum:b.fix_assets/b.cip/b.const_materials/b.invest_real_estate', '.02'),
    'netdebt': ('subtract:i.interestdebt/b.money_cap', '.02'),
    'current_exint': ('sum:b.acct_payable/b.adv_receipts/b.payroll_payable/b.taxes_payable/b.oth_payable/b.div_payable', '.02'),
    'noncurrent_exint': ('sum:b.lt_payable/b.estimated_liab/b.defer_tax_liab/b.oth_ncl', '.02'),
    'interestdebt': ('subtract:b.total_liab/i.noninterest_total', '.02'),
    'q_opincome': ('quarter:i.op_income', '.02'),
    'q_investincome': ('quarter:i.valuechange_income', '.02'),
    'q_dtprofit': ('quarter:i.profit_dedt', '.02'),
    'turn_days': ('sum:i.invturn_days/i.arturn_days', '.0002'),
}
for field, (operand, tolerance) in amounts.items():
    for code in ('600019.SH', '000002.SZ'):
        periods = sorted({row['end_date'] for row in records[code, 'fina_indicator']})
        for period in periods:
            actual, expected = value(code, period, 'i.' + field.split('#')[0]), value(code, period, operand)
            entry = dict(field=field, security=code, period=period, operand=operand,
                         comparison='explicit amount or day identity', tolerance=tolerance,
                         actual=None if actual is None else str(actual),
                         expected=None if expected is None else str(expected))
            if actual is None or expected is None:
                entry['status'] = 'missing_or_ambiguous_operand'
            else:
                difference = abs(actual - expected)
                entry.update(difference=str(difference), matching_scales=[1],
                             status='matches' if difference <= Decimal(tolerance) else 'differs')
            checks.append(entry)
summary = []
for field in (*pairs, *growth, *amounts):
    rows = [x for x in checks if x['field'] == field]
    scales = Counter(str(x['matching_scales'][0]) for x in rows if x['status'] == 'matches')
    summary.append(dict(field=field, counts=dict(Counter(x['status'] for x in rows)),
                        scales=dict(scales)))
(root / 'indicator-ratio-scale-crosschecks.json').write_text(json.dumps(
    dict(sources=sources, join_conflicts=join_conflicts, tolerance='per-check tolerance in source units', checks=checks, summary=summary),
    ensure_ascii=False, indent=2) + '\n')
for row in summary:
    print(row)

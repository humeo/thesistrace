"""Bounded source-period comparisons, never production fallback formulas."""
import contextlib
import io
import json
import runpy
from collections import Counter
from decimal import Decimal
from pathlib import Path

root = Path(__file__).resolve().parent
with contextlib.redirect_stdout(io.StringIO()):
    evidence = runpy.run_path(str(root / 'check_indicator_ratio_scales.py'))
value = evidence['value']
checks = []
for code in ('600019.SH', '000002.SZ', '600009.SH'):
    periods = sorted({row['end_date'] for row in evidence['records'][code, 'fina_indicator']})
    for period in periods:
        prior = str(int(period[:4]) - 1) + '1231'
        operands = {name: value(code, period, ref) for name, ref in {
            'operating_cashflow': 'c.n_cashflow_act',
            'capex': 'c.c_pay_acq_const_fiolta', 'ebit': 'i.ebit',
            'daa': 'i.daa', 'tax': 'p.income_tax', 'profit': 'p.total_profit',
            'interest': 'i.interst_income', 'working_capital': 'i.networking_capital',
            'netdebt': 'i.netdebt', 'interestdebt': 'i.interestdebt',
            'fixed_assets': 'i.fixed_assets', 'fcff': 'i.fcff',
            'gross_working_capital': 'i.working_capital',
            'parent_profit': 'p.n_income_attr_p', 'provisions': 'c.prov_depr_assets',
            'intang_amort': 'c.amort_intang_assets', 'deferred_amort': 'c.lt_amort_deferred_exp',
            'interest_expense': 'p.fin_exp_int_exp', 'interest_income': 'p.fin_exp_int_inc',
            'borrowing': 'c.c_recp_borrow', 'repayment': 'c.c_prepay_amt_borr',
            'bond_proceeds': 'c.proc_issue_bonds',
            'statement_free_cashflow': 'c.free_cashflow',
        }.items()}
        operands['prior_working_capital'] = value(code, prior, 'i.networking_capital')
        operands['prior_gross_working_capital'] = value(code, prior, 'i.working_capital')
        operands['prior_fixed_assets'] = value(code, prior, 'i.fixed_assets')
        operands['prior_netdebt'] = value(code, prior, 'i.netdebt')
        operands['prior_interestdebt'] = value(code, prior, 'i.interestdebt')
        def calc(names, operation):
            cells = [operands[name] for name in names.split()]
            if any(v is None for v in cells):
                return None
            try:
                return operation(*cells)
            except (ZeroDivisionError, ArithmeticError):
                return None
        def operating_wc(at):
            refs = ('b.total_cur_assets', 'b.money_cap', 'b.total_cur_liab',
                    'b.notes_payable', 'b.non_cur_liab_due_1y')
            cells = [value(code, at, ref) for ref in refs]
            if any(cell is None for cell in cells):
                return None
            assets,cash,liabilities,notes,due = cells
            return assets-cash-liabilities+notes+due
        operands['alternative_wc'] = operating_wc(period)
        operands['prior_alternative_wc'] = operating_wc(prior)
        hypotheses = {
            'fcff#statement_free_cashflow': operands['statement_free_cashflow'],
            'fcff#parent_profit_balance_investment': calc(
                'parent_profit provisions intang_amort deferred_amort interest_expense interest_income tax profit fixed_assets prior_fixed_assets alternative_wc prior_alternative_wc',
                lambda net,provisions,amort,deferred,interest,income,tax,profit,fa,prior_fa,wc,prior_wc:
                    net+provisions+amort+deferred+(interest-income)*(1-tax/profit)
                    -(fa-prior_fa)-(wc-prior_wc)),
            'fcfe#parent_profit_balance_investment_borrowing': calc(
                'parent_profit provisions intang_amort deferred_amort fixed_assets prior_fixed_assets alternative_wc prior_alternative_wc borrowing repayment',
                lambda net,provisions,amort,deferred,fa,prior_fa,wc,prior_wc,borrowing,repayment:
                    net+provisions+amort+deferred-(fa-prior_fa)-(wc-prior_wc)+borrowing-repayment),
            'fcff#cashflow_after_tax_interest': calc(
                'operating_cashflow capex interest tax profit',
                lambda ocf, capex, interest, tax, profit: ocf - capex + interest * (1-tax/profit)),
            'fcff#nopat_gross_working_capital': calc(
                'ebit tax profit daa capex gross_working_capital prior_gross_working_capital',
                lambda ebit,tax,profit,daa,capex,wc,prior_wc:
                    ebit*(1-tax/profit)+daa-capex-(wc-prior_wc)),
            'fcff#nopat_working_capital': calc(
                'ebit tax profit daa capex working_capital prior_working_capital',
                lambda ebit,tax,profit,daa,capex,wc,prior_wc:
                    ebit*(1-tax/profit)+daa-capex-(wc-prior_wc)),
            'fcff#nopat_asset_balance_changes': calc(
                'ebit tax profit fixed_assets prior_fixed_assets working_capital prior_working_capital',
                lambda ebit,tax,profit,fa,prior_fa,wc,prior_wc:
                    ebit*(1-tax/profit)-(fa-prior_fa)-(wc-prior_wc)),
            'fcfe#fcff_after_tax_interest_debt_change': calc(
                'fcff interest tax profit interestdebt prior_interestdebt',
                lambda fcff,interest,tax,profit,debt,prior_debt:
                    fcff-interest*(1-tax/profit)+debt-prior_debt),
            'fcfe#fcff_net_financing_cashflow': calc(
                'fcff borrowing repayment bond_proceeds',
                lambda fcff,borrowing,repayment,bonds: fcff+borrowing-repayment+bonds),
            'fcfe#cashflow_debt_change': calc(
                'operating_cashflow capex interestdebt prior_interestdebt',
                lambda ocf,capex,debt,prior_debt: ocf-capex+debt-prior_debt),
        }
        for hypothesis, expected in hypotheses.items():
            actual = value(code, period, 'i.' + hypothesis.split('#')[0])
            difference = None if actual is None or expected is None else abs(actual-expected)
            checks.append({
                'hypothesis': hypothesis, 'security': code, 'period': period,
                'comparison_base': prior, 'unit': 'CNY',
                'operands': {k: None if v is None else str(v) for k,v in operands.items()},
                'actual': None if actual is None else str(actual),
                'expected': None if expected is None else str(expected),
                'difference': None if difference is None else str(difference),
                'tolerance': '.02',
                'status': 'missing_or_ambiguous_operand' if difference is None else
                          'matches' if difference <= Decimal('.02') else 'differs',
            })
summary = {name: dict(Counter(row['status'] for row in checks if row['hypothesis'] == name))
           for name in sorted({row['hypothesis'] for row in checks})}
(root/'indicator-free-cashflow-crosschecks.json').write_text(json.dumps({
    'scope': 'Retained cumulative cashflow and year-start balance hypotheses; not universal vendor reconstruction.',
    'checks': checks, 'summary': summary,
}, ensure_ascii=False, indent=2)+'\n')
print(summary)

"""Bounded source qualification; existing adapter, no credential serialization."""
import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from thesistrace.data.financial_indicator_source import FINANCIAL_INDICATOR_SOURCE_FIELDS
from thesistrace.adapters.tushare_provider import HttpTushareTransport, TushareAdapter

parser = argparse.ArgumentParser()
profiles = parser.add_mutually_exclusive_group()
profiles.add_argument("--catalog", action="store_true")
profiles.add_argument("--catalog-operands", action="store_true")
profiles.add_argument("--catalog-stock-operands", action="store_true")
profiles.add_argument("--catalog-final-operands", action="store_true")
profiles.add_argument("--catalog-cashflow-sample", action="store_true")
profiles.add_argument("--catalog-cashflow-bridge", action="store_true")
args = parser.parse_args()

config = {}
for line in Path('../../.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key.strip() in {'THESISTRACE_TUSHARE_TOKEN', 'THESISTRACE_TUSHARE_ENDPOINT'}:
        config[key.strip()] = value.strip().strip('"').strip("'")
token = os.environ.get('THESISTRACE_TUSHARE_TOKEN') or config.get('THESISTRACE_TUSHARE_TOKEN')
endpoint = config.get('THESISTRACE_TUSHARE_ENDPOINT', 'https://api.tushare.pro')
if not token or urlsplit(endpoint).hostname != 'api.tushare.pro':
    raise SystemExit('Official endpoint/token configuration unavailable')
transport = HttpTushareTransport(endpoint=endpoint, timeout_seconds=20)
provider = TushareAdapter(token=token, transport=transport, max_attempts=1)
metadata = ('ts_code', 'ann_date', 'f_ann_date', 'end_date', 'report_type', 'comp_type', 'update_flag')
if args.catalog_cashflow_bridge:
    securities = ('600019.SH', '000002.SZ', '600009.SH')
    start_date, end_date = '20150101', '20181231'
    requests = (
        ('cashflow', (*metadata, 'free_cashflow', 'proc_issue_bonds',
                     'c_recp_borrow', 'c_prepay_amt_borr')),
    )
    output_name = 'indicator-cashflow-bridge-observations.json'
elif args.catalog_cashflow_sample:
    securities = ('600009.SH',)
    start_date, end_date = '20150101', '20181231'
    requests = (
        ('fina_indicator', FINANCIAL_INDICATOR_SOURCE_FIELDS),
        ('income', (*metadata, 'total_profit', 'income_tax', 'n_income', 'n_income_attr_p',
                    'fin_exp_int_exp', 'fin_exp_int_inc')),
        ('cashflow', (*metadata, 'net_profit', 'prov_depr_assets', 'c_recp_borrow',
                     'c_prepay_amt_borr', 'proc_issue_bonds', 'depr_fa_coga_dpba',
                     'amort_intang_assets', 'lt_amort_deferred_exp', 'n_cashflow_act',
                     'c_pay_acq_const_fiolta')),
        ('balancesheet', (*metadata, 'total_cur_assets', 'money_cap', 'total_cur_liab',
                         'notes_payable', 'non_cur_liab_due_1y', 'total_share')),
    )
    output_name = 'indicator-cashflow-sample-observations.json'
elif args.catalog_final_operands:
    securities = ('600019.SH', '000002.SZ')
    start_date, end_date = '20150101', '20181231'
    requests = (
        ('cashflow', (*metadata, 'net_profit', 'prov_depr_assets', 'c_recp_borrow',
                     'c_prepay_amt_borr', 'depr_fa_coga_dpba', 'amort_intang_assets',
                     'lt_amort_deferred_exp')),
        ('income', (*metadata, 'fin_exp_int_exp', 'fin_exp_int_inc')),
        ('balancesheet', (*metadata, 'notes_payable')),
    )
    output_name = 'indicator-catalog-final-operand-observations.json'
elif args.catalog_stock_operands:
    securities = ('600019.SH', '000002.SZ')
    start_date, end_date = '20150101', '20181231'
    requests = (
        ('balancesheet', (*metadata, 'prepayment', 'trad_asset', 'notes_receiv',
                         'oth_receiv', 'cip', 'const_materials', 'fixed_assets_disp',
                         'invest_real_estate', 'r_and_d', 'defer_tax_assets', 'int_payable',
                         'acct_payable', 'adv_receipts', 'payroll_payable', 'taxes_payable',
                         'oth_payable', 'div_payable', 'lt_payable', 'estimated_liab',
                         'defer_tax_liab', 'oth_ncl')),
        ('income', (*metadata, 'rd_exp', 'forex_gain')),
    )
    output_name = 'indicator-catalog-stock-operand-observations.json'
elif args.catalog_operands:
    securities = ('600019.SH', '000002.SZ')
    start_date, end_date = '20150101', '20181231'
    requests = (
        ('income', (*metadata, 'total_revenue', 'revenue', 'oper_cost', 'total_cogs',
                    'operate_profit', 'total_profit', 'n_income', 'n_income_attr_p',
                    'income_tax', 'sell_exp', 'admin_exp', 'fin_exp', 'assets_impair_loss',
                    'non_oper_income', 'non_oper_exp', 'invest_income', 'fv_value_chg_gain',
                    'int_exp', 'fin_exp_int_exp', 'basic_eps', 'diluted_eps')),
        ('balancesheet', (*metadata, 'total_share', 'total_assets', 'total_liab',
                         'total_hldr_eqy_exc_min_int', 'total_hldr_eqy_inc_min_int',
                         'total_cur_assets', 'total_nca', 'total_cur_liab', 'total_ncl',
                         'money_cap', 'inventories', 'accounts_receiv', 'fix_assets',
                         'fix_assets_total', 'cap_rese', 'surplus_rese', 'undistr_porfit',
                         'intan_assets', 'goodwill', 'lt_amor_exp', 'lt_borr', 'st_borr',
                         'bond_payable', 'non_cur_liab_due_1y')),
        ('cashflow', (*metadata, 'n_cashflow_act', 'c_fr_sale_sg', 'n_incr_cash_cash_equ',
                     'c_pay_acq_const_fiolta', 'depr_fa_coga_dpba', 'amort_intang_assets',
                     'lt_amort_deferred_exp', 'finan_exp')),
    )
    output_name = 'indicator-catalog-operand-observations.json'
elif args.catalog:
    securities = ('600019.SH', '000002.SZ')
    start_date, end_date = '20150101', '20181231'
    requests = (
        ('fina_indicator', FINANCIAL_INDICATOR_SOURCE_FIELDS),
        ('income', (*metadata, 'total_revenue', 'revenue', 'oper_cost', 'assets_impair_loss',
                    'n_income_attr_p', 'n_income', 'total_profit', 'int_exp', 'fin_exp')),
        ('balancesheet', (*metadata, 'total_hldr_eqy_inc_min_int',
                         'total_hldr_eqy_exc_min_int', 'total_assets', 'total_liab')),
    )
    output_name = 'indicator-catalog-additional-observations.json'
else:
    securities = ('600519.SH', '000001.SZ')
    start_date, end_date = '20230101', '20251231'
    requests = (
        ('fina_indicator', FINANCIAL_INDICATOR_SOURCE_FIELDS),
        ('income', (*metadata, 'basic_eps', 'n_income_attr_p', 'n_income')),
        ('balancesheet', (*metadata, 'total_share', 'total_cur_assets', 'total_cur_liab',
                         'total_hldr_eqy_exc_min_int', 'oth_eqt_tools_p_shr')),
    )
    output_name = 'indicator-pilot-source-observations.json'
output = Path('.scratch/data-field-expansion-20260912') / output_name
records = []
try:
    for code in securities:
        for api, fields in requests:
            params = {'ts_code': code, 'start_date': start_date, 'end_date': end_date}
            if api != 'fina_indicator':
                params['report_type'] = '1'
            record = {'endpoint': api, 'params': params, 'requested_fields': fields,
                      'observed_at': datetime.now(UTC).isoformat()}
            try:
                response = provider.query_raw(api, params=params, fields=fields)
                record.update(fields=response.fields, items=response.items,
                              status='returned' if response.items else 'empty',
                              row_count=len(response.items))
            except Exception as error:
                record.update(status='failed', error_type=type(error).__name__,
                              reason_code=getattr(error, 'reason_code', None))
            records.append(record)
            output.write_text(json.dumps({'scope': f'{len(securities)*len(requests)} read-only requests; {start_date}-{end_date}',
                'documentation': 'https://tushare.pro/document/2?doc_id=79',
                'records': records}, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps({'endpoint': api, 'security': code, 'status': record['status'],
                              'rows': record.get('row_count')}, ensure_ascii=False), flush=True)
finally:
    transport.close()

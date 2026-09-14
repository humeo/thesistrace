"""Ordinary financial indicators, bounded by report period rather than pagination."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from thesistrace.data.source import DataSourceError, RawSourceResponse

# Explicit source contract: https://tushare.pro/document/2?doc_id=79
FINANCIAL_INDICATOR_SOURCE_FIELDS = (
    "ts_code",
    "ann_date",
    "end_date",
    "eps",
    "dt_eps",
    "total_revenue_ps",
    "revenue_ps",
    "capital_rese_ps",
    "surplus_rese_ps",
    "undist_profit_ps",
    "extra_item",
    "profit_dedt",
    "gross_margin",
    "current_ratio",
    "quick_ratio",
    "cash_ratio",
    "invturn_days",
    "arturn_days",
    "inv_turn",
    "ar_turn",
    "ca_turn",
    "fa_turn",
    "assets_turn",
    "op_income",
    "valuechange_income",
    "interst_income",
    "daa",
    "ebit",
    "ebitda",
    "fcff",
    "fcfe",
    "current_exint",
    "noncurrent_exint",
    "interestdebt",
    "netdebt",
    "tangible_asset",
    "working_capital",
    "networking_capital",
    "invest_capital",
    "retained_earnings",
    "diluted2_eps",
    "bps",
    "ocfps",
    "retainedps",
    "cfps",
    "ebit_ps",
    "fcff_ps",
    "fcfe_ps",
    "netprofit_margin",
    "grossprofit_margin",
    "cogs_of_sales",
    "expense_of_sales",
    "profit_to_gr",
    "saleexp_to_gr",
    "adminexp_of_gr",
    "finaexp_of_gr",
    "impai_ttm",
    "gc_of_gr",
    "op_of_gr",
    "ebit_of_gr",
    "roe",
    "roe_waa",
    "roe_dt",
    "roa",
    "npta",
    "roic",
    "roe_yearly",
    "roa2_yearly",
    "roe_avg",
    "opincome_of_ebt",
    "investincome_of_ebt",
    "n_op_profit_of_ebt",
    "tax_to_ebt",
    "dtprofit_to_profit",
    "salescash_to_or",
    "ocf_to_or",
    "ocf_to_opincome",
    "capitalized_to_da",
    "debt_to_assets",
    "assets_to_eqt",
    "dp_assets_to_eqt",
    "ca_to_assets",
    "nca_to_assets",
    "tbassets_to_totalassets",
    "int_to_talcap",
    "eqt_to_talcapital",
    "currentdebt_to_debt",
    "longdeb_to_debt",
    "ocf_to_shortdebt",
    "debt_to_eqt",
    "eqt_to_debt",
    "eqt_to_interestdebt",
    "tangibleasset_to_debt",
    "tangasset_to_intdebt",
    "tangibleasset_to_netdebt",
    "ocf_to_debt",
    "ocf_to_interestdebt",
    "ocf_to_netdebt",
    "ebit_to_interest",
    "longdebt_to_workingcapital",
    "ebitda_to_debt",
    "turn_days",
    "roa_yearly",
    "roa_dp",
    "fixed_assets",
    "profit_prefin_exp",
    "non_op_profit",
    "op_to_ebt",
    "nop_to_ebt",
    "ocf_to_profit",
    "cash_to_liqdebt",
    "cash_to_liqdebt_withinterest",
    "op_to_liqdebt",
    "op_to_debt",
    "roic_yearly",
    "total_fa_trun",
    "profit_to_op",
    "q_opincome",
    "q_investincome",
    "q_dtprofit",
    "q_eps",
    "q_netprofit_margin",
    "q_gsprofit_margin",
    "q_exp_to_sales",
    "q_profit_to_gr",
    "q_saleexp_to_gr",
    "q_adminexp_to_gr",
    "q_finaexp_to_gr",
    "q_impair_to_gr_ttm",
    "q_gc_to_gr",
    "q_op_to_gr",
    "q_roe",
    "q_dt_roe",
    "q_npta",
    "q_opincome_to_ebt",
    "q_investincome_to_ebt",
    "q_dtprofit_to_profit",
    "q_salescash_to_or",
    "q_ocf_to_sales",
    "q_ocf_to_or",
    "basic_eps_yoy",
    "dt_eps_yoy",
    "cfps_yoy",
    "op_yoy",
    "ebt_yoy",
    "netprofit_yoy",
    "dt_netprofit_yoy",
    "ocf_yoy",
    "roe_yoy",
    "bps_yoy",
    "assets_yoy",
    "eqt_yoy",
    "tr_yoy",
    "or_yoy",
    "q_gr_yoy",
    "q_gr_qoq",
    "q_sales_yoy",
    "q_sales_qoq",
    "q_op_yoy",
    "q_op_qoq",
    "q_profit_yoy",
    "q_profit_qoq",
    "q_netprofit_yoy",
    "q_netprofit_qoq",
    "equity_yoy",
    "rd_exp",
    "update_flag",
)


@dataclass(frozen=True)
class FinancialIndicatorSourceShard:
    ts_code: str
    start_date: str
    end_date: str
    response: RawSourceResponse
    complete: bool


class FinancialIndicatorProvider(Protocol):
    """Return source rows or raise a normalized DataSourceError."""

    def query_raw(
        self, api_name: str, *, params: Mapping[str, object], fields: Sequence[str],
    ) -> RawSourceResponse: ...


class FinancialIndicatorSource:
    def __init__(self, provider: FinancialIndicatorProvider) -> None:
        self._provider = provider

    def collect_report_range(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> Iterator[FinancialIndicatorSourceShard]:
        """Yield receipts, including capped parents; exhaust to establish completion.

        The caller persists each receipt before continuing. Only complete leaves
        contribute records; capped parents remain evidence of why we subdivided.
        Empty leaves mean no returned source records, not a satisfied disclosure
        target. Disclosure pending is owned by the collection service.
        """
        start = datetime.strptime(start_date, "%Y%m%d").date()
        end = datetime.strptime(end_date, "%Y%m%d").date()
        if start > end or not ts_code or ts_code != ts_code.strip():
            raise ValueError("Invalid indicator report range or identity")
        pending = [(start, end)]
        while pending:
            lower, upper = pending.pop()
            lower_text, upper_text = lower.strftime("%Y%m%d"), upper.strftime("%Y%m%d")
            raw = self._provider.query_raw(
                "fina_indicator",
                params={"ts_code": ts_code, "start_date": lower_text, "end_date": upper_text},
                fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            )
            try:
                if len(set(raw.fields)) != len(raw.fields) or not set(
                    FINANCIAL_INDICATOR_SOURCE_FIELDS
                ) <= set(raw.fields):
                    raise ValueError("Missing or duplicate source columns")
                for item in raw.items:
                    row = dict(zip(raw.fields, item, strict=True))
                    period = str(row["end_date"])
                    datetime.strptime(period, "%Y%m%d")
                    if row["ts_code"] != ts_code or not lower_text <= period <= upper_text:
                        raise ValueError("Source returned an unrelated identity or report period")
            except (ValueError, TypeError, KeyError) as error:
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="MALFORMED_FINANCIAL_INDICATOR_PAYLOAD",
                ) from error
            complete = len(raw.items) < 100
            yield FinancialIndicatorSourceShard(ts_code, lower_text, upper_text, raw, complete)
            if complete:
                continue
            if lower == upper:
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="FINANCIAL_INDICATOR_TRUNCATED",
                )
            midpoint = lower + (upper - lower) // 2
            pending.extend(((midpoint + timedelta(days=1), upper), (lower, midpoint)))

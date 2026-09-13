import pyarrow as pa
import pytest

from thesistrace.data.financial_indicator_series import FinancialIndicatorSeriesResolver


def fact(period, session, **values):
    return {
        "instrument_id": "stock-1",
        "source_report_period": period,
        "source_published_date": "20200420",
        "state_effective_session": session,
        "availability_status": "available",
        "observation_event_at": session + "T00:00:00+00:00",
        "eps": None,
        "roe": None,
        **values,
    }


def resolver(rows):
    def read(columns, instruments, through):
        table = pa.Table.from_pylist(
            [
                row
                for row in rows
                if row["instrument_id"] in instruments and row["state_effective_session"] <= through
            ]
        )
        return table.select(sorted(columns))

    return FinancialIndicatorSeriesResolver("a" * 64, read)


def test_latest_report_null_and_conflict_hide_previous_values():
    rows = [
        fact("20191231", "2020-04-21", eps=2.0, roe=15.0),
        fact("20200331", "2020-04-30", eps=None, roe=3.0),
        fact(
            "20200331",
            "2020-05-04",
            eps=9.0,
            roe=8.0,
            availability_status="conflicting_observation",
        ),
        fact("20200331", "2020-05-05", eps=1.0, roe=4.0),
    ]
    result = (
        resolver(rows)
        .resolve_table(
            manifest_sha256="a" * 64,
            field_ids=("financial.indicator.eps", "financial.indicator.roe"),
            sessions=("2020-04-21", "2020-04-30", "2020-05-04", "2020-05-05"),
            instrument_ids=("stock-1",),
        )
        .to_pylist()
    )
    assert [r["financial.indicator.eps"] for r in result] == [2.0, None, None, 1.0]
    assert [r["financial.indicator.roe"] for r in result] == [0.15, 0.03, None, 0.04]


def test_old_report_revision_does_not_replace_newer_report():
    rows = [
        fact("20191231", "2020-04-21", eps=2.0),
        fact("20200331", "2020-04-30", eps=1.0),
        fact("20191231", "2020-05-04", eps=3.0),
    ]
    result = (
        resolver(rows)
        .resolve_table(
            manifest_sha256="a" * 64,
            field_ids=("financial.indicator.eps",),
            sessions=("2020-05-04",),
            instrument_ids=("stock-1",),
        )
        .to_pylist()
    )
    assert result[0]["financial.indicator.eps"] == 1.0


def test_reader_rejects_different_generation():
    with pytest.raises(ValueError):
        resolver([]).resolve_table(
            manifest_sha256="b" * 64,
            field_ids=("financial.indicator.eps",),
            sessions=("2020-05-04",),
            instrument_ids=("stock-1",),
        )


def test_requested_projection_preserves_sorted_coordinates_and_missing_values():
    rows = [
        fact("20200331", "2020-04-21", eps="2", roe="15"),
        fact("20200331", "2020-04-30", instrument_id="stock-2", eps="3", roe=None),
    ]

    def read(columns, instruments, through):
        assert columns == {
            "instrument_id", "source_report_period", "source_published_date",
            "state_effective_session", "availability_status", "observation_event_at",
            "eps", "roe",
        }
        assert instruments == frozenset({"stock-2", "stock-1", "stock-3"})
        assert through == "2020-04-30"
        return pa.Table.from_pylist(rows).select(sorted(columns))

    result = FinancialIndicatorSeriesResolver("a" * 64, read).resolve_table(
        manifest_sha256="a" * 64,
        field_ids=("financial.indicator.roe", "financial.indicator.eps"),
        sessions=("2020-04-20", "2020-04-21", "2020-04-30"),
        instrument_ids=("stock-2", "stock-1", "stock-3"),
    )
    assert result.column_names == [
        "session", "instrument_id", "financial.indicator.roe", "financial.indicator.eps",
    ]
    assert result["instrument_id"].to_pylist() == ["stock-1", "stock-2", "stock-3"] * 3
    assert result["financial.indicator.eps"].to_pylist() == [
        None, None, None, 2, None, None, 2, 3, None,
    ]
    assert result["financial.indicator.roe"].to_pylist() == [
        None, None, None, .15, None, None, .15, None, None,
    ]


def test_gross_profit_reads_supplier_amount_and_impairment_keeps_fixed_periods():
    from thesistrace.data.fields import alpha_field_catalog

    catalog = {field.alpha.identifier: field for field in alpha_field_catalog()}
    gross = catalog["gross_profit"]
    assert gross.source_column == "gross_margin"
    assert gross.source_lineage == "tushare.fina_indicator.gross_margin"
    assert gross.unit == "CNY"
    assert gross.report_period_selection == "latest_visible_report_cumulative"
    assert catalog["impai_ttm"].report_period_selection == "latest_visible_report_cumulative"
    assert catalog["q_impair_to_gr_ttm"].report_period_selection == "latest_visible_single_quarter"

    rows = [
        fact("20200331", "2020-04-21", gross_margin="120000", impai_ttm="15",
             q_impair_to_gr_ttm="8"),
        fact("20200630", "2020-08-03", gross_margin=None, impai_ttm=None,
             q_impair_to_gr_ttm="4"),
    ]
    result = resolver(rows).resolve_table(
        manifest_sha256="a" * 64,
        field_ids=("financial.indicator.gross_profit", "financial.indicator.impai_ttm",
                   "financial.indicator.q_impair_to_gr_ttm"),
        sessions=("2020-04-21", "2020-08-03"),
        instrument_ids=("stock-1",),
    )
    assert result["financial.indicator.gross_profit"].to_pylist() == [120000, None]
    assert result["financial.indicator.impai_ttm"].to_pylist() == [.15, None]
    assert result["financial.indicator.q_impair_to_gr_ttm"].to_pylist() == [.08, .04]


@pytest.mark.parametrize("name,period", [
    ("total_revenue_ps", "latest_visible_report_cumulative"),
    ("revenue_ps", "latest_visible_report_cumulative"),
    ("capital_rese_ps", "latest_visible_report_end"),
    ("surplus_rese_ps", "latest_visible_report_end"),
    ("undist_profit_ps", "latest_visible_report_end"),
    ("diluted2_eps", "latest_visible_report_cumulative"),
    ("ocfps", "latest_visible_report_cumulative"),
    ("retainedps", "latest_visible_report_end"),
    ("cfps", "latest_visible_report_cumulative"),
    ("ebit_ps", "latest_visible_report_cumulative"),
    ("q_eps", "latest_visible_single_quarter"),
])
def test_per_share_fields_preserve_amount_and_fixed_period(name, period):
    from thesistrace.data.fields import alpha_field_catalog

    field = next(f for f in alpha_field_catalog() if f.alpha.identifier == name)
    assert field.unit == field.source_unit == "CNY/share"
    assert field.report_period_selection == period
    result = resolver([fact("20200331", "2020-04-21", **{name: "2.5"})]).resolve_table(
        manifest_sha256="a" * 64, field_ids=(field.field_id,),
        sessions=("2020-04-21",), instrument_ids=("stock-1",),
    )
    assert result[field.field_id].to_pylist() == [2.5]


@pytest.mark.parametrize("name,raw,period", [
    ("salescash_to_or", ".15", "latest_visible_report_cumulative"),
    ("ocf_to_or", ".15", "latest_visible_report_cumulative"),
    ("ocf_to_opincome", ".15", "latest_visible_report_cumulative"),
    ("capitalized_to_da", ".15", "latest_visible_report_cumulative"),
    ("ocf_to_profit", "15", "latest_visible_report_cumulative"),
    ("q_salescash_to_or", "15", "latest_visible_single_quarter"),
    ("q_ocf_to_sales", "15", "latest_visible_single_quarter"),
    ("q_ocf_to_or", "15", "latest_visible_single_quarter"),
])
def test_cashflow_ratios_use_individually_verified_source_scale(name, raw, period):
    from thesistrace.data.fields import alpha_field_catalog

    field = next(f for f in alpha_field_catalog() if f.alpha.identifier == name)
    assert field.unit == "ratio"
    assert field.report_period_selection == period
    result = resolver([fact("20200331", "2020-04-21", **{name: raw})]).resolve_table(
        manifest_sha256="a" * 64, field_ids=(field.field_id,),
        sessions=("2020-04-21",), instrument_ids=("stock-1",),
    )
    assert result[field.field_id].to_pylist() == [.15]


@pytest.mark.parametrize("name,column,raw,expected,period", [
    ("net_profit_margin", "netprofit_margin", "15", .15, "report_cumulative"),
    ("gross_profit_margin", "grossprofit_margin", "25", .25, "report_cumulative"),
    ("q_net_profit_margin", "q_netprofit_margin", "15", .15, "single_quarter"),
    ("q_gross_profit_margin", "q_gsprofit_margin", "25", .25, "single_quarter"),
    ("debt_to_assets", "debt_to_assets", "60", .60, "report_end"),
    ("assets_to_eqt", "assets_to_eqt", "2.5", 2.5, "report_end"),
    ("cash_ratio", "cash_ratio", ".3459", .3459, "report_end"),
    ("ocf_to_debt", "ocf_to_debt", ".15", .15, "report_cumulative"),
    ("q_dtprofit_to_profit", "q_dtprofit_to_profit", "80", .8, "single_quarter"),
])
def test_profit_and_debt_fields_keep_source_identity_scale_and_latest_null(
    name, column, raw, expected, period,
):
    from thesistrace.data.fields import alpha_field_catalog

    field = next(f for f in alpha_field_catalog() if f.alpha.identifier == name)
    assert field.source_column == column
    assert field.source_lineage == f"tushare.fina_indicator.{column}"
    assert field.report_period_selection == f"latest_visible_{period}"
    result = resolver([
        fact("20200331", "2020-04-21", **{column: raw}),
        fact("20200630", "2020-08-03", **{column: None}),
    ]).resolve_table(
        manifest_sha256="a" * 64, field_ids=(field.field_id,),
        sessions=("2020-04-21", "2020-08-03"), instrument_ids=("stock-1",),
    )
    assert result[field.field_id].to_pylist() == [expected, None]


@pytest.mark.parametrize("name,column,period", [
    ("ocfps_yoy", "cfps_yoy", "report_yoy"),
    ("bps_ytd_growth", "bps_yoy", "report_year_start_growth"),
    ("assets_ytd_growth", "assets_yoy", "report_year_start_growth"),
    ("equity_parent_ytd_growth", "eqt_yoy", "report_year_start_growth"),
    ("equity_yoy", "equity_yoy", "report_yoy"),
    ("q_gr_yoy", "q_gr_yoy", "single_quarter_yoy"),
    ("q_gr_qoq", "q_gr_qoq", "single_quarter_qoq"),
])
def test_growth_fields_keep_source_comparison_period_and_negative_percentage(name, column, period):
    from thesistrace.data.fields import alpha_field_catalog

    field = next(f for f in alpha_field_catalog() if f.alpha.identifier == name)
    assert field.source_column == column
    assert field.report_period_selection == f"latest_visible_{period}"
    assert field.unit == "ratio"
    result = resolver([fact("20200331", "2020-04-21", **{column: "-25"})]).resolve_table(
        manifest_sha256="a" * 64, field_ids=(field.field_id,),
        sessions=("2020-04-21",), instrument_ids=("stock-1",),
    )
    assert result[field.field_id].to_pylist() == [-.25]


@pytest.mark.parametrize("name,column,unit,raw,expected,period", [
    ("interest_expense", "interst_income", "CNY", "1200", 1200, "report_cumulative"),
    ("tangible_asset", "tangible_asset", "CNY", "4500", 4500, "report_end"),
    ("q_dtprofit", "q_dtprofit", "CNY", "300", 300, "single_quarter"),
    ("invturn_days", "invturn_days", "day", "45", 45, "report_cumulative"),
    ("assets_turn", "assets_turn", "multiple", "1.2", 1.2, "report_cumulative"),
    ("ebit_to_interest", "ebit_to_interest", "multiple", "5.1586", 5.1586, "report_cumulative"),
    ("roa", "roa", "ratio", "8", .08, "report_cumulative"),
    ("roa_yearly", "roa_yearly", "ratio", "12", .12, "report_annualized"),
    ("q_npta", "q_npta", "ratio", "3", .03, "single_quarter"),
])
def test_amount_turnover_and_return_fields_preserve_distinct_units_and_periods(
    name, column, unit, raw, expected, period,
):
    from thesistrace.data.fields import alpha_field_catalog

    field = next(f for f in alpha_field_catalog() if f.alpha.identifier == name)
    assert field.source_column == column
    assert field.unit == unit
    assert field.report_period_selection == f"latest_visible_{period}"
    result = resolver([fact("20200331", "2020-04-21", **{column: raw})]).resolve_table(
        manifest_sha256="a" * 64, field_ids=(field.field_id,),
        sessions=("2020-04-21",), instrument_ids=("stock-1",),
    )
    assert result[field.field_id].to_pylist() == [expected]


def test_reported_research_investment_and_roe_keep_cumulative_period_and_quarter_null():
    from thesistrace.data.fields import alpha_field_catalog

    catalog = {f.alpha.identifier: f for f in alpha_field_catalog()}
    names = ("rd_exp", "roe_waa", "roe_avg")
    for name in names:
        assert catalog[name].report_period_selection == "latest_visible_report_cumulative"
    assert catalog["rd_exp"].unit == "CNY"
    assert catalog["roe_avg"].unit == catalog["roe_waa"].unit == "ratio"
    rows = [
        fact("20240630", "2024-08-12", rd_exp="418062861.85", roe_waa="17.63", roe_avg="17.62"),
        fact("20240930", "2024-11-01", rd_exp=None, roe_waa="26.09", roe_avg=None),
    ]
    result = resolver(rows).resolve_table(
        manifest_sha256="a" * 64, field_ids=tuple(catalog[name].field_id for name in names),
        sessions=("2024-08-12", "2024-11-01"), instrument_ids=("stock-1",),
    )
    assert result["financial.indicator.rd_exp"].to_pylist() == [418062861.85, None]
    assert result["financial.indicator.roe_waa"].to_pylist() == [.1763, .2609]
    assert result["financial.indicator.roe_avg"].to_pylist() == [.1762, None]


def test_free_cashflow_fields_read_supplier_values_without_reconstruction_or_share_scaling():
    from thesistrace.data.fields import alpha_field_catalog

    catalog = {f.alpha.identifier: f for f in alpha_field_catalog()}
    names = ("fcff", "fcfe", "fcff_ps", "fcfe_ps")
    for name in names:
        assert catalog[name].source_column == name
        assert catalog[name].report_period_selection == "latest_visible_report_cumulative"
    assert catalog["fcff"].unit == catalog["fcfe"].unit == "CNY"
    assert catalog["fcff_ps"].unit == catalog["fcfe_ps"].unit == "CNY/share"
    # Deliberately independent values: the reader must neither rebuild the flows
    # nor derive per-share values from the other requested fields.
    result = resolver([
        fact("20200331", "2020-04-21", fcff="-125000", fcfe="300000",
             fcff_ps="-2.5", fcfe_ps="4.25"),
        fact("20200630", "2020-08-03", fcff=None, fcfe=None,
             fcff_ps=None, fcfe_ps=None),
    ]).resolve_table(
        manifest_sha256="a" * 64, field_ids=tuple(catalog[n].field_id for n in names),
        sessions=("2020-04-21", "2020-08-03"), instrument_ids=("stock-1",),
    )
    for name, expected in zip(names, (-125000, 300000, -2.5, 4.25), strict=True):
        assert result[catalog[name].field_id].to_pylist() == [expected, None]

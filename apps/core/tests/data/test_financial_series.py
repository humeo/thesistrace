from __future__ import annotations

import pyarrow as pa
import pytest

from thesistrace.data.fields import FINANCIAL_FIELDS, authorable_fields
from thesistrace.data.financial_series import (
    FinancialSeriesError,
    FinancialSeriesResolver,
)


class RecordingReader:
    def __init__(self, rows: dict[str, list[dict[str, object]]]) -> None:
        self.rows = rows
        self.requests: list[tuple[str, tuple[str, ...], str, frozenset[str]]] = []

    def read_financial_rows(
        self,
        manifest_sha256: str,
        endpoint: str,
        source_columns: tuple[str, ...],
        sessions: tuple[str, ...],
        instrument_ids: frozenset[str],
    ) -> tuple[dict[str, object], ...]:
        assert manifest_sha256 == "a" * 64
        self.requests.append((endpoint, source_columns, sessions[-1], instrument_ids))
        return tuple(self.rows.get(endpoint, ()))

    def read_financial_table(
        self,
        manifest_sha256: str,
        endpoint: str,
        source_columns: tuple[str, ...],
        sessions: tuple[str, ...],
        instrument_ids: frozenset[str],
    ) -> pa.Table:
        assert manifest_sha256 == "a" * 64
        self.requests.append((endpoint, source_columns, sessions[-1], instrument_ids))
        return pa.Table.from_pylist(
            self.rows.get(endpoint, ()),
            schema=pa.schema([pa.field(column, pa.string()) for column in source_columns]),
        )


class ColumnarOnlyReader(RecordingReader):
    def read_financial_rows(
        self,
        manifest_sha256: str,
        endpoint: str,
        source_columns: tuple[str, ...],
        sessions: tuple[str, ...],
        instrument_ids: frozenset[str],
    ) -> tuple[dict[str, object], ...]:
        del manifest_sha256, endpoint, source_columns, sessions, instrument_ids
        raise AssertionError("columnar Research used the row-oriented financial reader")


def test_catalog_preserves_six_fields_and_adds_sixteen_statement_stocks() -> None:
    assert [field.field_id for field in FINANCIAL_FIELDS[:6]] == [
        "financial.income.total_revenue.latest_fy",
        "financial.income.net_profit_parent.latest_fy",
        "financial.cashflow.operating_cash_flow.latest_fy",
        "financial.balance_sheet.total_assets.latest_reported",
        "financial.balance_sheet.total_liabilities.latest_reported",
        "financial.balance_sheet.equity_parent.latest_reported",
    ]
    assert [
        field.alpha.identifier for field in FINANCIAL_FIELDS[:6] if field.alpha is not None
    ] == [
        "revenue",
        "net_profit",
        "operating_cash_flow",
        "assets",
        "liabilities",
        "equity",
    ]
    assert len(FINANCIAL_FIELDS) == 41
    assert {
        (field.alpha.identifier, field.source_endpoint, field.source_column)
        for field in FINANCIAL_FIELDS[6:22] if field.alpha is not None
    } == {
        ("monetary_funds", "balancesheet", "money_cap"),
        ("accounts_receivable", "balancesheet", "accounts_receiv"),
        ("notes_receivable", "balancesheet", "notes_receiv"),
        ("other_receivables", "balancesheet", "oth_receiv"),
        ("prepayments", "balancesheet", "prepayment"),
        ("inventories", "balancesheet", "inventories"),
        ("accounts_payable", "balancesheet", "acct_payable"),
        ("contract_assets", "balancesheet", "contract_assets"),
        ("contract_liabilities", "balancesheet", "contract_liab"),
        ("goodwill", "balancesheet", "goodwill"),
        ("short_term_borrowings", "balancesheet", "st_borr"),
        ("long_term_borrowings", "balancesheet", "lt_borr"),
        ("bonds_payable", "balancesheet", "bond_payable"),
        ("noncurrent_liabilities_due_1y", "balancesheet", "non_cur_liab_due_1y"),
        ("other_equity_instruments", "balancesheet", "oth_eqt_tools"),
        ("cash_equivalents", "cashflow", "c_cash_equ_end_period"),
    }
    assert all(field.family_id == "equity.financial_pit" for field in FINANCIAL_FIELDS)
    assert all(field.physical_type == "decimal" for field in FINANCIAL_FIELDS)
    assert all(field.unit == "CNY" for field in FINANCIAL_FIELDS)
    assert all(
        field.availability == "next_research_session_after_source_publication"
        for field in FINANCIAL_FIELDS
    )
    assert all(field.reporting_scope == "report_type_1_consolidated" for field in FINANCIAL_FIELDS)
    assert all(
        field.missingness == "missing_when_no_visible_eligible_fact" for field in FINANCIAL_FIELDS
    )
    assert all(field.source_lineage.startswith("tushare.") for field in FINANCIAL_FIELDS)
    assert all(
        field.applicable_company_types == (
            ("1", "2", "4") if field.source_column == "contract_liab" else ("1", "2", "3", "4")
        ) for field in FINANCIAL_FIELDS
    )
    assert {field.report_period_selection for field in FINANCIAL_FIELDS} == {
        "latest_visible_full_year",
        "latest_visible_quarterly_or_annual",
        "latest_visible_ttm",
    }
    assert set(FINANCIAL_FIELDS) <= set(authorable_fields())


def test_resolves_annual_and_latest_reported_fields_without_fallback() -> None:
    instruments = frozenset({"equity:000001.SZ", "equity:000002.SZ"})
    reader = RecordingReader(
        {
            "income": [
                _row("equity:000001.SZ", "20081231", "2009-04-27", revenue="80"),
                _row("equity:000001.SZ", "20091231", "2010-04-21", revenue="100"),
                _row("equity:000001.SZ", "20091231", "2010-04-22", revenue="101"),
                _row("equity:000001.SZ", "20100331", "2010-04-20", revenue="25"),
                _row(
                    "equity:000001.SZ",
                    "20101231",
                    "2011-04-25",
                    revenue=None,
                    profit="9",
                ),
                _row(
                    "equity:000002.SZ",
                    "20091231",
                    "2010-04-21",
                    company_type="4",
                    revenue="200",
                    profit="20",
                ),
                _row(
                    "equity:000002.SZ",
                    "20101231",
                    "2011-04-25",
                    report_type="2",
                    company_type="4",
                    revenue="999",
                    profit="999",
                ),
            ],
            "cashflow": [
                _row("equity:000001.SZ", "20091231", "2010-04-21", cashflow="30"),
            ],
            "balancesheet": [
                _row("equity:000001.SZ", "20091231", "2010-04-21", assets="500"),
                _row(
                    "equity:000001.SZ",
                    "20100331",
                    "2010-04-22",
                    assets="550",
                    liabilities=None,
                    equity="300",
                ),
            ],
        }
    )
    resolver = FinancialSeriesResolver(reader)
    sessions = ("2010-01-04", "2010-04-20", "2010-04-21", "2010-04-22", "2011-04-25")

    values = resolver.resolve(
        manifest_sha256="a" * 64,
        field_ids=tuple(field.field_id for field in FINANCIAL_FIELDS),
        sessions=sessions,
        instrument_ids=tuple(sorted(instruments)),
    )

    revenue = values["financial.income.total_revenue.latest_fy"]
    assert revenue[("2010-01-04", "equity:000001.SZ")] == "80"
    assert revenue[("2010-04-21", "equity:000001.SZ")] == "100"
    assert revenue[("2010-04-22", "equity:000001.SZ")] == "101"
    assert ("2011-04-25", "equity:000001.SZ") not in revenue
    assert revenue[("2011-04-25", "equity:000002.SZ")] == "200"
    assert (
        values["financial.cashflow.operating_cash_flow.latest_fy"][
            ("2011-04-25", "equity:000001.SZ")
        ]
        == "30"
    )
    assets = values["financial.balance_sheet.total_assets.latest_reported"]
    assert assets[("2010-04-21", "equity:000001.SZ")] == "500"
    assert assets[("2010-04-22", "equity:000001.SZ")] == "550"
    assert ("2010-04-22", "equity:000001.SZ") not in values[
        "financial.balance_sheet.total_liabilities.latest_reported"
    ]
    assert (
        values["financial.balance_sheet.equity_parent.latest_reported"][
            ("2010-04-22", "equity:000001.SZ")
        ]
        == "300"
    )
    assert len(reader.requests) == 3
    assert all(
        request[2] == sessions[-1] and request[3] == instruments for request in reader.requests
    )
    requested_columns = {endpoint: columns for endpoint, columns, _through, _ids in reader.requests}
    assert set(requested_columns["income"]) >= {"total_revenue", "n_income_attr_p"}
    assert "n_cashflow_act" in requested_columns["cashflow"]
    assert set(requested_columns["balancesheet"]) >= {
        "total_assets",
        "total_liab",
        "total_hldr_eqy_exc_min_int",
    }


def test_columnar_financial_resolution_keeps_pit_selection_in_arrow() -> None:
    reader = ColumnarOnlyReader(
        {
            "income": [
                _row("equity:000001.SZ", "20091231", "2010-04-21", revenue="100"),
                _row("equity:000001.SZ", "20091231", "2010-04-22", revenue="101"),
                _row("equity:000001.SZ", "20100331", "2010-04-20", revenue="25"),
                _row("equity:000002.SZ", "20091231", "2010-04-21", revenue="200"),
            ]
        }
    )

    table = FinancialSeriesResolver(reader).resolve_table(
        manifest_sha256="a" * 64,
        field_ids=("financial.income.total_revenue.latest_fy",),
        sessions=("2010-04-20", "2010-04-21", "2010-04-22"),
        instrument_ids=("equity:000001.SZ", "equity:000002.SZ"),
    )

    assert table.to_pydict() == {
        "session": [
            "2010-04-20",
            "2010-04-20",
            "2010-04-21",
            "2010-04-21",
            "2010-04-22",
            "2010-04-22",
        ],
        "instrument_id": [
            "equity:000001.SZ",
            "equity:000002.SZ",
            "equity:000001.SZ",
            "equity:000002.SZ",
            "equity:000001.SZ",
            "equity:000002.SZ",
        ],
        "financial.income.total_revenue.latest_fy": [None, None, "100", "200", "101", "200"],
    }


@pytest.mark.parametrize("company_type", ["1", "2", "3", "4"])
def test_all_supported_company_types_resolve_without_promising_non_null(
    company_type: str,
) -> None:
    reader = RecordingReader(
        {
            "income": [
                _row(
                    "equity:000001.SZ",
                    "20091231",
                    "2010-04-21",
                    company_type=company_type,
                    revenue="10",
                )
            ]
        }
    )

    values = FinancialSeriesResolver(reader).resolve(
        manifest_sha256="a" * 64,
        field_ids=("financial.income.total_revenue.latest_fy",),
        sessions=("2010-04-20", "2010-04-21"),
        instrument_ids=("equity:000001.SZ",),
    )

    assert values["financial.income.total_revenue.latest_fy"] == {
        ("2010-04-21", "equity:000001.SZ"): "10"
    }


def test_rejects_unapproved_fields_and_noncanonical_request_axes() -> None:
    resolver = FinancialSeriesResolver(RecordingReader({}))

    with pytest.raises(FinancialSeriesError, match="FINANCIAL_FIELD_UNSUPPORTED"):
        resolver.resolve(
            manifest_sha256="a" * 64,
            field_ids=("revenue",),
            sessions=("2010-01-04",),
            instrument_ids=("equity:000001.SZ",),
        )
    with pytest.raises(FinancialSeriesError, match="FINANCIAL_SERIES_REQUEST_INVALID"):
        resolver.resolve(
            manifest_sha256="a" * 64,
            field_ids=("financial.income.total_revenue.latest_fy",),
            sessions=("2010-01-05", "2010-01-04"),
            instrument_ids=("equity:000001.SZ",),
        )


def _row(
    instrument_id: str,
    report_period: str,
    available_session: str,
    *,
    report_type: str = "1",
    company_type: str = "1",
    revenue: str | None = None,
    profit: str | None = None,
    cashflow: str | None = None,
    assets: str | None = None,
    liabilities: str | None = None,
    equity: str | None = None,
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "source_report_period": report_period,
        "source_report_type": report_type,
        "source_company_type": company_type,
        "effective_available_session": available_session,
        "availability_status": "available",
        "first_observed_at": f"{available_session}T08:00:00+00:00",
        "source_published_date": available_session.replace("-", ""),
        "source_row_sha256": (report_period + available_session).encode().hex().ljust(64, "0")[:64],
        "update_flag": "1",
        "total_revenue": revenue,
        "n_income_attr_p": profit,
        "n_cashflow_act": cashflow,
        "total_assets": assets,
        "total_liab": liabilities,
        "total_hldr_eqy_exc_min_int": equity,
    }


@pytest.mark.parametrize("columnar", [False, True])
def test_cash_equivalents_use_latest_quarter_without_annual_flow_fallback(columnar: bool) -> None:
    instrument = "equity:000001.SZ"
    cash_field = "financial.cashflow.cash_equivalents.latest_reported"
    flow_field = "financial.cashflow.operating_cash_flow.latest_fy"
    rows = [
        {
            **_row(instrument, "20091231", "2010-04-20", cashflow="100"),
            "c_cash_equ_end_period": "40",
        },
        {
            **_row(instrument, "20100331", "2010-04-21", cashflow="15"),
            "c_cash_equ_end_period": "60",
        },
        {
            **_row(instrument, "20100630", "2010-08-02", cashflow="35"),
            "c_cash_equ_end_period": None,
        },
    ]
    reader = (ColumnarOnlyReader if columnar else RecordingReader)({"cashflow": rows})
    resolver = FinancialSeriesResolver(reader)
    sessions = ("2010-04-20", "2010-04-21", "2010-08-02")
    request = {
        "manifest_sha256": "a" * 64,
        "field_ids": (cash_field, flow_field),
        "sessions": sessions,
        "instrument_ids": (instrument,),
    }
    if columnar:
        result = resolver.resolve_table(**request).to_pydict()
        assert result[cash_field] == ["40", "60", None]
        assert result[flow_field] == ["100", "100", "100"]
    else:
        result = resolver.resolve(**request)
        assert [result[cash_field].get((session, instrument)) for session in sessions] == [
            "40", "60", None,
        ]
        assert [result[flow_field][(session, instrument)] for session in sessions] == [
            "100", "100", "100",
        ]
    assert reader.requests[0][0] == "cashflow"
    assert "total_assets" not in reader.requests[0][1]


@pytest.mark.parametrize("columnar", [False, True])
def test_contract_liabilities_exclude_insurance_without_hiding_other_stocks(columnar: bool) -> None:
    instrument = "equity:601318.SH"
    contract = "financial.balance_sheet.contract_liabilities.latest_reported"
    assets = "financial.balance_sheet.total_assets.latest_reported"
    rows = [
        {**_row(instrument, "20091231", "2010-04-20", assets="100", company_type="1"),
         "contract_liab": "10"},
        {**_row(instrument, "20100331", "2010-04-21", assets="200", company_type="3"),
         "contract_liab": "150"},
    ]
    reader = (ColumnarOnlyReader if columnar else RecordingReader)({"balancesheet": rows})
    resolver = FinancialSeriesResolver(reader)
    sessions = ("2010-04-20", "2010-04-21")
    request = {
        "manifest_sha256": "a" * 64,
        "field_ids": (contract, assets),
        "sessions": sessions,
        "instrument_ids": (instrument,),
    }
    if columnar:
        result = resolver.resolve_table(**request).to_pydict()
        assert result[contract] == ["10", None]
        assert result[assets] == ["100", "200"]
    else:
        result = resolver.resolve(**request)
        assert [result[contract].get((session, instrument)) for session in sessions] == ["10", None]
        assert [result[assets].get((session, instrument)) for session in sessions] == ["100", "200"]


@pytest.mark.parametrize("columnar", [False, True])
def test_ttm_recomputes_visible_components_without_changing_annual_flow(columnar: bool) -> None:
    instrument = "equity:000001.SZ"
    ttm = "financial.income.total_revenue.ttm"
    annual = "financial.income.total_revenue.latest_fy"
    rows = [
        _row(instrument, "20090331", "2010-04-20", revenue="50"),
        _row(instrument, "20091231", "2010-04-20", revenue="100"),
        _row(instrument, "20100331", "2010-04-21", revenue="60"),
        _row(instrument, "20091231", "2010-04-22", revenue="105"),
        _row(instrument, "20100630", "2010-08-02", revenue=None),
    ]
    sessions = ("2010-04-20", "2010-04-21", "2010-04-22", "2010-08-02")
    reader = (ColumnarOnlyReader if columnar else RecordingReader)({"income": rows})
    resolver = FinancialSeriesResolver(reader)
    request = dict(manifest_sha256="a" * 64, field_ids=(ttm, annual),
                   sessions=sessions, instrument_ids=(instrument,))
    expected = {ttm: ["100", "110", "115", None], annual: ["100", "100", "105", "105"]}
    if columnar:
        table = resolver.resolve_table(**request)
        assert {name: table[name].to_pylist() for name in expected} == expected
        assert table[f"ttm_window_end:{ttm}"].to_pylist() == [
            "20091231", "20100331", "20100331", None,
        ]
    else:
        resolved = resolver.resolve(**request)
        assert {name: [resolved[name].get((day, instrument)) for day in sessions]
                for name in expected} == expected


@pytest.mark.parametrize("columnar", [False, True])
@pytest.mark.parametrize("gap", ["annual", "same_quarter", "target_value", "scope"])
def test_ttm_missing_components_do_not_reuse_previous_value(columnar: bool, gap: str) -> None:
    instrument = "equity:000001.SZ"
    ttm = "financial.income.total_revenue.ttm"
    rows = [
        _row(instrument, "20091231", "2010-04-20", revenue="100"),
        _row(instrument, "20090331", "2010-04-20", revenue="50"),
        _row(instrument, "20100331", "2010-04-21", revenue="60"),
    ]
    if gap == "annual":
        rows.pop(0)
    elif gap == "same_quarter":
        rows.pop(1)
    elif gap == "target_value":
        rows[2]["total_revenue"] = None
    else:
        rows[1]["source_company_type"] = "2"
    reader = (ColumnarOnlyReader if columnar else RecordingReader)({"income": rows})
    resolver = FinancialSeriesResolver(reader)
    request = dict(manifest_sha256="a" * 64, field_ids=(ttm,),
                   sessions=("2010-04-21",), instrument_ids=(instrument,))
    if columnar:
        assert resolver.resolve_table(**request)[ttm].to_pylist() == [None]
    else:
        assert resolver.resolve(**request) == {ttm: {}}

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thesistrace.alpha_language import alpha_language
from thesistrace.data.fields import MARKET_FIELDS, alpha_field_catalog
from thesistrace.entrypoints.alpha_http import install_alpha_http


def _client(*, available_field_ids: frozenset[str] = frozenset(
    field.field_id for field in MARKET_FIELDS
)) -> TestClient:
    app = FastAPI()
    install_alpha_http(
        app,
        catalog_snapshot=lambda _request: alpha_language.catalog(
            available_field_ids=available_field_ids,
            generation_manifest_sha256="a" * 64,
        ),
    )
    return TestClient(app)


def test_alpha_catalog_is_public_and_contains_no_execution_implementation() -> None:
    with _client() as client:
        response = client.get("/api/alpha/catalog")

    assert response.status_code == 200
    catalog = response.json()
    market_fields = {
        field["identifier"]: field["field_id"]
        for field in catalog["fields"]
        if field["family_id"] == "equity.eod_price"
    }
    assert market_fields == {
        "open": "price.open.adjusted",
        "high": "price.high.adjusted",
        "low": "price.low.adjusted",
        "close": "price.close.adjusted",
        "close_raw": "price.close.raw",
        "volume": "market.volume.shares",
        "amount": "market.turnover.cny",
    }
    assert not set(market_fields) & {
        "open_adj",
        "high_adj",
        "low_adj",
        "close_adj",
        "volume_shares",
        "turnover_amount_cny",
    }
    assert "ts_mean" in {builtin["identifier"] for builtin in catalog["builtins"]}
    assert "evaluator" not in str(catalog).lower()
    assert "release" not in str(catalog).lower()


def test_alpha_catalog_exposes_financial_fields_and_cross_sectional_rank() -> None:
    with _client(
        available_field_ids=frozenset(field.field_id for field in alpha_field_catalog())
    ) as client:
        catalog = client.get("/api/alpha/catalog").json()

    financial = {
        field["identifier"]: field
        for field in catalog["fields"]
        if field["family_id"] == "equity.financial_pit"
    }
    assert set(financial) == {
        "revenue",
        "net_profit",
        "operating_cash_flow",
        "assets",
        "liabilities",
        "equity",
        "monetary_funds",
        "accounts_receivable",
        "notes_receivable",
        "other_receivables",
        "prepayments",
        "inventories",
        "accounts_payable",
        "contract_assets",
        "contract_liabilities",
        "goodwill",
        "short_term_borrowings",
        "long_term_borrowings",
        "bonds_payable",
        "noncurrent_liabilities_due_1y",
        "other_equity_instruments",
        "cash_equivalents",
        "cash_paid_capex_ttm",
        "cash_received_sales_ttm",
        "cash_paid_goods_ttm",
        "cash_received_asset_disposals_ttm",
        "cash_paid_acquisitions_ttm",
        "cash_paid_investments_ttm",
        "cash_received_borrowing_ttm",
        "cash_paid_debt_repayment_ttm",
        "operating_revenue_ttm",
        "consolidated_net_profit_ttm",
        "operating_cost_ttm",
        "rd_expense_ttm",
        "investment_income_ttm",
        "fair_value_gain_ttm",
        "nonoperating_income_ttm",
        "nonoperating_expense_ttm",
        "revenue_ttm",
        "net_profit_ttm",
        "operating_cash_flow_ttm",
    }
    assert {
        identifier: field["field_id"] for identifier, field in financial.items()
    } == {
        "revenue": "financial.income.total_revenue.latest_fy",
        "net_profit": "financial.income.net_profit_parent.latest_fy",
        "operating_cash_flow": (
            "financial.cashflow.operating_cash_flow.latest_fy"
        ),
        "assets": (
            "financial.balance_sheet.total_assets.latest_reported"
        ),
        "liabilities": (
            "financial.balance_sheet.total_liabilities.latest_reported"
        ),
        "equity": (
            "financial.balance_sheet.equity_parent.latest_reported"
        ),
        "monetary_funds": (
            "financial.balance_sheet.monetary_funds.latest_reported"
        ),
        "accounts_receivable": (
            "financial.balance_sheet.accounts_receivable.latest_reported"
        ),
        "notes_receivable": (
            "financial.balance_sheet.notes_receivable.latest_reported"
        ),
        "other_receivables": (
            "financial.balance_sheet.other_receivables.latest_reported"
        ),
        "prepayments": (
            "financial.balance_sheet.prepayments.latest_reported"
        ),
        "inventories": (
            "financial.balance_sheet.inventories.latest_reported"
        ),
        "accounts_payable": (
            "financial.balance_sheet.accounts_payable.latest_reported"
        ),
        "contract_assets": (
            "financial.balance_sheet.contract_assets.latest_reported"
        ),
        "contract_liabilities": (
            "financial.balance_sheet.contract_liabilities.latest_reported"
        ),
        "goodwill": (
            "financial.balance_sheet.goodwill.latest_reported"
        ),
        "short_term_borrowings": (
            "financial.balance_sheet.short_term_borrowings.latest_reported"
        ),
        "long_term_borrowings": (
            "financial.balance_sheet.long_term_borrowings.latest_reported"
        ),
        "bonds_payable": (
            "financial.balance_sheet.bonds_payable.latest_reported"
        ),
        "noncurrent_liabilities_due_1y": (
            "financial.balance_sheet.noncurrent_liabilities_due_1y.latest_reported"
        ),
        "other_equity_instruments": (
            "financial.balance_sheet.other_equity_instruments.latest_reported"
        ),
        "cash_equivalents": (
            "financial.cashflow.cash_equivalents.latest_reported"
        ),
        "cash_paid_capex_ttm": (
            "financial.cashflow.cash_paid_capex.ttm"
        ),
        "cash_received_sales_ttm": (
            "financial.cashflow.cash_received_sales.ttm"
        ),
        "cash_paid_goods_ttm": (
            "financial.cashflow.cash_paid_goods.ttm"
        ),
        "cash_received_asset_disposals_ttm": (
            "financial.cashflow.cash_received_asset_disposals.ttm"
        ),
        "cash_paid_acquisitions_ttm": (
            "financial.cashflow.cash_paid_acquisitions.ttm"
        ),
        "cash_paid_investments_ttm": (
            "financial.cashflow.cash_paid_investments.ttm"
        ),
        "cash_received_borrowing_ttm": (
            "financial.cashflow.cash_received_borrowing.ttm"
        ),
        "cash_paid_debt_repayment_ttm": (
            "financial.cashflow.cash_paid_debt_repayment.ttm"
        ),
        "operating_revenue_ttm": (
            "financial.income.operating_revenue.ttm"
        ),
        "consolidated_net_profit_ttm": (
            "financial.income.consolidated_net_profit.ttm"
        ),
        "operating_cost_ttm": (
            "financial.income.operating_cost.ttm"
        ),
        "rd_expense_ttm": (
            "financial.income.rd_expense.ttm"
        ),
        "investment_income_ttm": (
            "financial.income.investment_income.ttm"
        ),
        "fair_value_gain_ttm": (
            "financial.income.fair_value_gain.ttm"
        ),
        "nonoperating_income_ttm": (
            "financial.income.nonoperating_income.ttm"
        ),
        "nonoperating_expense_ttm": (
            "financial.income.nonoperating_expense.ttm"
        ),
        "revenue_ttm": (
            "financial.income.total_revenue.ttm"
        ),
        "net_profit_ttm": (
            "financial.income.net_profit_parent.ttm"
        ),
        "operating_cash_flow_ttm": (
            "financial.cashflow.operating_cash_flow.ttm"
        ),
    }
    assert all(field["report_period_selection"] for field in financial.values())
    assert all(
        field["applicable_company_types"] == (
            ["1", "2", "4"] if identifier == "contract_liabilities" else ["1", "2", "3", "4"]
        )
        for identifier, field in financial.items()
    )
    assert all(field["example"] for field in financial.values())
    assert "rank" in {builtin["identifier"] for builtin in catalog["builtins"]}


def test_alpha_catalog_hides_financial_fields_until_the_current_head_is_ready() -> None:
    with _client() as client:
        catalog = client.get("/api/alpha/catalog").json()

    assert {field["family_id"] for field in catalog["fields"]} == {"equity.eod_price"}
    assert "rank" in {builtin["identifier"] for builtin in catalog["builtins"]}


def test_alpha_diagnostics_is_non_mutating_for_valid_and_invalid_formulae() -> None:
    with _client() as client:
        valid = client.post(
            "/api/alpha/diagnostics",
            json={"source": "ts_mean(close, 20)"},
        )
        invalid = client.post(
            "/api/alpha/diagnostics",
            json={"source": "ts_mean(closes, 20)"},
        )

    assert valid.status_code == 200
    assert valid.json() == {"valid": True, "diagnostics": []}
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert invalid.json()["diagnostics"][0]["code"] == "UNKNOWN_IDENTIFIER"
    assert invalid.json()["diagnostics"][0]["details"] == {
        "kind": "identifier",
        "expected": sorted(
            [field.identifier for field in alpha_language.catalog().fields]
            + [builtin.identifier for builtin in alpha_language.catalog().builtins]
        ),
        "actual": "closes",
    }
    assert invalid.json()["diagnostics"][0]["range"] == {
        "start": {"offset": 8, "line": 1, "column": 9},
        "end": {"offset": 14, "line": 1, "column": 15},
    }


def test_alpha_diagnostics_rejects_request_shape_errors() -> None:
    with _client() as client:
        missing = client.post("/api/alpha/diagnostics", json={})
        extra = client.post(
            "/api/alpha/diagnostics",
            json={"source": "close", "release_id": "alpha-v2"},
        )

    assert missing.status_code == 422
    assert extra.status_code == 422


def test_alpha_http_catalog_keeps_a_partial_family_partial() -> None:
    with _client(
        available_field_ids=frozenset({"financial.balance_sheet.total_assets.latest_reported"})
    ) as client:
        catalog = client.get("/api/alpha/catalog").json()

    assert [field["identifier"] for field in catalog["fields"]] == ["assets"]
    assert catalog["generation_manifest_sha256"] == "a" * 64


def test_daily_basic_http_catalog_preserves_family_units_and_actual_availability() -> None:
    with _client(available_field_ids=frozenset(
        field.field_id for field in alpha_field_catalog()
    )) as client:
        result = client.get("/api/alpha/catalog")
    assert result.status_code == 200
    daily = {field["identifier"]: field for field in result.json()["fields"]
             if field["family_id"] == "equity.daily_basic"}
    assert set(daily) == {
        "total_mv", "circ_mv", "total_share", "float_share", "free_share",
        "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm",
        "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
    }
    assert daily["pe"]["field_id"] == "market.valuation.pe"
    assert daily["pe"]["unit"] == "multiple"
    assert daily["turnover_rate"]["unit"] == "ratio"
    assert all(field["research_category"] == "market" for field in daily.values())
    with _client() as client:
        prices = client.get("/api/alpha/catalog").json()
    assert not any(field["family_id"] == "equity.daily_basic" for field in prices["fields"])

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thesistrace.alpha_language import alpha_language
from thesistrace.entrypoints.alpha_http import install_alpha_http


def _client(*, financial_authoring_ready: bool = False) -> TestClient:
    app = FastAPI()
    install_alpha_http(
        app,
        financial_authoring_ready=lambda _request: financial_authoring_ready,
    )
    return TestClient(app)


def test_alpha_catalog_is_public_and_contains_no_execution_implementation() -> None:
    with _client() as client:
        response = client.get("/api/alpha/catalog")

    assert response.status_code == 200
    catalog = response.json()
    assert "close_adj" in {field["identifier"] for field in catalog["fields"]}
    assert "ts_mean" in {builtin["identifier"] for builtin in catalog["builtins"]}
    assert "evaluator" not in str(catalog).lower()
    assert "release" not in str(catalog).lower()


def test_alpha_catalog_exposes_financial_fields_and_cross_sectional_rank() -> None:
    with _client(financial_authoring_ready=True) as client:
        catalog = client.get("/api/alpha/catalog").json()

    financial = {
        field["identifier"]: field
        for field in catalog["fields"]
        if field["family_id"] == "equity.financial_pit"
    }
    assert set(financial) == {
        "total_revenue_latest_fy",
        "net_profit_parent_latest_fy",
        "operating_cash_flow_latest_fy",
        "total_assets_latest_reported",
        "total_liabilities_latest_reported",
        "equity_parent_latest_reported",
    }
    assert all(field["report_period_selection"] for field in financial.values())
    assert all(
        field["applicable_company_types"] == ["1", "2", "3", "4"]
        for field in financial.values()
    )
    assert all(field["example"] for field in financial.values())
    assert "cs_rank" in {builtin["identifier"] for builtin in catalog["builtins"]}


def test_alpha_catalog_hides_financial_fields_until_the_current_head_is_ready() -> None:
    with _client() as client:
        catalog = client.get("/api/alpha/catalog").json()

    assert {field["family_id"] for field in catalog["fields"]} == {"equity.eod_price"}
    assert "cs_rank" in {builtin["identifier"] for builtin in catalog["builtins"]}


def test_alpha_diagnostics_is_non_mutating_for_valid_and_invalid_formulae() -> None:
    with _client() as client:
        valid = client.post(
            "/api/alpha/diagnostics",
            json={"source": "ts_mean(close_adj, 20)"},
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
            json={"source": "close_adj", "release_id": "alpha-v2"},
        )

    assert missing.status_code == 422
    assert extra.status_code == 422

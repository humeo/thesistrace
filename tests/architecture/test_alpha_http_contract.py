from fastapi import FastAPI
from fastapi.testclient import TestClient

from thesistrace.entrypoints.alpha_http import install_alpha_http


def _client() -> TestClient:
    app = FastAPI()
    install_alpha_http(app)
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
        "expected": [
            "abs",
            "close_adj",
            "delta",
            "high_adj",
            "lag",
            "log",
            "low_adj",
            "open_adj",
            "pct_change",
            "sign",
            "ts_max",
            "ts_mean",
            "ts_min",
            "ts_std",
            "ts_sum",
            "turnover_amount_cny",
            "volume_shares",
        ],
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

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace.data.fields import MARKET_FIELDS
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_kernel.alpha_expression import operator_catalog


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_authoring_options_and_saved_tree_use_authoritative_stable_ids() -> None:
    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/definitions/authoring-options")

        assert response.status_code == 200
        options = response.json()
        assert options["fields"] == [
            {
                "field_id": field.field_id,
                "definition": field.definition,
                "unit": field.unit,
                "result_type": "numeric",
            }
            for field in MARKET_FIELDS
        ]
        assert options["operators"] == operator_catalog()["operators"]
        assert options["universes"] == ["top300", "top1000", "top2000", "top3000"]
        assert options["neutralizations"] == ["none", "industry"]
        assert options["holdings_count"] == {"minimum": 1, "maximum": 100}
        assert options["rebalance_every_sessions"] == {"minimum": 1, "maximum": 20}
        assert "start_date" not in options
        assert "end_date" not in options

        serialized_options = str(options)
        for private_name in (
            "evaluation_name",
            "field_bindings",
            "dataset_release",
            "strategy_kind",
            "initial_cash",
            "execution",
            "costs",
            "risk_free_rate",
            "numeric_contract",
            "semantic_version",
        ):
            assert private_name not in serialized_options

        alpha = {
            "operator_id": "ts_mean",
            "operands": [
                {"field_id": "price.close.adjusted"},
                {"literal": 20},
            ],
        }
        created = client.post(
            "/api/definitions",
            json={
                "alpha": alpha,
                "universe": "top1000",
                "neutralization": "industry",
                "holdings_count": 30,
                "rebalance_every_sessions": 5,
            },
        )

        assert created.status_code == 201
        definition = created.json()
        assert definition["alpha"] == alpha
        assert client.get(f"/api/definitions/{definition['id']}").json() == definition

        rejected = client.post(
            "/api/definitions",
            json={"dataset_release": "release_user_selected"},
        )
        assert rejected.status_code == 422

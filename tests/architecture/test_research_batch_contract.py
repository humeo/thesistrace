from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from thesistrace.entrypoints.http import create_app
from thesistrace.research_batch import ResearchBatchAdmissionCommand

ROOT = Path(__file__).resolve().parents[2]
ADMISSION = TypeAdapter(ResearchBatchAdmissionCommand)


def _common() -> dict[str, object]:
    return {
        "request_id": "batch-request-1",
        "start_date": "2026-06-01",
        "end_date": "2026-07-31",
        "universe": "top300",
        "neutralization": "industry",
    }


def test_factor_batch_contract_is_explicit_ordered_and_bounded() -> None:
    command = ADMISSION.validate_python(
        {
            **_common(),
            "batch_kind": "factor_evaluation",
            "factors": [
                {
                    "item_key": f"factor-{ordinal}",
                    "name": f"Factor {ordinal}",
                    "formula": f"rank(close) + {ordinal}",
                    "hypothesis": None,
                }
                for ordinal in range(20)
            ],
        }
    )
    assert [item.item_key for item in command.factors] == [
        f"factor-{ordinal}" for ordinal in range(20)
    ]

    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {**command.model_dump(mode="json"), "factors": []}
        )

    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {
                **_common(),
                "batch_kind": "factor_evaluation",
                "factors": [{"item_key": "   ", "formula": "rank(close)"}],
            }
        )
    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {
                **command.model_dump(mode="json"),
                "factors": [
                    *command.model_dump(mode="json")["factors"],
                    {"item_key": "factor-21", "formula": "rank(close)"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {
                **_common(),
                "batch_kind": "factor_evaluation",
                "factors": [
                    {
                        "item_key": "factor-1",
                        "formula": "rank(close)",
                        "holdings_count": 10,
                    }
                ],
            }
        )


def test_strategy_sweep_has_one_shared_alpha_and_one_to_twenty_parameter_items() -> None:
    command = ADMISSION.validate_python(
        {
            **_common(),
            "batch_kind": "strategy_sweep",
            "alpha": {"formula": "rank(close)", "hypothesis": "shared"},
            "strategies": [
                {
                    "item_key": f"strategy-{ordinal}",
                    "holdings_count": ordinal,
                    "rebalance_every_sessions": ordinal,
                }
                for ordinal in range(1, 21)
            ],
        }
    )
    assert command.alpha.formula == "rank(close)"
    assert len(command.strategies) == 20
    assert not hasattr(command.alpha, "item_key")

    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {**command.model_dump(mode="json"), "batch_kind": "mixed"}
        )
    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {**command.model_dump(mode="json"), "strategies": []}
        )
    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {
                **command.model_dump(mode="json"),
                "strategies": [
                    *command.model_dump(mode="json")["strategies"],
                    {
                        "item_key": "strategy-21",
                        "holdings_count": 21,
                        "rebalance_every_sessions": 1,
                    },
                ],
            }
        )
    with pytest.raises(ValidationError):
        ADMISSION.validate_python(
            {
                **_common(),
                "alpha": {"formula": "rank(close)"},
                "strategies": command.model_dump(mode="json")["strategies"],
            }
        )


def test_batch_backend_surface_has_no_delete_or_frontend_route() -> None:
    routes = {
        (method.lower(), route.path)
        for route in create_app().routes
        for method in getattr(route, "methods", set())
    }
    assert ("post", "/api/research-batches") in routes
    assert ("get", "/api/research-batches") in routes
    assert ("get", "/api/research-batches/{batch_id}") in routes
    assert not any(
        method == "delete" and path.startswith("/api/research-batches")
        for method, path in routes
    )
    assert "research-batches" not in "\n".join(
        path.read_text()
        for path in (ROOT / "web" / "src").rglob("*")
        if path.is_file()
    )


def test_batch_schema_keeps_membership_separate_and_claims_structural() -> None:
    batch_schema = (ROOT / "src/thesistrace/research_batch/schema.sql").read_text()
    run_schema = (ROOT / "src/thesistrace/research_run/schema.sql").read_text()
    run_service = (ROOT / "src/thesistrace/research_run/service.py").read_text()
    batch_service = (ROOT / "src/thesistrace/research_batch/service.py").read_text()

    assert "UNIQUE (research_run_id)" in batch_schema
    assert "REFERENCES research_runs.runs" not in batch_schema
    assert "research_runs.runs" not in batch_service
    assert "execution_owner text DEFAULT 'ordinary' NOT NULL" in run_schema
    assert "run.execution_owner = 'ordinary'" in run_service
    assert "execution_owner=\"research_batch\"" in batch_service
    assert "project_child_statuses_in_transaction" in batch_service

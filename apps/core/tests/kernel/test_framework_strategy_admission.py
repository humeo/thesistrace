from copy import deepcopy
from datetime import date
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError
from test_direct_strategy_admission import SOURCE, service_and_snapshot

from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES
from thesistrace.research_run.models import ResearchRunAdmissionCommand, ResearchSpec
from thesistrace.research_run.service import ResearchRunAdmissionRejected

pytestmark = pytest.mark.bounded_process


def test_authoring_discovery_publishes_the_four_framework_module_contracts():
    from thesistrace.research_authoring import ResearchAuthoringService

    framework = ResearchAuthoringService().constraints().model_dump(mode="json")["framework"]
    assert [(stage["stage"], stage["builtin_identity"]) for stage in framework["stages"]] == [
        ("universe_selection", "dataset_universe/v1"),
        ("alpha", "alpha_formula/v1"),
        ("portfolio_construction", "periodic_top_n/v1"),
        ("risk_management", "no_risk/v1"),
    ]
    assert "instrument_ids" in framework["stages"][0]["output_contract"]
    assert "valid_for_sessions" in framework["stages"][1]["output_contract"]
    assert "NoUpdate" in framework["stages"][2]["output_contract"]
    assert "limit_positions" in framework["stages"][3]["output_contract"]
    threshold = framework["builtin_risk_schema"]["properties"]["stop_loss_threshold"]
    assert threshold["exclusiveMaximum"] == 1
    assert "close_risk_nav_cny" in framework["account_observation"]
    assert framework["maximum_active_signals"] == 3000
    assert framework["signal_validity_sessions"] == {"minimum": 1, "maximum": 252}
    assert framework["maximum_state_bytes"] == 3 * 1024 * 1024


def framework_spec():
    modules = dict(BUILTIN_FRAMEWORK_MODULES)
    for stage, fields, history in (
        ("alpha", ["price.close.adjusted"], 3),
        ("portfolio_construction", ["price.open.adjusted"], 2),
    ):
        modules[stage] = {"kind": "python", "program": {
            "source": SOURCE, "parameters": {"stage": stage},
            "data_requirements": {"field_ids": fields, "history_sessions": history},
        }}
    return {
        "research_kind": "strategy_backtest", "strategy_mode": "framework",
        "start_date": "2026-08-07", "end_date": "2026-08-07", "universe": "top300",
        "initial_cash_cny": "100000", "modules": modules,
    }


def test_framework_admission_freezes_only_active_modules_and_unions_declared_requirements():
    service, snapshot = service_and_snapshot(
        field_ids=["price.close.adjusted", "price.open.adjusted"],
    )
    values = framework_spec()
    values["costs"] = {
        "commission_rate_all_in": "0.0002", "commission_min_cny": "1",
        "stamp_duty_sell_rate": "0.0004", "transfer_fee_rate": "0.00002",
        "slippage_bps": "10",
    }
    spec = TypeAdapter(ResearchSpec).validate_python(values)
    assert service.diagnose_research_spec(spec).valid
    command = TypeAdapter(ResearchRunAdmissionCommand).validate_python({
        **values, "request_id": "framework", "folder_id": "folder_default",
    })
    admitted = service.prepare_child_admission(
        UUID(int=1), command, dataset=snapshot,
    ).immutable_input
    frozen = admitted.canonical_value()
    assert frozen["costs"] == values["costs"]
    assert frozen["formula_source"] is None
    assert frozen["alpha_expression"] is None
    assert frozen["neutralization"] is None
    assert frozen["strategy"]["modules"] == values["modules"]
    assert "holdings_count" not in frozen["strategy"]
    assert "exposure_expression" not in frozen["strategy"]
    assert frozen["strategy"]["environment"]["contract"] == "python-strategy/v2"
    assert admitted.expression_admission.effective_lookback == 2
    assert admitted.field_bindings == {
        "price.close.adjusted": "close", "price.open.adjusted": "open",
    }
    assert admitted.expression_trees == ()
    command.modules.alpha.program.parameters["stage"] = "changed"
    assert admitted.canonical_value() == frozen
    assert admitted.authorable_value() == {
        **values, "hypothesis": None,
        "start_date": date(2026, 8, 7), "end_date": date(2026, 8, 7),
    }
    kernel = admitted.kernel_strategy()
    assert kernel.slippage_bps == "10"
    assert kernel.commission_min_cny == "1"
    assert kernel.modules_snapshot().model_dump(mode="json") == values["modules"]
    from thesistrace.daily_track.models import DailyTrackFrozenResearchInput
    from thesistrace.research_run.models import ResearchRunAuthorableInput

    authorable = ResearchRunAuthorableInput.model_validate(admitted.authorable_value())
    assert authorable.model_dump(mode="json")["modules"] == values["modules"]
    track_input = DailyTrackFrozenResearchInput.model_validate(
        authorable.model_dump(exclude={"research_kind"}),
    )
    assert track_input.model_dump(mode="json")["modules"] == values["modules"]
    assert track_input.model_dump(mode="json")["costs"] == values["costs"]


@pytest.mark.parametrize("extra", [
    {"formula": "close"}, {"neutralization": "none"}, {"holdings_count": 10},
    {"selection_every_sessions": 5}, {"exposure_expression": "1"}, {"weighting": "equal_weight"},
])
def test_framework_rejects_inactive_builtin_configuration(extra):
    with pytest.raises(ValidationError):
        TypeAdapter(ResearchSpec).validate_python({**framework_spec(), **extra})


@pytest.mark.parametrize("stage", ["alpha", "portfolio_construction"])
def test_framework_diagnostics_identify_the_failing_stage(stage):
    service, snapshot = service_and_snapshot()
    values = framework_spec()
    values["modules"][stage]["program"]["source"] = "def decide(:"
    spec = TypeAdapter(ResearchSpec).validate_python(values)
    diagnostic = service.diagnose_research_spec(spec)
    assert not diagnostic.valid
    assert diagnostic.issues[0].field == f"modules.{stage}.program.source"
    command = TypeAdapter(ResearchRunAdmissionCommand).validate_python({
        **values, "request_id": "bad-framework", "folder_id": "folder_default",
    })
    with pytest.raises(ResearchRunAdmissionRejected) as caught:
        service.prepare_child_admission(UUID(int=1), command, dataset=snapshot)
    assert caught.value.issues == diagnostic.issues


def test_framework_unavailable_data_diagnostic_identifies_the_requiring_module():
    service, _ = service_and_snapshot()
    spec = TypeAdapter(ResearchSpec).validate_python(framework_spec())
    diagnostic = service.diagnose_research_spec(spec)
    assert not diagnostic.valid
    assert [(issue.code, issue.field) for issue in diagnostic.issues] == [
        ("FIELD_UNAVAILABLE_IN_CURRENT_DATA",
         "modules.portfolio_construction.program.data_requirements"),
    ]


def test_framework_shared_alpha_binding_excludes_individual_module_fields():
    service, snapshot = service_and_snapshot(
        field_ids=["price.close.adjusted", "price.open.adjusted"],
    )
    values = framework_spec()
    values["modules"]["alpha"] = "alpha_formula/v1"
    command = TypeAdapter(ResearchRunAdmissionCommand).validate_python({
        **values, "formula": "close", "neutralization": "none",
        "request_id": "shared-alpha", "folder_id": "folder_default",
    })
    admitted = service.prepare_child_admission(
        UUID(int=1), command, dataset=snapshot,
    ).immutable_input
    assert admitted.alpha_field_bindings == {"price.close.adjusted": "close"}
    assert admitted.field_bindings == {
        "price.close.adjusted": "close", "price.open.adjusted": "open",
    }


def test_framework_sweep_freezes_each_items_modules_without_a_dummy_shared_formula():
    from thesistrace.research_batch.models import ResearchBatchAdmissionCommand

    values = framework_spec()
    item = {name: values[name] for name in ("strategy_mode", "initial_cash_cny", "modules")}
    second = deepcopy(item)
    second["modules"]["alpha"]["program"]["parameters"]["threshold"] = 2
    command = TypeAdapter(ResearchBatchAdmissionCommand).validate_python({
        "batch_kind": "strategy_sweep", "request_id": "frameworks",
        **{name: values[name] for name in ("start_date", "end_date", "universe")},
        "strategies": [{**item, "item_key": "first"}, {**second, "item_key": "second"}],
    })
    assert command.alpha is None
    assert command.neutralization is None
    assert command.strategies[0].modules.alpha.program.parameters == {"stage": "alpha"}
    assert command.strategies[1].modules.alpha.program.parameters["threshold"] == 2


def test_builtin_stop_loss_freezes_and_reuses_the_same_risk_module():
    service, snapshot = service_and_snapshot()
    values = {
        "research_kind": "strategy_backtest", "strategy_mode": "framework",
        "start_date": "2026-08-07", "end_date": "2026-08-07", "universe": "top300",
        "initial_cash_cny": "100000", "formula": "close", "neutralization": "none",
        "holdings_count": 10, "selection_every_sessions": 5, "exposure_expression": "1",
        "weighting": "equal_weight", "volatility_window": 20,
        "modules": {**BUILTIN_FRAMEWORK_MODULES, "risk_management": {
            "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1,
        }},
    }
    spec = TypeAdapter(ResearchSpec).validate_python(values)
    assert service.diagnose_research_spec(spec).valid
    command = TypeAdapter(ResearchRunAdmissionCommand).validate_python({
        **values, "request_id": "stop-loss", "folder_id": "folder_default",
    })
    admitted = service.prepare_child_admission(
        UUID(int=1), command, dataset=snapshot,
    ).immutable_input
    assert admitted.authorable_value()["modules"] == values["modules"]
    assert (admitted.kernel_strategy().modules_snapshot().model_dump(mode="json")
            == values["modules"])
    from thesistrace.daily_track.models import DailyTrackFrozenResearchInput
    authorable = admitted.authorable_value()
    authorable.pop("research_kind")
    track = DailyTrackFrozenResearchInput.model_validate(authorable)
    assert track.model_dump(mode="json")["modules"] == values["modules"]


@pytest.mark.parametrize(
    "threshold", [None, 0, -0.1, 1, 1.1, float("nan"), float("inf"), "0.1", True],
)
def test_builtin_stop_loss_rejects_invalid_thresholds(threshold):
    values = framework_spec()
    values["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "stop_loss_threshold": threshold,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(ResearchSpec).validate_python(values)

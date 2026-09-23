from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError
from test_common_input_admission import inputs

from thesistrace.alpha_language import alpha_language
from thesistrace.research_run.models import ResearchRunAdmissionCommand, ResearchSpec
from thesistrace.research_run.service import ResearchRunAdmissionRejected, ResearchRunService

pytestmark = pytest.mark.bounded_process

SOURCE = "def decide(context, state, parameters):\n    return {'output': None, 'state': state}\n"


def direct_spec():
    return {
        "research_kind": "strategy_backtest",
        "strategy_mode": "direct",
        "start_date": "2026-08-07",
        "end_date": "2026-08-07",
        "universe": "top300",
        "initial_cash_cny": "100000",
        "program": {
            "source": SOURCE,
            "parameters": {"threshold": 0.1},
            "data_requirements": {"field_ids": ["price.close.adjusted"], "history_sessions": 3},
        },
    }


def service_and_snapshot(*, field_ids=None):
    class NoPersistence:
        def __getattr__(self, name):
            raise AssertionError(f"Preparation attempted persistence: {name}")

    _, _, snapshot = inputs("close")
    if field_ids is not None:
        snapshot = replace(snapshot, available_field_ids=frozenset(field_ids))
    return ResearchRunService(
        NoPersistence(), current_dataset=lambda: snapshot, compile_formula=alpha_language.compile,
    ), snapshot


def test_direct_diagnosis_and_admission_freeze_only_the_active_program():
    service, snapshot = service_and_snapshot()
    values = direct_spec()
    values["costs"] = {
        "commission_rate_all_in": "0.0002", "commission_min_cny": "1",
        "stamp_duty_sell_rate": "0.0004", "transfer_fee_rate": "0.00002",
        "slippage_bps": "10",
    }
    spec = TypeAdapter(ResearchSpec).validate_python(values)
    assert service.diagnose_research_spec(spec).valid
    command = TypeAdapter(ResearchRunAdmissionCommand).validate_python(
        {
            **values,
            "request_id": "direct",
            "folder_id": "folder_default",
        }
    )
    admitted = service.prepare_child_admission(
        UUID(int=1), command, dataset=snapshot
    ).immutable_input
    frozen = admitted.canonical_value()
    assert frozen["costs"] == values["costs"]
    assert admitted.kernel_strategy().slippage_bps == "10"
    assert admitted.authorable_value()["costs"] == values["costs"]
    assert frozen["formula_source"] is None
    assert frozen["alpha_expression"] is None
    assert frozen["neutralization"] is None
    assert frozen["strategy"]["kind"] == "direct"
    assert frozen["strategy"]["program"] == values["program"]
    assert "holdings_count" not in frozen["strategy"]
    assert "modules" not in frozen["strategy"]
    assert frozen["strategy"]["environment"]["contract"] == "python-strategy/v2"
    assert admitted.expression_admission.effective_lookback == 2
    assert admitted.execution_plan.calculation_sessions[0].isoformat() == "2026-08-05"
    command.program.parameters["threshold"] = 0.9
    assert admitted.canonical_value() == frozen


@pytest.mark.parametrize(
    "extra",
    [
        {"formula": "close"},
        {"holdings_count": 10},
        {"neutralization": "none"},
        {"selection_every_sessions": 5},
    ],
)
def test_direct_rejects_inactive_framework_settings(extra):
    with pytest.raises(ValidationError):
        TypeAdapter(ResearchSpec).validate_python({**direct_spec(), **extra})


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"source": "def decide(:"}, "program.source"),
        (
            {"data_requirements": {"field_ids": ["unknown.field"], "history_sessions": 1}},
            "program.data_requirements",
        ),
        (
            {"data_requirements": {"field_ids": ["price.close.adjusted"], "history_sessions": 10}},
            "start_date",
        ),
    ],
)
def test_direct_invalid_program_or_data_is_rejected_consistently(change, field):
    service, snapshot = service_and_snapshot()
    values = deepcopy(direct_spec())
    values["program"].update(change)
    spec = TypeAdapter(ResearchSpec).validate_python(values)
    diagnostic = service.diagnose_research_spec(spec)
    assert not diagnostic.valid
    assert diagnostic.issues[0].field == field
    command = TypeAdapter(ResearchRunAdmissionCommand).validate_python(
        {
            **values,
            "request_id": "reject",
            "folder_id": "folder_default",
        }
    )
    with pytest.raises(ResearchRunAdmissionRejected) as error:
        service.prepare_child_admission(UUID(int=1), command, dataset=snapshot)
    assert error.value.issues == diagnostic.issues


def test_direct_batch_contract_keeps_programs_independent_and_omits_shared_alpha():
    from thesistrace.research_batch.models import ResearchBatchAdmissionCommand

    value = {
        "batch_kind": "strategy_sweep",
        "request_id": "programs",
        "start_date": "2026-08-07",
        "end_date": "2026-08-07",
        "universe": "top300",
        "strategies": [
            {
                "item_key": "one",
                "strategy_mode": "direct",
                "program": direct_spec()["program"],
                "initial_cash_cny": "100000",
            }
        ],
    }
    command = TypeAdapter(ResearchBatchAdmissionCommand).validate_python(value)
    assert command.strategies[0].program.source == SOURCE
    assert command.alpha is None
    with pytest.raises(ValidationError):
        TypeAdapter(ResearchBatchAdmissionCommand).validate_python(
            {
                **value,
                "alpha": {"formula": "close"},
            }
        )


def test_authoring_discovery_publishes_program_contract_and_limits():
    from thesistrace.research_authoring import ResearchAuthoringService

    value = ResearchAuthoringService().constraints().model_dump(mode="json")
    assert value["strategy_modes"] == ["framework", "direct"]
    program = value["python_program"]
    assert program["callback"] == "decide(context, state, parameters)"
    assert program["maximum_source_bytes"] == 65536
    assert program["maximum_state_bytes"] == 262144
    assert program["history_sessions"] == {"minimum": 1, "maximum": 253}
    assert program["maximum_fields"] == 32
    assert program["execution_time"] == "next_session_open"
    assert "math" in program["modules"]

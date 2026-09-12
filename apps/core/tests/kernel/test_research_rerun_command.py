import pytest
from pydantic import TypeAdapter, ValidationError


def test_current_data_rerun_is_an_explicit_source_submission_without_strategy_overrides():
    from thesistrace.research_run.models import ResearchRunSubmissionCommand

    adapter = TypeAdapter(ResearchRunSubmissionCommand)
    command = {
        "request_id": "rerun-new-request", "folder_id": "folder-research",
        "rerun_source": {"kind": "research_run", "run_id": "run-original"},
    }
    parsed = adapter.validate_python(command)
    assert parsed.rerun_source.run_id == "run-original"
    assert parsed.request_id == "rerun-new-request"
    for override in ({"formula": "close"}, {"initial_cash_cny": "1"},
                     {"research_kind": "factor_evaluation"}):
        with pytest.raises(ValidationError):
            adapter.validate_python({**command, **override})
    with pytest.raises(ValidationError):
        adapter.validate_python({**command, "rerun_source": {"kind": "research_run", "run_id": ""}})


def test_track_rerun_requires_explicit_published_checkpoint_and_investigation_date():
    from thesistrace.research_run.models import ResearchRunSubmissionCommand

    adapter = TypeAdapter(ResearchRunSubmissionCommand)
    source = {"kind": "daily_track", "track_id": "track-original",
              "checkpoint_manifest_sha256": "a" * 64, "through_session": "2026-08-20"}
    command = {"request_id": "rerun-track", "folder_id": "folder-research", "rerun_source": source}
    parsed = adapter.validate_python(command)
    assert parsed.rerun_source.through_session.isoformat() == "2026-08-20"
    for missing in ("checkpoint_manifest_sha256", "through_session"):
        with pytest.raises(ValidationError):
            adapter.validate_python({**command, "rerun_source": {
                key: value for key, value in source.items() if key != missing
            }})
    for field, invalid in (("checkpoint_manifest_sha256", "bad"),
                           ("through_session", "2026-02-30")):
        with pytest.raises(ValidationError):
            adapter.validate_python({**command, "rerun_source": {**source, field: invalid}})


def test_source_submission_keeps_direct_factor_and_strategy_contracts_available():
    from thesistrace.research_run.models import ResearchRunSubmissionCommand

    adapter = TypeAdapter(ResearchRunSubmissionCommand)
    ordinary = {
        "request_id": "ordinary", "folder_id": "folder-research", "formula": "close",
        "research_kind": "factor_evaluation", "start_date": "2026-08-01",
        "end_date": "2026-08-20", "universe": "top300", "neutralization": "none",
    }
    assert adapter.validate_python(ordinary).research_kind == "factor_evaluation"
    strategy = {**ordinary, "research_kind": "strategy_backtest", "initial_cash_cny": "100000",
                "holdings_count": 10, "selection_every_sessions": 5}
    assert adapter.validate_python(strategy).initial_cash_cny == "100000"
    with pytest.raises(ValidationError):
        adapter.validate_python({**strategy, "rerun_source": {
            "kind": "research_run", "run_id": "original",
        }})

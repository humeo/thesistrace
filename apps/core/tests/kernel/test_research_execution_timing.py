from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from thesistrace.research_batch.run_progress import project_batch_run_execution
from thesistrace.research_run.models import ResearchRunProgress


@pytest.mark.parametrize("kind", ["independent_strategies", "strategy_sweep", "factor_evaluation"])
@pytest.mark.parametrize("formula", ["rank(close)", "close * universe_return()"])
def test_batch_execution_measurements_exclude_waiting_for_message_consumers(
    tmp_path,
    monkeypatch,
    kind,
    formula,
):
    from test_research_batch_execution import _batch_request

    import thesistrace.research_batch.execution as module

    clock = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    for name in (
        "execute_alpha_factor_chunk",
        "execute_strategy_chunk_from_alpha_factor_outcome",
        "execute_research_chunk",
    ):
        original = getattr(module, name)

        def measured_work(*args, original=original, **kwargs):
            result = original(*args, **kwargs)
            clock[0] += 2.0
            return result

        monkeypatch.setattr(module, name, measured_work)
    measured = []
    for delay in (0.0, 1000.0):
        request = _batch_request(
            tmp_path / f"case-{delay}",
            kind="factor_evaluation" if kind == "factor_evaluation" else "strategy_sweep",
            formula=formula,
        )
        request["batch_kind"] = kind
        clock[0] = 0.0
        messages = []
        for message in module.execute_research_batch_messages(deepcopy(request)):
            messages.append(message)
            clock[0] += delay
        measured.append(
            [
                message["child_processing_seconds"]
                for message in messages
                if message.get("status") == "item_succeeded"
                or (
                    kind == "factor_evaluation"
                    and message.get("alpha_factor_task_completed") is True
                )
            ]
        )
    assert measured[0]
    assert all(seconds > 0 for seconds in measured[0])
    assert measured[1] == measured[0]


class TerminalTaskTransaction:
    def __init__(self, processing_seconds):
        self.processing_seconds = processing_seconds

    def execute(self, _query, _parameters):
        return self

    def fetchone(self):
        start = datetime(2026, 10, 13, 2, tzinfo=UTC)
        return {
            "batch_id": "batch-example",
            "item_key": "D141",
            "dependency_role": "strategy",
            "outcome": "succeeded",
            "batch_status": "succeeded",
            "batch_kind": "independent_strategies",
            "started_at": start,
            "finished_at": start + timedelta(hours=1),
            "observed_at": start + timedelta(days=1),
            "processing_seconds": self.processing_seconds,
        }


@pytest.mark.parametrize("processing_seconds", [487.0, None])
def test_completed_run_reports_measured_execution_and_never_substitutes_batch_wait(
    processing_seconds,
):
    progress = ResearchRunProgress(
        phase="succeeded",
        completed_warmup_sessions=0,
        total_warmup_sessions=0,
        completed_research_sessions=1945,
        total_research_sessions=1945,
        committed_chunk_count=56,
    )
    _, _, timing = project_batch_run_execution(
        TerminalTaskTransaction(processing_seconds),
        uuid4(),
        "run-example",
        "succeeded",
        progress,
    )
    assert timing.elapsed_seconds == processing_seconds
    assert timing.is_final is True
    assert timing.finished_at - timing.started_at == timedelta(hours=1)

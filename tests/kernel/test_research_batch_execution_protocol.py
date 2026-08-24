from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from thesistrace.research_batch.execution import (
    ResearchBatchExecutionRequest,
    SupervisedResearchBatchExecutor,
)
from thesistrace.research_run.execution import (
    ResearchExecutionInputInvalid,
    ResearchExecutionResourceExhausted,
)
from thesistrace.research_run.supervised_child import SupervisedChildTransport


def test_supervised_child_reports_invalid_input_without_losing_its_category(
    tmp_path: Path,
) -> None:
    executor = SupervisedResearchBatchExecutor(
        tmp_path,
        execution_memory_bytes=512 * 1024**2,
    )

    with pytest.raises(
        ResearchExecutionInputInvalid,
        match="Research Batch items are invalid",
    ):
        executor.execute(
            _empty_request(), emit=lambda _event: None, cancel_requested=lambda: False
        )


def test_supervisor_preserves_resource_exhausted_child_category(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _failure_envelope_transport("resource_exhausted")
    monkeypatch.setattr(
        SupervisedChildTransport,
        "spawn",
        classmethod(lambda _cls, _module: transport),
    )
    executor = SupervisedResearchBatchExecutor(
        tmp_path,
        execution_memory_bytes=512 * 1024**2,
    )

    with pytest.raises(
        ResearchExecutionResourceExhausted,
        match="injected resource envelope",
    ):
        executor.execute(
            _empty_request(), emit=lambda _event: None, cancel_requested=lambda: False
        )


def test_supervised_child_rejects_an_unknown_batch_kind(tmp_path: Path) -> None:
    executor = SupervisedResearchBatchExecutor(
        tmp_path,
        execution_memory_bytes=512 * 1024**2,
    )
    request = ResearchBatchExecutionRequest(
        batch_kind="unknown",  # type: ignore[arg-type]
        batch_id="batch_protocol",
        attempt_id="attempt_protocol",
        data_generation_id="generation_protocol",
        items=(),
    )

    with pytest.raises(ResearchExecutionInputInvalid, match="Batch Kind is invalid"):
        executor.execute(
            request, emit=lambda _event: None, cancel_requested=lambda: False
        )


def _empty_request() -> ResearchBatchExecutionRequest:
    return ResearchBatchExecutionRequest(
        batch_kind="factor_evaluation",
        batch_id="batch_protocol",
        attempt_id="attempt_protocol",
        data_generation_id="generation_protocol",
        items=(),
    )


def _failure_envelope_transport(category: str) -> SupervisedChildTransport:
    data_io = {
        "manifest_opens": 0,
        "parquet_object_opens": 0,
        "raw_financial_batch_opens": 0,
        "market_parquet_scans": 0,
        "financial_parquet_scans": 0,
        "bytes_read": 0,
        "rows_scanned": 0,
        "columns_scanned": 0,
    }
    envelope = json.dumps(
        {
            "status": "failed",
            "category": category,
            "message": "injected resource envelope",
            "child_peak_rss_bytes": 1,
            "data_io": data_io,
        },
        separators=(",", ":"),
    )
    program = (
        "import sys; sys.stdin.readline(); "
        f"print({envelope!r}, flush=True); raise SystemExit(1)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return SupervisedChildTransport(process=process, oom_kill_count_before=None)

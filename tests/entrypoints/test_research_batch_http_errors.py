from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from thesistrace.entrypoints.http import create_app
from thesistrace.research_batch import (
    ResearchBatchInvalidCursor,
    ResearchBatchTemporarilyUnavailable,
)


class _FailingResearchBatches:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def admit(self, _command: object) -> object:
        raise self._error

    def list(self, **_filters: object) -> object:
        raise self._error

    def get(self, _batch_id: str) -> object:
        raise self._error

    def cancel(self, _batch_id: str, _command: object) -> object:
        raise self._error


def test_http_maps_only_owned_research_batch_failures_to_422_or_503() -> None:
    app = create_app(event_sink=lambda _event: None)
    client = TestClient(app, raise_server_exceptions=False)

    app.state.core_runtime = SimpleNamespace(
        research_batches=_FailingResearchBatches(ResearchBatchInvalidCursor("invalid cursor"))
    )
    invalid_cursor = client.get("/api/research-batches", params={"cursor": "invalid"})
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json() == {"detail": "invalid cursor"}

    app.state.core_runtime = SimpleNamespace(
        research_batches=_FailingResearchBatches(
            ResearchBatchTemporarilyUnavailable("private-database-canary")
        )
    )
    responses = (
        client.post("/api/research-batches", json=_valid_command()),
        client.get("/api/research-batches"),
        client.get("/api/research-batches/batch_test"),
        client.post(
            "/api/research-batches/batch_test/cancel",
            json={"request_id": "batch-http-error-cancel"},
        ),
    )
    assert [response.status_code for response in responses] == [503, 503, 503, 503]
    assert [response.json()["detail"] for response in responses] == [
        "Research Batch admission is temporarily unavailable",
        "Research Batch listing is temporarily unavailable",
        "Research Batch lookup is temporarily unavailable",
        "Research Batch cancellation is temporarily unavailable",
    ]
    assert "private-database-canary" not in "".join(response.text for response in responses)


def test_http_keeps_unexpected_research_batch_failures_internal() -> None:
    app = create_app(event_sink=lambda _event: None)
    app.state.core_runtime = SimpleNamespace(
        research_batches=_FailingResearchBatches(ValueError("private-product-state-canary"))
    )
    client = TestClient(app, raise_server_exceptions=False)

    responses = (
        client.post("/api/research-batches", json=_valid_command()),
        client.get("/api/research-batches"),
        client.get("/api/research-batches/batch_test"),
        client.post(
            "/api/research-batches/batch_test/cancel",
            json={"request_id": "batch-http-unexpected-cancel"},
        ),
    )
    assert [response.status_code for response in responses] == [500, 500, 500, 500]
    assert "private-product-state-canary" not in "".join(response.text for response in responses)


def _valid_command() -> dict[str, object]:
    return {
        "request_id": "batch-http-error-contract",
        "batch_kind": "factor_evaluation",
        "start_date": "2026-08-03",
        "end_date": "2026-08-04",
        "universe": "top300",
        "neutralization": "none",
        "factors": [{"item_key": "value", "formula": "close"}],
    }

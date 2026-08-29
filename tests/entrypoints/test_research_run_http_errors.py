from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from thesistrace.entrypoints.http import create_app
from thesistrace.research_run import (
    ResearchRunInvalidCursor,
    ResearchRunTemporarilyUnavailable,
)
from thesistrace.researcher import ResearcherIdentity

PUBLIC_ORIGIN = "https://core.test"


class _SessionVerifier:
    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        return ResearcherIdentity(
            researcher_id=UUID("018f6f7e-8342-7c9a-a4df-9a86147d2e11"),
            email="researcher@example.test",
            display_label="researcher",
        )


def _app():  # type: ignore[no-untyped-def]
    return create_app(
        auth_verifier=_SessionVerifier(),
        public_origin=PUBLIC_ORIGIN,
        event_sink=lambda _event: None,
    )


class _FailingResearchRuns:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def admit(self, _researcher_id: UUID, _command: object) -> object:
        raise self._error

    def list(self, _researcher_id: UUID, **_filters: object) -> object:
        raise self._error


def test_http_maps_only_owned_research_run_failures_to_400_or_503() -> None:
    app = _app()
    client = TestClient(
        app,
        headers={"Origin": PUBLIC_ORIGIN},
        raise_server_exceptions=False,
    )

    app.state.core_runtime = SimpleNamespace(
        research_runs=_FailingResearchRuns(ResearchRunInvalidCursor("invalid cursor"))
    )
    invalid_cursor = client.get("/api/research-runs", params={"cursor": "invalid"})
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json() == {"detail": "invalid cursor"}

    app.state.core_runtime = SimpleNamespace(
        research_runs=_FailingResearchRuns(
            ResearchRunTemporarilyUnavailable("private-database-canary")
        )
    )
    unavailable_list = client.get("/api/research-runs")
    unavailable_admission = client.post("/api/research-runs", json=_valid_command())
    assert unavailable_list.status_code == 503
    assert unavailable_list.json() == {
        "detail": "ResearchRun history temporarily unavailable"
    }
    assert unavailable_admission.status_code == 503
    assert unavailable_admission.json() == {
        "detail": "ResearchRun admission temporarily unavailable"
    }
    assert "private-database-canary" not in (
        unavailable_list.text + unavailable_admission.text
    )


def test_http_keeps_unexpected_research_run_failures_internal() -> None:
    app = _app()
    app.state.core_runtime = SimpleNamespace(
        research_runs=_FailingResearchRuns(ValueError("private-product-state-canary"))
    )
    client = TestClient(
        app,
        headers={"Origin": PUBLIC_ORIGIN},
        raise_server_exceptions=False,
    )

    failed_list = client.get("/api/research-runs")
    failed_admission = client.post("/api/research-runs", json=_valid_command())

    assert failed_list.status_code == 500
    assert failed_admission.status_code == 500
    assert "private-product-state-canary" not in failed_list.text
    assert "private-product-state-canary" not in failed_admission.text


def _valid_command() -> dict[str, object]:
    return {
        "request_id": "http-error-contract",
        "folder_id": "folder_default",
        "name": "HTTP Error Contract",
        "formula": "close",
        "hypothesis": None,
        "start_date": "2026-08-03",
        "end_date": "2026-08-04",
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "factor_evaluation",
    }

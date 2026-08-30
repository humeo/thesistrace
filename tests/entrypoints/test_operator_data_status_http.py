from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from thesistrace.data.operational_status import (
    DataOperatorWorkerStatus,
    DataRefreshInvalidCursor,
    DataRefreshOperationalStatus,
    DatasetOperationalHead,
    DatasetOperationalStatus,
)
from thesistrace.entrypoints.authentication import OperatorAccessNotFound
from thesistrace.entrypoints.http import create_app
from thesistrace.researcher import ResearcherIdentity

PUBLIC_ORIGIN = "https://thesistrace.test"
COOKIE = "thesistrace.session_token=operator"
IDENTITY = ResearcherIdentity(
    researcher_id=UUID("00000000-0000-4000-8000-000000000041"),
    email="operator@example.test",
    display_label="Operator",
)


class SessionVerifier:
    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        return IDENTITY


class OperatorAuthorizer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def authorize_operator(self, _cookie: str | None) -> None:
        if self.error is not None:
            raise self.error


class OperationalStatusReader:
    def __init__(self) -> None:
        self.cursors: list[str | None] = []
        created_at = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
        operation = DataRefreshOperationalStatus(
            idempotency_key="financial-20260830",
            kind="financial",
            status="succeeded",
            outcome="degraded",
            as_of=None,
            observation_through_session=date(2026, 8, 29),
            phase="financial",
            attempt_count=2,
            last_heartbeat_at=datetime(2026, 8, 30, 8, 1, tzinfo=UTC),
            data_through_session=date(2026, 8, 29),
            last_refresh_at=datetime(2026, 8, 30, 8, 2, tzinfo=UTC),
            financial_complete_through_session=date(2026, 8, 28),
            matched_trigger_count=9,
            checked_no_structured_change_count=4,
            accepted_instrument_count=3,
            failed_instrument_count=1,
            pending_instrument_count=2,
            discovery_gap_count=1,
            failure_code=None,
            last_failure_code=None,
            created_at=created_at,
            started_at=created_at,
            finished_at=datetime(2026, 8, 30, 8, 2, tzinfo=UTC),
            updated_at=datetime(2026, 8, 30, 8, 2, tzinfo=UTC),
        )
        self.response = DatasetOperationalStatus(
            head=DatasetOperationalHead(
                data_identity="d" * 64,
                prepared_at=datetime(2026, 8, 29, 23, 0, tzinfo=UTC),
                data_through_session=date(2026, 8, 29),
                market_research_readiness=True,
                benchmark_research_readiness=True,
                financial_research_readiness="ready_with_pending",
                industry_research_readiness=True,
            ),
            worker=DataOperatorWorkerStatus(
                available=False,
                last_heartbeat_at=datetime(2026, 8, 30, 7, 59, tzinfo=UTC),
            ),
            latest_by_kind=(operation,),
            operations=(operation,),
            next_cursor="opaque-next-page",
        )

    def status(self, *, cursor: str | None) -> DatasetOperationalStatus:
        self.cursors.append(cursor)
        if cursor == "invalid":
            raise DataRefreshInvalidCursor("invalid")
        return self.response


def test_operator_dataset_status_returns_exact_safe_projection() -> None:
    reader = OperationalStatusReader()
    client = _client(reader, OperatorAuthorizer())

    response = client.get(
        "/api/operator/data/status",
        headers={"cookie": COOKIE},
        params={"cursor": "opaque-page"},
    )

    assert response.status_code == 200
    assert reader.cursors == ["opaque-page"]
    payload = response.json()
    assert set(payload) == {
        "head",
        "worker",
        "latest_by_kind",
        "operations",
        "next_cursor",
    }
    assert payload["worker"] == {
        "available": False,
        "last_heartbeat_at": "2026-08-30T07:59:00Z",
    }
    assert payload["head"] == {
        "data_identity": "d" * 64,
        "prepared_at": "2026-08-29T23:00:00Z",
        "data_through_session": "2026-08-29",
        "market_research_readiness": True,
        "benchmark_research_readiness": True,
        "financial_research_readiness": "ready_with_pending",
        "industry_research_readiness": True,
    }
    assert payload["operations"][0]["status"] == "succeeded"
    assert payload["operations"][0]["outcome"] == "degraded"
    serialized = response.text
    for forbidden in (
        "owner_token",
        "lease_expires_at",
        "fingerprint",
        "manifest",
        "object_path",
    ):
        assert forbidden not in serialized


def test_operator_dataset_status_rejects_invalid_cursor_without_echoing_it() -> None:
    client = _client(OperationalStatusReader(), OperatorAuthorizer())

    response = client.get(
        "/api/operator/data/status",
        headers={"cookie": COOKIE},
        params={"cursor": "invalid"},
    )

    assert response.status_code == 400
    assert response.json() == {"code": "DATA_REFRESH_CURSOR_INVALID"}
    assert "invalid" not in response.text


def test_researcher_cannot_discover_operator_dataset_status() -> None:
    client = _client(
        OperationalStatusReader(),
        OperatorAuthorizer(OperatorAccessNotFound()),
    )

    response = client.get(
        "/api/operator/data/status",
        headers={"cookie": "thesistrace.session_token=researcher"},
    )

    assert response.status_code == 404
    assert response.text == ""


def _client(
    reader: OperationalStatusReader,
    authorizer: OperatorAuthorizer,
) -> TestClient:
    app = create_app(
        auth_verifier=SessionVerifier(),
        operator_authorizer=authorizer,
        public_origin=PUBLIC_ORIGIN,
    )
    app.state.core_runtime = SimpleNamespace(data_operational_status=reader)
    return TestClient(app)

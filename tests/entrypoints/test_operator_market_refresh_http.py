from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import anyio
import httpx
from fastapi.testclient import TestClient

from thesistrace.data import DataRefreshError, RefreshOutcome
from thesistrace.entrypoints.authentication import (
    AuthSessionUnavailable,
    InvalidOperatorProof,
    OperatorAccessNotFound,
)
from thesistrace.entrypoints.http import create_app
from thesistrace.researcher import ResearcherIdentity

PUBLIC_ORIGIN = "https://thesistrace.test"
COOKIE = "thesistrace.session_token=operator"
PROOF = "00000000-0000-4000-8000-000000000041." + "a" * 43
IDENTITY = ResearcherIdentity(
    researcher_id=UUID("00000000-0000-4000-8000-000000000041"),
    email="operator@example.test",
    display_label="Operator",
)


class SessionVerifier:
    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        return IDENTITY


class UnexpectedSessionVerifier:
    async def verify(self, _cookie: str | None) -> ResearcherIdentity:
        raise AssertionError("Operator API used the ordinary Session boundary")


class OperatorAuthorizer:
    def __init__(self) -> None:
        self.authorize_error: Exception | None = None
        self.consume_error: Exception | None = None
        self.authorized_cookies: list[str | None] = []
        self.consumed: list[dict[str, str | None]] = []

    async def authorize_operator(self, cookie: str | None) -> None:
        self.authorized_cookies.append(cookie)
        if self.authorize_error is not None:
            raise self.authorize_error

    async def consume_market_refresh_proof(
        self,
        cookie: str | None,
        *,
        as_of: str,
        idempotency_key: str,
        proof: str,
    ) -> None:
        self.consumed.append({
            "as_of": as_of,
            "cookie": cookie,
            "idempotency_key": idempotency_key,
            "proof": proof,
        })
        if self.consume_error is not None:
            raise self.consume_error


class Refreshes:
    def __init__(self) -> None:
        self.submit_error: Exception | None = None
        self.submissions: list[dict[str, object]] = []
        self.receipt = RefreshOutcome(
            idempotency_key="market-20260811T180000+0800",
            kind="market",
            as_of="2026-08-11T10:00:00+00:00",
            status="accepted",
            outcome=None,
            data_through_session=None,
            last_refresh_at=None,
            failure_code=None,
            last_failure_code=None,
            attempt_count=0,
        )

    def submit(self, **request: object) -> RefreshOutcome:
        self.submissions.append(request)
        if self.submit_error is not None:
            raise self.submit_error
        return self.receipt

    def inspect(self, idempotency_key: str) -> RefreshOutcome:
        if idempotency_key != self.receipt.idempotency_key:
            raise DataRefreshError("REFRESH_NOT_FOUND")
        return self.receipt


def test_operator_market_submission_consumes_proof_then_returns_safe_receipt() -> None:
    authorizer = OperatorAuthorizer()
    refreshes = Refreshes()
    client = _client(authorizer, refreshes)

    response = client.post(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE, "origin": PUBLIC_ORIGIN},
        json={
            "as_of": "2026-08-11T18:00:00+08:00",
            "idempotency_key": "market-20260811T180000+0800",
            "proof": PROOF,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "as_of": "2026-08-11T10:00:00Z",
        "attempt_count": 0,
        "data_through_session": None,
        "failure_code": None,
        "idempotency_key": "market-20260811T180000+0800",
        "kind": "market",
        "last_failure_code": None,
        "last_refresh_at": None,
        "outcome": None,
        "status": "accepted",
    }
    assert authorizer.authorized_cookies == [COOKIE]
    assert authorizer.consumed == [{
        "as_of": "2026-08-11T18:00:00+08:00",
        "cookie": COOKIE,
        "idempotency_key": "market-20260811T180000+0800",
        "proof": PROOF,
    }]
    assert refreshes.submissions == [{
        "as_of": datetime(2026, 8, 11, 10, tzinfo=UTC),
        "idempotency_key": "market-20260811T180000+0800",
    }]


def test_operator_market_validation_and_proof_failure_have_no_operation_side_effect() -> None:
    authorizer = OperatorAuthorizer()
    refreshes = Refreshes()
    client = _client(authorizer, refreshes)
    invalid = client.post(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE, "origin": PUBLIC_ORIGIN},
        json={
            "as_of": "2026-08-11",
            "idempotency_key": "market-key",
            "proof": PROOF,
        },
    )

    assert invalid.status_code == 422
    assert authorizer.consumed == []
    assert refreshes.submissions == []

    for incompatible_key in ("market-\0-key", f"market-{chr(0xD800)}-key"):
        incompatible = client.post(
            "/api/operator/data/refreshes/market",
            content=json.dumps(
                {
                    "as_of": "2026-08-11T18:00:00+08:00",
                    "idempotency_key": incompatible_key,
                    "proof": PROOF,
                },
                ensure_ascii=True,
            ),
            headers={
                "content-type": "application/json",
                "cookie": COOKIE,
                "origin": PUBLIC_ORIGIN,
            },
        )
        assert incompatible.status_code == 422
        assert incompatible.json() == {"code": "OPERATOR_REQUEST_INVALID"}
        assert authorizer.consumed == []
        assert refreshes.submissions == []

    malformed_proof = client.post(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE, "origin": PUBLIC_ORIGIN},
        json={
            "as_of": "2026-08-11T18:00:00+08:00",
            "idempotency_key": "market-key",
            "proof": "canary-secret-proof",
        },
    )
    assert malformed_proof.status_code == 422
    assert malformed_proof.json() == {"code": "OPERATOR_REQUEST_INVALID"}
    assert "canary-secret-proof" not in malformed_proof.text
    assert authorizer.consumed == []
    assert refreshes.submissions == []

    authorizer.consume_error = InvalidOperatorProof()
    rejected = client.post(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE, "origin": PUBLIC_ORIGIN},
        json={
            "as_of": "2026-08-11T18:00:00+08:00",
            "idempotency_key": "market-key",
            "proof": PROOF,
        },
    )
    assert rejected.status_code == 400
    assert rejected.json() == {"code": "OPERATOR_PROOF_INVALID"}
    assert refreshes.submissions == []


def test_operator_market_read_and_mutation_hide_the_surface_or_fail_unavailable() -> None:
    authorizer = OperatorAuthorizer()
    refreshes = Refreshes()
    client = _client(authorizer, refreshes)
    authorizer.authorize_error = OperatorAccessNotFound()
    hidden = client.get(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE},
        params={"idempotency_key": refreshes.receipt.idempotency_key},
    )
    assert hidden.status_code == 404
    assert hidden.text == ""

    hidden_invalid_mutation = client.post(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE, "origin": PUBLIC_ORIGIN},
        json={"proof": "short"},
    )
    assert hidden_invalid_mutation.status_code == 404
    assert hidden_invalid_mutation.text == ""

    authorizer.authorize_error = None
    authorizer.consume_error = OperatorAccessNotFound()
    hidden_mutation = client.post(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE, "origin": PUBLIC_ORIGIN},
        json={
            "as_of": "2026-08-11T18:00:00+08:00",
            "idempotency_key": "market-key",
            "proof": PROOF,
        },
    )
    assert hidden_mutation.status_code == 404
    assert hidden_mutation.text == ""

    authorizer.authorize_error = AuthSessionUnavailable()
    unavailable = client.get(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE},
        params={"idempotency_key": refreshes.receipt.idempotency_key},
    )
    assert unavailable.status_code == 503


def test_operator_market_inspection_is_bound_to_the_canonical_request() -> None:
    authorizer = OperatorAuthorizer()
    refreshes = Refreshes()
    client = _client(authorizer, refreshes)

    matching = client.get(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE},
        params={
            "as_of": "2026-08-11T18:00:00+08:00",
            "idempotency_key": refreshes.receipt.idempotency_key,
        },
    )
    assert matching.status_code == 200
    assert matching.json()["idempotency_key"] == refreshes.receipt.idempotency_key

    conflict = client.get(
        "/api/operator/data/refreshes/market",
        headers={"cookie": COOKIE},
        params={
            "as_of": "2026-08-11T19:00:00+08:00",
            "idempotency_key": refreshes.receipt.idempotency_key,
        },
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"code": "IDEMPOTENCY_KEY_CONFLICT"}


def test_operator_market_persistence_does_not_block_the_api_event_loop() -> None:
    anyio.run(_exercise_operator_market_persistence_event_loop_liveness)


async def _exercise_operator_market_persistence_event_loop_liveness() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingRefreshes(Refreshes):
        def submit(self, **request: object) -> RefreshOutcome:
            entered.set()
            assert release.wait(timeout=3)
            return super().submit(**request)

    app = create_app(
        auth_verifier=SessionVerifier(),
        operator_authorizer=OperatorAuthorizer(),
        public_origin=PUBLIC_ORIGIN,
    )
    app.state.core_runtime = SimpleNamespace(data_refreshes=BlockingRefreshes())
    submitted: list[httpx.Response] = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
    ) as client:
        async with anyio.create_task_group() as tasks:
            async def submit() -> None:
                submitted.append(await client.post(
                    "/api/operator/data/refreshes/market",
                    headers={"cookie": COOKIE, "origin": PUBLIC_ORIGIN},
                    json={
                        "as_of": "2026-08-11T18:00:00+08:00",
                        "idempotency_key": "market-async-persistence",
                        "proof": PROOF,
                    },
                ))

            try:
                tasks.start_soon(submit)
                assert await anyio.to_thread.run_sync(entered.wait, 2)
                with anyio.fail_after(1):
                    liveness = await client.get("/health/live")
                assert liveness.status_code == 200
            finally:
                release.set()

    assert len(submitted) == 1
    assert submitted[0].status_code == 202


def test_anonymous_operator_api_is_hidden_before_the_ordinary_session_boundary() -> None:
    authorizer = OperatorAuthorizer()
    authorizer.authorize_error = OperatorAccessNotFound()
    client = _client(
        authorizer,
        Refreshes(),
        session_verifier=UnexpectedSessionVerifier(),
    )

    response = client.post(
        "/api/operator/data/refreshes/market",
        headers={"origin": PUBLIC_ORIGIN},
        json={"proof": "short"},
    )

    assert response.status_code == 404
    assert response.text == ""


def _client(
    authorizer: OperatorAuthorizer,
    refreshes: Refreshes,
    *,
    session_verifier: SessionVerifier | UnexpectedSessionVerifier | None = None,
) -> TestClient:
    app = create_app(
        auth_verifier=session_verifier or SessionVerifier(),
        operator_authorizer=authorizer,
        public_origin=PUBLIC_ORIGIN,
    )
    app.state.core_runtime = SimpleNamespace(data_refreshes=refreshes)
    return TestClient(app)

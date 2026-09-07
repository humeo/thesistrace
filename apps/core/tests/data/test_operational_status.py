from datetime import UTC, date, datetime

import pytest

from thesistrace.data.operational_status import (
    DataOperatorWorkerStatus,
    DataRefreshInvalidCursor,
    _decode_cursor,
    _encode_cursor,
    _operation_from_row,
)


def test_worker_status_contains_only_safe_availability_facts() -> None:
    heartbeat = datetime(2026, 8, 30, 8, 1, tzinfo=UTC)

    assert DataOperatorWorkerStatus(
        available=False,
        last_heartbeat_at=heartbeat,
    ).model_dump(mode="json") == {
        "available": False,
        "last_heartbeat_at": "2026-08-30T08:01:00Z",
    }


def test_operational_status_cursor_is_opaque_bound_and_strict() -> None:
    secret = bytes.fromhex("12" * 32)
    created_at = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)

    cursor = _encode_cursor(
        created_at=created_at,
        idempotency_key="financial-20260830",
        secret=secret,
    )

    assert "financial-20260830" not in cursor
    assert _decode_cursor(cursor, secret=secret) == (
        created_at,
        "financial-20260830",
    )
    for invalid, invalid_secret in (
        (cursor, bytes.fromhex("34" * 32)),
        ("not-a-cursor", secret),
        ("x" * 1_025, secret),
    ):
        with pytest.raises(DataRefreshInvalidCursor):
            _decode_cursor(invalid, secret=invalid_secret)


def test_operational_status_projects_only_bounded_safe_refresh_fields() -> None:
    created_at = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    row: dict[str, object] = {
        "idempotency_key": "financial-20260830",
        "kind": "financial",
        "fingerprint": "f" * 64,
        "status": "running",
        "owner_token": "must-not-leak",
        "lease_expires_at": datetime(2026, 8, 30, 8, 15, tzinfo=UTC),
        "attempt_count": 2,
        "phase": "financial",
        "last_heartbeat_at": datetime(2026, 8, 30, 8, 1, tzinfo=UTC),
        "outcome": None,
        "as_of": None,
        "observation_through_session": date(2026, 8, 29),
        "expected_generation_manifest_sha256": "e" * 64,
        "candidate_prepared_at": None,
        "generation_manifest_sha256": "g" * 64,
        "data_through_session": None,
        "last_refresh_at": None,
        "financial_complete_through_session": None,
        "matched_trigger_count": None,
        "checked_no_structured_change_count": None,
        "accepted_instrument_count": None,
        "failed_instrument_count": None,
        "pending_instrument_count": None,
        "discovery_gap_count": None,
        "failure_code": None,
        "last_failure_code": "WORKER_LEASE_EXPIRED",
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": None,
        "updated_at": datetime(2026, 8, 30, 8, 1, tzinfo=UTC),
    }
    operation = _operation_from_row(row)

    assert operation.model_dump(mode="json") == {
        "financial_progress": None,
        "idempotency_key": "financial-20260830",
        "kind": "financial",
        "status": "running",
        "outcome": None,
        "as_of": None,
        "observation_through_session": "2026-08-29",
        "phase": "financial",
        "attempt_count": 2,
        "last_heartbeat_at": "2026-08-30T08:01:00Z",
        "data_through_session": None,
        "last_refresh_at": None,
        "financial_complete_through_session": None,
        "matched_trigger_count": None,
        "checked_no_structured_change_count": None,
        "accepted_instrument_count": None,
        "failed_instrument_count": None,
        "pending_instrument_count": None,
        "discovery_gap_count": None,
        "failure_code": None,
        "last_failure_code": "WORKER_LEASE_EXPIRED",
        "created_at": "2026-08-30T08:00:00Z",
        "started_at": "2026-08-30T08:00:00Z",
        "finished_at": None,
        "updated_at": "2026-08-30T08:01:00Z",
    }

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_run.diagnostics import (
    ResearchRunDiagnosticNotFound,
    ResearchRunDiagnostics,
)
from thesistrace.researcher import ResearcherIdentity, ResearcherService

TEST_NOW = datetime.now(UTC)
TEST_RESEARCHER = ResearcherIdentity(
    researcher_id=UUID("30000000-0000-4000-8000-000000000003"),
    email="research-run-diagnostics@example.test",
    display_label="Research Run Diagnostics",
)
FOREIGN_RESEARCHER = ResearcherIdentity(
    researcher_id=UUID("30000000-0000-4000-8000-000000000004"),
    email="foreign-research-run-diagnostics@example.test",
    display_label="Foreign Research Run Diagnostics",
)


def test_research_run_diagnostic_hides_a_foreign_researcher_resource(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    try:
        ResearcherService(database).bootstrap(FOREIGN_RESEARCHER)
        with database.transaction() as transaction:
            _insert_run(
                transaction,
                "diagnostic-private",
                status="queued",
                progress="queued",
            )

        snapshot = ResearchRunDiagnostics(database).inspect(
            TEST_RESEARCHER.researcher_id,
            "diagnostic-private",
        )
        assert snapshot["run"]["id"] == "diagnostic-private"  # type: ignore[index]
        try:
            ResearchRunDiagnostics(database).inspect(
                FOREIGN_RESEARCHER.researcher_id,
                "diagnostic-private",
            )
        except ResearchRunDiagnosticNotFound:
            pass
        else:
            raise AssertionError("foreign Researcher diagnostic was disclosed")
    finally:
        database.close()


def test_research_run_diagnostic_reports_the_postgresql_state_matrix(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    try:
        with database.transaction() as transaction:
            _insert_run(transaction, "diagnostic-queued", status="queued", progress="queued")
            _insert_run(
                transaction,
                "diagnostic-active",
                status="running",
                progress="finalizing",
            )
            _insert_attempt(
                transaction,
                "diagnostic-active",
                "attempt-active",
                ordinal=1,
                status="running",
                lease_expires_at=TEST_NOW + timedelta(minutes=10),
            )
            _insert_checkpoint(transaction, "diagnostic-active", "attempt-active")
            _insert_run(transaction, "diagnostic-expired", status="running", progress="warmup")
            _insert_attempt(
                transaction,
                "diagnostic-expired",
                "attempt-expired",
                ordinal=1,
                status="running",
                lease_expires_at=TEST_NOW - timedelta(minutes=1),
            )
            _insert_run(transaction, "diagnostic-retry", status="running", progress="research")
            _insert_attempt(
                transaction,
                "diagnostic-retry",
                "attempt-retry",
                ordinal=1,
                status="failed",
                lease_expires_at=TEST_NOW - timedelta(minutes=5),
                failure_reason="InfrastructureUnavailable",
            )
            _insert_run(transaction, "diagnostic-failed", status="failed", progress="research")
            _insert_attempt(
                transaction,
                "diagnostic-failed",
                "attempt-failed",
                ordinal=1,
                status="failed",
                lease_expires_at=TEST_NOW - timedelta(minutes=5),
                failure_reason="canary-secret /private/result.json",
            )
            _insert_run(
                transaction,
                "diagnostic-token-failed",
                status="failed",
                progress="research",
            )
            _insert_attempt(
                transaction,
                "diagnostic-token-failed",
                "attempt-token-failed",
                ordinal=1,
                status="failed",
                lease_expires_at=TEST_NOW - timedelta(minutes=5),
                failure_reason="canarySecretToken123",
            )
            _insert_run(
                transaction,
                "diagnostic-cancelled",
                status="cancelled",
                progress="research",
            )
            _insert_attempt(
                transaction,
                "diagnostic-cancelled",
                "attempt-cancelled",
                ordinal=1,
                status="cancelled",
                lease_expires_at=TEST_NOW,
                failure_reason="UserCancelled",
            )
            _insert_run(
                transaction,
                "diagnostic-succeeded",
                status="succeeded",
                progress="succeeded",
                result_present=True,
                research_kind="strategy_backtest",
            )
            _insert_attempt(
                transaction,
                "diagnostic-succeeded",
                "attempt-z-first",
                ordinal=1,
                status="failed",
                lease_expires_at=TEST_NOW - timedelta(minutes=10),
                failure_reason="WorkerLost",
            )
            _insert_attempt(
                transaction,
                "diagnostic-succeeded",
                "attempt-a-second",
                ordinal=2,
                status="succeeded",
                lease_expires_at=TEST_NOW,
            )

        snapshots = {
            name: ResearchRunDiagnostics(database).inspect(
                TEST_RESEARCHER.researcher_id, f"diagnostic-{name}"
            )
            for name in (
                "queued",
                "active",
                "expired",
                "retry",
                "failed",
                "token-failed",
                "cancelled",
                "succeeded",
            )
        }

        assert snapshots["queued"]["attempts"] == []
        assert snapshots["queued"]["recovery"] == {
            "state": "awaiting_attempt",
            "retry_eligible": False,
            "retry_at": None,
            "failure_code": None,
        }
        assert snapshots["queued"]["publication"] == {
            "state": "unpublished",
            "result_bundle_present": False,
        }
        assert snapshots["active"]["attempts"][0]["lease_state"] == "current"
        assert snapshots["active"]["attempts"][0]["phase"] == "finalizing"
        assert snapshots["active"]["recovery"]["state"] == "active"
        assert snapshots["active"]["private_artifacts"] == {
            "checkpoint_present": True,
            "result_bundle_present": False,
        }
        assert snapshots["expired"]["attempts"][0]["lease_state"] == "expired"
        assert snapshots["expired"]["recovery"]["state"] == "lease_expired"
        assert snapshots["retry"]["recovery"] == {
            "state": "retry_pending",
            "retry_eligible": True,
            "retry_at": None,
            "failure_code": "INFRASTRUCTURE_UNAVAILABLE",
        }
        assert snapshots["failed"]["attempts"][0]["failure_code"] == (
            "UNCLASSIFIED_FAILURE"
        )
        assert snapshots["token-failed"]["attempts"][0]["failure_code"] == (
            "UNCLASSIFIED_FAILURE"
        )
        assert snapshots["failed"]["recovery"]["state"] == "not_applicable"
        assert snapshots["cancelled"]["attempts"][0]["failure_code"] == (
            "USER_CANCELLED"
        )
        assert snapshots["succeeded"]["run"]["research_kind"] == "strategy_backtest"
        assert snapshots["succeeded"]["publication"] == {
            "state": "published",
            "result_bundle_present": True,
        }
        assert [
            attempt["id"] for attempt in snapshots["succeeded"]["attempts"]
        ] == ["attempt-z-first", "attempt-a-second"]
        assert all(
            attempt["lease_state"] == "expired"
            for attempt in snapshots["succeeded"]["attempts"]
        )
        serialized = json.dumps(snapshots, sort_keys=True)
        assert "canary-secret" not in serialized
        assert "canarySecretToken123" not in serialized
        assert "/private/result.json" not in serialized
        assert "manifest" not in serialized
        assert "payload" not in serialized
        assert "object_key" not in serialized
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z",
            str(snapshots["active"]["diagnosed_at"]),
        )
    finally:
        database.close()


def test_research_run_diagnostic_cli_uses_only_postgresql_and_has_stable_exits(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        with database.transaction() as transaction:
            _insert_run(
                transaction,
                "diagnostic-cli",
                status="failed",
                progress=None,
            )
    finally:
        database.close()

    postgres_only_environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("THESISTRACE_S3_") and key != "THESISTRACE_DATA_MOUNT"
    }
    postgres_only_environment["THESISTRACE_DATABASE_URL"] = core_settings.database_url
    unavailable_storage_environment = {
        **postgres_only_environment,
        "THESISTRACE_S3_ENDPOINT_URL": "http://127.0.0.1:1/canary-secret",
        "THESISTRACE_S3_ACCESS_KEY_ID": "canary-access-key",
        "THESISTRACE_S3_SECRET_ACCESS_KEY": "canary-secret-key",
        "THESISTRACE_DATA_MOUNT": os.fspath(
            tmp_path / "unavailable" / "private" / "dataset"
        ),
    }
    first = _diagnose(
        postgres_only_environment,
        "research-run",
        str(TEST_RESEARCHER.researcher_id),
        "diagnostic-cli",
    )
    second = _diagnose(
        unavailable_storage_environment,
        "research-run",
        str(TEST_RESEARCHER.researcher_id),
        "diagnostic-cli",
    )

    assert first.returncode == second.returncode == 0
    first_snapshot = json.loads(first.stdout)
    second_snapshot = json.loads(second.stdout)
    assert first.stdout == json.dumps(first_snapshot, indent=2, sort_keys=True) + "\n"
    assert first.stderr == second.stderr == ""
    assert first_snapshot["progress"]["present"] is False
    assert all(
        first_snapshot["progress"][name] is None
        for name in (
            "phase",
            "completed_warmup_sessions",
            "total_warmup_sessions",
            "completed_research_sessions",
            "total_research_sessions",
            "committed_chunk_count",
            "last_completed_warmup_session",
            "last_completed_research_session",
            "remaining_duration_estimate_seconds",
            "updated_at",
        )
    )
    first_snapshot.pop("diagnosed_at")
    second_snapshot.pop("diagnosed_at")
    assert first_snapshot == second_snapshot
    assert "canary" not in first.stdout + first.stderr

    missing = _diagnose(
        unavailable_storage_environment,
        "research-run",
        str(TEST_RESEARCHER.researcher_id),
        "diagnostic-missing",
    )
    assert missing.returncode == 3
    assert missing.stdout == ""
    assert missing.stderr == "RESEARCH_RUN_NOT_FOUND\n"

    invalid = _diagnose(
        unavailable_storage_environment,
        "research-run",
        str(TEST_RESEARCHER.researcher_id),
        "/private/canary-secret",
    )
    assert invalid.returncode == 2
    assert invalid.stdout == ""
    assert invalid.stderr == "INVALID_USAGE\n"

    unavailable_environment = {
        key: value
        for key, value in unavailable_storage_environment.items()
        if key != "THESISTRACE_DATABASE_URL"
    }
    unavailable = _diagnose(
        unavailable_environment,
        "research-run",
        str(TEST_RESEARCHER.researcher_id),
        "diagnostic-cli",
    )
    assert unavailable.returncode == 4
    assert unavailable.stdout == ""
    assert unavailable.stderr == "POSTGRESQL_UNAVAILABLE\n"


def test_research_run_diagnostic_cli_redacts_parser_errors() -> None:
    environment = dict(os.environ)
    cases = (
        (),
        ("/private/canary-secret",),
        ("research-run", "diagnostic-cli", "--token", "canarySecretToken123"),
    )

    for arguments in cases:
        result = _diagnose(environment, *arguments)
        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr == "INVALID_USAGE\n"


def _insert_run(
    transaction: PostgresTransaction,
    run_id: str,
    *,
    status: str,
    progress: str | None,
    result_present: bool = False,
    research_kind: str = "factor_evaluation",
    researcher_id: UUID = TEST_RESEARCHER.researcher_id,
) -> None:
    immutable_input: dict[str, object] = {"research_kind": research_kind}
    if research_kind == "strategy_backtest":
        immutable_input.update(
            {
                "strategy": {},
                "costs": {},
                "risk_free_rate": "0",
            }
        )
    transaction.execute(
        """
        INSERT INTO research_runs.run_ownership (researcher_id, run_id)
        VALUES (%s, %s)
        """,
        (researcher_id, run_id),
    )
    transaction.execute(
        """
        INSERT INTO research_runs.runs (
            researcher_id, id, folder_id, name, requested_start_date, requested_end_date,
            status, immutable_input, result_manifest_sha256, failure_reason
        ) VALUES (%s, %s, 'folder_default', %s, '2026-01-01', '2026-01-31',
                  %s, %s, %s, %s)
        """,
        (
            researcher_id,
            run_id,
            run_id,
            status,
            Jsonb(immutable_input),
            "f" * 64 if result_present else None,
            "PermanentExecutionFailure" if status == "failed" else None,
        ),
    )
    if progress is not None:
        transaction.execute(
            """
            INSERT INTO research_runs.progress (
                run_id, phase, completed_warmup_sessions, total_warmup_sessions,
                completed_research_sessions, total_research_sessions,
                committed_chunk_count, last_completed_warmup_session,
                last_completed_research_session, remaining_duration_estimate_seconds,
                updated_at
            ) VALUES (%s, %s, 2, 3, 4, 5, 6, '2026-01-02',
                      '2026-01-03', 7, %s)
            """,
            (run_id, progress, TEST_NOW),
        )


def _insert_attempt(
    transaction: PostgresTransaction,
    run_id: str,
    attempt_id: str,
    *,
    ordinal: int,
    status: str,
    lease_expires_at: datetime,
    failure_reason: str | None = None,
) -> None:
    terminal = status in {"succeeded", "failed", "cancelled"}
    transaction.execute(
        """
        INSERT INTO research_runs.attempts (
            id, run_id, ordinal, fence, generation_pin_id,
            data_generation_id, data_through_session, status,
            started_at, heartbeat_at, lease_expires_at, finished_at,
            failure_reason
        ) VALUES (%s, %s, %s, %s, %s, 'generation-diagnostic', '2026-01-31',
                  %s, %s, %s, %s, %s, %s)
        """,
        (
            attempt_id,
            run_id,
            ordinal,
            ordinal,
            f"pin-{attempt_id}",
            status,
            TEST_NOW - timedelta(minutes=15),
            TEST_NOW - timedelta(minutes=1),
            lease_expires_at,
            TEST_NOW if terminal else None,
            failure_reason,
        ),
    )


def _insert_checkpoint(
    transaction: PostgresTransaction,
    run_id: str,
    attempt_id: str,
) -> None:
    transaction.execute(
        """
        INSERT INTO research_runs.execution_checkpoints (
            id, run_id, attempt_id, ordinal, boundary_session, phase,
            completed_warmup_sessions, completed_research_sessions,
            continuation_payload, observation_payload, final_values_payload,
            observation_row_count, checkpoint_manifest_sha256, chain_sha256
        ) VALUES (
            'checkpoint-diagnostic', %s, %s, 1, '2026-01-03', 'research',
            2, 4, '{}'::jsonb, NULL, NULL, 0, %s, %s
        )
        """,
        (run_id, attempt_id, "c" * 64, "d" * 64),
    )


def _diagnose(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [os.fspath(Path(sys.executable).with_name("thesistrace-core-diagnose")), *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=15,
    )


def _database(settings: CoreSettings) -> PostgresDatabase:
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    ResearcherService(database).bootstrap(TEST_RESEARCHER)
    return database

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from uuid import UUID

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.daily_track.diagnostics import DailyTrackDiagnostics
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.researcher import ResearcherIdentity, ResearcherService

TEST_RESEARCHER = ResearcherIdentity(
    researcher_id=UUID("10000000-0000-4000-8000-000000000001"),
    email="daily-track-diagnostics@example.test",
    display_label="Daily Track Diagnostics",
)


def test_daily_track_diagnostic_reports_the_postgresql_state_matrix(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    try:
        with database.transaction() as transaction:
            _insert_track(transaction, "daily-diagnostic-idle")
            _insert_track(transaction, "daily-diagnostic-advancing")
            _insert_progression(transaction, "daily-diagnostic-advancing", "advance-active")
            _insert_attempt(
                transaction,
                "daily-diagnostic-advancing",
                "advance-active",
                "attempt-active",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="running",
                phase="calculating",
                # This is the exact in-flight progress shape emitted before the
                # child starts calculating its Target; nothing is complete yet.
                current_session=date(2026, 8, 2),
                lease_offset_seconds=600,
            )

            _insert_track(transaction, "daily-diagnostic-expired")
            _insert_progression(transaction, "daily-diagnostic-expired", "advance-expired")
            _insert_attempt(
                transaction,
                "daily-diagnostic-expired",
                "advance-expired",
                "attempt-expired",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="running",
                phase="result_ready",
                current_session=date(2026, 8, 4),
                lease_offset_seconds=-60,
            )

            _insert_track(transaction, "daily-diagnostic-retry")
            _insert_progression(
                transaction,
                "daily-diagnostic-retry",
                "advance-retry",
                next_attempt_delay_seconds=600,
            )
            _insert_attempt(
                transaction,
                "daily-diagnostic-retry",
                "advance-retry",
                "attempt-retry",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="failed",
                phase="calculating",
                current_session=date(2026, 8, 2),
                lease_offset_seconds=-60,
                failure_reason="InfrastructureFailure",
            )

            _insert_track(transaction, "daily-diagnostic-blocked")
            _insert_progression(
                transaction,
                "daily-diagnostic-blocked",
                "advance-blocked",
                status="blocked",
                current_cycle_ordinal=1,
            )
            _insert_attempt(
                transaction,
                "daily-diagnostic-blocked",
                "advance-blocked",
                "attempt-blocked",
                ordinal=3,
                cycle_attempt_ordinal=3,
                status="failed",
                phase="calculating",
                current_session=date(2026, 8, 2),
                lease_offset_seconds=-60,
                failure_reason="InfrastructureFailure",
            )
            _block_track(
                transaction,
                "daily-diagnostic-blocked",
                "advance-blocked",
                "DailyTrack exhausted its automatic infrastructure retries.",
            )

            _insert_track(transaction, "daily-diagnostic-blocked-zero")
            _insert_progression(
                transaction,
                "daily-diagnostic-blocked-zero",
                "advance-blocked-zero",
                status="blocked",
                current_cycle_ordinal=None,
            )
            _block_track(
                transaction,
                "daily-diagnostic-blocked-zero",
                "advance-blocked-zero",
                "DailyTrack target exceeds Tracking Worker capacity.",
            )

            _insert_track(transaction, "daily-diagnostic-secret")
            _insert_progression(
                transaction,
                "daily-diagnostic-secret",
                "advance-secret",
                status="blocked",
            )
            _insert_attempt(
                transaction,
                "daily-diagnostic-secret",
                "advance-secret",
                "attempt-secret",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="failed",
                phase="calculating",
                current_session=None,
                lease_offset_seconds=-60,
                failure_reason="canarySecretToken123",
            )
            _block_track(
                transaction,
                "daily-diagnostic-secret",
                "advance-secret",
                "/private/canary-secret",
            )

            _insert_track(transaction, "daily-diagnostic-numeric")
            _insert_progression(
                transaction,
                "daily-diagnostic-numeric",
                "advance-numeric",
                status="blocked",
            )
            _insert_attempt(
                transaction,
                "daily-diagnostic-numeric",
                "advance-numeric",
                "attempt-numeric",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="failed",
                phase="calculating",
                current_session=date(2026, 8, 2),
                lease_offset_seconds=-60,
                failure_reason="NumericContractError",
            )
            _block_track(
                transaction,
                "daily-diagnostic-numeric",
                "advance-numeric",
                "DailyTrack could not process the current dataset.",
            )

            _insert_track(transaction, "daily-diagnostic-stopping")
            _insert_progression(
                transaction,
                "daily-diagnostic-stopping",
                "advance-stopping",
                status="stopping",
            )
            _insert_attempt(
                transaction,
                "daily-diagnostic-stopping",
                "advance-stopping",
                "attempt-stopping",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="stopping",
                phase="staging",
                current_session=date(2026, 8, 4),
                lease_offset_seconds=600,
            )
            _set_track_status(transaction, "daily-diagnostic-stopping", "stopping")

            _insert_track(transaction, "daily-diagnostic-stopped")
            _insert_progression(
                transaction,
                "daily-diagnostic-stopped",
                "advance-stopped",
                status="cancelled",
            )
            _insert_attempt(
                transaction,
                "daily-diagnostic-stopped",
                "advance-stopped",
                "attempt-stopped",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="cancelled",
                phase="calculating",
                current_session=date(2026, 8, 2),
                lease_offset_seconds=-60,
                failure_reason="UserStopped",
            )
            _set_track_status(transaction, "daily-diagnostic-stopped", "stopped")

            _insert_track(transaction, "daily-diagnostic-published")
            _insert_progression(transaction, "daily-diagnostic-published", "advance-published")
            _insert_attempt(
                transaction,
                "daily-diagnostic-published",
                "advance-published",
                "attempt-z-first",
                ordinal=1,
                cycle_attempt_ordinal=1,
                status="failed",
                phase="calculating",
                current_session=date(2026, 8, 2),
                lease_offset_seconds=-300,
                failure_reason="WorkerLost",
            )
            _insert_attempt(
                transaction,
                "daily-diagnostic-published",
                "advance-published",
                "attempt-a-second",
                ordinal=2,
                cycle_attempt_ordinal=2,
                status="succeeded",
                phase="staging",
                current_session=date(2026, 8, 4),
                lease_offset_seconds=0,
            )
            _publish_progression(
                transaction,
                "daily-diagnostic-published",
                "advance-published",
            )

        snapshots = {
            name: DailyTrackDiagnostics(database).inspect(f"daily-diagnostic-{name}")
            for name in (
                "idle",
                "advancing",
                "expired",
                "retry",
                "blocked",
                "blocked-zero",
                "secret",
                "numeric",
                "stopping",
                "stopped",
                "published",
            )
        }

        assert snapshots["idle"]["advance"] is None
        assert snapshots["idle"]["attempts"] == []
        assert snapshots["idle"]["progress"] == {
            "phase": "idle",
            "head_session": "2026-08-01",
            "target_start_session": None,
            "target_end_session": None,
            "target_session_count": 0,
            "completed_target_sessions": 0,
            "current_session": None,
        }
        assert snapshots["advancing"]["head"]["session"] == "2026-08-01"
        assert snapshots["advancing"]["advance"]["target"] == {
            "start_session": "2026-08-02",
            "end_session": "2026-08-04",
            "session_count": 3,
        }
        assert snapshots["advancing"]["progress"] == {
            "phase": "calculating",
            "head_session": "2026-08-01",
            "target_start_session": "2026-08-02",
            "target_end_session": "2026-08-04",
            "target_session_count": 3,
            "completed_target_sessions": 0,
            "current_session": "2026-08-02",
        }
        assert snapshots["advancing"]["attempts"][0]["lease_state"] == "current"
        assert snapshots["expired"]["recovery"]["state"] == "lease_expired"
        assert snapshots["expired"]["attempts"][0]["lease_state"] == "expired"
        assert snapshots["expired"]["progress"]["completed_target_sessions"] == 0
        assert snapshots["retry"]["progress"]["phase"] == "retry_wait"
        assert snapshots["retry"]["recovery"]["state"] == "retry_wait"
        assert snapshots["retry"]["recovery"]["retry_eligible"] is True
        assert snapshots["retry"]["recovery"]["retry_at"] is not None
        assert snapshots["retry"]["attempts"][0]["retry_at"] is not None
        assert snapshots["blocked"]["track"]["status"] == "blocked"
        assert snapshots["blocked"]["advance"]["blocked"] == {
            "present": True,
            "reason_code": "INFRASTRUCTURE_RETRIES_EXHAUSTED",
        }
        assert snapshots["blocked"]["recovery"]["state"] == "blocked"
        assert snapshots["blocked"]["recovery"]["retry_eligible"] is False
        assert snapshots["blocked-zero"]["attempts"] == []
        assert snapshots["blocked-zero"]["advance"]["cycle"]["attempt"] is None
        assert snapshots["secret"]["advance"]["blocked"]["reason_code"] == (
            "UNCLASSIFIED_BLOCK"
        )
        assert snapshots["secret"]["attempts"][0]["failure_code"] == (
            "UNCLASSIFIED_FAILURE"
        )
        assert snapshots["numeric"]["attempts"][0]["failure_code"] == (
            "NUMERIC_CONTRACT_ERROR"
        )
        assert snapshots["stopping"]["progress"]["phase"] == "stopping"
        assert snapshots["stopping"]["progress"]["completed_target_sessions"] == 0
        assert snapshots["stopped"]["progress"]["phase"] == "stopped"
        assert snapshots["stopped"]["attempts"][0]["failure_code"] == "USER_STOPPED"
        assert snapshots["published"]["head"]["session"] == "2026-08-04"
        assert snapshots["published"]["progress"]["completed_target_sessions"] == 3
        assert snapshots["published"]["publication"] == {
            "state": "advance_published",
            "head_checkpoint_present": True,
            "advance_checkpoint_present": True,
        }
        assert snapshots["published"]["private_artifacts"] == {
            "head_checkpoint_present": True,
            "advance_checkpoint_present": True,
        }
        assert [
            attempt["id"] for attempt in snapshots["published"]["attempts"]
        ] == ["attempt-z-first", "attempt-a-second"]
        serialized = json.dumps(snapshots, sort_keys=True)
        for forbidden in (
            "canarySecretToken123",
            "/private/canary-secret",
            "terminal_strategy_state",
            "provenance",
            "manifest",
            "checksum",
            "object_key",
            "physical_path",
        ):
            assert forbidden not in serialized
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z",
            str(snapshots["advancing"]["diagnosed_at"]),
        )
    finally:
        database.close()


def test_daily_track_diagnostic_cli_uses_only_postgresql_and_preserves_run_contract(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        with database.transaction() as transaction:
            _insert_track(transaction, "daily-diagnostic-cli")
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
    first = _diagnose(postgres_only_environment, "daily-track", "daily-diagnostic-cli")
    second = _diagnose(
        unavailable_storage_environment,
        "daily-track",
        "daily-diagnostic-cli",
    )

    assert first.returncode == second.returncode == 0
    first_snapshot = json.loads(first.stdout)
    second_snapshot = json.loads(second.stdout)
    assert first.stdout == json.dumps(first_snapshot, indent=2, sort_keys=True) + "\n"
    assert first.stderr == second.stderr == ""
    first_snapshot.pop("diagnosed_at")
    second_snapshot.pop("diagnosed_at")
    assert first_snapshot == second_snapshot
    assert "canary" not in first.stdout + first.stderr

    missing = _diagnose(
        unavailable_storage_environment,
        "daily-track",
        "daily-diagnostic-missing",
    )
    assert missing.returncode == 3
    assert missing.stdout == ""
    assert missing.stderr == "DAILY_TRACK_NOT_FOUND\n"

    invalid = _diagnose(
        unavailable_storage_environment,
        "daily-track",
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
        "daily-track",
        "daily-diagnostic-cli",
    )
    assert unavailable.returncode == 4
    assert unavailable.stdout == ""
    assert unavailable.stderr == "POSTGRESQL_UNAVAILABLE\n"

    research_run_invalid = _diagnose(
        unavailable_storage_environment,
        "research-run",
        "/private/canary-secret",
    )
    assert research_run_invalid.returncode == 2
    assert research_run_invalid.stdout == ""
    assert research_run_invalid.stderr == "INVALID_USAGE\n"


def _insert_track(transaction: PostgresTransaction, track_id: str) -> None:
    origin_manifest = _digest(f"{track_id}:origin")
    transaction.execute(
        """
        INSERT INTO research_runs.run_ownership (researcher_id, run_id)
        VALUES (%s, %s)
        """,
        (TEST_RESEARCHER.researcher_id, f"seed-{track_id}"),
    )
    transaction.execute(
        """
        INSERT INTO daily_tracks.tracks (
            researcher_id, id, status, seed_run_id, origin
        ) VALUES (%s, %s, 'active', %s, '{}'::jsonb)
        """,
        (TEST_RESEARCHER.researcher_id, track_id, f"seed-{track_id}"),
    )
    transaction.execute(
        """
        INSERT INTO daily_tracks.session_checkpoints (
            manifest_sha256, track_id, progression_id,
            predecessor_manifest_sha256, boundary_session,
            terminal_strategy_state, data_generation_id, provenance
        ) VALUES (%s, %s, NULL, NULL, '2026-08-01', '{}'::jsonb,
                  'generation-origin', '{}'::jsonb)
        """,
        (origin_manifest, track_id),
    )
    transaction.execute(
        """
        INSERT INTO daily_tracks.session_tracking_states (
            track_id, origin_session, origin_checkpoint_manifest_sha256,
            current_checkpoint_manifest_sha256
        ) VALUES (%s, '2026-08-01', %s, %s)
        """,
        (track_id, origin_manifest, origin_manifest),
    )


def _insert_progression(
    transaction: PostgresTransaction,
    track_id: str,
    progression_id: str,
    *,
    status: str = "running",
    current_cycle_ordinal: int | None = 1,
    next_attempt_delay_seconds: int | None = None,
) -> None:
    transaction.execute(
        """
        INSERT INTO daily_tracks.session_progressions (
            id, track_id, predecessor_checkpoint_manifest_sha256,
            target_sessions, target_start_session, target_end_session,
            planning_data_generation_id, current_cycle_ordinal,
            next_attempt_eligible_at, queue_position, status, provenance,
            finished_at
        ) VALUES (
            %s, %s, %s, ARRAY['2026-08-02', '2026-08-03', '2026-08-04']::date[],
            '2026-08-02', '2026-08-04', 'generation-target', %s,
            transaction_timestamp() + make_interval(secs => %s), 1,
            %s, '{}'::jsonb,
            CASE WHEN %s THEN transaction_timestamp() ELSE NULL END
        )
        """,
        (
            progression_id,
            track_id,
            _digest(f"{track_id}:origin"),
            current_cycle_ordinal,
            next_attempt_delay_seconds,
            status,
            status in {"blocked", "cancelled"},
        ),
    )


def _insert_attempt(
    transaction: PostgresTransaction,
    track_id: str,
    progression_id: str,
    attempt_id: str,
    *,
    ordinal: int,
    cycle_attempt_ordinal: int,
    status: str,
    phase: str,
    current_session: date | None,
    lease_offset_seconds: int,
    failure_reason: str | None = None,
) -> None:
    terminal = status in {"succeeded", "failed", "cancelled"}
    transaction.execute(
        """
        INSERT INTO daily_tracks.session_progression_attempts (
            id, progression_id, track_id, ordinal, cycle_ordinal,
            cycle_attempt_ordinal, fence, generation_pin_id,
            data_generation_id, data_through_session, status,
            execution_phase, current_session, started_at, heartbeat_at,
            lease_expires_at, finished_at, failure_reason
        ) VALUES (
            %s, %s, %s, %s, 1, %s, %s, %s, 'generation-target',
            '2026-08-04', %s, %s, %s,
            transaction_timestamp() - interval '15 minutes',
            transaction_timestamp() - interval '1 minute',
            transaction_timestamp() + make_interval(secs => %s),
            CASE WHEN %s THEN transaction_timestamp() ELSE NULL END, %s
        )
        """,
        (
            attempt_id,
            progression_id,
            track_id,
            ordinal,
            cycle_attempt_ordinal,
            ordinal,
            f"pin-{attempt_id}",
            status,
            phase,
            current_session,
            lease_offset_seconds,
            terminal,
            failure_reason,
        ),
    )


def _block_track(
    transaction: PostgresTransaction,
    track_id: str,
    progression_id: str,
    reason: str,
) -> None:
    transaction.execute(
        """
        UPDATE daily_tracks.tracks
        SET status = 'blocked', blocked_progression_id = %s, blocked_reason = %s
        WHERE id = %s
        """,
        (progression_id, reason, track_id),
    )


def _set_track_status(
    transaction: PostgresTransaction,
    track_id: str,
    status: str,
) -> None:
    transaction.execute(
        "UPDATE daily_tracks.tracks SET status = %s WHERE id = %s",
        (status, track_id),
    )


def _publish_progression(
    transaction: PostgresTransaction,
    track_id: str,
    progression_id: str,
) -> None:
    checkpoint_manifest = _digest(f"{track_id}:published")
    transaction.execute(
        """
        INSERT INTO daily_tracks.session_checkpoints (
            manifest_sha256, track_id, progression_id,
            predecessor_manifest_sha256, boundary_session,
            terminal_strategy_state, data_generation_id, provenance
        ) VALUES (%s, %s, %s, %s, '2026-08-04', '{}'::jsonb,
                  'generation-target', '{}'::jsonb)
        """,
        (
            checkpoint_manifest,
            track_id,
            progression_id,
            _digest(f"{track_id}:origin"),
        ),
    )
    transaction.execute(
        """
        UPDATE daily_tracks.session_progressions
        SET status = 'succeeded', checkpoint_manifest_sha256 = %s,
            finished_at = transaction_timestamp(), next_attempt_eligible_at = NULL,
            queue_position = NULL
        WHERE id = %s
        """,
        (checkpoint_manifest, progression_id),
    )
    transaction.execute(
        """
        UPDATE daily_tracks.session_tracking_states
        SET current_checkpoint_manifest_sha256 = %s,
            updated_at = transaction_timestamp()
        WHERE track_id = %s
        """,
        (checkpoint_manifest, track_id),
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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

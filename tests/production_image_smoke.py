from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from threading import Event, Thread

import boto3

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import MountedDatasetHeadStore
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.product_state import product_state_counts
from thesistrace.publication import Publication, PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_run.result import (
    RESULT_DAILY_PARTITION_PREFIX,
    read_result_bundle,
)

EXPECTED_OVERVIEW = {
    "market_coverage": {"start": "2009-12-07", "end": "2026-08-05"},
    "financial_coverage": {
        "start": "2010-01-01",
        "observation_through_session": "2026-08-05",
        "reconciliation_status": "complete",
        "historical_reconciliation_watermark": "2026-08-05",
        "revision_coverage": "source-dated-and-first-observed-corrections",
        "seed_policy": "latest-pre-start-annual-flow-and-balance-facts",
        "sparse_facts": True,
    },
    "data_through_session": "2026-08-05",
    "last_market_refresh_at": None,
    "market_research_readiness": True,
    "financial_research_readiness": True,
}


def main() -> None:
    phases = {
        "before",
        "expire-worker-loss",
        "checkpointed",
        "recovered",
        "persisted",
        "transient-failed",
        "after",
        "reset-ready",
        "worker-events",
        "reset",
    }
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        raise SystemExit(f"usage: production_image_smoke.py {{{'|'.join(sorted(phases))}}}")
    api_origin = _required_environment("THESISTRACE_TEST_API_ORIGIN").rstrip("/")
    web_origin = _required_environment("THESISTRACE_TEST_WEB_ORIGIN").rstrip("/")
    state_path = Path(_required_environment("THESISTRACE_TEST_SMOKE_STATE"))
    settings = CoreSettings.from_environment()
    assert "THESISTRACE_TUSHARE_TOKEN" not in os.environ
    _assert_web_image(web_origin)
    phase = sys.argv[1]
    if phase == "before":
        result = _before_restart(
            api_origin,
            settings,
            image_identity=_required_environment("THESISTRACE_TEST_IMAGE_ID"),
            mounted_data_sha256=_directory_sha256(settings.data_mount),
        )
        state_path.write_text(json.dumps(result, sort_keys=True))
    else:
        expected = json.loads(state_path.read_text())
        if phase == "expire-worker-loss":
            result = _expire_worker_loss(settings, expected)
        elif phase == "checkpointed":
            result = _verify_checkpointed_state(api_origin, settings, expected)
        elif phase == "recovered":
            result = _after_worker_loss(api_origin, settings, expected)
        elif phase == "persisted":
            result = _verify_persisted_state(api_origin, settings, expected)
        elif phase == "transient-failed":
            result = _verify_transient_retry_wait(settings, expected)
        elif phase == "after":
            result = _after_restart(api_origin, settings, expected)
        elif phase == "reset-ready":
            result = _verify_reset_ready(settings, expected)
        elif phase == "worker-events":
            result = _verify_worker_events(
                Path(_required_environment("THESISTRACE_TEST_WORKER_EVENTS"))
            )
        else:
            result = _after_product_state_reset(api_origin, settings, expected)
        expected.update(result)
        state_path.write_text(json.dumps(expected, sort_keys=True))
    print(json.dumps(result, sort_keys=True))


def _before_restart(
    api_origin: str,
    settings: CoreSettings,
    *,
    image_identity: str,
    mounted_data_sha256: str,
) -> dict[str, object]:
    overview = _request_json(api_origin, "GET", "/api/data")
    _assert_expected_overview(overview)
    catalog = _request_json(api_origin, "GET", "/api/alpha/catalog")
    identifiers = {field["identifier"] for field in catalog["fields"]}
    assert identifiers >= {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "revenue",
        "net_profit",
        "operating_cash_flow",
        "assets",
        "liabilities",
        "equity",
    }
    assert identifiers.isdisjoint(
        {
            "open_adj",
            "high_adj",
            "low_adj",
            "close_adj",
            "volume_shares",
            "turnover_amount_cny",
        }
    )
    assert {builtin["identifier"] for builtin in catalog["builtins"]} >= {
        "rank",
        "lag",
        "ts_mean",
    }
    _assert_private_operator_installed()
    folders = _request_json(api_origin, "GET", "/api/research-folders")
    assert folders["items"] == [
        {
            "id": "folder_default",
            "name": "Default",
            "is_default": True,
            "created_at": folders["items"][0]["created_at"],
        }
    ]
    for obsolete_path in (
        "/api/definitions",
        "/api/definitions/definition_obsolete",
    ):
        assert _request_status(api_origin, "GET", obsolete_path) == 404
    factor_accepted = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        {
            "request_id": "production-image-smoke-factor-run",
            "folder_id": "folder_default",
            "name": "Production Image Smoke Factor Evaluation",
            "hypothesis": "Factor evidence remains executable offline.",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "formula": "rank(close) + rank(revenue)",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "factor_evaluation",
        },
    )
    assert factor_accepted["status"] == "queued"
    assert factor_accepted["research_kind"] == "factor_evaluation"
    factor_run_id = str(factor_accepted["id"])
    factor_detail = _wait_for_run(
        api_origin,
        factor_run_id,
        research_kind="factor_evaluation",
    )
    factor_tracking_error = _request_error_json(
        api_origin,
        "POST",
        f"/api/research-runs/{factor_run_id}/daily-tracks",
        {"request_id": "production-image-smoke-factor-track"},
    )
    assert factor_tracking_error == (
        409,
        {"detail": "Start Tracking requires a Strategy Backtest Result"},
    )

    accepted = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        {
            "request_id": "production-image-smoke-run",
            "folder_id": "folder_default",
            "name": "Production Image Smoke Alpha",
            "hypothesis": "Prepared mounted data remains executable offline.",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "formula": "rank(close) + rank(revenue)",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "strategy_backtest",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
        },
    )
    assert accepted["status"] == "queued"
    assert accepted["research_kind"] == "strategy_backtest"
    run_id = str(accepted["id"])
    detail = _wait_for_run(
        api_origin,
        run_id,
        research_kind="strategy_backtest",
    )
    assert (
        _request_status(
            api_origin,
            "POST",
            f"/api/research-runs/{run_id}/rerun",
            {"request_id": "obsolete-rerun"},
        )
        == 404
    )
    track = _request_json(
        api_origin,
        "POST",
        f"/api/research-runs/{run_id}/daily-tracks",
        {"request_id": "production-image-smoke-track"},
    )
    assert track["status"] == "active"
    market_run = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        {
            "request_id": "production-image-smoke-market-run",
            "folder_id": "folder_default",
            "name": "Production Image Smoke Market Alpha",
            "hypothesis": "Market-only tracking remains independent of finance.",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "formula": "close",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "strategy_backtest",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
        },
    )
    market_detail = _wait_for_run(
        api_origin,
        str(market_run["id"]),
        research_kind="strategy_backtest",
    )
    assert market_detail["status"] == "succeeded"
    market_track = _request_json(
        api_origin,
        "POST",
        f"/api/research-runs/{market_run['id']}/daily-tracks",
        {"request_id": "production-image-smoke-market-track"},
    )
    assert market_track["status"] == "active"
    stop_run = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        {
            "request_id": "production-image-smoke-stop-run",
            "folder_id": "folder_default",
            "name": "Production Image Smoke Stop Alpha",
            "hypothesis": "A running Tracking child can be stopped safely.",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "formula": "rank(close) + rank(revenue)",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "strategy_backtest",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
        },
    )
    stop_detail = _wait_for_run(
        api_origin,
        str(stop_run["id"]),
        research_kind="strategy_backtest",
    )
    assert stop_detail["status"] == "succeeded"
    stop_track = _request_json(
        api_origin,
        "POST",
        f"/api/research-runs/{stop_run['id']}/daily-tracks",
        {"request_id": "production-image-smoke-running-stop-track"},
    )
    recovery_run = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        {
            "request_id": "production-image-smoke-worker-loss-run",
            "folder_id": "folder_default",
            "name": "Production Image Smoke Long Recovery",
            "hypothesis": "A long Run resumes from its durable Chunk after Worker loss.",
            "start_date": "2010-01-04",
            "end_date": "2026-08-05",
            "formula": "rank(pct_change(close, 20))",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "factor_evaluation",
        },
    )
    recovery_checkpoint_count = _wait_for_checkpoint(
        api_origin,
        str(recovery_run["id"]),
    )
    recovery_checkpoint = _checkpoint_state(settings, str(recovery_run["id"]))
    assert recovery_checkpoint["checkpoint_count"] == recovery_checkpoint_count
    assert recovery_checkpoint["active_pin_count"] == 1
    factor_durable = _durable_result(
        settings,
        factor_run_id,
        research_kind="factor_evaluation",
    )
    durable = _durable_result(
        settings,
        run_id,
        research_kind="strategy_backtest",
    )
    canonical_identity = _canonical_identity(settings)
    return {
        "image_identity": image_identity,
        "canonical_identity": canonical_identity,
        "factor_run_id": factor_run_id,
        "factor_research_kind": factor_detail["research_kind"],
        "factor_public_result_sha256": hashlib.sha256(
            canonical_json_bytes(factor_detail)
        ).hexdigest(),
        "factor_result_manifest_sha256": factor_durable["manifest_sha256"],
        "factor_result_object_names": factor_durable["result_object_names"],
        "factor_payload_names": factor_durable["payload_names"],
        "run_id": run_id,
        "strategy_research_kind": detail["research_kind"],
        "track_id": track["id"],
        "market_run_id": market_run["id"],
        "market_track_id": market_track["id"],
        "stop_run_id": stop_run["id"],
        "stop_track_id": stop_track["id"],
        "recovery_run_id": recovery_run["id"],
        "recovery_checkpoint_count": recovery_checkpoint_count,
        "recovery_checkpoint_manifests": recovery_checkpoint["checkpoint_manifest_sha256s"],
        "public_result_sha256": hashlib.sha256(canonical_json_bytes(detail)).hexdigest(),
        "result_manifest_sha256": durable["manifest_sha256"],
        "strategy_result_object_names": durable["result_object_names"],
        "strategy_payload_names": durable["payload_names"],
        "attempt_count": durable["attempt_count"],
        "execution_snapshot": durable["execution_snapshot"],
        "overview": overview,
        "mounted_data_sha256": mounted_data_sha256,
    }


def _expire_worker_loss(settings: CoreSettings, expected: dict[str, object]) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET lease_expires_at = now() - interval '1 second'
                WHERE run_id = %s AND status = 'running'
                """,
                (str(expected["recovery_run_id"]),),
            )
        assert updated.rowcount == 1
    finally:
        database.close()
    checkpoint = _checkpoint_state(settings, str(expected["recovery_run_id"]))
    assert checkpoint["checkpoint_count"] >= expected["recovery_checkpoint_count"]
    assert checkpoint["active_pin_count"] == 1
    return {
        "worker_loss_checkpoint_count": checkpoint["checkpoint_count"],
        "worker_loss_checkpoint_manifests": checkpoint["checkpoint_manifest_sha256s"],
        "worker_loss_lease_expired": True,
    }


def _verify_checkpointed_state(
    api_origin: str,
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    recovery_run_id = str(expected["recovery_run_id"])
    detail = _request_json(api_origin, "GET", f"/api/research-runs/{recovery_run_id}")
    assert detail["status"] == "running"
    assert detail["research_kind"] == "factor_evaluation"
    assert "result" not in detail
    checkpoint = _checkpoint_state(settings, recovery_run_id)
    assert checkpoint["checkpoint_count"] == expected["worker_loss_checkpoint_count"]
    assert checkpoint["checkpoint_manifest_sha256s"] == expected["worker_loss_checkpoint_manifests"]
    assert checkpoint["active_pin_count"] == 1
    assert _canonical_identity(settings) == expected["canonical_identity"]
    return {
        "checkpoint_survived_application_and_database_restart": True,
        "checkpointed_factor_research_kind": detail["research_kind"],
    }


def _after_worker_loss(
    api_origin: str,
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    recovery_run_id = str(expected["recovery_run_id"])
    recovered = _wait_for_run(
        api_origin,
        recovery_run_id,
        research_kind="factor_evaluation",
        timeout=180,
    )
    durable = _durable_result(
        settings,
        recovery_run_id,
        research_kind="factor_evaluation",
    )
    assert durable["attempt_count"] == 2
    assert durable["result_object_names"] == ["factor_summary"]
    assert durable["active_pin_count"] == 0
    attempts = durable["execution_snapshot"]["attempts"]
    assert attempts[0]["status"] == "failed"
    assert attempts[1]["status"] == "succeeded"
    cancel_run = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        {
            "request_id": "production-image-smoke-cancel-run",
            "folder_id": "folder_default",
            "name": "Production Image Smoke Cancellation",
            "hypothesis": "A healthy supervisor confirms cancellation after child exit.",
            "start_date": "2010-01-04",
            "end_date": "2026-08-05",
            "formula": "rank(pct_change(close, 20))",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "factor_evaluation",
        },
    )
    cancel_run_id = str(cancel_run["id"])
    _wait_for_checkpoint(api_origin, cancel_run_id)
    cancel_started = time.monotonic()
    cancelled = _request_json(
        api_origin,
        "POST",
        f"/api/research-runs/{cancel_run_id}/cancel",
        {"request_id": "production-image-smoke-cancel-command"},
    )
    assert cancelled["status"] in {"cancelling", "cancelled"}
    terminal = _wait_for_run_status(api_origin, cancel_run_id, "cancelled", timeout=5)
    cancellation_latency_ms = round((time.monotonic() - cancel_started) * 1000, 3)
    assert cancellation_latency_ms <= 5_000
    cancelled_state = _run_lifecycle_state(settings, cancel_run_id)
    assert cancelled_state == {
        "active_pin_count": 0,
        "checkpoint_count": 0,
        "result_manifest_sha256": None,
        "research_kind": "factor_evaluation",
        "status": "cancelled",
    }
    return {
        "recovery_result_manifest_sha256": durable["manifest_sha256"],
        "recovery_result_object_names": durable["result_object_names"],
        "recovery_payload_names": durable["payload_names"],
        "recovery_attempt_count": durable["attempt_count"],
        "recovery_public_result_sha256": hashlib.sha256(
            canonical_json_bytes(recovered)
        ).hexdigest(),
        "cancel_run_id": cancel_run_id,
        "cancel_research_kind": terminal["research_kind"],
        "cancel_status": terminal["status"],
        "cancel_latency_ms": cancellation_latency_ms,
        "cancel_cleanup": cancelled_state,
        "recovered_status": recovered["status"],
    }


def _after_restart(
    api_origin: str,
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    overview = _request_json(api_origin, "GET", "/api/data")
    run_id = str(expected["run_id"])
    detail = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
    durable = _durable_result(
        settings,
        run_id,
        research_kind="strategy_backtest",
    )
    track_id = str(expected["track_id"])
    market_track_id = str(expected["market_track_id"])
    market_advanced = _wait_for_track(api_origin, market_track_id, "2026-08-11")
    assert market_advanced["status"] == "active"
    subprocess.run(
        [
            sys.executable,
            "/smoke/browser/prepare_image_smoke_data.py",
            "recovered",
        ],
        check=True,
        timeout=60,
    )
    retried = _request_json(
        api_origin,
        "POST",
        f"/api/daily-tracks/{track_id}/retry",
        {"request_id": "production-image-smoke-financial-retry"},
    )
    assert retried["status"] in {"active", "catching_up"}
    advanced = _wait_for_track(api_origin, track_id, "2026-08-11")
    assert advanced["status"] == "active"
    assert advanced["blocked_reason"] is None
    stop_track_id = str(expected["stop_track_id"])
    stopped = _retry_and_stop_running_track(api_origin, stop_track_id)
    assert stopped["status"] == "stopped"
    with open_core_runtime(settings) as runtime:
        equivalence = runtime.daily_tracks.verify_persisted_equivalence(track_id)
    assert equivalence.status == "equivalent"
    assert equivalence.head_session == "2026-08-11"
    stopped = _request_json(
        api_origin,
        "POST",
        f"/api/daily-tracks/{track_id}/stop",
        {"request_id": "production-image-smoke-stop"},
    )
    assert stopped["status"] == "stopped"
    assert _request_status(api_origin, "DELETE", f"/api/daily-tracks/{track_id}") == 204
    assert _request_status(api_origin, "GET", f"/api/daily-tracks/{track_id}") == 404
    market_stopped = _request_json(
        api_origin,
        "POST",
        f"/api/daily-tracks/{market_track_id}/stop",
        {"request_id": "production-image-smoke-market-stop"},
    )
    assert market_stopped["status"] == "stopped"
    assert _request_status(api_origin, "DELETE", f"/api/daily-tracks/{market_track_id}") == 204
    reset_run = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        {
            "request_id": "production-image-smoke-reset-checkpoint-run",
            "folder_id": "folder_default",
            "name": "Production Image Smoke Reset Checkpoint",
            "hypothesis": "Product State reset removes active private execution state.",
            "start_date": "2010-01-04",
            "end_date": "2026-08-05",
            "formula": "rank(pct_change(close, 20))",
            "universe": "top300",
            "neutralization": "none",
            "research_kind": "factor_evaluation",
        },
    )
    reset_run_id = str(reset_run["id"])
    _wait_for_checkpoint(api_origin, reset_run_id)
    reset_checkpoint = _checkpoint_state(settings, reset_run_id)
    assert reset_checkpoint["checkpoint_count"] >= 1
    assert reset_checkpoint["active_pin_count"] == 1
    product_state_before_reset = _product_state_counts(settings)
    assert product_state_before_reset["research_runs"] >= 1
    assert product_state_before_reset["research_attempts"] >= 1
    assert product_state_before_reset["research_checkpoints"] >= 1
    assert product_state_before_reset["daily_tracks"] >= 1
    assert product_state_before_reset["publication_manifests"] >= 1
    assert product_state_before_reset["rustfs_product_objects"] >= 1
    reset_overview = _request_json(api_origin, "GET", "/api/data")
    return {
        "run_id": run_id,
        "status": detail["status"],
        "result_manifest_sha256": durable["manifest_sha256"],
        "attempt_count": durable["attempt_count"],
        "financial_research_readiness": overview["financial_research_readiness"],
        "equivalence": equivalence.status,
        "strategy_session": advanced["strategy_session"],
        "market_strategy_session": market_advanced["strategy_session"],
        "reset_mounted_data_sha256": _directory_sha256(settings.data_mount),
        "reset_canonical_identity": _canonical_identity(settings),
        "reset_overview": reset_overview,
        "running_stop_confirmed": True,
        "track_deleted": True,
        "reset_checkpoint_run_id": reset_run_id,
        "reset_checkpoint_manifests": reset_checkpoint["checkpoint_manifest_sha256s"],
        "product_state_before_reset": product_state_before_reset,
    }


def _verify_persisted_state(
    api_origin: str,
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    overview = _request_json(api_origin, "GET", "/api/data")
    assert overview == expected["overview"]
    _assert_expected_overview(overview)
    run_id = str(expected["run_id"])
    detail = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
    assert detail["status"] == "succeeded"
    assert detail["research_kind"] == "strategy_backtest"
    assert (
        hashlib.sha256(canonical_json_bytes(detail)).hexdigest() == expected["public_result_sha256"]
    )
    durable = _durable_result(
        settings,
        run_id,
        research_kind="strategy_backtest",
    )
    assert durable["manifest_sha256"] == expected["result_manifest_sha256"]
    assert durable["attempt_count"] == expected["attempt_count"] == 1
    assert durable["execution_snapshot"] == expected["execution_snapshot"]
    assert durable["result_object_names"] == expected["strategy_result_object_names"]
    assert durable["payload_names"] == expected["strategy_payload_names"]

    factor_run_id = str(expected["factor_run_id"])
    factor_detail = _request_json(
        api_origin,
        "GET",
        f"/api/research-runs/{factor_run_id}",
    )
    assert factor_detail["status"] == "succeeded"
    assert factor_detail["research_kind"] == "factor_evaluation"
    assert (
        hashlib.sha256(canonical_json_bytes(factor_detail)).hexdigest()
        == expected["factor_public_result_sha256"]
    )
    factor_durable = _durable_result(
        settings,
        factor_run_id,
        research_kind="factor_evaluation",
    )
    assert factor_durable["manifest_sha256"] == expected["factor_result_manifest_sha256"]
    assert factor_durable["result_object_names"] == expected["factor_result_object_names"]
    assert factor_durable["payload_names"] == expected["factor_payload_names"]

    recovery_run_id = str(expected["recovery_run_id"])
    recovery_detail = _request_json(
        api_origin,
        "GET",
        f"/api/research-runs/{recovery_run_id}",
    )
    assert recovery_detail["research_kind"] == "factor_evaluation"
    assert (
        hashlib.sha256(canonical_json_bytes(recovery_detail)).hexdigest()
        == expected["recovery_public_result_sha256"]
    )
    recovery_durable = _durable_result(
        settings,
        recovery_run_id,
        research_kind="factor_evaluation",
    )
    assert recovery_durable["manifest_sha256"] == expected["recovery_result_manifest_sha256"]
    assert recovery_durable["attempt_count"] == expected["recovery_attempt_count"] == 2
    assert recovery_durable["active_pin_count"] == 0

    cancelled = _request_json(
        api_origin,
        "GET",
        f"/api/research-runs/{expected['cancel_run_id']}",
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["research_kind"] == "factor_evaluation"
    assert _directory_sha256(settings.data_mount) == expected["mounted_data_sha256"]
    assert _canonical_identity(settings) == expected["canonical_identity"]
    track = _request_json(
        api_origin,
        "GET",
        f"/api/daily-tracks/{expected['track_id']}",
    )
    assert track["status"] == "active"
    assert track["strategy_session"] == "2026-08-05"
    return {
        "application_and_database_restart_verified": True,
        "factor_result_manifest_preserved": factor_durable["manifest_sha256"],
        "recovered_factor_result_manifest_preserved": recovery_durable["manifest_sha256"],
        "persisted_result_manifest_sha256": durable["manifest_sha256"],
    }


def _verify_transient_retry_wait(
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    track_id = str(expected["track_id"])
    market_track_id = str(expected["market_track_id"])
    database = PostgresDatabase(settings.database_url)
    database.open()
    deadline = time.monotonic() + 20
    poll_interval = Event()
    row: dict[str, object] | None = None
    try:
        while time.monotonic() < deadline:
            with database.transaction() as transaction:
                row = transaction.execute(
                    """
                    SELECT financial.status AS financial_status,
                           financial.blocked_reason,
                           market.status AS market_status,
                           progression.next_attempt_eligible_at > now() AS retry_wait,
                           attempt.cycle_attempt_ordinal,
                           attempt.failure_reason
                    FROM daily_tracks.tracks AS financial
                    JOIN daily_tracks.tracks AS market ON market.id = %s
                    LEFT JOIN LATERAL (
                        SELECT * FROM daily_tracks.session_progressions
                        WHERE track_id = market.id
                        ORDER BY created_at DESC LIMIT 1
                    ) AS progression ON true
                    LEFT JOIN LATERAL (
                        SELECT * FROM daily_tracks.session_progression_attempts
                        WHERE progression_id = progression.id
                        ORDER BY ordinal DESC LIMIT 1
                    ) AS attempt ON true
                    WHERE financial.id = %s
                    """,
                    (market_track_id, track_id),
                ).fetchone()
            if (
                row is not None
                and row["financial_status"] == "blocked"
                and row["market_status"] == "active"
                and row["retry_wait"] is True
            ):
                break
            poll_interval.wait(0.02)
        else:
            raise AssertionError({"transient_retry_timeout": True, "state": row})
    finally:
        database.close()
    assert row is not None
    assert row["blocked_reason"] == ("Financial Coverage ends before the next Research Session.")
    assert row["cycle_attempt_ordinal"] == 1
    assert row["failure_reason"] == "InfrastructureFailure"
    return {
        "transient_retry_attempt": row["cycle_attempt_ordinal"],
        "transient_retry_wait_verified": True,
    }


def _retry_and_stop_running_track(
    api_origin: str,
    track_id: str,
) -> dict[str, object]:
    stopped: dict[str, object] = {}
    failure: list[BaseException] = []

    def stop_when_running() -> None:
        try:
            attempt_id = _wait_for_running_tracking_attempt(track_id)
            stopped.update(
                _request_json(
                    api_origin,
                    "POST",
                    f"/api/daily-tracks/{track_id}/stop",
                    {"request_id": "production-image-smoke-running-stop"},
                )
            )
            stopped["observed_running_attempt_id"] = attempt_id
        except BaseException as error:
            failure.append(error)

    watcher = Thread(target=stop_when_running, daemon=True)
    watcher.start()
    retried = _request_json(
        api_origin,
        "POST",
        f"/api/daily-tracks/{track_id}/retry",
        {"request_id": "production-image-smoke-stop-track-retry"},
    )
    assert retried["status"] in {"active", "catching_up"}
    watcher.join(timeout=10)
    assert not watcher.is_alive()
    if failure:
        raise failure[0]
    assert stopped["status"] in {"stopping", "stopped"}
    terminal = _wait_for_track_status(api_origin, track_id, "stopped")
    terminal["observed_running_attempt_id"] = stopped["observed_running_attempt_id"]
    return terminal


def _wait_for_running_tracking_attempt(track_id: str) -> str:
    settings = CoreSettings.from_environment()
    database = PostgresDatabase(settings.database_url)
    database.open()
    deadline = time.monotonic() + 10
    poll_interval = Event()
    try:
        while time.monotonic() < deadline:
            with database.transaction() as transaction:
                row = transaction.execute(
                    """
                    SELECT id
                    FROM daily_tracks.session_progression_attempts
                    WHERE track_id = %s AND status = 'running'
                    ORDER BY ordinal DESC
                    LIMIT 1
                    """,
                    (track_id,),
                ).fetchone()
            if row is not None:
                return str(row["id"])
            poll_interval.wait(0.001)
    finally:
        database.close()
    raise AssertionError({"running_attempt_timeout": True, "track_id": track_id})


def _after_product_state_reset(
    api_origin: str,
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    overview = _request_json(api_origin, "GET", "/api/data")
    expected_overview = dict(expected["reset_overview"])
    expected_overview["last_financial_refresh_at"] = None
    assert overview == expected_overview
    assert _directory_sha256(settings.data_mount) == expected["reset_mounted_data_sha256"]
    assert _canonical_identity(settings) == expected["reset_canonical_identity"]
    stale_run_ids = {
        str(expected[key])
        for key in (
            "factor_run_id",
            "run_id",
            "market_run_id",
            "stop_run_id",
            "recovery_run_id",
            "cancel_run_id",
            "reset_checkpoint_run_id",
        )
    }
    for run_id in stale_run_ids:
        assert _request_status(api_origin, "GET", f"/api/research-runs/{run_id}") == 404
    stale_track_ids = {
        str(expected[key]) for key in ("track_id", "market_track_id", "stop_track_id")
    }
    for track_id in stale_track_ids:
        assert _request_status(api_origin, "GET", f"/api/daily-tracks/{track_id}") == 404
    assert _request_json(api_origin, "GET", "/api/research-runs")["items"] == []
    assert _request_json(api_origin, "GET", "/api/daily-tracks")["items"] == []
    product_state_after_reset = _product_state_counts(settings)
    assert product_state_after_reset == {key: 0 for key in product_state_after_reset}
    return {
        "canonical_data_preserved_by_reset": True,
        "canonical_identity_after_reset": _canonical_identity(settings),
        "product_state_after_reset": product_state_after_reset,
        "product_state_reset_verified": True,
        "stale_research_reference_count": len(stale_run_ids),
        "stale_tracking_reference_count": len(stale_track_ids),
    }


def _verify_reset_ready(
    settings: CoreSettings,
    expected: dict[str, object],
) -> dict[str, object]:
    checkpoint = _checkpoint_state(settings, str(expected["reset_checkpoint_run_id"]))
    observed_before_stop = list(expected["reset_checkpoint_manifests"])
    observed_after_stop = list(checkpoint["checkpoint_manifest_sha256s"])
    assert observed_after_stop[: len(observed_before_stop)] == observed_before_stop
    assert checkpoint["checkpoint_count"] == len(observed_after_stop)
    assert checkpoint["checkpoint_count"] >= 1
    assert checkpoint["active_pin_count"] == 1
    return {
        "reset_active_checkpoint_verified_after_worker_stop": True,
        "reset_checkpoint_manifests_after_worker_stop": observed_after_stop,
    }


def _verify_worker_events(path: Path) -> dict[str, object]:
    events: list[dict[str, object]] = []
    for line in path.read_text().splitlines():
        payload = line.partition("|")[2].strip()
        if not payload.startswith("{"):
            continue
        value = json.loads(payload)
        if isinstance(value, dict):
            events.append(value)

    lifecycle_names = {
        "research_execution_child_started",
        "research_execution_child_exited",
        "research_execution_chunk_committed",
        "research_checkpoint_committed",
        "research_result_published",
        "research_run_succeeded",
    }
    lifecycle = [event for event in events if event.get("event") in lifecycle_names]
    assert lifecycle
    for event in lifecycle:
        assert event["component"] == "research_worker"
        assert event["worker_role"] == "research"
        assert str(event["run_id"]).startswith("run_")
        assert str(event["attempt_id"]).startswith("attempt_")
        assert "resource_type" not in event
        assert "resource_id" not in event
        assert "research_kind" not in event
        assert "child_pid" not in event
        assert "boundary_session" not in event
        assert "data_io" not in event

    started = [
        event
        for event in lifecycle
        if event["event"] == "research_execution_child_started"
    ]
    assert started

    exited = [
        event
        for event in lifecycle
        if event["event"] == "research_execution_child_exited"
    ]
    assert exited

    committed = [
        event
        for event in lifecycle
        if event["event"] == "research_execution_chunk_committed"
    ]
    assert committed
    return {
        "worker_event_contract_verified": True,
        "worker_lifecycle_event_count": len(lifecycle),
    }


def _wait_for_run(
    api_origin: str,
    run_id: str,
    *,
    research_kind: str,
    timeout: float = 60,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    poll_interval = Event()
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
        if last["status"] == "succeeded":
            assert last["research_kind"] == research_kind
            if research_kind == "factor_evaluation":
                assert set(last["result"]) == {"factor", "provenance"}
                assert last["result"]["provenance"]["research_kind"] == research_kind
            else:
                assert research_kind == "strategy_backtest"
                assert set(last["result"]) == {
                    "factor",
                    "strategy",
                    "terminal_strategy_state",
                    "provenance",
                }
                assert last["result"]["strategy"]["observations"]
                assert last["result"]["provenance"]["research_kind"] == research_kind
            return last
        if last["status"] in {"failed", "cancelled"}:
            raise AssertionError(last)
        poll_interval.wait(0.1)
    raise AssertionError({"timeout": True, "last_run": last})


def _wait_for_run_status(
    api_origin: str,
    run_id: str,
    expected_status: str,
    *,
    timeout: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    poll_interval = Event()
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
        if last["status"] == expected_status:
            return last
        if last["status"] in {"succeeded", "failed", "cancelled"}:
            raise AssertionError(last)
        poll_interval.wait(0.02)
    raise AssertionError({"timeout": True, "last_run": last})


def _wait_for_checkpoint(api_origin: str, run_id: str) -> int:
    deadline = time.monotonic() + 60
    poll_interval = Event()
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
        committed = int(last["progress"]["committed_chunk_count"])
        if last["status"] == "running" and committed >= 1:
            return committed
        if last["status"] in {"succeeded", "failed", "cancelled"}:
            raise AssertionError({"long_run_finished_before_fault": last})
        poll_interval.wait(0.02)
    raise AssertionError({"checkpoint_timeout": True, "last_run": last})


def _wait_for_track(
    api_origin: str,
    track_id: str,
    expected_session: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 60
    last: dict[str, object] | None = None
    poll_interval = Event()
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/daily-tracks/{track_id}")
        if last["status"] == "active" and last["strategy_session"] == expected_session:
            return last
        if last["status"] in {"blocked", "stopped"}:
            raise AssertionError(last)
        poll_interval.wait(0.1)
    raise AssertionError({"timeout": True, "last_track": last})


def _wait_for_track_status(
    api_origin: str,
    track_id: str,
    expected_status: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 60
    last: dict[str, object] | None = None
    poll_interval = Event()
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/daily-tracks/{track_id}")
        if last["status"] == expected_status:
            return last
        if last["status"] == "stopped":
            raise AssertionError(last)
        poll_interval.wait(0.1)
    raise AssertionError({"timeout": True, "last_track": last})


def _wait_for_track_phase(
    api_origin: str,
    track_id: str,
    expected_phase: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 20
    poll_interval = Event()
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/daily-tracks/{track_id}")
        if last["progress"]["phase"] == expected_phase:
            return last
        if last["status"] in {"blocked", "stopped"}:
            raise AssertionError(last)
        poll_interval.wait(0.02)
    raise AssertionError({"phase_timeout": expected_phase, "last_track": last})


def _wait_for_track_execution(api_origin: str, track_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    poll_interval = Event()
    last: dict[str, object] | None = None
    active_phases = {"starting", "calculating", "result_ready", "staging"}
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/daily-tracks/{track_id}")
        if last["status"] == "active" and last["progress"]["phase"] in active_phases:
            return last
        if last["status"] in {"blocked", "stopped"}:
            raise AssertionError(last)
        poll_interval.wait(0.01)
    raise AssertionError({"execution_timeout": True, "last_track": last})


def _assert_private_operator_installed() -> None:
    result = subprocess.run(
        ["thesistrace-data-operator", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "bootstrap" in result.stdout
    assert "refresh-financial" in result.stdout


def _assert_expected_overview(overview: dict[str, object]) -> None:
    assert {key: overview[key] for key in EXPECTED_OVERVIEW} == EXPECTED_OVERVIEW
    refreshed_at = overview.get("last_financial_refresh_at")
    assert isinstance(refreshed_at, str)
    assert refreshed_at.endswith(("+00:00", "Z"))


def _durable_result(
    settings: CoreSettings,
    run_id: str,
    *,
    research_kind: str,
) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.result_manifest_sha256, run.result_provenance,
                       run.immutable_input->>'research_kind' AS research_kind,
                       to_jsonb(run.*) AS run_snapshot,
                       coalesce((
                           SELECT jsonb_agg(to_jsonb(attempt.*) ORDER BY attempt.ordinal)
                           FROM research_runs.attempts AS attempt
                           WHERE attempt.run_id = run.id
                       ), '[]'::jsonb) AS attempt_snapshots,
                       (SELECT count(*)
                        FROM data.generation_pins AS pin
                        JOIN research_runs.attempts AS attempt
                          ON attempt.generation_pin_id = pin.id
                        WHERE attempt.run_id = run.id
                          AND pin.status = 'active') AS active_pin_count
                FROM research_runs.runs AS run WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        assert row["research_kind"] == research_kind
        manifest_sha256 = str(row["result_manifest_sha256"])
        provenance = row["result_provenance"]
        bundle = Publication(database, s3, bucket=settings.s3_bucket).read(
            PublishedRef(
                manifest_sha256=manifest_sha256,
                kind="research.result",
                provenance=provenance,
            )
        )
        result_object_names = sorted(read_result_bundle(bundle, research_kind=research_kind))
        payload_names = sorted(bundle.payloads)
        if research_kind == "factor_evaluation":
            assert result_object_names == ["factor_summary"]
            assert payload_names == ["factor_summary"]
        else:
            assert research_kind == "strategy_backtest"
            assert result_object_names == [
                "factor_summary",
                "strategy_daily_observations",
                "strategy_summary",
                "terminal_strategy_state",
            ]
            partition_names = {
                name for name in payload_names if name.startswith(RESULT_DAILY_PARTITION_PREFIX)
            }
            assert partition_names
            assert set(payload_names) == set(result_object_names) | partition_names
        return {
            "active_pin_count": int(row["active_pin_count"]),
            "manifest_sha256": manifest_sha256,
            "attempt_count": len(row["attempt_snapshots"]),
            "payload_names": payload_names,
            "result_object_names": result_object_names,
            "execution_snapshot": {
                "run": row["run_snapshot"],
                "attempts": row["attempt_snapshots"],
            },
        }
    finally:
        s3.close()
        database.close()


def _checkpoint_state(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS checkpoint_count,
                       coalesce(
                           jsonb_agg(
                               checkpoint_manifest_sha256 ORDER BY ordinal
                           ) FILTER (WHERE checkpoint_manifest_sha256 IS NOT NULL),
                           '[]'::jsonb
                       ) AS checkpoint_manifest_sha256s,
                       (SELECT count(*)
                        FROM data.generation_pins AS pin
                        JOIN research_runs.attempts AS attempt
                          ON attempt.generation_pin_id = pin.id
                        WHERE attempt.run_id = %s
                          AND pin.status = 'active') AS active_pin_count
                FROM research_runs.execution_checkpoints
                WHERE run_id = %s
                """,
                (run_id, run_id),
            ).fetchone()
        assert row is not None
        return {
            "active_pin_count": int(row["active_pin_count"]),
            "checkpoint_count": int(row["checkpoint_count"]),
            "checkpoint_manifest_sha256s": row["checkpoint_manifest_sha256s"],
        }
    finally:
        database.close()


def _run_lifecycle_state(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.status, run.result_manifest_sha256,
                       run.immutable_input->>'research_kind' AS research_kind,
                       (SELECT count(*)
                        FROM research_runs.execution_checkpoints AS checkpoint
                        WHERE checkpoint.run_id = run.id) AS checkpoint_count,
                       (SELECT count(*)
                        FROM data.generation_pins AS pin
                        JOIN research_runs.attempts AS attempt
                          ON attempt.generation_pin_id = pin.id
                        WHERE attempt.run_id = run.id
                          AND pin.status = 'active') AS active_pin_count
                FROM research_runs.runs AS run
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return {
            "active_pin_count": int(row["active_pin_count"]),
            "checkpoint_count": int(row["checkpoint_count"]),
            "result_manifest_sha256": row["result_manifest_sha256"],
            "research_kind": row["research_kind"],
            "status": row["status"],
        }
    finally:
        database.close()


def _canonical_identity(settings: CoreSettings) -> dict[str, object]:
    heads = MountedDatasetHeadStore(settings.data_mount)
    pointer = heads.current_pointer()
    assert pointer is not None
    descriptor = heads.resolve_descriptor(pointer)
    assert descriptor.manifest_sha256 == pointer.generation_manifest_sha256
    return {
        "data_identity": pointer.data_identity,
        "data_through_session": pointer.data_through_session,
        "dataset_coverage": pointer.dataset_coverage,
        "generation_manifest_sha256": pointer.generation_manifest_sha256,
        "prepared_at": pointer.prepared_at,
    }


def _product_state_counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        database.open()
        return product_state_counts(database, s3, bucket=settings.s3_bucket)
    finally:
        s3.close()
        database.close()


def _request_json(
    api_origin: str,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{api_origin}{path}",
        data=payload,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status < 300
            value = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise AssertionError(
            {"status": error.code, "method": method, "path": path, "body": error.read().decode()}
        ) from error
    assert isinstance(value, dict)
    return value


def _request_status(
    api_origin: str,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> int:
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{api_origin}{path}",
        data=payload,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        error.read()
        return error.code


def _request_error_json(
    api_origin: str,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{api_origin}{path}",
        data=payload,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raise AssertionError(
                {"unexpected_status": response.status, "method": method, "path": path}
            )
    except urllib.error.HTTPError as error:
        value = json.loads(error.read())
        assert isinstance(value, dict)
        return error.code, value


def _assert_web_image(web_origin: str) -> None:
    with urllib.request.urlopen(f"{web_origin}/data", timeout=5) as response:
        assert response.status == 200
        body = response.read().decode()
    assert '<div id="root"></div>' in body


def _directory_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()

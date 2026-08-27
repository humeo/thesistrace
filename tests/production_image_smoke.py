from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from threading import Event, Thread

import boto3

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_data import normalize_tushare_snapshot
from thesistrace.data import MountedDatasetHeadStore
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.product_state import product_state_counts
from thesistrace.publication import Publication, PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_run.result import (
    RESULT_DAILY_PARTITION_PREFIX,
    RESULT_TERMINAL_POSITION_PARTITION_PREFIX,
    read_result_bundle,
)

EXPECTED_OVERVIEW = {
    "market_coverage": {"start": "2009-12-07", "end": "2026-08-05"},
    "financial_coverage": {
        "start": "2010-01-01",
        "discovery_baseline_session": "2026-08-05",
        "discovery_attempted_through_session": "2026-08-05",
        "discovery_complete_through_session": "2026-08-05",
        "historical_reconciliation_watermark": "2026-08-05",
        "revision_coverage": "source-dated-and-first-observed-corrections",
        "seed_policy": "latest-pre-start-annual-flow-and-balance-facts",
        "readiness_status": "ready",
        "pending_instrument_count": 0,
        "discovery_gap_count": 0,
        "earliest_unresolved_date": None,
        "sparse_facts": True,
    },
    "industry_coverage": {
        "start": "2009-12-07",
        "observation_through_session": "2026-08-05",
        "classification_version": "SW2021",
    },
    "benchmark_coverage": {"start": "2010-01-04", "end": "2026-08-05"},
    "data_through_session": "2026-08-05",
    "market_research_readiness": True,
    "benchmark_research_readiness": True,
    "financial_research_readiness": "ready",
    "industry_research_readiness": True,
}
READY_DEPENDENCIES = {
    "postgresql": {"status": "ready", "code": "POSTGRESQL_READY"},
    "rustfs": {"status": "ready", "code": "RUSTFS_READY"},
    "dataset_store": {"status": "ready", "code": "DATASET_STORE_READY"},
}
UNAVAILABLE_DEPENDENCY_CODES = {
    "postgresql": "POSTGRESQL_UNAVAILABLE",
    "rustfs": "RUSTFS_UNAVAILABLE",
    "dataset_store": "DATASET_STORE_UNAVAILABLE",
}
HTTP_REQUEST_TIMEOUT_SECONDS = 10

BATCH_PERFORMANCE_WARMUP_SAMPLES = 1
BATCH_PERFORMANCE_MEASURED_SAMPLES = 4
BATCH_PERFORMANCE_MAXIMUM_MEDIAN_RATIO = 0.8


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
        "health",
        "readiness-outage",
        "observability",
        "reset",
    }
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        raise SystemExit(f"usage: production_image_smoke.py {{{'|'.join(sorted(phases))}}}")
    api_origin = _required_environment("THESISTRACE_TEST_API_ORIGIN").rstrip("/")
    web_origin = _required_environment("THESISTRACE_TEST_WEB_ORIGIN").rstrip("/")
    state_path = Path(_required_environment("THESISTRACE_TEST_SMOKE_STATE"))
    settings = CoreSettings.from_environment()
    assert "THESISTRACE_TUSHARE_TOKEN" not in os.environ
    phase = sys.argv[1]
    _assert_web_image(web_origin)
    if phase == "health":
        result = _verify_health(api_origin)
    elif phase == "readiness-outage":
        result = _verify_readiness_outage(
            api_origin,
            _required_environment("THESISTRACE_TEST_UNAVAILABLE_DEPENDENCY"),
        )
    elif phase == "observability":
        result = _verify_observability_evidence(
            state_path.parent,
            api_events=Path(_required_environment("THESISTRACE_TEST_API_EVENTS")),
            worker_events=Path(_required_environment("THESISTRACE_TEST_WORKER_EVENTS")),
        )
    elif phase == "before":
        result = _before_restart(
            api_origin,
            settings,
            image_identity=_required_environment("THESISTRACE_TEST_IMAGE_ID"),
            evidence_dir=state_path.parent,
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
                Path(_required_environment("THESISTRACE_TEST_WORKER_EVENTS")),
                expected,
                execution_memory_bytes=settings.research_execution_memory_bytes,
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
    evidence_dir: Path,
) -> dict[str, object]:
    refresh_evidence = _verify_data_refresh_events(evidence_dir)
    mounted_data_sha256 = _directory_sha256(settings.data_mount)
    overview = _request_json(api_origin, "GET", "/api/data")
    _assert_expected_overview(overview)
    _request_with_secret_canary(api_origin)
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
        },
        {
            "id": "folder_batch_research",
            "name": "Batch Research",
            "is_default": False,
            "created_at": folders["items"][1]["created_at"],
        },
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
    factor_batch = _request_json(
        api_origin,
        "POST",
        "/api/research-batches",
        {
            "request_id": "production-image-smoke-factor-batch",
            "batch_kind": "factor_evaluation",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "universe": "top300",
            "neutralization": "none",
            "factors": [
                {"item_key": "value", "formula": "close"},
                {"item_key": "rank", "formula": "rank(close)"},
            ],
        },
    )
    factor_batch_detail = _wait_for_batch(api_origin, str(factor_batch["id"]))
    assert [item["status"] for item in factor_batch_detail["items"]] == [
        "succeeded",
        "succeeded",
    ]
    factor_batch_run_ids = [str(item["research_run_id"]) for item in factor_batch_detail["items"]]
    for batch_run_id in factor_batch_run_ids:
        batch_run = _wait_for_run(
            api_origin,
            batch_run_id,
            research_kind="factor_evaluation",
        )
        assert batch_run["result"]["provenance"]["research_run_id"] == batch_run_id
        _assert_batch_owned_durable_result(settings, batch_run_id)
    strategy_batch = _request_json(
        api_origin,
        "POST",
        "/api/research-batches",
        {
            "request_id": "production-image-smoke-strategy-batch",
            "batch_kind": "strategy_sweep",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "universe": "top300",
            "neutralization": "none",
            "alpha": {
                "formula": "rank(close) + rank(revenue)",
                "hypothesis": "One shared Alpha supports ordered Strategy variants.",
            },
            "strategies": [
                {
                    "item_key": "focused",
                    "holdings_count": 1,
                    "rebalance_every_sessions": 1,
                },
                {
                    "item_key": "broad",
                    "holdings_count": 2,
                    "rebalance_every_sessions": 2,
                },
            ],
        },
    )
    strategy_batch_detail = _wait_for_batch(api_origin, str(strategy_batch["id"]))
    assert [item["status"] for item in strategy_batch_detail["items"]] == [
        "succeeded",
        "succeeded",
    ]
    strategy_batch_run_ids = [
        str(item["research_run_id"]) for item in strategy_batch_detail["items"]
    ]
    for batch_run_id in strategy_batch_run_ids:
        batch_run = _wait_for_run(
            api_origin,
            batch_run_id,
            research_kind="strategy_backtest",
        )
        assert batch_run["result"]["provenance"]["research_run_id"] == batch_run_id
        _assert_batch_owned_durable_result(settings, batch_run_id)
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
    diagnostic_evidence = _verify_packaged_diagnostics(
        factor_run_id,
        str(track["id"]),
        evidence_dir,
    )
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
    batch_qualification = _qualify_research_batches(
        api_origin,
        settings,
        image_identity=image_identity,
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
        "factor_batch_id": factor_batch_detail["id"],
        "factor_batch_run_ids": factor_batch_run_ids,
        "strategy_batch_id": strategy_batch_detail["id"],
        "strategy_batch_run_ids": strategy_batch_run_ids,
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
        "batch_qualification": batch_qualification,
        "attempt_count": durable["attempt_count"],
        "execution_snapshot": durable["execution_snapshot"],
        "overview": overview,
        "mounted_data_sha256": mounted_data_sha256,
        **diagnostic_evidence,
        **refresh_evidence,
    }


def _qualify_research_batches(
    api_origin: str,
    settings: CoreSettings,
    *,
    image_identity: str,
) -> dict[str, object]:
    factor_specs = (
        {"item_key": "positive", "formula": "rank(close)"},
        {"item_key": "negative", "formula": "-rank(close)"},
    )
    strategy_specs = (
        {
            "item_key": "baseline",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
        },
        {
            "item_key": "holdings-only",
            "holdings_count": 2,
            "rebalance_every_sessions": 1,
        },
        {
            "item_key": "rebalance-only",
            "holdings_count": 1,
            "rebalance_every_sessions": 5,
        },
    )
    scope = {
        "start_date": "2026-05-04",
        "end_date": "2026-07-01",
        "universe": "top300",
        "neutralization": "none",
    }
    samples: list[dict[str, object]] = []
    completed_batch_ids: list[str] = []
    completed_run_ids: list[str] = []

    total_sample_count = BATCH_PERFORMANCE_WARMUP_SAMPLES + BATCH_PERFORMANCE_MEASURED_SAMPLES
    for sample_index in range(total_sample_count):
        prefix = f"production-image-batch-qualification-{sample_index + 1}"
        sample_number = sample_index + 1
        request_response_records: list[dict[str, object]] = []

        def execute_factor_serial(
            request_prefix: str = prefix,
            selected_sample: int = sample_number,
            records: list[dict[str, object]] = request_response_records,
        ) -> list[dict[str, object]]:
            details: list[dict[str, object]] = []
            for item in factor_specs:
                request = {
                    "request_id": f"{request_prefix}-factor-serial-{item['item_key']}",
                    "folder_id": "folder_default",
                    "name": f"Qualification Factor {selected_sample} {item['item_key']}",
                    "hypothesis": "Factor Batch and serial execution are identical.",
                    **scope,
                    "formula": item["formula"],
                    "research_kind": "factor_evaluation",
                }
                accepted = _request_json(
                    api_origin,
                    "POST",
                    "/api/research-runs",
                    request,
                )
                terminal = _wait_for_run(
                    api_origin,
                    str(accepted["id"]),
                    research_kind="factor_evaluation",
                    timeout=180,
                )
                records.append(
                    {
                        "resource": "serial_factor",
                        "request": request,
                        "admission_response": accepted,
                        "terminal_response": terminal,
                    }
                )
                details.append(terminal)
            return details

        def execute_factor_batch(
            request_prefix: str = prefix,
            records: list[dict[str, object]] = request_response_records,
        ) -> dict[str, object]:
            request = {
                "request_id": f"{request_prefix}-factor-batch",
                "batch_kind": "factor_evaluation",
                **scope,
                "factors": list(factor_specs),
            }
            admitted = _request_json(
                api_origin,
                "POST",
                "/api/research-batches",
                request,
            )
            terminal = _wait_for_batch(api_origin, str(admitted["id"]), timeout=180)
            records.append(
                {
                    "resource": "factor_batch",
                    "request": request,
                    "admission_response": admitted,
                    "terminal_response": terminal,
                }
            )
            return terminal

        def execute_strategy_serial(
            request_prefix: str = prefix,
            selected_sample: int = sample_number,
            records: list[dict[str, object]] = request_response_records,
        ) -> list[dict[str, object]]:
            details: list[dict[str, object]] = []
            for item in strategy_specs:
                request = {
                    "request_id": f"{request_prefix}-strategy-serial-{item['item_key']}",
                    "folder_id": "folder_default",
                    "name": f"Qualification Strategy {selected_sample} {item['item_key']}",
                    "hypothesis": "Strategy Sweep and serial execution are identical.",
                    **scope,
                    "formula": "rank(close)",
                    "research_kind": "strategy_backtest",
                    "holdings_count": item["holdings_count"],
                    "rebalance_every_sessions": item["rebalance_every_sessions"],
                }
                accepted = _request_json(
                    api_origin,
                    "POST",
                    "/api/research-runs",
                    request,
                )
                terminal = _wait_for_run(
                    api_origin,
                    str(accepted["id"]),
                    research_kind="strategy_backtest",
                    timeout=180,
                )
                records.append(
                    {
                        "resource": "serial_strategy",
                        "request": request,
                        "admission_response": accepted,
                        "terminal_response": terminal,
                    }
                )
                details.append(terminal)
            return details

        def execute_strategy_batch(
            request_prefix: str = prefix,
            records: list[dict[str, object]] = request_response_records,
        ) -> dict[str, object]:
            request = {
                "request_id": f"{request_prefix}-strategy-batch",
                "batch_kind": "strategy_sweep",
                **scope,
                "alpha": {
                    "formula": "rank(close)",
                    "hypothesis": "One Alpha supports deterministic Strategy variants.",
                },
                "strategies": list(strategy_specs),
            }
            admitted = _request_json(
                api_origin,
                "POST",
                "/api/research-batches",
                request,
            )
            terminal = _wait_for_batch(api_origin, str(admitted["id"]), timeout=180)
            records.append(
                {
                    "resource": "strategy_batch",
                    "request": request,
                    "admission_response": admitted,
                    "terminal_response": terminal,
                }
            )
            return terminal

        if sample_index % 2 == 0:
            factor_batch = execute_factor_batch()
            factor_serial = execute_factor_serial()
            strategy_batch = execute_strategy_batch()
            strategy_serial = execute_strategy_serial()
        else:
            factor_serial = execute_factor_serial()
            factor_batch = execute_factor_batch()
            strategy_serial = execute_strategy_serial()
            strategy_batch = execute_strategy_batch()

        factor_batch_results = [
            _result_qualification_evidence(
                api_origin,
                settings,
                str(item["research_run_id"]),
                research_kind="factor_evaluation",
            )
            for item in factor_batch["items"]
        ]
        factor_serial_results = [
            _result_qualification_evidence(
                api_origin,
                settings,
                str(detail["id"]),
                research_kind="factor_evaluation",
            )
            for detail in factor_serial
        ]
        strategy_batch_results = [
            _result_qualification_evidence(
                api_origin,
                settings,
                str(item["research_run_id"]),
                research_kind="strategy_backtest",
            )
            for item in strategy_batch["items"]
        ]
        strategy_serial_results = [
            _result_qualification_evidence(
                api_origin,
                settings,
                str(detail["id"]),
                research_kind="strategy_backtest",
            )
            for detail in strategy_serial
        ]
        _assert_equivalent_result_pairs(factor_batch_results, factor_serial_results)
        _assert_equivalent_result_pairs(strategy_batch_results, strategy_serial_results)
        _assert_factor_negation_and_coverage(factor_batch_results)
        _assert_strategy_science(strategy_batch_results)

        factor_serial_elapsed = sum(
            _final_elapsed_seconds(detail["execution_timing"]) for detail in factor_serial
        )
        strategy_serial_elapsed = sum(
            _final_elapsed_seconds(detail["execution_timing"]) for detail in strategy_serial
        )
        factor_batch_elapsed = _final_elapsed_seconds(factor_batch["execution_timing"])
        strategy_batch_elapsed = _final_elapsed_seconds(strategy_batch["execution_timing"])
        factor_batch_id = str(factor_batch["id"])
        strategy_batch_id = str(strategy_batch["id"])
        completed_batch_ids.extend((factor_batch_id, strategy_batch_id))
        sample_run_ids = [
            *(str(detail["id"]) for detail in factor_serial),
            *(str(item["research_run_id"]) for item in factor_batch["items"]),
            *(str(detail["id"]) for detail in strategy_serial),
            *(str(item["research_run_id"]) for item in strategy_batch["items"]),
        ]
        completed_run_ids.extend(sample_run_ids)
        samples.append(
            {
                "sample_index": sample_index + 1,
                "execution_order": (
                    "batch_then_serial" if sample_index % 2 == 0 else "serial_then_batch"
                ),
                "factor_batch_id": factor_batch_id,
                "strategy_batch_id": strategy_batch_id,
                "factor_item_order": [item["item_key"] for item in factor_batch["items"]],
                "strategy_item_order": [item["item_key"] for item in strategy_batch["items"]],
                "factor_batch_elapsed_seconds": factor_batch_elapsed,
                "factor_serial_elapsed_seconds": factor_serial_elapsed,
                "strategy_batch_elapsed_seconds": strategy_batch_elapsed,
                "strategy_serial_elapsed_seconds": strategy_serial_elapsed,
                "factor_batch_queue_wait_seconds": _queue_wait_seconds(factor_batch),
                "strategy_batch_queue_wait_seconds": _queue_wait_seconds(strategy_batch),
                "factor_serial_queue_wait_seconds": [
                    _queue_wait_seconds(detail) for detail in factor_serial
                ],
                "strategy_serial_queue_wait_seconds": [
                    _queue_wait_seconds(detail) for detail in strategy_serial
                ],
                "factor_calculation_payload_checksums": [
                    result["calculation_payload_checksum"] for result in factor_batch_results
                ],
                "factor_semantic_result_checksums": [
                    result["semantic_result_checksum"] for result in factor_batch_results
                ],
                "strategy_calculation_payload_checksums": [
                    result["calculation_payload_checksum"] for result in strategy_batch_results
                ],
                "strategy_semantic_result_checksums": [
                    result["semantic_result_checksum"] for result in strategy_batch_results
                ],
                "factor_batch_result_objects": [
                    {
                        "run_id": result["run_id"],
                        "manifest_sha256": result["manifest_sha256"],
                        "object_references": result["object_references"],
                    }
                    for result in factor_batch_results
                ],
                "factor_serial_result_objects": [
                    {
                        "run_id": result["run_id"],
                        "manifest_sha256": result["manifest_sha256"],
                        "object_references": result["object_references"],
                    }
                    for result in factor_serial_results
                ],
                "strategy_batch_result_objects": [
                    {
                        "run_id": result["run_id"],
                        "manifest_sha256": result["manifest_sha256"],
                        "object_references": result["object_references"],
                    }
                    for result in strategy_batch_results
                ],
                "strategy_serial_result_objects": [
                    {
                        "run_id": result["run_id"],
                        "manifest_sha256": result["manifest_sha256"],
                        "object_references": result["object_references"],
                    }
                    for result in strategy_serial_results
                ],
                "batch_result_object_bytes": sum(
                    int(result["object_bytes"])
                    for result in (*factor_batch_results, *strategy_batch_results)
                ),
                "serial_result_object_bytes": sum(
                    int(result["object_bytes"])
                    for result in (*factor_serial_results, *strategy_serial_results)
                ),
                "batch_attempts": [
                    _batch_attempt_evidence(settings, factor_batch_id),
                    _batch_attempt_evidence(settings, strategy_batch_id),
                ],
                "request_response_records": request_response_records,
                "run_ids": sample_run_ids,
            }
        )

    first = samples[0]
    for key in (
        "factor_calculation_payload_checksums",
        "factor_semantic_result_checksums",
        "strategy_calculation_payload_checksums",
        "strategy_semantic_result_checksums",
        "factor_item_order",
        "strategy_item_order",
    ):
        assert all(sample[key] == first[key] for sample in samples[1:])

    measured_samples = samples[BATCH_PERFORMANCE_WARMUP_SAMPLES:]
    assert len(measured_samples) == BATCH_PERFORMANCE_MEASURED_SAMPLES
    assert [sample["execution_order"] for sample in measured_samples] == [
        "serial_then_batch",
        "batch_then_serial",
        "serial_then_batch",
        "batch_then_serial",
    ]
    performance = {
        "warmup_sample_count": BATCH_PERFORMANCE_WARMUP_SAMPLES,
        "measured_sample_count": BATCH_PERFORMANCE_MEASURED_SAMPLES,
        "maximum_median_ratio": BATCH_PERFORMANCE_MAXIMUM_MEDIAN_RATIO,
        "factor_batch_median_seconds": median(
            float(sample["factor_batch_elapsed_seconds"]) for sample in measured_samples
        ),
        "factor_serial_median_seconds": median(
            float(sample["factor_serial_elapsed_seconds"]) for sample in measured_samples
        ),
        "strategy_batch_median_seconds": median(
            float(sample["strategy_batch_elapsed_seconds"]) for sample in measured_samples
        ),
        "strategy_serial_median_seconds": median(
            float(sample["strategy_serial_elapsed_seconds"]) for sample in measured_samples
        ),
    }
    assert performance["factor_batch_median_seconds"] < (
        performance["factor_serial_median_seconds"] * BATCH_PERFORMANCE_MAXIMUM_MEDIAN_RATIO
    ), {"performance": performance, "samples": samples}
    assert performance["strategy_batch_median_seconds"] < (
        performance["strategy_serial_median_seconds"] * BATCH_PERFORMANCE_MAXIMUM_MEDIAN_RATIO
    ), {"performance": performance, "samples": samples}

    cancellation_command = {
        "request_id": "production-image-batch-qualification-cancel-admission",
        "batch_kind": "factor_evaluation",
        "start_date": "2010-01-04",
        "end_date": "2026-08-05",
        "universe": "top300",
        "neutralization": "none",
        "factors": [
            {"item_key": "long-positive", "formula": "rank(pct_change(close, 20))"},
            {"item_key": "long-negative", "formula": "-rank(pct_change(close, 20))"},
        ],
    }
    cancelling_batch = _request_json(
        api_origin,
        "POST",
        "/api/research-batches",
        cancellation_command,
    )
    running = _wait_for_running_batch_attempt(
        api_origin,
        str(cancelling_batch["id"]),
        timeout=60,
    )
    cancel_response = _request_json(
        api_origin,
        "POST",
        f"/api/research-batches/{cancelling_batch['id']}/cancel",
        {"request_id": "production-image-batch-qualification-cancel"},
    )
    assert cancel_response["status"] in {"cancelling", "cancelled"}
    cancelled = _wait_for_batch_status(
        api_origin,
        str(cancelling_batch["id"]),
        "cancelled",
        timeout=10,
    )
    assert cancelled["execution_timing"]["is_final"] is True
    assert all(item["outcome"] == "cancelled" for item in cancelled["items"])

    return {
        "schema_version": "production-batch-qualification-v1",
        "image_identity": image_identity,
        "scope": scope,
        "factor_requests": list(factor_specs),
        "strategy_requests": list(strategy_specs),
        "samples": samples,
        "performance": performance,
        "determinism_controls": {
            "fixed_scope": scope,
            "fixed_factor_requests": list(factor_specs),
            "fixed_strategy_requests": list(strategy_specs),
            "fixed_request_ids": [
                str(record["request"]["request_id"])
                for sample in samples
                for record in sample["request_response_records"]
            ]
            + [
                str(cancellation_command["request_id"]),
                "production-image-batch-qualification-cancel",
            ],
            "random_source_used": False,
            "recorded_dynamic_fields": [
                "resource_ids",
                "attempt_ids",
                "timestamps",
                "elapsed_seconds",
            ],
            "semantic_comparison_excludes_dynamic_fields": True,
        },
        "completed_batch_ids": completed_batch_ids,
        "completed_run_ids": completed_run_ids,
        "cancel_request": cancellation_command,
        "cancel_admission_response": cancelling_batch,
        "cancel_batch_id": cancelled["id"],
        "cancel_running_attempt_id": running["attempt"]["id"],
        "cancel_response_status": cancel_response["status"],
        "cancel_terminal_status": cancelled["status"],
        "cancel_terminal_response": cancelled,
        "execution_memory_bytes": settings.research_execution_memory_bytes,
    }


def _result_qualification_evidence(
    api_origin: str,
    settings: CoreSettings,
    run_id: str,
    *,
    research_kind: str,
) -> dict[str, object]:
    detail = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
    assert detail["status"] == "succeeded"
    result = dict(detail["result"])
    provenance = dict(result.pop("provenance"))
    assert provenance["research_run_id"] == run_id
    durable = _durable_result(settings, run_id, research_kind=research_kind)
    stored_provenance = durable["provenance"]
    assert stored_provenance["research_run_id"] == run_id
    return {
        "run_id": run_id,
        "data_generation_id": stored_provenance["data_generation_id"],
        "calculation_contracts": stored_provenance["calculation_contracts"],
        "semantic_versions": stored_provenance["semantic_versions"],
        "manifest_sha256": durable["manifest_sha256"],
        "object_references": durable["object_references"],
        "calculation_payload_checksum": hashlib.sha256(
            canonical_json_bytes(durable["stored_result"])
        ).hexdigest(),
        "semantic_result_checksum": hashlib.sha256(canonical_json_bytes(result)).hexdigest(),
        "object_bytes": durable["object_bytes"],
        "stored_result": durable["stored_result"],
        "public_result": result,
    }


def _assert_equivalent_result_pairs(
    batch_results: list[dict[str, object]],
    serial_results: list[dict[str, object]],
) -> None:
    assert len(batch_results) == len(serial_results)
    generations: set[str] = set()
    for batch, serial in zip(batch_results, serial_results, strict=True):
        assert batch["calculation_payload_checksum"] == serial["calculation_payload_checksum"]
        assert batch["semantic_result_checksum"] == serial["semantic_result_checksum"]
        assert batch["calculation_contracts"] == serial["calculation_contracts"]
        assert batch["semantic_versions"] == serial["semantic_versions"]
        assert batch["data_generation_id"] == serial["data_generation_id"]
        assert batch["object_references"] == serial["object_references"]
        assert batch["manifest_sha256"] != serial["manifest_sha256"]
        generations.add(str(batch["data_generation_id"]))
    assert len(generations) == 1


def _assert_factor_negation_and_coverage(results: list[dict[str, object]]) -> None:
    assert len(results) == 2
    positive = results[0]["stored_result"]["factor_summary"]["horizons"]
    negative = results[1]["stored_result"]["factor_summary"]["horizons"]
    for horizon in ("1", "5", "20"):
        positive_horizon = positive[horizon]
        negative_horizon = negative[horizon]
        assert positive_horizon["alpha_checksum"] != negative_horizon["alpha_checksum"]
        positive_coverage = positive_horizon["coverage"]
        assert int(positive_coverage["signal_session_count"]) > 0
        assert int(positive_coverage["ic_valid_session_count"]) > 0
        assert int(positive_coverage["rank_ic_valid_session_count"]) > 0
        assert int(positive_coverage["quantile_valid_session_count"]) > 0
        assert positive_horizon["coverage"] == negative_horizon["coverage"]
        for correlation in ("ic", "rank_ic"):
            positive_mean = positive_horizon["summary"][correlation]["mean"]
            negative_mean = negative_horizon["summary"][correlation]["mean"]
            assert positive_mean is not None
            assert negative_mean is not None
            assert Decimal(str(negative_mean)) == -Decimal(str(positive_mean))
    assert results[0]["calculation_payload_checksum"] != results[1]["calculation_payload_checksum"]


def _assert_strategy_science(results: list[dict[str, object]]) -> None:
    assert len(results) == 3
    baseline, holdings_only, rebalance_only = results
    assert baseline["semantic_result_checksum"] != holdings_only["semantic_result_checksum"]
    assert baseline["semantic_result_checksum"] != rebalance_only["semantic_result_checksum"]
    for result in results:
        stored = result["stored_result"]
        observations = stored["strategy_daily_observations"]
        assert observations
        summary = stored["strategy_summary"]
        metrics = summary["metrics"]
        assert summary["source_checksum"] == _independent_observation_checksum(observations)
        initial_cash = Decimal(str(summary["initial_cash_cny"]))
        for observation in observations:
            for name in ("gross_nav", "net_nav", "net_cash"):
                assert Decimal(str(observation[name])).is_finite()
            assert Decimal(str(observation["gross_nav"])) > 0
            assert Decimal(str(observation["net_nav"])) > 0
        last = observations[-1]
        assert metrics["gross_cumulative_return"] == float(
            Decimal(str(last["gross_nav"])) / initial_cash - 1
        )
        assert metrics["net_cumulative_return"] == float(
            Decimal(str(last["net_nav"])) / initial_cash - 1
        )
        cumulative_cost = sum(
            (Decimal(str(observation["transaction_cost_cny"])) for observation in observations),
            start=Decimal(0),
        )
        terminal = stored["terminal_strategy_state"]
        assert Decimal(str(terminal["cumulative_transaction_cost"])) == cumulative_cost
        assert metrics["transaction_costs"]["cumulative_amount"] == float(cumulative_cost)
        assert {
            name: str(terminal[name])
            for name in ("session", "gross_nav", "net_nav", "net_cash")
        } == {
            name: str(last[name])
            for name in ("session", "gross_nav", "net_nav", "net_cash")
        }
        independently_recomputed_drawdown = _independent_maximum_drawdown(observations)
        assert metrics["maximum_drawdown"] == independently_recomputed_drawdown, {
            "reported": metrics["maximum_drawdown"],
            "independently_recomputed": independently_recomputed_drawdown,
            "run_id": result["run_id"],
        }
        drawdown = Decimal(str(metrics["maximum_drawdown"]["value"]))
        assert drawdown.is_finite()
        assert Decimal(0) <= drawdown <= Decimal(1)


def _independent_observation_checksum(observations: list[dict[str, object]]) -> str:
    prior: bytes | None = None
    for observation in observations:
        digest = hashlib.sha256()
        if prior is not None:
            digest.update(prior)
        digest.update(canonical_json_bytes(observation))
        prior = digest.digest()
    assert prior is not None
    return prior.hex()


def _independent_maximum_drawdown(
    observations: list[dict[str, object]],
) -> dict[str, object]:
    net_nav = [Decimal(str(observation["net_nav"])) for observation in observations]
    peak_index = 0
    worst_value = Decimal(0)
    worst_peak = 0
    worst_trough = 0
    for index, value in enumerate(net_nav):
        if value > net_nav[peak_index]:
            peak_index = index
        drawdown = Decimal(1) - value / net_nav[peak_index]
        if drawdown > worst_value:
            worst_value = drawdown
            worst_peak = peak_index
            worst_trough = index
    recovery = (
        None
        if worst_value == 0
        else next(
            (
                index
                for index in range(worst_trough + 1, len(net_nav))
                if net_nav[index] >= net_nav[worst_peak]
            ),
            None,
        )
    )
    return {
        "value": float(worst_value),
        "peak_session": observations[worst_peak]["session"],
        "trough_session": observations[worst_trough]["session"],
        "recovery_session": (observations[recovery]["session"] if recovery is not None else None),
        "unrecovered": recovery is None and worst_value > 0,
    }


def _final_elapsed_seconds(value: object) -> float:
    assert isinstance(value, dict)
    assert value["is_final"] is True
    elapsed = value["elapsed_seconds"]
    assert isinstance(elapsed, int | float) and elapsed > 0
    return float(elapsed)


def _queue_wait_seconds(detail: dict[str, object]) -> float:
    timing = detail["execution_timing"]
    assert isinstance(timing, dict)
    started_at = timing["started_at"]
    created_at = detail["created_at"]
    assert isinstance(started_at, str) and isinstance(created_at, str)
    return max(
        0.0,
        (datetime.fromisoformat(started_at) - datetime.fromisoformat(created_at)).total_seconds(),
    )


def _batch_attempt_evidence(settings: CoreSettings, batch_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT to_jsonb(attempt.*) AS attempt,
                       coalesce((
                           SELECT jsonb_agg(to_jsonb(task.*) ORDER BY task.started_at, task.id)
                           FROM research_batches.task_attempts AS task
                           WHERE task.batch_id = attempt.batch_id
                       ), '[]'::jsonb) AS task_attempts
                FROM research_batches.attempts AS attempt
                WHERE attempt.batch_id = %s
                ORDER BY attempt.ordinal DESC
                LIMIT 1
                """,
                (batch_id,),
            ).fetchone()
        assert row is not None
        return {"attempt": row["attempt"], "task_attempts": row["task_attempts"]}
    finally:
        database.close()


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
    assert product_state_before_reset["research_batches"] >= 1
    assert product_state_before_reset["research_batch_items"] >= 1
    assert product_state_before_reset["research_batch_attempts"] >= 1
    assert product_state_before_reset["research_batch_task_attempts"] >= 1
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

    qualification = expected["batch_qualification"]
    assert isinstance(qualification, dict)
    for sample in qualification["samples"]:
        factor_batch = _request_json(
            api_origin,
            "GET",
            f"/api/research-batches/{sample['factor_batch_id']}",
        )
        strategy_batch = _request_json(
            api_origin,
            "GET",
            f"/api/research-batches/{sample['strategy_batch_id']}",
        )
        assert factor_batch["status"] == strategy_batch["status"] == "succeeded"
        factor_checksums = [
            _result_qualification_evidence(
                api_origin,
                settings,
                str(item["research_run_id"]),
                research_kind="factor_evaluation",
            )["calculation_payload_checksum"]
            for item in factor_batch["items"]
        ]
        strategy_checksums = [
            _result_qualification_evidence(
                api_origin,
                settings,
                str(item["research_run_id"]),
                research_kind="strategy_backtest",
            )["calculation_payload_checksum"]
            for item in strategy_batch["items"]
        ]
        assert factor_checksums == sample["factor_calculation_payload_checksums"]
        assert strategy_checksums == sample["strategy_calculation_payload_checksums"]
    cancelled_batch = _request_json(
        api_origin,
        "GET",
        f"/api/research-batches/{qualification['cancel_batch_id']}",
    )
    assert cancelled_batch["status"] == "cancelled"

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
        "batch_qualification_restart_verified": True,
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
    expected_overview["last_market_refresh_at"] = None
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
    qualification = expected["batch_qualification"]
    assert isinstance(qualification, dict)
    stale_batch_ids = {
        *(str(batch_id) for batch_id in qualification["completed_batch_ids"]),
        str(qualification["cancel_batch_id"]),
    }
    for batch_id in stale_batch_ids:
        assert _request_status(api_origin, "GET", f"/api/research-batches/{batch_id}") == 404
    stale_track_ids = {
        str(expected[key]) for key in ("track_id", "market_track_id", "stop_track_id")
    }
    for track_id in stale_track_ids:
        assert _request_status(api_origin, "GET", f"/api/daily-tracks/{track_id}") == 404
    assert _request_json(api_origin, "GET", "/api/research-runs")["items"] == []
    assert _request_json(api_origin, "GET", "/api/research-batches")["items"] == []
    assert _request_json(api_origin, "GET", "/api/daily-tracks")["items"] == []
    product_state_after_reset = _product_state_counts(settings)
    assert product_state_after_reset == {key: 0 for key in product_state_after_reset}
    return {
        "canonical_data_preserved_by_reset": True,
        "canonical_identity_after_reset": _canonical_identity(settings),
        "product_state_after_reset": product_state_after_reset,
        "product_state_reset_verified": True,
        "stale_research_reference_count": len(stale_run_ids),
        "stale_batch_reference_count": len(stale_batch_ids),
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


def _verify_worker_events(
    path: Path,
    expected: dict[str, object],
    *,
    execution_memory_bytes: int,
) -> dict[str, object]:
    events: list[dict[str, object]] = []
    for line in path.read_text().splitlines():
        payload = line.partition("|")[2].strip()
        if not payload.startswith("{"):
            continue
        value = json.loads(payload)
        if isinstance(value, dict):
            events.append(value)

    worker_started = [event for event in events if event.get("event") == "worker_started"]
    assert {event["worker_role"] for event in worker_started} == {
        "research",
        "batch-research",
        "tracking",
    }
    assert all(event["slot"] == 1 and event["slot_count"] == 1 for event in worker_started)

    research_lifecycle_names = {
        "research_execution_child_started",
        "research_execution_child_exited",
        "research_execution_chunk_committed",
        "research_checkpoint_committed",
        "research_result_published",
        "research_run_succeeded",
    }
    research_lifecycle = [
        event for event in events if event.get("event") in research_lifecycle_names
    ]
    assert research_lifecycle
    for event in research_lifecycle:
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

    assert any(
        event["event"] == "research_execution_child_started"
        for event in research_lifecycle
    )
    assert any(
        event["event"] == "research_execution_child_exited"
        for event in research_lifecycle
    )
    assert any(
        event["event"] == "research_execution_chunk_committed"
        for event in research_lifecycle
    )

    batch_lifecycle = [
        event
        for event in events
        if str(event.get("event", "")).startswith("research_batch_execution_")
    ]
    assert batch_lifecycle
    assert {
        "research_batch_execution_child_started",
        "research_batch_execution_batch_prepared",
        "research_batch_execution_batch_succeeded",
        "research_batch_execution_child_acknowledged",
        "research_batch_execution_child_exited",
        "research_batch_execution_shared_alpha_factor_succeeded",
        "research_batch_execution_item_succeeded",
    } <= {str(event["event"]) for event in batch_lifecycle}
    for event in batch_lifecycle:
        assert str(event["batch_id"]).startswith("batch_")
        assert str(event["attempt_id"]).startswith("batch_attempt_")
        assert "resource_type" not in event
        assert "resource_id" not in event

    qualification = expected["batch_qualification"]
    assert isinstance(qualification, dict)
    samples = qualification["samples"]
    assert isinstance(samples, list) and len(samples) == (
        BATCH_PERFORMANCE_WARMUP_SAMPLES + BATCH_PERFORMANCE_MEASURED_SAMPLES
    )
    qualified_batch_ids = {
        str(sample[key])
        for sample in samples
        for key in ("factor_batch_id", "strategy_batch_id")
    }
    qualified_events = [
        event
        for event in batch_lifecycle
        if str(event["batch_id"]) in qualified_batch_ids
    ]
    assert qualified_events
    for sample in samples:
        factor_batch_id = str(sample["factor_batch_id"])
        strategy_batch_id = str(sample["strategy_batch_id"])
        factor_events = [
            event for event in qualified_events if event["batch_id"] == factor_batch_id
        ]
        strategy_events = [
            event
            for event in qualified_events
            if event["batch_id"] == strategy_batch_id
        ]
        factor_prepared = [
            event
            for event in factor_events
            if event["event"] == "research_batch_execution_batch_prepared"
        ]
        assert len(factor_prepared) == 1
        factor_items = [
            event
            for event in factor_events
            if event["event"] == "research_batch_execution_item_chunk_succeeded"
            and event.get("alpha_factor_task_completed") is True
        ]
        assert [event["item_ordinal"] for event in factor_items] == list(
            range(1, len(qualification["factor_requests"]) + 1)
        )
        assert all(event["alpha_factor_task_started"] is True for event in factor_items)
        assert all(
            event["data_io"] == factor_prepared[0]["data_io"]
            for event in factor_items
        )

        strategy_prepared = [
            event
            for event in strategy_events
            if event["event"] == "research_batch_execution_batch_prepared"
        ]
        shared = [
            event
            for event in strategy_events
            if event["event"]
            == "research_batch_execution_shared_alpha_factor_succeeded"
        ]
        strategy_items = [
            event
            for event in strategy_events
            if event["event"] == "research_batch_execution_item_succeeded"
        ]
        assert len(strategy_prepared) == 1
        assert len(shared) == 1
        assert shared[0]["alpha_factor_task_started"] is True
        assert shared[0]["alpha_factor_task_completed"] is True
        assert [event["item_ordinal"] for event in strategy_items] == list(
            range(1, len(qualification["strategy_requests"]) + 1)
        )
        assert all(event["strategy_task_completed"] is True for event in strategy_items)
        assert all(
            event["alpha_factor_task_started"] is False for event in strategy_items
        )
        assert all(
            event["data_io"] == strategy_prepared[0]["data_io"]
            for event in strategy_items
        )

    qualified_peak_rss = max(
        int(event["child_peak_rss_bytes"])
        for event in qualified_events
        if "child_peak_rss_bytes" in event
    )
    assert qualified_peak_rss <= execution_memory_bytes
    calculation_phase_timings = [
        event["child_calculation_phase_seconds"]
        for event in qualified_events
        if "child_calculation_phase_seconds" in event
    ]
    assert calculation_phase_timings
    assert all(
        isinstance(value, int | float) and value >= 0
        for phase in calculation_phase_timings
        for value in phase.values()
    )
    cancelled_batch_id = str(qualification["cancel_batch_id"])
    cancelled_exits = [
        event
        for event in batch_lifecycle
        if event["batch_id"] == cancelled_batch_id
        and event["event"] == "research_batch_execution_child_exited"
    ]
    assert len(cancelled_exits) == 1
    assert cancelled_exits[0]["acknowledged"] is False

    tracking_lifecycle_names = {
        "tracking_advance_claimed",
        "tracking_attempt_started",
        "tracking_advance_started",
        "tracking_execution_child_started",
        "tracking_execution_child_exited",
        "tracking_phase_completed",
        "tracking_checkpoint_published",
        "tracking_head_advanced",
    }
    tracking_lifecycle = [
        event for event in events if event.get("event") in tracking_lifecycle_names
    ]
    assert tracking_lifecycle
    assert tracking_lifecycle_names <= {
        str(event["event"]) for event in tracking_lifecycle
    }
    for event in tracking_lifecycle:
        assert event["component"] == "tracking_worker"
        assert event["worker_role"] == "tracking"
        assert str(event["track_id"]).startswith("track_")
        assert str(event["attempt_id"]).startswith("track_attempt_")
        assert "resource_type" not in event
        assert "resource_id" not in event
        assert "child_pid" not in event
        assert "current_session" not in event
        assert "checkpoint" not in event
        assert "object_key" not in event

    return {
        "worker_event_contract_verified": True,
        "worker_roles": sorted({str(event["worker_role"]) for event in worker_started}),
        "worker_lifecycle_event_count": len(research_lifecycle)
        + len(batch_lifecycle)
        + len(tracking_lifecycle),
        "tracking_lifecycle_event_count": len(tracking_lifecycle),
        "batch_worker_lifecycle_event_count": len(batch_lifecycle),
        "batch_qualification_event_count": len(qualified_events),
        "batch_qualification_peak_rss_bytes": qualified_peak_rss,
        "batch_qualification_phase_timing_count": len(calculation_phase_timings),
    }
def _verify_health(api_origin: str) -> dict[str, object]:
    status, payload, elapsed = _wait_for_readiness(api_origin, unavailable=None)
    assert status == 200
    assert payload == {"status": "ready", "dependencies": READY_DEPENDENCIES}
    liveness_status, liveness, liveness_elapsed = _request_health(
        api_origin,
        "/health/live",
    )
    assert liveness_status == 200
    assert liveness == {"status": "ok"}
    assert elapsed < 3
    assert liveness_elapsed < 3
    overview = _wait_for_data_overview(api_origin)
    assert overview["data_through_session"] == EXPECTED_OVERVIEW["data_through_session"]
    return {"api_data": "ready", "liveness": "ok", "readiness": "ready"}


def _wait_for_data_overview(api_origin: str) -> dict[str, object]:
    deadline = time.monotonic() + 20
    interval = Event()
    last_error: AssertionError | None = None
    while time.monotonic() < deadline:
        try:
            return _request_json(api_origin, "GET", "/api/data")
        except AssertionError as error:
            last_error = error
            interval.wait(0.05)
    raise AssertionError({"api_data_recovery_timeout": repr(last_error)})


def _verify_readiness_outage(
    api_origin: str,
    unavailable: str,
) -> dict[str, object]:
    assert unavailable in READY_DEPENDENCIES
    status, payload, elapsed = _wait_for_readiness(api_origin, unavailable=unavailable)
    expected_dependencies = json.loads(json.dumps(READY_DEPENDENCIES))
    expected_dependencies[unavailable] = {
        "status": "unavailable",
        "code": UNAVAILABLE_DEPENDENCY_CODES[unavailable],
    }
    assert status == 503
    assert payload == {"status": "unavailable", "dependencies": expected_dependencies}
    liveness_status, liveness, liveness_elapsed = _request_health(
        api_origin,
        "/health/live",
    )
    assert liveness_status == 200
    assert liveness == {"status": "ok"}
    assert elapsed < 3
    assert liveness_elapsed < 3
    return {"liveness": "ok", "unavailable_dependency": unavailable}


def _wait_for_readiness(
    api_origin: str,
    *,
    unavailable: str | None,
) -> tuple[int, dict[str, object], float]:
    timeout_seconds = 60 if unavailable is not None else 20
    deadline = time.monotonic() + timeout_seconds
    interval = Event()
    last: tuple[int, dict[str, object], float] | None = None
    expected_status = 200 if unavailable is None else 503
    expected_dependencies = json.loads(json.dumps(READY_DEPENDENCIES))
    if unavailable is not None:
        expected_dependencies[unavailable] = {
            "status": "unavailable",
            "code": UNAVAILABLE_DEPENDENCY_CODES[unavailable],
        }
    expected_payload = {
        "status": "ready" if unavailable is None else "unavailable",
        "dependencies": expected_dependencies,
    }
    while time.monotonic() < deadline:
        try:
            last = _request_health(api_origin, "/health/ready")
        except urllib.error.URLError:
            interval.wait(0.05)
            continue
        if last[0] == expected_status and last[1] == expected_payload:
            return last
        interval.wait(0.05)
    raise AssertionError({"readiness_timeout": unavailable, "last": last})


def _request_health(
    api_origin: str,
    path: str,
) -> tuple[int, dict[str, object], float]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(f"{api_origin}{path}", timeout=4) as response:
            status = response.status
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        status = error.code
        payload = json.loads(error.read())
    elapsed = time.monotonic() - started
    assert isinstance(payload, dict)
    return status, payload, elapsed


def _build_data_refresh_replay(replay: dict[str, object]) -> dict[str, object]:
    replay.pop("financial")
    snapshot = replay["snapshot"]
    assert isinstance(snapshot, dict)
    _source, canonical = normalize_tushare_snapshot(snapshot)
    calendar = canonical["research_calendar"]
    request_start = calendar[-20]
    request_end = calendar[-1]
    compact_start = request_start.replace("-", "")
    compact_end = request_end.replace("-", "")
    for table in ("calendar_sse", "calendar_szse"):
        snapshot[table] = [
            row
            for row in snapshot[table]
            if compact_start <= str(row["cal_date"]) <= compact_end
        ]
    for table in (
        "daily",
        "adjustments",
        "suspensions",
        "price_limits",
        "industry_membership",
    ):
        snapshot[table] = []
    snapshot["benchmark_index_daily"] = []
    for instrument in snapshot["stock_basic"]:
        instrument["list_date"] = EXPECTED_OVERVIEW["market_coverage"]["start"].replace(
            "-", ""
        )
    replay.update(
        {
            "format": "thesistrace-tushare-refresh-replay",
            "version": 2,
            "request_start": request_start,
            "request_end": request_end,
        }
    )
    return replay


def _verify_data_refresh_events(evidence_dir: Path) -> dict[str, object]:
    fixture = Path("/smoke/fixtures/tushare-financial-product-replay.json")
    replay = _build_data_refresh_replay(json.loads(fixture.read_text()))
    with tempfile.TemporaryDirectory(prefix="thesistrace-image-refresh-") as directory:
        replay_path = Path(directory) / "refresh-replay.json"
        replay_path.write_text(json.dumps(replay, sort_keys=True, separators=(",", ":")))
        submitted = subprocess.run(
            [
                "thesistrace-data-operator",
                "refresh",
                "--idempotency-key",
                "image-smoke-observability-refresh",
                "--as-of",
                "2026-08-06T15:00:00+08:00",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        processed = subprocess.run(
            [
                "thesistrace-data-operator",
                "work-refresh",
                "--replay",
                str(replay_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    (evidence_dir / "data-refresh-submit.stdout.json").write_text(submitted.stdout)
    (evidence_dir / "data-refresh-submit.stderr.log").write_text(submitted.stderr)
    (evidence_dir / "data-refresh.stdout.json").write_text(processed.stdout)
    (evidence_dir / "data-refresh.events.jsonl").write_text(processed.stderr)
    assert submitted.returncode == 0, submitted.stderr
    assert processed.returncode == 0, processed.stderr
    assert json.loads(submitted.stdout)["status"] == "accepted"
    assert submitted.stderr == ""
    assert json.loads(processed.stdout) == {"status": "processed"}
    events = [json.loads(line) for line in processed.stderr.splitlines()]
    expected_phases = [
        "current_head",
        "market",
        "validation",
        "materialization",
        "benchmark",
        "candidate_validation",
        "publication",
    ]
    assert [event["event"] for event in events] == [
        "data_refresh_started",
        *("data_refresh_phase_completed" for _phase in expected_phases),
        "data_refresh_succeeded",
    ]
    assert [
        event["phase"]
        for event in events
        if event["event"] == "data_refresh_phase_completed"
    ] == expected_phases
    return {"data_refresh_event_count": len(events), "data_refresh_stdout_verified": True}


def _verify_packaged_diagnostics(
    run_id: str,
    track_id: str,
    evidence_dir: Path,
) -> dict[str, object]:
    for resource, resource_id in (("research-run", run_id), ("daily-track", track_id)):
        completed = subprocess.run(
            ["thesistrace-core-diagnose", resource, resource_id],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        snapshot = json.loads(completed.stdout)
        (evidence_dir / f"diagnose-{resource}.stdout.json").write_text(completed.stdout)
        (evidence_dir / f"diagnose-{resource}.stderr.log").write_text(completed.stderr)
        assert completed.stdout == json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
        assert completed.stderr == ""
        identity_key = "run" if resource == "research-run" else "track"
        assert snapshot[identity_key]["id"] == resource_id
    return {
        "daily_track_diagnostic_verified": True,
        "research_run_diagnostic_verified": True,
    }


def _request_with_secret_canary(api_origin: str) -> None:
    request = urllib.request.Request(
        f"{api_origin}/api/data?token=observability-request-canary",
        headers={
            "Authorization": "Bearer observability-request-canary",
            "Cookie": "session=observability-request-canary",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
        assert isinstance(json.loads(response.read()), dict)


def _verify_observability_evidence(
    evidence_dir: Path,
    *,
    api_events: Path,
    worker_events: Path,
) -> dict[str, object]:
    api = _container_events(api_events)
    workers = _container_events(worker_events)
    completions = [event for event in api if event.get("event") == "http_request_completed"]
    assert completions
    assert any(
        event.get("component") == "core_api"
        and event.get("method") == "GET"
        and event.get("route") == "/api/data"
        and event.get("status_code") == 200
        and isinstance(event.get("http_request_id"), str)
        for event in completions
    )
    assert any(event.get("event") == "research_run_succeeded" for event in workers)
    assert any(event.get("event") == "tracking_checkpoint_published" for event in workers)
    refresh_events = [
        json.loads(line)
        for line in (evidence_dir / "data-refresh.events.jsonl").read_text().splitlines()
    ]
    assert any(event.get("event") == "data_refresh_phase_completed" for event in refresh_events)
    for path in (
        evidence_dir / "diagnose-research-run.stdout.json",
        evidence_dir / "diagnose-daily-track.stdout.json",
        evidence_dir / "data-refresh.stdout.json",
    ):
        assert isinstance(json.loads(path.read_text()), dict)
    canaries = {
        "mcp-image-action-token-canary",
        "mcp-image-read-token-canary",
        "observability-access-canary",
        "observability-secret-canary",
        "observability-request-canary",
    }
    for path in evidence_dir.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(errors="replace")
        for canary in canaries:
            assert canary not in content, {"secret_canary_detected_in": path.name}
    return {
        "api_completion_event_verified": True,
        "secret_canaries_absent": True,
    }


def _container_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in path.read_text().splitlines():
        payload = line.partition("|")[2].strip()
        if not payload.startswith("{"):
            continue
        value = json.loads(payload)
        if isinstance(value, dict):
            events.append(value)
    return events


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


def _wait_for_batch(
    api_origin: str,
    batch_id: str,
    *,
    timeout: float = 60,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    poll_interval = Event()
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-batches/{batch_id}")
        if last["status"] == "succeeded":
            if last["batch_kind"] == "factor_evaluation":
                assert last["progress"] == {
                    "completed_factor_tasks": len(last["items"]),
                    "total_factor_tasks": len(last["items"]),
                }
            else:
                assert last["progress"] == {
                    "shared_alpha_factor_status": "succeeded",
                    "completed_strategy_tasks": len(last["items"]),
                    "total_strategy_tasks": len(last["items"]),
                }
            return last
        if last["status"] in {"completed_with_failures", "failed", "cancelled"}:
            raise AssertionError(last)
        poll_interval.wait(0.1)
    raise AssertionError({"timeout": True, "last_batch": last})


def _wait_for_batch_status(
    api_origin: str,
    batch_id: str,
    expected_status: str,
    *,
    timeout: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    poll_interval = Event()
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-batches/{batch_id}")
        if last["status"] == expected_status:
            return last
        if last["status"] in {
            "succeeded",
            "completed_with_failures",
            "failed",
            "cancelled",
        }:
            raise AssertionError(last)
        poll_interval.wait(0.01)
    raise AssertionError(
        {
            "batch_status_timeout": expected_status,
            "last_batch": last,
        }
    )


def _wait_for_running_batch_attempt(
    api_origin: str,
    batch_id: str,
    *,
    timeout: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    poll_interval = Event()
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-batches/{batch_id}")
        if last["status"] == "running" and last["attempt"] is not None:
            return last
        if last["status"] in {
            "succeeded",
            "completed_with_failures",
            "failed",
            "cancelled",
        }:
            raise AssertionError(last)
        poll_interval.wait(0.01)
    raise AssertionError(
        {
            "running_batch_attempt_timeout": True,
            "last_batch": last,
        }
    )


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
    assert "bootstrap-financial" in result.stdout
    assert "refresh-financial" in result.stdout
    assert "inspect-financial-refresh" in result.stdout


def _assert_expected_overview(overview: dict[str, object]) -> None:
    assert {key: overview[key] for key in EXPECTED_OVERVIEW} == EXPECTED_OVERVIEW
    snapshot_sha256 = overview.get("benchmark_snapshot_sha256")
    assert isinstance(snapshot_sha256, str)
    assert len(snapshot_sha256) == 64
    assert all(character in "0123456789abcdef" for character in snapshot_sha256)
    for field in ("last_market_refresh_at", "last_financial_refresh_at"):
        refreshed_at = overview.get(field)
        assert isinstance(refreshed_at, str)
        assert refreshed_at.endswith(("+00:00", "Z"))
    benchmark_published_at = overview.get("benchmark_last_published_at")
    assert isinstance(benchmark_published_at, str)
    assert benchmark_published_at.endswith(("+00:00", "Z"))


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
                          AND pin.status = 'active') AS active_pin_count,
                       (
                           SELECT octet_length(manifest.manifest_bytes)
                                  + coalesce(sum(object.byte_size), 0)
                           FROM publication.manifests AS manifest
                           LEFT JOIN publication.manifest_objects AS manifest_object
                             ON manifest_object.manifest_sha256 = manifest.sha256
                           LEFT JOIN publication.objects AS object
                             ON object.sha256 = manifest_object.object_sha256
                           WHERE manifest.sha256 = run.result_manifest_sha256
                           GROUP BY manifest.manifest_bytes
                       ) AS object_bytes,
                       coalesce((
                           SELECT jsonb_agg(
                               jsonb_build_object(
                                   'logical_name', manifest_object.logical_name,
                                   'object_sha256', manifest_object.object_sha256,
                                   'byte_size', object.byte_size
                               ) ORDER BY manifest_object.ordinal
                           )
                           FROM publication.manifest_objects AS manifest_object
                           JOIN publication.objects AS object
                             ON object.sha256 = manifest_object.object_sha256
                           WHERE manifest_object.manifest_sha256 = run.result_manifest_sha256
                       ), '[]'::jsonb) AS object_references
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
        stored_result = read_result_bundle(bundle, research_kind=research_kind)
        result_object_names = sorted(stored_result)
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
            position_partition_names = {
                name
                for name in payload_names
                if name.startswith(RESULT_TERMINAL_POSITION_PARTITION_PREFIX)
            }
            assert partition_names
            assert set(payload_names) == (
                set(result_object_names)
                | {"terminal_positions"}
                | partition_names
                | position_partition_names
            )
        return {
            "active_pin_count": int(row["active_pin_count"]),
            "manifest_sha256": manifest_sha256,
            "object_references": row["object_references"],
            "object_bytes": int(row["object_bytes"]),
            "attempt_count": len(row["attempt_snapshots"]),
            "payload_names": payload_names,
            "provenance": provenance,
            "result_object_names": result_object_names,
            "stored_result": stored_result,
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


def _assert_batch_owned_durable_result(settings: CoreSettings, run_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.execution_owner, run.status,
                       run.result_manifest_sha256,
                       run.result_provenance->>'research_run_id' AS provenance_run_id,
                       (SELECT count(*) FROM research_runs.attempts AS attempt
                        WHERE attempt.run_id = run.id) AS attempt_count
                FROM research_runs.runs AS run
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row == {
            "execution_owner": "research_batch",
            "status": "succeeded",
            "result_manifest_sha256": row["result_manifest_sha256"],
            "provenance_run_id": run_id,
            "attempt_count": 0,
        }
        assert isinstance(row["result_manifest_sha256"], str)
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
        with urllib.request.urlopen(
            request,
            timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
        ) as response:
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
        assert response.headers.get("Cache-Control") == "no-cache"
        body = response.read().decode()
    assert '<div id="root"></div>' in body


def _directory_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative_path = path.relative_to(root)
        digest.update(relative_path.as_posix().encode())
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

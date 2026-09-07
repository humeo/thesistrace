from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from threading import Event

import boto3
from benchmark_financial_io import build_market_benchmark_stream

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.io_benchmark import (
    is_research_execution_child_started_event,
    long_research_qualification_outcome,
    long_research_qualification_summary,
    long_research_sample_qualification,
)
from thesistrace.data.io_metrics import measure_data_io
from thesistrace.data.lifecycle import DatasetLifecycle
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.product_state import product_state_counts
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_run.result import read_result_bundle

_PROFILE_PATH = Path(__file__).with_name("long-research-2010-profile.json")
_POLL_SECONDS = 0.05
_RUN_TIMEOUT_SECONDS = 720
_TERMINAL = {"succeeded", "failed", "cancelled"}
_RESEARCH_KINDS = ("factor_evaluation", "strategy_backtest")
_POLL_EVENT = Event()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Qualify the fixed 2010-scale Research workload in the Production Image."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    preload = subparsers.add_parser("preload")
    preload.add_argument("--output", type=Path, required=True)
    sample = subparsers.add_parser("sample")
    sample.add_argument("--phase", choices=("cold", "warm"), required=True)
    sample.add_argument("--research-kind", choices=_RESEARCH_KINDS, required=True)
    sample.add_argument("--index", type=int, required=True)
    sample.add_argument("--log", type=Path, required=True)
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--require-fresh-product-state", action="store_true")
    cancel = subparsers.add_parser("cancel")
    cancel.add_argument("--research-kind", choices=_RESEARCH_KINDS, required=True)
    cancel.add_argument("--log", type=Path, required=True)
    cancel.add_argument("--output", type=Path, required=True)
    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--samples", type=Path, required=True)
    assemble.add_argument("--image-revision", required=True)
    assemble.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        _write_json(arguments.output, _prepare())
    elif arguments.command == "preload":
        _write_json(arguments.output, _preload_canonical_objects())
    elif arguments.command == "sample":
        evidence = _execute_sample(
            arguments.phase,
            arguments.index,
            arguments.log,
            research_kind=arguments.research_kind,
            require_fresh_product_state=arguments.require_fresh_product_state,
        )
        outcome = long_research_sample_qualification(
            evidence,
            research_kind=arguments.research_kind,
            phase=arguments.phase,
            index=arguments.index,
        )
        evidence["qualification"] = outcome
        _write_json(arguments.output, evidence)
        _raise_for_failed_qualification(outcome)
    elif arguments.command == "cancel":
        _write_json(
            arguments.output,
            _cancel_sample(arguments.log, research_kind=arguments.research_kind),
        )
    else:
        evidence = _assemble(arguments.samples, arguments.image_revision)
        outcome = long_research_qualification_outcome(evidence)
        evidence["qualification"] = outcome
        _write_json(arguments.output, evidence)
        _raise_for_failed_qualification(outcome)


def _raise_for_failed_qualification(outcome: dict[str, str | None]) -> None:
    if outcome == {"status": "passed", "failure_reason": None}:
        return
    failure_reason = outcome.get("failure_reason")
    if outcome.get("status") != "failed" or not failure_reason:
        raise RuntimeError("qualification outcome is invalid")
    raise AssertionError(failure_reason)


def _prepare() -> dict[str, object]:
    profile = _read_json(_PROFILE_PATH)
    settings = CoreSettings.from_environment()
    sessions = _weekdays(
        str(profile["generation_calendar_start"]),
        str(profile["workload_end_date"]),
    )
    store = MountedGenerationStore(settings.data_mount)
    generation = store.materialize_bootstrap_stream(
        build_market_benchmark_stream(
            sessions,
            int(profile["ordinary_a_share_instrument_count"]),
            int(profile["execution_universe_size"]),
            int(profile["market_dense_session_count"]),
        ),
        prepared_at=datetime(2026, 8, 13, 9, tzinfo=UTC),
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        current = lifecycle.current_pointer()
        if current is None:
            lifecycle.protect_candidate(
                operation_id="long-research-qualification-head",
                generation_manifest_sha256=generation.manifest_sha256,
                lease_seconds=3600,
            )
            lifecycle.compare_and_swap_head(
                expected_generation_manifest_sha256=None,
                candidate_generation_manifest_sha256=generation.manifest_sha256,
                operation_id="long-research-qualification-head",
            )
        elif current != generation.manifest_sha256:
            raise RuntimeError("qualification Dataset Head already names another Generation")
    finally:
        database.close()
    return {
        "generation_manifest_sha256": generation.manifest_sha256,
        "data_through_session": generation.data_through_session,
        "research_session_count": len(sessions),
        "profile_sha256": hashlib.sha256(canonical_json_bytes(profile)).hexdigest(),
    }


def _execute_sample(
    phase: str,
    index: int,
    log_path: Path,
    *,
    research_kind: str,
    require_fresh_product_state: bool,
) -> dict[str, object]:
    profile = _read_json(_PROFILE_PATH)
    api_origin = _required_environment("THESISTRACE_TEST_API_ORIGIN").rstrip("/")
    _ensure_researcher_bootstrap(api_origin)
    fresh_product_state: dict[str, int] | None = None
    if require_fresh_product_state:
        fresh_product_state = _require_fresh_product_state()
    admission_started = time.perf_counter()
    accepted = _admit(
        api_origin,
        profile,
        research_kind=research_kind,
        request_id=f"qualification-{research_kind}-{phase}-{index}",
    )
    admission_duration_ms = round((time.perf_counter() - admission_started) * 1000, 3)
    run_id = str(accepted["id"])
    process = _start_worker(log_path, cold=phase == "cold")
    observation = _observe_run(run_id, process)
    process_exit_code = process.wait(timeout=10)
    events = _read_events(log_path)
    if observation["status"] != "succeeded" or process_exit_code != 0:
        raise RuntimeError(
            f"qualification sample failed: run={observation}, exit={process_exit_code}"
        )
    last_io = _last_chunk_io(events)
    child_exit_codes = [
        event.get("exit_code")
        for event in events
        if event.get("event") == "research_execution_child_exited"
    ]
    if child_exit_codes != [0]:
        raise RuntimeError(f"qualification child exit evidence is invalid: {child_exit_codes}")
    result = _result_evidence(run_id, research_kind=research_kind)
    phase_timings = _phase_timings(events)
    strategy_continuations = [
        event.get("strategy_continuation_present")
        for event in events
        if event.get("event") == "research_execution_chunk_received"
    ]
    strategy_observation_count = sum(
        int(event.get("strategy_observation_count", 0))
        for event in events
        if event.get("event") == "research_execution_chunk_received"
    )
    return {
        "phase": phase,
        "index": index,
        "research_kind": research_kind,
        "run_id": run_id,
        "admission_duration_ms": admission_duration_ms,
        "attempt_duration_ms": observation["duration_ms"],
        "duration_ms": round(admission_duration_ms + float(observation["duration_ms"]), 3),
        "peak_rss_bytes": max(
            int(event["child_peak_rss_bytes"])
            for event in events
            if event.get("event") == "research_execution_chunk_received"
        ),
        "first_checkpoint_latency_ms": observation["first_checkpoint_latency_ms"],
        **last_io,
        "process_exit_code": child_exit_codes[0],
        "worker_exit_code": process_exit_code,
        "result_manifest_sha256": observation["result_manifest_sha256"],
        "generation_manifest_sha256": observation["generation_manifest_sha256"],
        "chunk_session_count": observation["chunk_session_count"],
        "chunk_count": observation["chunk_count"],
        "attempt_id": observation["attempt_id"],
        "phase_timings_seconds": phase_timings,
        "strategy_continuation_present": any(
            value is True for value in strategy_continuations
        ),
        "strategy_observation_count": strategy_observation_count,
        **result,
        "fresh_product_state_verified": fresh_product_state is not None,
        "fresh_product_state_counts": fresh_product_state,
    }


def _require_fresh_product_state() -> dict[str, int]:
    settings = CoreSettings.from_environment()
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
        observed = product_state_counts(database, s3, bucket=settings.s3_bucket)
    finally:
        s3.close()
        database.close()
    if any(observed.values()):
        raise RuntimeError(
            f"qualification sample would reuse Product State: {observed}"
        )
    return observed


def _preload_canonical_objects() -> dict[str, object]:
    profile = _read_json(_PROFILE_PATH)
    settings = CoreSettings.from_environment()
    product_state_before = _require_fresh_product_state()
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        pointer = DatasetLifecycle(database, settings.data_mount).current_pointer()
        if pointer is None:
            raise RuntimeError("qualification Dataset Head is unavailable")
        generation_manifest_sha256 = pointer.generation_manifest_sha256
    finally:
        database.close()
    store = MountedGenerationStore(settings.data_mount)
    admission = store.open_admission(generation_manifest_sha256)
    calendar = admission.research_calendar
    start_date = str(profile["workload_start_date"])
    end_date = str(profile["workload_end_date"])
    selected = tuple(session for session in calendar if start_date <= session <= end_date)
    if not selected:
        raise RuntimeError("qualification preload has no Research Sessions")
    first = calendar.index(selected[0])
    with measure_data_io() as measurement:
        for offset in range(0, len(selected), 64):
            context_start = max(0, first + offset - 20)
            context_end = first + min(offset + 64, len(selected))
            store.read_columnar_slice(
                generation_manifest_sha256,
                sessions=list(calendar[context_start:context_end]),
                universe_name=str(profile["universe"]),
                neutralization="none",
                field_bindings={"price.close.adjusted": "close"},
                fact_instrument_ids=frozenset(),
            )
    return {
        "generation_manifest_sha256": generation_manifest_sha256,
        "chunk_count": math.ceil(len(selected) / 64),
        "research_session_count": len(selected),
        "product_state_before": product_state_before,
        "product_state_after": _require_fresh_product_state(),
        **measurement.snapshot(),
    }


def _cancel_sample(log_path: Path, *, research_kind: str) -> dict[str, object]:
    profile = _read_json(_PROFILE_PATH)
    api_origin = _required_environment("THESISTRACE_TEST_API_ORIGIN").rstrip("/")
    _ensure_researcher_bootstrap(api_origin)
    fresh_product_state = _require_fresh_product_state()
    accepted = _admit(
        api_origin,
        profile,
        research_kind=research_kind,
        request_id=f"qualification-{research_kind}-cancel",
    )
    run_id = str(accepted["id"])
    process = _start_worker(log_path, cold=False)
    _wait_for_child_start(run_id, log_path, process)
    started = time.perf_counter()
    cancelled = _request_json(
        api_origin,
        "POST",
        f"/api/research-runs/{run_id}/cancel",
        {"request_id": f"qualification-{research_kind}-cancel-command"},
    )
    if cancelled["status"] not in {"cancelling", "cancelled"}:
        raise RuntimeError(f"qualification cancellation was not accepted: {cancelled}")
    detail = _wait_for_public_status(api_origin, run_id, "cancelled", timeout=5)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    worker_exit_code = process.wait(timeout=5)
    if worker_exit_code != 0:
        raise RuntimeError(f"qualification cancellation Worker exited {worker_exit_code}")
    events = _read_events(log_path)
    exits = [event for event in events if event.get("event") == "research_execution_child_exited"]
    if len(exits) != 1:
        raise RuntimeError("qualification cancellation has no unique child exit")
    cancelled_state = _cancelled_run_state(run_id)
    return {
        "research_kind": research_kind,
        "run_id": run_id,
        "status": detail["status"],
        "cancellation_latency_ms": latency_ms,
        "worker_exit_code": worker_exit_code,
        "child_exit_code": exits[0].get("exit_code"),
        "child_acknowledged": exits[0].get("acknowledged"),
        "fresh_product_state_verified": True,
        "fresh_product_state_counts": fresh_product_state,
        **cancelled_state,
    }


def _cancelled_run_state(run_id: str) -> dict[str, object]:
    settings = CoreSettings.from_environment()
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.status, run.result_manifest_sha256,
                       (SELECT count(*)
                        FROM research_runs.execution_checkpoints AS checkpoint
                        WHERE checkpoint.run_id = run.id) AS checkpoint_count,
                       (SELECT count(*)
                        FROM research_runs.attempts AS attempt
                        JOIN data.generation_pins AS pin
                          ON pin.id = attempt.generation_pin_id
                        WHERE attempt.run_id = run.id AND pin.status = 'active')
                           AS active_pin_count
                FROM research_runs.runs AS run
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
    finally:
        database.close()
    if row is None or row["status"] != "cancelled":
        raise RuntimeError(f"qualification cancellation state is invalid: {row}")
    return {
        "result_manifest_sha256": row["result_manifest_sha256"],
        "checkpoint_count": int(row["checkpoint_count"]),
        "active_pin_count": int(row["active_pin_count"]),
    }


def _result_evidence(run_id: str, *, research_kind: str) -> dict[str, object]:
    settings = CoreSettings.from_environment()
    with open_core_runtime(settings) as runtime:
        with runtime.database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.result_manifest_sha256, run.result_provenance,
                       (SELECT count(*)
                        FROM research_runs.execution_checkpoints AS checkpoint
                        WHERE checkpoint.run_id = run.id) AS checkpoint_count,
                       (SELECT count(*)
                        FROM research_runs.attempts AS attempt
                        JOIN data.generation_pins AS pin
                          ON pin.id = attempt.generation_pin_id
                        WHERE attempt.run_id = run.id AND pin.status = 'active')
                           AS active_pin_count
                FROM research_runs.runs AS run
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None or row["result_manifest_sha256"] is None:
            raise RuntimeError("qualification Result publication is unavailable")
        manifest_sha256 = str(row["result_manifest_sha256"])
        bundle = runtime.publication.read(
            PublishedRef(
                manifest_sha256=manifest_sha256,
                kind="research.result",
                provenance=row["result_provenance"],
            )
        )
        result = read_result_bundle(bundle, research_kind=research_kind)
    return {
        "result_payload_names": sorted(bundle.payloads),
        "result_object_names": sorted(result),
        "factor_summary_sha256": hashlib.sha256(
            canonical_json_bytes(result["factor_summary"])
        ).hexdigest(),
        "checkpoint_count_after_success": int(row["checkpoint_count"]),
        "active_pin_count_after_success": int(row["active_pin_count"]),
    }


def _phase_timings(events: list[dict[str, object]]) -> dict[str, float]:
    totals = {
        "data_read": 0.0,
        "calculation": 0.0,
        "input": 0.0,
        "alpha_and_pending": 0.0,
        "factor": 0.0,
        "strategy": 0.0,
        "finalize": 0.0,
        "checkpoint_commit": 0.0,
    }
    for event in events:
        if event.get("event") == "research_execution_chunk_received":
            totals["data_read"] += float(event["child_data_read_seconds"])
            totals["calculation"] += float(event["child_calculation_seconds"])
            phases = event.get("child_calculation_phase_seconds")
            if not isinstance(phases, dict):
                raise RuntimeError("qualification calculation phase evidence is invalid")
            for name in ("input", "alpha_and_pending", "factor", "strategy", "finalize"):
                totals[name] += float(phases[name])
        elif event.get("event") == "research_execution_chunk_committed":
            totals["checkpoint_commit"] += float(event["supervisor_commit_seconds"])
    return {name: round(value, 6) for name, value in totals.items()}


def _assemble(samples_path: Path, image_revision: str) -> dict[str, object]:
    research_kinds: dict[str, object] = {}
    all_samples: list[dict[str, object]] = []
    for research_kind in _RESEARCH_KINDS:
        cold = [
            _read_json(samples_path / f"{research_kind}-cold-{index}.json")
            for index in range(5)
        ]
        warm = [
            _read_json(samples_path / f"{research_kind}-warm-{index}.json")
            for index in range(5)
        ]
        cancellation = _read_json(samples_path / f"{research_kind}-cancellation.json")
        all_samples.extend((*cold, *warm))
        research_kinds[research_kind] = {
            "cold": {"samples": cold},
            "warm": {"samples": warm},
            "cancellation": cancellation,
        }
    generation_ids = {str(item["generation_manifest_sha256"]) for item in all_samples}
    plans = {(int(item["chunk_session_count"]), int(item["chunk_count"])) for item in all_samples}
    factor_summary_ids = {str(item["factor_summary_sha256"]) for item in all_samples}
    generation_manifest_sha256 = sorted(generation_ids)[0]
    chunk_session_count, chunk_count = sorted(plans)[0]
    factor_summary_sha256 = sorted(factor_summary_ids)[0]
    preload = _read_json(samples_path / "preload.json")
    evidence = {
        "format": "thesistrace-long-research-qualification",
        "version": 2,
        "image": {"revision": image_revision},
        "capacity": {
            "cpu_count": 2,
            "memory_bytes": 2 * 1024 * 1024 * 1024,
            "execution_memory_bytes": 1536 * 1024 * 1024,
            "calculation_threads": 2,
            "slot_count": 1,
        },
        "workload": {
            "formula": "rank(pct_change(close, 20))",
            "universe": "top3000",
            "start_date": "2010-01-04",
            "end_date": "2026-08-13",
            "generation_manifest_sha256": generation_manifest_sha256,
            "chunk_session_count": chunk_session_count,
            "chunk_count": chunk_count,
        },
        "warm_preload": preload,
        "research_kinds": research_kinds,
        "scientific_equivalence": {
            "factor_summary_sha256": factor_summary_sha256,
            "sample_count": len(all_samples),
        },
    }
    evidence["summary"] = long_research_qualification_summary(evidence)
    return evidence


def _admit(
    api_origin: str,
    profile: dict[str, object],
    *,
    research_kind: str,
    request_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": f"Long Research Qualification {request_id}",
        "hypothesis": "The fixed long-history momentum workload is executable.",
        "start_date": profile["workload_start_date"],
        "end_date": profile["workload_end_date"],
        "formula": profile["formula"],
        "universe": profile["universe"],
        "neutralization": "none",
        "research_kind": research_kind,
    }
    if research_kind == "strategy_backtest":
        payload.update(
            {
                "holdings_count": 100,
                "rebalance_every_sessions": 5,
            }
        )
    accepted = _request_json(
        api_origin,
        "POST",
        "/api/research-runs",
        payload,
    )
    if accepted.get("status") != "queued":
        raise RuntimeError(f"qualification ResearchRun was not admitted: {accepted}")
    return accepted


def _start_worker(log_path: Path, *, cold: bool) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
    environment = dict(os.environ)
    if cold:
        environment["THESISTRACE_QUALIFICATION_COLD_DATA_READS"] = "1"
    else:
        environment.pop("THESISTRACE_QUALIFICATION_COLD_DATA_READS", None)
    process = subprocess.Popen(
        [
            "thesistrace-core-worker",
            "--role",
            "research",
            "--once",
            "--cpu-count",
            "2",
            "--memory-bytes",
            str(2 * 1024 * 1024 * 1024),
            "--execution-memory-bytes",
            str(1536 * 1024 * 1024),
            "--calculation-threads",
            "2",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    log.close()
    return process


def _observe_run(run_id: str, process: subprocess.Popen[bytes]) -> dict[str, object]:
    settings = CoreSettings.from_environment()
    database = PostgresDatabase(settings.database_url)
    database.open()
    deadline = time.monotonic() + _RUN_TIMEOUT_SECONDS
    attempt_visible_at: float | None = None
    first_checkpoint_visible_at: float | None = None
    terminal_visible_at: float | None = None
    last: dict[str, object] | None = None
    try:
        while time.monotonic() < deadline:
            with database.transaction() as transaction:
                row = transaction.execute(
                    """
                    SELECT run.status, run.result_manifest_sha256, run.immutable_input,
                           attempt.id AS attempt_id, attempt.started_at,
                           attempt.finished_at, attempt.failure_reason,
                           (SELECT min(created_at)
                            FROM research_runs.execution_checkpoints
                            WHERE run_id = run.id) AS first_checkpoint_at
                    FROM research_runs.runs AS run
                    LEFT JOIN LATERAL (
                        SELECT * FROM research_runs.attempts
                        WHERE run_id = run.id ORDER BY ordinal DESC LIMIT 1
                    ) AS attempt ON true
                    WHERE run.id = %s
                    """,
                    (run_id,),
                ).fetchone()
            if row is not None:
                last = dict(row)
                if (
                    attempt_visible_at is None
                    and isinstance(row.get("started_at"), datetime)
                ):
                    attempt_visible_at = time.perf_counter()
                if (
                    first_checkpoint_visible_at is None
                    and isinstance(row.get("first_checkpoint_at"), datetime)
                ):
                    first_checkpoint_visible_at = time.perf_counter()
                if row["status"] in _TERMINAL:
                    terminal_visible_at = time.perf_counter()
                    break
            if process.poll() is not None and (last is None or last["status"] not in _TERMINAL):
                raise RuntimeError(f"qualification Worker exited before terminal Run state: {last}")
            _POLL_EVENT.wait(_POLL_SECONDS)
        else:
            process.terminate()
            raise TimeoutError(f"qualification ResearchRun exceeded {_RUN_TIMEOUT_SECONDS}s")
    finally:
        database.close()
    assert last is not None
    started_at = last.get("started_at")
    immutable_input = last.get("immutable_input")
    if (
        not isinstance(started_at, datetime)
        or not isinstance(last.get("finished_at"), datetime)
        or attempt_visible_at is None
        or first_checkpoint_visible_at is None
        or terminal_visible_at is None
        or not isinstance(immutable_input, dict)
    ):
        raise RuntimeError(f"qualification durable timing evidence is incomplete: {last}")
    plan = immutable_input["execution_plan"]
    admission = immutable_input["data_admission"]
    return {
        "status": last["status"],
        "attempt_id": last["attempt_id"],
        "failure_reason": last["failure_reason"],
        "duration_ms": round((terminal_visible_at - attempt_visible_at) * 1000, 3),
        "first_checkpoint_latency_ms": round(
            (first_checkpoint_visible_at - attempt_visible_at) * 1000, 3
        ),
        "result_manifest_sha256": last["result_manifest_sha256"],
        "generation_manifest_sha256": admission["generation_manifest_sha256"],
        "chunk_session_count": plan["chunk_session_count"],
        "chunk_count": len(plan["chunks"]),
    }


def _wait_for_child_start(
    run_id: str,
    log_path: Path,
    process: subprocess.Popen[bytes],
) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(
            is_research_execution_child_started_event(event, run_id)
            for event in _read_events(log_path)
        ):
            return
        if process.poll() is not None:
            raise RuntimeError("qualification Worker exited before child start")
        _POLL_EVENT.wait(_POLL_SECONDS)
    raise TimeoutError("qualification child did not start within 30 seconds")


def _wait_for_public_status(
    api_origin: str, run_id: str, expected: str, *, timeout: float
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = _request_json(api_origin, "GET", f"/api/research-runs/{run_id}")
        if last.get("status") == expected:
            return last
        _POLL_EVENT.wait(_POLL_SECONDS)
    raise TimeoutError(f"ResearchRun did not reach {expected}: {last}")


def _last_chunk_io(events: list[dict[str, object]]) -> dict[str, int]:
    values = [
        event["data_io"]
        for event in events
        if event.get("event") == "research_execution_chunk_received"
    ]
    if not values or not isinstance(values[-1], dict):
        raise RuntimeError("qualification has no child I/O evidence")
    return {str(key): int(value) for key, value in values[-1].items()}


def _read_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _request_json(
    origin: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = None if payload is None else canonical_json_bytes(payload)
    request = urllib.request.Request(
        f"{origin}{path}",
        data=data,
        method=method,
        headers=_authenticated_headers(method, has_body=data is not None),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"qualification API {method} {path} failed: {error.code} {error.read()!r}"
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError(f"qualification API {method} {path} returned no object")
    return value


def _ensure_researcher_bootstrap(api_origin: str) -> None:
    response = _request_json(api_origin, "POST", "/api/researcher/bootstrap")
    expected = {
        "researcher_id": _auth_session()["researcher_id"],
        "system_folders": {
            "default": "folder_default",
            "batch_research": "folder_batch_research",
        },
    }
    if response != expected:
        raise RuntimeError(f"qualification Researcher bootstrap is invalid: {response}")


def _authenticated_headers(method: str, *, has_body: bool) -> dict[str, str]:
    headers = {"Cookie": _auth_session()["cookie"]}
    if method in {"POST", "PATCH", "DELETE"}:
        headers["Origin"] = _required_environment("THESISTRACE_PUBLIC_ORIGIN")
    if has_body:
        headers["Content-Type"] = "application/json"
    return headers


@lru_cache(maxsize=1)
def _auth_session() -> dict[str, str]:
    path = Path(_required_environment("THESISTRACE_TEST_AUTH_SESSION_FILE"))
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or set(value) != {"cookie", "researcher_id"}
        or not all(isinstance(item, str) and item for item in value.values())
    ):
        raise RuntimeError("Long Research Qualification Auth Session is invalid")
    return value


def _weekdays(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    final = date.fromisoformat(end)
    sessions: list[str] = []
    while current <= final:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    return sessions


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment is missing: {name}")
    return value


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

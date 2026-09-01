from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, FinancialCandidateStore, MountedGenerationStore
from thesistrace.data.financial_candidate import FinancialDiscoveryPublication
from thesistrace.data.financial_collection import CompletedFinancialCollection
from thesistrace.entrypoints.runtime import CoreSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("lagged", "recovered"))
    mode = parser.parse_args().mode
    settings = CoreSettings.from_environment()
    if mode == "lagged":
        outcome = _run_operator(
            "refresh",
            "--idempotency-key",
            "financial-release-market-refresh",
            "--as-of",
            "2026-08-11T18:00:00+08:00",
        )
        if outcome.get("status") not in {"accepted", "succeeded"}:
            raise RuntimeError(f"Market Refresh was not accepted: {outcome}")
        outcome = _wait_for_market_refresh("financial-release-market-refresh")
    else:
        database = PostgresDatabase(settings.database_url)
        database.open()
        try:
            pointer = DatasetLifecycle(database, settings.data_mount).current_pointer()
            if pointer is None:
                raise RuntimeError("financial release Head is unavailable")
            root = MountedGenerationStore(settings.data_mount).inspect_root(
                pointer.generation_manifest_sha256
            )
        finally:
            database.close()
        outcome = _publish_ready_financial_fixture(
            database_url=settings.database_url,
            mount_root=settings.data_mount,
            generation=root.manifest_sha256,
        )
    print(json.dumps({"mode": mode, "operator_outcome": outcome}, sort_keys=True))


def _publish_ready_financial_fixture(
    *,
    database_url: str,
    mount_root: Path,
    generation: str,
) -> dict[str, object]:
    prepared_at = datetime(2026, 8, 11, 10, tzinfo=UTC)
    candidates = FinancialCandidateStore(mount_root)
    generations = MountedGenerationStore(mount_root)
    root = generations.inspect_root(generation)
    prior_manifest = root.financial_candidate_manifest_sha256
    if prior_manifest is None:
        raise RuntimeError("financial release candidate is unavailable")
    prior = candidates.reopen(prior_manifest)
    candidate = candidates.rebuild_daily(
        CompletedFinancialCollection(
            idempotency_key="financial-release-financial-fixture",
            generation_manifest_sha256=generation,
            contract=candidates.collection_contract(prior_manifest),
            finished_at=prepared_at.isoformat(),
            target_count=0,
            shards=(),
        ),
        prior_candidate_manifest_sha256=prior_manifest,
        discovery=FinancialDiscoveryPublication(
            baseline_session=(
                prior.discovery_baseline_session or prior.observation_through_session
            ),
            attempted_through_session="2026-08-11",
            complete_through_session="2026-08-11",
            source_lineage_sha256="d" * 64,
            readiness_status="ready",
            pending_instrument_count=0,
            discovery_gap_count=0,
            earliest_unresolved_date=None,
        ),
    )
    composed = generations.compose_financial_candidate(
        generation,
        candidate.manifest_sha256,
        prepared_at=prepared_at,
        publication_coordinate="e" * 64,
    )
    database = PostgresDatabase(database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, mount_root)
        lifecycle.protect_candidate(
            operation_id="financial-release-financial-fixture",
            generation_manifest_sha256=composed.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=generation,
            candidate_generation_manifest_sha256=composed.manifest_sha256,
            operation_id="financial-release-financial-fixture",
        )
    finally:
        database.close()
    return {
        "status": "succeeded",
        "generation_manifest_sha256": composed.manifest_sha256,
    }


def _run_operator(*arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        ["thesistrace-data-operator", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"private Data Operator failed ({completed.returncode}): {completed.stderr}"
        )
    outcome = json.loads(completed.stdout)
    if not isinstance(outcome, dict):
        raise RuntimeError("private Data Operator returned an invalid outcome")
    return outcome


def _wait_for_market_refresh(idempotency_key: str) -> dict[str, object]:
    deadline = time.monotonic() + 60
    interval = Event()
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = _run_operator(
            "inspect-refresh",
            "--idempotency-key",
            idempotency_key,
        )
        if last.get("status") == "succeeded":
            return last
        if last.get("status") == "failed":
            raise RuntimeError(f"Market Refresh failed: {last}")
        interval.wait(0.1)
    raise RuntimeError(f"Market Refresh did not finish: {last}")


if __name__ == "__main__":
    main()

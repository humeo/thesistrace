from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_financial_indicator import (
    TushareFinancialIndicatorProvider,
)
from thesistrace.adapters.tushare_replay import ReplayTushareProvider
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.financial_indicator_candidate import (
    FinancialIndicatorCandidateStore,
)
from thesistrace.data.financial_indicator_collection import FinancialIndicatorCollector
from thesistrace.entrypoints.runtime import CoreSettings

SESSIONS = (
    "2010-01-04",
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
)
def main() -> None:
    settings = CoreSettings.from_environment()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        try:
            s3.create_bucket(Bucket=settings.s3_bucket)
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code")) not in {
                "BucketAlreadyExists",
                "BucketAlreadyOwnedByYou",
            }:
                raise
    finally:
        s3.close()

    store = MountedGenerationStore(settings.data_mount)
    database = PostgresDatabase(settings.database_url)
    database.open()
    lifecycle = DatasetLifecycle(database, settings.data_mount)
    current = lifecycle.current_pointer()
    if current is None:
        raise RuntimeError("private Data Operator bootstrap Head is unavailable")
    market = store.inspect_root(current.generation_manifest_sha256)
    if market.data_through_session != SESSIONS[-1]:
        raise RuntimeError("private Data Operator bootstrap coverage is unexpected")
    database.close()
    fixture_root = Path(__file__).resolve().parents[2] / "fixtures"
    completed = subprocess.run(
        [
            "thesistrace-data-operator",
            "bootstrap-financial",
            "--idempotency-key",
            "financial-release-initial-publication",
            "--generation-manifest-sha256",
            market.manifest_sha256,
            "--capability-report",
            str(fixture_root / "tushare-financial-capability.json"),
            "--observation-through-session",
            SESSIONS[-1],
            "--replay",
            str(fixture_root / "tushare-financial-product-replay.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"initial Financial Refresh failed: {completed.stderr}")
    outcome = json.loads(completed.stdout)
    generation_manifest_sha256 = str(outcome["generation_manifest_sha256"])
    generation_manifest_sha256 = publish_indicator_fixture(
        settings, generation_manifest_sha256,
        fixture_root / "tushare-financial-product-replay.json",
    )
    print(
        json.dumps(
            {
                "coverage_start": SESSIONS[0],
                "data_through_session": SESSIONS[-1],
                "generation_manifest_sha256": generation_manifest_sha256,
                "operator_status": outcome["status"],
            },
            sort_keys=True,
        )
    )


def publish_indicator_fixture(
    settings: CoreSettings, generation: str, replay_path: Path,
) -> str:
    prepared_at = datetime.now(UTC)
    store = MountedGenerationStore(settings.data_mount)
    root = store.inspect_root(generation)
    checked_through = root.data_through_session
    identities = store.read_historical_ordinary_a_share_identities(generation)
    provider = TushareFinancialIndicatorProvider(
        ReplayTushareProvider(replay_path),
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        collector = FinancialIndicatorCollector(
            database, settings.data_mount, provider, clock=lambda: prepared_at,
        )
        candidates = FinancialIndicatorCandidateStore(settings.data_mount)
        prior_family = next(
            (family for family in root.families
             if family.family_id == "equity.financial_indicator"), None,
        )
        prior = candidates.reopen(prior_family.manifest_sha256) if prior_family else None
        evidence = list(prior["collection_evidence_sha256s"]) if prior else []
        for identity in identities:
            collected = collector.collect(
                collection_key=f"e2e-indicators:{checked_through}:{identity.instrument_id}",
                identity=identity,
                start_date="19900101",
                end_date=checked_through.replace("-", ""),
                checked_through=checked_through,
                required_reports=(),
            )
            if collected.pending_reports:
                raise RuntimeError("initial indicator collection has unresolved reports")
            evidence.append(collected.evidence_sha256)
        candidate = candidates.build(
            collection_evidence_sha256s=evidence,
            instrument_ids={identity.ts_code: identity.instrument_id for identity in identities},
            sessions=root.research_sessions,
            discovery_evidence_sha256s=prior["discovery_evidence_sha256s"] if prior else (),
        )
        composed = store.compose_with_indicator_candidate(
            generation, candidate, prepared_at=prepared_at,
        )
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        operation = f"e2e-indicators:{checked_through}"
        lifecycle.protect_candidate(
            operation_id=operation,
            generation_manifest_sha256=composed.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=generation,
            candidate_generation_manifest_sha256=composed.manifest_sha256,
            operation_id=operation,
        )
        return composed.manifest_sha256
    finally:
        database.close()


if __name__ == "__main__":
    main()

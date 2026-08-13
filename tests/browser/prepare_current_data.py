from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.financial_collection import (
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialDateShard,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication.serialization import canonical_json_bytes

SESSIONS = (
    "2010-01-04",
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
)
CURRENT_SESSIONS = (
    *SESSIONS,
    "2026-08-06",
    "2026-08-07",
    "2026-08-10",
    "2026-08-11",
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

    canonical = _canonical(SESSIONS)
    store = MountedGenerationStore(settings.data_mount)
    market = store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        source_name="ticket-25-browser-fixture",
        source_lineage={"contract": "prepared-current-data-v1"},
    )
    financial = _financial_candidate(
        settings,
        market.manifest_sha256,
        observation_through_session=SESSIONS[-1],
        idempotency_key="browser-financial-fixture",
    )
    generation = store.compose_financial_candidate(
        market.manifest_sha256,
        financial.manifest_sha256,
        prepared_at=datetime(2026, 8, 11, 13, tzinfo=UTC),
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id="ticket-25-browser-head",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="ticket-25-browser-head",
        )
    finally:
        database.close()
    print(
        json.dumps(
            {
                "coverage_start": SESSIONS[0],
                "data_through_session": SESSIONS[-1],
                "generation_manifest_sha256": generation.manifest_sha256,
            },
            sort_keys=True,
        )
    )


def _canonical(sessions: tuple[str, ...]) -> dict[str, object]:
    template = build_minimal_canonical_fixture()
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "research_calendar": list(sessions),
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]}
            for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _financial_candidate(
    settings: CoreSettings,
    market_manifest: str,
    *,
    observation_through_session: str,
    idempotency_key: str,
):
    instrument_id = "equity:000001.SZ"
    ts_code = "000001.SZ"
    endpoint_rows = {
        "income": (
            ("total_revenue", "n_income_attr_p"),
            ("100000000", "10000000"),
        ),
        "balancesheet": (
            ("total_assets", "total_liab", "total_hldr_eqy_exc_min_int"),
            ("1000000000", "400000000", "600000000"),
        ),
        "cashflow": (("n_cashflow_act",), ("30000000",)),
    }
    base_fields = (
        "ts_code", "ann_date", "f_ann_date", "end_date", "report_type",
        "comp_type", "end_type",
    )
    raw = RawFinancialBatchStore(settings.data_mount)
    checkpoints: list[FinancialShardCheckpoint] = []
    endpoint_fields: list[tuple[str, tuple[str, ...]]] = []
    for ordinal, (endpoint, (value_fields, values)) in enumerate(endpoint_rows.items()):
        fields = (*base_fields, *value_fields, "update_flag")
        endpoint_fields.append((endpoint, fields))
        item = [ts_code, "20260425", "", "20251231", "1", "1", "4", *values, "0"]
        payload_sha256 = hashlib.sha256(
            canonical_json_bytes({"fields": list(fields), "items": [item]})
        ).hexdigest()
        payload = {
            "format": "thesistrace-raw-financial-batch",
            "version": 1,
            "source_contract_version": "tushare-financial-ordinary-v1",
            "endpoint": endpoint,
            "parameters": {"ts_code": ts_code},
            "returned_fields": list(fields),
            "items": [item],
            "row_count": 1,
            "source_date_extent": ["20260425", "20260425"],
            "payload_sha256": payload_sha256,
        }
        checkpoints.append(
            FinancialShardCheckpoint(
                ordinal=ordinal,
                endpoint=endpoint,
                instrument_id=instrument_id,
                ts_code=ts_code,
                shard="complete-history",
                status="completed",
                batch_sha256=raw.store(canonical_json_bytes(payload)),
                collected_at="2026-08-11T12:30:00+00:00",
                first_observed_at="2026-08-11T12:30:00+00:00",
            )
        )
    contract = FinancialCollectionContract(
        capability_sha256="e" * 64,
        endpoint_fields=tuple(endpoint_fields),
        suspected_truncation_row_counts=tuple(
            (endpoint, None) for endpoint in endpoint_rows
        ),
        shards=(FinancialDateShard("complete-history"),),
    )
    return FinancialCandidateStore(settings.data_mount).materialize(
        CompletedFinancialCollection(
            idempotency_key=idempotency_key,
            generation_manifest_sha256=market_manifest,
            contract=contract,
            finished_at="2026-08-11T12:45:00+00:00",
            target_count=len(checkpoints),
            shards=tuple(checkpoints),
        ),
        observation_through_session=observation_through_session,
    )


if __name__ == "__main__":
    main()

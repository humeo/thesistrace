from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data import MountedGenerationStore
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    FinancialCollectionContract,
    FinancialCollectionError,
    FinancialCollectionService,
    FinancialDateShard,
)
from thesistrace.data.source import RawSourceResponse
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture

COLLECTED_AT = datetime(2026, 8, 13, 5, tzinfo=UTC)
FIELDS = ("ts_code", "ann_date", "end_date", "report_type", "revenue")


class StatementSource:
    def __init__(self, *, interrupt_after: int | None = None) -> None:
        self.requests: list[tuple[str, str, str]] = []
        self.interrupt_after = interrupt_after

    def query_raw(
        self,
        endpoint: str,
        *,
        params: dict[str, object],
        fields: tuple[str, ...],
    ) -> RawSourceResponse:
        if self.interrupt_after is not None and len(self.requests) == self.interrupt_after:
            self.interrupt_after = None
            raise KeyboardInterrupt
        assert fields == FIELDS
        ts_code = str(params["ts_code"])
        shard = str(params.get("start_date", "complete-history"))
        self.requests.append((endpoint, ts_code, shard))
        return RawSourceResponse(
            FIELDS,
            (
                (ts_code, "20260425", "20260331", "1", None),
                (ts_code, "20260425", "20260331", "1", None),
            ),
        )


def test_collection_uses_historical_identities_and_reuses_raw_evidence(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = StatementSource()
        progress: list[dict[str, object]] = []
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
            progress=progress.append,
        )

        first = service.collect(
            idempotency_key="financial-bootstrap",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )
        repeated = service.collect(
            idempotency_key="financial-bootstrap",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )

        assert first == repeated
        assert first.status == "succeeded"
        assert first.target_count == first.completed_count == 6
        assert {request[1] for request in source.requests} == {"000001.SZ", "000002.SZ"}
        assert len(source.requests) == 6
        checkpoints = service.inspect("financial-bootstrap")
        assert len(checkpoints) == 6
        assert all(item.status == "completed" for item in checkpoints)
        assert len({item.batch_sha256 for item in checkpoints}) == 6
        assert checkpoints[0].batch_sha256 is not None
        batch = service.read_batch(checkpoints[0].batch_sha256)
        assert batch["returned_fields"] == list(FIELDS)
        assert batch["items"][0][-1] is None
        assert batch["items"][0] == batch["items"][1]
        assert batch["collected_at"] == COLLECTED_AT.isoformat()
        assert batch["row_count"] == 2
        assert batch["source_date_extent"] == ["20260425", "20260425"]
        assert all("token" not in repr(event).lower() for event in progress)

        replayed = service.collect(
            idempotency_key="financial-bootstrap-exact-replay",
            generation_manifest_sha256=manifest,
            contract=_contract(capability_sha256="b" * 64),
        )
        replayed_checkpoints = service.inspect("financial-bootstrap-exact-replay")
        assert replayed.status == "succeeded"
        assert len(source.requests) == 12
        assert {item.batch_sha256 for item in replayed_checkpoints} == {
            item.batch_sha256 for item in checkpoints
        }
        assert len(tuple((tmp_path / "financial" / "raw").rglob("*.json"))) == 6
        assert MountedGenerationStore(tmp_path).inspect_root(manifest).manifest_sha256 == manifest
        assert not (tmp_path / "HEAD.json").exists()
    finally:
        database.close()


def test_interrupted_collection_resumes_only_unfinished_shards(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = StatementSource(interrupt_after=2)
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(KeyboardInterrupt):
            service.collect(
                idempotency_key="resume-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
        assert len(source.requests) == 2

        outcome = service.collect(
            idempotency_key="resume-financial",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )

        assert outcome.status == "succeeded"
        assert len(source.requests) == 6
        assert len(set(source.requests)) == 6
    finally:
        database.close()


def test_collection_preserves_rows_without_a_usable_publication_date(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class MissingPublicationSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            self.requests.append((endpoint, str(params["ts_code"]), "complete-history"))
            return RawSourceResponse(
                FIELDS,
                ((str(params["ts_code"]), None, None, "1", 12),),
            )

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = MissingPublicationSource()
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        outcome = service.collect(
            idempotency_key="missing-publication-raw",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )

        assert outcome.status == "succeeded"
        checkpoint = service.inspect("missing-publication-raw")[0]
        assert checkpoint.batch_sha256 is not None
        batch = service.read_batch(checkpoint.batch_sha256)
        assert batch["items"][0][1:3] == [None, None]
        assert batch["source_date_extent"] is None
    finally:
        database.close()


def test_concurrent_duplicate_collection_accepts_each_shard_once(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = StatementSource()
        start = threading.Barrier(2)

        def collect() -> object:
            start.wait(timeout=5)
            return FinancialCollectionService(
                database,
                tmp_path,
                source,
                clock=lambda: COLLECTED_AT,
            ).collect(
                idempotency_key="concurrent-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(lambda _ordinal: collect(), range(2)))

        assert outcomes[0] == outcomes[1]
        assert len(source.requests) == 6
        assert len(set(source.requests)) == 6
        checkpoints = FinancialCollectionService(
            database,
            tmp_path,
            source,
        ).inspect("concurrent-financial")
        assert len(checkpoints) == 6
        assert all(checkpoint.status == "completed" for checkpoint in checkpoints)
    finally:
        database.close()


def test_partial_endpoint_failure_keeps_evidence_but_never_completes(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class PartialFailureSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            if endpoint == "balancesheet":
                self.requests.append((endpoint, str(params["ts_code"]), "complete-history"))
                raise TushareSourceError("UPSTREAM_RATE_LIMITED", source_code=40203)
            return super().query_raw(endpoint, params=params, fields=fields)

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = PartialFailureSource()
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCollectionError, match="UPSTREAM_RATE_LIMITED"):
            service.collect(
                idempotency_key="partial-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
        first_checkpoints = service.inspect("partial-financial")
        assert [checkpoint.status for checkpoint in first_checkpoints] == [
            "completed",
            "completed",
            "pending",
            "pending",
            "pending",
            "pending",
        ]
        accepted = [
            checkpoint.batch_sha256
            for checkpoint in first_checkpoints
            if checkpoint.batch_sha256 is not None
        ]
        assert len(accepted) == 2
        assert all(service.read_batch(batch)["endpoint"] == "income" for batch in accepted)

        with pytest.raises(FinancialCollectionError, match="UPSTREAM_RATE_LIMITED"):
            service.collect(
                idempotency_key="partial-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
        assert len(source.requests) == 3
        assert service.inspect("partial-financial") == first_checkpoints
        assert not (tmp_path / "HEAD.json").exists()
    finally:
        database.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (RawSourceResponse(("ts_code", "unexpected"), (("000001.SZ", "x"),)), "SCHEMA_DRIFT"),
        (
            RawSourceResponse(
                FIELDS,
                tuple(("000001.SZ", "20260425", "20260331", "1", 1) for _ in range(10)),
            ),
            "SUSPECTED_TRUNCATION",
        ),
        (TushareSourceError("MISSING_PERMISSION", source_code=2002), "MISSING_PERMISSION"),
        (
            RawSourceResponse(
                FIELDS,
                (("000001.SZ", "20261399", "20260331", "1", 1),),
            ),
            "MALFORMED_FIELDS",
        ),
    ],
)
def test_collection_fails_closed_with_shard_diagnostics(
    core_settings: CoreSettings,
    tmp_path: Path,
    response: RawSourceResponse | TushareSourceError,
    expected_code: str,
) -> None:
    class FailingSource:
        def query_raw(self, *args: object, **kwargs: object) -> RawSourceResponse:
            if isinstance(response, TushareSourceError):
                raise response
            return response

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        service = FinancialCollectionService(database, tmp_path, FailingSource())

        with pytest.raises(FinancialCollectionError) as failure:
            service.collect(
                idempotency_key=f"fail-{expected_code}",
                generation_manifest_sha256=manifest,
                contract=_contract(
                    suspected_truncation_row_count=(
                        10 if expected_code == "SUSPECTED_TRUNCATION" else None
                    )
                ),
            )

        assert failure.value.code == expected_code
        assert failure.value.endpoint == "income"
        assert failure.value.instrument == "000001.SZ"
        assert failure.value.shard == "complete-history"
        assert not (tmp_path / "HEAD.json").exists()
    finally:
        database.close()


def _contract(
    *,
    suspected_truncation_row_count: int | None = None,
    capability_sha256: str = "a" * 64,
) -> FinancialCollectionContract:
    return FinancialCollectionContract(
        capability_sha256=capability_sha256,
        endpoint_fields=tuple((endpoint, FIELDS) for endpoint in FINANCIAL_ENDPOINTS),
        suspected_truncation_row_counts=tuple(
            (endpoint, suspected_truncation_row_count) for endpoint in FINANCIAL_ENDPOINTS
        ),
        shards=(FinancialDateShard("complete-history"),),
    )


def _market_generation(root: Path) -> str:
    canonical = build_minimal_canonical_fixture()
    instruments = list(canonical["instruments"])
    instruments.append(
        {
            "instrument_id": "equity:000002.SZ",
            "ts_code": "000002.SZ",
            "asset_type": "ordinary_a_share",
            "exchange": "SZSE",
            "board": "main",
            "listed_from": "1991-01-29",
            "listed_to": "2020-01-01",
        }
    )
    canonical["instruments"] = instruments
    return (
        MountedGenerationStore(root)
        .materialize(
            canonical,
            prepared_at=datetime(2026, 8, 13, tzinfo=UTC),
            source_name="financial-collection-test",
            source_lineage={"fixture": "historical-identities"},
        )
        .manifest_sha256
    )


def _database(settings: CoreSettings) -> PostgresDatabase:
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    with database.transaction() as transaction:
        transaction.execute(
            "TRUNCATE data.financial_collection_shards, "
            "data.financial_raw_batches, data.financial_collection_operations"
        )
    return database

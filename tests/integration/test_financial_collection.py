from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from psycopg.errors import CheckViolation

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data import (
    FinancialCandidateError,
    FinancialCandidateStore,
    FinancialFamilyCandidate,
    FinancialRefreshError,
    FinancialRefreshOutcome,
    FinancialRefreshService,
    MountedGenerationStore,
)
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
FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "revenue",
    "update_flag",
)


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
                (ts_code, "20260425", "", "20260331", "1", "1", "1", None, "0"),
                (ts_code, "20260425", "", "20260331", "1", "1", "1", None, "0"),
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
        assert batch["items"][0][-2] is None
        assert batch["items"][0] == batch["items"][1]
        assert batch["collected_at"] == COLLECTED_AT.isoformat()
        assert batch["row_count"] == 2
        assert batch["source_date_extent"] == ["20260425", "20260425"]
        assert all("token" not in repr(event).lower() for event in progress)
        assert progress[-1] | {"duration_seconds": 0.0} == {
            "event": "financial_collection",
            "phase": "collection",
            "status": "completed",
            "idempotency_key": "financial-bootstrap",
            "target_count": 6,
            "completed_count": 6,
            "failed_count": 0,
            "resumed_count": 0,
            "duration_seconds": 0.0,
        }
        assert float(progress[-1]["duration_seconds"]) >= 0
        snapshot = service.completed_snapshot("financial-bootstrap")
        assert snapshot.idempotency_key == "financial-bootstrap"
        assert snapshot.generation_manifest_sha256 == manifest
        assert snapshot.contract == _contract()
        assert snapshot.target_count == 6
        assert (
            tuple(item.first_observed_at for item in snapshot.shards)
            == (COLLECTED_AT.isoformat(),) * 6
        )

        later_service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT + timedelta(days=1),
        )
        replayed = later_service.collect(
            idempotency_key="financial-bootstrap-exact-replay",
            generation_manifest_sha256=manifest,
            contract=_contract(capability_sha256="b" * 64),
        )
        replayed_checkpoints = service.inspect("financial-bootstrap-exact-replay")
        replayed_snapshot = later_service.completed_snapshot("financial-bootstrap-exact-replay")
        assert replayed.status == "succeeded"
        assert len(source.requests) == 12
        assert {item.batch_sha256 for item in replayed_checkpoints} == {
            item.batch_sha256 for item in checkpoints
        }
        assert (
            tuple(item.collected_at for item in replayed_snapshot.shards)
            == ((COLLECTED_AT + timedelta(days=1)).isoformat(),) * 6
        )
        assert (
            tuple(item.first_observed_at for item in replayed_snapshot.shards)
            == (COLLECTED_AT.isoformat(),) * 6
        )
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
                (
                    (
                        str(params["ts_code"]),
                        None,
                        None,
                        "20260331",
                        "1",
                        "1",
                        "1",
                        12,
                        "0",
                    ),
                ),
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


def test_refresh_rebuild_retains_absent_versions_and_reports_progress(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class ValueSource(StatementSource):
        def __init__(self, value: int) -> None:
            super().__init__()
            self.value = value

        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            ts_code = str(params["ts_code"])
            self.requests.append((endpoint, ts_code, "complete-history"))
            return RawSourceResponse(
                fields,
                (
                    (
                        ts_code,
                        "20260425",
                        "",
                        "20260331",
                        "1",
                        "1",
                        "1",
                        self.value,
                        "0",
                    ),
                ),
            )

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        first = _initial_candidate(
            database,
            tmp_path,
            ValueSource(10),
            manifest,
            idempotency_key="initial-financial-family",
        )
        progress: list[dict[str, object]] = []
        refresh_source = ValueSource(11)
        refresh_service = FinancialRefreshService(
            database,
            tmp_path,
            refresh_source,
            clock=lambda: COLLECTED_AT + timedelta(days=1),
            monotonic=lambda: 2.0,
            progress=progress.append,
        )
        refreshed = refresh_service.rebuild(
            idempotency_key="refresh-financial-family",
            generation_manifest_sha256=manifest,
            contract=_contract(capability_sha256="b" * 64),
            prior_candidate_manifest_sha256=first.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        assert refreshed.expected_shard_count == refreshed.completed_shard_count == 6
        assert refreshed.resumed_shard_count == 0
        income = FinancialCandidateStore(tmp_path).read_table(
            refreshed.candidate.manifest_sha256,
            "income_statement_versions",
        )
        assert {row["revenue"] for row in income} == {"10", "11"}
        assert (
            next(row for row in income if row["revenue"] == "11")["revision_basis"]
            == "observed_correction"
        )
        assert progress[-1]["phase"] == "candidate"
        assert progress[-1]["status"] == "completed"
        assert progress[-1]["target_count"] == progress[-1]["completed_count"] == 6
        assert progress[-1]["failed_count"] == progress[-1]["resumed_count"] == 0
        assert progress[-1]["duration_seconds"] == 0.0
        assert all("token" not in repr(event).lower() for event in progress)
        assert not (tmp_path / "HEAD.json").exists()
        assert (
            refresh_service.rebuild(
                idempotency_key="refresh-financial-family",
                generation_manifest_sha256=manifest,
                contract=_contract(capability_sha256="b" * 64),
                prior_candidate_manifest_sha256=first.manifest_sha256,
                observation_through_session="2026-08-13",
            )
            == refreshed
        )
        assert len(refresh_source.requests) == 6
        with pytest.raises(
            FinancialRefreshError,
            match="FINANCIAL_REFRESH_IDEMPOTENCY_KEY_REUSED",
        ):
            refresh_service.rebuild(
                idempotency_key="refresh-financial-family",
                generation_manifest_sha256=manifest,
                contract=_contract(capability_sha256="b" * 64),
                prior_candidate_manifest_sha256=first.manifest_sha256,
                observation_through_session="2026-08-07",
            )
    finally:
        database.close()


def test_refresh_resumes_durable_completed_shards(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="resume-prior",
        )
        source = StatementSource(interrupt_after=2)
        progress: list[dict[str, object]] = []
        service = FinancialRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
            monotonic=lambda: 3.0,
            progress=progress.append,
        )

        with pytest.raises(KeyboardInterrupt):
            service.rebuild(
                idempotency_key="resumable-financial-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )
        outcome = service.rebuild(
            idempotency_key="resumable-financial-refresh",
            generation_manifest_sha256=manifest,
            contract=_contract(),
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        assert outcome.completed_shard_count == outcome.expected_shard_count == 6
        assert outcome.resumed_shard_count == 2
        resumed = [event for event in progress if event.get("resumed_count") == 2]
        assert resumed
        assert len(source.requests) == 6
    finally:
        database.close()


def test_concurrent_duplicate_refresh_builds_one_candidate_attempt(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="concurrent-prior",
        )
        source = StatementSource()
        start = threading.Barrier(2)

        def rebuild() -> FinancialRefreshOutcome:
            start.wait(timeout=5)
            return FinancialRefreshService(
                database,
                tmp_path,
                source,
                clock=lambda: COLLECTED_AT,
            ).rebuild(
                idempotency_key="concurrent-financial-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(lambda _ordinal: rebuild(), range(2)))

        assert outcomes[0] == outcomes[1]
        assert len(source.requests) == 6
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'concurrent-financial-refresh'
                """
            ).fetchone()
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["candidate_manifest_sha256"] == outcomes[0].candidate.manifest_sha256
    finally:
        database.close()


def test_checkpoint_conflict_marks_collection_and_refresh_failed(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="checkpoint-conflict-prior",
        )

        class DeleteClaimedShardSource(StatementSource):
            def query_raw(
                self,
                endpoint: str,
                *,
                params: dict[str, object],
                fields: tuple[str, ...],
            ) -> RawSourceResponse:
                with database.transaction() as transaction:
                    transaction.execute(
                        """
                        DELETE FROM data.financial_collection_shards
                        WHERE idempotency_key = 'checkpoint-conflict-refresh'
                          AND ordinal = 0
                        """
                    )
                return super().query_raw(endpoint, params=params, fields=fields)

        progress: list[dict[str, object]] = []
        service = FinancialRefreshService(
            database,
            tmp_path,
            DeleteClaimedShardSource(),
            clock=lambda: COLLECTED_AT,
            progress=progress.append,
        )

        with pytest.raises(FinancialCollectionError, match="SHARD_CHECKPOINT_CONFLICT"):
            service.rebuild(
                idempotency_key="checkpoint-conflict-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            collection = transaction.execute(
                """
                SELECT status, failure_code
                FROM data.financial_collection_operations
                WHERE idempotency_key = 'checkpoint-conflict-refresh'
                """
            ).fetchone()
            refresh = transaction.execute(
                """
                SELECT status, failure_code, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'checkpoint-conflict-refresh'
                """
            ).fetchone()
        assert collection is not None and refresh is not None
        assert collection["status"] == refresh["status"] == "failed"
        assert (
            collection["failure_code"] == refresh["failure_code"] == ("SHARD_CHECKPOINT_CONFLICT")
        )
        assert refresh["candidate_manifest_sha256"] is None
        failed = [event for event in progress if event.get("status") == "failed"]
        assert failed[-1]["failed_count"] == 1
    finally:
        database.close()


def test_invalid_market_generation_marks_refresh_failed(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="invalid-market-prior",
        )
        source = StatementSource()
        progress: list[dict[str, object]] = []
        service = FinancialRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
            progress=progress.append,
        )

        with pytest.raises(FinancialRefreshError, match="FINANCIAL_MARKET_GENERATION_INVALID"):
            service.rebuild(
                idempotency_key="invalid-market-refresh",
                generation_manifest_sha256="f" * 64,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            refresh = transaction.execute(
                """
                SELECT status, failure_code, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'invalid-market-refresh'
                """
            ).fetchone()
        assert refresh is not None
        assert refresh["status"] == "failed"
        assert refresh["failure_code"] == "FINANCIAL_MARKET_GENERATION_INVALID"
        assert refresh["candidate_manifest_sha256"] is None
        assert source.requests == []
        assert progress[-1]["phase"] == "collection"
        assert progress[-1]["status"] == "failed"
    finally:
        database.close()


def test_invalid_prior_fails_before_any_source_request(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="missing-prior-raw-evidence",
        )
        manifest_path = (
            tmp_path
            / "manifests"
            / "sha256"
            / prior.manifest_sha256[:2]
            / f"{prior.manifest_sha256}.json"
        )
        family = json.loads(manifest_path.read_bytes())
        evidence_sha256 = str(family["raw_evidence"]["manifest_sha256"])
        evidence_path = (
            tmp_path / "manifests" / "sha256" / evidence_sha256[:2] / f"{evidence_sha256}.json"
        )
        evidence = json.loads(evidence_path.read_bytes())
        chunk_sha256 = str(evidence["chunks"][0]["sha256"])
        chunk_path = tmp_path / "manifests" / "sha256" / chunk_sha256[:2] / f"{chunk_sha256}.json"
        chunk = json.loads(chunk_path.read_bytes())
        batch_sha256 = str(chunk["entries"][0]["batch_sha256"])
        (
            tmp_path / "financial" / "raw" / "sha256" / batch_sha256[:2] / f"{batch_sha256}.json"
        ).unlink()
        source = StatementSource()
        service = FinancialRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCandidateError, match="FINANCIAL_RAW_BATCH_INVALID"):
            service.rebuild(
                idempotency_key="missing-prior-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            refresh = transaction.execute(
                """
                SELECT status, failure_code
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'missing-prior-refresh'
                """
            ).fetchone()
        assert refresh is not None
        assert refresh["status"] == "failed"
        assert refresh["failure_code"] == "FINANCIAL_RAW_BATCH_INVALID"
        assert source.requests == []
    finally:
        database.close()


def test_raw_batch_write_failure_marks_collection_and_refresh_failed(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="raw-write-prior",
        )
        raw_root = tmp_path / "financial" / "raw"
        preserved_raw = tmp_path / "financial" / "preserved-raw"

        class BlockRawWriteSource(StatementSource):
            def query_raw(
                self,
                endpoint: str,
                *,
                params: dict[str, object],
                fields: tuple[str, ...],
            ) -> RawSourceResponse:
                response = super().query_raw(endpoint, params=params, fields=fields)
                if not preserved_raw.exists():
                    raw_root.rename(preserved_raw)
                    raw_root.write_text("not-a-directory")
                return response

        service = FinancialRefreshService(
            database,
            tmp_path,
            BlockRawWriteSource(),
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCollectionError, match="RAW_BATCH_WRITE_FAILED"):
            service.rebuild(
                idempotency_key="raw-write-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            collection = transaction.execute(
                """
                SELECT status, failure_code
                FROM data.financial_collection_operations
                WHERE idempotency_key = 'raw-write-refresh'
                """
            ).fetchone()
            refresh = transaction.execute(
                """
                SELECT status, failure_code, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'raw-write-refresh'
                """
            ).fetchone()
        assert collection is not None and refresh is not None
        assert collection["status"] == refresh["status"] == "failed"
        assert collection["failure_code"] == refresh["failure_code"] == ("RAW_BATCH_WRITE_FAILED")
        assert refresh["candidate_manifest_sha256"] is None
    finally:
        database.close()


def test_refresh_failure_progress_preserves_durable_collection_counts(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="partial-failure-prior",
        )

        class FailAfterThreeSource(StatementSource):
            def query_raw(
                self,
                endpoint: str,
                *,
                params: dict[str, object],
                fields: tuple[str, ...],
            ) -> RawSourceResponse:
                if len(self.requests) == 3:
                    raise TushareSourceError("UPSTREAM_RATE_LIMITED", source_code=40203)
                return super().query_raw(endpoint, params=params, fields=fields)

        progress: list[dict[str, object]] = []
        service = FinancialRefreshService(
            database,
            tmp_path,
            FailAfterThreeSource(),
            clock=lambda: COLLECTED_AT,
            progress=progress.append,
        )

        with pytest.raises(FinancialCollectionError, match="UPSTREAM_RATE_LIMITED"):
            service.rebuild(
                idempotency_key="partial-failure-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        refresh_failure = [
            event
            for event in progress
            if event.get("event") == "financial_refresh" and event.get("status") == "failed"
        ][-1]
        assert refresh_failure["target_count"] == 6
        assert refresh_failure["completed_count"] == 3
        assert refresh_failure["failed_count"] == 1
        assert refresh_failure["resumed_count"] == 0
    finally:
        database.close()


def test_refresh_succeeded_state_requires_explicit_counts(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    try:
        with pytest.raises(CheckViolation), database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO data.financial_refresh_operations (
                    idempotency_key, fingerprint, generation_manifest_sha256,
                    prior_candidate_manifest_sha256, observation_through_session,
                    status, candidate_manifest_sha256, finished_at
                ) VALUES (%s, %s, %s, %s, %s, 'succeeded', %s, %s)
                """,
                (
                    "missing-success-counts",
                    "a" * 64,
                    "b" * 64,
                    "c" * 64,
                    "2026-08-13",
                    "d" * 64,
                    COLLECTED_AT,
                ),
            )
    finally:
        database.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (RawSourceResponse(("ts_code", "unexpected"), (("000001.SZ", "x"),)), "SCHEMA_DRIFT"),
        (
            RawSourceResponse(
                FIELDS,
                tuple(
                    (
                        "000001.SZ",
                        "20260425",
                        "",
                        "20260331",
                        "1",
                        "1",
                        "1",
                        1,
                        "0",
                    )
                    for _ in range(10)
                ),
            ),
            "SUSPECTED_TRUNCATION",
        ),
        (TushareSourceError("MISSING_PERMISSION", source_code=2002), "MISSING_PERMISSION"),
        (
            RawSourceResponse(
                FIELDS,
                (
                    (
                        "000001.SZ",
                        "20261399",
                        "",
                        "20260331",
                        "1",
                        "1",
                        "1",
                        1,
                        "0",
                    ),
                ),
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


def _initial_candidate(
    database: PostgresDatabase,
    root: Path,
    source: StatementSource,
    generation_manifest_sha256: str,
    *,
    idempotency_key: str,
) -> FinancialFamilyCandidate:
    collection = FinancialCollectionService(
        database,
        root,
        source,
        clock=lambda: COLLECTED_AT,
    )
    collection.collect(
        idempotency_key=idempotency_key,
        generation_manifest_sha256=generation_manifest_sha256,
        contract=_contract(),
    )
    return FinancialCandidateStore(root).materialize(
        collection.completed_snapshot(idempotency_key),
        observation_through_session="2026-08-13",
    )


def _market_generation(root: Path) -> str:
    canonical = build_minimal_canonical_fixture()
    sessions = ("2010-01-04", "2026-08-07", "2026-08-13")
    price = dict(canonical["prices"][0])
    state = dict(canonical["trading_states"][0])
    limits = dict(canonical["price_limits"][0])
    pool = dict(canonical["base_pool"][0])
    universes = {name: dict(rows[0]) for name, rows in canonical["liquidity_universes"].items()}
    canonical["research_calendar"] = list(sessions)
    canonical["prices"] = [dict(price, session=session) for session in sessions]
    canonical["trading_states"] = [dict(state, session=session) for session in sessions]
    canonical["price_limits"] = [dict(limits, session=session) for session in sessions]
    canonical["base_pool"] = [dict(pool, session=session) for session in sessions]
    canonical["liquidity_universes"] = {
        name: [dict(row, session=session) for session in sessions]
        for name, row in universes.items()
    }
    catalog = dict(canonical["field_catalog"][0])
    catalog["release_available_from"] = sessions[0]
    canonical["field_catalog"] = [catalog]
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
            "TRUNCATE data.financial_refresh_operations, "
            "data.financial_collection_shards, "
            "data.financial_raw_batches, data.financial_collection_operations"
        )
    return database

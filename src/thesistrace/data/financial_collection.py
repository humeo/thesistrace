from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.generation_store import HistoricalInstrumentIdentity, MountedGenerationStore
from thesistrace.data.lifecycle import mounted_data_mutation_lock
from thesistrace.data.source import RawSourceError, RawSourceResponse
from thesistrace.publication.serialization import canonical_json_bytes

FINANCIAL_ENDPOINTS = ("income", "balancesheet", "cashflow")
FINANCIAL_SOURCE_CONTRACT_VERSION = "tushare-financial-ordinary-v1"
FINANCIAL_HISTORY_FLOOR = "19900101"
_REQUIRED_FINANCIAL_FIELDS = {
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "update_flag",
}


class FinancialRawSource(Protocol):
    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse: ...


@dataclass(frozen=True)
class FinancialDateShard:
    name: str
    start_date: str | None = None
    end_date: str | None = None

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("financial shard name is invalid")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("financial date shard requires both boundaries")
        if self.start_date is not None:
            try:
                start = datetime.strptime(self.start_date, "%Y%m%d").date()
                end = datetime.strptime(str(self.end_date), "%Y%m%d").date()
            except ValueError as error:
                raise ValueError("financial date shard boundaries are invalid") from error
            if start > end:
                raise ValueError("financial date shard boundaries are invalid")

    def parameters(self) -> dict[str, str]:
        if self.start_date is None:
            return {}
        assert self.end_date is not None
        return {"start_date": self.start_date, "end_date": self.end_date}


@dataclass(frozen=True)
class FinancialEndpointCapability:
    endpoint: str
    permission: str
    failure_code: str | None
    returned_fields: tuple[str, ...]
    null_value_count: int
    duplicate_row_count: int
    full_history_row_count: int
    source_date_extent: tuple[str, str] | None
    observed_response_row_counts: tuple[int, ...]
    suspected_truncation_row_count: int | None
    observed_rate_limit_events: int
    observed_rate_limit_retry_seconds: tuple[float, ...]
    full_history_proven: bool

    def descriptor(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "permission": self.permission,
            "failure_code": self.failure_code,
            "returned_fields": list(self.returned_fields),
            "null_value_count": self.null_value_count,
            "duplicate_row_count": self.duplicate_row_count,
            "full_history_row_count": self.full_history_row_count,
            "source_date_extent": (
                None if self.source_date_extent is None else list(self.source_date_extent)
            ),
            "observed_response_row_counts": list(self.observed_response_row_counts),
            "suspected_truncation_row_count": self.suspected_truncation_row_count,
            "observed_rate_limit_events": self.observed_rate_limit_events,
            "observed_rate_limit_retry_seconds": list(self.observed_rate_limit_retry_seconds),
            "full_history_proven": self.full_history_proven,
        }


@dataclass(frozen=True)
class FinancialCapabilityReport:
    format: str
    version: int
    probed_at: str
    reference_instrument: str
    comparison_shards: tuple[FinancialDateShard, ...]
    endpoints: tuple[FinancialEndpointCapability, ...]

    @classmethod
    def from_descriptor(cls, value: object) -> FinancialCapabilityReport:
        try:
            if not isinstance(value, Mapping) or set(value) != {
                "format",
                "version",
                "probed_at",
                "reference_instrument",
                "comparison_shards",
                "endpoints",
            }:
                raise ValueError
            if value["format"] != "thesistrace-financial-capability" or value["version"] != 1:
                raise ValueError
            comparison = value["comparison_shards"]
            endpoint_values = value["endpoints"]
            if not isinstance(comparison, list) or not isinstance(endpoint_values, list):
                raise ValueError
            shards = tuple(
                FinancialDateShard(
                    name=str(item["name"]),
                    start_date=None if item["start_date"] is None else str(item["start_date"]),
                    end_date=None if item["end_date"] is None else str(item["end_date"]),
                )
                for item in comparison
                if isinstance(item, Mapping) and set(item) == {"name", "start_date", "end_date"}
            )
            if len(shards) != len(comparison):
                raise ValueError
            endpoints: list[FinancialEndpointCapability] = []
            expected_endpoint_fields = {
                "endpoint",
                "permission",
                "failure_code",
                "returned_fields",
                "null_value_count",
                "duplicate_row_count",
                "full_history_row_count",
                "source_date_extent",
                "observed_response_row_counts",
                "suspected_truncation_row_count",
                "observed_rate_limit_events",
                "observed_rate_limit_retry_seconds",
                "full_history_proven",
            }
            for item in endpoint_values:
                if not isinstance(item, Mapping) or set(item) != expected_endpoint_fields:
                    raise ValueError
                returned_fields = item["returned_fields"]
                extent = item["source_date_extent"]
                if not isinstance(returned_fields, list) or any(
                    not isinstance(field, str) for field in returned_fields
                ):
                    raise ValueError
                if extent is not None and (
                    not isinstance(extent, list)
                    or len(extent) != 2
                    or any(not isinstance(part, str) for part in extent)
                ):
                    raise ValueError
                retry_seconds = item["observed_rate_limit_retry_seconds"]
                if not isinstance(retry_seconds, list) or any(
                    not isinstance(seconds, (int, float)) or seconds < 0
                    for seconds in retry_seconds
                ):
                    raise ValueError
                response_counts = item["observed_response_row_counts"]
                suspected_count = item["suspected_truncation_row_count"]
                if not isinstance(response_counts, list) or any(
                    not isinstance(count, int) or count < 0 for count in response_counts
                ):
                    raise ValueError
                if suspected_count is not None and (
                    not isinstance(suspected_count, int) or suspected_count <= 0
                ):
                    raise ValueError
                endpoints.append(
                    FinancialEndpointCapability(
                        endpoint=str(item["endpoint"]),
                        permission=str(item["permission"]),
                        failure_code=(
                            None if item["failure_code"] is None else str(item["failure_code"])
                        ),
                        returned_fields=tuple(returned_fields),
                        null_value_count=int(item["null_value_count"]),
                        duplicate_row_count=int(item["duplicate_row_count"]),
                        full_history_row_count=int(item["full_history_row_count"]),
                        source_date_extent=None if extent is None else (extent[0], extent[1]),
                        observed_response_row_counts=tuple(response_counts),
                        suspected_truncation_row_count=suspected_count,
                        observed_rate_limit_events=int(item["observed_rate_limit_events"]),
                        observed_rate_limit_retry_seconds=tuple(
                            float(seconds) for seconds in retry_seconds
                        ),
                        full_history_proven=item["full_history_proven"] is True,
                    )
                )
            report = cls(
                format=str(value["format"]),
                version=int(value["version"]),
                probed_at=str(value["probed_at"]),
                reference_instrument=str(value["reference_instrument"]),
                comparison_shards=shards,
                endpoints=tuple(endpoints),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("financial capability report is invalid") from error
        if tuple(endpoint.endpoint for endpoint in report.endpoints) != FINANCIAL_ENDPOINTS or any(
            endpoint.permission not in {"available", "unavailable"}
            or (
                endpoint.failure_code is None
                and (endpoint.permission != "available" or not endpoint.returned_fields)
            )
            or (endpoint.failure_code is not None and bool(endpoint.returned_fields))
            for endpoint in report.endpoints
        ):
            raise ValueError("financial capability report is invalid")
        return report

    def descriptor(self) -> dict[str, object]:
        return {
            "format": self.format,
            "version": self.version,
            "probed_at": self.probed_at,
            "reference_instrument": self.reference_instrument,
            "comparison_shards": [
                {
                    "name": shard.name,
                    "start_date": shard.start_date,
                    "end_date": shard.end_date,
                }
                for shard in self.comparison_shards
            ],
            "endpoints": [endpoint.descriptor() for endpoint in self.endpoints],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.descriptor())).hexdigest()


@dataclass(frozen=True)
class FinancialCollectionContract:
    capability_sha256: str
    endpoint_fields: tuple[tuple[str, tuple[str, ...]], ...]
    suspected_truncation_row_counts: tuple[tuple[str, int | None], ...]
    shards: tuple[FinancialDateShard, ...]

    def descriptor(self) -> dict[str, object]:
        return {
            "capability_sha256": self.capability_sha256,
            "endpoint_fields": [
                [endpoint, list(fields)] for endpoint, fields in self.endpoint_fields
            ],
            "suspected_truncation_row_counts": [
                [endpoint, count] for endpoint, count in self.suspected_truncation_row_counts
            ],
            "shards": [
                {
                    "name": shard.name,
                    "start_date": shard.start_date,
                    "end_date": shard.end_date,
                }
                for shard in self.shards
            ],
        }

    @classmethod
    def from_descriptor(cls, value: object) -> FinancialCollectionContract:
        if not isinstance(value, Mapping) or set(value) != {
            "capability_sha256",
            "endpoint_fields",
            "suspected_truncation_row_counts",
            "shards",
        }:
            raise ValueError("financial collection contract is invalid")
        try:
            endpoint_fields = tuple(
                (str(item[0]), tuple(str(field) for field in item[1]))
                for item in value["endpoint_fields"]
            )
            truncation = tuple(
                (str(item[0]), None if item[1] is None else int(item[1]))
                for item in value["suspected_truncation_row_counts"]
            )
            shards = tuple(
                FinancialDateShard(
                    name=str(item["name"]),
                    start_date=item["start_date"],
                    end_date=item["end_date"],
                )
                for item in value["shards"]
            )
            contract = cls(
                capability_sha256=str(value["capability_sha256"]),
                endpoint_fields=endpoint_fields,
                suspected_truncation_row_counts=truncation,
                shards=shards,
            )
            _validate_collection_contract(contract)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("financial collection contract is invalid") from error
        if contract.descriptor() != value:
            raise ValueError("financial collection contract is invalid")
        return contract

    @classmethod
    def from_capability(
        cls,
        report: FinancialCapabilityReport,
        *,
        date_shards: tuple[FinancialDateShard, ...] | None = None,
    ) -> FinancialCollectionContract:
        try:
            probed_at = datetime.fromisoformat(report.probed_at)
        except ValueError as error:
            raise ValueError("financial capability probe time is invalid") from error
        _validate_probe_shards(report.comparison_shards, through=probed_at)
        if tuple(endpoint.endpoint for endpoint in report.endpoints) != FINANCIAL_ENDPOINTS:
            raise ValueError("financial capability endpoint set is invalid")
        if any(
            endpoint.permission != "available" or endpoint.failure_code is not None
            for endpoint in report.endpoints
        ):
            raise ValueError("financial endpoint permission is unavailable")
        if date_shards is None:
            if not all(endpoint.full_history_proven for endpoint in report.endpoints):
                raise ValueError("complete-history response is unproven")
            shards = (FinancialDateShard("complete-history"),)
        else:
            if date_shards != report.comparison_shards:
                raise ValueError("preselected financial date shards are invalid")
            shards = date_shards
        return cls(
            capability_sha256=report.sha256,
            endpoint_fields=tuple(
                (endpoint.endpoint, endpoint.returned_fields) for endpoint in report.endpoints
            ),
            suspected_truncation_row_counts=tuple(
                (endpoint.endpoint, endpoint.suspected_truncation_row_count)
                for endpoint in report.endpoints
            ),
            shards=shards,
        )


class FinancialCollectionError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        endpoint: str | None = None,
        instrument: str | None = None,
        shard: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.endpoint = endpoint
        self.instrument = instrument
        self.shard = shard

    def diagnostic(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "endpoint": self.endpoint,
                "instrument": self.instrument,
                "shard": self.shard,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class FinancialCollectionOutcome:
    idempotency_key: str
    status: str
    target_count: int
    completed_count: int


@dataclass(frozen=True)
class FinancialShardCheckpoint:
    ordinal: int
    endpoint: str
    instrument_id: str
    ts_code: str
    shard: str
    status: str
    batch_sha256: str | None
    collected_at: str | None
    first_observed_at: str | None = None


@dataclass(frozen=True)
class CompletedFinancialCollection:
    idempotency_key: str
    generation_manifest_sha256: str
    contract: FinancialCollectionContract
    finished_at: str
    target_count: int
    shards: tuple[FinancialShardCheckpoint, ...]


class RawFinancialBatchStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._files = AddressedFileStore(self._root)

    def store(self, content: bytes) -> str:
        sha256 = hashlib.sha256(content).hexdigest()
        try:
            self._files.store(self._path(sha256), sha256, content)
        except AddressedFileError as error:
            raise FinancialCollectionError("RAW_BATCH_WRITE_FAILED") from error
        return sha256

    def read(self, sha256: str, *, byte_count: int | None = None) -> dict[str, object]:
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise FinancialCollectionError("INVALID_RAW_BATCH_REFERENCE")
        try:
            content = self._files.read(
                self._path(sha256),
                sha256,
                expected_byte_count=byte_count,
                max_byte_count=256 * 1024 * 1024,
            )
        except AddressedFileError as error:
            raise FinancialCollectionError("RAW_BATCH_READ_FAILED") from error
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FinancialCollectionError("INVALID_RAW_BATCH") from error
        if not isinstance(value, dict):
            raise FinancialCollectionError("INVALID_RAW_BATCH")
        return value

    def _path(self, sha256: str) -> Path:
        return self._root / "financial" / "raw" / "sha256" / sha256[:2] / f"{sha256}.json"


class FinancialCollectionService:
    def __init__(
        self,
        database: PostgresDatabase,
        mount_root: Path | str,
        source: FinancialRawSource,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._database = database
        self._generation_store = MountedGenerationStore(mount_root)
        self._batches = RawFinancialBatchStore(mount_root)
        self._source = source
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._progress = progress or (lambda _event: None)

    def collect(
        self,
        *,
        idempotency_key: str,
        generation_manifest_sha256: str,
        contract: FinancialCollectionContract,
    ) -> FinancialCollectionOutcome:
        _validate_collection_request(idempotency_key, generation_manifest_sha256, contract)
        collection_started = self._monotonic()
        lock_name = f"financial-collection:{idempotency_key}"
        with mounted_data_mutation_lock(self._database):
            identities = self._generation_store.read_historical_ordinary_a_share_identities(
                generation_manifest_sha256
            )
            fingerprint = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "generation_manifest_sha256": generation_manifest_sha256,
                        "contract": contract.descriptor(),
                        "instruments": [identity.__dict__ for identity in identities],
                    }
                )
            ).hexdigest()
            self._initialize_operation(
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                generation_manifest_sha256=generation_manifest_sha256,
                contract=contract,
                identities=identities,
                allow_create=True,
            )
        with self._database.session_advisory_lock(lock_name):
            existing = self._initialize_operation(
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                generation_manifest_sha256=generation_manifest_sha256,
                contract=contract,
                identities=identities,
                allow_create=False,
            )
            if existing.status == "succeeded":
                return existing
            if existing.status == "failed":
                raise self._stored_failure(idempotency_key)
            self._progress(
                {
                    "event": "financial_collection",
                    "phase": "claimed",
                    "status": "completed",
                    "idempotency_key": idempotency_key,
                    "target_count": existing.target_count,
                    "completed_count": existing.completed_count,
                    "failed_count": 0,
                    "resumed_count": existing.completed_count,
                    "duration_seconds": _duration(collection_started, self._monotonic()),
                }
            )
            while checkpoint := self._next_pending(idempotency_key):
                fields = dict(contract.endpoint_fields)[checkpoint.endpoint]
                parameters = {
                    "ts_code": checkpoint.ts_code,
                    **_shard_by_name(contract, checkpoint.shard).parameters(),
                }
                request_started = self._monotonic()
                self._progress(
                    {
                        "event": "financial_collection",
                        "phase": "source_request",
                        "status": "started",
                        "endpoint": checkpoint.endpoint,
                        "instrument": checkpoint.ts_code,
                        "shard": checkpoint.shard,
                    }
                )
                try:
                    response = self._source.query_raw(
                        checkpoint.endpoint,
                        params=parameters,
                        fields=fields,
                    )
                except RawSourceError as error:
                    failure = FinancialCollectionError(
                        _source_failure_code(error),
                        endpoint=checkpoint.endpoint,
                        instrument=checkpoint.ts_code,
                        shard=checkpoint.shard,
                    )
                    self._mark_failed(idempotency_key, failure)
                    self._failed_progress(
                        checkpoint,
                        existing.target_count,
                        existing.completed_count,
                        request_started,
                        failure.code,
                    )
                    raise failure from error
                except Exception as error:
                    failure = FinancialCollectionError(
                        "SOURCE_FAILURE",
                        endpoint=checkpoint.endpoint,
                        instrument=checkpoint.ts_code,
                        shard=checkpoint.shard,
                    )
                    self._mark_failed(idempotency_key, failure)
                    self._failed_progress(
                        checkpoint,
                        existing.target_count,
                        existing.completed_count,
                        request_started,
                        failure.code,
                    )
                    raise failure from error
                try:
                    batch_content, payload_sha256, extent = _raw_batch_content(
                        checkpoint=checkpoint,
                        parameters=parameters,
                        expected_fields=fields,
                        response=response,
                        suspected_truncation_row_count=dict(
                            contract.suspected_truncation_row_counts
                        )[checkpoint.endpoint],
                    )
                    collected_at = self._clock()
                    if collected_at.tzinfo is None:
                        raise FinancialCollectionError("COLLECTION_TIME_INVALID")
                    batch_sha256 = self._batches.store(batch_content)
                    completed_count = self._complete_shard(
                        idempotency_key=idempotency_key,
                        checkpoint=checkpoint,
                        batch_sha256=batch_sha256,
                        payload_sha256=payload_sha256,
                        parameters=parameters,
                        response=response,
                        extent=extent,
                        byte_count=len(batch_content),
                        collected_at=collected_at,
                    )
                except FinancialCollectionError as error:
                    failure = FinancialCollectionError(
                        error.code,
                        endpoint=checkpoint.endpoint,
                        instrument=checkpoint.ts_code,
                        shard=checkpoint.shard,
                    )
                    self._mark_failed(idempotency_key, failure)
                    self._failed_progress(
                        checkpoint,
                        existing.target_count,
                        existing.completed_count,
                        request_started,
                        failure.code,
                    )
                    raise failure from error
                self._progress(
                    {
                        "event": "financial_collection",
                        "phase": "source_request",
                        "status": "completed",
                        "endpoint": checkpoint.endpoint,
                        "instrument": checkpoint.ts_code,
                        "shard": checkpoint.shard,
                        "batch_sha256": batch_sha256,
                        "target_count": existing.target_count,
                        "completed_count": completed_count,
                        "failed_count": 0,
                        "resumed_count": existing.completed_count,
                        "duration_seconds": _duration(request_started, self._monotonic()),
                    }
                )
            outcome = self._finish(idempotency_key)
            self._progress(
                {
                    "event": "financial_collection",
                    "phase": "collection",
                    "status": "completed",
                    "idempotency_key": idempotency_key,
                    "target_count": outcome.target_count,
                    "completed_count": outcome.completed_count,
                    "failed_count": 0,
                    "resumed_count": existing.completed_count,
                    "duration_seconds": _duration(collection_started, self._monotonic()),
                }
            )
            return outcome

    def inspect(self, idempotency_key: str) -> tuple[FinancialShardCheckpoint, ...]:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT ordinal, endpoint, instrument_id, ts_code, shard_name,
                       status, batch_sha256, collected_at
                FROM data.financial_collection_shards
                WHERE idempotency_key = %s
                ORDER BY ordinal
                """,
                (idempotency_key,),
            ).fetchall()
        return tuple(_checkpoint(row) for row in rows)

    def release(self, idempotency_key: str) -> None:
        with mounted_data_mutation_lock(self._database):
            with self._database.transaction() as transaction:
                row = transaction.execute(
                    """
                SELECT status FROM data.financial_collection_operations
                WHERE idempotency_key = %s FOR UPDATE
                """,
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    raise FinancialCollectionError("COLLECTION_NOT_FOUND")
                if row["status"] != "succeeded":
                    raise FinancialCollectionError("COLLECTION_NOT_RELEASABLE")
                transaction.execute(
                    """
                    UPDATE data.financial_collection_operations
                    SET retention_released_at = COALESCE(retention_released_at, now()),
                        updated_at = now()
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )

    def inspect_outcome(self, idempotency_key: str) -> FinancialCollectionOutcome | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, target_count, completed_count
                FROM data.financial_collection_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return FinancialCollectionOutcome(
            idempotency_key=idempotency_key,
            status=str(row["status"]),
            target_count=int(row["target_count"]),
            completed_count=int(row["completed_count"]),
        )

    def read_batch(self, batch_sha256: str) -> dict[str, object]:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT byte_count, first_collected_at
                FROM data.financial_raw_batches WHERE batch_sha256 = %s
                """,
                (batch_sha256,),
            ).fetchone()
        if row is None:
            raise FinancialCollectionError("RAW_BATCH_NOT_FOUND")
        batch = self._batches.read(batch_sha256, byte_count=int(row["byte_count"]))
        batch["collected_at"] = row["first_collected_at"].isoformat()
        return batch

    def completed_snapshot(self, idempotency_key: str) -> CompletedFinancialCollection:
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT generation_manifest_sha256, capability_sha256, status,
                       contract_descriptor, target_count, completed_count, finished_at
                FROM data.financial_collection_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            rows = transaction.execute(
                """
                SELECT shard.ordinal, shard.endpoint, shard.instrument_id, shard.ts_code,
                       shard.shard_name, shard.status, shard.batch_sha256,
                       shard.collected_at, batch.first_collected_at AS first_observed_at
                FROM data.financial_collection_shards AS shard
                LEFT JOIN data.financial_raw_batches AS batch
                  ON batch.batch_sha256 = shard.batch_sha256
                WHERE shard.idempotency_key = %s
                ORDER BY shard.ordinal
                """,
                (idempotency_key,),
            ).fetchall()
        if operation is None:
            raise FinancialCollectionError("COLLECTION_NOT_FOUND")
        target_count = int(operation["target_count"])
        shards = tuple(_checkpoint(row) for row in rows)
        try:
            contract = FinancialCollectionContract.from_descriptor(operation["contract_descriptor"])
        except ValueError as error:
            raise FinancialCollectionError("COLLECTION_CONTRACT_INVALID") from error
        if (
            operation["status"] != "succeeded"
            or operation["finished_at"] is None
            or int(operation["completed_count"]) != target_count
            or len(shards) != target_count
            or tuple(item.ordinal for item in shards) != tuple(range(target_count))
            or any(
                item.status != "completed"
                or item.batch_sha256 is None
                or item.collected_at is None
                or item.first_observed_at is None
                for item in shards
            )
        ):
            raise FinancialCollectionError("COLLECTION_INCOMPLETE")
        return CompletedFinancialCollection(
            idempotency_key=idempotency_key,
            generation_manifest_sha256=str(operation["generation_manifest_sha256"]),
            contract=contract,
            finished_at=operation["finished_at"].isoformat(),
            target_count=target_count,
            shards=shards,
        )

    def _initialize_operation(
        self,
        *,
        idempotency_key: str,
        fingerprint: str,
        generation_manifest_sha256: str,
        contract: FinancialCollectionContract,
        identities: Sequence[HistoricalInstrumentIdentity],
        allow_create: bool,
    ) -> FinancialCollectionOutcome:
        target_count = len(FINANCIAL_ENDPOINTS) * len(identities) * len(contract.shards)
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT fingerprint, status, target_count, completed_count
                FROM data.financial_collection_operations
                WHERE idempotency_key = %s FOR UPDATE
                """,
                (idempotency_key,),
            ).fetchone()
            if row is None:
                if not allow_create:
                    raise RuntimeError("Financial collection claim disappeared")
                transaction.execute(
                    """
                    INSERT INTO data.financial_collection_operations (
                        idempotency_key, fingerprint, generation_manifest_sha256,
                        capability_sha256, contract_descriptor, status, target_count
                    ) VALUES (%s, %s, %s, %s, %s, 'running', %s)
                    """,
                    (
                        idempotency_key,
                        fingerprint,
                        generation_manifest_sha256,
                        contract.capability_sha256,
                        Jsonb(contract.descriptor()),
                        target_count,
                    ),
                )
                targets: list[tuple[object, ...]] = []
                ordinal = 0
                for endpoint, _fields in contract.endpoint_fields:
                    for identity in identities:
                        for shard in contract.shards:
                            targets.append(
                                (
                                    idempotency_key,
                                    ordinal,
                                    endpoint,
                                    identity.instrument_id,
                                    identity.ts_code,
                                    shard.name,
                                    Jsonb({"ts_code": identity.ts_code, **shard.parameters()}),
                                )
                            )
                            ordinal += 1
                with transaction.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO data.financial_collection_shards (
                            idempotency_key, ordinal, endpoint, instrument_id,
                            ts_code, shard_name, parameters, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                        """,
                        targets,
                    )
                return FinancialCollectionOutcome(idempotency_key, "running", target_count, 0)
            if row["fingerprint"] != fingerprint or int(row["target_count"]) != target_count:
                raise FinancialCollectionError("IDEMPOTENCY_KEY_REUSED")
            return FinancialCollectionOutcome(
                idempotency_key,
                str(row["status"]),
                int(row["target_count"]),
                int(row["completed_count"]),
            )

    def _next_pending(self, idempotency_key: str) -> FinancialShardCheckpoint | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT ordinal, endpoint, instrument_id, ts_code, shard_name,
                       status, batch_sha256, collected_at
                FROM data.financial_collection_shards
                WHERE idempotency_key = %s AND status = 'pending'
                ORDER BY ordinal LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
        return None if row is None else _checkpoint(row)

    def _complete_shard(
        self,
        *,
        idempotency_key: str,
        checkpoint: FinancialShardCheckpoint,
        batch_sha256: str,
        payload_sha256: str,
        parameters: Mapping[str, object],
        response: RawSourceResponse,
        extent: tuple[str, str] | None,
        byte_count: int,
        collected_at: datetime,
    ) -> int:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO data.financial_raw_batches (
                    batch_sha256, payload_sha256, endpoint, parameters,
                    returned_fields, row_count, source_date_start,
                    source_date_end, byte_count, first_collected_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (batch_sha256) DO NOTHING
                """,
                (
                    batch_sha256,
                    payload_sha256,
                    checkpoint.endpoint,
                    Jsonb(dict(parameters)),
                    Jsonb(list(response.fields)),
                    len(response.items),
                    None if extent is None else extent[0],
                    None if extent is None else extent[1],
                    byte_count,
                    collected_at,
                ),
            )
            changed = transaction.execute(
                """
                UPDATE data.financial_collection_shards
                SET status = 'completed', batch_sha256 = %s, collected_at = %s
                WHERE idempotency_key = %s AND ordinal = %s AND status = 'pending'
                """,
                (batch_sha256, collected_at, idempotency_key, checkpoint.ordinal),
            ).rowcount
            if changed != 1:
                raise FinancialCollectionError(
                    "SHARD_CHECKPOINT_CONFLICT",
                    endpoint=checkpoint.endpoint,
                    instrument=checkpoint.ts_code,
                    shard=checkpoint.shard,
                )
            operation = transaction.execute(
                """
                UPDATE data.financial_collection_operations
                SET completed_count = completed_count + 1, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                RETURNING completed_count
                """,
                (collected_at, idempotency_key),
            ).fetchone()
            if operation is None:
                raise FinancialCollectionError(
                    "SHARD_CHECKPOINT_CONFLICT",
                    endpoint=checkpoint.endpoint,
                    instrument=checkpoint.ts_code,
                    shard=checkpoint.shard,
                )
            return int(operation["completed_count"])

    def _failed_progress(
        self,
        checkpoint: FinancialShardCheckpoint,
        target_count: int,
        resumed_count: int,
        started: float,
        failure_code: str,
    ) -> None:
        self._progress(
            {
                "event": "financial_collection",
                "phase": "source_request",
                "status": "failed",
                "endpoint": checkpoint.endpoint,
                "instrument": checkpoint.ts_code,
                "shard": checkpoint.shard,
                "failure_code": failure_code,
                "target_count": target_count,
                "completed_count": checkpoint.ordinal,
                "failed_count": 1,
                "resumed_count": resumed_count,
                "duration_seconds": _duration(started, self._monotonic()),
            }
        )

    def _finish(self, idempotency_key: str) -> FinancialCollectionOutcome:
        finished_at = self._clock()
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                UPDATE data.financial_collection_operations
                SET status = 'succeeded', finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                  AND completed_count = target_count
                RETURNING target_count, completed_count
                """,
                (finished_at, finished_at, idempotency_key),
            ).fetchone()
        if row is None:
            raise FinancialCollectionError("COLLECTION_INCOMPLETE")
        return FinancialCollectionOutcome(
            idempotency_key,
            "succeeded",
            int(row["target_count"]),
            int(row["completed_count"]),
        )

    def _mark_failed(self, idempotency_key: str, failure: FinancialCollectionError) -> None:
        failed_at = self._clock()
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.financial_collection_operations
                SET status = 'failed', failure_code = %s, failure_endpoint = %s,
                    failure_instrument = %s, failure_shard = %s,
                    finished_at = %s, updated_at = %s
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (
                    failure.code,
                    failure.endpoint,
                    failure.instrument,
                    failure.shard,
                    failed_at,
                    failed_at,
                    idempotency_key,
                ),
            )

    def _stored_failure(self, idempotency_key: str) -> FinancialCollectionError:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT failure_code, failure_endpoint, failure_instrument, failure_shard
                FROM data.financial_collection_operations WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        assert row is not None
        return FinancialCollectionError(
            str(row["failure_code"]),
            endpoint=str(row["failure_endpoint"]),
            instrument=str(row["failure_instrument"]),
            shard=str(row["failure_shard"]),
        )


def probe_financial_capability(
    source: FinancialRawSource,
    *,
    reference_instrument: str,
    comparison_shards: tuple[FinancialDateShard, ...],
    observed_rate_limit_events: Mapping[str, Sequence[float]] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FinancialCapabilityReport:
    now = (clock or (lambda: datetime.now(UTC)))()
    if not reference_instrument or not comparison_shards:
        raise ValueError("financial capability probe configuration is invalid")
    _validate_probe_shards(comparison_shards, through=now)
    endpoint_reports: list[FinancialEndpointCapability] = []
    rate_limits = observed_rate_limit_events if observed_rate_limit_events is not None else {}
    for endpoint in FINANCIAL_ENDPOINTS:
        try:
            full = _probe_query(
                source,
                endpoint=endpoint,
                reference_instrument=reference_instrument,
                shard="complete-history",
                parameters={"ts_code": reference_instrument},
                fields=(),
            )
            _validate_probe_response(
                full,
                endpoint=endpoint,
                instrument=reference_instrument,
                shard="complete-history",
            )
            comparison: list[tuple[object, ...]] = []
            comparison_counts: list[int] = []
            matching_schema = True
            for shard in comparison_shards:
                response = _probe_query(
                    source,
                    endpoint=endpoint,
                    reference_instrument=reference_instrument,
                    shard=shard.name,
                    parameters={"ts_code": reference_instrument, **shard.parameters()},
                    fields=full.fields,
                )
                _validate_probe_response(
                    response,
                    endpoint=endpoint,
                    instrument=reference_instrument,
                    shard=shard.name,
                )
                matching_schema = matching_schema and response.fields == full.fields
                comparison.extend(response.items)
                comparison_counts.append(len(response.items))
            full_counter = _row_counter(full.items)
            comparison_counter = _row_counter(tuple(comparison))
            suspected_boundary = (
                len(full.items) if full.items and len(full.items) in comparison_counts else None
            )
            endpoint_reports.append(
                FinancialEndpointCapability(
                    endpoint=endpoint,
                    permission="available",
                    failure_code=None,
                    returned_fields=full.fields,
                    null_value_count=sum(value is None for row in full.items for value in row),
                    duplicate_row_count=sum(count - 1 for count in full_counter.values()),
                    full_history_row_count=len(full.items),
                    source_date_extent=_source_date_extent(full),
                    observed_response_row_counts=(len(full.items), *comparison_counts),
                    suspected_truncation_row_count=suspected_boundary,
                    observed_rate_limit_events=len(rate_limits.get(endpoint, ())),
                    observed_rate_limit_retry_seconds=tuple(
                        float(seconds) for seconds in rate_limits.get(endpoint, ())
                    ),
                    full_history_proven=(
                        matching_schema
                        and suspected_boundary is None
                        and full_counter == comparison_counter
                    ),
                )
            )
        except FinancialCollectionError as error:
            endpoint_reports.append(
                FinancialEndpointCapability(
                    endpoint=endpoint,
                    permission=(
                        "unavailable" if error.code == "MISSING_PERMISSION" else "available"
                    ),
                    failure_code=error.code,
                    returned_fields=(),
                    null_value_count=0,
                    duplicate_row_count=0,
                    full_history_row_count=0,
                    source_date_extent=None,
                    observed_response_row_counts=(),
                    suspected_truncation_row_count=None,
                    observed_rate_limit_events=len(rate_limits.get(endpoint, ())),
                    observed_rate_limit_retry_seconds=tuple(
                        float(seconds) for seconds in rate_limits.get(endpoint, ())
                    ),
                    full_history_proven=False,
                )
            )
    if now.tzinfo is None:
        raise ValueError("financial capability probe time must be timezone-aware")
    return FinancialCapabilityReport(
        format="thesistrace-financial-capability",
        version=1,
        probed_at=now.isoformat(),
        reference_instrument=reference_instrument,
        comparison_shards=comparison_shards,
        endpoints=tuple(endpoint_reports),
    )


def _validate_probe_response(
    response: RawSourceResponse,
    *,
    endpoint: str,
    instrument: str,
    shard: str,
) -> None:
    if (
        not response.fields
        or len(set(response.fields)) != len(response.fields)
        or not {"ts_code", "ann_date", "end_date"} <= set(response.fields)
        or any(len(row) != len(response.fields) for row in response.items)
    ):
        raise FinancialCollectionError(
            "MALFORMED_FIELDS",
            endpoint=endpoint,
            instrument=instrument,
            shard=shard,
        )
    code_position = response.fields.index("ts_code")
    announcement_position = response.fields.index("ann_date")
    end_date_position = response.fields.index("end_date")
    final_position = (
        response.fields.index("f_ann_date") if "f_ann_date" in response.fields else None
    )
    if any(
        row[code_position] != instrument
        or not _valid_optional_source_date(row[announcement_position])
        or not _valid_optional_source_date(row[end_date_position])
        or (final_position is not None and not _valid_optional_source_date(row[final_position]))
        for row in response.items
    ):
        raise FinancialCollectionError(
            "MALFORMED_FIELDS",
            endpoint=endpoint,
            instrument=instrument,
            shard=shard,
        )


def _validate_probe_shards(
    shards: tuple[FinancialDateShard, ...],
    *,
    through: datetime,
) -> None:
    if through.tzinfo is None or any(shard.start_date is None for shard in shards):
        raise ValueError("financial capability comparison shards are invalid")
    if len({shard.name for shard in shards}) != len(shards):
        raise ValueError("financial capability comparison shards are invalid")
    ordered = tuple(sorted(shards, key=lambda shard: str(shard.start_date)))
    if ordered != shards or shards[0].start_date != FINANCIAL_HISTORY_FLOOR:
        raise ValueError("financial capability comparison shards are invalid")
    for shard in shards:
        start = datetime.strptime(str(shard.start_date), "%Y%m%d").date()
        end = datetime.strptime(str(shard.end_date), "%Y%m%d").date()
        if (end - start).days > 365:
            raise ValueError("financial capability comparison shards are invalid")
    for previous, current in zip(shards, shards[1:], strict=False):
        previous_end = datetime.strptime(str(previous.end_date), "%Y%m%d").date()
        current_start = datetime.strptime(str(current.start_date), "%Y%m%d").date()
        if current_start != previous_end + timedelta(days=1):
            raise ValueError("financial capability comparison shards are invalid")
    if str(shards[-1].end_date) < through.date().strftime("%Y%m%d"):
        raise ValueError("financial capability comparison shards are invalid")


def _duration(started: float, finished: float) -> float:
    return round(max(0.0, finished - started), 6)


def _probe_query(
    source: FinancialRawSource,
    *,
    endpoint: str,
    reference_instrument: str,
    shard: str,
    parameters: Mapping[str, object],
    fields: Sequence[str],
) -> RawSourceResponse:
    try:
        return source.query_raw(endpoint, params=parameters, fields=fields)
    except RawSourceError as error:
        raise FinancialCollectionError(
            _source_failure_code(error),
            endpoint=endpoint,
            instrument=reference_instrument,
            shard=shard,
        ) from error
    except Exception as error:
        raise FinancialCollectionError(
            "SOURCE_FAILURE",
            endpoint=endpoint,
            instrument=reference_instrument,
            shard=shard,
        ) from error


def _row_counter(rows: tuple[tuple[object, ...], ...]) -> Counter[bytes]:
    return Counter(canonical_json_bytes(list(row)) for row in rows)


def _source_date_extent(response: RawSourceResponse) -> tuple[str, str] | None:
    announcement_position = response.fields.index("ann_date")
    final_position = (
        response.fields.index("f_ann_date") if "f_ann_date" in response.fields else None
    )
    dates = sorted(
        publication
        for row in response.items
        if (
            publication := _effective_source_publication_date(
                row[announcement_position],
                None if final_position is None else row[final_position],
            )
        )
        is not None
    )
    return None if not dates else (dates[0], dates[-1])


def _source_failure_code(error: RawSourceError) -> str:
    reason_code = getattr(error, "reason_code", None)
    return reason_code if isinstance(reason_code, str) and reason_code else "SOURCE_FAILURE"


def _validate_collection_request(
    idempotency_key: str,
    generation_manifest_sha256: str,
    contract: FinancialCollectionContract,
) -> None:
    if not idempotency_key or idempotency_key != idempotency_key.strip():
        raise FinancialCollectionError("INVALID_IDEMPOTENCY_KEY")
    if len(generation_manifest_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in generation_manifest_sha256
    ):
        raise FinancialCollectionError("INVALID_GENERATION")
    try:
        _validate_collection_contract(contract)
    except ValueError as error:
        raise FinancialCollectionError("INVALID_FINANCIAL_CONTRACT") from error


def _validate_collection_contract(contract: FinancialCollectionContract) -> None:
    if (
        len(contract.capability_sha256) != 64
        or any(character not in "0123456789abcdef" for character in contract.capability_sha256)
        or tuple(endpoint for endpoint, _fields in contract.endpoint_fields) != FINANCIAL_ENDPOINTS
        or any(
            not fields
            or len(set(fields)) != len(fields)
            or not _REQUIRED_FINANCIAL_FIELDS.issubset(fields)
            for _endpoint, fields in contract.endpoint_fields
        )
        or tuple(endpoint for endpoint, _count in contract.suspected_truncation_row_counts)
        != FINANCIAL_ENDPOINTS
        or not contract.shards
        or len({shard.name for shard in contract.shards}) != len(contract.shards)
    ):
        raise ValueError("financial collection contract is invalid")


def _checkpoint(row: Mapping[str, object]) -> FinancialShardCheckpoint:
    collected_at = row["collected_at"]
    if collected_at is not None and not isinstance(collected_at, datetime):
        raise FinancialCollectionError("SHARD_CHECKPOINT_INVALID")
    first_observed_at = row.get("first_observed_at")
    if first_observed_at is not None and not isinstance(first_observed_at, datetime):
        raise FinancialCollectionError("SHARD_CHECKPOINT_INVALID")
    return FinancialShardCheckpoint(
        ordinal=int(str(row["ordinal"])),
        endpoint=str(row["endpoint"]),
        instrument_id=str(row["instrument_id"]),
        ts_code=str(row["ts_code"]),
        shard=str(row["shard_name"]),
        status=str(row["status"]),
        batch_sha256=None if row["batch_sha256"] is None else str(row["batch_sha256"]),
        collected_at=None if collected_at is None else collected_at.isoformat(),
        first_observed_at=(None if first_observed_at is None else first_observed_at.isoformat()),
    )


def _shard_by_name(
    contract: FinancialCollectionContract,
    name: str,
) -> FinancialDateShard:
    matches = [shard for shard in contract.shards if shard.name == name]
    if len(matches) != 1:
        raise FinancialCollectionError("INVALID_FINANCIAL_CONTRACT")
    return matches[0]


def _raw_batch_content(
    *,
    checkpoint: FinancialShardCheckpoint,
    parameters: Mapping[str, object],
    expected_fields: tuple[str, ...],
    response: RawSourceResponse,
    suspected_truncation_row_count: int | None,
) -> tuple[bytes, str, tuple[str, str] | None]:
    diagnostic = {
        "endpoint": checkpoint.endpoint,
        "instrument": checkpoint.ts_code,
        "shard": checkpoint.shard,
    }
    if response.fields != expected_fields:
        raise FinancialCollectionError("SCHEMA_DRIFT", **diagnostic)
    if (
        not response.fields
        or len(set(response.fields)) != len(response.fields)
        or any(len(row) != len(response.fields) for row in response.items)
    ):
        raise FinancialCollectionError("MALFORMED_FIELDS", **diagnostic)
    required = {"ts_code", "ann_date", "end_date"}
    if not required <= set(response.fields):
        raise FinancialCollectionError("MALFORMED_FIELDS", **diagnostic)
    if (
        suspected_truncation_row_count is not None
        and len(response.items) >= suspected_truncation_row_count
    ):
        raise FinancialCollectionError("SUSPECTED_TRUNCATION", **diagnostic)
    code_position = response.fields.index("ts_code")
    announcement_position = response.fields.index("ann_date")
    end_date_position = response.fields.index("end_date")
    final_announcement_position = (
        response.fields.index("f_ann_date") if "f_ann_date" in response.fields else None
    )
    for row in response.items:
        if row[code_position] != checkpoint.ts_code:
            raise FinancialCollectionError("MALFORMED_FIELDS", **diagnostic)
        announcement = row[announcement_position]
        if not _valid_optional_source_date(announcement):
            raise FinancialCollectionError("MALFORMED_FIELDS", **diagnostic)
        if not _valid_optional_source_date(row[end_date_position]):
            raise FinancialCollectionError("MALFORMED_FIELDS", **diagnostic)
        final_announcement = (
            None if final_announcement_position is None else row[final_announcement_position]
        )
        if not _valid_optional_source_date(final_announcement):
            raise FinancialCollectionError("MALFORMED_FIELDS", **diagnostic)
        publication = _effective_source_publication_date(
            announcement,
            final_announcement,
        )
        if publication is not None:
            start = parameters.get("start_date")
            end = parameters.get("end_date")
            if start is not None and not (str(start) <= publication <= str(end)):
                raise FinancialCollectionError("RESPONSE_OUTSIDE_SHARD", **diagnostic)
    extent = _source_date_extent(response)
    payload = {
        "fields": list(response.fields),
        "items": [list(row) for row in response.items],
    }
    try:
        payload_bytes = canonical_json_bytes(payload)
    except (TypeError, ValueError) as error:
        raise FinancialCollectionError("MALFORMED_PAYLOAD", **diagnostic) from error
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    batch = {
        "format": "thesistrace-raw-financial-batch",
        "version": 1,
        "source_contract_version": FINANCIAL_SOURCE_CONTRACT_VERSION,
        "endpoint": checkpoint.endpoint,
        "parameters": dict(parameters),
        "returned_fields": list(response.fields),
        "items": [list(row) for row in response.items],
        "row_count": len(response.items),
        "source_date_extent": None if extent is None else list(extent),
        "payload_sha256": payload_sha256,
    }
    return canonical_json_bytes(batch), payload_sha256, extent


def _valid_source_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _valid_optional_source_date(value: object) -> bool:
    return value is None or value == "" or _valid_source_date(value)


def _effective_source_publication_date(
    announcement: object,
    final_announcement: object,
) -> str | None:
    if isinstance(final_announcement, str) and final_announcement:
        return final_announcement
    if isinstance(announcement, str) and announcement:
        return announcement
    return None


__all__ = (
    "CompletedFinancialCollection",
    "FINANCIAL_ENDPOINTS",
    "FINANCIAL_SOURCE_CONTRACT_VERSION",
    "FinancialCapabilityReport",
    "FinancialCollectionContract",
    "FinancialCollectionError",
    "FinancialCollectionOutcome",
    "FinancialCollectionService",
    "FinancialDateShard",
    "FinancialEndpointCapability",
    "FinancialRawSource",
    "FinancialShardCheckpoint",
    "RawFinancialBatchStore",
    "probe_financial_capability",
)

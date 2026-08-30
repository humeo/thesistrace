from __future__ import annotations

import json
from base64 import urlsafe_b64encode
from datetime import date, datetime
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.overview import DatasetOverviewService, DatasetOverviewSnapshot

DATA_REFRESH_OPERATION_PAGE_SIZE = 50
_MAX_CURSOR_LENGTH = 1_024

DataRefreshKind = Literal["market", "financial", "industry"]
DataRefreshStatus = Literal["accepted", "running", "succeeded", "failed", "cancelled"]
DataRefreshOutcome = Literal[
    "published",
    "no_change",
    "degraded",
    "business_rejected",
    "infrastructure_failed",
]


class DataRefreshInvalidCursor(ValueError):
    pass


class DatasetOperationalHead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_identity: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_at: datetime | None
    data_through_session: date | None
    market_research_readiness: bool
    benchmark_research_readiness: bool
    financial_research_readiness: Literal[
        "ready",
        "ready_with_pending",
        "ready_with_gaps",
        "not_ready",
    ]
    industry_research_readiness: bool


class DataOperatorWorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    last_heartbeat_at: datetime | None


class DataRefreshOperationalStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str
    kind: DataRefreshKind
    status: DataRefreshStatus
    outcome: DataRefreshOutcome | None
    as_of: datetime | None
    observation_through_session: date | None
    phase: str | None
    attempt_count: int = Field(ge=0)
    last_heartbeat_at: datetime | None
    data_through_session: date | None
    last_refresh_at: datetime | None
    financial_complete_through_session: date | None
    matched_trigger_count: int | None = Field(default=None, ge=0)
    checked_no_structured_change_count: int | None = Field(default=None, ge=0)
    accepted_instrument_count: int | None = Field(default=None, ge=0)
    failed_instrument_count: int | None = Field(default=None, ge=0)
    pending_instrument_count: int | None = Field(default=None, ge=0)
    discovery_gap_count: int | None = Field(default=None, ge=0)
    failure_code: str | None
    last_failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class DatasetOperationalStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    head: DatasetOperationalHead
    worker: DataOperatorWorkerStatus
    latest_by_kind: tuple[DataRefreshOperationalStatus, ...]
    operations: tuple[DataRefreshOperationalStatus, ...]
    next_cursor: str | None


class DatasetOperationalStatusService:
    """Read one bounded, safe projection of Dataset and Refresh operations."""

    def __init__(
        self,
        database: PostgresDatabase,
        overview: DatasetOverviewService,
    ) -> None:
        self._database = database
        self._overview = overview

    def status(self, *, cursor: str | None) -> DatasetOperationalStatus:
        overview = self._overview.snapshot()
        with self._database.transaction() as transaction:
            secret = _cursor_secret(transaction)
            cursor_created_at, cursor_key = _decode_cursor(cursor, secret=secret)
            latest_rows = transaction.execute(
                """
                SELECT latest.*
                FROM (
                    SELECT DISTINCT ON (kind) *
                    FROM data.refresh_operations
                    ORDER BY kind, created_at DESC, idempotency_key DESC
                ) AS latest
                ORDER BY CASE latest.kind
                    WHEN 'market' THEN 1
                    WHEN 'financial' THEN 2
                    WHEN 'industry' THEN 3
                END
                """
            ).fetchall()
            rows = transaction.execute(
                """
                SELECT *
                FROM data.refresh_operations
                WHERE (
                    %s::timestamptz IS NULL
                    OR created_at < %s::timestamptz
                    OR (
                        created_at = %s::timestamptz
                        AND idempotency_key < %s::text
                    )
                )
                ORDER BY created_at DESC, idempotency_key DESC
                LIMIT %s::integer
                """,
                (
                    cursor_created_at,
                    cursor_created_at,
                    cursor_created_at,
                    cursor_key,
                    DATA_REFRESH_OPERATION_PAGE_SIZE + 1,
                ),
            ).fetchall()
            worker_row = transaction.execute(
                """
                SELECT
                    lease_expires_at IS NOT NULL
                        AND lease_expires_at > clock_timestamp() AS available,
                    last_heartbeat_at
                FROM data.refresh_worker_leases
                WHERE singleton = 1
                """
            ).fetchone()
        operations = tuple(
            _operation_from_row(row)
            for row in rows[:DATA_REFRESH_OPERATION_PAGE_SIZE]
        )
        return DatasetOperationalStatus(
            head=_head_from_snapshot(overview),
            worker=DataOperatorWorkerStatus(
                available=bool(worker_row and worker_row["available"]),
                last_heartbeat_at=(
                    None if worker_row is None else worker_row["last_heartbeat_at"]
                ),
            ),
            latest_by_kind=tuple(_operation_from_row(row) for row in latest_rows),
            operations=operations,
            next_cursor=(
                _encode_cursor(
                    created_at=operations[-1].created_at,
                    idempotency_key=operations[-1].idempotency_key,
                    secret=secret,
                )
                if len(rows) > DATA_REFRESH_OPERATION_PAGE_SIZE
                else None
            ),
        )


def _head_from_snapshot(snapshot: DatasetOverviewSnapshot) -> DatasetOperationalHead:
    pointer = snapshot.pointer
    overview = snapshot.overview
    return DatasetOperationalHead(
        data_identity=None if pointer is None else pointer.data_identity,
        prepared_at=None if pointer is None else _aware_datetime(pointer.prepared_at),
        data_through_session=(
            None if pointer is None else date.fromisoformat(pointer.data_through_session)
        ),
        market_research_readiness=overview.market_research_readiness,
        benchmark_research_readiness=overview.benchmark_research_readiness,
        financial_research_readiness=overview.financial_research_readiness,
        industry_research_readiness=overview.industry_research_readiness,
    )


def _operation_from_row(row: dict[str, object]) -> DataRefreshOperationalStatus:
    return DataRefreshOperationalStatus(
        idempotency_key=str(row["idempotency_key"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        status=str(row["status"]),  # type: ignore[arg-type]
        outcome=None if row["outcome"] is None else str(row["outcome"]),  # type: ignore[arg-type]
        as_of=row["as_of"],  # type: ignore[arg-type]
        observation_through_session=row["observation_through_session"],  # type: ignore[arg-type]
        phase=None if row["phase"] is None else str(row["phase"]),
        attempt_count=int(row["attempt_count"]),
        last_heartbeat_at=row["last_heartbeat_at"],  # type: ignore[arg-type]
        data_through_session=row["data_through_session"],  # type: ignore[arg-type]
        last_refresh_at=row["last_refresh_at"],  # type: ignore[arg-type]
        financial_complete_through_session=row[
            "financial_complete_through_session"
        ],  # type: ignore[arg-type]
        matched_trigger_count=_optional_count(row["matched_trigger_count"]),
        checked_no_structured_change_count=_optional_count(
            row["checked_no_structured_change_count"]
        ),
        accepted_instrument_count=_optional_count(row["accepted_instrument_count"]),
        failed_instrument_count=_optional_count(row["failed_instrument_count"]),
        pending_instrument_count=_optional_count(row["pending_instrument_count"]),
        discovery_gap_count=_optional_count(row["discovery_gap_count"]),
        failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
        last_failure_code=(
            None if row["last_failure_code"] is None else str(row["last_failure_code"])
        ),
        created_at=row["created_at"],  # type: ignore[arg-type]
        started_at=row["started_at"],  # type: ignore[arg-type]
        finished_at=row["finished_at"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
    )


def _optional_count(value: object) -> int | None:
    return None if value is None else int(value)


def _cursor_secret(transaction: PostgresTransaction) -> bytes:
    row = transaction.execute(
        "SELECT secret FROM data.refresh_cursor_secrets WHERE singleton = 1",
        (),
    ).fetchone()
    if row is None or not isinstance(row.get("secret"), str):
        raise RuntimeError("Data Refresh cursor secret is unavailable")
    try:
        secret = bytes.fromhex(str(row["secret"]))
    except ValueError as error:
        raise RuntimeError("Data Refresh cursor secret is invalid") from error
    if len(secret) != 32:
        raise RuntimeError("Data Refresh cursor secret is invalid")
    return secret


def _cursor_fernet(secret: bytes) -> Fernet:
    return Fernet(urlsafe_b64encode(secret))


def _encode_cursor(
    *,
    created_at: datetime,
    idempotency_key: str,
    secret: bytes,
) -> str:
    payload = json.dumps(
        {
            "created_at": created_at.isoformat(),
            "idempotency_key": idempotency_key,
            "order": "created_at_desc_idempotency_key_desc",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _cursor_fernet(secret).encrypt(payload).decode("ascii")


def _decode_cursor(
    cursor: str | None,
    *,
    secret: bytes,
) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        if len(cursor) > _MAX_CURSOR_LENGTH:
            raise ValueError
        plaintext = _cursor_fernet(secret).decrypt(cursor.encode("ascii"))
        value = json.loads(plaintext.decode("utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"created_at", "idempotency_key", "order"}
            or value["order"] != "created_at_desc_idempotency_key_desc"
            or not isinstance(value["idempotency_key"], str)
            or not value["idempotency_key"]
            or len(value["idempotency_key"]) > 512
        ):
            raise ValueError
        created_at = datetime.fromisoformat(str(value["created_at"]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at, value["idempotency_key"]
    except (
        InvalidToken,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ):
        raise DataRefreshInvalidCursor("Data Refresh cursor is invalid") from None


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("Dataset Head preparation time is invalid")
    return parsed

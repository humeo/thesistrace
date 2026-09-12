"""Explicit metadata and detail queries for expiring daily holdings."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from thesistrace.research_kernel.holding_observations import DailyHoldingRow

HOLDING_PAGE_PARTITIONS = 8


class HoldingQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_session: StrictStr | None = None
    end_session: StrictStr | None = None
    limit: Annotated[StrictInt, Field(ge=1, le=50)] = 20
    cursor: Annotated[StrictStr, Field(min_length=1, max_length=8192)] | None = None

    @field_validator("start_session", "end_session")
    @classmethod
    def canonical_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Holding filter must be a canonical ISO date")
        return value

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_session and self.end_session and self.start_session > self.end_session:
            raise ValueError("Holding date range is reversed")
        return self

    def cursor_order(self) -> str:
        return json.dumps(self.model_dump(exclude={"cursor", "limit", "run_id", "track_id"}),
                          sort_keys=True, separators=(",", ":"))


class HoldingStatusQuery(HoldingQuery):
    section: Literal["daily_holdings_status"]


class HoldingDetailsQuery(HoldingQuery):
    section: Literal["daily_holdings"]
    unit_id: Annotated[StrictStr, Field(min_length=1, max_length=160)]
    instrument_id: Annotated[StrictStr, Field(min_length=1, max_length=128)] | None = None


class HoldingUnitMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id: str
    source_kind: Literal["research_run", "daily_track"]
    source_id: str
    first_session: str
    last_session: str
    published_at: datetime
    last_read_at: datetime | None
    expires_at: datetime
    status: Literal["available", "expired"]


class HoldingCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_session: str | None
    last_session: str | None
    session_count: Annotated[StrictInt, Field(ge=0)]


class HoldingStatusPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Literal["daily_holdings_status"] = "daily_holdings_status"
    status: Literal["recorded", "not_recorded"]
    units: Annotated[list[HoldingUnitMetadata], Field(max_length=50)]
    next_cursor: str | None


class HoldingDetailsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Literal["daily_holdings"] = "daily_holdings"
    status: Literal["available", "expired", "not_recorded"]
    unit: HoldingUnitMetadata | None
    reporting_point: Literal["post_execution_open"] = "post_execution_open"
    coverage: HoldingCoverage | None
    rows: Annotated[list[DailyHoldingRow], Field(max_length=50)]
    next_cursor: str | None


def read_holding_page(
    publication, transaction, reference, query: HoldingDetailsQuery, *, after=None,
):
    """Read verified partitions one at a time; the retention owner holds read admission."""
    from thesistrace.daily_holding_evidence import HOLDING_CONTRACT, read_holding_partition

    def read(names):
        return publication.read_selected_in_transaction(transaction, reference, frozenset(names))

    descriptor_payload = read({"daily_holdings"}).payloads["daily_holdings"]
    descriptor = json.loads(descriptor_payload.content)
    if (not isinstance(descriptor, dict)
            or set(descriptor) != {"reporting_point", "sessions", "parts"}
            or descriptor["reporting_point"] != "post_execution_open"):
        raise ValueError("Daily holding descriptor is invalid")
    sessions, parts = descriptor["sessions"], descriptor["parts"]
    if (not isinstance(sessions, list) or not sessions or sessions != sorted(set(sessions))
            or not isinstance(parts, list)):
        raise ValueError("Daily holding coverage is invalid")
    for session in sessions:
        if date.fromisoformat(session).isoformat() != session:
            raise ValueError("Daily holding coverage date is invalid")
    selected = [session for session in sessions
                if (query.start_session is None or session >= query.start_session)
                and (query.end_session is None or session <= query.end_session)]
    coverage = HoldingCoverage(
        first_session=selected[0] if selected else None,
        last_session=selected[-1] if selected else None, session_count=len(selected),
    )
    if after is not None:
        position = json.loads(after)
        if (not isinstance(position, list) or len(position) != 2
                or any(not isinstance(item, str) for item in position)):
            raise ValueError("Daily holding cursor position is invalid")
        after_key = tuple(position)
    else:
        after_key = None
    rows, previous = [], None
    scanned_parts, last_scanned, scan_incomplete = 0, None, False
    for index, part in enumerate(parts):
        if (not isinstance(part, dict)
                or set(part) != {"name", "row_count", "first", "last"}
                or part["name"] != f"daily_holdings.part-{index:06d}"
                or type(part["row_count"]) is not int or not 1 <= part["row_count"] <= 512
                or any(not isinstance(part[key], list) or len(part[key]) != 2
                       or any(not isinstance(value, str) for value in part[key])
                       for key in ("first", "last"))):
            raise ValueError("Daily holding partition descriptor is invalid")
        first, last = tuple(part["first"]), tuple(part["last"])
        if first > last or (previous is not None and previous >= first):
            raise ValueError("Daily holding partitions overlap")
        previous = last
        if (not selected or last[0] < selected[0] or first[0] > selected[-1]
                or (after_key is not None and last <= after_key) or len(rows) > query.limit):
            continue
        if scanned_parts >= HOLDING_PAGE_PARTITIONS:
            scan_incomplete = True
            continue
        payload = read({part["name"]}).payloads[part["name"]]
        scanned_parts += 1
        last_scanned = last
        if payload.media_type != "application/vnd.apache.parquet" or payload.serialization != {
            "format": "canonical-parquet", "writer_contract": HOLDING_CONTRACT.descriptor(),
        }:
            raise ValueError("Daily holding partition contract is invalid")
        values = read_holding_partition(payload.content)
        def key(row):
            return row["session"], row["instrument_id"]
        if (len(values) != part["row_count"] or key(values[0]) != first or key(values[-1]) != last
                or any(row["session"] not in sessions for row in values)):
            raise ValueError("Daily holding partition bounds differ from its rows")
        for row in values:
            if (row["session"] in selected and (after_key is None or key(row) > after_key)
                    and (query.instrument_id is None
                         or row["instrument_id"] == query.instrument_id)):
                rows.append(row)
                if len(rows) > query.limit:
                    break
    next_after = (json.dumps([rows[query.limit - 1]["session"],
                             rows[query.limit - 1]["instrument_id"]], separators=(",", ":"))
                  if len(rows) > query.limit else None)
    if next_after is None and scan_incomplete:
        next_after = json.dumps(last_scanned, separators=(",", ":"))
    return coverage, rows[:query.limit], next_after


def holding_query_response(
    retention, publication, researcher_id, *, sources, boundary, query, after, encode_cursor,
):
    """Use only resource-authorized immutable units; listing never performs detail reads."""
    if isinstance(query, HoldingStatusQuery):
        position = None
        if after is not None:
            position = json.loads(after)
            if (not isinstance(position, list) or len(position) != 2
                    or any(not isinstance(item, str) for item in position)):
                raise ValueError("Holding metadata cursor position is invalid")
            position = tuple(position)
        units, next_after, recorded = retention.list_units(
            researcher_id, sources=sources, boundary=boundary,
            start_session=query.start_session, end_session=query.end_session,
            after=position, limit=query.limit,
        )
        return HoldingStatusPage(
            status="recorded" if recorded else "not_recorded",
            units=units,
            next_cursor=encode_cursor(json.dumps(next_after, separators=(",", ":")))
            if next_after is not None else None,
        )
    metadata = retention.inspect(researcher_id, query.unit_id)
    if metadata is None:
        return HoldingDetailsPage(status="not_recorded", unit=None, coverage=None,
                                  rows=[], next_cursor=None)
    if ((metadata["source_kind"], metadata["source_id"]) not in sources
            or metadata["last_session"] > boundary):
        return None
    if ((query.start_session and query.start_session > metadata["last_session"])
            or (query.end_session and query.end_session < metadata["first_session"])):
        return HoldingDetailsPage(
            status=metadata["status"], unit=metadata,
            coverage=HoldingCoverage(first_session=None, last_session=None, session_count=0),
            rows=[], next_cursor=None,
        )

    def read(transaction, reference):
        coverage, rows, next_after = read_holding_page(
            publication, transaction, reference, query, after=after,
        )
        return coverage, [DailyHoldingRow.model_validate(row) for row in rows], (
            encode_cursor(next_after) if next_after is not None else None
        )

    result = retention.read_detail(researcher_id, query.unit_id, read)
    if result is None:
        return None
    metadata, value = result
    if metadata["status"] == "expired":
        return HoldingDetailsPage(status="expired", unit=metadata, coverage=None,
                                  rows=[], next_cursor=None)
    coverage, rows, cursor = value
    return HoldingDetailsPage(status="available", unit=metadata, coverage=coverage,
                              rows=rows, next_cursor=cursor)


type HoldingQueryInput = Annotated[
    HoldingStatusQuery | HoldingDetailsQuery, Field(discriminator="section"),
]
type HoldingPageResponse = Annotated[
    HoldingStatusPage | HoldingDetailsPage, Field(discriminator="section"),
]

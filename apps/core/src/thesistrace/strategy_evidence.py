"""Compressed, bounded partitions for time-limited Strategy execution evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from thesistrace.publication import (
    JsonPayload,
    ParquetRowsPayload,
    Publication,
    PublishedRef,
    StagedPayload,
    VerifiedBundle,
)
from thesistrace.publication.serialization import ParquetWriterContract
from thesistrace.research_kernel.strategy_events import (
    EVENT_ID_FIELDS,
    EVENT_MODELS,
    StrategyAdjustmentEvent,
    StrategyChildOrderEvent,
    StrategyExecutionConstraintEvent,
    StrategyFillEvent,
    StrategyFrameworkEvent,
    StrategyOrderEvent,
    StrategyTargetEvent,
)

EVENT_PARTITION_ROWS = 512
_JSON_FIELDS = frozenset({
    "allocation", "position_limits", "modules", "universe", "alpha", "proposal", "risk_adjustment",
    "portfolio_retentions",
})
_INTEGER_FIELDS = frozenset(
    {
        "unrounded_quantity",
        "legal_quantity",
        "quantity",
        "execution_shares_delta",
        "submitted_quantity",
    }
)
_NULLABLE_FIELDS = frozenset({"unrounded_quantity", "legal_quantity", "rejection_reason"})


def _field(name: str, section: str) -> pa.Field:
    if name in _INTEGER_FIELDS:
        data_type = pa.int64()
    else:
        data_type = pa.string()
    nullable = name in _NULLABLE_FIELDS or (
        section == "strategy_execution_constraints" and name == "order_id"
    ) or (
        section == "strategy_framework" and name == "target_id"
    )
    return pa.field(name, data_type, nullable=nullable)


def event_session_field(section: str) -> str:
    return ("decision_session" if section in {"strategy_targets", "strategy_framework"}
            else "session")


EVENT_CONTRACTS = {
    section: ParquetWriterContract(
        name="research-result-" + section.replace("_", "-"),
        version=3 if section == "strategy_framework" else 2,
        schema=pa.schema([_field(name, section) for name in model.model_fields]),
        sort_keys=(event_session_field(section), EVENT_ID_FIELDS[section]),
    )
    for section, model in EVENT_MODELS.items()
}


def strategy_event_payload_names(names) -> frozenset[str]:
    return frozenset(name for name in names if name in EVENT_MODELS or any(
        name.startswith(section + ".part-") for section in EVENT_MODELS
    ))


def recorded_event_sections(names: set[str] | frozenset[str]) -> set[str]:
    """Constraint evidence has independent availability; absent records are never inferred."""
    present = set(EVENT_MODELS) & names
    trading = set(EVENT_MODELS) - {"strategy_execution_constraints"}
    if (present and not trading <= present) or any(
        section not in present and any(name.startswith(section + ".part-") for name in names)
        for section in EVENT_MODELS
    ):
        raise ValueError("Strategy event publication is incomplete")
    return present


def event_order(section: str, row: Mapping[str, object]) -> tuple[str, str]:
    return str(row[event_session_field(section)]), str(row[EVENT_ID_FIELDS[section]])


def validated_event_rows(section: str, rows: Sequence[Mapping[str, object]]) -> list[dict]:
    if section not in EVENT_MODELS:
        raise ValueError("Unknown Strategy evidence section")
    if not 1 <= len(rows) <= EVENT_PARTITION_ROWS:
        raise ValueError("Strategy evidence partition size is invalid")
    result = [EVENT_MODELS[section].model_validate(row).model_dump(mode="json") for row in rows]
    from thesistrace.strategy_event_wire import event_record_byte_limit

    if any(len(json.dumps(row, separators=(",", ":")).encode()) > event_record_byte_limit(section)
           for row in result):
        raise ValueError("Strategy event record exceeds its transport and page bound")
    keys = [event_order(section, row) for row in result]
    if keys != sorted(set(keys)):
        raise ValueError("Strategy evidence partition is unordered or duplicated")
    return result


def strategy_event_payload(
    section: str,
    rows: Sequence[Mapping[str, object]],
) -> ParquetRowsPayload:
    values = validated_event_rows(section, rows)
    encoded = [
        {
            key: json.dumps(value, sort_keys=True, separators=(",", ":"))
            if key in _JSON_FIELDS
            else value
            for key, value in row.items()
        }
        for row in values
    ]
    return ParquetRowsPayload(rows=tuple(encoded), contract=EVENT_CONTRACTS[section])


def read_strategy_event_partition(section: str, content: bytes) -> list[dict]:
    contract = EVENT_CONTRACTS[section]
    table = pq.read_table(pa.BufferReader(content))
    if not table.schema.equals(contract.schema, check_metadata=False):
        raise ValueError("Strategy evidence partition schema is invalid")
    if any(table[field.name].null_count for field in table.schema if not field.nullable):
        raise ValueError("Strategy evidence partition is missing required fields")
    values = [
        {key: json.loads(value) if key in _JSON_FIELDS else value for key, value in row.items()}
        for row in table.to_pylist()
    ]
    return validated_event_rows(section, values)


class StrategyEvidencePublication:
    """Retain only immutable payload references and small partition bounds across chunks."""

    def __init__(self) -> None:
        self._parts: dict[str, list[dict[str, object]]] = {section: [] for section in EVENT_MODELS}
        self._payloads: dict[str, StagedPayload | ParquetRowsPayload] = {}

    def add(
        self,
        section: str,
        payload: StagedPayload | ParquetRowsPayload,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        values = validated_event_rows(section, rows)
        if isinstance(payload, ParquetRowsPayload):
            valid = payload == strategy_event_payload(section, values)
        else:
            valid = (
                payload.media_type == "application/vnd.apache.parquet"
                and payload.serialization
                == {
                    "format": "canonical-parquet",
                    "writer_contract": EVENT_CONTRACTS[section].descriptor(),
                }
            )
        if not valid:
            raise ValueError("Strategy evidence staged contract is invalid")
        parts = self._parts[section]
        first, last = event_order(section, values[0]), event_order(section, values[-1])
        if parts and tuple(parts[-1]["last"]) >= first:
            raise ValueError("Strategy evidence partitions overlap")
        name = f"{section}.part-{len(parts):06d}"
        parts.append(
            {
                "name": name,
                "row_count": len(values),
                "first": list(first),
                "last": list(last),
            }
        )
        self._payloads[name] = payload

    def finish(self) -> dict[str, JsonPayload | StagedPayload | ParquetRowsPayload]:
        return {
            **self._payloads,
            **{
                section: JsonPayload(
                    {
                        "status": "recorded",
                        "format": "partitioned-parquet",
                        "writer_contract": EVENT_CONTRACTS[section].descriptor(),
                        "partitions": list(parts),
                    }
                )
                for section, parts in self._parts.items()
            },
        }


def strategy_event_record_count(
    payloads: Mapping[str, object], *, section: str | None = None,
) -> int:
    """Count validated builder descriptors for the permanent evidence byte allowance."""
    if section is not None and section not in EVENT_MODELS:
        raise ValueError("Unknown Strategy evidence section")
    if not set(EVENT_MODELS) & set(payloads):
        return 0
    if not set(EVENT_MODELS) <= set(payloads):
        raise ValueError("Strategy evidence section set is incomplete")
    count = 0
    for name in EVENT_MODELS:
        descriptor = payloads[name]
        if not isinstance(descriptor, JsonPayload):
            raise ValueError("Strategy event count requires a publication descriptor")
        for part in descriptor.value["partitions"]:
            size = part["row_count"]
            if type(size) is not int or not 1 <= size <= EVENT_PARTITION_ROWS:
                raise ValueError("Strategy event partition count is invalid")
            if section is None or section == name:
                count += size
    return count


def event_partition_descriptors(bundle: VerifiedBundle, section: str) -> list[dict[str, object]]:
    """Validate physical bounds before selecting any event partition bytes."""
    if section not in EVENT_MODELS:
        raise ValueError("Unknown Strategy evidence section")
    payload = bundle.payloads[section]
    if payload.media_type != "application/json":
        raise ValueError("Strategy evidence descriptor encoding is invalid")
    value = json.loads(payload.content)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "status",
            "format",
            "writer_contract",
            "partitions",
        }
        or value
        != {
            **value,
            "status": "recorded",
            "format": "partitioned-parquet",
            "writer_contract": EVENT_CONTRACTS[section].descriptor(),
        }
        or not isinstance(value["partitions"], list)
    ):
        raise ValueError("Strategy evidence descriptor is invalid")
    prior = None
    for index, part in enumerate(value["partitions"]):
        if not isinstance(part, dict) or set(part) != {"name", "row_count", "first", "last"}:
            raise ValueError("Strategy evidence partition descriptor is invalid")
        if part["name"] != f"{section}.part-{index:06d}" or type(part["row_count"]) is not int:
            raise ValueError("Strategy evidence partition identity is invalid")
        first, last = part["first"], part["last"]
        if (
            not all(
                isinstance(key, list)
                and len(key) == 2
                and all(isinstance(item, str) and item for item in key)
                for key in (first, last)
            )
            or not 1 <= part["row_count"] <= EVENT_PARTITION_ROWS
        ):
            raise ValueError("Strategy evidence partition bounds are invalid")
        if first > last or (prior is not None and prior >= first):
            raise ValueError("Strategy evidence partition bounds overlap")
        prior = last
    return value["partitions"]


def event_matches(
    row: Mapping[str, object],
    section: str,
    filters: Mapping[str, str | None],
) -> bool:
    session = str(row[event_session_field(section)])
    start, end = filters.get("start_session"), filters.get("end_session")
    if (start is not None and session < start) or (end is not None and session > end):
        return False
    instrument = filters.get("instrument_id")
    if instrument is not None:
        if section in {"strategy_targets", "strategy_framework"}:
            if instrument not in EVENT_MODELS[section].model_validate(row).instrument_ids:
                return False
        elif row["instrument_id"] != instrument:
            return False
    return all(
        value is None or row.get(key) == value
        for key, value in filters.items()
        if key not in {"start_session", "end_session", "instrument_id"}
    )


def _validate_event_relationships(evidence: Mapping, covered: set[str]) -> None:
    """Parents executing together must reconcile before any part is staged."""
    try:
        targets = {row["target_id"]: row for row in evidence["strategy_targets"]}
        for row in evidence["strategy_framework"]:
            if row["target_id"] is not None:
                if targets[row["target_id"]]["decision_session"] != row["decision_session"]:
                    raise ValueError("Framework evidence differs from its final target Session")
        orders = {row["order_id"]: row for row in evidence["strategy_orders"]}
        children = {row["child_order_id"]: row for row in evidence["strategy_child_orders"]}
        fills = evidence["strategy_fills"]
        shared = ("target_id", "order_id", "decision_session", "session", "instrument_id",
                  "side", "reason")
        quantities = {key: 0 for key in orders}
        filled_children = set()
        for child in children.values():
            order = orders[child["order_id"]]
            if order["rejection_reason"] is not None or any(
                child[key] != order[key] for key in shared
            ):
                raise ValueError("Strategy event relationship differs from its order")
            quantities[child["order_id"]] += child["quantity"]
        for fill in fills:
            child = children[fill["child_order_id"]]
            if fill["child_order_id"] in filled_children or any(
                fill[key] != child[key] for key in (*shared, "quantity")
            ):
                raise ValueError("Strategy event relationship differs from its child order")
            filled_children.add(fill["child_order_id"])
        if filled_children != set(children):
            raise ValueError("Strategy event relationship is missing a child fill")
        for key, order in orders.items():
            expected = order["legal_quantity"] if order["rejection_reason"] is None else 0
            if quantities[key] != expected:
                raise ValueError("Strategy event relationship has incomplete order shares")
            # A first-session execution may refer to the preceding segment's pending target.
            if order["decision_session"] in covered:
                target = targets[order["target_id"]]
                if (target["decision_session"] != order["decision_session"]
                    or target["reason"] != order["reason"]):
                    raise ValueError("Strategy event relationship differs from its target")
        context = ("target_id", "decision_session", "session", "instrument_id", "side")
        submitted_orders = {
            tuple(order[key] for key in context): order for order in orders.values()
        }
        for constraint in evidence["strategy_execution_constraints"]:
            order = submitted_orders.get(tuple(constraint[key] for key in context))
            if constraint["submitted_quantity"]:
                if (order is None or order["order_id"] != constraint["order_id"]
                    or order["legal_quantity"] != constraint["submitted_quantity"]
                    or order["reason"] != constraint["decision_reason"]):
                    raise ValueError("Strategy constraint relationship differs from its order")
            elif order is not None:
                raise ValueError("Skipped Strategy constraint relationship cannot have an order")
            if constraint["decision_session"] in covered:
                target = targets[constraint["target_id"]]
                allocation = target["allocation"]
                if (target["decision_session"] != constraint["decision_session"]
                    or target["reason"] != constraint["decision_reason"]
                    or (allocation["mode"] if allocation is not None else "local")
                    != constraint["mode"]):
                    raise ValueError("Strategy constraint relationship differs from its target")
    except (KeyError, TypeError) as error:
        raise ValueError("Strategy event relationship has a missing or invalid parent") from error


def _event_parts(
    evidence: Mapping[str, Sequence[Mapping[str, object]]],
    sessions: Sequence[str],
) -> Iterator[tuple[str, list[Mapping[str, object]]]]:
    if set(evidence) != set(EVENT_MODELS):
        raise ValueError("Strategy evidence must declare every event section")
    covered = set(sessions)
    _validate_event_relationships(evidence, covered)
    for section, rows in evidence.items():
        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping) or row.get(event_session_field(section)) not in covered
            for row in rows
        ):
            raise ValueError("Strategy evidence is outside the completed segment")
        for start in range(0, len(rows), EVENT_PARTITION_ROWS):
            yield section, rows[start : start + EVENT_PARTITION_ROWS]


def strategy_evidence_payloads(
    evidence: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    sessions: Sequence[str],
) -> dict[str, JsonPayload | StagedPayload | ParquetRowsPayload]:
    builder = StrategyEvidencePublication()
    for section, part in _event_parts(evidence, sessions):
        builder.add(section, strategy_event_payload(section, part), part)
    return builder.finish()


def append_staged_strategy_evidence(
    builder: StrategyEvidencePublication,
    publication: Publication,
    evidence: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    sessions: Sequence[str],
    staging_authority: Callable[[], AbstractContextManager[None]],
) -> None:
    for section, part in _event_parts(evidence, sessions):
        payload = publication.stage(
            strategy_event_payload(section, part),
            staging_authority=staging_authority,
        )
        builder.add(section, payload, part)


def stage_strategy_evidence(
    publication: Publication,
    evidence: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    sessions: Sequence[str],
    staging_authority: Callable[[], AbstractContextManager[None]],
) -> dict[str, StagedPayload]:
    builder = StrategyEvidencePublication()
    append_staged_strategy_evidence(
        builder,
        publication,
        evidence,
        sessions=sessions,
        staging_authority=staging_authority,
    )
    return {
        name: payload
        if isinstance(payload, StagedPayload)
        else publication.stage(
            payload,
            staging_authority=staging_authority,
        )
        for name, payload in builder.finish().items()
    }


def verified_event_partitions(
    bundle: VerifiedBundle,
    *,
    sessions: Sequence[str],
) -> Iterator[tuple[str, str, list[dict[str, object]]]]:
    """Yield typed rows from a single completed segment and verify declared coverage."""
    covered = set(sessions)
    expected_names = set(EVENT_MODELS)
    for section in EVENT_MODELS:
        for part in event_partition_descriptors(bundle, section):
            name = part["name"]
            expected_names.add(name)
            payload = bundle.payloads[name]
            if payload.media_type != "application/vnd.apache.parquet" or payload.serialization != {
                "format": "canonical-parquet",
                "writer_contract": EVENT_CONTRACTS[section].descriptor(),
            }:
                raise ValueError("Strategy event payload contract is invalid")
            rows = read_strategy_event_partition(section, payload.content)
            if (
                len(rows) != part["row_count"]
                or list(event_order(section, rows[0])) != part["first"]
                or list(event_order(section, rows[-1])) != part["last"]
            ):
                raise ValueError("Strategy event rows differ from their partition bounds")
            if any(row[event_session_field(section)] not in covered for row in rows):
                raise ValueError("Strategy event is outside the completed segment")
            yield section, name, rows
    actual_names = {
        name
        for name in bundle.payloads
        if name in EVENT_MODELS
        or any(name.startswith(section + ".part-") for section in EVENT_MODELS)
    }
    if actual_names != expected_names:
        raise ValueError("Strategy event publication has unexpected partitions")


EventFilterIdentity = Annotated[StrictStr, Field(min_length=1, max_length=200)]
EventPageLimit = Annotated[StrictInt, Field(ge=1, le=50)]


class StrategyEventQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_session: StrictStr | None = None
    end_session: StrictStr | None = None
    instrument_id: EventFilterIdentity | None = None
    cursor: Annotated[StrictStr, Field(min_length=1, max_length=8192)] | None = None
    limit: EventPageLimit = 20

    @field_validator("start_session", "end_session")
    @classmethod
    def canonical_date(cls, value: str | None) -> str | None:
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Event date must be canonical ISO date")
        return value

    @model_validator(mode="after")
    def ordered_date_range(self):
        if self.start_session and self.end_session and self.start_session > self.end_session:
            raise ValueError("Event date range is reversed")
        return self

    def filters(self) -> dict[str, str | None]:
        return self.model_dump(exclude={"run_id", "track_id", "section", "cursor", "limit"})

    def cursor_order(self) -> str:
        return json.dumps(
            {"order": "session_event_id", "filters": self.filters()},
            sort_keys=True,
            separators=(",", ":"),
        )


class StrategyTargetsQuery(StrategyEventQuery):
    section: Literal["strategy_targets"]
    target_id: EventFilterIdentity | None = None


class StrategyFrameworkQuery(StrategyEventQuery):
    section: Literal["strategy_framework"]
    target_id: EventFilterIdentity | None = None
    decision_id: EventFilterIdentity | None = None


class StrategyOrdersQuery(StrategyEventQuery):
    section: Literal["strategy_orders"]
    target_id: EventFilterIdentity | None = None
    order_id: EventFilterIdentity | None = None


class StrategyChildOrdersQuery(StrategyEventQuery):
    section: Literal["strategy_child_orders"]
    target_id: EventFilterIdentity | None = None
    order_id: EventFilterIdentity | None = None
    child_order_id: EventFilterIdentity | None = None


class StrategyFillsQuery(StrategyEventQuery):
    section: Literal["strategy_fills"]
    target_id: EventFilterIdentity | None = None
    order_id: EventFilterIdentity | None = None
    child_order_id: EventFilterIdentity | None = None
    fill_id: EventFilterIdentity | None = None


class StrategyAdjustmentsQuery(StrategyEventQuery):
    section: Literal["strategy_adjustments"]
    adjustment_id: EventFilterIdentity | None = None


class StrategyExecutionConstraintsQuery(StrategyEventQuery):
    section: Literal["strategy_execution_constraints"]
    target_id: EventFilterIdentity | None = None
    order_id: EventFilterIdentity | None = None
    constraint_id: EventFilterIdentity | None = None


@dataclass(frozen=True)
class StrategyEventPageRead:
    status: Literal["recorded", "not_recorded", "expired", "partially_expired"]
    rows: list[dict[str, object]]
    next_after: str | None = None
    expires_at: datetime | None = None


def read_retained_strategy_events(database, publication, reference, *, query, after=None):
    from dataclasses import replace

    from thesistrace.publication.payload_retention import PayloadRetention

    metadata, page = PayloadRetention(database, publication).read_detail(
        reference, lambda tx: read_strategy_event_page(
            publication, reference, query=query, after=after, transaction=tx,
        ), payload_name=query.section,
    )
    if page is None:
        return StrategyEventPageRead(status="expired", rows=[], expires_at=metadata["expires_at"])
    return replace(page, expires_at=metadata["expires_at"]) if metadata else page


def event_cursor_after(section: str, row: Mapping[str, object]) -> str:
    return json.dumps(event_order(section, row), separators=(",", ":"))


def read_strategy_event_page(
    publication: Publication,
    published_ref: PublishedRef,
    *,
    query: StrategyEventQuery,
    after: str | None = None,
    transaction=None,
) -> StrategyEventPageRead:
    section = query.section
    if section not in EVENT_MODELS:
        raise ValueError("Unknown Strategy evidence section")
    boundary = None
    if after is not None:
        value = json.loads(after)
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise ValueError("Event cursor position is invalid")
        boundary = tuple(value)
    inventory = (publication.payload_names(published_ref) if transaction is None else
                 publication.payload_names_in_transaction(transaction, published_ref))
    def read_selected(names):
        if transaction is None:
            return publication.read_selected(published_ref, names)
        return publication.read_selected_in_transaction(transaction, published_ref, names)

    present = recorded_event_sections(inventory)
    if section not in present:
        return StrategyEventPageRead(status="not_recorded", rows=[])
    descriptor = read_selected(frozenset({section}))
    parts = event_partition_descriptors(descriptor, section)
    partition_names = {part["name"] for part in parts}
    if partition_names != {name for name in inventory if name.startswith(section + ".part-")}:
        raise ValueError("Strategy event publication partitions are incomplete")
    rows = []
    filters = query.filters()
    for part in parts:
        if boundary is not None and tuple(part["last"]) <= boundary:
            continue
        if query.start_session is not None and part["last"][0] < query.start_session:
            continue
        if query.end_session is not None and part["first"][0] > query.end_session:
            break
        bundle = read_selected(frozenset({part["name"]}))
        payload = bundle.payloads[part["name"]]
        if payload.media_type != "application/vnd.apache.parquet" or payload.serialization != {
            "format": "canonical-parquet",
            "writer_contract": EVENT_CONTRACTS[section].descriptor(),
        }:
            raise ValueError("Strategy event payload contract is invalid")
        values = read_strategy_event_partition(section, payload.content)
        if (
            len(values) != part["row_count"]
            or list(event_order(section, values[0])) != part["first"]
            or list(event_order(section, values[-1])) != part["last"]
        ):
            raise ValueError("Strategy event rows differ from their partition bounds")
        for row in values:
            if (boundary is None or event_order(section, row) > boundary) and event_matches(
                row, section, filters
            ):
                rows.append(row)
                if len(rows) > query.limit:
                    return StrategyEventPageRead(
                        status="recorded",
                        rows=rows[: query.limit],
                        next_after=event_cursor_after(section, rows[query.limit - 1]),
                    )
    return StrategyEventPageRead(status="recorded", rows=rows)


class StrategyEvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    kind: Literal["research_run", "daily_track"]
    id: EventFilterIdentity
    snapshot_id: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]

    @classmethod
    def for_publication(cls, *, kind, id: str, manifest_sha256: str):
        from hashlib import sha256

        identity = json.dumps(["strategy-evidence", kind, id, manifest_sha256])
        return cls(kind=kind, id=id, snapshot_id=sha256(identity.encode()).hexdigest())


class StrategyEventPage[Event](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source: StrategyEvidenceSource
    status: Literal["recorded", "not_recorded", "expired", "partially_expired"]
    rows: list[Event]
    next_cursor: str | None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def availability_matches_rows(self):
        if (self.status in {"not_recorded", "expired"}
                and (self.rows or self.next_cursor is not None)):
            raise ValueError("Unrecorded evidence cannot contain rows or a continuation")
        if len(self.rows) > 50:
            raise ValueError("Event page exceeds its row limit")
        return self


class StrategyTargetsPage(StrategyEventPage[StrategyTargetEvent]):
    section: Literal["strategy_targets"] = "strategy_targets"


class StrategyFrameworkPage(StrategyEventPage[StrategyFrameworkEvent]):
    section: Literal["strategy_framework"] = "strategy_framework"


class StrategyOrdersPage(StrategyEventPage[StrategyOrderEvent]):
    section: Literal["strategy_orders"] = "strategy_orders"


class StrategyChildOrdersPage(StrategyEventPage[StrategyChildOrderEvent]):
    section: Literal["strategy_child_orders"] = "strategy_child_orders"


class StrategyFillsPage(StrategyEventPage[StrategyFillEvent]):
    section: Literal["strategy_fills"] = "strategy_fills"


class StrategyAdjustmentsPage(StrategyEventPage[StrategyAdjustmentEvent]):
    section: Literal["strategy_adjustments"] = "strategy_adjustments"


class StrategyExecutionConstraintsPage(StrategyEventPage[StrategyExecutionConstraintEvent]):
    section: Literal["strategy_execution_constraints"] = "strategy_execution_constraints"


EVENT_PAGE_MODELS = {
    "strategy_framework": StrategyFrameworkPage,
    "strategy_targets": StrategyTargetsPage,
    "strategy_orders": StrategyOrdersPage,
    "strategy_child_orders": StrategyChildOrdersPage,
    "strategy_fills": StrategyFillsPage,
    "strategy_adjustments": StrategyAdjustmentsPage,
    "strategy_execution_constraints": StrategyExecutionConstraintsPage,
}


def strategy_event_response(
    query: StrategyEventQuery,
    read: StrategyEventPageRead,
    *,
    source: StrategyEvidenceSource,
    encode_cursor: Callable[[str], str],
):
    from thesistrace._paging import BUSINESS_PAGE_BYTES, fit_page
    from thesistrace.strategy_event_wire import event_record_byte_limit

    def build(rows):
        has_more = len(rows) < len(read.rows) or read.next_after is not None
        cursor = (
            encode_cursor(event_cursor_after(query.section, rows[-1]))
            if has_more and rows
            else None
        )
        return EVENT_PAGE_MODELS[query.section](
            source=source,
            status=read.status,
            expires_at=read.expires_at,
            rows=rows,
            next_cursor=cursor,
        )

    return fit_page(read.rows, build, byte_budget=BUSINESS_PAGE_BYTES + (
        event_record_byte_limit(query.section)
        if query.section in {"strategy_targets", "strategy_framework"} else 0
    ))


type StrategyEventQueryInput = Annotated[
    StrategyTargetsQuery | StrategyOrdersQuery | StrategyChildOrdersQuery
    | StrategyFillsQuery | StrategyAdjustmentsQuery | StrategyExecutionConstraintsQuery
    | StrategyFrameworkQuery,
    Field(discriminator="section"),
]
type StrategyEventPageResponse = Annotated[
    StrategyTargetsPage | StrategyOrdersPage | StrategyChildOrdersPage
    | StrategyFillsPage | StrategyAdjustmentsPage | StrategyExecutionConstraintsPage
    | StrategyFrameworkPage,
    Field(discriminator="section"),
]

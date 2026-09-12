"""Bounded immutable daily holdings, published independently of permanent Results."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.publication import JsonPayload, ParquetRowsPayload, StagedPayload
from thesistrace.publication.serialization import ParquetWriterContract
from thesistrace.research_kernel.holding_observations import DailyHoldingRow

HOLDING_PARTITION_ROWS = 512
HOLDING_CONTRACT = ParquetWriterContract(
    name="daily-holding-observations",
    version=1,
    schema=pa.schema([
        pa.field(name, pa.int64() if name == "execution_shares" else
                 pa.float64() if name == "weight" else pa.string(), nullable=False)
        for name in DailyHoldingRow.model_fields
    ]),
    sort_keys=("session", "instrument_id"),
)


def _key(row: dict) -> tuple[str, str]:
    return row["session"], row["instrument_id"]


def validated_holding_rows(rows: Sequence[dict]) -> list[dict]:
    if not 1 <= len(rows) <= HOLDING_PARTITION_ROWS:
        raise ValueError("Daily holding partition size is invalid")
    values = [DailyHoldingRow.model_validate(row).model_dump(mode="json") for row in rows]
    keys = [_key(row) for row in values]
    if keys != sorted(set(keys)):
        raise ValueError("Daily holding rows must be ordered and unique")
    return values


def holding_partition(rows: Sequence[dict]) -> ParquetRowsPayload:
    return ParquetRowsPayload(rows=tuple(validated_holding_rows(rows)), contract=HOLDING_CONTRACT)


def read_holding_partition(content: bytes) -> list[dict]:
    table = pq.read_table(pa.BufferReader(content))
    if not table.schema.equals(HOLDING_CONTRACT.schema, check_metadata=False):
        raise ValueError("Daily holding partition schema is invalid")
    if any(table[field.name].null_count for field in table.schema):
        raise ValueError("Daily holding partition contains missing fields")
    return validated_holding_rows(table.to_pylist())


class HoldingEvidencePublication:
    """Accumulate coverage and staged references, without retaining prior Chunk rows."""

    def __init__(self) -> None:
        self._sessions: list[str] = []
        self._parts: list[dict] = []
        self._payloads: dict[str, ParquetRowsPayload | StagedPayload] = {}

    def add_segment(
        self, sessions: list[str], rows: list[dict], *,
        stage: Callable[[ParquetRowsPayload], StagedPayload] | None = None,
    ) -> None:
        if not sessions or sessions != sorted(set(sessions)):
            raise ValueError("Daily holding coverage must be ordered and unique")
        if self._sessions and self._sessions[-1] >= sessions[0]:
            raise ValueError("Daily holding segments overlap")
        covered = set(sessions)
        if any(row.get("session") not in covered for row in rows):
            raise ValueError("Daily holding row is outside coverage")
        previous = None
        # Validate the entire bounded segment before mutating the builder.
        for start in range(0, len(rows), HOLDING_PARTITION_ROWS):
            values = validated_holding_rows(rows[start:start + HOLDING_PARTITION_ROWS])
            if previous is not None and previous >= _key(values[0]):
                raise ValueError("Daily holding rows overlap")
            previous = _key(values[-1])
        for start in range(0, len(rows), HOLDING_PARTITION_ROWS):
            values = rows[start:start + HOLDING_PARTITION_ROWS]
            payload = holding_partition(values)
            stored = stage(payload) if stage is not None else payload
            name = f"daily_holdings.part-{len(self._parts):06d}"
            self._parts.append({
                "name": name, "row_count": len(values),
                "first": list(_key(values[0])), "last": list(_key(values[-1])),
            })
            self._payloads[name] = stored
        self._sessions.extend(sessions)

    def finish(self) -> dict[str, JsonPayload | ParquetRowsPayload | StagedPayload]:
        if not self._sessions:
            raise ValueError("Daily holding publication has no Session coverage")
        return {
            "daily_holdings": JsonPayload({
                "reporting_point": "post_execution_open",
                "sessions": list(self._sessions),
                "parts": [dict(part) for part in self._parts],
            }),
            **self._payloads,
        }


def stage_holding_evidence(publication, sessions, rows, *, staging_authority):
    builder = HoldingEvidencePublication()
    builder.add_segment(
        sessions, rows,
        stage=lambda payload: publication.stage(payload, staging_authority=staging_authority),
    )
    return {
        name: publication.stage(payload, staging_authority=staging_authority)
        if isinstance(payload, JsonPayload) else payload
        for name, payload in builder.finish().items()
    }


def merge_verified_holding_segment(builder, bundle, references, *, sessions):
    """Verify one checkpoint segment before carrying its immutable bytes to the final unit."""
    import hashlib
    import json

    descriptor = json.loads(bundle.payloads["daily_holdings"].content)
    if (not isinstance(descriptor, dict)
            or set(descriptor) != {"reporting_point", "sessions", "parts"}
            or descriptor["reporting_point"] != "post_execution_open"
            or descriptor["sessions"] != sessions
            or not isinstance(descriptor["parts"], list)):
        raise ValueError("Daily holding coverage is invalid")
    names = {"daily_holdings"}
    rows, staged = [], []
    for index, part in enumerate(descriptor["parts"]):
        name = f"daily_holdings.part-{index:06d}"
        if not isinstance(part, dict) or part.get("name") != name:
            raise ValueError("Daily holding partition identity is invalid")
        payload = bundle.payloads[name]
        reference = references[name]
        if (payload.media_type != "application/vnd.apache.parquet"
                or payload.serialization != {
                    "format": "canonical-parquet",
                    "writer_contract": HOLDING_CONTRACT.descriptor(),
                }
                or hashlib.sha256(payload.content).hexdigest() != reference.sha256
                or len(payload.content) != reference.byte_size):
            raise ValueError("Daily holding partition reference is invalid")
        values = read_holding_partition(payload.content)
        if (part != {"name": name, "row_count": len(values),
                     "first": list(_key(values[0])), "last": list(_key(values[-1]))}):
            raise ValueError("Daily holding partition bounds are invalid")
        names.add(name)
        rows.extend(values)
        staged.append(reference)
    if set(references) != names:
        raise ValueError("Daily holding partition inventory is invalid")
    iterator = iter(staged)
    builder.add_segment(sessions, rows, stage=lambda _: next(iterator))

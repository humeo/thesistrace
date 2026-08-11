from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

from thesistrace.publication.serialization import ParquetWriterContract

GENERATION_MANIFEST_MAX_BYTES = 1_048_576
GENERATION_OBJECT_MAX_BYTES = 268_435_456
GENERATION_SESSION_PARTITION_COUNT = 64
GENERATION_ROW_PARTITION_COUNT = 4_096


@dataclass(frozen=True)
class TableSpec:
    name: str
    contract: ParquetWriterContract
    session_field: str | None = None

    @property
    def partitioning(self) -> dict[str, object]:
        if self.session_field is not None:
            return {
                "kind": "research-session-block",
                "session_count": GENERATION_SESSION_PARTITION_COUNT,
            }
        return {"kind": "row-block", "row_count": GENERATION_ROW_PARTITION_COUNT}


def _contract(
    name: str,
    fields: tuple[tuple[str, pa.DataType], ...],
    sort_keys: tuple[str, ...],
    *,
    version: int = 1,
) -> ParquetWriterContract:
    return ParquetWriterContract(
        name=f"canonical-generation-{name}",
        version=version,
        schema=pa.schema([pa.field(field, kind, nullable=False) for field, kind in fields]),
        sort_keys=sort_keys,
    )


_STRING = pa.string()
_STRING_LIST = pa.list_(pa.field("item", pa.string(), nullable=False))
TABLE_SPECS = (
    TableSpec(
        "research_calendar",
        _contract("research-calendar", (("session", _STRING),), ("session",)),
        "session",
    ),
    TableSpec(
        "instruments",
        _contract(
            "instruments",
            tuple(
                (name, _STRING)
                for name in (
                    "instrument_id",
                    "ts_code",
                    "asset_type",
                    "exchange",
                    "board",
                    "listed_from",
                    "listed_to",
                )
            ),
            ("instrument_id",),
        ),
    ),
    TableSpec(
        "prices",
        _contract(
            "prices",
            tuple(
                (name, _STRING)
                for name in (
                    "session",
                    "instrument_id",
                    "open_raw",
                    "high_raw",
                    "low_raw",
                    "close_raw",
                    "pre_close_raw",
                    "change_raw",
                    "pct_change_raw",
                    "volume_shares",
                    "turnover_cny",
                    "adjustment_factor",
                    "open_adj",
                    "high_adj",
                    "low_adj",
                    "close_adj",
                    "trading_state",
                )
            ),
            ("session", "instrument_id"),
            version=2,
        ),
        "session",
    ),
    TableSpec(
        "trading_states",
        _contract(
            "trading-states",
            (("session", _STRING), ("instrument_id", _STRING), ("state", _STRING)),
            ("session", "instrument_id"),
        ),
        "session",
    ),
    TableSpec(
        "price_limits",
        _contract(
            "price-limits",
            (
                ("session", _STRING),
                ("instrument_id", _STRING),
                ("upper", _STRING),
                ("lower", _STRING),
            ),
            ("session", "instrument_id"),
        ),
        "session",
    ),
    TableSpec(
        "base_pool",
        _contract(
            "base-pool",
            (("session", _STRING), ("instrument_ids", _STRING_LIST)),
            ("session",),
        ),
        "session",
    ),
    TableSpec(
        "liquidity_universes",
        _contract(
            "liquidity-universes",
            (
                ("session", _STRING),
                ("universe", _STRING),
                ("instrument_ids", _STRING_LIST),
                ("status", _STRING),
            ),
            ("session", "universe"),
        ),
        "session",
    ),
    TableSpec(
        "industry_membership",
        _contract(
            "industry-membership",
            tuple(
                (name, _STRING)
                for name in (
                    "instrument_id",
                    "active_from",
                    "active_to",
                    "sw2021_l1",
                    "sw2021_l2",
                    "sw2021_l3",
                )
            ),
            ("instrument_id", "active_from"),
        ),
    ),
    TableSpec(
        "field_catalog",
        _contract(
            "field-catalog",
            (
                ("field_id", _STRING),
                ("name", _STRING),
                ("definition", _STRING),
                ("unit", _STRING),
                ("time_semantics", _STRING),
                ("alpha_authorable", pa.bool_()),
                ("release_available_from", _STRING),
                ("coverage", _STRING),
            ),
            ("field_id",),
        ),
    ),
)


__all__ = (
    "GENERATION_MANIFEST_MAX_BYTES",
    "GENERATION_OBJECT_MAX_BYTES",
    "GENERATION_ROW_PARTITION_COUNT",
    "GENERATION_SESSION_PARTITION_COUNT",
    "TABLE_SPECS",
    "TableSpec",
)

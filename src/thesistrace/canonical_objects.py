from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pyarrow as pa

from thesistrace.fixture import ALPHA_FIELDS, DAILY_FIELDS
from thesistrace.objects import (
    ImmutableObjectStore,
    ParquetContractError,
    ParquetWriterContract,
)


class CanonicalObjectError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalFamily:
    table: str
    family: str
    schema_version: str
    schema: pa.Schema
    sort_keys: tuple[str, ...]
    partition_field: str | None = None

    @property
    def writer_contract(self) -> ParquetWriterContract:
        return ParquetWriterContract(
            name=self.family,
            version=1,
            schema=self.schema,
            sort_keys=self.sort_keys,
        )


def required_string(name: str) -> pa.Field:
    return pa.field(name, pa.string(), nullable=False)


CANONICAL_FAMILIES = (
    CanonicalFamily(
        table="research_calendar",
        family="market.research_calendar",
        schema_version="research-calendar-v1",
        schema=pa.schema([required_string("session")]),
        sort_keys=("session",),
        partition_field="session",
    ),
    CanonicalFamily(
        table="instruments",
        family="instrument.identity",
        schema_version="instrument-identity-v1",
        schema=pa.schema(
            [
                required_string("instrument_id"),
                required_string("ts_code"),
                required_string("asset_type"),
                required_string("exchange"),
                required_string("board"),
                required_string("listed_from"),
                required_string("listed_to"),
            ]
        ),
        sort_keys=("instrument_id",),
    ),
    CanonicalFamily(
        table="prices",
        family="equity.eod_price",
        schema_version="equity-eod-price-v1",
        schema=pa.schema(
            [
                required_string("session"),
                required_string("instrument_id"),
                required_string("open_raw"),
                required_string("high_raw"),
                required_string("low_raw"),
                required_string("close_raw"),
                required_string("pre_close_raw"),
                required_string("change_raw"),
                required_string("pct_change_raw"),
                required_string("volume_shares"),
                required_string("turnover_cny"),
                required_string("adjustment_factor"),
                required_string("adjustment_anchor_factor"),
                required_string("open_adj"),
                required_string("high_adj"),
                required_string("low_adj"),
                required_string("close_adj"),
                required_string("trading_state"),
            ]
        ),
        sort_keys=("session", "instrument_id"),
        partition_field="session",
    ),
    CanonicalFamily(
        table="trading_states",
        family="equity.trading_state",
        schema_version="equity-trading-state-v1",
        schema=pa.schema(
            [
                required_string("session"),
                required_string("instrument_id"),
                required_string("state"),
            ]
        ),
        sort_keys=("session", "instrument_id"),
        partition_field="session",
    ),
    CanonicalFamily(
        table="price_limits",
        family="equity.price_limit",
        schema_version="equity-price-limit-v1",
        schema=pa.schema(
            [
                required_string("session"),
                required_string("instrument_id"),
                required_string("upper"),
                required_string("lower"),
            ]
        ),
        sort_keys=("session", "instrument_id"),
        partition_field="session",
    ),
    CanonicalFamily(
        table="adjustment_anchors",
        family="equity.adjustment_anchor",
        schema_version="equity-adjustment-anchor-v1",
        schema=pa.schema(
            [
                required_string("instrument_id"),
                required_string("anchor_session"),
                required_string("anchor_factor"),
            ]
        ),
        sort_keys=("instrument_id",),
        partition_field="anchor_session",
    ),
    CanonicalFamily(
        table="base_pool",
        family="universe.base_pool",
        schema_version="universe-base-pool-v1",
        schema=pa.schema(
            [
                required_string("session"),
                pa.field(
                    "instrument_ids",
                    pa.list_(pa.field("element", pa.string(), nullable=False)),
                    nullable=False,
                ),
            ]
        ),
        sort_keys=("session",),
        partition_field="session",
    ),
    CanonicalFamily(
        table="liquidity_universes",
        family="equity.liquidity_universe",
        schema_version="equity-liquidity-universe-v1",
        schema=pa.schema(
            [
                required_string("session"),
                required_string("universe"),
                required_string("status"),
                pa.field(
                    "instrument_ids",
                    pa.list_(pa.field("element", pa.string(), nullable=False)),
                    nullable=False,
                ),
            ]
        ),
        sort_keys=("session", "universe"),
        partition_field="session",
    ),
    CanonicalFamily(
        table="industry_membership",
        family="equity.industry_sw2021",
        schema_version="equity-industry-sw2021-v1",
        schema=pa.schema(
            [
                required_string("instrument_id"),
                required_string("active_from"),
                required_string("active_to"),
                required_string("sw2021_l1"),
                required_string("sw2021_l2"),
                required_string("sw2021_l3"),
            ]
        ),
        sort_keys=("instrument_id", "active_from"),
    ),
    CanonicalFamily(
        table="st_designations",
        family="equity.st_designation",
        schema_version="equity-st-designation-v1",
        schema=pa.schema(
            [
                required_string("trade_date"),
                required_string("instrument_id"),
                required_string("ts_code"),
                pa.field("name", pa.string(), nullable=True),
                pa.field("type", pa.string(), nullable=True),
                pa.field("type_name", pa.string(), nullable=True),
            ]
        ),
        sort_keys=("trade_date", "instrument_id"),
        partition_field="trade_date",
    ),
    CanonicalFamily(
        table="field_catalog",
        family="canonical.field_catalog",
        schema_version="canonical-field-catalog-v1",
        schema=pa.schema(
            [
                required_string("name"),
                required_string("field_id"),
                required_string("definition"),
                required_string("unit"),
                required_string("time_semantics"),
                pa.field("alpha_authorable", pa.bool_(), nullable=False),
                required_string("release_available_from"),
                required_string("coverage"),
            ]
        ),
        sort_keys=("field_id",),
    ),
)

FAMILY_BY_TABLE = {family.table: family for family in CANONICAL_FAMILIES}
FAMILY_BY_NAME = {family.family: family for family in CANONICAL_FAMILIES}

APPEND_KEYS = {
    "research_calendar_append": "research_calendar",
    "prices_append": "prices",
    "trading_states_append": "trading_states",
    "price_limits_append": "price_limits",
    "base_pool_append": "base_pool",
    "adjustment_anchors_append": "adjustment_anchors",
    "st_designations_append": "st_designations",
}

REPLACEMENT_KEYS = {
    "instruments_replace": "instruments",
    "industry_membership_replace": "industry_membership",
}


def canonical_schema_entries() -> list[dict[str, str]]:
    return [
        {"family": family.family, "version": family.schema_version}
        for family in CANONICAL_FAMILIES
    ]


def write_full_canonical(
    objects: ImmutableObjectStore,
    canonical: Mapping[str, object],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for family in CANONICAL_FAMILIES:
        if family.table not in canonical:
            continue
        rows = rows_for_table(family, canonical[family.table])
        if rows:
            entries.append(write_partition(objects, family, rows))
    return sort_partition_entries(entries)


def update_canonical_partitions(
    objects: ImmutableObjectStore,
    predecessor_entries: Sequence[Mapping[str, object]],
    canonical: Mapping[str, object],
    delta: Mapping[str, object],
) -> list[dict[str, object]]:
    entries = [dict(entry) for entry in predecessor_entries]
    if not entries:
        return write_full_canonical(objects, canonical)

    for delta_key, table in REPLACEMENT_KEYS.items():
        if delta.get(delta_key) is None:
            continue
        family = FAMILY_BY_TABLE[table]
        entries = without_family(entries, family.family)
        rows = rows_for_table(family, canonical[table])
        if rows:
            entries.append(write_partition(objects, family, rows))

    corrections = delta.get("price_corrections", [])
    if not isinstance(corrections, list):
        raise CanonicalObjectError("canonical price corrections must be a list")
    correction_sessions = {
        str(item["session"])
        for item in corrections
        if isinstance(item, Mapping) and "session" in item
    }
    if correction_sessions:
        entries = replace_affected_partitions(
            objects,
            entries,
            FAMILY_BY_TABLE["prices"],
            canonical["prices"],
            correction_sessions,
        )

    universe_replacements = delta.get("liquidity_universes_replace", {})
    if not isinstance(universe_replacements, Mapping):
        raise CanonicalObjectError("canonical universe replacements must be a mapping")
    replaced_universe_sessions = {
        str(snapshot["session"])
        for snapshots in universe_replacements.values()
        if isinstance(snapshots, list)
        for snapshot in snapshots
        if isinstance(snapshot, Mapping) and "session" in snapshot
    }
    if replaced_universe_sessions:
        entries = replace_affected_partitions(
            objects,
            entries,
            FAMILY_BY_TABLE["liquidity_universes"],
            canonical["liquidity_universes"],
            replaced_universe_sessions,
        )

    for delta_key, table in APPEND_KEYS.items():
        addition = delta.get(delta_key, [])
        if not isinstance(addition, list):
            raise CanonicalObjectError(f"{delta_key} must be a list")
        if not addition:
            continue
        family = FAMILY_BY_TABLE[table]
        rows = rows_for_table(family, addition)
        entries.append(write_partition(objects, family, rows))

    universe_additions = delta.get("liquidity_universes_append", {})
    if not isinstance(universe_additions, Mapping):
        raise CanonicalObjectError("canonical universe additions must be a mapping")
    universe_rows = rows_for_table(
        FAMILY_BY_TABLE["liquidity_universes"],
        universe_additions,
    )
    if universe_rows:
        entries.append(
            write_partition(
                objects,
                FAMILY_BY_TABLE["liquidity_universes"],
                universe_rows,
            )
        )
    return sort_partition_entries(entries)


def materialize_partitioned_canonical(
    objects: ImmutableObjectStore,
    release: Mapping[str, object],
    entries: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    table_names = release.get("canonical_tables")
    if not isinstance(table_names, list) or not all(
        isinstance(table, str) for table in table_names
    ):
        raise CanonicalObjectError("Dataset Release has no Canonical table manifest")
    canonical: dict[str, object] = {
        "schema_version": str(
            release.get("canonical_schema_version", "canonical-eod-v1")
        )
    }
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for entry in entries:
        family_name = str(entry.get("family", ""))
        grouped.setdefault(family_name, []).append(entry)
    for table in table_names:
        family = FAMILY_BY_TABLE.get(table)
        if family is None:
            raise CanonicalObjectError(f"unknown Canonical table: {table}")
        rows: list[dict[str, object]] = []
        identities: set[tuple[object, ...]] = set()
        for entry in sort_partition_entries(grouped.get(family.family, [])):
            validate_partition_entry(entry, family)
            try:
                table_value = objects.read_parquet(str(entry["sha256"]), family.writer_contract)
            except (OSError, ParquetContractError) as error:
                raise CanonicalObjectError(
                    f"cannot read Canonical partition for {family.family}"
                ) from error
            for row in table_value.to_pylist():
                identity = tuple(row[key] for key in family.sort_keys)
                if identity in identities:
                    raise CanonicalObjectError(
                        f"duplicate Canonical row identity in {family.family}"
                    )
                identities.add(identity)
                rows.append(row)
        rows.sort(key=lambda row: tuple(row[key] for key in family.sort_keys))
        canonical[table] = table_from_rows(family, rows)
    return canonical


def write_partition(
    objects: ImmutableObjectStore,
    family: CanonicalFamily,
    rows: Sequence[Mapping[str, object]],
    *,
    partition: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not rows:
        raise CanonicalObjectError("Canonical partition cannot be empty")
    coordinates = (
        dict(partition)
        if partition is not None
        else partition_coordinates(family, rows)
    )
    object_entry = objects.put_parquet_rows(rows, family.writer_contract)
    return {
        "kind": "canonical_partition",
        "family": family.family,
        "schema_version": family.schema_version,
        "partition": coordinates,
        **object_entry,
    }


def replace_affected_partitions(
    objects: ImmutableObjectStore,
    entries: list[dict[str, object]],
    family: CanonicalFamily,
    canonical_value: object,
    affected_coordinates: set[str],
) -> list[dict[str, object]]:
    if family.partition_field is None:
        raise CanonicalObjectError(f"{family.family} is not range partitioned")
    current_rows = rows_for_table(family, canonical_value)
    replaced = False
    updated: list[dict[str, object]] = []
    for entry in entries:
        if entry.get("family") != family.family:
            updated.append(entry)
            continue
        partition = entry.get("partition")
        if not isinstance(partition, Mapping):
            raise CanonicalObjectError("Canonical partition coordinates are invalid")
        start = str(partition.get("start", ""))
        end = str(partition.get("end", ""))
        if not any(start <= coordinate <= end for coordinate in affected_coordinates):
            updated.append(entry)
            continue
        rows = [
            row
            for row in current_rows
            if start <= str(row[family.partition_field]) <= end
        ]
        if not rows:
            raise CanonicalObjectError("Canonical replacement partition is empty")
        updated.append(write_partition(objects, family, rows, partition=partition))
        replaced = True
    if not replaced:
        raise CanonicalObjectError(
            f"no {family.family} partition covers accepted correction"
        )
    return updated


def rows_for_table(family: CanonicalFamily, value: object) -> list[dict[str, object]]:
    if family.table == "research_calendar":
        if not isinstance(value, list):
            raise CanonicalObjectError("Research Calendar must be a list")
        return [{"session": str(session)} for session in value]
    if family.table == "liquidity_universes":
        if not isinstance(value, Mapping):
            raise CanonicalObjectError("Liquidity Universes must be a mapping")
        return [
            {
                "session": str(snapshot["session"]),
                "universe": str(universe),
                "status": str(snapshot["status"]),
                "instrument_ids": [
                    str(instrument_id)
                    for instrument_id in snapshot["instrument_ids"]
                ],
            }
            for universe, snapshots in value.items()
            if isinstance(snapshots, list)
            for snapshot in snapshots
            if isinstance(snapshot, Mapping)
        ]
    if not isinstance(value, list):
        raise CanonicalObjectError(f"{family.table} must be a list")
    return [
        {str(key): item for key, item in row.items()}
        for row in value
        if isinstance(row, Mapping)
    ]


def table_from_rows(
    family: CanonicalFamily,
    rows: Sequence[Mapping[str, object]],
) -> object:
    if family.table == "research_calendar":
        return [str(row["session"]) for row in rows]
    if family.table == "liquidity_universes":
        universes: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            universes.setdefault(str(row["universe"]), []).append(
                {
                    "session": str(row["session"]),
                    "instrument_ids": list(row["instrument_ids"]),
                    "status": str(row["status"]),
                }
            )
        return universes
    materialized = [dict(row) for row in rows]
    if family.table == "field_catalog":
        known_order = {
            name: index
            for index, (name, *_rest) in enumerate((*DAILY_FIELDS, *ALPHA_FIELDS))
        }
        materialized.sort(
            key=lambda row: (
                known_order.get(str(row["name"]), len(known_order)),
                str(row["field_id"]),
            )
        )
    return materialized


def partition_coordinates(
    family: CanonicalFamily,
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if family.partition_field is None:
        return {"type": "complete"}
    coordinates = sorted(str(row[family.partition_field]) for row in rows)
    partition_type = (
        "session_range"
        if family.partition_field in {"session", "trade_date"}
        else f"{family.partition_field}_range"
    )
    return {
        "type": partition_type,
        "start": coordinates[0],
        "end": coordinates[-1],
    }


def validate_partition_entry(
    entry: Mapping[str, object],
    family: CanonicalFamily,
) -> None:
    if entry.get("kind") != "canonical_partition":
        raise CanonicalObjectError("invalid Canonical object kind")
    if entry.get("format") != "parquet":
        raise CanonicalObjectError("Canonical partitions must use Parquet")
    if entry.get("schema_version") != family.schema_version:
        raise CanonicalObjectError(
            f"unsupported Canonical schema for {family.family}"
        )
    if entry.get("writer_contract_id") != family.writer_contract.identifier:
        raise CanonicalObjectError(
            f"unsupported writer contract for {family.family}"
        )
    if not isinstance(entry.get("partition"), Mapping):
        raise CanonicalObjectError("Canonical partition coordinates are missing")


def without_family(
    entries: Sequence[dict[str, object]],
    family: str,
) -> list[dict[str, object]]:
    return [entry for entry in entries if entry.get("family") != family]


def sort_partition_entries(
    entries: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return sorted(
        (dict(entry) for entry in entries),
        key=lambda entry: (
            str(entry.get("family", "")),
            str(
                entry.get("partition", {}).get("start", "")
                if isinstance(entry.get("partition"), Mapping)
                else ""
            ),
            str(
                entry.get("partition", {}).get("end", "")
                if isinstance(entry.get("partition"), Mapping)
                else ""
            ),
            str(entry.get("sha256", "")),
        ),
    )

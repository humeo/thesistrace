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


CANONICAL_PARTITION_SESSION_CAP = 252


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
        for partition_rows in bounded_partition_rows(family, rows):
            entries.append(write_partition(objects, family, partition_rows))
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
        for partition_rows in bounded_partition_rows(family, rows):
            entries.append(write_partition(objects, family, partition_rows))

    universe_additions = delta.get("liquidity_universes_append", {})
    if not isinstance(universe_additions, Mapping):
        raise CanonicalObjectError("canonical universe additions must be a mapping")
    universe_rows = rows_for_table(
        FAMILY_BY_TABLE["liquidity_universes"],
        universe_additions,
    )
    if universe_rows:
        family = FAMILY_BY_TABLE["liquidity_universes"]
        for partition_rows in bounded_partition_rows(family, universe_rows):
            entries.append(write_partition(objects, family, partition_rows))
    return sort_partition_entries(entries)


def materialize_partitioned_canonical(
    objects: ImmutableObjectStore,
    release: Mapping[str, object],
    entries: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return materialize_partitioned_canonical_window(
        objects,
        release,
        entries,
        first_session=None,
        final_session=None,
    )


def materialize_partitioned_canonical_tail(
    objects: ImmutableObjectStore,
    release: Mapping[str, object],
    entries: Sequence[Mapping[str, object]],
    session_count: int,
) -> dict[str, object]:
    if session_count < 1:
        raise CanonicalObjectError("Canonical tail must contain at least one session")
    final_session = str(
        require_mapping(release.get("appended_session_range"))["end"]
    )
    table_cache: dict[str, pa.Table] = {}
    sessions = partitioned_research_calendar_window(
        objects,
        entries,
        final_session=final_session,
        session_count=session_count,
        table_cache=table_cache,
    )
    if not sessions:
        raise CanonicalObjectError("Canonical tail has no Research Session")
    return materialize_partitioned_canonical_window(
        objects,
        release,
        entries,
        first_session=sessions[0],
        final_session=sessions[-1],
        table_cache=table_cache,
    )


def materialize_partitioned_canonical_window(
    objects: ImmutableObjectStore,
    release: Mapping[str, object],
    entries: Sequence[Mapping[str, object]],
    *,
    first_session: str | None,
    final_session: str | None,
    table_cache: dict[str, pa.Table] | None = None,
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
            if not partition_overlaps_window(
                entry,
                family,
                first_session=first_session,
                final_session=final_session,
            ):
                continue
            try:
                table_value = read_partition_table(
                    objects,
                    entry,
                    family,
                    table_cache=table_cache,
                )
            except (OSError, ParquetContractError) as error:
                raise CanonicalObjectError(
                    f"cannot read Canonical partition for {family.family}"
                ) from error
            for row in table_value.to_pylist():
                if (
                    family.partition_field is not None
                    and not coordinate_in_window(
                        str(row[family.partition_field]),
                        first_session=first_session,
                        final_session=final_session,
                    )
                ):
                    continue
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


def partitioned_research_calendar_window(
    objects: ImmutableObjectStore,
    entries: Sequence[Mapping[str, object]],
    *,
    final_session: str,
    session_count: int,
    table_cache: dict[str, pa.Table] | None = None,
) -> list[str]:
    if session_count < 1:
        raise CanonicalObjectError(
            "Research Calendar window must contain at least one session"
        )
    family = FAMILY_BY_TABLE["research_calendar"]
    candidates = [
        entry
        for entry in sort_partition_entries(entries)
        if entry.get("family") == family.family
        and partition_starts_before_or_at(entry, final_session)
    ]
    sessions: set[str] = set()
    for entry in reversed(candidates):
        validate_partition_entry(entry, family)
        try:
            table = read_partition_table(
                objects,
                entry,
                family,
                table_cache=table_cache,
            )
        except (OSError, ParquetContractError) as error:
            raise CanonicalObjectError(
                "cannot read Canonical partition for market.research_calendar"
            ) from error
        sessions.update(
            str(row["session"])
            for row in table.to_pylist()
            if str(row["session"]) <= final_session
        )
        if len(sessions) >= session_count:
            break
    return sorted(sessions)[-session_count:]


def partitioned_research_calendar_neighborhood(
    objects: ImmutableObjectStore,
    entries: Sequence[Mapping[str, object]],
    *,
    center_session: str,
    preceding_sessions: int,
    following_sessions: int,
    table_cache: dict[str, pa.Table] | None = None,
) -> list[str]:
    if preceding_sessions < 0 or following_sessions < 0:
        raise CanonicalObjectError(
            "Research Calendar neighborhood bounds must be non-negative"
        )
    family = FAMILY_BY_TABLE["research_calendar"]
    candidates = [
        entry
        for entry in sort_partition_entries(entries)
        if entry.get("family") == family.family
    ]
    center_index = next(
        (
            index
            for index, entry in enumerate(candidates)
            if partition_contains(entry, center_session)
        ),
        None,
    )
    if center_index is None:
        raise CanonicalObjectError(
            "Research Calendar neighborhood center is missing"
        )
    sessions: set[str] = set()
    left = center_index
    right = center_index
    visited: set[int] = set()
    while True:
        for index in sorted({left, right}):
            if (
                index < 0
                or index >= len(candidates)
                or index in visited
            ):
                continue
            visited.add(index)
            entry = candidates[index]
            validate_partition_entry(entry, family)
            try:
                table = read_partition_table(
                    objects,
                    entry,
                    family,
                    table_cache=table_cache,
                )
            except (OSError, ParquetContractError) as error:
                raise CanonicalObjectError(
                    "cannot read Canonical partition for market.research_calendar"
                ) from error
            sessions.update(
                str(row["session"])
                for row in table.to_pylist()
            )
        ordered = sorted(sessions)
        center_position = (
            ordered.index(center_session)
            if center_session in ordered
            else -1
        )
        preceding_complete = (
            center_position >= preceding_sessions
            or left == 0
        )
        following_complete = (
            center_position >= 0
            and len(ordered) - center_position - 1 >= following_sessions
        ) or right == len(candidates) - 1
        if preceding_complete and following_complete:
            if center_position < 0:
                raise CanonicalObjectError(
                    "Research Calendar neighborhood center is missing"
                )
            return ordered[
                max(0, center_position - preceding_sessions) :
                center_position + following_sessions + 1
            ]
        if not preceding_complete:
            left -= 1
        if not following_complete:
            right += 1


def partitioned_research_calendar_range(
    objects: ImmutableObjectStore,
    entries: Sequence[Mapping[str, object]],
    *,
    after_session: str,
    through_session: str,
    table_cache: dict[str, pa.Table] | None = None,
) -> list[str]:
    if after_session >= through_session:
        return []
    family = FAMILY_BY_TABLE["research_calendar"]
    sessions: set[str] = set()
    for entry in sort_partition_entries(entries):
        if entry.get("family") != family.family:
            continue
        partition = require_mapping(entry.get("partition"))
        start = str(partition.get("start", ""))
        end = str(partition.get("end", ""))
        if (end and end <= after_session) or (
            start and start > through_session
        ):
            continue
        validate_partition_entry(entry, family)
        try:
            table = read_partition_table(
                objects,
                entry,
                family,
                table_cache=table_cache,
            )
        except (OSError, ParquetContractError) as error:
            raise CanonicalObjectError(
                "cannot read Canonical partition for market.research_calendar"
            ) from error
        sessions.update(
            str(row["session"])
            for row in table.to_pylist()
            if after_session < str(row["session"]) <= through_session
        )
    return sorted(sessions)


def partitioned_liquidity_universe_membership(
    objects: ImmutableObjectStore,
    entries: Sequence[Mapping[str, object]],
    *,
    universe_name: str,
    sessions: Sequence[str],
) -> dict[str, set[str]]:
    selected_sessions = set(sessions)
    if not selected_sessions:
        return {}
    family = FAMILY_BY_TABLE["liquidity_universes"]
    memberships = {
        session: set()
        for session in selected_sessions
    }
    for entry in sort_partition_entries(entries):
        if entry.get("family") != family.family:
            continue
        validate_partition_entry(entry, family)
        partition = require_mapping(entry.get("partition"))
        start = str(partition.get("start", ""))
        end = str(partition.get("end", ""))
        if start and end and not any(
            start <= session <= end
            for session in selected_sessions
        ):
            continue
        try:
            table = objects.read_parquet(
                str(entry["sha256"]),
                family.writer_contract,
            )
        except (OSError, ParquetContractError) as error:
            raise CanonicalObjectError(
                "cannot read Canonical liquidity universe partition"
            ) from error
        for row in table.to_pylist():
            session = str(row["session"])
            if (
                session in selected_sessions
                and str(row["universe"]) == universe_name
            ):
                memberships[session].update(
                    str(instrument_id)
                    for instrument_id in row["instrument_ids"]
                )
    return memberships


def read_partition_table(
    objects: ImmutableObjectStore,
    entry: Mapping[str, object],
    family: CanonicalFamily,
    *,
    table_cache: dict[str, pa.Table] | None,
) -> pa.Table:
    digest = str(entry["sha256"])
    if table_cache is not None and digest in table_cache:
        return table_cache[digest]
    table = objects.read_parquet(digest, family.writer_contract)
    if table_cache is not None:
        table_cache[digest] = table
    return table


def partition_overlaps_window(
    entry: Mapping[str, object],
    family: CanonicalFamily,
    *,
    first_session: str | None,
    final_session: str | None,
) -> bool:
    if family.partition_field is None or (
        first_session is None and final_session is None
    ):
        return True
    partition = require_mapping(entry.get("partition"))
    start = str(partition.get("start", ""))
    end = str(partition.get("end", ""))
    if not start or not end:
        return True
    return (
        (first_session is None or end >= first_session)
        and (final_session is None or start <= final_session)
    )


def partition_starts_before_or_at(
    entry: Mapping[str, object],
    final_session: str,
) -> bool:
    partition = require_mapping(entry.get("partition"))
    start = str(partition.get("start", ""))
    return not start or start <= final_session


def partition_contains(
    entry: Mapping[str, object],
    session: str,
) -> bool:
    partition = require_mapping(entry.get("partition"))
    start = str(partition.get("start", ""))
    end = str(partition.get("end", ""))
    return (not start or start <= session) and (not end or session <= end)


def coordinate_in_window(
    coordinate: str,
    *,
    first_session: str | None,
    final_session: str | None,
) -> bool:
    return (
        (first_session is None or coordinate >= first_session)
        and (final_session is None or coordinate <= final_session)
    )


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
        "coordinate_count": coordinate_count(family, rows),
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


def bounded_partition_rows(
    family: CanonicalFamily,
    rows: Sequence[Mapping[str, object]],
) -> list[list[dict[str, object]]]:
    materialized = [dict(row) for row in rows]
    if not materialized:
        return []
    if family.partition_field is None:
        return [materialized]
    coordinates = sorted(
        {
            str(row[family.partition_field])
            for row in materialized
        }
    )
    partition_by_coordinate = {
        coordinate: index // CANONICAL_PARTITION_SESSION_CAP
        for index, coordinate in enumerate(coordinates)
    }
    partitions: list[list[dict[str, object]]] = [
        []
        for _index in range(
            (len(coordinates) + CANONICAL_PARTITION_SESSION_CAP - 1)
            // CANONICAL_PARTITION_SESSION_CAP
        )
    ]
    for row in materialized:
        partitions[
            partition_by_coordinate[str(row[family.partition_field])]
        ].append(row)
    return partitions


def coordinate_count(
    family: CanonicalFamily,
    rows: Sequence[Mapping[str, object]],
) -> int:
    if family.partition_field is None:
        return 1
    return len(
        {
            str(row[family.partition_field])
            for row in rows
        }
    )


def require_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CanonicalObjectError("Canonical partition coordinates are invalid")
    return value


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

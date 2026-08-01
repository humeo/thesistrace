import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from thesistrace.canonical_objects import (
    FAMILY_BY_TABLE,
    canonical_schema_entries,
    sort_partition_entries,
    write_partition,
)
from thesistrace.datasets import DatasetPublisher, next_business_sessions
from thesistrace.fixture import (
    decimal_string,
    field_catalog,
    research_sessions,
)
from thesistrace.objects import canonical_json_bytes
from thesistrace.storage_admission import publication_storage_objects

CAPACITY_INSTRUMENT_COUNT = 3000
CAPACITY_SESSION_COUNT = 756
CAPACITY_PARTITION_SESSIONS = 21


def publish_capacity_corpus(
    publisher: DatasetPublisher,
    *,
    idempotency_key: str,
) -> tuple[dict[str, object], bool]:
    existing = publisher.metadata.dataset_release_for_idempotency_key(
        idempotency_key
    )
    if existing is not None:
        return existing, False
    if publisher.metadata.latest_dataset_release() is not None:
        raise RuntimeError("capacity corpus requires an empty Dataset repository")
    sessions = research_sessions()
    if len(sessions) != CAPACITY_SESSION_COUNT:
        raise RuntimeError("capacity corpus Research Calendar is invalid")
    instruments = _instruments(sessions[0])
    instrument_ids = [str(value["instrument_id"]) for value in instruments]
    entries: list[dict[str, object]] = []
    entries.append(
        write_partition(
            publisher.objects,
            FAMILY_BY_TABLE["instruments"],
            instruments,
        )
    )
    entries.append(
        write_partition(
            publisher.objects,
            FAMILY_BY_TABLE["adjustment_anchors"],
            [
                {
                    "instrument_id": instrument_id,
                    "anchor_session": sessions[0],
                    "anchor_factor": "1.000000",
                }
                for instrument_id in instrument_ids
            ],
        )
    )
    entries.append(
        write_partition(
            publisher.objects,
            FAMILY_BY_TABLE["industry_membership"],
            [
                {
                    "instrument_id": instrument_id,
                    "active_from": sessions[0],
                    "active_to": "",
                    "sw2021_l1": f"L1-{index % 30 + 1:02d}",
                    "sw2021_l2": f"L2-{index % 90 + 1:02d}",
                    "sw2021_l3": f"L3-{index % 180 + 1:03d}",
                }
                for index, instrument_id in enumerate(instrument_ids)
            ],
        )
    )
    entries.append(
        write_partition(
            publisher.objects,
            FAMILY_BY_TABLE["field_catalog"],
            field_catalog(sessions[0]),
        )
    )
    for start in range(0, len(sessions), CAPACITY_PARTITION_SESSIONS):
        selected_sessions = sessions[start : start + CAPACITY_PARTITION_SESSIONS]
        partition = {
            "type": "session_range",
            "start": selected_sessions[0],
            "end": selected_sessions[-1],
        }
        entries.extend(
            _write_session_partitions(
                publisher,
                sessions=selected_sessions,
                first_session_index=start,
                instruments=instruments,
                instrument_ids=instrument_ids,
                partition=partition,
            )
        )
    source_object = publisher.objects.put_json(
        {
            "source": "capacity-qualification-corpus",
            "generator_version": 1,
            "session_count": len(sessions),
            "instrument_count": len(instruments),
        }
    )
    objects = [
        {"kind": "source_capacity_qualification", **source_object},
        *sort_partition_entries(entries),
    ]
    manifest_core: dict[str, object] = {
        "predecessor_id": None,
        "created_at": datetime.now(UTC).isoformat(),
        "appended_session_range": {
            "start": sessions[0],
            "end": sessions[-1],
        },
        "session_count": len(sessions),
        "instrument_count": len(instruments),
        "correction_change_set": [],
        "canonical_schema_version": "canonical-eod-v1",
        "canonical_tables": [
            "adjustment_anchors",
            "base_pool",
            "field_catalog",
            "industry_membership",
            "instruments",
            "liquidity_universes",
            "price_limits",
            "prices",
            "research_calendar",
            "st_designations",
            "trading_states",
        ],
        "schemas": [
            {
                "family": "source_capacity_qualification",
                "version": "capacity-corpus-v1",
            },
            *canonical_schema_entries(),
        ],
        "objects": objects,
    }
    digest = hashlib.sha256(canonical_json_bytes(manifest_core)).hexdigest()
    release = {
        "id": f"dsr_{digest[:20]}",
        **manifest_core,
        "manifest_sha256": digest,
    }
    publisher.objects.put_manifest(str(release["id"]), release)
    return publisher.metadata.publish_dataset_release_with_storage(
        release,
        idempotency_key,
        publication_storage_objects(release),
    )


def maximum_definition() -> dict[str, object]:
    return {
        "title": "Top3000 capacity qualification",
        "hypothesis": "capacity qualification",
        "dataset_release": "latest",
        "universe": "top3000",
        "alpha": {"expression": "pct_change($close_adj, 252)"},
        "neutralization": "industry",
        "strategy": {
            "holdings_count": 100,
            "rebalance_interval": 20,
            "initial_cash_cny": "10000000",
            "execution": "next_open_full_fill",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
        "risk_free_rate": "0",
    }


def publish_capacity_increment(
    publisher: DatasetPublisher,
    *,
    idempotency_key: str,
) -> tuple[dict[str, object], bool]:
    predecessor = publisher.metadata.latest_dataset_release()
    if predecessor is None:
        raise RuntimeError("capacity corpus must be published first")
    session_range = predecessor.get("appended_session_range")
    if not isinstance(session_range, dict):
        raise RuntimeError("capacity corpus Release range is invalid")
    prior_session = str(session_range["end"])
    session = next_business_sessions(prior_session, 1)[0]
    session_index = int(predecessor["session_count"])
    instruments = _instruments(str(session_range["start"]))
    instrument_ids = [str(value["instrument_id"]) for value in instruments]
    prices = [
        _price_row(session, session_index, index, instrument)
        for index, instrument in enumerate(instruments)
    ]
    states = [
        {
            "session": session,
            "instrument_id": instrument_id,
            "state": "normal",
        }
        for instrument_id in instrument_ids
    ]
    limits = [
        {
            "session": session,
            "instrument_id": str(price["instrument_id"]),
            "upper": decimal_string(
                Decimal(str(price["close_raw"])) * Decimal("1.10"),
                4,
            ),
            "lower": decimal_string(
                Decimal(str(price["close_raw"])) * Decimal("0.90"),
                4,
            ),
        }
        for price in prices
    ]
    ranking = list(reversed(instrument_ids))
    return publisher.publish_increment_documents(
        idempotency_key,
        source={
            "source": "capacity-qualification-corpus",
            "generator_version": 1,
            "session": session,
            "corrections": [],
        },
        canonical_delta={
            "research_calendar_append": [session],
            "instruments_replace": instruments,
            "prices_append": prices,
            "trading_states_append": states,
            "price_limits_append": limits,
            "base_pool_append": [
                {"session": session, "instrument_ids": instrument_ids}
            ],
            "adjustment_anchors_append": [],
            "st_designations_append": [],
            "liquidity_universes_append": {
                f"top{size}": [
                    {
                        "session": session,
                        "status": "available",
                        "instrument_ids": ranking[:size],
                    }
                ]
                for size in (300, 1000, 2000, 3000)
            },
            "liquidity_universes_replace": {},
            "industry_membership_replace": [
                {
                    "instrument_id": instrument_id,
                    "active_from": str(session_range["start"]),
                    "active_to": "",
                    "sw2021_l1": f"L1-{index % 30 + 1:02d}",
                    "sw2021_l2": f"L2-{index % 90 + 1:02d}",
                    "sw2021_l3": f"L3-{index % 180 + 1:03d}",
                }
                for index, instrument_id in enumerate(instrument_ids)
            ],
            "price_corrections": [],
        },
        source_schema="capacity-corpus-v1",
    )


def _write_session_partitions(
    publisher: DatasetPublisher,
    *,
    sessions: list[str],
    first_session_index: int,
    instruments: list[dict[str, str]],
    instrument_ids: list[str],
    partition: dict[str, object],
) -> list[dict[str, object]]:
    calendar = [{"session": session} for session in sessions]
    prices: list[dict[str, object]] = []
    states: list[dict[str, object]] = []
    limits: list[dict[str, object]] = []
    for local_index, session in enumerate(sessions):
        session_index = first_session_index + local_index
        for instrument_index, instrument in enumerate(instruments):
            price = _price_row(session, session_index, instrument_index, instrument)
            prices.append(price)
            states.append(
                {
                    "session": session,
                    "instrument_id": instrument["instrument_id"],
                    "state": "normal",
                }
            )
            close = Decimal(str(price["close_raw"]))
            limits.append(
                {
                    "session": session,
                    "instrument_id": instrument["instrument_id"],
                    "upper": decimal_string(close * Decimal("1.10"), 4),
                    "lower": decimal_string(close * Decimal("0.90"), 4),
                }
            )
    universe_rows: list[dict[str, object]] = []
    sizes = (300, 1000, 2000, 3000)
    for local_index, session in enumerate(sessions):
        session_index = first_session_index + local_index
        ranking = sorted(
            instrument_ids,
            key=lambda value: (
                -int(value.removeprefix("equity:CAP").removesuffix(".SH")),
                value,
            ),
        )
        for size in sizes:
            universe_rows.append(
                {
                    "session": session,
                    "universe": f"top{size}",
                    "status": (
                        "available"
                        if session_index >= 19
                        else "insufficient_history"
                    ),
                    "instrument_ids": ranking[:size] if session_index >= 19 else [],
                }
            )
    rows_by_table = {
        "research_calendar": calendar,
        "prices": prices,
        "trading_states": states,
        "price_limits": limits,
        "base_pool": [
            {"session": session, "instrument_ids": instrument_ids}
            for session in sessions
        ],
        "liquidity_universes": universe_rows,
    }
    return [
        write_partition(
            publisher.objects,
            FAMILY_BY_TABLE[table],
            rows,
            partition=partition,
        )
        for table, rows in rows_by_table.items()
    ]


def _instruments(listed_from: str) -> list[dict[str, str]]:
    return [
        {
            "instrument_id": f"equity:CAP{index:04d}.SH",
            "ts_code": f"CAP{index:04d}.SH",
            "asset_type": "equity",
            "exchange": "SSE",
            "board": "main",
            "listed_from": listed_from,
            "listed_to": "",
        }
        for index in range(CAPACITY_INSTRUMENT_COUNT)
    ]


def _price_row(
    session: str,
    session_index: int,
    instrument_index: int,
    instrument: dict[str, str],
) -> dict[str, object]:
    base = Decimal("10") + Decimal(instrument_index % 500) / Decimal(100)
    slope = Decimal(instrument_index % 31 + 1) / Decimal(10000)
    cycle = Decimal((session_index + instrument_index) % 17) / Decimal(10000)
    close = base + Decimal(session_index) * slope + cycle
    prior_cycle = Decimal((max(0, session_index - 1) + instrument_index) % 17) / Decimal(10000)
    pre_close = base + Decimal(max(0, session_index - 1)) * slope + prior_cycle
    open_price = close - Decimal("0.005")
    change = close - pre_close
    return {
        "session": session,
        "instrument_id": instrument["instrument_id"],
        "open_raw": decimal_string(open_price, 4),
        "high_raw": decimal_string(close + Decimal("0.02"), 4),
        "low_raw": decimal_string(open_price - Decimal("0.02"), 4),
        "close_raw": decimal_string(close, 4),
        "pre_close_raw": decimal_string(pre_close, 4),
        "change_raw": decimal_string(change, 4),
        "pct_change_raw": decimal_string(change / pre_close * 100, 6),
        "volume_shares": str(10_000_000 + instrument_index * 100 + session_index),
        "turnover_cny": decimal_string(
            close * Decimal(10_000_000 + instrument_index * 100),
            2,
        ),
        "adjustment_factor": "1.000000",
        "adjustment_anchor_factor": "1.000000",
        "open_adj": decimal_string(open_price, 8),
        "high_adj": decimal_string(close + Decimal("0.02"), 8),
        "low_adj": decimal_string(open_price - Decimal("0.02"), 8),
        "close_adj": decimal_string(close, 8),
        "trading_state": "normal",
    }

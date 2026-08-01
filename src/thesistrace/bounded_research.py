import hashlib
import math
from array import array
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.alpha import evaluate_parsed_series, validate_alpha
from thesistrace.canonical_objects import (
    FAMILY_BY_TABLE,
    CanonicalFamily,
    partition_overlaps_window,
    partitioned_research_calendar_window,
    sort_partition_entries,
    validate_partition_entry,
)
from thesistrace.factor import correlation_summary, factor_day, mean_or_none
from thesistrace.numeric import canonical_binary64_bytes
from thesistrace.objects import canonical_json_bytes
from thesistrace.ports import ObjectStorePort
from thesistrace.strategy import run_strategy

HORIZONS = (1, 5, 20)
INPUT_SESSIONS = 756
REPORT_SESSIONS = 504
MISSING = math.nan
PRICE_FIELD_BY_ALPHA_FIELD = {
    "open_adj": "open_adj",
    "high_adj": "high_adj",
    "low_adj": "low_adj",
    "close_adj": "close_adj",
    "volume_shares": "volume_shares",
    "turnover_amount_cny": "turnover_cny",
}


class BoundedResearchError(RuntimeError):
    pass


class _FlatLookup(Mapping[tuple[str, str], object]):
    def __init__(self, window: "ColumnarResearchWindow") -> None:
        self.window = window

    def _position(self, key: tuple[str, str]) -> int | None:
        session, instrument_id = key
        session_index = self.window.session_index.get(session)
        instrument_index = self.window.instrument_index.get(instrument_id)
        if session_index is None or instrument_index is None:
            return None
        return session_index * self.window.instrument_count + instrument_index

    def __iter__(self) -> Iterator[tuple[str, str]]:
        for session_index, session in enumerate(self.window.sessions):
            offset = session_index * self.window.instrument_count
            for instrument_index, instrument_id in enumerate(
                self.window.instrument_ids
            ):
                if not math.isnan(self.window.price_fields["open_adj"][offset + instrument_index]):
                    yield session, instrument_id

    def __len__(self) -> int:
        return len(self.window.sessions) * self.window.instrument_count


class PriceLookup(_FlatLookup):
    def __getitem__(self, key: tuple[str, str]) -> dict[str, object]:
        position = self._position(key)
        if position is None:
            raise KeyError(key)
        adjusted_open = self.window.price_fields["open_adj"][position]
        if math.isnan(adjusted_open):
            raise KeyError(key)
        return {
            "open_adj": adjusted_open,
            "open_raw": self.window.price_fields["open_raw"][position],
        }

    def latest_adjusted_open_before(
        self,
        session: str,
        instrument_id: str,
    ) -> float | None:
        session_index = self.window.session_index.get(session)
        instrument_index = self.window.instrument_index.get(instrument_id)
        if session_index is None or instrument_index is None:
            return None
        for index in range(session_index - 1, -1, -1):
            value = self.window.price_fields["open_adj"][
                index * self.window.instrument_count + instrument_index
            ]
            if not math.isnan(value):
                return value
        return None


class StateLookup(_FlatLookup):
    def __getitem__(self, key: tuple[str, str]) -> str:
        position = self._position(key)
        if position is None:
            raise KeyError(key)
        state = self.window.trading_states[position]
        if state == 1:
            return "normal"
        if state == 2:
            return "full_session_suspension"
        raise KeyError(key)


class LimitLookup(_FlatLookup):
    def __getitem__(self, key: tuple[str, str]) -> dict[str, object]:
        position = self._position(key)
        if position is None:
            raise KeyError(key)
        upper = self.window.upper_limits[position]
        lower = self.window.lower_limits[position]
        if math.isnan(upper) or math.isnan(lower):
            raise KeyError(key)
        return {"upper": upper, "lower": lower}


class UniverseLookup(Mapping[str, list[str]]):
    def __init__(self, window: "ColumnarResearchWindow") -> None:
        self.window = window

    def __getitem__(self, session: str) -> list[str]:
        membership = self.window.universe_membership.get(session)
        if membership is None:
            raise KeyError(session)
        return [self.window.instrument_ids[index] for index in membership]

    def __iter__(self) -> Iterator[str]:
        return iter(self.window.sessions)

    def __len__(self) -> int:
        return len(self.window.sessions)


class AlphaValueStore(Mapping[str, list[dict[str, object]]]):
    def __init__(
        self,
        window: "ColumnarResearchWindow",
        values: array,
    ) -> None:
        self.window = window
        self.values = values

    def __getitem__(self, session: str) -> list[dict[str, object]]:
        session_index = self.window.session_index.get(session)
        if session_index is None:
            raise KeyError(session)
        offset = session_index * self.window.instrument_count
        rows: list[dict[str, object]] = []
        for instrument_index in self.window.universe_membership.get(session, ()):
            value = self.values[offset + instrument_index]
            if not math.isnan(value):
                rows.append(
                    {
                        "instrument_id": self.window.instrument_ids[instrument_index],
                        "value": value,
                    }
                )
        rows.sort(key=lambda row: str(row["instrument_id"]))
        return rows

    def __iter__(self) -> Iterator[str]:
        return iter(self.window.sessions)

    def __len__(self) -> int:
        return len(self.window.sessions)


@dataclass
class ColumnarResearchWindow:
    sessions: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    instruments: dict[str, dict[str, object]]
    universe_name: str
    universe_membership: dict[str, array]
    price_fields: dict[str, array]
    trading_states: bytearray
    upper_limits: array
    lower_limits: array
    st_designations: bytearray
    industry_membership: dict[str, tuple[dict[str, object], ...]]

    def __post_init__(self) -> None:
        self.session_index = {
            session: index for index, session in enumerate(self.sessions)
        }
        self.instrument_index = {
            instrument_id: index
            for index, instrument_id in enumerate(self.instrument_ids)
        }
        self.instrument_count = len(self.instrument_ids)

    def strategy_canonical(self) -> dict[str, object]:
        return {
            "research_calendar": list(self.sessions),
            "instruments": [self.instruments[value] for value in self.instrument_ids],
            "prices": PriceLookup(self),
            "trading_states": StateLookup(self),
            "price_limits": LimitLookup(self),
            "liquidity_universes": {
                self.universe_name: UniverseLookup(self),
            },
        }

    def discard_alpha_only_fields(self) -> None:
        self.price_fields = {
            field: values
            for field, values in self.price_fields.items()
            if field in {"open_adj", "open_raw"}
        }


def load_columnar_research_window(
    objects: ObjectStorePort,
    release: Mapping[str, object],
    definition: Mapping[str, object],
) -> ColumnarResearchWindow:
    entries_value = release.get("objects")
    if not isinstance(entries_value, list):
        raise BoundedResearchError("Dataset Release has no object manifest")
    entries = [
        entry
        for entry in entries_value
        if isinstance(entry, dict) and entry.get("kind") == "canonical_partition"
    ]
    if not entries:
        raise BoundedResearchError("Dataset Release is not partitioned Parquet")
    final_session = str(
        _mapping(release.get("appended_session_range"), "appended session range")[
            "end"
        ]
    )
    sessions = tuple(
        partitioned_research_calendar_window(
            objects,
            entries,
            final_session=final_session,
            session_count=INPUT_SESSIONS,
        )
    )
    if len(sessions) != INPUT_SESSIONS:
        raise BoundedResearchError("ResearchRun requires exactly 756 input sessions")
    first_session = sessions[0]
    session_index = {session: index for index, session in enumerate(sessions)}

    instrument_rows = _read_static_rows(objects, entries, "instruments")
    instrument_reference = {
        str(row["instrument_id"]): dict(row) for row in instrument_rows
    }
    universe_name = str(definition["universe"])
    global_ids = tuple(sorted(instrument_reference))
    global_index = {value: index for index, value in enumerate(global_ids)}
    global_membership: dict[str, array] = {session: array("I") for session in sessions}
    selected_global: set[int] = set()
    family = FAMILY_BY_TABLE["liquidity_universes"]
    for batch in _window_batches(
        objects,
        entries,
        family,
        first_session,
        final_session,
        columns=("session", "universe", "instrument_ids"),
    ):
        session_values = batch.column("session")
        universe_values = batch.column("universe")
        instrument_values = batch.column("instrument_ids")
        for row_index in range(batch.num_rows):
            session = str(session_values[row_index].as_py())
            if (
                session not in session_index
                or str(universe_values[row_index].as_py()) != universe_name
            ):
                continue
            membership = array("I")
            for instrument_id in instrument_values[row_index].as_py():
                index = global_index.get(str(instrument_id))
                if index is None:
                    raise BoundedResearchError(
                        "Liquidity Universe references an unknown instrument"
                    )
                membership.append(index)
                selected_global.add(index)
            global_membership[session] = membership
    selected_ids = tuple(global_ids[index] for index in sorted(selected_global))
    if not selected_ids:
        raise BoundedResearchError("selected Liquidity Universe is empty")
    compact_by_global = {
        global_value: compact
        for compact, global_value in enumerate(sorted(selected_global))
    }
    universe_membership = {
        session: array(
            "I",
            (compact_by_global[value] for value in global_membership[session]),
        )
        for session in sessions
    }
    compact_index = {value: index for index, value in enumerate(selected_ids)}
    cell_count = len(sessions) * len(selected_ids)

    alpha = _mapping(definition.get("alpha"), "Alpha definition")
    parsed = validate_alpha(str(alpha["expression"]))
    price_columns = {
        PRICE_FIELD_BY_ALPHA_FIELD[field] for field in parsed.field_names
    } | {"open_adj", "open_raw"}
    price_fields = {
        field: array("d", [MISSING]) * cell_count for field in price_columns
    }
    price_family = FAMILY_BY_TABLE["prices"]
    selected_price_columns = ("session", "instrument_id", *sorted(price_columns))
    for batch in _window_batches(
        objects,
        entries,
        price_family,
        first_session,
        final_session,
        columns=selected_price_columns,
    ):
        columns = {
            name: batch.column(name).to_pylist() for name in selected_price_columns
        }
        for row_index, session_value in enumerate(columns["session"]):
            session_position = session_index.get(str(session_value))
            instrument_position = compact_index.get(
                str(columns["instrument_id"][row_index])
            )
            if session_position is None or instrument_position is None:
                continue
            position = session_position * len(selected_ids) + instrument_position
            for field in price_columns:
                value = columns[field][row_index]
                if value is not None:
                    price_fields[field][position] = float(value)

    trading_states = bytearray(cell_count)
    state_family = FAMILY_BY_TABLE["trading_states"]
    for batch in _window_batches(
        objects,
        entries,
        state_family,
        first_session,
        final_session,
        columns=("session", "instrument_id", "state"),
    ):
        for row in batch.to_pylist():
            position = _flat_position(row, session_index, compact_index, len(selected_ids))
            if position is not None:
                trading_states[position] = (
                    2 if row["state"] == "full_session_suspension" else 1
                )

    upper_limits = array("d", [MISSING]) * cell_count
    lower_limits = array("d", [MISSING]) * cell_count
    limit_family = FAMILY_BY_TABLE["price_limits"]
    for batch in _window_batches(
        objects,
        entries,
        limit_family,
        first_session,
        final_session,
        columns=("session", "instrument_id", "upper", "lower"),
    ):
        for row in batch.to_pylist():
            position = _flat_position(row, session_index, compact_index, len(selected_ids))
            if position is not None:
                upper_limits[position] = float(row["upper"])
                lower_limits[position] = float(row["lower"])

    st_designations = bytearray(cell_count)
    st_family = FAMILY_BY_TABLE["st_designations"]
    for batch in _window_batches(
        objects,
        entries,
        st_family,
        first_session,
        final_session,
        columns=("trade_date", "instrument_id"),
    ):
        for row in batch.to_pylist():
            session_position = session_index.get(str(row["trade_date"]))
            instrument_position = compact_index.get(str(row["instrument_id"]))
            if session_position is not None and instrument_position is not None:
                st_designations[
                    session_position * len(selected_ids) + instrument_position
                ] = 1

    industry_rows: dict[str, list[dict[str, object]]] = {}
    for row in _read_static_rows(objects, entries, "industry_membership"):
        instrument_id = str(row["instrument_id"])
        if instrument_id in compact_index:
            industry_rows.setdefault(instrument_id, []).append(row)
    industry_membership = {
        instrument_id: tuple(
            sorted(rows, key=lambda row: str(row["active_from"]))
        )
        for instrument_id, rows in industry_rows.items()
    }
    return ColumnarResearchWindow(
        sessions=sessions,
        instrument_ids=selected_ids,
        instruments={value: instrument_reference[value] for value in selected_ids},
        universe_name=universe_name,
        universe_membership=universe_membership,
        price_fields=price_fields,
        trading_states=trading_states,
        upper_limits=upper_limits,
        lower_limits=lower_limits,
        st_designations=st_designations,
        industry_membership=industry_membership,
    )


def calculate_bounded_research(
    window: ColumnarResearchWindow,
    definition: dict[str, object],
) -> dict[str, dict[str, object]]:
    matrix, alpha_values = _calculate_alpha(window, definition)
    window.discard_alpha_only_fields()
    labels, factor = _calculate_labels_and_factor(window, matrix, alpha_values)
    strategy = run_strategy(window.strategy_canonical(), matrix, definition)
    return {
        "alpha_matrix": matrix,
        "forward_labels": labels,
        "factor_evaluation": factor,
        "strategy_backtest": strategy,
        "strategy_time_series": {"daily": strategy["daily"]},
        "strategy_events": {
            "orders": strategy["orders"],
            "child_orders": strategy["child_orders"],
            "fills": strategy["fills"],
            "rebalance_events": strategy["rebalance_events"],
            "rejections": strategy["rejections"],
        },
        "diagnostics": {
            "alpha_coverage": [
                {
                    "session": item["session"],
                    "coverage_loss": item["coverage_loss"],
                }
                for item in matrix["sessions"]
            ],
            "strategy": strategy["diagnostics"],
        },
    }


def _calculate_alpha(
    window: ColumnarResearchWindow,
    definition: Mapping[str, object],
) -> tuple[dict[str, object], AlphaValueStore]:
    alpha = _mapping(definition.get("alpha"), "Alpha definition")
    expression = str(alpha["expression"])
    parsed = validate_alpha(expression)
    neutralization = str(definition["neutralization"])
    if neutralization not in {"none", "industry"}:
        raise BoundedResearchError("neutralization must be none or industry")
    cell_count = len(window.sessions) * window.instrument_count
    values = array("d", [MISSING]) * cell_count
    for instrument_index in range(window.instrument_count):
        inputs: dict[str, list[float | None]] = {}
        for field in parsed.field_names:
            source = window.price_fields[PRICE_FIELD_BY_ALPHA_FIELD[field]]
            series = [
                source[session_index * window.instrument_count + instrument_index]
                for session_index in range(len(window.sessions))
            ]
            inputs[field] = [None if math.isnan(value) else value for value in series]
        evaluated = evaluate_parsed_series(
            parsed,
            inputs,
            length=len(window.sessions),
        )
        for session_index, value in enumerate(evaluated):
            if value is not None:
                values[
                    session_index * window.instrument_count + instrument_index
                ] = value

    checksum = hashlib.sha256()
    coverage_rows: list[dict[str, object]] = []
    for session_index, session in enumerate(window.sessions):
        offset = session_index * window.instrument_count
        coverage: Counter[str] = Counter()
        eligible: list[int] = []
        for instrument_index in window.universe_membership[session]:
            position = offset + instrument_index
            if window.st_designations[position]:
                coverage["st_excluded"] += 1
                values[position] = MISSING
            elif math.isnan(values[position]):
                coverage["missing_expression"] += 1
            else:
                eligible.append(instrument_index)
        if neutralization == "industry":
            grouped: dict[str, list[int]] = {}
            for instrument_index in eligible:
                instrument_id = window.instrument_ids[instrument_index]
                industry = _resolve_industry(
                    window.industry_membership,
                    instrument_id,
                    session,
                )
                if industry is None:
                    coverage["missing_industry"] += 1
                    values[offset + instrument_index] = MISSING
                    continue
                grouped.setdefault(industry, []).append(instrument_index)
            eligible = []
            for indexes in grouped.values():
                if len(indexes) < 2:
                    coverage["industry_group_too_small"] += len(indexes)
                    for instrument_index in indexes:
                        values[offset + instrument_index] = MISSING
                    continue
                mean = math.fsum(values[offset + index] for index in indexes) / len(indexes)
                for instrument_index in indexes:
                    values[offset + instrument_index] -= mean
                    eligible.append(instrument_index)
        checksum.update(session.encode())
        checksum.update(b"\0")
        for instrument_index in sorted(
            eligible,
            key=lambda index: window.instrument_ids[index],
        ):
            checksum.update(window.instrument_ids[instrument_index].encode())
            checksum.update(b"\0")
            checksum.update(canonical_binary64_bytes(values[offset + instrument_index]))
        coverage_rows.append(
            {
                "session": session,
                "coverage_loss": dict(sorted(coverage.items())),
            }
        )
    store = AlphaValueStore(window, values)
    matrix = {
        "expression": expression,
        "effective_lookback": parsed.effective_lookback,
        "neutralization": neutralization,
        "sessions": coverage_rows,
        "checksum": checksum.hexdigest(),
        "value_store": store,
    }
    return matrix, store


def _calculate_labels_and_factor(
    window: ColumnarResearchWindow,
    matrix: Mapping[str, object],
    alpha_values: AlphaValueStore,
) -> tuple[dict[str, object], dict[str, object]]:
    prices = PriceLookup(window)
    states = StateLookup(window)
    signal_sessions = window.sessions[-REPORT_SESSIONS:]
    alpha_checksum = str(matrix["checksum"])
    label_horizons: dict[str, object] = {}
    factor_horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        label_checksum = hashlib.sha256()
        label_checksum.update(f'{{"horizon":{horizon},"sessions":['.encode())
        daily: list[dict[str, object]] = []
        for signal_offset, signal_session in enumerate(signal_sessions):
            signal_index = len(window.sessions) - REPORT_SESSIONS + signal_offset
            session_alpha = alpha_values[signal_session]
            samples: list[dict[str, object]] = []
            resolutions: list[dict[str, object]] = []
            unavailable: Counter[str] = Counter()
            entry_index = signal_index + 1
            exit_index = entry_index + horizon
            for alpha in session_alpha:
                instrument_id = str(alpha["instrument_id"])
                alpha_value = float(alpha["value"])
                if exit_index >= len(window.sessions):
                    reason = "right_censored_by_release_end"
                    unavailable[reason] += 1
                    resolutions.append(
                        {
                            "instrument_id": instrument_id,
                            "alpha": alpha_value,
                            "label": None,
                            "reason": reason,
                        }
                    )
                    continue
                entry_session = window.sessions[entry_index]
                exit_session = window.sessions[exit_index]
                entry = prices.get((entry_session, instrument_id))
                if entry is None:
                    reason = _unavailable_reason(
                        states.get((entry_session, instrument_id)),
                        window.instruments[instrument_id],
                        entry_session,
                        valid_entry=False,
                    )
                    if reason == "unexplained_missing_or_invalid_data":
                        raise BoundedResearchError(
                            f"unexplained Label entry Open for {instrument_id} on {entry_session}"
                        )
                    unavailable[reason] += 1
                    resolutions.append(
                        {
                            "instrument_id": instrument_id,
                            "alpha": alpha_value,
                            "label": None,
                            "reason": reason,
                        }
                    )
                    continue
                exit_price = prices.get((exit_session, instrument_id))
                if exit_price is None:
                    reason = _unavailable_reason(
                        states.get((exit_session, instrument_id)),
                        window.instruments[instrument_id],
                        exit_session,
                        valid_entry=True,
                    )
                    if reason == "terminal_delisting":
                        label = -1.0
                    else:
                        if reason == "unexplained_missing_or_invalid_data":
                            raise BoundedResearchError(
                                f"unexplained Label exit Open for {instrument_id} on {exit_session}"
                            )
                        unavailable[reason] += 1
                        resolutions.append(
                            {
                                "instrument_id": instrument_id,
                                "alpha": alpha_value,
                                "label": None,
                                "reason": reason,
                            }
                        )
                        continue
                else:
                    entry_open = float(entry["open_adj"])
                    exit_open = float(exit_price["open_adj"])
                    if entry_open == 0.0:
                        raise BoundedResearchError(
                            f"invalid Label entry Open for {instrument_id} on {entry_session}"
                        )
                    label = exit_open / entry_open - 1.0
                    if not math.isfinite(label):
                        raise BoundedResearchError(
                            f"non-finite Label for {instrument_id} on {signal_session}"
                        )
                resolution = {
                    "instrument_id": instrument_id,
                    "alpha": alpha_value,
                    "label": label,
                    "reason": None,
                }
                resolutions.append(resolution)
                samples.append(
                    {key: resolution[key] for key in ("instrument_id", "alpha", "label")}
                )
            session_payload = {
                "session": signal_session,
                "signal_session": signal_session,
                "alpha_values": session_alpha,
                "samples": samples,
                "resolutions": resolutions,
                "unavailable": dict(sorted(unavailable.items())),
            }
            if signal_offset:
                label_checksum.update(b",")
            label_checksum.update(canonical_json_bytes(session_payload))
            daily.append(
                {
                    "session": signal_session,
                    "sample_count": len(samples),
                    **factor_day(samples),
                }
            )
        label_checksum.update(b"]}")
        label_digest = label_checksum.hexdigest()
        summary = _factor_summary(daily)
        factor_payload = {
            "horizon": horizon,
            "alpha_checksum": alpha_checksum,
            "label_checksum": label_digest,
            "daily": daily,
            "summary": summary,
        }
        factor_horizons[str(horizon)] = {
            **factor_payload,
            "checksum": hashlib.sha256(
                canonical_json_bytes(factor_payload)
            ).hexdigest(),
        }
        label_horizons[str(horizon)] = {
            "horizon": horizon,
            "checksum": label_digest,
        }
    return (
        {
            "alpha_checksum": alpha_checksum,
            "report_session_count": len(signal_sessions),
            "horizons": label_horizons,
        },
        {"horizons": factor_horizons},
    )


def _factor_summary(daily: list[dict[str, object]]) -> dict[str, object]:
    return {
        "ic": correlation_summary(daily, "ic"),
        "rank_ic": correlation_summary(daily, "rank_ic"),
        "quantile_returns": {
            name: mean_or_none(
                [
                    float(day["quantile_returns"][name])
                    for day in daily
                    if day["quantile_returns"][name] is not None
                ]
            )
            for name in ("q1", "q2", "q3", "q4", "q5")
        },
        "top_bottom_return": mean_or_none(
            [
                float(day["top_bottom_return"])
                for day in daily
                if day["top_bottom_return"] is not None
            ]
        ),
    }


def _unavailable_reason(
    trading_state: str | None,
    instrument: Mapping[str, object],
    session: str,
    *,
    valid_entry: bool,
) -> str:
    listed_to = str(instrument.get("listed_to", ""))
    if listed_to and listed_to <= session:
        return "terminal_delisting" if valid_entry else "confirmed_market_open_unavailable"
    if trading_state == "full_session_suspension":
        return "confirmed_market_open_unavailable"
    return "unexplained_missing_or_invalid_data"


def _resolve_industry(
    memberships: Mapping[str, Sequence[Mapping[str, object]]],
    instrument_id: str,
    session: str,
) -> str | None:
    for item in memberships.get(instrument_id, ()):
        active_to = str(item.get("active_to", ""))
        if str(item["active_from"]) <= session and (
            not active_to or session < active_to
        ):
            value = str(item.get("sw2021_l1", ""))
            return value or None
    return None


def _flat_position(
    row: Mapping[str, object],
    session_index: Mapping[str, int],
    instrument_index: Mapping[str, int],
    instrument_count: int,
) -> int | None:
    session = str(row.get("session") or row.get("trade_date"))
    session_position = session_index.get(session)
    instrument_position = instrument_index.get(str(row["instrument_id"]))
    if session_position is None or instrument_position is None:
        return None
    return session_position * instrument_count + instrument_position


def _read_static_rows(
    objects: ObjectStorePort,
    entries: Sequence[Mapping[str, object]],
    table_name: str,
) -> list[dict[str, object]]:
    family = FAMILY_BY_TABLE[table_name]
    rows: list[dict[str, object]] = []
    for batch in _window_batches(
        objects,
        entries,
        family,
        None,
        None,
        columns=tuple(family.schema.names),
    ):
        rows.extend(batch.to_pylist())
    return rows


def _window_batches(
    objects: ObjectStorePort,
    entries: Sequence[Mapping[str, object]],
    family: CanonicalFamily,
    first_session: str | None,
    final_session: str | None,
    *,
    columns: Sequence[str],
) -> Iterator[pa.RecordBatch]:
    for entry in sort_partition_entries(entries):
        if entry.get("family") != family.family:
            continue
        validate_partition_entry(entry, family)
        if not partition_overlaps_window(
            entry,
            family,
            first_session=first_session,
            final_session=final_session,
        ):
            continue
        payload = objects.read_parquet_bytes(str(entry["sha256"]))
        parquet = pq.ParquetFile(pa.BufferReader(payload))
        if not parquet.schema_arrow.equals(family.schema, check_metadata=True):
            raise BoundedResearchError(
                f"Canonical partition schema mismatch: {family.family}"
            )
        if parquet.metadata.num_row_groups != 1:
            raise BoundedResearchError(
                f"Canonical partition row-group mismatch: {family.family}"
            )
        yield from parquet.iter_batches(batch_size=8192, columns=list(columns))


def _mapping(value: Any, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BoundedResearchError(f"{name} is invalid")
    return value

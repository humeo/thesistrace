import hashlib
import math
from collections import Counter
from collections.abc import Callable, Sequence
from statistics import stdev

import numpy as np

from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_series import (
    AlignedResearchData,
    ColumnarResearchSeries,
    InstrumentProfile,
)

HORIZONS = (1, 5, 20)


class FactorDataError(RuntimeError):
    pass


def affected_label_sessions(
    calendar: Sequence[str],
    new_sessions: Sequence[str],
    horizon: int,
) -> list[str]:
    """Select new signals and prior signals whose exit matures in this delta."""
    affected = {str(session) for session in new_sessions}
    for session in new_sessions:
        signal_index = calendar.index(str(session)) - horizon - 1
        if signal_index >= 0:
            affected.add(str(calendar[signal_index]))
    return [str(session) for session in calendar if str(session) in affected]


def build_forward_labels(
    research_data: AlignedResearchData,
    alpha_matrix: dict[str, object],
    *,
    signal_sessions: Sequence[str],
    horizons: Sequence[int] = HORIZONS,
    cancellation_check: Callable[[], None] | None = None,
) -> dict[str, object]:
    calendar = list(research_data.sessions)
    prices = research_data.execution_prices
    states = research_data.trading_states
    instruments = research_data.instruments
    alpha_by_session = {str(item["session"]): item for item in alpha_matrix["sessions"]}
    selected_sessions = [str(session) for session in signal_sessions]
    horizon_results: dict[str, object] = {}
    for horizon in horizons:
        sessions: list[dict[str, object]] = []
        for signal_session in selected_sessions:
            if cancellation_check is not None:
                cancellation_check()
            signal_index = calendar.index(signal_session)
            alpha_values = list(alpha_by_session[signal_session]["values"])
            samples: list[dict[str, object]] = []
            resolutions: list[dict[str, object]] = []
            unavailable: Counter[str] = Counter()
            entry_index = signal_index + 1
            exit_index = signal_index + 1 + horizon
            for alpha in alpha_values:
                instrument_id = str(alpha["instrument_id"])
                if exit_index >= len(calendar):
                    reason = "right_censored_by_research_period_end"
                    unavailable[reason] += 1
                    resolutions.append(
                        {
                            "instrument_id": instrument_id,
                            "alpha": float(alpha["value"]),
                            "label": None,
                            "reason": reason,
                        }
                    )
                    continue
                entry_session = calendar[entry_index]
                exit_session = calendar[exit_index]
                entry = prices.get((entry_session, instrument_id))
                if entry is None:
                    reason = unavailable_reason(
                        states.get((entry_session, instrument_id)),
                        instruments[instrument_id],
                        entry_session,
                        valid_entry=False,
                    )
                    if reason == "unexplained_missing_or_invalid_data":
                        raise FactorDataError(
                            f"unexplained Label entry Open for {instrument_id} on {entry_session}"
                        )
                    unavailable[reason] += 1
                    resolutions.append(
                        {
                            "instrument_id": instrument_id,
                            "alpha": float(alpha["value"]),
                            "label": None,
                            "reason": reason,
                        }
                    )
                    continue
                exit_price = prices.get((exit_session, instrument_id))
                if exit_price is None:
                    reason = unavailable_reason(
                        states.get((exit_session, instrument_id)),
                        instruments[instrument_id],
                        exit_session,
                        valid_entry=True,
                    )
                    if reason == "terminal_delisting":
                        label = -1.0
                    else:
                        if reason == "unexplained_missing_or_invalid_data":
                            raise FactorDataError(
                                f"unexplained Label exit Open for {instrument_id} on {exit_session}"
                            )
                        unavailable[reason] += 1
                        resolutions.append(
                            {
                                "instrument_id": instrument_id,
                                "alpha": float(alpha["value"]),
                                "label": None,
                                "reason": reason,
                            }
                        )
                        continue
                else:
                    entry_open = float(entry.adjusted_open)
                    exit_open = float(exit_price.adjusted_open)
                    if entry_open == 0.0:
                        raise FactorDataError(
                            f"invalid Label entry Open for {instrument_id} on {entry_session}"
                        )
                    label = exit_open / entry_open - 1.0
                    if not math.isfinite(label):
                        raise FactorDataError(
                            f"non-finite Label for {instrument_id} on {signal_session}"
                        )
                resolution = {
                    "instrument_id": instrument_id,
                    "alpha": float(alpha["value"]),
                    "label": label,
                    "reason": None,
                }
                resolutions.append(resolution)
                samples.append(
                    {key: resolution[key] for key in ("instrument_id", "alpha", "label")}
                )
            samples.sort(key=lambda row: str(row["instrument_id"]))
            resolutions.sort(key=lambda row: str(row["instrument_id"]))
            sessions.append(
                {
                    "session": signal_session,
                    "signal_session": signal_session,
                    "alpha_values": alpha_values,
                    "samples": samples,
                    "resolutions": resolutions,
                    "unavailable": dict(sorted(unavailable.items())),
                }
            )
            if cancellation_check is not None:
                cancellation_check()
        horizon_payload = {"horizon": horizon, "sessions": sessions}
        horizon_results[str(horizon)] = {
            **horizon_payload,
            "checksum": hashlib.sha256(canonical_json_bytes(horizon_payload)).hexdigest(),
        }
    return {
        "alpha_checksum": alpha_matrix["checksum"],
        "report_session_count": len(selected_sessions),
        "horizons": horizon_results,
    }


def unavailable_reason(
    trading_state: str | None,
    instrument: InstrumentProfile,
    session: str,
    *,
    valid_entry: bool,
) -> str:
    listed_to = instrument.listed_to
    if listed_to and listed_to <= session:
        return "terminal_delisting" if valid_entry else "confirmed_market_open_unavailable"
    if trading_state == "full_session_suspension":
        return "confirmed_market_open_unavailable"
    if trading_state == "data_unavailable":
        return "data_unavailable"
    return "unexplained_missing_or_invalid_data"


def columnar_forward_factor_days_by_horizon(
    research_data: ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    *,
    signal_sessions_by_horizon: dict[int, Sequence[str]],
    cancellation_check: Callable[[], None],
) -> dict[str, list[dict[str, object]]]:
    calendar = tuple(research_data.sessions)
    session_positions = {session: index for index, session in enumerate(calendar)}
    instruments = tuple(
        sorted(
            {
                str(value["instrument_id"])
                for item in alpha_matrix["sessions"]
                for value in item["values"]
            }
        )
    )
    instrument_positions = {
        instrument_id: index for index, instrument_id in enumerate(instruments)
    }
    adjusted_opens = research_data.adjusted_open_matrix(instruments)
    alpha_by_session = {
        str(item["session"]): item for item in alpha_matrix["sessions"]
    }
    alpha_coordinates: dict[str, tuple[tuple[str, ...], np.ndarray, np.ndarray]] = {}
    days_by_horizon: dict[str, list[dict[str, object]]] = {}
    for horizon, signal_sessions in signal_sessions_by_horizon.items():
        days: list[dict[str, object]] = []
        for signal_session in signal_sessions:
            cancellation_check()
            signal_session = str(signal_session)
            signal_index = session_positions[signal_session]
            alpha_values = list(alpha_by_session[signal_session]["values"])
            coordinates = alpha_coordinates.get(signal_session)
            if coordinates is None:
                instrument_ids = tuple(str(value["instrument_id"]) for value in alpha_values)
                positions = np.fromiter(
                    (instrument_positions[instrument_id] for instrument_id in instrument_ids),
                    dtype=np.intp,
                    count=len(instrument_ids),
                )
                alpha_array = np.fromiter(
                    (float(value["value"]) for value in alpha_values),
                    dtype=np.float64,
                    count=len(alpha_values),
                )
                coordinates = (instrument_ids, positions, alpha_array)
                alpha_coordinates[signal_session] = coordinates
            instrument_ids, positions, alpha_array = coordinates
            entry_index = signal_index + 1
            exit_index = signal_index + 1 + horizon
            included_alpha = np.asarray([], dtype=np.float64)
            selected_labels = np.asarray([], dtype=np.float64)
            if exit_index < len(calendar) and alpha_values:
                entry_session = calendar[entry_index]
                exit_session = calendar[exit_index]
                entry_opens = adjusted_opens[positions, entry_index]
                exit_opens = adjusted_opens[positions, exit_index]
                valid_entry = np.isfinite(entry_opens)
                valid_exit = np.isfinite(exit_opens)
                zero_entry = valid_entry & (entry_opens == 0.0)
                if np.any(zero_entry):
                    instrument_id = instrument_ids[int(np.flatnonzero(zero_entry)[0])]
                    raise FactorDataError(
                        f"invalid Label entry Open for {instrument_id} on {entry_session}"
                    )
                included = valid_entry & valid_exit
                label_array = np.empty(len(alpha_values), dtype=np.float64)
                label_array[included] = (
                    exit_opens[included] / entry_opens[included] - 1.0
                )
                for index in np.flatnonzero(~valid_entry):
                    instrument_id = instrument_ids[int(index)]
                    reason = unavailable_reason(
                        research_data.trading_states.get((entry_session, instrument_id)),
                        research_data.instruments[instrument_id],
                        entry_session,
                        valid_entry=False,
                    )
                    if reason == "unexplained_missing_or_invalid_data":
                        raise FactorDataError(
                            f"unexplained Label entry Open for {instrument_id} on {entry_session}"
                        )
                for index in np.flatnonzero(valid_entry & ~valid_exit):
                    instrument_id = instrument_ids[int(index)]
                    reason = unavailable_reason(
                        research_data.trading_states.get((exit_session, instrument_id)),
                        research_data.instruments[instrument_id],
                        exit_session,
                        valid_entry=True,
                    )
                    if reason == "terminal_delisting":
                        label_array[index] = -1.0
                        included[index] = True
                    elif reason == "unexplained_missing_or_invalid_data":
                        raise FactorDataError(
                            f"unexplained Label exit Open for {instrument_id} on {exit_session}"
                        )
                selected_labels = label_array[included]
                if not np.all(np.isfinite(selected_labels)):
                    index = int(np.flatnonzero(included & ~np.isfinite(label_array))[0])
                    raise FactorDataError(
                        f"non-finite Label for {instrument_ids[index]} on {signal_session}"
                    )
                included_alpha = alpha_array[included]
            days.append(
                {
                    "session": signal_session,
                    "sample_count": len(included_alpha),
                    **_factor_array_values(included_alpha, selected_labels),
                }
            )
            cancellation_check()
        days_by_horizon[str(horizon)] = days
    return days_by_horizon


def evaluate_factor(labels: dict[str, object]) -> dict[str, object]:
    horizons: dict[str, object] = {}
    for horizon, label_artifact in labels["horizons"].items():
        daily: list[dict[str, object]] = []
        for item in label_artifact["sessions"]:
            metrics = factor_day(item["samples"])
            daily.append(
                {
                    "session": item["session"],
                    "sample_count": len(item["samples"]),
                    **metrics,
                }
            )
        horizons[horizon] = factor_horizon_from_daily(
            horizon=int(horizon),
            alpha_checksum=str(labels["alpha_checksum"]),
            label_checksum=str(label_artifact["checksum"]),
            daily=daily,
        )
    return {"horizons": horizons}


def factor_horizon_from_daily(
    *,
    horizon: int,
    alpha_checksum: str,
    label_checksum: str,
    daily: list[dict[str, object]],
) -> dict[str, object]:
    summary = {
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
    payload = {
        "horizon": horizon,
        "alpha_checksum": alpha_checksum,
        "label_checksum": label_checksum,
        "daily": daily,
        "summary": summary,
    }
    return {
        **payload,
        "checksum": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def factor_day(samples: list[dict[str, object]]) -> dict[str, object]:
    return factor_values(
        [float(item["alpha"]) for item in samples],
        [float(item["label"]) for item in samples],
    )


def factor_values(alpha: list[float], label: list[float]) -> dict[str, object]:
    if len(alpha) != len(label):
        raise FactorDataError("Factor sample coordinates are misaligned")
    return _factor_array_values(
        np.asarray(alpha, dtype=np.float64),
        np.asarray(label, dtype=np.float64),
    )


def _factor_array_values(
    alpha: np.ndarray,
    label: np.ndarray,
) -> dict[str, object]:
    if len(alpha) != len(label):
        raise FactorDataError("Factor sample coordinates are misaligned")
    if len(alpha) < 30:
        return {
            "ic": None,
            "rank_ic": None,
            "correlation_reason": "sample_insufficient",
            "quantile_returns": empty_quantiles(),
            "top_bottom_return": None,
            "quantile_reason": "sample_insufficient",
        }
    ic = _pearson_arrays(alpha, label)
    alpha_ranks = _average_ranks_array(alpha)
    rank_ic = _pearson_arrays(alpha_ranks, _average_ranks_array(label))
    reason = "constant_array" if ic is None or rank_ic is None else None

    count = len(alpha)
    groups = np.minimum(5, ((alpha_ranks - 1) * 5 / count).astype(np.int8) + 1)
    quantiles = {
        f"q{group}": mean_or_none(label[groups == group].tolist())
        for group in range(1, 6)
    }
    top_bottom = (
        None
        if quantiles["q1"] is None or quantiles["q5"] is None
        else quantiles["q5"] - quantiles["q1"]
    )
    return {
        "ic": ic,
        "rank_ic": rank_ic,
        "correlation_reason": reason,
        "quantile_returns": quantiles,
        "top_bottom_return": top_bottom,
        "quantile_reason": None,
    }


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    return _pearson_arrays(
        np.asarray(left, dtype=np.float64),
        np.asarray(right, dtype=np.float64),
    )


def _pearson_arrays(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) != len(right) or len(left) == 0:
        return None
    left_mean = math.fsum(left.tolist()) / len(left)
    right_mean = math.fsum(right.tolist()) / len(right)
    left_centered = left - left_mean
    right_centered = right - right_mean
    left_sum = math.fsum(np.square(left_centered).tolist())
    right_sum = math.fsum(np.square(right_centered).tolist())
    if left_sum == 0.0 or right_sum == 0.0:
        return None
    result = math.fsum(np.multiply(left_centered, right_centered).tolist()) / math.sqrt(
        left_sum * right_sum
    )
    return result if math.isfinite(result) else None


def average_ranks(values: list[float]) -> list[float]:
    return _average_ranks_array(np.asarray(values, dtype=np.float64)).tolist()


def _average_ranks_array(array: np.ndarray) -> np.ndarray:
    if not np.all(np.isfinite(array)):
        raise FactorDataError("Factor rank values must be finite")
    order = np.argsort(array, kind="stable")
    ordered = array[order]
    starts = np.flatnonzero(
        np.concatenate((np.asarray([True]), ordered[1:] != ordered[:-1]))
    )
    ends = np.concatenate((starts[1:], np.asarray([len(array)])))
    group_ranks = (starts + 1 + ends) / 2
    sorted_ranks = np.repeat(group_ranks, ends - starts)
    ranks = np.empty(len(array), dtype=np.float64)
    ranks[order] = sorted_ranks
    return ranks


def correlation_summary(daily: list[dict[str, object]], field: str) -> dict[str, object]:
    values = [float(day[field]) for day in daily if day[field] is not None]
    mean = mean_or_none(values)
    sample_deviation = stdev(values) if len(values) >= 2 else None
    return {
        "mean": mean,
        "sample_deviation": sample_deviation,
        "icir": (
            None if mean is None or sample_deviation in {None, 0.0} else mean / sample_deviation
        ),
        "positive_fraction": (
            None if not values else sum(value > 0.0 for value in values) / len(values)
        ),
        "valid_session_count": len(values),
    }


def mean_or_none(values: list[float]) -> float | None:
    return None if not values else math.fsum(values) / len(values)


def empty_quantiles() -> dict[str, None]:
    return {f"q{group}": None for group in range(1, 6)}

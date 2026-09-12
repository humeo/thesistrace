import hashlib
import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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


_LABEL_UNAVAILABLE = np.uint8(1)
_LABEL_INVALID_ZERO_ENTRY = np.uint8(2)
_LABEL_INVALID_ENTRY = np.uint8(3)
_LABEL_INVALID_EXIT = np.uint8(4)
_LABEL_INVALID_NON_FINITE = np.uint8(5)
_LABEL_CENSORED = np.uint8(6)
_LABEL_DATA_UNAVAILABLE = np.uint8(7)


@dataclass(frozen=True)
class PreparedColumnarForwardLabels:
    sessions: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    labels_by_horizon: dict[int, np.ndarray]
    states_by_horizon: dict[int, np.ndarray]

    def factor_days_by_horizon(
        self,
        alpha_matrix: dict[str, object],
        *,
        signal_sessions_by_horizon: dict[int, Sequence[str]],
        cancellation_check: Callable[[], None],
    ) -> dict[str, list[dict[str, object]]]:
        session_positions = {session: index for index, session in enumerate(self.sessions)}
        instrument_positions = {
            instrument_id: index for index, instrument_id in enumerate(self.instrument_ids)
        }
        alpha_by_session = {str(item["session"]): item for item in alpha_matrix["sessions"]}
        days_by_horizon: dict[str, list[dict[str, object]]] = {}
        for horizon, signal_sessions in signal_sessions_by_horizon.items():
            labels = self.labels_by_horizon[horizon]
            states = self.states_by_horizon[horizon]
            days: list[dict[str, object]] = []
            for signal_session in signal_sessions:
                cancellation_check()
                signal_session = str(signal_session)
                signal_index = session_positions[signal_session]
                alpha_values = list(alpha_by_session[signal_session]["values"])
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
                selected_states = states[positions, signal_index]
                _raise_selected_label_error(
                    selected_states,
                    instrument_ids=instrument_ids,
                    signal_session=signal_session,
                    entry_session=(
                        self.sessions[signal_index + 1]
                        if signal_index + 1 < len(self.sessions)
                        else signal_session
                    ),
                    exit_session=(
                        self.sessions[signal_index + 1 + horizon]
                        if signal_index + 1 + horizon < len(self.sessions)
                        else signal_session
                    ),
                )
                included = selected_states == 0
                selected_labels = labels[positions, signal_index][included]
                included_alpha = alpha_array[included]
                days.append(
                    _factor_observation(
                        session=signal_session,
                        horizon=horizon,
                        entry_session=(
                            self.sessions[signal_index + 1]
                            if signal_index + 1 < len(self.sessions)
                            else None
                        ),
                        exit_session=(
                            self.sessions[signal_index + 1 + horizon]
                            if signal_index + 1 + horizon < len(self.sessions)
                            else None
                        ),
                        alpha_count=len(alpha_values),
                        alpha_exclusions=dict(
                            alpha_by_session[signal_session]["coverage_loss"]
                        ),
                        label_exclusions={
                            reason: int(np.count_nonzero(selected_states == code))
                            for code, reason in (
                                (_LABEL_UNAVAILABLE, "confirmed_market_open_unavailable"),
                                (_LABEL_CENSORED, "right_censored_by_research_period_end"),
                                (_LABEL_DATA_UNAVAILABLE, "data_unavailable"),
                            )
                            if np.any(selected_states == code)
                        },
                        sample_count=len(included_alpha),
                        metrics=_factor_array_values(included_alpha, selected_labels),
                    )
                )
                cancellation_check()
            days_by_horizon[str(horizon)] = days
        return days_by_horizon


def prepare_columnar_forward_labels(
    research_data: ColumnarResearchSeries,
    *,
    cancellation_check: Callable[[], None],
) -> PreparedColumnarForwardLabels:
    sessions = tuple(research_data.sessions)
    instrument_ids = tuple(sorted(research_data.instruments))
    adjusted_opens = research_data.adjusted_open_matrix(instrument_ids)
    finite = np.isfinite(adjusted_opens)
    # Classify each missing coordinate once, across all horizons. A terminal
    # delisting is unavailable on entry, but a total loss after a valid entry.
    missing_reason = np.zeros(adjusted_opens.shape, dtype=np.uint8)
    terminal_delisting, unexplained, data_unavailable = 1, 2, 3
    for index, session in enumerate(sessions):
        cancellation_check()
        for position in np.flatnonzero(~finite[:, index]):
            instrument_id = instrument_ids[int(position)]
            reason = unavailable_reason(
                research_data.trading_states.get((session, instrument_id)),
                research_data.instruments[instrument_id],
                session,
                valid_entry=True,
            )
            if reason == "terminal_delisting":
                missing_reason[position, index] = terminal_delisting
            elif reason == "unexplained_missing_or_invalid_data":
                missing_reason[position, index] = unexplained
            elif reason == "data_unavailable":
                missing_reason[position, index] = data_unavailable
    labels_by_horizon: dict[int, np.ndarray] = {}
    states_by_horizon: dict[int, np.ndarray] = {}
    for horizon in HORIZONS:
        cancellation_check()
        labels = np.full(adjusted_opens.shape, np.nan, dtype=np.float64)
        states = np.full(adjusted_opens.shape, _LABEL_CENSORED, dtype=np.uint8)
        width = max(0, len(sessions) - horizon - 1)
        entry_opens = adjusted_opens[:, 1 : 1 + width]
        exit_opens = adjusted_opens[:, 1 + horizon : 1 + horizon + width]
        valid_entry = finite[:, 1 : 1 + width]
        valid_exit = finite[:, 1 + horizon : 1 + horizon + width]
        entry_reason = missing_reason[:, 1 : 1 + width]
        exit_reason = missing_reason[:, 1 + horizon : 1 + horizon + width]
        projected_labels = labels[:, :width]
        projected_states = states[:, :width]
        projected_states[:] = _LABEL_UNAVAILABLE
        zero_entry = valid_entry & (entry_opens == 0.0)
        projected_states[zero_entry] = _LABEL_INVALID_ZERO_ENTRY
        valid = valid_entry & valid_exit & ~zero_entry
        projected_labels[valid] = exit_opens[valid] / entry_opens[valid] - 1.0
        projected_states[valid] = 0
        projected_states[~valid_entry & (entry_reason == data_unavailable)] = (
            _LABEL_DATA_UNAVAILABLE
        )
        projected_states[~valid_entry & (entry_reason == unexplained)] = _LABEL_INVALID_ENTRY
        missing_exit = valid_entry & ~valid_exit & ~zero_entry
        terminal = missing_exit & (exit_reason == terminal_delisting)
        projected_labels[terminal] = -1.0
        projected_states[terminal] = 0
        projected_states[missing_exit & (exit_reason == data_unavailable)] = _LABEL_DATA_UNAVAILABLE
        projected_states[missing_exit & (exit_reason == unexplained)] = _LABEL_INVALID_EXIT
        non_finite = (projected_states == 0) & ~np.isfinite(projected_labels)
        projected_states[non_finite] = _LABEL_INVALID_NON_FINITE
        labels_by_horizon[horizon] = labels
        states_by_horizon[horizon] = states
    cancellation_check()
    return PreparedColumnarForwardLabels(
        sessions=sessions,
        instrument_ids=instrument_ids,
        labels_by_horizon=labels_by_horizon,
        states_by_horizon=states_by_horizon,
    )


def _raise_selected_label_error(
    states: np.ndarray,
    *,
    instrument_ids: tuple[str, ...],
    signal_session: str,
    entry_session: str,
    exit_session: str,
) -> None:
    for code, message in (
        (_LABEL_INVALID_ZERO_ENTRY, "invalid Label entry Open"),
        (_LABEL_INVALID_ENTRY, "unexplained Label entry Open"),
        (_LABEL_INVALID_EXIT, "unexplained Label exit Open"),
        (_LABEL_INVALID_NON_FINITE, "non-finite Label"),
    ):
        selected = np.flatnonzero(states == code)
        if not len(selected):
            continue
        instrument_id = instrument_ids[int(selected[0])]
        session = (
            entry_session
            if code in {_LABEL_INVALID_ZERO_ENTRY, _LABEL_INVALID_ENTRY}
            else exit_session
            if code == _LABEL_INVALID_EXIT
            else signal_session
        )
        raise FactorDataError(f"{message} for {instrument_id} on {session}")


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
                entry_open = float(entry.adjusted_open)
                if entry_open == 0.0:
                    raise FactorDataError(
                        f"invalid Label entry Open for {instrument_id} on {entry_session}"
                    )
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
                    exit_open = float(exit_price.adjusted_open)
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
                    "alpha_coverage_loss": dict(
                        alpha_by_session[signal_session]["coverage_loss"]
                    ),
                    "entry_session": calendar[entry_index] if entry_index < len(calendar) else None,
                    "exit_session": calendar[exit_index] if exit_index < len(calendar) else None,
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


def prepared_forward_factor_days_by_horizon(
    forward_labels: PreparedColumnarForwardLabels,
    alpha_matrix: dict[str, object],
    *,
    signal_sessions_by_horizon: dict[int, Sequence[str]],
    cancellation_check: Callable[[], None],
) -> dict[str, list[dict[str, object]]]:
    return forward_labels.factor_days_by_horizon(
        alpha_matrix,
        signal_sessions_by_horizon=signal_sessions_by_horizon,
        cancellation_check=cancellation_check,
    )


def evaluate_factor(labels: dict[str, object]) -> dict[str, object]:
    horizons: dict[str, object] = {}
    for horizon, label_artifact in labels["horizons"].items():
        daily: list[dict[str, object]] = []
        for item in label_artifact["sessions"]:
            daily.append(factor_observation_from_labels(item, horizon=int(horizon)))
        horizons[horizon] = factor_horizon_from_daily(
            horizon=int(horizon),
            alpha_checksum=str(labels["alpha_checksum"]),
            label_checksum=str(label_artifact["checksum"]),
            daily=daily,
        )
    return {"horizons": horizons}


def factor_observation_from_labels(item: dict[str, object], *, horizon: int) -> dict[str, object]:
    return _factor_observation(
        session=str(item["session"]),
        horizon=horizon,
        entry_session=item["entry_session"],
        exit_session=item["exit_session"],
        alpha_count=len(item["alpha_values"]),
        alpha_exclusions=dict(item["alpha_coverage_loss"]),
        label_exclusions=dict(item["unavailable"]),
        sample_count=len(item["samples"]),
        metrics=factor_day(item["samples"]),
    )


def _factor_observation(
    *,
    session: str,
    horizon: int,
    entry_session: str | None,
    exit_session: str | None,
    alpha_count: int,
    alpha_exclusions: dict[str, int],
    label_exclusions: dict[str, int],
    sample_count: int,
    metrics: dict[str, object],
) -> dict[str, object]:
    if sample_count + sum(label_exclusions.values()) != alpha_count:
        raise FactorDataError("Factor label sample accounting is inconsistent")
    return {
        "session": session,
        "horizon": horizon,
        "label_entry_session": entry_session,
        "label_exit_session": exit_session,
        "label_status": (
            "right_censored_by_research_period_end"
            if exit_session is None
            else "within_research_period"
        ),
        "alpha_candidate_count": alpha_count + sum(alpha_exclusions.values()),
        "alpha_sample_count": alpha_count,
        "alpha_exclusions": dict(sorted(alpha_exclusions.items())),
        "sample_count": sample_count,
        "label_exclusions": dict(sorted(label_exclusions.items())),
        **metrics,
    }


def factor_horizon_from_daily(
    *,
    horizon: int,
    alpha_checksum: str,
    label_checksum: str,
    daily: list[dict[str, object]],
) -> dict[str, object]:
    payload = {
        "horizon": horizon,
        "alpha_checksum": alpha_checksum,
        "label_checksum": label_checksum,
        "daily": daily,
        "summary": summarize_factor_days(daily),
    }
    return {
        **payload,
        "checksum": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def summarize_factor_days(daily: list[dict[str, object]]) -> dict[str, object]:
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
            "quantile_counts": {f"q{group}": 0 for group in range(1, 6)},
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
        f"q{group}": mean_or_none(label[groups == group].tolist()) for group in range(1, 6)
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
        "quantile_counts": {
            f"q{group}": int(np.count_nonzero(groups == group)) for group in range(1, 6)
        },
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


def _average_ranks_array(array: np.ndarray) -> np.ndarray:
    if not np.all(np.isfinite(array)):
        raise FactorDataError("Factor rank values must be finite")
    order = np.argsort(array, kind="stable")
    ordered = array[order]
    starts = np.flatnonzero(np.concatenate((np.asarray([True]), ordered[1:] != ordered[:-1])))
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

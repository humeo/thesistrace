import hashlib
import math
from collections import Counter
from collections.abc import Sequence
from statistics import stdev

from thesistrace.research_kernel.serialization import canonical_json_bytes

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
    canonical: dict[str, object],
    alpha_matrix: dict[str, object],
    *,
    signal_sessions: Sequence[str],
    horizons: Sequence[int] = HORIZONS,
) -> dict[str, object]:
    calendar = [str(value) for value in canonical["research_calendar"]]
    prices = {(str(row["session"]), str(row["instrument_id"])): row for row in canonical["prices"]}
    states = {
        (str(row["session"]), str(row["instrument_id"])): str(row["state"])
        for row in canonical["trading_states"]
    }
    instruments = {str(row["instrument_id"]): row for row in canonical["instruments"]}
    alpha_by_session = {str(item["session"]): item for item in alpha_matrix["sessions"]}
    selected_sessions = [str(session) for session in signal_sessions]
    horizon_results: dict[str, object] = {}
    for horizon in horizons:
        sessions: list[dict[str, object]] = []
        for signal_session in selected_sessions:
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
                    entry_open = float(entry["open_adj"])
                    exit_open = float(exit_price["open_adj"])
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
    instrument: dict[str, object],
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
    if len(samples) < 30:
        return {
            "ic": None,
            "rank_ic": None,
            "correlation_reason": "sample_insufficient",
            "quantile_returns": empty_quantiles(),
            "top_bottom_return": None,
            "quantile_reason": "sample_insufficient",
        }
    alpha = [float(item["alpha"]) for item in samples]
    label = [float(item["label"]) for item in samples]
    ic = pearson(alpha, label)
    rank_ic = pearson(average_ranks(alpha), average_ranks(label))
    reason = "constant_array" if ic is None or rank_ic is None else None

    alpha_ranks = average_ranks(alpha)
    grouped: dict[int, list[float]] = {index: [] for index in range(1, 6)}
    count = len(samples)
    for rank, label_value in zip(alpha_ranks, label, strict=True):
        group = min(5, int((rank - 1) * 5 / count) + 1)
        grouped[group].append(label_value)
    quantiles = {f"q{group}": mean_or_none(grouped[group]) for group in range(1, 6)}
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
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    left_sum = math.fsum(value * value for value in left_centered)
    right_sum = math.fsum(value * value for value in right_centered)
    if left_sum == 0.0 or right_sum == 0.0:
        return None
    result = math.fsum(
        left_value * right_value
        for left_value, right_value in zip(left_centered, right_centered, strict=True)
    ) / math.sqrt(left_sum * right_sum)
    return result if math.isfinite(result) else None


def average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average = ((cursor + 1) + end) / 2
        for position in range(cursor, end):
            ranks[ordered[position][0]] = average
        cursor = end
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

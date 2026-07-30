import hashlib
import math
from collections import Counter
from statistics import stdev

from thesistrace.objects import canonical_json_bytes

HORIZONS = (1, 5, 20)


def build_forward_labels(
    canonical: dict[str, object],
    alpha_matrix: dict[str, object],
    *,
    report_sessions: int = 504,
) -> dict[str, object]:
    calendar = [str(value) for value in canonical["research_calendar"]]
    prices = {(str(row["session"]), str(row["instrument_id"])): row for row in canonical["prices"]}
    states = {
        (str(row["session"]), str(row["instrument_id"])): str(row["state"])
        for row in canonical["trading_states"]
    }
    instruments = {str(row["instrument_id"]): row for row in canonical["instruments"]}
    alpha_by_session = {str(item["session"]): item for item in alpha_matrix["sessions"]}
    report_start = max(0, len(calendar) - report_sessions)
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        sessions: list[dict[str, object]] = []
        for signal_index in range(report_start, len(calendar)):
            signal_session = calendar[signal_index]
            alpha_values = list(alpha_by_session[signal_session]["values"])
            samples: list[dict[str, object]] = []
            unavailable: Counter[str] = Counter()
            entry_index = signal_index + 1
            exit_index = signal_index + 1 + horizon
            for alpha in alpha_values:
                instrument_id = str(alpha["instrument_id"])
                if exit_index >= len(calendar):
                    unavailable["right_censored"] += 1
                    continue
                entry_session = calendar[entry_index]
                exit_session = calendar[exit_index]
                entry = prices.get((entry_session, instrument_id))
                if entry is None:
                    unavailable[
                        unavailable_reason(
                            states.get((entry_session, instrument_id)),
                            instruments[instrument_id],
                            entry_session,
                            valid_entry=False,
                        )
                    ] += 1
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
                        unavailable[reason] += 1
                        continue
                else:
                    entry_open = float(entry["open_adj"])
                    exit_open = float(exit_price["open_adj"])
                    if entry_open == 0.0:
                        unavailable["invalid_entry_open"] += 1
                        continue
                    label = exit_open / entry_open - 1.0
                    if not math.isfinite(label):
                        unavailable["non_finite_label"] += 1
                        continue
                samples.append(
                    {
                        "instrument_id": instrument_id,
                        "alpha": float(alpha["value"]),
                        "label": label,
                    }
                )
            samples.sort(key=lambda row: str(row["instrument_id"]))
            sessions.append(
                {
                    "session": signal_session,
                    "signal_session": signal_session,
                    "alpha_values": alpha_values,
                    "samples": samples,
                    "unavailable": dict(sorted(unavailable.items())),
                }
            )
        horizon_payload = {"horizon": horizon, "sessions": sessions}
        horizons[str(horizon)] = {
            **horizon_payload,
            "checksum": hashlib.sha256(canonical_json_bytes(horizon_payload)).hexdigest(),
        }
    return {
        "alpha_checksum": alpha_matrix["checksum"],
        "report_session_count": min(report_sessions, len(calendar)),
        "horizons": horizons,
    }


def unavailable_reason(
    trading_state: str | None,
    instrument: dict[str, object],
    session: str,
    *,
    valid_entry: bool,
) -> str:
    listed_to = str(instrument.get("listed_to", ""))
    if valid_entry and listed_to and listed_to <= session:
        return "terminal_delisting"
    if trading_state == "full_session_suspension":
        return "confirmed_open_unavailable"
    return "unexplained_data_failure"


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
            "horizon": int(horizon),
            "alpha_checksum": labels["alpha_checksum"],
            "label_checksum": label_artifact["checksum"],
            "daily": daily,
            "summary": summary,
        }
        horizons[horizon] = {
            **payload,
            "checksum": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        }
    return {"horizons": horizons}


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

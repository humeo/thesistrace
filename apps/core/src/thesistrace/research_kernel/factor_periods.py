"""Signal-date summaries built incrementally from the published daily evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from thesistrace.research_kernel.factor_evidence import validate_factor_observations
from thesistrace.research_kernel.research_chunks import (
    advance_factor_state_from_daily,
    empty_factor_state,
    finalize_factor_state,
)


class FactorPeriodAccumulator:
    """Retain aggregate states per period, never the complete daily or stock matrix."""

    def __init__(self) -> None:
        self._states: dict[tuple[int, str, str], dict[str, object]] = {}
        self._coverage: dict[tuple[int, str, str], dict[str, object]] = {}
        self._last_session: dict[int, str] = {}

    def add(self, rows: list[dict[str, object]]) -> None:
        observations = validate_factor_observations(rows)
        previous = dict(self._last_session)
        for row in observations:
            horizon, session = row["horizon"], row["session"]
            date.fromisoformat(session)
            if session <= previous.get(horizon, ""):
                raise ValueError("Factor period observations must be unique and ordered")
            previous[horizon] = session
        for row in observations:
            horizon, session = row["horizon"], row["session"]
            for granularity, period in (
                ("all", "all"),
                ("year", session[:4]),
                ("month", session[:7]),
            ):
                key = (horizon, granularity, period)
                daily = {str(value): [] for value in (1, 5, 20)}
                daily[str(horizon)] = [row]
                self._states[key] = advance_factor_state_from_daily(
                    self._states.get(key, empty_factor_state()), daily
                )
                coverage = self._coverage.setdefault(
                    key,
                    {
                        "first_signal_session": session,
                        "last_signal_session": session,
                        "label_evaluable_session_count": 0,
                        "first_evaluable_signal_session": None,
                        "last_evaluable_signal_session": None,
                        "right_censored_session_count": 0,
                        "sample_available_session_count": 0,
                        "alpha_candidate_count": 0,
                        "alpha_sample_count": 0,
                        "sample_count": 0,
                        "alpha_exclusions": {},
                        "label_exclusions": {},
                    },
                )
                coverage["last_signal_session"] = session
                if row["label_status"] == "within_research_period":
                    coverage["label_evaluable_session_count"] += 1
                    if coverage["first_evaluable_signal_session"] is None:
                        coverage["first_evaluable_signal_session"] = session
                    coverage["last_evaluable_signal_session"] = session
                else:
                    coverage["right_censored_session_count"] += 1
                coverage["sample_available_session_count"] += int(row["sample_count"] > 0)
                for count in ("alpha_candidate_count", "alpha_sample_count", "sample_count"):
                    coverage[count] += row[count]
                for name in ("alpha_exclusions", "label_exclusions"):
                    for reason, count in row[name].items():
                        coverage[name][reason] = coverage[name].get(reason, 0) + count
        self._last_session = previous

    def full_summary(self, *, alpha_checksums: dict[int, str]) -> dict[str, object]:
        horizons = {}
        for horizon in (1, 5, 20):
            key = (horizon, "all", "all")
            if key not in self._states:
                raise ValueError("Factor evidence is missing a horizon")
            horizons[str(horizon)] = finalize_factor_state(
                self._states[key],
                alpha_checksum=alpha_checksums[horizon],
            )["horizons"][str(horizon)]
        return {"horizons": horizons}

    def finish(self) -> list[dict[str, object]]:
        periods = []
        for key in sorted(self._states):
            horizon, granularity, period = key
            # Period statistics use the same reducer as the full Factor summary.
            # Provenance is owned by the enclosing Result, not invented per period.
            value = finalize_factor_state(self._states[key], alpha_checksum="")["horizons"][
                str(horizon)
            ]
            periods.append(
                {
                    "horizon": horizon,
                    "granularity": granularity,
                    "period": period,
                    "summary": value["summary"],
                    "coverage": {**value["coverage"], **deepcopy(self._coverage[key])},
                }
            )
        return periods

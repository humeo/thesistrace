"""Additional local-only optimization probes, reusing the audit's fixed fixture."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import numpy as np
from benchmark import (
    HERE,
    NOOP,
    alpha_operation,
    chunk_operation,
    compare,
    deduplicated_plan,
    fixture,
)

from thesistrace.alpha_language import alpha_language
from thesistrace.research_kernel import factor
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_columnar_execution_matrix,
)


def shared_factor_coordinates(
    self, alpha_matrix, *, signal_sessions_by_horizon, cancellation_check
):
    session_positions = {session: index for index, session in enumerate(self.sessions)}
    instrument_positions = {
        instrument: index for index, instrument in enumerate(self.instrument_ids)
    }
    alpha_by_session = {str(item["session"]): item for item in alpha_matrix["sessions"]}
    coordinates = {}
    result = {}
    for horizon, sessions in signal_sessions_by_horizon.items():
        daily = []
        for session in sessions:
            cancellation_check()
            session = str(session)
            index = session_positions[session]
            if session not in coordinates:
                values = alpha_by_session[session]["values"]
                ids = tuple(str(row["instrument_id"]) for row in values)
                positions = np.fromiter(
                    (instrument_positions[instrument] for instrument in ids),
                    dtype=np.intp,
                    count=len(ids),
                )
                alpha = np.fromiter(
                    (float(row["value"]) for row in values),
                    dtype=np.float64,
                    count=len(ids),
                )
                coordinates[session] = ids, positions, alpha
            ids, positions, alpha = coordinates[session]
            states = self.states_by_horizon[horizon][positions, index]
            factor._raise_selected_label_error(
                states,
                instrument_ids=ids,
                signal_session=session,
                entry_session=self.sessions[index + 1]
                if index + 1 < len(self.sessions)
                else session,
                exit_session=self.sessions[index + 1 + horizon]
                if index + 1 + horizon < len(self.sessions)
                else session,
            )
            included = states == 0
            labels = self.labels_by_horizon[horizon][positions, index][included]
            selected_alpha = alpha[included]
            daily.append(
                {
                    "session": session,
                    "sample_count": len(selected_alpha),
                    **factor._factor_array_values(selected_alpha, labels),
                }
            )
            cancellation_check()
        result[str(horizon)] = daily
    return result


def main():
    data = fixture()
    matrix, _ = alpha_operation(replace(data), True)()
    labels = factor.prepare_columnar_forward_labels(
        replace(data), cancellation_check=NOOP
    )
    selected = {h: data.sessions[21:] for h in factor.HORIZONS}

    def days(shared):
        def operation():
            target = (
                shared_factor_coordinates
                if shared
                else factor.PreparedColumnarForwardLabels.factor_days_by_horizon
            )
            return target(
                labels,
                matrix,
                signal_sessions_by_horizon=selected,
                cancellation_check=NOOP,
            ), {}

        return operation

    report = {
        "factor_coordinate_reuse": compare(
            "factor_coordinate_reuse",
            {
                "current": lambda: days(False),
                "shared": lambda: days(True),
            },
        )
    }

    def chunk(shared):
        calculate = chunk_operation(replace(data), "factor_evaluation")

        def operation():
            if shared:
                with patch.object(
                    factor.PreparedColumnarForwardLabels,
                    "factor_days_by_horizon",
                    shared_factor_coordinates,
                ):
                    return calculate()
            return calculate()

        return operation

    report["factor_chunk_coordinate_reuse"] = compare(
        "factor_chunk_coordinate_reuse",
        {
            "current": lambda: chunk(False),
            "shared": lambda: chunk(True),
        },
    )
    small = fixture(300, 85)
    ids = tuple(small.instruments)
    fields = small.numeric_field_matrices(("price.close.adjusted",), ids)
    formula = (
        "rank(close / ts_mean(close, 20)) - rank(lag(close / ts_mean(close, 20), 5))"
    )
    current = build_series_execution_plan(alpha_language.compile(formula))
    shared = deduplicated_plan(current)

    def evaluate(plan):
        return lambda: (
            evaluate_columnar_execution_matrix(
                plan,
                ids,
                small.sessions,
                fields,
                small.universe_members,
                cancellation_check=NOOP,
            ),
            {},
        )

    report["two_occurrence_formula"] = {
        "formula": formula,
        "stocks": 300,
        "sessions": 85,
        "nodes_before": len(current.nodes),
        "nodes_after": len(shared.nodes),
        **compare(
            "two_occurrence_formula",
            {
                "current": lambda: evaluate(current),
                "shared": lambda: evaluate(shared),
            },
        ),
    }
    (HERE / "candidate-results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

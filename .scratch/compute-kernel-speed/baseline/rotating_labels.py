"""Probe the existing qualification fixture's rotating Top3000 label workload."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from unittest.mock import patch

import benchmark
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from benchmark import HERE, NOOP, chunk_operation, compare, fixture, profile

from thesistrace.data.columnar_series import ColumnarResearchData
from thesistrace.research_kernel import factor

sys.path.insert(0, str(HERE.parents[2] / "apps/core/benchmarks"))
from benchmark_financial_io import build_market_benchmark_stream  # noqa: E402


def rotating_fixture():
    sessions = fixture(1, 85).sessions
    stream = build_market_benchmark_stream(list(sessions), 5541, 3000, len(sessions))
    partitions = list(stream.partitions())
    tables = {
        name: pa.concat_tables([part.tables[name] for part in partitions])
        for name in partitions[0].tables
    }
    universe = tables["liquidity_universes"]
    universe = universe.filter(pc.equal(universe["universe"], "top3000"))
    return ColumnarResearchData(
        sessions=sessions,
        _instruments=pa.Table.from_pylist(list(stream.static["instruments"])),
        _eod_prices=tables["eod_prices"],
        _universes=universe,
        _trading_states=tables["trading_states"],
        _price_limits=tables["price_limits"],
        _industries=pa.Table.from_pylist(list(stream.static["industry_membership"])),
        _financial_values=None,
        _field_columns={"price.close.adjusted": "close_adj"},
    )


def vector_labels(data, *, cancellation_check):
    sessions = data.sessions
    ids = tuple(sorted(data.instruments))
    opens = data.adjusted_open_matrix(ids)
    finite = np.isfinite(opens)
    # Resolve each missing coordinate once; entry/exit retain distinct meanings.
    missing_reason = np.zeros(opens.shape, dtype=np.uint8)
    for index, session in enumerate(sessions):
        cancellation_check()
        for position in np.flatnonzero(~finite[:, index]):
            instrument = ids[int(position)]
            reason = factor.unavailable_reason(
                data.trading_states.get((session, instrument)),
                data.instruments[instrument],
                session,
                valid_entry=True,
            )
            missing_reason[position, index] = (
                2
                if reason == "terminal_delisting"
                else 3
                if reason == "unexplained_missing_or_invalid_data"
                else 1
            )
    labels_by_horizon, states_by_horizon = {}, {}
    for horizon in factor.HORIZONS:
        cancellation_check()
        labels = np.full(opens.shape, np.nan, dtype=np.float64)
        states = np.full(opens.shape, factor._LABEL_UNAVAILABLE, dtype=np.uint8)
        width = max(0, len(sessions) - horizon - 1)
        entry = opens[:, 1 : 1 + width]
        exit_open = opens[:, 1 + horizon : 1 + horizon + width]
        valid_entry = finite[:, 1 : 1 + width]
        valid_exit = finite[:, 1 + horizon : 1 + horizon + width]
        entry_reason = missing_reason[:, 1 : 1 + width]
        exit_reason = missing_reason[:, 1 + horizon : 1 + horizon + width]
        zero_entry = valid_entry & (entry == 0.0)
        valid = valid_entry & valid_exit & ~zero_entry
        projected_labels = labels[:, :width]
        projected_states = states[:, :width]
        projected_states[zero_entry] = factor._LABEL_INVALID_ZERO_ENTRY
        projected_labels[valid] = exit_open[valid] / entry[valid] - 1.0
        projected_states[valid] = 0
        projected_states[~valid_entry & (entry_reason == 3)] = (
            factor._LABEL_INVALID_ENTRY
        )
        missing_exit = valid_entry & ~valid_exit & ~zero_entry
        terminal = missing_exit & (exit_reason == 2)
        projected_labels[terminal] = -1.0
        projected_states[terminal] = 0
        projected_states[missing_exit & (exit_reason == 3)] = factor._LABEL_INVALID_EXIT
        projected_states[(projected_states == 0) & ~np.isfinite(projected_labels)] = (
            factor._LABEL_INVALID_NON_FINITE
        )
        labels_by_horizon[horizon] = labels
        states_by_horizon[horizon] = states
    return factor.PreparedColumnarForwardLabels(
        sessions=sessions,
        instrument_ids=ids,
        labels_by_horizon=labels_by_horizon,
        states_by_horizon=states_by_horizon,
    )


def label_operation(data, vector):
    def operation():
        target = vector_labels if vector else factor.prepare_columnar_forward_labels
        result = target(data, cancellation_check=NOOP)
        return np.stack(
            [
                array
                for horizon in factor.HORIZONS
                for array in (
                    result.labels_by_horizon[horizon],
                    result.states_by_horizon[horizon],
                )
            ]
        ), {}

    return operation


def main():
    data = rotating_fixture()
    report = {
        "description": "Existing long-research qualification generator; 85 sessions, 5541 historical IDs, rotating Top3000",
        "label_arrays_and_error_states": compare(
            "rotating_label_preparation",
            {
                "current": lambda: label_operation(replace(data), False),
                "vector_once": lambda: label_operation(replace(data), True),
            },
        ),
    }

    def chunk(vector, kind):
        calculate = chunk_operation(replace(data), kind)

        def operation():
            if vector:
                with patch.object(
                    benchmark, "prepare_columnar_forward_labels", vector_labels
                ):
                    return calculate()
            return calculate()

        return operation

    for kind in ("factor_evaluation", "strategy_backtest"):
        report[kind] = compare(
            f"rotating_{kind}",
            {
                "current": lambda: chunk(False, kind),
                "vector_once": lambda: chunk(True, kind),
            },
        )
        (HERE / "rotating-results.json").write_text(json.dumps(report, indent=2) + "\n")
    profile("rotating-labels", label_operation(replace(data), False))


if __name__ == "__main__":
    main()

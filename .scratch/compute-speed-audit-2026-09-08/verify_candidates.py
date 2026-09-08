"""Verify local candidates against error states and existing behavior contracts."""

from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import dataclass
from unittest.mock import patch

import numpy as np
import pytest
from benchmark import HERE, NOOP, deduplicated_plan
from candidates import shared_factor_coordinates
from rotating_labels import vector_labels

from thesistrace.research_kernel import alpha, factor
from thesistrace.research_kernel.series_plan import evaluate_columnar_execution_matrix
from thesistrace.research_series import InstrumentProfile


@dataclass
class LabelInput:
    sessions: tuple[str, ...]
    instruments: dict[str, InstrumentProfile]
    trading_states: dict[tuple[str, str], str]
    opens: np.ndarray

    def adjusted_open_matrix(self, _instruments):
        return self.opens


def main():
    observed_states = set()
    for seed in range(30):
        rng = np.random.default_rng(seed)
        sessions = tuple(f"s{index:03d}" for index in range(35))
        ids = tuple(f"equity:{index:04d}" for index in range(40))
        opens = rng.normal(10.0, 2.0, (len(ids), len(sessions)))
        opens[rng.random(opens.shape) < 0.12] = np.nan
        opens[0, 1] = 0.0
        opens[1, 1] = 1e-308
        opens[1, 2] = 1e308
        opens[2, 6] = np.inf
        opens[3, 10:] = np.nan
        opens[4, 1] = np.nan
        opens[5, 2] = np.nan
        inputs = LabelInput(
            sessions=sessions,
            instruments={
                key: InstrumentProfile(
                    board="main", listed_to=sessions[10] if index == 3 else ""
                )
                for index, key in enumerate(ids)
            },
            trading_states={
                (session, key): (
                    "normal",
                    "data_unavailable",
                    "full_session_suspension",
                )[(index + day) % 3]
                for index, key in enumerate(ids)
                for day, session in enumerate(sessions)
            },
            opens=opens,
        )
        with np.errstate(all="ignore"):
            expected = factor.prepare_columnar_forward_labels(
                inputs, cancellation_check=NOOP
            )
            actual = vector_labels(inputs, cancellation_check=NOOP)
        for horizon in factor.HORIZONS:
            np.testing.assert_array_equal(
                actual.labels_by_horizon[horizon],
                expected.labels_by_horizon[horizon],
                strict=True,
            )
            np.testing.assert_array_equal(
                actual.states_by_horizon[horizon],
                expected.states_by_horizon[horizon],
                strict=True,
            )
            observed_states.update(
                map(int, np.unique(actual.states_by_horizon[horizon]))
            )
    assert observed_states == {0, 1, 2, 3, 4, 5}
    print(
        "30 deterministic label edge cases: exact values and all 6 error/availability states verified",
        flush=True,
    )

    def prepare(research_data, *, cancellation_check):
        return vector_labels(research_data, cancellation_check=cancellation_check)

    def evaluate(plan, *args, **kwargs):
        return evaluate_columnar_execution_matrix(
            deduplicated_plan(plan), *args, **kwargs
        )

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(factor, "prepare_columnar_forward_labels", prepare)
        )
        stack.enter_context(
            patch.object(
                factor.PreparedColumnarForwardLabels,
                "factor_days_by_horizon",
                shared_factor_coordinates,
            )
        )
        stack.enter_context(
            patch.object(alpha, "evaluate_columnar_execution_matrix", evaluate)
        )
        code = pytest.main(
            [
                "-c",
                "apps/core/pyproject.toml",
                "--rootdir",
                ".",
                "-q",
                "apps/core/tests/kernel/test_factor.py",
                "apps/core/tests/kernel/test_research_chunk_continuation.py",
                "apps/core/tests/kernel/test_numeric_contract.py",
                "-k",
                "not performance_gate and not regression_gate",
            ]
        )
    (HERE / "verification.json").write_text(
        json.dumps(
            {
                "label_edge_cases": 30,
                "label_state_codes": sorted(observed_states),
                "candidate_patches": [
                    "vector_label_preparation",
                    "shared_factor_coordinates",
                    "alpha_subexpression_reuse",
                ],
                "pytest_exit_code": int(code),
                "boundary": "In-process candidate computation; excludes DailyTrack orchestration, storage, and Worker qualification",
            },
            indent=2,
        )
        + "\n"
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()

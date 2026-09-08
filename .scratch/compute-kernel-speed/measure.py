"""Serial, exact-output comparisons against the captured pre-edit source.

Run from this worktree: uv run --project apps/core python .scratch/compute-kernel-speed/measure.py
Input creation and digest comparison are outside each timed operation.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import platform
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "baseline"))
import benchmark as bench
from rotating_labels import rotating_fixture
from verify_candidates import LabelInput

from thesistrace.alpha_language import alpha_language
from thesistrace.daily_track.checkpoint import project_tracking_checkpoint, restore_tracking_checkpoint
from thesistrace.daily_track.observation_state import initial_tracking_observation_state
from thesistrace.research_kernel import alpha, factor
from thesistrace.research_kernel.kernel_advance import AdvanceInput, continuation_snapshot
from thesistrace.research_kernel.kernel_run import KernelState, RunInput, StrategyRunInput, calculation_definition, compose_output
from thesistrace.research_kernel.series_plan import build_series_execution_plan, evaluate_columnar_execution_matrix
from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_kernel.tracking_advance import advance_tracking, advance_tracking_continuation
from thesistrace.research_kernel import empty_continuation
from thesistrace.research_series import InstrumentProfile


def before(name):
    spec = importlib.util.spec_from_file_location(name, HERE / "baseline" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


old_factor = before("factor_before")
old_series = before("series_plan_before")
old_advance = before("kernel_advance_before")
for name in ("build_forward_labels", "evaluate_factor", "factor_horizon_from_daily"):
    setattr(old_advance, name, getattr(old_factor, name))


def verify_labels():
    observed = set()
    for seed in range(30):
        rng = np.random.default_rng(seed)
        sessions = tuple(f"s{index:03d}" for index in range(35))
        ids = tuple(f"equity:{index:04d}" for index in range(40))
        opens = rng.normal(10.0, 2.0, (len(ids), len(sessions)))
        opens[rng.random(opens.shape) < 0.12] = np.nan
        opens[0, 1], opens[1, 1], opens[1, 2] = 0.0, 1e-308, 1e308
        opens[2, 6], opens[3, 10:], opens[4, 1], opens[5, 2] = np.inf, np.nan, np.nan, np.nan
        data = LabelInput(
            sessions=sessions, opens=opens,
            instruments={key: InstrumentProfile("main", sessions[10] if index == 3 else "") for index, key in enumerate(ids)},
            trading_states={(session, key): ("normal", "data_unavailable", "full_session_suspension")[(index + day) % 3] for index, key in enumerate(ids) for day, session in enumerate(sessions)},
        )
        with np.errstate(all="ignore"):
            expected = old_factor.prepare_columnar_forward_labels(data, cancellation_check=bench.NOOP)
            actual = factor.prepare_columnar_forward_labels(data, cancellation_check=bench.NOOP)
        for horizon in factor.HORIZONS:
            np.testing.assert_array_equal(actual.labels_by_horizon[horizon], expected.labels_by_horizon[horizon], strict=True)
            np.testing.assert_array_equal(actual.states_by_horizon[horizon], expected.states_by_horizon[horizon], strict=True)
            observed.update(map(int, np.unique(actual.states_by_horizon[horizon])))
    assert observed == {0, 1, 2, 3, 4, 5}
    return {"cases": 30, "states": sorted(observed), "exact_equal": True}


def input_for(data):
    compiled = alpha_language.compile("rank(pct_change(close, 20))")
    return RunInput(
        research_data=data, alpha_expression=compiled.expression,
        field_bindings={value: key for key, value in compiled.field_ids_by_identifier.items()},
        effective_alpha_lookback=20, universe="top3000", neutralization="none",
        research_kind="strategy_backtest", strategy=StrategyRunInput(
            holdings_count=10, rebalance_interval=5, initial_cash_cny="10000000",
            commission_rate_all_in="0.0003", commission_min_cny="5",
            stamp_duty_sell_rate="0.0005", transfer_fee_rate="0.00001",
        ),
    )


def main():
    source_root = HERE.parents[1] / "apps/core/src/thesistrace"
    sources = ["research_kernel/factor.py", "research_kernel/series_plan.py", "research_kernel/kernel_advance.py", "research_kernel/tracking_advance.py", "daily_track/calculation.py"]
    report = {
        "base_commit": "adc1007bf40308246e46c4e4deb3c31648b1c149",
        "python": platform.python_version(), "numpy": np.__version__, "pyarrow": bench.pa.__version__,
        "current_source_sha256": {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in sources},
        "baseline_source_sha256": {name.name: hashlib.sha256(name.read_bytes()).hexdigest() for name in (HERE / "baseline").glob("*_before.py")},
        "repetitions": bench.REPETITIONS,
        "timing_boundary": "Actual in-memory calculation and checkpoint projection; excludes fixture construction, result comparison, I/O and Worker scheduling",
        "host_load_start": os.getloadavg(), "label_edges": verify_labels(), "experiments": {},
    }
    def save(name, factories):
        report["experiments"][name] = bench.compare(name, factories)
        report["host_load_latest"] = os.getloadavg()
        (HERE / "measurements.json").write_text(json.dumps(report, indent=2) + "\n")
    data = rotating_fixture()
    for kind in ("factor_evaluation", "strategy_backtest"):
        def factory(original):
            calculate = bench.chunk_operation(replace(data), kind)
            def operation():
                with patch.object(bench, "prepare_columnar_forward_labels", old_factor.prepare_columnar_forward_labels if original else factor.prepare_columnar_forward_labels), patch.object(alpha, "evaluate_columnar_execution_matrix", old_series.evaluate_columnar_execution_matrix if original else evaluate_columnar_execution_matrix):
                    return calculate()
            return operation
        save(kind, {"before": lambda: factory(True), "after": lambda: factory(False)})
    small = bench.fixture(300, 85)
    ids = tuple(small.instruments)
    fields = small.numeric_field_matrices(("price.close.adjusted",), ids)
    plan = build_series_execution_plan(alpha_language.compile("rank(close / ts_mean(close, 20)) - rank(lag(close / ts_mean(close, 20), 5))"))
    save("repeated_alpha", {name: lambda evaluate=evaluate: lambda: (evaluate(plan, ids, small.sessions, fields, small.universe_members, cancellation_check=bench.NOOP), {}) for name, evaluate in (("before", old_series.evaluate_columnar_execution_matrix), ("after", evaluate_columnar_execution_matrix))})

    full = data
    prior_data = full.slice_sessions(full.sessions[:-1])
    value = input_for(prior_data)
    matrix = alpha.evaluate_columnar_alpha_matrix(prior_data, compiled_alpha=value.compiled_alpha_snapshot(), neutralization="none", cancellation_check=bench.NOOP)
    days = factor.prepare_columnar_forward_labels(prior_data, cancellation_check=bench.NOOP).factor_days_by_horizon(matrix, signal_sessions_by_horizon={h: prior_data.sessions for h in factor.HORIZONS}, cancellation_check=bench.NOOP)
    factors = {"horizons": {str(h): {"horizon": h, "daily": days[str(h)], "summary": factor.summarize_factor_days(days[str(h)])} for h in factor.HORIZONS}}
    strategy = transition_strategy(prior_data, matrix, calculation_definition(value), origin_session=prior_data.sessions[21])
    prior = KernelState(run_input=value, output=compose_output(matrix, {"horizons": {}}, factors, strategy.finalized), strategy_resume=strategy.resumable, origin_session=prior_data.sessions[21])
    observation = initial_tracking_observation_state(prior.boundary_session, "10000000")
    checkpoint = project_tracking_checkpoint(prior, retained_strategy_sessions=[prior.boundary_session], prior_observation_state=observation)
    continuation = continuation_snapshot(prior)
    def tracking_factory(calculate):
        data = full.slice_sessions(full.sessions[-22:])
        restored = restore_tracking_checkpoint(checkpoint, research_data=data.slice_sessions(data.sessions[:-1]))
        advance_input = AdvanceInput(prior_state=restored, target_research_data=data, appended_sessions=[data.sessions[-1]], continuation=continuation, calculation_scope="forward_tracking")
        def operation():
            state = calculate(advance_input)
            return {"checkpoint": project_tracking_checkpoint(state, retained_strategy_sessions=list(data.sessions[-2:]), prior_observation_state=observation), "continuation": continuation_snapshot(state), "strategy_resume": state.strategy_resume_snapshot()}, {}
        return operation
    save("dailytrack_full_warm_advance_rotating_top3000", {"before": lambda: tracking_factory(old_advance.advance), "after": lambda: tracking_factory(advance_tracking)})
    def cold_factory(calculate):
        data = full.slice_sessions(full.sessions[-53:])
        value = input_for(data)
        return lambda: (calculate(run_input=value, prior_continuation=empty_continuation(), target_research_data=data, appended_sessions=list(data.sessions[21:])), {})
    save("dailytrack_cold_rebuild_32_sessions_rotating_top3000", {"before": lambda: cold_factory(old_advance.advance_continuation), "after": lambda: cold_factory(advance_tracking_continuation)})


if __name__ == "__main__":
    main()

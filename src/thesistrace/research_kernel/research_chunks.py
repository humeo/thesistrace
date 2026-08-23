from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from time import monotonic

from thesistrace.research_kernel.alpha import (
    advance_alpha_checksum,
    evaluate_columnar_alpha_sessions,
)
from thesistrace.research_kernel.factor import (
    HORIZONS,
    PreparedColumnarForwardLabels,
    factor_day,
    prepared_forward_factor_days_by_horizon,
)
from thesistrace.research_kernel.kernel_run import RunInput, calculation_definition
from thesistrace.research_kernel.numeric import (
    canonical_decimal,
    require_current_numeric_contract,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy import (
    run_strategy_with_metric_state,
    strategy_metrics_from_state,
)
from thesistrace.research_series import ColumnarResearchSeries

_STATISTIC_NAMES = (
    "ic",
    "rank_ic",
    "q1",
    "q2",
    "q3",
    "q4",
    "q5",
    "top_bottom_return",
)
_MAX_PENDING_ALPHA_SESSIONS = 21
_ALPHA_FACTOR_CONTINUATION_KEYS = {
    "binding_checksum",
    "completed_research_session_count",
    "rolling_tail_sessions",
    "pending_alpha",
    "alpha_checksum",
    "factor_state",
}
_STRATEGY_CONTINUATION_KEYS = {
    "alpha_factor_binding_checksum",
    "strategy_input_checksum",
    "strategy_state",
    "strategy_checksum",
}


@dataclass(frozen=True, init=False)
class AlphaFactorExecutionBinding:
    _value_json: bytes
    _run_contract: dict[str, object]
    checksum: str

    @classmethod
    def from_run_input(
        cls,
        run_input: RunInput,
        *,
        data_generation_id: str,
        numeric_execution_contract: str,
        semantic_versions: Mapping[str, str],
    ) -> AlphaFactorExecutionBinding:
        require_current_numeric_contract(numeric_execution_contract)
        if not data_generation_id:
            raise ValueError("Alpha-and-Factor Data Generation is invalid")
        if (
            not semantic_versions
            or any(
                not isinstance(name, str)
                or not name
                or not isinstance(version, str)
                or not version
                for name, version in semantic_versions.items()
            )
        ):
            raise ValueError("Alpha-and-Factor semantic versions are invalid")
        run_contract = run_input.alpha_factor_contract_snapshot()
        value = {
            "data_generation_id": data_generation_id,
            **run_contract,
            "label_horizons": list(HORIZONS),
            "numeric_execution_contract": numeric_execution_contract,
            "semantic_versions": dict(semantic_versions),
        }
        encoded = canonical_json_bytes(value)
        instance = object.__new__(cls)
        object.__setattr__(instance, "_value_json", encoded)
        object.__setattr__(instance, "_run_contract", run_contract)
        object.__setattr__(instance, "checksum", hashlib.sha256(encoded).hexdigest())
        return instance

    def value_snapshot(self) -> dict[str, object]:
        return _json_mapping(self._value_json, "Alpha-and-Factor binding")

    def require_run_input(self, run_input: RunInput) -> None:
        if run_input.alpha_factor_contract_snapshot() != self._run_contract:
            raise ValueError("Alpha-and-Factor binding does not match Research input")


@dataclass(frozen=True, init=False)
class AlphaFactorChunkOutcome:
    _binding_json: bytes
    _continuation: dict[str, object]
    _alpha_matrix: dict[str, object]
    _factor_summary: dict[str, object] | None
    _phase_seconds: tuple[tuple[str, float], ...]
    binding_checksum: str
    completed_research_session_count: int

    @classmethod
    def _from_validated(
        cls,
        *,
        binding: AlphaFactorExecutionBinding,
        continuation: dict[str, object],
        alpha_matrix: dict[str, object],
        factor_summary: dict[str, object] | None,
        phase_seconds: Mapping[str, float],
    ) -> AlphaFactorChunkOutcome:
        expected_phases = {"alpha_and_pending", "factor", "finalize"}
        if set(phase_seconds) != expected_phases or any(
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in phase_seconds.values()
        ):
            raise ValueError("Alpha-and-Factor phase timing is invalid")
        instance = object.__new__(cls)
        object.__setattr__(instance, "_binding_json", binding._value_json)
        object.__setattr__(instance, "_continuation", continuation)
        object.__setattr__(instance, "_alpha_matrix", alpha_matrix)
        object.__setattr__(instance, "_factor_summary", factor_summary)
        object.__setattr__(instance, "binding_checksum", binding.checksum)
        object.__setattr__(
            instance,
            "completed_research_session_count",
            int(continuation["completed_research_session_count"]),
        )
        object.__setattr__(
            instance,
            "_phase_seconds",
            tuple((name, float(phase_seconds[name])) for name in sorted(expected_phases)),
        )
        return instance

    def binding_snapshot(self) -> dict[str, object]:
        return _json_mapping(self._binding_json, "Alpha-and-Factor binding")

    def continuation_snapshot(self) -> dict[str, object]:
        return deepcopy(self._continuation)

    def alpha_matrix_snapshot(self) -> dict[str, object]:
        return deepcopy(self._alpha_matrix)

    def factor_summary_snapshot(self) -> dict[str, object] | None:
        return deepcopy(self._factor_summary)

    def _continuation_for_current_process(self) -> dict[str, object]:
        return self._continuation

    def _alpha_matrix_for_current_process(self) -> dict[str, object]:
        return self._alpha_matrix

    def _factor_summary_for_current_process(self) -> dict[str, object] | None:
        return self._factor_summary

    @property
    def phase_seconds(self) -> dict[str, float]:
        return dict(self._phase_seconds)

    def require_binding(self, expected: AlphaFactorExecutionBinding) -> None:
        if self.binding_checksum != expected.checksum or self._binding_json != expected._value_json:
            raise ValueError("Alpha-and-Factor binding does not match expected contract")


@dataclass(frozen=True, init=False)
class StrategyChunkOutcome:
    _continuation: dict[str, object]
    _daily_observations: tuple[dict[str, object], ...]
    _final_values: dict[str, object] | None
    _phase_seconds: tuple[tuple[str, float], ...]
    binding_checksum: str
    strategy_input_checksum: str

    @classmethod
    def _from_validated(
        cls,
        *,
        binding: AlphaFactorExecutionBinding,
        run_input: RunInput,
        continuation: dict[str, object],
        daily_observations: list[dict[str, object]],
        final_values: dict[str, object] | None,
        phase_seconds: Mapping[str, float],
    ) -> StrategyChunkOutcome:
        expected_phases = {"strategy", "finalize"}
        if set(phase_seconds) != expected_phases or any(
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in phase_seconds.values()
        ):
            raise ValueError("Strategy phase timing is invalid")
        instance = object.__new__(cls)
        object.__setattr__(instance, "_continuation", continuation)
        object.__setattr__(instance, "_daily_observations", tuple(daily_observations))
        object.__setattr__(instance, "_final_values", final_values)
        object.__setattr__(instance, "binding_checksum", binding.checksum)
        object.__setattr__(
            instance,
            "strategy_input_checksum",
            _strategy_input_checksum(run_input),
        )
        object.__setattr__(
            instance,
            "_phase_seconds",
            tuple((name, float(phase_seconds[name])) for name in sorted(expected_phases)),
        )
        return instance

    def continuation_snapshot(self) -> dict[str, object]:
        return deepcopy(self._continuation)

    def daily_observations_snapshot(self) -> list[dict[str, object]]:
        return deepcopy(list(self._daily_observations))

    def final_values_snapshot(self) -> dict[str, object] | None:
        return deepcopy(self._final_values)

    @property
    def phase_seconds(self) -> dict[str, float]:
        return dict(self._phase_seconds)

    def require_strategy_input(self, run_input: RunInput) -> None:
        if self.strategy_input_checksum != _strategy_input_checksum(run_input):
            raise ValueError("Strategy outcome does not match Strategy input")

    def _continuation_for_current_process(self) -> dict[str, object]:
        return self._continuation

    def _daily_observations_for_current_process(self) -> tuple[dict[str, object], ...]:
        return self._daily_observations

    def _final_values_for_current_process(self) -> dict[str, object] | None:
        return self._final_values


@dataclass(frozen=True)
class ResearchChunkCalculation:
    continuation: dict[str, object]
    strategy_daily_observations: tuple[dict[str, object], ...]
    final_values: dict[str, object] | None
    phase_seconds: dict[str, float]


def empty_alpha_factor_continuation() -> dict[str, object]:
    return {
        "binding_checksum": None,
        "completed_research_session_count": 0,
        "rolling_tail_sessions": [],
        "pending_alpha": [],
        "alpha_checksum": None,
        "factor_state": empty_factor_state(),
    }


def empty_strategy_continuation() -> dict[str, object]:
    return {
        "alpha_factor_binding_checksum": None,
        "strategy_input_checksum": None,
        "strategy_state": None,
        "strategy_checksum": None,
    }


def empty_research_continuation(
    research_kind: str,
) -> dict[str, object]:
    if research_kind not in {"factor_evaluation", "strategy_backtest"}:
        raise ValueError("Research Kind is invalid")
    continuation: dict[str, object] = {
        "schema_version": "research-chunk-continuation-v2",
        "research_kind": research_kind,
        **empty_alpha_factor_continuation(),
    }
    if research_kind == "strategy_backtest":
        continuation.update(empty_strategy_continuation())
    return continuation


def execute_research_chunk(
    *,
    run_input: RunInput,
    binding: AlphaFactorExecutionBinding,
    research_data: ColumnarResearchSeries,
    forward_labels: PreparedColumnarForwardLabels,
    research_sessions: tuple[str, ...],
    final_chunk: bool,
    continuation: Mapping[str, object],
    cancellation_check: Callable[[], None],
) -> ResearchChunkCalculation:
    alpha_started = monotonic()
    state = validated_research_continuation(
        continuation,
        research_kind=run_input.research_kind,
    )
    if not research_sessions:
        binding.require_run_input(run_input)
        return ResearchChunkCalculation(
            continuation=state,
            strategy_daily_observations=(),
            final_values=None,
            phase_seconds={
                "alpha_and_pending": monotonic() - alpha_started,
                "factor": 0.0,
                "strategy": 0.0,
                "finalize": 0.0,
            },
        )
    alpha_factor = _execute_alpha_factor_chunk_from_validated(
        run_input=run_input,
        binding=binding,
        research_data=research_data,
        forward_labels=forward_labels,
        research_sessions=research_sessions,
        final_chunk=final_chunk,
        state={name: state[name] for name in _ALPHA_FACTOR_CONTINUATION_KEYS},
        cancellation_check=cancellation_check,
    )
    state.update(alpha_factor._continuation_for_current_process())
    alpha_and_pending_seconds = alpha_factor.phase_seconds["alpha_and_pending"]
    factor_seconds = alpha_factor.phase_seconds["factor"]
    factor_finalize_seconds = alpha_factor.phase_seconds["finalize"]
    if run_input.research_kind == "factor_evaluation":
        factor_summary = alpha_factor._factor_summary_for_current_process()
        if final_chunk and factor_summary is None:
            raise ValueError("Final Alpha-and-Factor outcome is incomplete")
        return ResearchChunkCalculation(
            continuation=state,
            strategy_daily_observations=(),
            final_values=(
                None if factor_summary is None else {"factor_summary": factor_summary}
            ),
            phase_seconds={
                "alpha_and_pending": alpha_and_pending_seconds,
                "factor": factor_seconds,
                "strategy": 0.0,
                "finalize": factor_finalize_seconds,
            },
        )

    strategy_outcome = _execute_strategy_chunk_from_validated_alpha_factor(
        run_input=run_input,
        binding=binding,
        alpha_factor_outcome=alpha_factor,
        research_data=research_data,
        final_chunk=final_chunk,
        continuation={name: state[name] for name in _STRATEGY_CONTINUATION_KEYS},
        cancellation_check=cancellation_check,
    )
    state.update(strategy_outcome._continuation_for_current_process())
    return ResearchChunkCalculation(
        continuation=state,
        strategy_daily_observations=(
            strategy_outcome._daily_observations_for_current_process()
        ),
        final_values=strategy_outcome._final_values_for_current_process(),
        phase_seconds={
            "alpha_and_pending": alpha_and_pending_seconds,
            "factor": factor_seconds,
            "strategy": strategy_outcome.phase_seconds["strategy"],
            "finalize": (
                factor_finalize_seconds + strategy_outcome.phase_seconds["finalize"]
            ),
        },
    )


def execute_strategy_chunk_from_alpha_factor_outcome(
    *,
    run_input: RunInput,
    binding: AlphaFactorExecutionBinding,
    alpha_factor_outcome: AlphaFactorChunkOutcome,
    research_data: ColumnarResearchSeries,
    final_chunk: bool,
    continuation: Mapping[str, object],
    cancellation_check: Callable[[], None],
) -> StrategyChunkOutcome:
    state = validated_strategy_continuation(continuation)
    if run_input.research_kind != "strategy_backtest" or run_input.strategy is None:
        raise ValueError("Strategy Backtest input is incomplete")
    binding.require_run_input(run_input)
    alpha_factor_outcome.require_binding(binding)
    return _execute_strategy_chunk_from_validated_alpha_factor(
        run_input=run_input,
        binding=binding,
        alpha_factor_outcome=alpha_factor_outcome,
        research_data=research_data,
        final_chunk=final_chunk,
        continuation=state,
        cancellation_check=cancellation_check,
    )


def _execute_strategy_chunk_from_validated_alpha_factor(
    *,
    run_input: RunInput,
    binding: AlphaFactorExecutionBinding,
    alpha_factor_outcome: AlphaFactorChunkOutcome,
    research_data: ColumnarResearchSeries,
    final_chunk: bool,
    continuation: dict[str, object],
    cancellation_check: Callable[[], None],
) -> StrategyChunkOutcome:
    strategy_settings = run_input.strategy
    assert strategy_settings is not None
    expected_strategy_input_checksum = _strategy_input_checksum(run_input)
    prior_binding_checksum = continuation["alpha_factor_binding_checksum"]
    prior_strategy_input_checksum = continuation["strategy_input_checksum"]
    if prior_binding_checksum is None and prior_strategy_input_checksum is None:
        continuation["alpha_factor_binding_checksum"] = binding.checksum
        continuation["strategy_input_checksum"] = expected_strategy_input_checksum
    elif (
        prior_binding_checksum != binding.checksum
        or prior_strategy_input_checksum != expected_strategy_input_checksum
    ):
        raise ValueError("Strategy continuation does not match execution input")
    strategy_started = monotonic()
    prior_strategy = continuation.get("strategy_state")
    prior_cost = Decimal(0)
    prior_daily_count = 0
    if prior_strategy is not None:
        strategy_continuation = _mapping(prior_strategy, "Strategy continuation")
        prior_daily = strategy_continuation.get("daily")
        if not isinstance(prior_daily, list) or len(prior_daily) != 1:
            raise ValueError("Strategy continuation is not bounded")
        prior_cost = Decimal(str(prior_daily[0]["cumulative_transaction_cost"]))
        prior_daily_count = 1
    else:
        strategy_continuation = None
    strategy = run_strategy_with_metric_state(
        research_data,
        alpha_factor_outcome._alpha_matrix_for_current_process(),
        calculation_definition(run_input),
        origin_session=str(run_input.research_start_session),
        terminal_cutoff=final_chunk,
        continuation=strategy_continuation,
        cancellation_check=cancellation_check,
    )
    new_daily = [dict(value) for value in strategy["daily"][prior_daily_count:]]
    new_rejections = [dict(value) for value in strategy["rejections"]]
    observations = _strategy_observations(
        new_daily,
        new_rejections,
        prior_cumulative_cost=prior_cost,
    )
    for observation in observations:
        continuation["strategy_checksum"] = _advance_checksum(
            continuation.get("strategy_checksum"), observation
        )
    metric_state = strategy.get("metric_state")
    if not isinstance(metric_state, Mapping):
        raise ValueError("Strategy calculation metric state is invalid")
    metric_state = dict(metric_state)
    metric_state["cumulative_cost"] = str(
        Decimal(str(metric_state["cumulative_cost"])).normalize()
    )
    strategy_seconds = monotonic() - strategy_started
    finalize_started = monotonic()
    completed_count = alpha_factor_outcome.completed_research_session_count
    continuation["strategy_state"] = {
        "daily": [dict(strategy["daily"][-1])],
        "positions": [dict(value) for value in strategy["positions"]],
        "orders": [],
        "child_orders": [],
        "fills": [],
        "rebalance_events": [],
        "rejections": [],
        "diagnostics": [],
        "report_session_count": completed_count,
        "metric_state": metric_state,
    }
    final_values: dict[str, object] | None = None
    if final_chunk:
        metrics = strategy_metrics_from_state(dict(metric_state))
        for metric_name, history_name in (
            ("maximum_drawdown", "series"),
            ("turnover", "events"),
            ("holdings_count", "daily"),
            ("maximum_single_name_weight", "daily"),
            ("cash_ratio", "daily"),
        ):
            metric = metrics.get(metric_name)
            if isinstance(metric, dict):
                metric.pop(history_name, None)
        terminal = dict(strategy["daily"][-1])
        factor_summary = alpha_factor_outcome._factor_summary_for_current_process()
        if factor_summary is None:
            raise ValueError("Final Alpha-and-Factor outcome is incomplete")
        final_values = {
            "factor_summary": factor_summary,
            "strategy_summary": {
                "alpha_checksum": str(
                    alpha_factor_outcome._continuation_for_current_process()[
                        "alpha_checksum"
                    ]
                ),
                "initial_cash_cny": str(strategy["initial_cash_cny"]),
                "source_checksum": str(continuation["strategy_checksum"]),
                "benchmark": {
                    "universe": run_input.universe,
                    "methodology": "selected_universe_equal_weight",
                },
                "metrics": metrics,
            },
            "terminal_strategy_state": {
                "session": str(terminal["session"]),
                "gross_cash": str(terminal["gross_cash"]),
                "net_cash": str(terminal["net_cash"]),
                "gross_nav": str(terminal["gross_nav"]),
                "net_nav": str(terminal["net_nav"]),
                "benchmark_nav": str(terminal["benchmark_nav"]),
                "cumulative_transaction_cost": str(terminal["cumulative_transaction_cost"]),
                "positions": [dict(value) for value in strategy["positions"]],
                "rebalance_phase": {
                    "origin_session": str(run_input.research_start_session),
                    "report_session_count": completed_count,
                    "rebalance_interval": strategy_settings.rebalance_interval,
                    "completed_intervals": completed_count - 1,
                },
                "pending_signal": (
                    {
                        "signal_session": str(terminal["session"]),
                        "execution": "next_research_session_open",
                    }
                    if (completed_count - 1) % strategy_settings.rebalance_interval == 0
                    else None
                ),
                "last_daily_observation": terminal,
                "metric_state": metric_state,
            },
        }
    return StrategyChunkOutcome._from_validated(
        binding=binding,
        run_input=run_input,
        continuation=continuation,
        daily_observations=observations,
        final_values=final_values,
        phase_seconds={
            "strategy": strategy_seconds,
            "finalize": monotonic() - finalize_started,
        },
    )


def execute_alpha_factor_chunk(
    *,
    run_input: RunInput,
    binding: AlphaFactorExecutionBinding,
    research_data: ColumnarResearchSeries,
    forward_labels: PreparedColumnarForwardLabels,
    research_sessions: tuple[str, ...],
    final_chunk: bool,
    continuation: Mapping[str, object],
    cancellation_check: Callable[[], None],
) -> AlphaFactorChunkOutcome:
    state = validated_alpha_factor_continuation(continuation)
    return _execute_alpha_factor_chunk_from_validated(
        run_input=run_input,
        binding=binding,
        research_data=research_data,
        forward_labels=forward_labels,
        research_sessions=research_sessions,
        final_chunk=final_chunk,
        state=state,
        cancellation_check=cancellation_check,
    )


def _execute_alpha_factor_chunk_from_validated(
    *,
    run_input: RunInput,
    binding: AlphaFactorExecutionBinding,
    research_data: ColumnarResearchSeries,
    forward_labels: PreparedColumnarForwardLabels,
    research_sessions: tuple[str, ...],
    final_chunk: bool,
    state: dict[str, object],
    cancellation_check: Callable[[], None],
) -> AlphaFactorChunkOutcome:
    alpha_started = monotonic()
    binding.require_run_input(run_input)
    prior_binding_checksum = state["binding_checksum"]
    if prior_binding_checksum is None:
        state["binding_checksum"] = binding.checksum
    elif prior_binding_checksum != binding.checksum:
        raise ValueError("Alpha-and-Factor continuation binding does not match execution")
    if not research_sessions:
        raise ValueError("Alpha-and-Factor Chunk requires Research Sessions")
    calendar = tuple(research_data.sessions)
    if any(session not in calendar for session in research_sessions):
        raise ValueError("Research Chunk sessions are outside its data slice")
    cancellation_check()
    evaluated = evaluate_columnar_alpha_sessions(
        research_data,
        compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization,
        cancellation_check=cancellation_check,
    )
    selected = set(research_sessions)
    new_alpha = [dict(row) for row in evaluated["sessions"] if str(row["session"]) in selected]
    if [str(row["session"]) for row in new_alpha] != list(research_sessions):
        raise ValueError("Research Chunk Alpha output is incomplete")
    for row in new_alpha:
        state["alpha_checksum"] = advance_alpha_checksum(
            None if state["alpha_checksum"] is None else str(state["alpha_checksum"]),
            row,
        )
    pending = state["pending_alpha"]
    if not isinstance(pending, list):
        raise ValueError("Pending Alpha continuation is invalid")
    pending.extend(
        _compact_pending_alpha(row, research_data)
        for row in new_alpha
    )
    if len(pending) > _MAX_PENDING_ALPHA_SESSIONS + len(research_sessions):
        raise ValueError("Pending Alpha continuation exceeded its bound")

    matrix_rows: list[dict[str, object]] = []
    for value in pending:
        item = _mapping(value, "Pending Alpha")
        matrix_rows.append(_expand_pending_alpha(item, research_data))
    matrix_rows.sort(key=lambda row: calendar.index(str(row["session"])))
    matrix = {
        "expression": run_input.alpha_expression_snapshot(),
        "effective_lookback": run_input.alpha_execution_plan().effective_lookback,
        "neutralization": run_input.neutralization,
        "sessions": matrix_rows,
        "checksum": state["alpha_checksum"],
    }
    last_new_index = calendar.index(research_sessions[-1])
    signal_sessions_by_horizon: dict[int, list[str]] = {}
    for horizon in HORIZONS:
        resolvable: list[str] = []
        for value in pending:
            item = _mapping(value, "Pending Alpha")
            remaining = item.get("remaining_horizons")
            if not isinstance(remaining, list) or horizon not in remaining:
                continue
            signal_session = str(item.get("session"))
            signal_index = calendar.index(signal_session)
            if final_chunk or signal_index + 1 + horizon <= last_new_index:
                resolvable.append(signal_session)
                remaining.remove(horizon)
        signal_sessions_by_horizon[horizon] = resolvable
    alpha_and_pending_seconds = monotonic() - alpha_started
    factor_started = monotonic()
    daily_by_horizon = prepared_forward_factor_days_by_horizon(
        forward_labels,
        matrix,
        signal_sessions_by_horizon=signal_sessions_by_horizon,
        cancellation_check=cancellation_check,
    )
    state["factor_state"] = advance_factor_state_from_daily(
        _mapping(state["factor_state"], "Factor state"),
        daily_by_horizon,
    )
    state["pending_alpha"] = [
        value for value in pending if _mapping(value, "Pending Alpha")["remaining_horizons"]
    ]
    if len(state["pending_alpha"]) > _MAX_PENDING_ALPHA_SESSIONS:
        raise ValueError("Pending Alpha continuation exceeded its bound")

    factor_seconds = monotonic() - factor_started
    completed_count = int(state["completed_research_session_count"]) + len(
        research_sessions
    )
    state["completed_research_session_count"] = completed_count
    lookback = max(run_input.alpha_execution_plan().effective_lookback, 2)
    state["rolling_tail_sessions"] = list(calendar[-lookback:])
    finalize_started = monotonic()
    factor_summary: dict[str, object] | None = None
    if final_chunk:
        if state["pending_alpha"]:
            raise ValueError("Final Research Chunk has unresolved Alpha Labels")
        factor_summary = finalize_factor_state(
            _mapping(state["factor_state"], "Factor state"),
            alpha_checksum=str(state["alpha_checksum"]),
        )
    summary = (
        None
        if factor_summary is None
        else _validated_factor_summary(
            factor_summary,
            alpha_checksum=str(state["alpha_checksum"]),
        )
    )
    return AlphaFactorChunkOutcome._from_validated(
        binding=binding,
        continuation=state,
        alpha_matrix=matrix,
        factor_summary=summary,
        phase_seconds={
            "alpha_and_pending": alpha_and_pending_seconds,
            "factor": factor_seconds,
            "finalize": monotonic() - finalize_started,
        },
    )


def _compact_pending_alpha(
    row: Mapping[str, object],
    research_data: ColumnarResearchSeries,
) -> dict[str, object]:
    session = str(row["session"])
    members = tuple(sorted(research_data.universe_members.get(session, ())))
    raw_values = row.get("values")
    coverage_loss = row.get("coverage_loss")
    if not isinstance(raw_values, list) or not isinstance(coverage_loss, Mapping):
        raise ValueError("Alpha Matrix session is invalid")
    items = [_mapping(value, "Alpha Matrix value") for value in raw_values]
    instrument_ids = tuple(str(item.get("instrument_id")) for item in items)
    if len(items) == len(members):
        if instrument_ids != members:
            raise ValueError("Alpha Matrix session is invalid")
        compact_values = [item.get("value") for item in items]
    else:
        compact_values: list[object] = [None] * len(members)
        member_index = 0
        prior_instrument_id: str | None = None
        for instrument_id, item in zip(instrument_ids, items, strict=True):
            if prior_instrument_id is not None and instrument_id <= prior_instrument_id:
                raise ValueError("Alpha Matrix session is invalid")
            while member_index < len(members) and members[member_index] < instrument_id:
                member_index += 1
            if member_index == len(members) or members[member_index] != instrument_id:
                raise ValueError("Alpha Matrix session is invalid")
            compact_values[member_index] = item.get("value")
            prior_instrument_id = instrument_id
    return {
        "session": session,
        "values": compact_values,
        "coverage_loss": dict(coverage_loss),
        "remaining_horizons": list(HORIZONS),
    }


def _expand_pending_alpha(
    item: Mapping[str, object],
    research_data: ColumnarResearchSeries,
) -> dict[str, object]:
    session = str(item.get("session"))
    members = tuple(sorted(research_data.universe_members.get(session, ())))
    values = item.get("values")
    coverage_loss = item.get("coverage_loss")
    if (
        not isinstance(values, list)
        or len(values) != len(members)
        or not isinstance(coverage_loss, Mapping)
    ):
        raise ValueError("Pending Alpha continuation is invalid")
    return {
        "session": session,
        "values": [
            {"instrument_id": instrument_id, "value": value}
            for instrument_id, value in zip(members, values, strict=True)
            if value is not None
        ],
        "coverage_loss": dict(coverage_loss),
    }


def empty_factor_state() -> dict[str, object]:
    return {
        "schema_version": "research-factor-aggregate-v1",
        "horizons": {
            str(horizon): {
                "signal_session_count": 0,
                "quantile_valid_session_count": 0,
                "statistics": {name: _empty_statistic() for name in _STATISTIC_NAMES},
                "label_checksum": None,
                "source_checksum": None,
            }
            for horizon in HORIZONS
        },
    }


def advance_factor_state(
    prior: Mapping[str, object],
    labels: Mapping[str, object],
) -> dict[str, object]:
    label_horizons = _mapping(labels.get("horizons"), "Label horizons")
    daily_by_horizon: dict[str, list[dict[str, object]]] = {}
    for horizon in HORIZONS:
        label_horizon = _mapping(
            label_horizons.get(str(horizon)),
            f"Label horizon {horizon}",
        )
        sessions = label_horizon.get("sessions")
        if not isinstance(sessions, list) or any(
            not isinstance(value, Mapping) for value in sessions
        ):
            raise ValueError("Label sessions are invalid")
        daily_by_horizon[str(horizon)] = []
        for session in sessions:
            samples = session.get("samples")
            if not isinstance(samples, list):
                raise ValueError("Label samples are invalid")
            daily_by_horizon[str(horizon)].append(
                {
                    "session": str(session["session"]),
                    "sample_count": len(samples),
                    **factor_day([dict(value) for value in samples]),
                }
            )
    return advance_factor_state_from_daily(prior, daily_by_horizon)


def advance_factor_state_from_daily(
    prior: Mapping[str, object],
    daily_by_horizon: Mapping[str, list[dict[str, object]]],
) -> dict[str, object]:
    state = _copy_factor_state(prior)
    for horizon in HORIZONS:
        horizon_state = _mapping(
            _mapping(state["horizons"], "Factor horizons")[str(horizon)],
            f"Factor horizon {horizon}",
        )
        statistics = _mapping(horizon_state["statistics"], "Factor statistics")
        daily_values = daily_by_horizon.get(str(horizon))
        if not isinstance(daily_values, list):
            raise ValueError("Factor daily continuation is invalid")
        for daily in daily_values:
            horizon_state["signal_session_count"] = int(horizon_state["signal_session_count"]) + 1
            if daily["quantile_reason"] is None:
                horizon_state["quantile_valid_session_count"] = (
                    int(horizon_state["quantile_valid_session_count"]) + 1
                )
            _advance_statistic(statistics["ic"], daily["ic"])
            _advance_statistic(statistics["rank_ic"], daily["rank_ic"])
            quantiles = _mapping(daily["quantile_returns"], "Factor quantiles")
            for name in ("q1", "q2", "q3", "q4", "q5"):
                _advance_statistic(statistics[name], quantiles[name])
            _advance_statistic(
                statistics["top_bottom_return"],
                daily["top_bottom_return"],
            )
            horizon_state["label_checksum"] = _advance_checksum(
                horizon_state.get("label_checksum"),
                {
                    "session": daily["session"],
                    "sample_count": daily["sample_count"],
                },
            )
            horizon_state["source_checksum"] = _advance_checksum(
                horizon_state.get("source_checksum"),
                daily,
            )
    return state


def finalize_factor_state(
    state: Mapping[str, object],
    *,
    alpha_checksum: str,
) -> dict[str, object]:
    copied = _copy_factor_state(state)
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        value = _mapping(
            _mapping(copied["horizons"], "Factor horizons")[str(horizon)],
            f"Factor horizon {horizon}",
        )
        statistics = _mapping(value["statistics"], "Factor statistics")
        ic = _correlation_summary(statistics["ic"])
        rank_ic = _correlation_summary(statistics["rank_ic"])
        horizons[str(horizon)] = {
            "horizon": horizon,
            "alpha_checksum": alpha_checksum,
            "label_checksum": value.get("label_checksum") or hashlib.sha256(b"").hexdigest(),
            "source_checksum": value.get("source_checksum") or hashlib.sha256(b"").hexdigest(),
            "summary": {
                "ic": ic,
                "rank_ic": rank_ic,
                "quantile_returns": {
                    name: _mean(statistics[name]) for name in ("q1", "q2", "q3", "q4", "q5")
                },
                "top_bottom_return": _mean(statistics["top_bottom_return"]),
            },
            "coverage": {
                "signal_session_count": int(value["signal_session_count"]),
                "ic_valid_session_count": int(ic["valid_session_count"]),
                "rank_ic_valid_session_count": int(rank_ic["valid_session_count"]),
                "quantile_valid_session_count": int(value["quantile_valid_session_count"]),
            },
        }
    return {"horizons": horizons}


def _empty_statistic() -> dict[str, object]:
    return {
        "count": 0,
        "positive_count": 0,
        "sum_numerator": 0,
        "sum_denominator": 1,
        "square_sum_numerator": 0,
        "square_sum_denominator": 1,
        "fsum_partials": [],
    }


def _advance_statistic(value: object, observation: object) -> None:
    statistic = _mapping(value, "Factor statistic")
    if observation is None:
        return
    number = float(observation)
    if not math.isfinite(number):
        raise ValueError("Factor statistic is not finite")
    total = Fraction(
        int(statistic["sum_numerator"]),
        int(statistic["sum_denominator"]),
    ) + Fraction.from_float(number)
    square_total = (
        Fraction(
            int(statistic["square_sum_numerator"]),
            int(statistic["square_sum_denominator"]),
        )
        + Fraction.from_float(number) ** 2
    )
    statistic["count"] = int(statistic["count"]) + 1
    statistic["positive_count"] = int(statistic["positive_count"]) + int(number > 0)
    statistic["sum_numerator"] = total.numerator
    statistic["sum_denominator"] = total.denominator
    statistic["square_sum_numerator"] = square_total.numerator
    statistic["square_sum_denominator"] = square_total.denominator
    partials = statistic["fsum_partials"]
    if not isinstance(partials, list):
        raise ValueError("Factor fsum continuation is invalid")
    updated: list[float] = []
    for partial in partials:
        partial_number = float(partial)
        if abs(number) < abs(partial_number):
            number, partial_number = partial_number, number
        high = number + partial_number
        low = partial_number - (high - number)
        if low:
            updated.append(low)
        number = high
    updated.append(number)
    statistic["fsum_partials"] = updated


def _mean(value: object) -> float | None:
    statistic = _mapping(value, "Factor statistic")
    count = int(statistic["count"])
    if count == 0:
        return None
    partials = statistic["fsum_partials"]
    if not isinstance(partials, list):
        raise ValueError("Factor fsum continuation is invalid")
    return math.fsum(float(value) for value in partials) / count


def _correlation_summary(value: object) -> dict[str, object]:
    statistic = _mapping(value, "Factor statistic")
    count = int(statistic["count"])
    mean = _mean(statistic)
    deviation: float | None = None
    if count >= 2:
        total = Fraction(
            int(statistic["sum_numerator"]),
            int(statistic["sum_denominator"]),
        )
        square_total = Fraction(
            int(statistic["square_sum_numerator"]),
            int(statistic["square_sum_denominator"]),
        )
        variance = (square_total - total * total / count) / (count - 1)
        deviation = math.sqrt(float(variance))
    return {
        "mean": mean,
        "sample_deviation": deviation,
        "icir": (None if mean is None or deviation in {None, 0.0} else mean / deviation),
        "positive_fraction": (None if count == 0 else int(statistic["positive_count"]) / count),
        "valid_session_count": count,
    }


def _advance_checksum(prior: object, value: object) -> str:
    checksum = hashlib.sha256()
    if prior is not None:
        checksum.update(bytes.fromhex(str(prior)))
    checksum.update(canonical_json_bytes(value))
    return checksum.hexdigest()


def _strategy_observations(
    daily: list[dict[str, object]],
    rejections: list[dict[str, object]],
    *,
    prior_cumulative_cost: Decimal,
) -> list[dict[str, object]]:
    rejection_counts: dict[str, dict[str, int]] = {}
    for rejection in rejections:
        session = str(rejection["session"])
        reason = str(rejection["reason"])
        counts = rejection_counts.setdefault(session, {})
        counts[reason] = counts.get(reason, 0) + 1
    observations: list[dict[str, object]] = []
    prior_cost = prior_cumulative_cost
    for row in daily:
        cumulative_cost = Decimal(str(row["cumulative_transaction_cost"]))
        counts = rejection_counts.get(str(row["session"]), {})
        observations.append(
            {
                "session": str(row["session"]),
                "gross_nav": str(row["gross_nav"]),
                "net_nav": str(row["net_nav"]),
                "benchmark_nav": str(row["benchmark_nav"]),
                "net_cash": str(row["net_cash"]),
                "transaction_cost_cny": canonical_decimal(cumulative_cost - prior_cost),
                "holdings_count": int(row["holdings_count"]),
                "maximum_single_name_weight": float(row["maximum_single_name_weight"]),
                "upper_limit_buy_rejections": counts.get("upper_limit_buy", 0),
                "lower_limit_sell_rejections": counts.get("lower_limit_sell", 0),
                "suspension_rejections": counts.get("suspension", 0),
            }
        )
        prior_cost = cumulative_cost
    return observations


def validated_research_continuation(
    value: Mapping[str, object],
    *,
    research_kind: str,
) -> dict[str, object]:
    import json

    try:
        copied = json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError):
        raise ValueError("Research Chunk continuation is invalid") from None
    common_keys = {
        "schema_version",
        "research_kind",
        "binding_checksum",
        "completed_research_session_count",
        "rolling_tail_sessions",
        "pending_alpha",
        "alpha_checksum",
        "factor_state",
    }
    expected_keys = (
        common_keys | _STRATEGY_CONTINUATION_KEYS
        if research_kind == "strategy_backtest"
        else common_keys
    )
    if (
        not isinstance(copied, dict)
        or copied.get("schema_version") != "research-chunk-continuation-v2"
        or copied.get("research_kind") != research_kind
        or research_kind not in {"factor_evaluation", "strategy_backtest"}
        or set(copied) != expected_keys
    ):
        raise ValueError("Research Chunk continuation is invalid")
    common = _validated_alpha_factor_continuation_mapping(
        {name: copied[name] for name in _ALPHA_FACTOR_CONTINUATION_KEYS}
    )
    copied.update(common)
    if research_kind == "strategy_backtest":
        strategy = _validated_strategy_continuation_mapping(
            {name: copied[name] for name in _STRATEGY_CONTINUATION_KEYS}
        )
        copied.update(strategy)
    return copied


def validated_alpha_factor_continuation(
    value: Mapping[str, object],
) -> dict[str, object]:
    try:
        copied = _json_mapping(
            canonical_json_bytes(value),
            "Alpha-and-Factor continuation",
        )
        return _validated_alpha_factor_continuation_mapping(copied)
    except (TypeError, ValueError):
        raise ValueError("Alpha-and-Factor continuation is invalid") from None


def validated_strategy_continuation(
    value: Mapping[str, object],
) -> dict[str, object]:
    try:
        copied = _json_mapping(
            canonical_json_bytes(value),
            "Strategy continuation",
        )
        return _validated_strategy_continuation_mapping(copied)
    except (TypeError, ValueError):
        raise ValueError("Strategy continuation is invalid") from None


def _validated_strategy_continuation_mapping(
    copied: dict[str, object],
) -> dict[str, object]:
    if set(copied) != _STRATEGY_CONTINUATION_KEYS:
        raise ValueError("Strategy continuation is invalid")
    state = copied.get("strategy_state")
    checksum = copied.get("strategy_checksum")
    binding_checksum = copied.get("alpha_factor_binding_checksum")
    strategy_input_checksum = copied.get("strategy_input_checksum")
    if (
        (state is not None and not isinstance(state, dict))
        or (checksum is not None and not _is_sha256(checksum))
        or (binding_checksum is not None and not _is_sha256(binding_checksum))
        or (strategy_input_checksum is not None and not _is_sha256(strategy_input_checksum))
        or ((state is None) != (checksum is None))
        or ((binding_checksum is None) != (strategy_input_checksum is None))
        or ((state is None) != (binding_checksum is None))
    ):
        raise ValueError("Strategy continuation is invalid")
    if state is not None:
        copied["strategy_state"] = _validated_bounded_strategy_state(state)
    return copied


def _validated_bounded_strategy_state(state: dict[str, object]) -> dict[str, object]:
    expected_keys = {
        "daily",
        "positions",
        "orders",
        "child_orders",
        "fills",
        "rebalance_events",
        "rejections",
        "diagnostics",
        "report_session_count",
        "metric_state",
    }
    daily = state.get("daily")
    positions = state.get("positions")
    report_session_count = state.get("report_session_count")
    metric_state = state.get("metric_state")
    if (
        set(state) != expected_keys
        or not isinstance(daily, list)
        or len(daily) != 1
        or not isinstance(daily[0], dict)
        or not isinstance(positions, list)
        or any(not isinstance(position, dict) for position in positions)
        or isinstance(report_session_count, bool)
        or not isinstance(report_session_count, int)
        or report_session_count < 1
        or not isinstance(metric_state, dict)
        or any(state[name] != [] for name in (
            "orders",
            "child_orders",
            "fills",
            "rebalance_events",
            "rejections",
            "diagnostics",
        ))
    ):
        raise ValueError("Strategy continuation is invalid")
    last_daily = daily[0]
    required_daily = {
        "session",
        "gross_nav",
        "net_nav",
        "gross_cash",
        "net_cash",
        "benchmark_nav",
        "cumulative_transaction_cost",
    }
    if not required_daily <= set(last_daily) or not isinstance(
        last_daily["session"], str
    ):
        raise ValueError("Strategy continuation is invalid")
    try:
        for name in required_daily - {"session"}:
            if not Decimal(str(last_daily[name])).is_finite():
                raise ValueError("Strategy continuation is invalid")
        for position in positions:
            if set(position) != {
                "instrument_id",
                "execution_shares",
                "adjusted_units",
                "last_adjusted_price",
            }:
                raise ValueError("Strategy continuation is invalid")
            if (
                not isinstance(position["instrument_id"], str)
                or isinstance(position["execution_shares"], bool)
                or not isinstance(position["execution_shares"], int)
                or position["execution_shares"] < 0
                or not Decimal(str(position["adjusted_units"])).is_finite()
                or not Decimal(str(position["last_adjusted_price"])).is_finite()
            ):
                raise ValueError("Strategy continuation is invalid")
        if (
            metric_state.get("contract") != "strategy-metric-state-v1"
            or metric_state.get("session_count") != report_session_count
            or metric_state.get("last_session") != last_daily["session"]
        ):
            raise ValueError("Strategy continuation is invalid")
        canonical_json_bytes(strategy_metrics_from_state(dict(metric_state)))
    except (ArithmeticError, KeyError, TypeError, ValueError):
        raise ValueError("Strategy continuation is invalid") from None
    return state


def _validated_alpha_factor_continuation_mapping(
    copied: dict[str, object],
) -> dict[str, object]:
    if set(copied) != _ALPHA_FACTOR_CONTINUATION_KEYS:
        raise ValueError("Alpha-and-Factor continuation is invalid")
    binding_checksum = copied.get("binding_checksum")
    completed = copied.get("completed_research_session_count")
    rolling = copied.get("rolling_tail_sessions")
    pending = copied.get("pending_alpha")
    alpha_checksum = copied.get("alpha_checksum")
    factor_state = copied.get("factor_state")
    if (
        (binding_checksum is not None and not _is_sha256(binding_checksum))
        or isinstance(completed, bool)
        or not isinstance(completed, int)
        or completed < 0
        or not isinstance(rolling, list)
        or any(not isinstance(session, str) for session in rolling)
        or not isinstance(pending, list)
        or any(not isinstance(item, dict) for item in pending)
        or (
            alpha_checksum is not None
            and (
                not isinstance(alpha_checksum, str)
                or len(alpha_checksum) != 64
                or any(character not in "0123456789abcdef" for character in alpha_checksum)
            )
        )
        or not isinstance(factor_state, dict)
    ):
        raise ValueError("Alpha-and-Factor continuation is invalid")
    copied["factor_state"] = _validated_factor_state_mapping(factor_state)
    if binding_checksum is None and (
        completed != 0
        or rolling
        or pending
        or alpha_checksum is not None
        or copied["factor_state"] != empty_factor_state()
    ):
        raise ValueError("Alpha-and-Factor continuation is invalid")
    return copied


def _validated_factor_summary(
    value: Mapping[str, object],
    *,
    alpha_checksum: str,
) -> dict[str, object]:
    try:
        copied = _json_mapping(canonical_json_bytes(value), "Factor Summary")
        horizons = _mapping(copied.get("horizons"), "Factor Summary horizons")
        if set(copied) != {"horizons"} or set(horizons) != {
            str(horizon) for horizon in HORIZONS
        }:
            raise ValueError("Factor Summary is invalid")
        for horizon in HORIZONS:
            item = _mapping(horizons[str(horizon)], f"Factor horizon {horizon}")
            summary = _mapping(item.get("summary"), "Factor metrics")
            coverage = _mapping(item.get("coverage"), "Factor coverage")
            if (
                set(item)
                != {
                    "horizon",
                    "alpha_checksum",
                    "label_checksum",
                    "source_checksum",
                    "summary",
                    "coverage",
                }
                or item.get("horizon") != horizon
                or item.get("alpha_checksum") != alpha_checksum
                or not _is_sha256(item.get("label_checksum"))
                or not _is_sha256(item.get("source_checksum"))
                or set(summary)
                != {"ic", "rank_ic", "quantile_returns", "top_bottom_return"}
                or set(coverage)
                != {
                    "signal_session_count",
                    "ic_valid_session_count",
                    "rank_ic_valid_session_count",
                    "quantile_valid_session_count",
                }
            ):
                raise ValueError("Factor Summary is invalid")
            _validate_factor_correlation(summary.get("ic"))
            _validate_factor_correlation(summary.get("rank_ic"))
            quantiles = _mapping(summary.get("quantile_returns"), "Factor quantiles")
            if set(quantiles) != {"q1", "q2", "q3", "q4", "q5"}:
                raise ValueError("Factor Summary is invalid")
            for metric in (*quantiles.values(), summary.get("top_bottom_return")):
                _validate_optional_finite_number(metric)
            for count in coverage.values():
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError("Factor Summary is invalid")
        return copied
    except (TypeError, ValueError):
        raise ValueError("Factor Summary is invalid") from None


def _validate_factor_correlation(value: object) -> None:
    correlation = _mapping(value, "Factor correlation")
    if set(correlation) != {
        "mean",
        "sample_deviation",
        "icir",
        "positive_fraction",
        "valid_session_count",
    }:
        raise ValueError("Factor Summary is invalid")
    for name in ("mean", "sample_deviation", "icir", "positive_fraction"):
        _validate_optional_finite_number(correlation[name])
    count = correlation["valid_session_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("Factor Summary is invalid")


def _validate_optional_finite_number(value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Factor Summary is invalid")
    if not math.isfinite(float(value)):
        raise ValueError("Factor Summary is invalid")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _strategy_input_checksum(run_input: RunInput) -> str:
    encoded = canonical_json_bytes(run_input.strategy_contract_snapshot())
    return hashlib.sha256(encoded).hexdigest()


def _json_mapping(value: bytes, name: str) -> dict[str, object]:
    import json

    copied = json.loads(value)
    if not isinstance(copied, dict):
        raise ValueError(f"{name} is invalid")
    return copied


def _copy_factor_state(value: Mapping[str, object]) -> dict[str, object]:
    import json

    copied = json.loads(canonical_json_bytes(value))
    if (
        not isinstance(copied, dict)
        or copied.get("schema_version") != "research-factor-aggregate-v1"
    ):
        raise ValueError("Factor aggregate state is invalid")
    return copied


def _validated_factor_state_mapping(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "research-factor-aggregate-v1"
    ):
        raise ValueError("Factor aggregate state is invalid")
    return value


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} is invalid")
    return value

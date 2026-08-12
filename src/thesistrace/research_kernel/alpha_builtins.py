from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ParameterRule = Literal["numeric", "numeric_series", "window"]
ResultRule = Literal["same_as_first", "numeric_series"]
LookbackRule = Literal["identity", "historical", "rolling"]
type NumericSeries = tuple[float | None, ...]
type NumericValue = float | None | NumericSeries
type BuiltinArgument = NumericValue | int
type BuiltinEvaluator = Callable[[tuple[BuiltinArgument, ...]], NumericValue]


@dataclass(frozen=True)
class BuiltinParameterDefinition:
    name: str
    rule: ParameterRule


@dataclass(frozen=True)
class BuiltinWorkDefinition:
    base_operations: int
    per_window_operations: int = 0


@dataclass(frozen=True)
class BuiltinDefinition:
    identifier: str
    parameters: tuple[BuiltinParameterDefinition, ...]
    result_rule: ResultRule
    description: str
    examples: tuple[str, ...]
    lookback_rule: LookbackRule
    missing_value_behavior: str
    numeric_behavior: str
    work: BuiltinWorkDefinition
    evaluator: BuiltinEvaluator

    def effective_lookback(self, child_lookback: int, window: int | None) -> int:
        if self.lookback_rule == "historical":
            assert window is not None
            return child_lookback + window
        if self.lookback_rule == "rolling":
            assert window is not None
            return child_lookback + window - 1
        return child_lookback

    def estimated_work(self, child_work: int, window: int | None) -> int:
        window_size = window or 0
        return (
            child_work + self.work.base_operations + self.work.per_window_operations * window_size
        )


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _map_numeric(
    value: BuiltinArgument,
    operation: Callable[[float], float | None],
) -> NumericValue:
    if isinstance(value, tuple):
        return tuple(
            None if item is None or not math.isfinite(item) else operation(item) for item in value
        )
    if value is None:
        return None
    finite = _finite(float(value))
    return None if finite is None else operation(finite)


def _absolute(arguments: tuple[BuiltinArgument, ...]) -> NumericValue:
    return _map_numeric(arguments[0], lambda value: _finite(abs(value)))


def _logarithm(arguments: tuple[BuiltinArgument, ...]) -> NumericValue:
    return _map_numeric(
        arguments[0],
        lambda value: None if value <= 0.0 else _finite(math.log(value)),
    )


def _sign(arguments: tuple[BuiltinArgument, ...]) -> NumericValue:
    return _map_numeric(
        arguments[0],
        lambda value: -1.0 if value < 0.0 else (1.0 if value > 0.0 else 0.0),
    )


def _series_window(arguments: tuple[BuiltinArgument, ...]) -> tuple[NumericSeries, int]:
    series, window = arguments
    if not isinstance(series, tuple) or not isinstance(window, int):
        raise TypeError("builtin received arguments that violate its compiled signature")
    return (
        tuple(None if value is None or not math.isfinite(value) else value for value in series),
        window,
    )


def _lag(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    series, window = _series_window(arguments)
    return tuple(None if index < window else series[index - window] for index in range(len(series)))


def _delta(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    series, window = _series_window(arguments)
    result: list[float | None] = []
    for index, current in enumerate(series):
        prior = None if index < window else series[index - window]
        result.append(None if current is None or prior is None else _finite(current - prior))
    return tuple(result)


def _pct_change(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    series, window = _series_window(arguments)
    result: list[float | None] = []
    for index, current in enumerate(series):
        prior = None if index < window else series[index - window]
        result.append(
            None if current is None or prior in {None, 0.0} else _finite(current / prior - 1.0)
        )
    return tuple(result)


def _rolling_total(arguments: tuple[BuiltinArgument, ...], *, mean: bool) -> NumericSeries:
    series, window = _series_window(arguments)
    result: list[float | None] = []
    buckets = [_CompensatedBucket() for _ in range(_SUM_BUCKET_COUNT)]
    missing = 0
    for index, value in enumerate(series):
        if value is None:
            missing += 1
        else:
            _update_sum_bucket(buckets, value)
        if index >= window:
            expired = series[index - window]
            if expired is None:
                missing -= 1
            else:
                _update_sum_bucket(buckets, -expired)
        complete = index + 1 >= window and missing == 0
        if not complete:
            result.append(None)
            continue
        result.append(_project_sum_buckets(buckets, divisor=window if mean else 1))
    return tuple(result)


_SUM_BUCKET_WIDTH = 32
_SUM_MIN_EXPONENT = -1074
_SUM_BUCKET_COUNT = 67


@dataclass
class _CompensatedBucket:
    total: float = 0.0
    compensation: float = 0.0

    def add(self, value: float) -> None:
        updated = self.total + value
        if abs(self.total) >= abs(value):
            self.compensation += (self.total - updated) + value
        else:
            self.compensation += (value - updated) + self.total
        self.total = updated

    def value(self) -> float:
        return math.fsum((self.total, self.compensation))


def _sum_bucket(value: float) -> tuple[int, int]:
    if value == 0.0:
        return 0, _SUM_MIN_EXPONENT
    exponent = math.frexp(value)[1]
    index = min(
        (exponent - _SUM_MIN_EXPONENT) // _SUM_BUCKET_WIDTH,
        _SUM_BUCKET_COUNT - 1,
    )
    scale_exponent = _SUM_MIN_EXPONENT + index * _SUM_BUCKET_WIDTH
    return index, scale_exponent


def _update_sum_bucket(buckets: list[_CompensatedBucket], value: float) -> None:
    index, scale_exponent = _sum_bucket(value)
    buckets[index].add(math.ldexp(value, -scale_exponent))


def _project_sum_buckets(buckets: list[_CompensatedBucket], *, divisor: int) -> float | None:
    projected: list[float] = []
    try:
        for index, bucket in enumerate(buckets):
            normalized = bucket.value() / divisor
            scale_exponent = _SUM_MIN_EXPONENT + index * _SUM_BUCKET_WIDTH
            projected.append(math.ldexp(normalized, scale_exponent))
        return _finite(math.fsum(projected))
    except OverflowError:
        return None


def _sum(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    return _rolling_total(arguments, mean=False)


def _mean(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    return _rolling_total(arguments, mean=True)


def _population_std(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    series, window = _series_window(arguments)
    result: list[float | None] = []
    count = 0
    origin = 0.0
    offset_sum = 0.0
    squared_offset_sum = 0.0
    missing = 0
    for index, value in enumerate(series):
        if value is None:
            missing += 1
        else:
            count, origin, offset_sum, squared_offset_sum = _add_centered(
                count,
                origin,
                offset_sum,
                squared_offset_sum,
                value,
            )
        if index >= window:
            expired = series[index - window]
            if expired is None:
                missing -= 1
            else:
                count, offset_sum, squared_offset_sum = _remove_centered(
                    count,
                    origin,
                    offset_sum,
                    squared_offset_sum,
                    expired,
                )
        if value is not None and count:
            origin, offset_sum, squared_offset_sum = _recenter(
                count,
                origin,
                offset_sum,
                squared_offset_sum,
                value,
            )
        if not all(math.isfinite(item) for item in (offset_sum, squared_offset_sum)):
            active = series[max(0, index - window + 1) : index + 1]
            count, origin, offset_sum, squared_offset_sum = _centered_state(active)
        if index + 1 < window or missing:
            result.append(None)
            continue
        correction = offset_sum * offset_sum / window
        numerator = squared_offset_sum - correction
        if numerator < 0.0:
            active = series[index - window + 1 : index + 1]
            count, origin, offset_sum, squared_offset_sum = _centered_state(active)
            correction = offset_sum * offset_sum / window
            numerator = squared_offset_sum - correction
        variance = numerator / window
        result.append(_finite(math.sqrt(max(variance, 0.0))))
    return tuple(result)


def _add_centered(
    count: int,
    origin: float,
    offset_sum: float,
    squared_offset_sum: float,
    value: float,
) -> tuple[int, float, float, float]:
    if count == 0:
        return 1, value, 0.0, 0.0
    offset = value - origin
    return count + 1, origin, offset_sum + offset, squared_offset_sum + offset * offset


def _remove_centered(
    count: int,
    origin: float,
    offset_sum: float,
    squared_offset_sum: float,
    value: float,
) -> tuple[int, float, float]:
    offset = value - origin
    return count - 1, offset_sum - offset, squared_offset_sum - offset * offset


def _recenter(
    count: int,
    origin: float,
    offset_sum: float,
    squared_offset_sum: float,
    new_origin: float,
) -> tuple[float, float, float]:
    shift = new_origin - origin
    previous_sum = offset_sum
    return (
        new_origin,
        previous_sum - count * shift,
        squared_offset_sum - 2.0 * shift * previous_sum + count * shift * shift,
    )


def _centered_state(
    values: tuple[float | None, ...],
) -> tuple[int, float, float, float]:
    finite = tuple(value for value in values if value is not None)
    if not finite:
        return 0, 0.0, 0.0, 0.0
    origin = finite[-1]
    offsets = tuple(value - origin for value in finite)
    try:
        return (
            len(finite),
            origin,
            math.fsum(offsets),
            math.fsum(offset * offset for offset in offsets),
        )
    except OverflowError:
        return len(finite), origin, math.inf, math.inf


def _minimum(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    return _rolling_extreme(arguments, minimum=True)


def _maximum(arguments: tuple[BuiltinArgument, ...]) -> NumericSeries:
    return _rolling_extreme(arguments, minimum=False)


def _rolling_extreme(arguments: tuple[BuiltinArgument, ...], *, minimum: bool) -> NumericSeries:
    series, window = _series_window(arguments)
    candidates: deque[tuple[int, float]] = deque()
    result: list[float | None] = []
    missing = 0
    for index, value in enumerate(series):
        if value is None:
            missing += 1
        else:
            while candidates and (
                candidates[-1][1] >= value if minimum else candidates[-1][1] <= value
            ):
                candidates.pop()
            candidates.append((index, value))
        expired_index = index - window
        if expired_index >= 0:
            expired = series[expired_index]
            if expired is None:
                missing -= 1
        while candidates and candidates[0][0] <= expired_index:
            candidates.popleft()
        complete = index + 1 >= window and missing == 0
        result.append(candidates[0][1] if complete else None)
    return tuple(result)


_VALUE = (BuiltinParameterDefinition("value", "numeric"),)
_SERIES_WINDOW = (
    BuiltinParameterDefinition("series", "numeric_series"),
    BuiltinParameterDefinition("window", "window"),
)
_ONE_STEP_WORK = BuiltinWorkDefinition(base_operations=1)
_ROLLING_WORK = BuiltinWorkDefinition(base_operations=1, per_window_operations=1)


BUILTIN_DEFINITIONS = (
    BuiltinDefinition(
        identifier="abs",
        parameters=_VALUE,
        result_rule="same_as_first",
        description="Absolute numeric value.",
        examples=("abs(close_adj)",),
        lookback_rule="identity",
        missing_value_behavior="Missing input produces a missing result.",
        numeric_behavior="Returns the non-negative magnitude of each finite input.",
        work=_ONE_STEP_WORK,
        evaluator=_absolute,
    ),
    BuiltinDefinition(
        identifier="log",
        parameters=_VALUE,
        result_rule="same_as_first",
        description="Natural logarithm; non-positive inputs are missing.",
        examples=("log(close_adj)",),
        lookback_rule="identity",
        missing_value_behavior="Missing or non-positive input produces a missing result.",
        numeric_behavior="Returns the natural logarithm of each positive finite input.",
        work=_ONE_STEP_WORK,
        evaluator=_logarithm,
    ),
    BuiltinDefinition(
        identifier="sign",
        parameters=_VALUE,
        result_rule="same_as_first",
        description="Map a numeric value to -1, 0, or 1.",
        examples=("sign(delta(close_adj, 1))",),
        lookback_rule="identity",
        missing_value_behavior="Missing input produces a missing result.",
        numeric_behavior="Maps negative, zero, and positive finite values to -1, 0, and 1.",
        work=_ONE_STEP_WORK,
        evaluator=_sign,
    ),
    BuiltinDefinition(
        identifier="lag",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Value from a prior Research Session.",
        examples=("lag(close_adj, 1)",),
        lookback_rule="historical",
        missing_value_behavior="Sessions without the requested history are missing.",
        numeric_behavior="Returns the value exactly window Research Sessions earlier.",
        work=_ONE_STEP_WORK,
        evaluator=_lag,
    ),
    BuiltinDefinition(
        identifier="delta",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Difference from a prior Research Session.",
        examples=("delta(close_adj, 5)",),
        lookback_rule="historical",
        missing_value_behavior="Missing current or lagged input produces a missing result.",
        numeric_behavior="Subtracts the value window Research Sessions earlier.",
        work=_ONE_STEP_WORK,
        evaluator=_delta,
    ),
    BuiltinDefinition(
        identifier="pct_change",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Fractional change from a prior Research Session.",
        examples=("pct_change(close_adj, 20)",),
        lookback_rule="historical",
        missing_value_behavior="Missing input or a zero lagged value produces a missing result.",
        numeric_behavior="Returns current divided by lagged value minus one.",
        work=_ONE_STEP_WORK,
        evaluator=_pct_change,
    ),
    BuiltinDefinition(
        identifier="ts_mean",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Complete-window rolling mean.",
        examples=("ts_mean(close_adj, 20)",),
        lookback_rule="rolling",
        missing_value_behavior=(
            "Any missing value in the complete window produces a missing result."
        ),
        numeric_behavior="Returns the arithmetic mean over the complete window.",
        work=_ROLLING_WORK,
        evaluator=_mean,
    ),
    BuiltinDefinition(
        identifier="ts_sum",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Complete-window rolling sum.",
        examples=("ts_sum(volume_shares, 20)",),
        lookback_rule="rolling",
        missing_value_behavior=(
            "Any missing value in the complete window produces a missing result."
        ),
        numeric_behavior="Returns the sum over the complete window.",
        work=_ROLLING_WORK,
        evaluator=_sum,
    ),
    BuiltinDefinition(
        identifier="ts_std",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Complete-window population standard deviation.",
        examples=("ts_std(close_adj, 20)",),
        lookback_rule="rolling",
        missing_value_behavior=(
            "Any missing value in the complete window produces a missing result."
        ),
        numeric_behavior="Returns population standard deviation over the complete window.",
        work=_ROLLING_WORK,
        evaluator=_population_std,
    ),
    BuiltinDefinition(
        identifier="ts_min",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Complete-window rolling minimum.",
        examples=("ts_min(close_adj, 20)",),
        lookback_rule="rolling",
        missing_value_behavior=(
            "Any missing value in the complete window produces a missing result."
        ),
        numeric_behavior="Returns the minimum finite value over the complete window.",
        work=_ROLLING_WORK,
        evaluator=_minimum,
    ),
    BuiltinDefinition(
        identifier="ts_max",
        parameters=_SERIES_WINDOW,
        result_rule="numeric_series",
        description="Complete-window rolling maximum.",
        examples=("ts_max(close_adj, 20)",),
        lookback_rule="rolling",
        missing_value_behavior=(
            "Any missing value in the complete window produces a missing result."
        ),
        numeric_behavior="Returns the maximum finite value over the complete window.",
        work=_ROLLING_WORK,
        evaluator=_maximum,
    ),
)

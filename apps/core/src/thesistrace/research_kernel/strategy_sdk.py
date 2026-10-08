"""Public authoring API, loaded only inside the isolated Python guest."""

import hashlib
import json
import math
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np
from _history_wire import decode_history
from _program_wire import array_from_wire, array_to_wire
from _thesistrace_execution import read_request


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


class Account:
    """Read-only facts from the actual execution account."""

    def __init__(self, context):
        object.__setattr__(self, "_values", _freeze({
            **context.get("account", {}),
            "fills": context.get("fills", []),
            "rejections": context.get("rejections", []),
        }))

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        raise TypeError("Account observations are read-only")


class _HistoryValues(Mapping):
    def __init__(self, history):
        self._history = history
        # The keyed view retains its canonical instrument ordering. The array
        # has its own explicit axis in the caller's requested order.
        self._rows = dict(sorted((instrument, index)
                                for index, instrument in enumerate(history.instruments)))

    def __getitem__(self, instrument):
        row = self._history.array[self._rows[instrument]].tolist()
        return tuple(None if math.isnan(value) else value for value in row)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)


class History:
    """Read-only float64 array: instruments by oldest-to-newest sessions.

    Missing observations are NaN in ``array`` and None in the keyed values view.
    Use ``array.copy()`` for writable numerical work.
    """

    def __init__(self, response):
        window = decode_history(response)
        self.sessions = window.sessions
        self.instruments = window.instruments
        self.array = window.array
        self.values = _HistoryValues(self)

    def __getitem__(self, instrument):
        return self.values[instrument]

    def items(self):
        return self.values.items()


class Data:
    def __init__(self, context):
        self.session = context.get("session")
        self.completed_sessions = context.get("completed_sessions", 0)
        self.candidates = tuple(row["instrument_id"] for row in context.get("candidates", []))
        self.instruments = tuple(context.get("value_instruments", self.candidates))
        self.candidate_details = _freeze(context.get("candidates", []))
        self.framework = _freeze(context.get("framework", {}))
        self.values = MappingProxyType(
            {name: array_from_wire(value) for name, value in context.get("values", {}).items()}
        )
        self._random_seed = context.get("random_seed", "")

    def rng(self, purpose, *, session=None):
        """A reproducible, date-addressed generator, independent of block size."""
        date = getattr(self, "session", None) if session is None else session
        allowed = (self.session,) if isinstance(self, Data) else self.sessions
        if type(purpose) is not str or not purpose or len(purpose) > 200 or date not in allowed:
            raise ValueError("rng requires a nonempty purpose and a visible output date")
        digest = hashlib.sha256(f"{self._random_seed}\0{date}\0{purpose}".encode()).digest()
        return np.random.default_rng(int.from_bytes(digest[:16], "little"))

    def history(self, field_id, days, *, instruments=None):
        """Read up to days sessions through this Close, never future observations."""
        payload = json.dumps({
            "field_id": field_id, "days": days,
            "instruments": None if instruments is None else list(instruments),
        }, allow_nan=False, separators=(",", ":")).encode()
        return History(read_request(payload))

    def common(self, name, days, *, industry=None):
        field = "common." + name + ("" if industry is None else ":" + str(industry))
        return self.history(field, days).array[0]

    def close_prices(self, days, *, instruments=None):
        return self.history("price.close.adjusted", days, instruments=instruments)


class Decision:
    def __init__(self, value):
        self.value = value


class _DecisionBuilder:
    def target_weights(self, weights, *, reason="target_weights"):
        return self._weights(weights, "rebalance", reason)

    def increase_to_weights(self, weights, *, reason="increase_to_weights"):
        """Only buy toward these portfolio weights; never sell other holdings."""
        return self._weights(weights, "increase", reason)

    def reduce_exposure(self, maximum, *, reason="reduce_exposure"):
        """Reduce existing holdings proportionally to an exposure ceiling; never buy."""
        return Decision({
            "reason": reason, "position_limits": {},
            "allocation": {"mode": "reduce", "instrument_ids": [],
                           "relative_weights": {}, "exposure": float(maximum)},
        })

    def with_limits(self, decision, *, maximum_shares=None, maximum_exposure=None):
        """Add simultaneous caps to a target; the returned decision must be returned."""
        value = dict(decision.value)
        caps = dict(value.get("position_limits", {}))
        for instrument, maximum in (maximum_shares or {}).items():
            caps[instrument] = min(caps.get(instrument, maximum), maximum)
        value["position_limits"] = caps
        if maximum_exposure is not None:
            value["maximum_stock_exposure"] = min(
                value.get("maximum_stock_exposure", 1.0), float(maximum_exposure),
            )
        return Decision(value)

    @staticmethod
    def _weights(weights, mode, reason):
        from fractions import Fraction

        ratios = {}
        for instrument, weight in weights.items():
            if type(instrument) is not str or not instrument:
                raise ValueError("Weights require instrument IDs")
            if isinstance(weight, bool):
                raise ValueError("Weights must be finite positive numbers")
            ratio = Fraction(str(weight))
            if ratio <= 0:
                raise ValueError("Weights must be positive; omit zero-weight instruments")
            ratios[instrument] = ratio
        total = sum(ratios.values(), Fraction())
        if total > 1:
            raise ValueError("Portfolio weights must sum to at most one")
        return Decision({
            "reason": reason,
            "allocation": {
                "mode": mode, "instrument_ids": list(ratios),
                "relative_weights": {key: str(value / total) for key, value in ratios.items()},
                "exposure": float(total),
            },
            "position_limits": {},
        })

    def limit_positions(self, maximum_shares, *, reason="limit_positions"):
        """Cap actual holdings in Close execution shares; omitted holdings remain."""
        return Decision({"reason": reason, "allocation": None,
                         "position_limits": dict(maximum_shares)})

    def limit_exposure(self, maximum, *, reason="limit_exposure"):
        return Decision({"reason": reason, "allocation": None, "position_limits": {},
                         "maximum_stock_exposure": float(maximum)})


class _UniverseBuilder(_DecisionBuilder):
    def select(self, instruments, *, reason="selection"):
        return Decision({"reason": reason, "instrument_ids": list(instruments)})


class _SignalBuilder(_DecisionBuilder):
    def signals(self, values, *, valid_for_sessions=1, reason="signals"):
        return Decision({"reason": reason, "signals": [
            {"instrument_id": key, "value": float(value),
             "valid_for_sessions": valid_for_sessions} for key, value in values.items()
        ]})


class _RiskBuilder(_DecisionBuilder):
    def replace(self, decision):
        return Decision({"mode": "replace", "reason": "replace",
                         "target": None if decision is None else decision.value})

    def limit_positions(self, maximum_shares, *, reason="limit_positions"):
        return Decision({"mode": "limit_positions", "reason": reason,
                         "position_limits": dict(maximum_shares)})


target_weights = _DecisionBuilder().target_weights
increase_to_weights = _DecisionBuilder().increase_to_weights
reduce_exposure = _DecisionBuilder().reduce_exposure
with_limits = _DecisionBuilder().with_limits
limit_positions = _DecisionBuilder().limit_positions
limit_exposure = _DecisionBuilder().limit_exposure
select = _UniverseBuilder().select
signals = _SignalBuilder().signals
replace = _RiskBuilder().replace
risk_limits = _RiskBuilder().limit_positions


class BatchData:
    """Numerical observations for several output dates; not an execution account."""

    def __init__(self, context):
        block = context["block"]
        self.sessions = tuple(block["sessions"])
        self.instruments = tuple(block["instruments"])
        self.session_index = np.asarray(block["session_index"], dtype=np.int64)
        self.eligible = array_from_wire(block["eligible"])
        self._random_seed = context.get("random_seed", "")
        self._cache = {}
        self._history_dates = {}

    rng = Data.rng

    def history(self, field_id, *, lookback=0):
        if type(lookback) is not int or not 0 <= lookback <= 252:
            raise ValueError("lookback must be an integer between 0 and 252")
        key = (field_id, lookback)
        if key not in self._cache:
            days = lookback + len(self.sessions)
            payload = json.dumps(
                {"field_id": field_id, "days": days, "instruments": list(self.instruments)},
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
            history = History(read_request(payload))
            if (
                history.instruments != self.instruments
                or history.sessions[-len(self.sessions) :] != self.sessions
            ):
                raise ValueError("History axes differ from the output block")
            padded = np.full((len(self.instruments), days), np.nan)
            padded[:, -len(history.sessions) :] = history.array
            self._cache[key] = np.frombuffer(padded.tobytes(), dtype="<f8").reshape(padded.shape)
            self._history_dates[key] = (None,) * (days - len(history.sessions)) + history.sessions
        return self._cache[key]

    def history_sessions(self, field_id, *, lookback=0):
        """Aligned history dates; None marks unavailable warmup positions."""
        self.history(field_id, lookback=lookback)
        return self._history_dates[(field_id, lookback)]

    def common(self, name, *, lookback=0, industry=None):
        if type(lookback) is not int or not 0 <= lookback <= 252:
            raise ValueError("lookback must be an integer between 0 and 252")
        field = "common." + name + ("" if industry is None else ":" + str(industry))
        key = (field, lookback)
        if key not in self._cache:
            days = lookback + len(self.sessions)
            history = History(
                read_request(
                    json.dumps(
                        {
                            "field_id": field,
                            "days": days,
                            "instruments": None,
                        },
                        separators=(",", ":"),
                    ).encode()
                )
            )
            if history.sessions[-len(self.sessions) :] != self.sessions:
                raise ValueError("Common input dates differ from the output block")
            padded = np.full(days, np.nan)
            padded[-len(history.sessions) :] = history.array[0]
            self._cache[key] = np.frombuffer(padded.tobytes(), dtype="<f8")
        return self._cache[key]


class Targets:
    """One portfolio column per output date; False update means no new decision."""

    def __init__(self, weights, *, update, priority=None, reason="target_weights"):
        self.weights = np.asarray(weights)
        self.update = np.asarray(update)
        self.priority = None if priority is None else np.asarray(priority)
        self.reason = reason
        self.equal = False

    @classmethod
    def equal_weight(cls, selected, *, update, priority=None, reason="target_weights"):
        selected = np.asarray(selected)
        if selected.dtype != np.dtype(bool):
            raise TypeError("equal_weight requires a boolean selection matrix")
        result = cls(selected, update=update, priority=priority, reason=reason)
        result.equal = True
        return result

    def _to_wire(self):
        priority = None
        if self.priority is not None:
            if self.priority.shape != self.weights.shape:
                raise ValueError("Targets priority must align with weights")
            selected = self.weights > 0
            # Only selected priorities affect buy order. Keep wide sparse portfolios
            # small without reducing precision or changing the author's array API.
            priority = {
                "indices": array_to_wire(np.flatnonzero(selected).astype(np.uint32)),
                "values": array_to_wire(self.priority[selected]),
            }
        return {
            "kind": "targets",
            "weights": array_to_wire(self.weights),
            "update": array_to_wire(self.update),
            "priority": priority,
            "equal": self.equal,
            "reason": self.reason,
        }


class Values:
    """Named stock-by-date or date-only results consumed by decide."""

    def __init__(self, values):
        self.values = dict(values)

    def _to_wire(self):
        return {
            "kind": "values",
            "values": {name: array_to_wire(value) for name, value in self.values.items()},
        }

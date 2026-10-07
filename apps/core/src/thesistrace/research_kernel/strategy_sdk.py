"""Public authoring API, loaded only inside the isolated Python guest."""

import json
import os
from types import MappingProxyType


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


class History:
    """Oldest-to-newest observations, keyed by instrument ID."""

    def __init__(self, response):
        self.sessions = tuple(response["sessions"])
        self.values = MappingProxyType({
            key: tuple(values) for key, values in response["values"].items()
        })

    def __getitem__(self, instrument):
        return self.values[instrument]

    def items(self):
        return self.values.items()


class Data:
    def __init__(self, context):
        self.session = context.get("session")
        self.completed_sessions = context.get("completed_sessions", 0)
        self.candidates = tuple(row["instrument_id"] for row in context.get("candidates", []))
        self.candidate_details = _freeze(context.get("candidates", []))
        self.framework = _freeze(context.get("framework", {}))

    def history(self, field_id, days, *, instruments=None):
        """Read up to days sessions through this Close, never future observations."""
        payload = json.dumps({
            "field_id": field_id, "days": days,
            "instruments": None if instruments is None else list(instruments),
        }, allow_nan=False, separators=(",", ":")).encode()
        os.write(4, payload)
        chunks = []
        while chunk := os.pread(4, 65536, 0):
            chunks.append(chunk)
        response = json.loads(b"".join(chunks))
        if "error" in response:
            raise ValueError(response["error"])
        return History(response)

    def close_prices(self, days, *, instruments=None):
        return self.history("price.close.adjusted", days, instruments=instruments)


class Decision:
    def __init__(self, value):
        self.value = value


class Strategy:
    """Implement on_close(data, account); only self.state survives invocations."""

    def on_close(self, data, account):
        raise NotImplementedError("Implement on_close(self, data, account)")

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


class UniverseSelection(Strategy):
    def select(self, instruments, *, reason="selection"):
        return Decision({"reason": reason, "instrument_ids": list(instruments)})


class Alpha(Strategy):
    def signals(self, values, *, valid_for_sessions=1, reason="signals"):
        return Decision({"reason": reason, "signals": [
            {"instrument_id": key, "value": float(value),
             "valid_for_sessions": valid_for_sessions} for key, value in values.items()
        ]})


class PortfolioConstruction(Strategy):
    pass


class RiskManagement(Strategy):
    def replace(self, decision):
        return Decision({"mode": "replace", "reason": "replace",
                         "target": None if decision is None else decision.value})

    def limit_positions(self, maximum_shares, *, reason="limit_positions"):
        return Decision({"mode": "limit_positions", "reason": reason,
                         "position_limits": dict(maximum_shares)})

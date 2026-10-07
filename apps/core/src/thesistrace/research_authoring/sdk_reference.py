"""SDK semantics beside the authoring contract; signatures read from shipped source.

Reading the AST neither imports nor executes the guest SDK on the host. Keeping
documentation outside that SDK also preserves the frozen execution identity.
"""

import ast
from functools import lru_cache
from pathlib import Path

from thesistrace.research_authoring.reference_models import (
    AuthoringExample,
    AuthoringReferenceEntry,
)
from thesistrace.research_kernel.strategy_events import StrategyFillEvent
from thesistrace.research_kernel.terminal_state_schema import (
    ActiveStrategySignal,
    PendingTarget,
    TerminalPosition,
)

SDK_OVERVIEW = (
    "Import the required base from quantgrove. Define exactly one local subclass with a "
    "zero-argument constructor and on_close(self, data, account). Direct uses Strategy; "
    "Framework uses UniverseSelection, Alpha, PortfolioConstruction and RiskManagement.",
    "Each invocation sees this Session's Close. Only the returned decision is submitted for "
    "the next Research Session Open; fills remain subject to tradability, board lots, costs "
    "and cash. Calling helpers without returning their decision has no execution effect.",
    "None is NoUpdate, target_weights({}) requests liquidation, and zero-weight entries are "
    "invalid. Data observations and the actual Account are separate from desired targets.",
    "Use get_alpha_catalog(kind='fields') for currently available fields: formulas use "
    "identifier; data.history uses field_id. Formula functions are not Python SDK functions.",
    "Only self.state persists. Class instances are recreated for each invocation. A failed "
    "invocation publishes neither changed state nor a decision. Check configuration validates "
    "syntax, class loading and callback signature, not every branch or future data request.",
    "Use NumPy on history.array for vectorized computation across instruments and history. "
    "The array axes are history.instruments and history.sessions. Account-dependent decisions "
    "still execute in Close order. Convert finite array results with tolist() or item() before "
    "putting them in the bounded JSON state.",
)


def _example(body: str, *, base: str = "Strategy") -> AuthoringExample:
    return AuthoringExample(
        title="Minimal callback", language="python", entrypoint=base,
        source=f"from quantgrove import {base}\n\nclass Example({base}):\n"
        "    def on_close(self, data, account):\n"
        + "\n".join(f"        {line}" for line in body.splitlines()) + "\n",
    )


def _entry(symbol, description, *, parameters=None, returns=None, notes=(), body=None,
           base="Strategy", data_schema=None):
    return AuthoringReferenceEntry(
        symbol=symbol, description=description, parameters=parameters or {}, returns=returns,
        notes=notes, examples=() if body is None else (_example(body, base=base),),
        data_schema=data_schema,
    )


def _sdk_entries() -> tuple[dict[str, AuthoringReferenceEntry], set[str]]:
    weights = (
        "Mapping of visible instrument IDs to finite positive portfolio weights, summing "
        "to at most 1. Omit zero weights. The unallocated fraction remains cash."
    )
    shares = (
        "Mapping of actual held instrument IDs to non-negative integer execution-share "
        "caps, no greater than the actual holding. These are not adjusted units."
    )
    reason = "Optional non-empty string, at most 512 characters, recorded with the decision."
    history = {
        "field_id": "Canonical field_id from get_alpha_catalog, not a formula identifier.",
        "days": "Integer Research Session count; see the current limits entry. May be computed.",
        "instruments": "Keyword-only iterable of unique current candidate or held IDs; None "
        "reads their union, and an empty iterable reads no instruments.",
    }
    methods = [
        _entry("Strategy.on_close", "Implement the Close callback for the required stage.",
               parameters={"data": "Data observation for the current Close.",
                           "account": "Read-only Account of actual simulated holdings."},
               returns="None or one Decision appropriate to this stage.", body="return None"),
        _entry("Strategy.target_weights", "Construct a complete portfolio target; omitted "
               "holdings exit. Empty weights explicitly request liquidation.",
               parameters={"weights": weights, "reason": reason}, returns="Decision",
               body="return self.target_weights({})"),
        _entry("Strategy.increase_to_weights", "Only buy toward these portfolio weights; "
               "never sell other holdings. This is not a complete rebalance.",
               parameters={"weights": weights, "reason": reason}, returns="Decision",
               body="if not data.candidates:\n    return None\n"
               "return self.increase_to_weights({data.candidates[0]: 0.5})"),
        _entry("Strategy.reduce_exposure", "Reduce existing holdings proportionally toward "
               "an exposure ceiling; never buy.",
               parameters={"maximum": "Finite number from 0 to 1.", "reason": reason},
               returns="Decision", body="return self.reduce_exposure(0.5)"),
        _entry("Strategy.with_limits", "Intersect a decision with simultaneous caps. "
               "Existing tighter caps remain. Return the new decision to apply it.",
               parameters={"decision": "Decision from a portfolio helper.",
                           "maximum_shares": shares + " Optional; None adds no share caps.",
                           "maximum_exposure": "Optional finite number from 0 to 1."},
               returns="A new Decision; the input decision is not modified.",
               body="if not data.candidates:\n    return None\n"
               "decision = self.target_weights({data.candidates[0]: 0.8})\n"
               "return self.with_limits(decision, maximum_exposure=0.5)"),
        _entry("Strategy.limit_positions", "Cap named actual holdings without a new "
               "allocation. Omitted holdings remain unchanged.",
               parameters={"maximum_shares": shares + " At least one entry is required.",
                           "reason": reason}, returns="Decision",
               body="if not account.positions:\n    return None\n"
               "return self.limit_positions({p['instrument_id']: 0 "
               "for p in account.positions})"),
        _entry("Strategy.limit_exposure", "Apply a total stock-exposure cap without a new "
               "allocation. It cannot request new purchases.",
               parameters={"maximum": "Finite number from 0 to 1.", "reason": reason},
               returns="Decision", body="return self.limit_exposure(0.5)"),
        _entry("UniverseSelection.select", "Replace the selected candidate set. None instead "
               "retains still-available prior selection, initially empty.",
               parameters={"instruments": "Unique current candidate IDs, bounded by "
                           "maximum_active_signals in the current limits.", "reason": reason},
               returns="Universe-stage Decision", base="UniverseSelection",
               body="return self.select(data.candidates)"),
        _entry("Alpha.signals", "Replace the signal snapshot with finite scores. None retains "
               "unexpired signals. Expiry or removal does not itself sell a holding.",
               parameters={"values": "Mapping of selected candidate IDs to finite numeric scores.",
                           "valid_for_sessions": "Positive integer; see current "
                           "signal_validity_sessions limits. Counted in Research Sessions.",
                           "reason": reason}, returns="Alpha-stage Decision", base="Alpha",
               body="return self.signals({stock: 1.0 for stock in data.candidates})"),
        _entry("RiskManagement.replace", "Replace this Close's portfolio proposal. "
               "replace(None) explicitly cancels it; returning None leaves it alone.",
               parameters={"decision": "A portfolio-helper Decision, or None to cancel."},
               returns="Risk-stage Decision", base="RiskManagement",
               body="return self.replace(self.target_weights({}))"),
        _entry("RiskManagement.limit_positions", "Intersect local holding caps with the "
               "proposal. Risk runs even when there is no new portfolio proposal.",
               parameters={"maximum_shares": shares + " At least one entry is required.",
                           "reason": reason}, returns="Risk-stage Decision", base="RiskManagement",
               body="if not account.positions:\n    return None\n"
               "return self.limit_positions({account.positions[0]['instrument_id']: 0})"),
        _entry("Data.history", "Read numeric observations through this Close from the frozen "
               "data generation. Financial values obey disclosure-time visibility.",
               parameters=history, returns="History with a read-only NumPy array and keyed values.",
               notes=("Fewer sessions may be returned at the start of the generation. "
                      "Missing observations are NaN in array and None in keyed values. "
                      "Unknown fields, out-of-scope IDs or "
                      "exceeded limits fail explicitly. No future dates can be requested.",),
               body="history = data.history('price.close.adjusted', 2)\n"
               "self.state['observations'] = len(history.sessions)\nreturn None"),
        _entry("Data.close_prices", "Read causal adjusted Close prices. Equivalent to "
               "data.history('price.close.adjusted', days, instruments=instruments).",
               parameters={name: value for name, value in history.items() if name != "field_id"},
               returns="History", body="prices = data.close_prices(2)\n"
               "self.state['observations'] = len(prices.sessions)\nreturn None"),
        _entry("History.__getitem__", "Read one instrument's observations with history[stock].",
               parameters={"instrument": "An instrument ID present in History.values."},
               returns="Tuple of float or None, aligned to History.sessions."),
        _entry("History.items", "Iterate over the instrument-to-observations mapping.",
               returns="Iterable of (instrument_id, tuple[float | None, ...]) pairs."),
    ]
    classes = [
        _entry("Strategy", "Base for Direct strategies. Implement on_close; use portfolio "
               "helpers and self.state. Return None for NoUpdate."),
        _entry("UniverseSelection", "Framework candidate-selection base, inheriting Strategy. "
               "Return select(...) or None; other stage decisions are rejected."),
        _entry("Alpha", "Framework scoring base, inheriting Strategy. Return signals(...) "
               "or None; other stage decisions are rejected."),
        _entry("PortfolioConstruction", "Framework portfolio base. Inherits Strategy callbacks, "
               "state and all portfolio helpers. None creates no new proposal."),
        _entry("RiskManagement", "Framework risk base. Return None, limit_positions(...) or "
               "replace(portfolio_decision). Wrap inherited portfolio helper decisions in "
               "replace(...); they are not standalone Risk outputs."),
        _entry("Data", "Current Close observations and bounded historical reads. "
               "Attributes assigned locally do not change the host's date or data authority."),
        _entry("Account", "Recursively read-only actual simulated account. Money and exact "
               "accounting quantities are decimal strings; use decimal.Decimal for arithmetic."),
        _entry("History", "Historical observations as a read-only float64 array with explicit "
               "instrument/session axes, and a keyed view of float-or-None tuples."),
        _entry("Decision", "Value returned by SDK helpers. Only the Decision returned by "
               "on_close is submitted. The host independently validates it and its stage."),
    ]
    attributes = [
        _entry("Strategy.state", "Bounded JSON object restored after construction and before "
               "on_close. Modify in place; do not rely on it in the constructor. Each Run, "
               "Batch item and Framework stage has its own state. DailyTrack continues it."),
        _entry("Data.session", "ISO YYYY-MM-DD string: the current Close decision date."),
        _entry("Data.completed_sessions", "Integer decision number since the original "
               "research start, including this Session (first decision is 1)."),
        _entry("Data.candidates", "Tuple of currently permitted candidate instrument ID strings. "
               "Framework stages after selection see that stage's selected universe."),
        _entry("Data.candidate_details", "Tuple of read-only mappings: instrument_id (string), "
               "board (string), industry (industry code or None). Same order as candidates."),
        _entry("Data.framework", "Read-only mapping, empty for Direct. Framework keys: universe "
               "(tuple of IDs), signals (tuple of ActiveStrategySignal mappings), universe_changed "
               "and signals_updated (bool), expired_signals and removed_signals (tuples of IDs), "
               "proposal and retained_proposal (PendingTarget mapping or None). The retained "
               "proposal is historical reference and is never replayed implicitly."),
        _entry("History.sessions", "Tuple of ISO dates from oldest to newest, ending no later "
               "than the current Close. May contain fewer dates than requested."),
        _entry("History.values", "Read-only mapping: instrument ID -> tuple of float or None. "
               "Keys iterate in canonical instrument-ID order. Every tuple aligns to "
               "History.sessions. No missing value is silently filled."),
        _entry("History.instruments", "Tuple of IDs aligned to the rows of History.array. "
               "Explicit instrument requests retain their order; the default scope is sorted."),
        _entry("History.array", "Read-only NumPy float64 ndarray with shape "
               "(len(history.instruments), len(history.sessions)). Missing observations are NaN.",
               notes=("Use array.copy() for writable work. Vectorization does not change "
                      "the current Close, permitted instruments or history limits.",),
               body="import numpy as np\n"
               "history = data.close_prices(2)\n"
               "if len(history.sessions) < 2 or not history.instruments:\n    return None\n"
               "prices = history.array\n"
               "valid = np.isfinite(prices[:, 0]) & np.isfinite(prices[:, -1]) "
               "& (prices[:, 0] > 0)\n"
               "returns = prices[valid, -1] / prices[valid, 0] - 1\n"
               "self.state['returns'] = returns.tolist()\nreturn None"),
        _entry("Account.cash_cny", "Available cash as a decimal CNY string."),
        _entry("Account.post_open_net_nav_cny", "Net NAV marked after this Session's Open "
               "execution, as a decimal CNY string."),
        _entry("Account.close_risk_nav_cny", "Net account value marked at this Session's Close "
               "for risk decisions, as a decimal CNY string."),
        _entry("Account.positions", "Tuple of actual holding mappings. execution_shares are "
               "integer shares; adjusted_units and price/cost quantities are decimal strings. "
               "last_adjusted_price is the Open mark; last_close_adjusted_price is the Close "
               "mark. holding_age counts Sessions including the first actual purchase.",
               data_schema=TerminalPosition.model_json_schema()),
        _entry("Account.fills", "Tuple of actual fill mappings from this Session; includes "
               "IDs, side, quantity, execution prices, fees, settlement and accounting deltas.",
               data_schema=StrategyFillEvent.model_json_schema()),
        _entry("Account.rejections", "Tuple of rejected-order mappings from this Session. "
               "Fields: order_id, session, instrument_id, side ('buy' or 'sell'), intended_value "
               "(decimal string), reason ('suspension', 'data_unavailable', 'upper_limit_buy', "
               "'lower_limit_sell'). quantity is an integer when known and may be absent."),
        _entry("Decision.value", "Helper-built decision payload. Return the Decision object, "
               "not this mapping. Payload shape depends on the stage; the host validates it."),
        _entry("ActiveStrategySignal", "One data.framework['signals'] mapping. created_session "
               "and created_session_number define its Research Session lifetime.",
               data_schema=ActiveStrategySignal.model_json_schema()),
        _entry("PendingTarget", "Read-only proposal shape in data.framework. Coordinates are "
               "supplied by the host; use SDK helpers to construct new decisions.",
               data_schema=PendingTarget.model_json_schema()),
    ]
    return ({entry.symbol: entry for entry in [*classes, *methods, *attributes]},
            {entry.symbol for entry in methods})


@lru_cache(maxsize=1)
def sdk_reference_entries() -> tuple[AuthoringReferenceEntry, ...]:
    entries, documented_methods = _sdk_entries()
    public_methods = set()
    source = Path(__file__).parents[1] / "research_kernel" / "strategy_sdk.py"
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        # Missing documentation for a newly published class/method fails here and in CI.
        entries[node.name]
        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            if method.name.startswith("_") and method.name != "__getitem__":
                continue
            symbol = f"{node.name}.{method.name}"
            public_methods.add(symbol)
            entry = entries[symbol]
            parameter_names = {
                argument.arg for argument in [*method.args.posonlyargs, *method.args.args,
                                              *method.args.kwonlyargs]
                if argument.arg != "self"
            }
            if parameter_names != set(entry.parameters):
                raise ValueError(f"SDK reference parameters differ from {symbol}")
            entries[symbol] = entry.model_copy(update={
                "signature": f"{symbol}({ast.unparse(method.args)})",
            })
    if public_methods != documented_methods:
        raise ValueError("SDK reference contains a removed public method")
    return tuple(entries[name] for name in sorted(entries))

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
    "Define compute(data, state) for a real block of up to 128 output dates. Return Targets "
    "directly, or Values with optional decide(data, account, state). No strategy-class base "
    "is required.",
    "compute receives ordinary NumPy arrays, not an expression compiler. data.history(field_id, "
    "lookback=L) returns instruments by L+T dates; "
    "data.eligible identifies each date's candidates.",
    "Optional decide sees only current values and the actual account. Framework modules use decide "
    "and may precompute Values. Only returned decisions execute at the following Open.",
    "False Targets.update means no new decision; an updated zero column means liquidation. "
    "target_weights({}) likewise requests liquidation; None creates no decision.",
    "Computation and decisions have separate explicit state. JSON containers and numeric arrays "
    "can be saved; globals and caches are not durable. Failed blocks publish no partial state.",
    "Batch code must be causal and invariant to partition size. Raw multi-date arrays allow "
    "lookahead mistakes; read-only data and configuration checking do not prove absence of them.",
    "Use date-addressed data.rng(purpose, session=...) for partition-independent randomness. "
    "Read the user guide docs/python-strategy.md before writing rolling or stateful programs.",
)


def _example(body: str) -> AuthoringExample:
    helpers = (
        "target_weights, increase_to_weights, reduce_exposure, with_limits, "
        "limit_positions, limit_exposure, select, signals, replace, risk_limits"
    )
    return AuthoringExample(
        title="Current Close decision",
        language="python",
        entrypoint="decide",
        source=f"from quantgrove import {helpers}\n\ndef decide(data, account, state):\n"
        + "\n".join(f"    {line}" for line in body.splitlines())
        + "\n",
    )


def _entry(symbol, description, *, parameters=None, returns=None, notes=(), body=None,
           data_schema=None):
    return AuthoringReferenceEntry(
        symbol=symbol, description=description, parameters=parameters or {}, returns=returns,
        notes=notes, examples=() if body is None else (_example(body),),
        data_schema=data_schema,
    )


def _sdk_entries() -> dict[str, AuthoringReferenceEntry]:
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
        _entry(
            "target_weights",
            "Construct a complete portfolio target; omitted "
            "holdings exit. Empty weights explicitly request liquidation.",
            parameters={"weights": weights, "reason": reason},
            returns="Decision",
            body="return target_weights({})",
        ),
        _entry(
            "increase_to_weights",
            "Only buy toward these portfolio weights; "
            "never sell other holdings. This is not a complete rebalance.",
            parameters={"weights": weights, "reason": reason},
            returns="Decision",
            body="if not data.candidates:\n    return None\n"
            "return increase_to_weights({data.candidates[0]: 0.5})",
        ),
        _entry(
            "reduce_exposure",
            "Reduce existing holdings proportionally toward an exposure ceiling; never buy.",
            parameters={"maximum": "Finite number from 0 to 1.", "reason": reason},
            returns="Decision",
            body="return reduce_exposure(0.5)",
        ),
        _entry(
            "with_limits",
            "Intersect a decision with simultaneous caps. "
            "Existing tighter caps remain. Return the new decision to apply it.",
            parameters={
                "decision": "Decision from a portfolio helper.",
                "maximum_shares": shares + " Optional; None adds no share caps.",
                "maximum_exposure": "Optional finite number from 0 to 1.",
            },
            returns="A new Decision; the input decision is not modified.",
            body="if not data.candidates:\n    return None\n"
            "decision = target_weights({data.candidates[0]: 0.8})\n"
            "return with_limits(decision, maximum_exposure=0.5)",
        ),
        _entry(
            "limit_positions",
            "Cap named actual holdings without a new "
            "allocation. Omitted holdings remain unchanged.",
            parameters={
                "maximum_shares": shares + " At least one entry is required.",
                "reason": reason,
            },
            returns="Decision",
            body="if not account.positions:\n    return None\n"
            "return limit_positions({p['instrument_id']: 0 "
            "for p in account.positions})",
        ),
        _entry(
            "limit_exposure",
            "Apply a total stock-exposure cap without a new "
            "allocation. It cannot request new purchases.",
            parameters={"maximum": "Finite number from 0 to 1.", "reason": reason},
            returns="Decision",
            body="return limit_exposure(0.5)",
        ),
        _entry(
            "select",
            "Replace the selected candidate set. None instead "
            "retains still-available prior selection, initially empty.",
            parameters={
                "instruments": "Unique current candidate IDs, bounded by "
                "maximum_active_signals in the current limits.",
                "reason": reason,
            },
            returns="Universe-stage Decision",
            body="return select(data.candidates)",
        ),
        _entry(
            "signals",
            "Replace the signal snapshot with finite scores. None retains "
            "unexpired signals. Expiry or removal does not itself sell a holding.",
            parameters={
                "values": "Mapping of selected candidate IDs to finite numeric scores.",
                "valid_for_sessions": "Positive integer; see current "
                "signal_validity_sessions limits. Counted in Research Sessions.",
                "reason": reason,
            },
            returns="Alpha-stage Decision",
            body="return signals({stock: 1.0 for stock in data.candidates})",
        ),
        _entry(
            "replace",
            "Replace this Close's portfolio proposal. "
            "replace(None) explicitly cancels it; returning None leaves it alone.",
            parameters={"decision": "A portfolio-helper Decision, or None to cancel."},
            returns="Risk-stage Decision",
            body="return replace(target_weights({}))",
        ),
        _entry(
            "risk_limits",
            "Intersect local holding caps with the "
            "proposal. Risk runs even when there is no new portfolio proposal.",
            parameters={
                "maximum_shares": shares + " At least one entry is required.",
                "reason": reason,
            },
            returns="Risk-stage Decision",
            body="if not account.positions:\n    return None\n"
            "return risk_limits({account.positions[0]['instrument_id']: 0})",
        ),
        _entry(
            "Data.history",
            "Read numeric observations through this Close from the frozen "
            "data generation. Financial values obey disclosure-time visibility.",
            parameters=history,
            returns="History with a read-only NumPy array and keyed values.",
            notes=(
                "Fewer sessions may be returned at the start of the generation. "
                "Missing observations are NaN in array and None in keyed values. "
                "Unknown fields, out-of-scope IDs or "
                "exceeded limits fail explicitly. No future dates can be requested.",
            ),
            body="history = data.history('price.close.adjusted', 2)\n"
            "state['observations'] = len(history.sessions)\nreturn None",
        ),
        _entry(
            "Data.close_prices",
            "Read causal adjusted Close prices. Equivalent to "
            "data.history('price.close.adjusted', days, instruments=instruments).",
            parameters={name: value for name, value in history.items() if name != "field_id"},
            returns="History",
            body="prices = data.close_prices(2)\n"
            "state['observations'] = len(prices.sessions)\nreturn None",
        ),
        _entry(
            "History.__getitem__",
            "Read one instrument's observations with history[stock].",
            parameters={"instrument": "An instrument ID present in History.values."},
            returns="Tuple of float or None, aligned to History.sessions.",
        ),
        _entry(
            "History.items",
            "Iterate over the instrument-to-observations mapping.",
            returns="Iterable of (instrument_id, tuple[float | None, ...]) pairs.",
        ),
    ]
    classes = [
        _entry(
            "Data",
            "Current Close observations and bounded historical reads. "
            "Attributes assigned locally do not change the host's date or data authority.",
        ),
        _entry(
            "Account",
            "Recursively read-only actual simulated account. Money and exact "
            "accounting quantities are decimal strings; use decimal.Decimal for arithmetic.",
        ),
        _entry(
            "History",
            "Historical observations as a read-only float64 array with explicit "
            "instrument/session axes, and a keyed view of float-or-None tuples.",
        ),
        _entry(
            "Decision",
            "Value returned by SDK helpers. Only the Decision returned by "
            "decide is submitted. The host independently validates it and its stage.",
        ),
    ]
    attributes = [
        _entry("Data.session", "ISO YYYY-MM-DD string: the current Close decision date."),
        _entry(
            "Data.completed_sessions",
            "Integer decision number since the original "
            "research start, including this Session (first decision is 1).",
        ),
        _entry(
            "Data.candidates",
            "Tuple of currently permitted candidate instrument ID strings. "
            "Framework stages after selection see that stage's selected universe.",
        ),
        _entry(
            "Data.candidate_details",
            "Tuple of read-only mappings: instrument_id (string), "
            "board (string), industry (industry code or None when unassigned). "
            "Industry metadata comes from the pinned data regardless of neutralization, "
            "standalone or batch execution. Same order as candidates.",
        ),
        _entry(
            "Data.framework",
            "Read-only mapping, empty for Direct. Framework keys: universe "
            "(tuple of IDs), signals (tuple of ActiveStrategySignal mappings), universe_changed "
            "and signals_updated (bool), expired_signals and removed_signals (tuples of IDs), "
            "proposal and retained_proposal (PendingTarget mapping or None). The retained "
            "proposal is historical reference and is never replayed implicitly.",
        ),
        _entry(
            "History.sessions",
            "Tuple of ISO dates from oldest to newest, ending no later "
            "than the current Close. May contain fewer dates than requested.",
        ),
        _entry(
            "History.values",
            "Read-only mapping: instrument ID -> tuple of float or None. "
            "Keys iterate in canonical instrument-ID order. Every tuple aligns to "
            "History.sessions. No missing value is silently filled.",
        ),
        _entry(
            "History.instruments",
            "Tuple of IDs aligned to the rows of History.array. "
            "Explicit instrument requests retain their order; the default scope is sorted.",
        ),
        _entry(
            "History.array",
            "Read-only NumPy float64 ndarray with shape "
            "(len(history.instruments), len(history.sessions)). Missing observations are NaN.",
            notes=(
                "Use array.copy() for writable work. Vectorization does not change "
                "the current Close, permitted instruments or history limits.",
            ),
            body="import numpy as np\n"
            "history = data.close_prices(2)\n"
            "if len(history.sessions) < 2 or not history.instruments:\n    return None\n"
            "prices = history.array\n"
            "valid = np.isfinite(prices[:, 0]) & np.isfinite(prices[:, -1]) "
            "& (prices[:, 0] > 0)\n"
            "returns = prices[valid, -1] / prices[valid, 0] - 1\n"
            "state['returns'] = returns.tolist()\nreturn None",
        ),
        _entry("Account.cash_cny", "Available cash as a decimal CNY string."),
        _entry(
            "Account.post_open_net_nav_cny",
            "Net NAV marked after this Session's Open execution, as a decimal CNY string.",
        ),
        _entry(
            "Account.close_risk_nav_cny",
            "Net account value marked at this Session's Close "
            "for risk decisions, as a decimal CNY string.",
        ),
        _entry(
            "Account.positions",
            "Tuple of actual holding mappings. execution_shares are "
            "integer shares; adjusted_units and price/cost quantities are decimal strings. "
            "last_adjusted_price is the Open mark; last_close_adjusted_price is the Close "
            "mark. holding_age counts Sessions including the first actual purchase.",
            data_schema=TerminalPosition.model_json_schema(),
        ),
        _entry(
            "Account.fills",
            "Tuple of actual fill mappings from this Session; includes "
            "IDs, side, quantity, execution prices, fees, settlement and accounting deltas.",
            data_schema=StrategyFillEvent.model_json_schema(),
        ),
        _entry(
            "Account.rejections",
            "Tuple of rejected-order mappings from this Session. "
            "Fields: order_id, session, instrument_id, side ('buy' or 'sell'), intended_value "
            "(decimal string), reason ('suspension', 'data_unavailable', 'upper_limit_buy', "
            "'lower_limit_sell'). quantity is an integer when known and may be absent.",
        ),
        _entry(
            "Decision.value",
            "Helper-built decision payload. Return the Decision object, "
            "not this mapping. Payload shape depends on the stage; the host validates it.",
        ),
        _entry(
            "ActiveStrategySignal",
            "One data.framework['signals'] mapping. created_session "
            "and created_session_number define its Research Session lifetime.",
            data_schema=ActiveStrategySignal.model_json_schema(),
        ),
        _entry(
            "PendingTarget",
            "Read-only proposal shape in data.framework. Coordinates are "
            "supplied by the host; use SDK helpers to construct new decisions.",
            data_schema=PendingTarget.model_json_schema(),
        ),
    ]
    extra = [
        _entry(
            "compute",
            "Compute multiple output dates with ordinary Python and NumPy.",
            parameters={
                "data": "BatchData observations.",
                "state": "Separate persistent compute memory.",
            },
            returns="Targets, or Values when decide is defined.",
        ),
        _entry(
            "decide",
            "Optional actual-account decision at the current Close.",
            parameters={
                "data": "Current Data including data.values.",
                "account": "Read-only actual account.",
                "state": "Separate persistent decision memory.",
            },
            returns="Decision or None",
        ),
        _entry(
            "state",
            (
                'Platform-supplied memory; JSON containers and numeric arrays'
                '. Compute and decision states are isolated, bounded together'
                ' and atomically checkpointed.'
            ),
        ),
        _entry("BatchData", "A bounded block of output dates and source-only dynamic reads."),
        _entry(
            "BatchData.history",
            "Read a numeric field over L history slots plus T output dates.",
            parameters={
                "field_id": "Numeric catalog field ID.",
                "lookback": "0..252 preceding sessions.",
            },
            returns="Read-only float64 ndarray, instruments by lookback+T; missing values are NaN.",
        ),
        _entry(
            "BatchData.history_sessions",
            "Aligned oldest-to-newest date coordinates for history; absent warmup dates are None.",
            parameters={"field_id": history["field_id"], "lookback": "Integer from 0 to 252."},
            returns="Tuple of L+T ISO dates or None; reuses the matching history read.",
        ),
        _entry(
            "BatchData.common",
            "Formula-identical market/industry aggregation with historical membership.",
            parameters={
                "name": (
                    "universe_return, universe_advancing_fraction, industry_return or "
                    "industry_advancing_fraction."
                ),
                "lookback": "0..252 preceding slots.",
                "industry": ("Required canonical SW2021 L1 code for industry inputs; "
                             "otherwise None."),
            },
            returns="Read-only float64 time vector with lookback+T elements.",
        ),
        _entry(
            "Data.common",
            "Formula-identical common inputs ending at the current Close.",
            parameters={
                "name": "Common input name.",
                "days": "Requested historical session count.",
                "industry": "SW2021 L1 code for industry inputs; otherwise None.",
            },
            returns="Read-only float64 time vector; history may be shorter than requested.",
        ),
        _entry(
            "BatchData.rng",
            "Create a reproducible generator addressed by date and purpose.",
            parameters={
                "purpose": "Stable string naming the use.",
                "session": "One output date; required for a block.",
            },
            returns="numpy.random.Generator",
        ),
        _entry(
            "Data.rng",
            "Create a reproducible generator addressed by date and purpose.",
            parameters={
                "purpose": "Stable string naming the use.",
                "session": "Optional current date.",
            },
            returns="numpy.random.Generator",
        ),
        _entry(
            "Targets",
            "Multi-date complete portfolio targets. weights is N by T; update is T booleans.",
            parameters={
                "weights": "N by T finite nonnegative weights; each column totals at most one.",
                "update": "T boolean flags.",
                "priority": (
                    "Optional N by T priorities: higher first then ID; selected values finite."
                ),
                "reason": reason,
            },
        ),
        _entry(
            "Targets.equal_weight",
            "Construct exact equal allocations from a boolean selection matrix.",
            parameters={
                "selected": "N by T boolean selection.",
                "update": "T boolean flags.",
                "priority": (
                    "Optional N by T priorities: higher first then ID; selected values finite."
                ),
                "reason": reason,
            },
            returns="Targets",
        ),
        _entry(
            "Values",
            "Named N by T or T numerical/boolean results for decide, with NaN for missing.",
        ),
        _entry("BatchData.sessions", "Tuple of this block's output dates."),
        _entry(
            "BatchData.instruments", "Canonical instrument axis; do not persist row indices as IDs."
        ),
        _entry(
            "BatchData.session_index",
            "Zero-based origin-relative ordinals, never reset by a chunk.",
        ),
        _entry("BatchData.eligible", "Read-only N by T point-in-time candidate membership."),
        _entry(
            "Data.values", "Read-only current-date values. Stock arrays align to data.instruments."
        ),
        _entry(
            "Data.instruments",
            "Current visible instrument axis for values, including actual holdings.",
        ),
        _entry(
            "Targets.weights",
            "N by T target matrix; finite nonnegative weights. Total at most one.",
        ),
        _entry(
            "Targets.update",
            "T boolean flags. False is NoUpdate; True with zero weights is liquidation.",
        ),
        _entry(
            "Targets.priority",
            "Optional N by T buy priority. Higher first, ID breaks ties; None uses ID order. "
            "Cash-limited fills depend on this order; pass scores to match ranked selection.",
        ),
        _entry("Targets.reason", "Decision reason recorded with each submitted target."),
        _entry(
            "Targets.equal", "Whether exact equal allocation is used; construct with equal_weight."
        ),
        _entry("Values.values", "Named numerical result matrices aligned to the current block."),
    ]
    entries = {entry.symbol: entry for entry in [*classes, *methods, *attributes, *extra]}
    return entries


@lru_cache(maxsize=1)
def sdk_reference_entries() -> tuple[AuthoringReferenceEntry, ...]:
    entries = _sdk_entries()
    source = Path(__file__).parents[1] / "research_kernel" / "strategy_sdk.py"
    nodes = ast.parse(source.read_text(encoding="utf-8")).body
    classes = {node.name: node for node in nodes if isinstance(node, ast.ClassDef)}
    for node in nodes:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            entries[node.name]
            for method in node.body:
                if not isinstance(method, ast.FunctionDef) or (
                    method.name.startswith("_") and method.name != "__getitem__"
                ):
                    continue
                symbol = f"{node.name}.{method.name}"
                parameters = {
                    arg.arg
                    for arg in [
                        *method.args.posonlyargs,
                        *method.args.args,
                        *method.args.kwonlyargs,
                    ]
                    if arg.arg not in {"self", "cls"}
                }
                if parameters != set(entries[symbol].parameters):
                    raise ValueError(f"SDK reference parameters differ from {symbol}")
                entries[symbol] = entries[symbol].model_copy(
                    update={
                        "signature": f"{symbol}({ast.unparse(method.args)})",
                    }
                )
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and not node.targets[0].id.startswith("_")
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Call)
        ):
            symbol = node.targets[0].id
            owner = classes[node.value.value.func.id]
            method = next(
                fn
                for fn in owner.body
                if isinstance(fn, ast.FunctionDef) and fn.name == node.value.attr
            )
            method.args.args = method.args.args[1:]
            parameters = {arg.arg for arg in [*method.args.args, *method.args.kwonlyargs]}
            if parameters != set(entries[symbol].parameters):
                raise ValueError(f"SDK reference parameters differ from {symbol}")
            entries[symbol] = entries[symbol].model_copy(
                update={
                    "signature": f"{symbol}({ast.unparse(method.args)})",
                }
            )
    return tuple(entries[name] for name in sorted(entries))

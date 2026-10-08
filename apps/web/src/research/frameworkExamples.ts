import type { FrameworkStage } from "./frameworkModules";
import type { ProgramInputs } from "./pythonStrategy";

const sources: Record<FrameworkStage, string> = {
  universe_selection: `from quantgrove import select


def decide(data, account, state):
    return select(data.candidates)
`,
  alpha: `import numpy as np
from quantgrove import Values, signals


def compute(data, state):
    close = data.history("price.close.adjusted", lookback=60)
    now, before = close[:, 60:], close[:, :-60]
    scores = np.full(now.shape, np.nan)
    valid = data.eligible & np.isfinite(now) & np.isfinite(before) & (before > 0)
    np.divide(now, before, out=scores, where=valid)
    scores -= 1
    return Values({"score": scores})


def decide(data, account, state):
    scores = data.values["score"]
    return signals({stock: float(value) for stock, value in zip(data.instruments, scores)
                    if stock in data.candidates and np.isfinite(value)}, valid_for_sessions=1)
`,
  portfolio_construction: `from quantgrove import target_weights


def decide(data, account, state):
    scores = {row["instrument_id"]: row["value"] for row in data.framework["signals"]}
    if not scores:
        return None
    best = min(scores, key=lambda stock: (-scores[stock], stock))
    if [row["instrument_id"] for row in account.positions] != [best]:
        return target_weights({best: 1})
    return None
`,
  risk_management: `from quantgrove import risk_limits


def decide(data, account, state):
    exits = {row["instrument_id"]: 0 for row in account.positions if row["holding_age"] >= 20}
    return risk_limits(exits) if exits else None
`,
};

export function frameworkExample(stage: FrameworkStage): ProgramInputs {
  return { programSource: sources[stage] };
}

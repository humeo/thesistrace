import type { FrameworkStage } from "./frameworkModules";
import type { ProgramInputs } from "./pythonStrategy";

const sources: Record<FrameworkStage, string> = {
  universe_selection: `def decide(context, state, parameters):
    instruments = [row["instrument_id"] for row in context["candidates"]]
    return {"output": {"reason": "available_candidates", "instrument_ids": instruments},
            "state": state}
`,
  alpha: `def decide(context, state, parameters):
    history = context["history"]
    prices = history["fields"]["price.close.adjusted"]
    candidates = {row["instrument_id"] for row in context["candidates"]}
    signals = []
    for instrument, closes in zip(history["instruments"], prices):
        if (instrument in candidates and closes[0] is not None
                and closes[-1] is not None and closes[0] > 0):
            signals.append({"instrument_id": instrument,
                            "value": closes[-1] / closes[0] - 1,
                            "valid_for_sessions": parameters["valid_for_sessions"]})
    return {"output": {"reason": "momentum_signals", "signals": signals}, "state": state}
`,
  portfolio_construction: `def decide(context, state, parameters):
    scores = {row["instrument_id"]: row["value"] for row in context["framework"]["signals"]}
    held = [row["instrument_id"] for row in context["account"]["positions"]]
    output = None
    if scores:
        best = max(scores, key=lambda item: (scores[item], item))
        held_score = max((scores.get(item, -1) for item in held), default=-1)
        if best not in held and (not held or scores[best] > held_score + parameters["improvement"]):
            output = {
                "reason": "better_signal_candidate",
                "allocation": {"mode": "rebalance", "instrument_ids": [best],
                               "relative_weights": {best: "1"}, "exposure": 1.0},
                "position_limits": {},
            }
    return {"output": output, "state": state}
`,
  risk_management: `def decide(context, state, parameters):
    exits = set(parameters["exit_instruments"])
    limits = {row["instrument_id"]: 0 for row in context["account"]["positions"]
              if row["instrument_id"] in exits}
    output = None
    if limits:
        output = {"mode": "limit_positions", "reason": "explicit_exit",
                  "position_limits": limits}
    return {"output": output, "state": state}
`,
};

export function frameworkExample(stage: FrameworkStage): ProgramInputs {
  return {
    programSource: sources[stage],
    programParameters: stage === "alpha" ? '{"valid_for_sessions": 2}'
      : stage === "portfolio_construction" ? '{"improvement": 0.02}'
        : stage === "risk_management" ? '{"exit_instruments": []}' : "{}",
    programFields: stage === "alpha" ? "price.close.adjusted" : "",
    programHistorySessions: stage === "alpha" ? "6" : "1",
  };
}

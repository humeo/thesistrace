import { describe, expect, it } from "vitest";
import { emptyResearchDraft, loadResearchDraftState, persistResearchDraft, researchDraftKey,
  researchInputs, type ResearchDraft } from "./draft";
import { DIRECT_EXAMPLE } from "./pythonStrategy";

// The built-in example saved by the previous function-based editor.
const previousExample = `def decide(context, state, parameters):
    history = context["history"]
    prices = history["fields"]["price.close.adjusted"]
    candidates = {row["instrument_id"] for row in context["candidates"]}
    scores = {}
    for instrument, closes in zip(history["instruments"], prices):
        if closes[0] is not None and closes[-1] is not None and closes[0] > 0:
            scores[instrument] = closes[-1] / closes[0] - 1
    eligible = [item for item in scores if item in candidates]
    output = None
    if eligible:
        best = max(eligible, key=lambda item: (scores[item], item))
        held = [row["instrument_id"] for row in context["account"]["positions"]]
        held_score = max((scores.get(item, -1) for item in held), default=-1)
        if best not in held and (not held or scores[best] > held_score + parameters["improvement"]):
            output = {
                "reason": "better_momentum_candidate",
                "allocation": {"mode": "rebalance", "instrument_ids": [best],
                               "relative_weights": {best: "1"}, "exposure": 1.0},
                "position_limits": {},
            }
    state["decisions"] = state.get("decisions", 0) + 1
    return {"output": output, "state": state}
`;

function draftStorage() {
  const entries = new Map<string, string>();
  return {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => { entries.set(key, value); },
  };
}

describe("saved Direct Python example", () => {
  it("loads the new class example while retaining the research identity", () => {
    const storage = draftStorage();
    persistResearchDraft(storage, "researcher", "folder", {
      ...emptyResearchDraft(), name: "s", researchKind: "strategy_backtest",
      strategyMode: "direct", programSource: previousExample,
    });

    const loaded = loadResearchDraftState(storage, "researcher", "folder");
    expect(loaded).toMatchObject({ restored: true, upgradedExample: true,
      draft: { name: "s", strategyMode: "direct", programSource: DIRECT_EXAMPLE } });
    expect(JSON.parse(storage.getItem(researchDraftKey("researcher", "folder"))!).programSource).toBe(previousExample);
  });

  it("also recognizes the unchanged sample with a trailing blank line", () => {
    const storage = draftStorage();
    persistResearchDraft(storage, "researcher", "folder", {
      ...emptyResearchDraft(), programSource: `${previousExample}\n`,
    });
    expect(loadResearchDraftState(storage, "researcher", "folder")).toMatchObject({
      upgradedExample: true, draft: { programSource: DIRECT_EXAMPLE },
    });
  });

  it("preserves edited legacy source and admitted source", () => {
    const storage = draftStorage();
    const edited = previousExample.replace("history = context", "# changed\n    history = context");
    persistResearchDraft(storage, "researcher", "folder", {
      ...emptyResearchDraft(), programSource: edited,
    });
    expect(loadResearchDraftState(storage, "researcher", "folder").draft.programSource).toBe(edited);

    const admitted: ResearchDraft = { ...emptyResearchDraft(), programSource: previousExample };
    admitted.lastAdmittedBaseline = researchInputs(admitted);
    persistResearchDraft(storage, "researcher", "folder", admitted);
    expect(loadResearchDraftState(storage, "researcher", "folder").draft.programSource).toBe(previousExample);
  });
});

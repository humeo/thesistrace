import { describe, expect, it } from "vitest";
import { modelCost } from "./model-budget.js";

const pricing = { input: 200, cacheRead: 20, cacheWrite: 250, output: 1200 };
describe("model cost", () => {
  it("prices cache reads, writes, and reasoning without double counting", () => {
    expect(modelCost({ inputTokens: { total: 1000, noCache: 500, cacheRead: 400, cacheWrite: 100 },
      outputTokens: { total: 200, text: 50, reasoning: 150 } }, pricing)).toBe(373000);
  });
  it("does not invent zero usage", () => {
    expect(modelCost({ inputTokens: { total: undefined, noCache: undefined, cacheRead: undefined, cacheWrite: undefined },
      outputTokens: { total: undefined, text: undefined, reasoning: undefined } }, pricing)).toBeNull();
  });
  it("does not require a cache write split when its price equals ordinary input", () => {
    expect(modelCost({ inputTokens: { total: 1000, noCache: 600, cacheRead: 400, cacheWrite: undefined },
      outputTokens: { total: 200, text: undefined, reasoning: undefined } }, { ...pricing, cacheWrite: 200 })).toBe(368000);
  });
});

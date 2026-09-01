import { expect, test } from "vitest";

import { RunUsageCapture } from "./usage-capture.js";

test("persists only normalized token counts and excludes provider raw usage", () => {
  const capture = new RunUsageCapture();
  capture.capture({
    inputTokens: {
      cacheRead: 2,
      cacheWrite: undefined,
      noCache: 9,
      total: 11,
    },
    outputTokens: {
      reasoning: 4,
      text: 8,
      total: 12,
    },
    raw: { providerPrivateCanary: "must-not-persist" },
  });

  expect(capture.value()).toEqual({
    reported: true,
    inputTokens: {
      cacheRead: 2,
      cacheWrite: null,
      noCache: 9,
      total: 11,
    },
    outputTokens: {
      reasoning: 4,
      text: 8,
      total: 12,
    },
  });
  expect(JSON.stringify(capture.value())).not.toContain("providerPrivateCanary");
});

test("aggregates every completed provider step rather than only the final answer", () => {
  const capture = new RunUsageCapture();
  const step = {
    inputTokens: { total: 11, noCache: 9, cacheRead: 2, cacheWrite: undefined },
    outputTokens: { total: 12, text: 8, reasoning: 4 },
  };
  capture.beginStep();
  capture.capture(step);
  capture.beginStep();
  expect(capture.value()).toBeUndefined();
  capture.capture(step);
  expect(capture.value()).toEqual({
    reported: true,
    inputTokens: { total: 22, noCache: 18, cacheRead: 4, cacheWrite: null },
    outputTokens: { total: 24, text: 16, reasoning: 8 },
  });
});

test("an unreported step cannot be hidden by later valid usage", () => {
  const capture = new RunUsageCapture();
  capture.beginStep();
  capture.capture(undefined as never);
  capture.beginStep();
  capture.capture({
    inputTokens: { total: 2, noCache: 2, cacheRead: 0, cacheWrite: 0 },
    outputTokens: { total: 1, text: 1, reasoning: 0 },
  });
  expect(capture.value()).toBeUndefined();
});

test("unknown and overflowing totals remain unknown without failing the run", () => {
  const capture = new RunUsageCapture();
  const step = {
    inputTokens: { total: Number.MAX_SAFE_INTEGER, noCache: 3, cacheRead: undefined, cacheWrite: undefined },
    outputTokens: { total: 1, text: 1, reasoning: 0 },
  };
  capture.capture(step);
  capture.capture(step);
  expect(capture.value()?.inputTokens).toEqual({ total: null, noCache: 6, cacheRead: null, cacheWrite: null });
});

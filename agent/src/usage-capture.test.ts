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

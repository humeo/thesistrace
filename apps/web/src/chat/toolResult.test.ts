import { expect, test } from "vitest";

import {
  parseResearchRunHref,
  parseSafeToolResult,
  researchRunHref,
} from "./toolResult";

const safeMarker = JSON.stringify({
  outcome: "completed",
  resource: {
    id: "run_0123456789abcdef0123",
    kind: "research_run",
    status: "queued",
  },
  type: "thesistrace.tool-result",
  version: 1,
});

test("accepts the exact browser-safe ResearchRun marker", () => {
  const parsed = parseSafeToolResult(safeMarker);
  expect(parsed).toEqual({
    outcome: "completed",
    resource: {
      id: "run_0123456789abcdef0123",
      kind: "research_run",
      status: "queued",
    },
  });
  expect(researchRunHref(parsed!.resource!)).toBe(
    "/research-runs/run_0123456789abcdef0123",
  );
});

test("rejects unexpected fields, unsafe resources, and failed resources", () => {
  expect(parseSafeToolResult(JSON.stringify({
    ...JSON.parse(safeMarker),
    input: { formula: "must-not-render" },
  }))).toBeNull();
  expect(parseSafeToolResult(safeMarker.replace("queued", "private-state"))).toBeNull();
  expect(parseSafeToolResult(safeMarker.replace("run_0123456789abcdef0123", "../data")))
    .toBeNull();
  expect(parseSafeToolResult(safeMarker.replace('"completed"', '"failed"')))
    .toBeNull();
});

test("allows only the exact same-origin ResearchRun Markdown route", () => {
  expect(parseResearchRunHref("/research-runs/run_0123456789abcdef0123")).toBe(
    "/research-runs/run_0123456789abcdef0123",
  );
  expect(parseResearchRunHref("https://example.com/research-runs/run_0123456789abcdef0123"))
    .toBeNull();
  expect(parseResearchRunHref("javascript:alert(1)")).toBeNull();
  expect(parseResearchRunHref("/research-runs/run_0123456789abcdef0123?secret=true"))
    .toBeNull();
});

import { describe, expect, it } from "vitest";

import {
  parseSafeToolResult,
  projectSafeToolResult,
  SAFE_TOOL_COMPLETED,
  SAFE_TOOL_FAILED,
} from "./safe-tool-result.js";

describe("safe Tool result marker", () => {
  it("projects only a validated public ResearchRun identity and status", () => {
    const marker = projectSafeToolResult({
      hypothesis: "must-not-cross-browser-boundary",
      replayed: false,
      run_id: "run_0123456789abcdef0123",
      status: "queued",
    }, false);

    expect(parseSafeToolResult(marker)).toEqual({
      outcome: "completed",
      resource: {
        id: "run_0123456789abcdef0123",
        kind: "research_run",
        status: "queued",
      },
    });
    expect(marker).not.toContain("hypothesis");
    expect(marker).not.toContain("replayed");
  });

  it("handles adapted, serialized, and nested JSON Tool results", () => {
    for (const value of [
      { id: "run_0123456789abcdef0123", status: "succeeded" },
      JSON.stringify({ run_id: "run_0123456789abcdef0123", status: "running" }),
      {
        type: "json",
        value: { run_id: "run_0123456789abcdef0123", status: "failed" },
      },
      {
        structuredContent: {
          run_id: "run_0123456789abcdef0123",
          status: "cancelled",
        },
      },
    ]) {
      expect(parseSafeToolResult(projectSafeToolResult(value, false))?.resource).toMatchObject({
        id: "run_0123456789abcdef0123",
        kind: "research_run",
      });
    }
  });

  it("fails closed for malformed identifiers, statuses, marker fields, and failures", () => {
    expect(projectSafeToolResult({
      run_id: "run_private/path",
      status: "queued",
    }, false)).toBe(SAFE_TOOL_COMPLETED);
    expect(projectSafeToolResult({
      run_id: "run_0123456789abcdef0123",
      status: "private-worker-state",
    }, false)).toBe(SAFE_TOOL_COMPLETED);
    expect(projectSafeToolResult({
      run_id: "run_0123456789abcdef0123",
      status: "queued",
    }, true)).toBe(SAFE_TOOL_FAILED);
    expect(parseSafeToolResult(JSON.stringify({
      outcome: "completed",
      private: "field",
      type: "thesistrace.tool-result",
      version: 1,
    }))).toBeNull();
    expect(parseSafeToolResult(JSON.stringify({
      outcome: "failed",
      resource: {
        id: "run_0123456789abcdef0123",
        kind: "research_run",
        status: "queued",
      },
      type: "thesistrace.tool-result",
      version: 1,
    }))).toBeNull();
  });
});

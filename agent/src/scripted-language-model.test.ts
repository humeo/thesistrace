import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { expect, test } from "vitest";

import {
  appendExchange,
  runScriptedTrajectory,
  scriptedCallOptions as researchOptions,
  type RecordedToolCall,
} from "../test-fixtures/scripted-trajectory.js";

import {
  SCRIPTED_ADMISSION_REPAIR_IDEA_PROMPT,
  SCRIPTED_AMBIGUOUS_IDEA_PROMPT,
  SCRIPTED_FACTOR_IDEA_PROMPT,
  SCRIPTED_FORMULA_REPAIR_IDEA_PROMPT,
  SCRIPTED_INVALID_A2UI_PROMPT,
  SCRIPTED_INVALID_A2UI_TOP_LEVEL_PROMPT,
  SCRIPTED_INVALID_A2UI_DATA_PROMPT,
  SCRIPTED_LARGE_A2UI_TABLE_PROMPT,
  SCRIPTED_RETRY_INTERRUPTED_PROMPT,
  SCRIPTED_RESUME_RESEARCH_PROMPT,
  SCRIPTED_STRATEGY_IDEA_PROMPT,
  SCRIPTED_SUBMIT_ONLY_IDEA_PROMPT,
  SCRIPTED_TOOL_PROMPT,
  ScriptedLanguageModel,
} from "./scripted-language-model.js";
import { RunUsageCapture } from "./usage-capture.js";
import { GuardedLanguageModel, RunModelObservation } from "./guarded-language-model.js";

const callOptions = {
  prompt: [{ role: "user" as const, content: [{ type: "text" as const, text: "idea" }] }],
};

test("streams deterministic chunks and captures the provider-reported usage", async () => {
  const capture = new RunUsageCapture();
  const model = new GuardedLanguageModel(
    new ScriptedLanguageModel("scripted-v1"),
    new RunModelObservation(capture),
  );
  const result = await model.doStream(callOptions);
  const parts = [];
  const reader = result.stream.getReader();
  for (;;) {
    const part = await reader.read();
    if (part.done) break;
    parts.push(part.value);
  }

  const text = parts
    .filter((part) => part.type === "text-delta")
    .map((part) => part.delta)
    .join("");
  expect(text.trim().length).toBeGreaterThan(0);
  expect(Buffer.byteLength(text, "utf8")).toBeLessThanOrEqual(512);
  expect(capture.value()).toMatchObject({
    inputTokens: { total: 11 },
    outputTokens: { reasoning: 0, text: 12, total: 12 },
  });
});

test("fails deterministically without leaking a synthetic response", async () => {
  const model = new ScriptedLanguageModel("scripted-failure-v1", "throw-before-stream");
  await expect(model.doStream(callOptions)).rejects.toThrow(
    "SCRIPTED_MODEL_FAILURE_INTERNAL_DETAIL",
  );
  await expect(model.doGenerate(callOptions)).rejects.toThrow(
    "SCRIPTED_MODEL_FAILURE_INTERNAL_DETAIL",
  );
});

test("calls a discovered no-argument Tool and then explains its result", async () => {
  const model = new ScriptedLanguageModel("scripted-v1");
  const firstOptions = {
    prompt: [{
      content: [{ type: "text" as const, text: SCRIPTED_TOOL_PROMPT }],
      role: "user" as const,
    }],
    tools: [{
      description: "Read the research context",
      inputSchema: { additionalProperties: false, properties: {}, type: "object" },
      name: "get_research_context",
      type: "function" as const,
    }],
  } satisfies LanguageModelV3CallOptions;
  const first = await readParts(await model.doStream(firstOptions));
  expect(first).toContainEqual({
    input: "{}",
    toolCallId: "scripted-tool-call-1",
    toolName: "get_research_context",
    type: "tool-call",
  });

  const second = await readParts(await model.doStream({
    ...firstOptions,
    prompt: [
      ...firstOptions.prompt,
      {
        content: [{
          input: {},
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-call" as const,
        }],
        role: "assistant" as const,
      },
      {
        content: [{
          output: { type: "json" as const, value: { dataset: "secret-server-result" } },
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-result" as const,
        }],
        role: "tool" as const,
      },
    ],
  }));
  const explanation = second
    .filter((part) => part.type === "text-delta")
    .map((part) => part.delta)
    .join("");
  expect(explanation.trim().length).toBeGreaterThan(0);
  expect(Buffer.byteLength(explanation, "utf8")).toBeLessThanOrEqual(512);
  expect(explanation).not.toContain("secret-server-result");

  const repeated = await readParts(await model.doStream({
    ...firstOptions,
    prompt: [
      ...firstOptions.prompt,
      {
        content: [{
          input: {},
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-call" as const,
        }],
        role: "assistant" as const,
      },
      {
        content: [{
          output: { type: "json" as const, value: { dataset: "first-result" } },
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-result" as const,
        }],
        role: "tool" as const,
      },
      {
        content: [{ type: "text" as const, text: SCRIPTED_TOOL_PROMPT }],
        role: "user" as const,
      },
    ],
  }));
  expect(repeated).toContainEqual({
    input: "{}",
    toolCallId: "scripted-tool-call-2",
    toolName: "get_research_context",
    type: "tool-call",
  });
});

test.each([
  SCRIPTED_INVALID_A2UI_PROMPT,
  SCRIPTED_INVALID_A2UI_TOP_LEVEL_PROMPT,
  SCRIPTED_INVALID_A2UI_DATA_PROMPT,
])("attempts one deterministic unsafe A2UI surface and then continues safely: %s", async (prompt) => {
  const model = new ScriptedLanguageModel("scripted-v1");
  const firstOptions = researchOptions(prompt, researchTools(true));
  const first = await readParts(await model.doStream(firstOptions));
  const toolCall = first.find((part) => part.type === "tool-call");
  expect(toolCall).toMatchObject({
    toolName: "render_a2ui",
    type: "tool-call",
  });
  if (toolCall?.type !== "tool-call") throw new Error("Expected unsafe A2UI Tool call");
  expect(toolCall.input).toContain("MALICIOUS_A2UI_SHOULD_NOT_RENDER");
  appendExchange(
    firstOptions,
    toolCall.toolCallId,
    toolCall.toolName,
    JSON.parse(toolCall.input) as Record<string, unknown>,
    { error: true, message: "INVALID_RESEARCH_A2UI" },
  );

  const second = await readParts(await model.doStream(firstOptions));
  const text = second
    .filter((part) => part.type === "text-delta")
    .map((part) => part.delta)
    .join("");
  expect(text).toContain("unsafe research surface was rejected");
  expect(text).not.toContain("MALICIOUS_A2UI_SHOULD_NOT_RENDER");
  expect(second.some((part) => part.type === "tool-call")).toBe(false);

  firstOptions.prompt.push({
    content: [{ type: "text", text }],
    role: "assistant",
  }, {
    content: [{ type: "text", text: "Continue after rejecting that unsafe surface." }],
    role: "user",
  });
  const continuation = await readParts(await model.doStream(firstOptions));
  expect(continuation
    .filter((part) => part.type === "text-delta")
    .map((part) => part.delta)
    .join(""))
    .toBe("I can help turn that idea into a testable Alpha.");
});

test("drives deterministic proposal, status, and result surfaces through direct A2UI", async () => {
  const trajectory = await runResearchTrajectory(
    SCRIPTED_FACTOR_IDEA_PROMPT,
    ({ input, name, occurrence }) => {
      switch (name) {
        case "get_research_context": return researchContext();
        case "get_alpha_catalog": return alphaCatalog();
        case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
        case "render_a2ui": return { a2ui_operations: [], rendered: input.surfaceId };
        case "submit_research_run": return acceptedRun();
        case "get_research_run": return occurrence === 1
          ? pollingDetail(input, "running", [])
          : pollingDetail(input, "succeeded", ["factor", "provenance"]);
        case "get_research_run_result": return factorResult();
        default: throw new Error(`Unexpected Tool call: ${name}`);
      }
    },
    true,
  );

  const surfaces = trajectory.calls.filter((call) => call.name === "render_a2ui");
  expect(surfaces.map((call) => call.input.surfaceId)).toEqual([
    "alpha-proposal",
    "research-run-status",
    "research-run-progress",
    "research-result",
  ]);
  expect(surfaceComponentNames(surfaces[0]?.input)).toEqual([
    "Column",
    "AlphaProposal",
    "Formula",
  ]);
  expect(surfaceComponentNames(surfaces[1]?.input)).toEqual([
    "Column",
    "ResearchRunStatus",
    "Navigation",
  ]);
  expect(surfaceComponentNames(surfaces[2]?.input)).toEqual([
    "Column",
    "ResearchRunStatus",
    "Navigation",
  ]);
  expect(surfaces[2]?.input.components).toContainEqual(expect.objectContaining({
    component: "ResearchRunStatus",
    formula: "rank(-abs(pct_change(close, 1)))",
    phase: "research",
    runId: "run_0123456789abcdef0123",
    status: "running",
  }));
  expect(surfaceComponentNames(surfaces[3]?.input)).toEqual([
    "Column",
    "ResearchRunStatus",
    "ResultMetrics",
    "Table",
    "Provenance",
    "Navigation",
  ]);
  expect(JSON.stringify(surfaces)).toContain("run_0123456789abcdef0123");
  expect(JSON.stringify(surfaces)).toContain("0.1200");
  expect(JSON.stringify(surfaces)).toContain("3.40%");
});

test("emits one explicitly non-research large table for renderer acceptance", async () => {
  const trajectory = await runResearchTrajectory(SCRIPTED_LARGE_A2UI_TABLE_PROMPT, ({ name }) => {
    expect(name).toBe("render_a2ui");
    return { rendered: true };
  }, true);
  expect(trajectory.calls).toHaveLength(1);
  expect(trajectory.calls[0]?.input.components).toEqual([expect.objectContaining({
    caption: "Renderer acceptance sample — not research evidence",
    columns: expect.any(Array),
    component: "Table",
    rows: expect.any(Array),
  })]);
  const table = (trajectory.calls[0]!.input.components as {
    rows: string[][]; columns: string[];
  }[])[0]!;
  expect(table.rows).toHaveLength(100);
  expect(table.columns).toHaveLength(12);
  expect(table.rows.every((row) => row.length === 12)).toBe(true);
  expect(trajectory.text).toBe("");
});

test.each([
  { label: "missing admission state", admission: { status: undefined } },
  { label: "unknown admission state", admission: { status: "finished" } },
  { label: "mismatched running id", detail: { id: "run_aaaaaaaaaaaaaaaaaaaa" } },
  { label: "missing running formula", detail: { input: {} } },
  { label: "oversized running formula", detail: { input: { formula: "x".repeat(9000) } } },
  { label: "invalid running phase", detail: { progress: { phase: 7 } } },
])("does not invent replacement facts for $label", async ({ admission, detail }) => {
  const trajectory = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({ input, name }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "render_a2ui": return { rendered: true };
      case "submit_research_run": return { ...acceptedRun(), ...admission };
      case "get_research_run": return { ...pollingDetail(input, "running", []), ...detail };
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  }, true);
  const surfaces = trajectory.calls.filter((call) => call.name === "render_a2ui");
  expect(surfaces.map((call) => call.input.surfaceId)).toEqual(admission === undefined
    ? ["alpha-proposal", "research-run-status"]
    : ["alpha-proposal"]);
  expect(trajectory.text).toContain("did not create a surface or invent replacement Research facts");
  expect(JSON.stringify(surfaces)).not.toContain("run_00000000000000000000");
});

test("drives the complete Factor loop from a natural-language idea", async () => {
  const trajectory = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({
    input,
    name,
    occurrence,
  }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "submit_research_run": return {
        outcome: "accepted",
        replayed: false,
        retry_after_seconds: 2,
        run_id: "run_0123456789abcdef0123",
        status: "queued",
      };
      case "get_research_run": return occurrence === 1
        ? pollingDetail(input, "running", [])
        : pollingDetail(input, "succeeded", ["factor", "provenance"]);
      case "get_research_run_result": return factorResult();
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  });

  expect(trajectory.calls.map((call) => call.name)).toEqual([
    "get_research_context",
    "get_alpha_catalog",
    "diagnose_alpha_formula",
    "submit_research_run",
    "get_research_run",
    "get_research_run",
    "get_research_run_result",
  ]);
  expect(trajectory.calls[3]?.input).toMatchObject({
    folder_id: "folder_default",
    formula: "rank(-abs(pct_change(close, 1)))",
    neutralization: "none",
    research_kind: "factor_evaluation",
    request_id: "agent_00000000000040008000000000000041_research_v1",
    universe: "top1000",
  });
  expect(trajectory.waits).toEqual([2, 2]);
  expect(trajectory.text).toContain("rank(-abs(pct_change(close, 1)))");
  expect(trajectory.text).toContain("0.1200");
  expect(trajectory.text).toContain("3.40%");
  expect(trajectory.text).toContain("/research-runs/run_0123456789abcdef0123");
});

test("reads the JSON text model output produced by real MCP Tools", async () => {
  const model = new ScriptedLanguageModel("scripted-v1");
  const options = researchOptions(SCRIPTED_FACTOR_IDEA_PROMPT, researchTools());
  appendMcpTextExchange(
    options,
    "context-call",
    "get_research_context",
    {},
    researchContext(),
  );
  appendMcpTextExchange(
    options,
    "catalog-call",
    "get_alpha_catalog",
    { identifiers: ["abs", "close", "pct_change", "rank"] },
    alphaCatalog(),
  );

  const generated = await model.doGenerate(options);
  expect(generated.content).toContainEqual(expect.objectContaining({
    input: JSON.stringify({ source: "rank(-abs(pct_change(close, 1)))" }),
    toolName: "diagnose_alpha_formula",
    type: "tool-call",
  }));
});

test("uses the same entry for a model-owned Strategy Backtest", async () => {
  const trajectory = await runResearchTrajectory(SCRIPTED_STRATEGY_IDEA_PROMPT, ({
    input,
    name,
  }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "submit_research_run": return {
        outcome: "accepted",
        replayed: false,
        retry_after_seconds: 2,
        run_id: "run_abcdef0123456789abcd",
        status: "queued",
      };
      case "get_research_run": return pollingDetail(
        input,
        "succeeded",
        ["factor", "strategy_summary", "provenance"],
      );
      case "get_research_run_result": return strategyResult();
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  });

  expect(trajectory.calls.find((call) => call.name === "submit_research_run")?.input)
    .toMatchObject({
      holdings_count: 10,
      rebalance_every_sessions: 5,
      research_kind: "strategy_backtest",
    });
  expect(trajectory.calls.at(-1)).toMatchObject({
    input: {
      run_id: "run_abcdef0123456789abcd",
      section: "strategy_summary",
    },
    name: "get_research_run_result",
  });
  expect(trajectory.text).toContain("1.2300");
  expect(trajectory.text).toContain("17.00%");
  expect(trajectory.text).toContain("-8.00%");
  expect(trajectory.text).toContain("/research-runs/run_abcdef0123456789abcd");
});

test("repairs its Formula and revises a rejected command without replaying a changed request", async () => {
  const diagnosed: string[] = [];
  const repaired = await runResearchTrajectory(
    SCRIPTED_FORMULA_REPAIR_IDEA_PROMPT,
    ({ input, name, occurrence }) => {
      switch (name) {
        case "get_research_context": return researchContext();
        case "get_alpha_catalog": return alphaCatalog();
        case "diagnose_alpha_formula": {
          diagnosed.push(String(input.source));
          return occurrence === 1
            ? { diagnostics: [{ code: "UNKNOWN_IDENTIFIER" }], valid: false }
            : { diagnostics: [], valid: true };
        }
        case "submit_research_run": return acceptedRun();
        case "get_research_run": return pollingDetail(
          input,
          "succeeded",
          ["factor", "provenance"],
        );
        case "get_research_run_result": return factorResult();
        default: throw new Error(`Unexpected Tool call: ${name}`);
      }
    },
  );
  expect(diagnosed).toEqual([
    "rank(-abs(pct_change(clsoe, 1)))",
    "rank(-abs(pct_change(close, 1)))",
  ]);
  expect(repaired.text).toContain("rank(-abs(pct_change(close, 1)))");
  expect(repaired.text).toContain("/research-runs/run_0123456789abcdef0123");

  const revised = await runResearchTrajectory(
    SCRIPTED_ADMISSION_REPAIR_IDEA_PROMPT,
    ({ input, name, occurrence }) => {
      switch (name) {
        case "get_research_context": return researchContext();
        case "get_alpha_catalog": return alphaCatalog();
        case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
        case "submit_research_run": {
          if (occurrence === 1) {
            return {
              issues: [{
                code: "INSUFFICIENT_CALCULATION_WARMUP",
                field: "start_date",
              }],
              outcome: "rejected",
              replayed: false,
            };
          }
          if (input.start_date !== "2024-01-31") {
            throw new Error("Revised admission did not make Dataset sessions available as warmup");
          }
          return acceptedRun();
        }
        case "get_research_run": return pollingDetail(
          input,
          "succeeded",
          ["factor", "provenance"],
        );
        case "get_research_run_result": return factorResult();
        default: throw new Error(`Unexpected Tool call: ${name}`);
      }
    },
  );
  const submissions = revised.calls.filter((call) => call.name === "submit_research_run");
  expect(submissions).toHaveLength(2);
  expect(submissions[0]?.input.request_id).toBe(
    "agent_00000000000040008000000000000041_research_v1",
  );
  expect(submissions[1]?.input).toMatchObject({
    request_id: "agent_00000000000040008000000000000041_research_v2",
    start_date: "2024-01-31",
  });
});

test("does not mutate and resubmit an unrelated structured admission rejection", async () => {
  const trajectory = await runResearchTrajectory(
    SCRIPTED_ADMISSION_REPAIR_IDEA_PROMPT,
    ({ name }) => {
      switch (name) {
        case "get_research_context": return researchContext();
        case "get_alpha_catalog": return alphaCatalog();
        case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
        case "submit_research_run": return {
          issues: [{ code: "FOLDER_NOT_FOUND", field: "folder_id" }],
          outcome: "rejected",
          replayed: false,
        };
        default: throw new Error(`Unexpected Tool call after unrelated rejection: ${name}`);
      }
    },
  );

  expect(trajectory.calls.filter((call) => call.name === "submit_research_run"))
    .toHaveLength(1);
  expect(trajectory.text).toContain("FOLDER_NOT_FOUND");
  expect(trajectory.text).toContain("could not safely derive a corrected command");
  expect(trajectory.text).toContain("stopped without resubmitting");
  expect(trajectory.text).not.toContain("after one bounded correction");
});

test("does not invent a warmup revision when coverage cannot produce a changed command", async () => {
  const trajectory = await runResearchTrajectory(
    SCRIPTED_ADMISSION_REPAIR_IDEA_PROMPT,
    ({ name }) => {
      switch (name) {
        case "get_research_context": return {
          ...researchContext(),
          data_overview: {
            market_coverage: { end: "2024-01-31", start: "2024-01-31" },
          },
        };
        case "get_alpha_catalog": return alphaCatalog();
        case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
        case "submit_research_run": return {
          issues: [{
            code: "INSUFFICIENT_CALCULATION_WARMUP",
            field: "start_date",
          }],
          outcome: "rejected",
          replayed: false,
        };
        default: throw new Error(`Unexpected Tool call after fixed coverage: ${name}`);
      }
    },
  );

  expect(trajectory.calls.filter((call) => call.name === "submit_research_run"))
    .toHaveLength(1);
  expect(trajectory.text).toContain("cannot produce a different Research start");
  expect(trajectory.text).toContain("stopped without resubmitting");
  expect(trajectory.text).not.toContain("does not provide a usable default Folder");
});

test("honors transient guidance and replays the exact effect command", async () => {
  const trajectory = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({
    input,
    name,
    occurrence,
  }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "submit_research_run": return occurrence === 1
        ? {
            code: "TEMPORARILY_UNAVAILABLE",
            retry_after_seconds: 3,
            retryable: true,
          }
        : acceptedRun();
      case "get_research_run": return pollingDetail(
        input,
        "succeeded",
        ["factor", "provenance"],
      );
      case "get_research_run_result": return factorResult();
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  });
  const submissions = trajectory.calls.filter((call) => call.name === "submit_research_run");
  expect(submissions).toHaveLength(2);
  expect(submissions[1]?.input).toEqual(submissions[0]?.input);
  expect(trajectory.waits).toEqual([3, 2]);
});

test("reconstructs an uncertain effect replay for retry and resume turns", async () => {
  const tools = researchTools();
  const request = {
    end_date: "2024-01-31",
    folder_id: "folder_default",
    formula: "rank(-abs(pct_change(close, 1)))",
    hypothesis: "Stable signal",
    name: "Low volatility",
    neutralization: "none",
    request_id: "agent_00000000000040008000000000000041_research_v1",
    research_kind: "factor_evaluation",
    start_date: "2024-01-02",
    universe: "top1000",
  };
  for (const continuation of [
    SCRIPTED_RETRY_INTERRUPTED_PROMPT,
    SCRIPTED_RESUME_RESEARCH_PROMPT,
  ]) {
    const model = new ScriptedLanguageModel(
      "scripted-v1",
      "reply",
      async () => undefined,
    );
    const options = researchOptions(SCRIPTED_FACTOR_IDEA_PROMPT, tools);
    appendExchange(options, "context-call", "get_research_context", {}, researchContext());
    appendExchange(options, "catalog-call", "get_alpha_catalog", {
      identifiers: ["abs", "close", "pct_change", "rank"],
    }, alphaCatalog());
    appendExchange(options, "diagnostic-call", "diagnose_alpha_formula", {
      source: "rank(-abs(pct_change(close, 1)))",
    }, { diagnostics: [], valid: true });
    appendExchange(options, "submit-call", "submit_research_run", request, {
      content: [{ text: JSON.stringify({ code: "MCP_TRANSIENT" }), type: "text" }],
      isError: true,
    });
    options.prompt.push({
      content: [{ type: "text", text: continuation }],
      role: "user",
    });

    const generated = await model.doGenerate(options);
    const toolCall = generated.content.find((part) => part.type === "tool-call");
    expect(toolCall).toMatchObject({
      input: JSON.stringify(request),
      toolName: "submit_research_run",
    });
  }
});

test("asks one focused follow-up for material ambiguity and reports worker failure", async () => {
  const model = new ScriptedLanguageModel("scripted-v1");
  const ambiguous = await model.doGenerate(researchOptions(
    SCRIPTED_AMBIGUOUS_IDEA_PROMPT,
    researchTools(),
  ));
  expect(ambiguous.content).toEqual([expect.objectContaining({
    text: expect.stringMatching(/signal.*factor.*strategy/i),
    type: "text",
  })]);

  const failed = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({
    input,
    name,
  }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "submit_research_run": return acceptedRun();
      case "get_research_run": return pollingDetail(input, "failed", []);
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  });
  expect(failed.calls.some((call) => call.name === "get_research_run_result")).toBe(false);
  expect(failed.text).toContain("run_0123456789abcdef0123");
  expect(failed.text).toContain("failed");
  expect(failed.text).not.toMatch(/0\.1200|3\.40%/);
});

test("does not turn a missing or unknown ResearchRun status into a failure claim", async () => {
  for (const malformedDetail of [
    {
      available_result_sections: [],
      id: "run_0123456789abcdef0123",
      input: {
        formula: "rank(-abs(pct_change(close, 1)))",
        hypothesis: "Stable recent returns should persist.",
        research_kind: "factor_evaluation",
      },
    },
    pollingDetail(
      { run_id: "run_0123456789abcdef0123" },
      "completed",
      [],
    ),
  ]) {
    const trajectory = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({
      name,
    }) => {
      switch (name) {
        case "get_research_context": return researchContext();
        case "get_alpha_catalog": return alphaCatalog();
        case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
        case "submit_research_run": return acceptedRun();
        case "get_research_run": return malformedDetail;
        default: throw new Error(`Unexpected Tool call after malformed status: ${name}`);
      }
    });

    expect(trajectory.calls.at(-1)?.name).toBe("get_research_run");
    expect(trajectory.text).toContain("lifecycle status I could not interpret");
    expect(trajectory.text).not.toMatch(/reached \*\*(failed|cancelled)\*\*|succeeded/i);
  }
});

test("ends after admission when requested and lets a later turn resume from history", async () => {
  const submitted = await runResearchTrajectory(SCRIPTED_SUBMIT_ONLY_IDEA_PROMPT, ({
    name,
  }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "submit_research_run": return acceptedRun();
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  });
  expect(submitted.calls.map((call) => call.name)).toEqual([
    "get_research_context",
    "get_alpha_catalog",
    "diagnose_alpha_formula",
    "submit_research_run",
  ]);
  expect(submitted.text).toContain("/research-runs/run_0123456789abcdef0123");

  const model = new ScriptedLanguageModel("scripted-v1", "reply", async () => undefined);
  const options = researchOptions(SCRIPTED_SUBMIT_ONLY_IDEA_PROMPT, researchTools());
  appendExchange(options, "context", "get_research_context", {}, researchContext());
  appendExchange(options, "catalog", "get_alpha_catalog", {
    identifiers: ["abs", "close", "pct_change", "rank"],
  }, alphaCatalog());
  appendExchange(options, "diagnostics", "diagnose_alpha_formula", {
    source: "rank(-abs(pct_change(close, 1)))",
  }, { diagnostics: [], valid: true });
  appendExchange(options, "submit", "submit_research_run", submitted.calls[3]!.input, acceptedRun());
  options.prompt.push({
    content: [{ type: "text", text: "Research accepted." }],
    role: "assistant",
  });
  options.prompt.push({
    content: [{ type: "text", text: SCRIPTED_RESUME_RESEARCH_PROMPT }],
    role: "user",
  });
  const resumed = await model.doGenerate(options);
  expect(resumed.content).toContainEqual(expect.objectContaining({
    toolName: "get_research_run",
    type: "tool-call",
  }));
});

test("gives every resume turn a fresh bounded poll budget", async () => {
  const model = new ScriptedLanguageModel("scripted-v1", "reply", async () => undefined);
  const options = researchOptions(SCRIPTED_FACTOR_IDEA_PROMPT, researchTools());
  appendExchange(options, "context", "get_research_context", {}, researchContext());
  appendExchange(options, "catalog", "get_alpha_catalog", {
    identifiers: ["abs", "close", "pct_change", "rank"],
  }, alphaCatalog());
  appendExchange(options, "diagnostics", "diagnose_alpha_formula", {
    source: "rank(-abs(pct_change(close, 1)))",
  }, { diagnostics: [], valid: true });
  const request = {
    end_date: "2024-01-31",
    folder_id: "folder_default",
    formula: "rank(-abs(pct_change(close, 1)))",
    hypothesis: "Stable recent returns should persist.",
    name: "Low-volatility factor",
    neutralization: "none",
    request_id: "agent_00000000000040008000000000000041_research_v1",
    research_kind: "factor_evaluation",
    start_date: "2024-01-02",
    universe: "top1000",
  };
  appendExchange(options, "submit", "submit_research_run", request, acceptedRun());
  for (let poll = 1; poll <= 6; poll += 1) {
    appendExchange(
      options,
      `poll-${poll}`,
      "get_research_run",
      { run_id: "run_0123456789abcdef0123" },
      pollingDetail({ run_id: "run_0123456789abcdef0123" }, "running", []),
    );
  }
  options.prompt.push({
    content: [{ text: "Run remains active.", type: "text" }],
    role: "assistant",
  });
  options.prompt.push({
    content: [{ type: "text", text: SCRIPTED_RESUME_RESEARCH_PROMPT }],
    role: "user",
  });

  const resumedPoll = await model.doGenerate(options);
  const pollCall = resumedPoll.content.find((part) => part.type === "tool-call");
  expect(pollCall).toMatchObject({
    input: JSON.stringify({ run_id: "run_0123456789abcdef0123" }),
    toolName: "get_research_run",
  });
  if (pollCall?.type !== "tool-call") throw new Error("resume did not poll");
  appendExchange(
    options,
    pollCall.toolCallId,
    pollCall.toolName,
    { run_id: "run_0123456789abcdef0123" },
    pollingDetail(
      { run_id: "run_0123456789abcdef0123" },
      "succeeded",
      ["factor", "provenance"],
    ),
  );
  const resultRequest = await model.doGenerate(options);
  expect(resultRequest.content).toContainEqual(expect.objectContaining({
    input: JSON.stringify({
      run_id: "run_0123456789abcdef0123",
      section: "factor",
    }),
    toolName: "get_research_run_result",
    type: "tool-call",
  }));
});

test("fails closed when Context constraints or authoritative Result input are malformed", async () => {
  const invalidContext = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({
    name,
  }) => {
    switch (name) {
      case "get_research_context": return {
        ...researchContext(),
        authoring_constraints: { universes: [] },
      };
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      default: throw new Error(`Unexpected Tool call after invalid Context: ${name}`);
    }
  });
  expect(invalidContext.calls.map((call) => call.name)).toEqual([
    "get_research_context",
    "get_alpha_catalog",
    "diagnose_alpha_formula",
  ]);

  const missingInput = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({
    name,
  }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "submit_research_run": return acceptedRun();
      case "get_research_run": return {
        available_result_sections: ["factor", "provenance"],
        id: "run_0123456789abcdef0123",
        status: "succeeded",
      };
      case "get_research_run_result": return factorResult();
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  });
  expect(missingInput.calls.at(-1)?.name).toBe("get_research_run_result");
  expect(missingInput.text).not.toMatch(
    /rank\(-abs\(pct_change\(close, 1\)\)\)|0\.1200|3\.40%|\/research-runs\//,
  );
});

test("preserves explicit unavailable Factor metrics without inventing values", async () => {
  const trajectory = await runResearchTrajectory(SCRIPTED_FACTOR_IDEA_PROMPT, ({
    input,
    name,
  }) => {
    switch (name) {
      case "get_research_context": return researchContext();
      case "get_alpha_catalog": return alphaCatalog();
      case "diagnose_alpha_formula": return { diagnostics: [], valid: true };
      case "submit_research_run": return acceptedRun();
      case "get_research_run": return pollingDetail(
        input,
        "succeeded",
        ["factor", "provenance"],
      );
      case "get_research_run_result": return {
        ...factorResult(),
        factor: {
          horizons: {
            "5": {
              summary: {
                rank_ic: { mean: null },
                top_bottom_return: null,
              },
            },
          },
        },
      };
      default: throw new Error(`Unexpected Tool call: ${name}`);
    }
  });

  expect(trajectory.text).toContain("rank(-abs(pct_change(close, 1)))");
  expect(trajectory.text).toContain("/research-runs/run_0123456789abcdef0123");
  expect(trajectory.text.match(/Unavailable/g)).toHaveLength(2);
  expect(trajectory.text).not.toMatch(/0\.0000|0\.00%/);
});

test("fails closed before admission when the Agent Run identity is absent", async () => {
  const model = new ScriptedLanguageModel("scripted-v1");
  const options = researchOptions(SCRIPTED_FACTOR_IDEA_PROMPT, researchTools());
  options.prompt[0] = { content: "ThesisTrace instructions.", role: "system" };
  appendExchange(options, "context", "get_research_context", {}, researchContext());
  appendExchange(options, "catalog", "get_alpha_catalog", {
    identifiers: ["abs", "close", "pct_change", "rank"],
  }, alphaCatalog());
  appendExchange(options, "diagnostics", "diagnose_alpha_formula", {
    source: "rank(-abs(pct_change(close, 1)))",
  }, { diagnostics: [], valid: true });

  const generated = await model.doGenerate(options);
  expect(generated.content.some((part) => part.type === "tool-call")).toBe(false);
});

async function readParts(
  result: Awaited<ReturnType<ScriptedLanguageModel["doStream"]>>,
) {
  const parts = [];
  const reader = result.stream.getReader();
  for (;;) {
    const part = await reader.read();
    if (part.done) return parts;
    parts.push(part.value);
  }
}

async function runResearchTrajectory(
  prompt: string,
  output: (call: RecordedToolCall & { occurrence: number }) => unknown,
  includeA2UI = false,
) {
  return runScriptedTrajectory(researchOptions(prompt, researchTools(includeA2UI)), output);
}

function researchTools(includeA2UI = false): NonNullable<LanguageModelV3CallOptions["tools"]> {
  const names = [
    "get_research_context",
    "get_alpha_catalog",
    "diagnose_alpha_formula",
    "submit_research_run",
    "get_research_run",
    "get_research_run_result",
  ];
  if (includeA2UI) names.push("render_a2ui");
  return names.map((name) => ({
    description: name,
    inputSchema: { additionalProperties: true, properties: {}, type: "object" },
    name,
    type: "function" as const,
  }));
}

function surfaceComponentNames(input: Record<string, unknown> | undefined): string[] {
  if (!Array.isArray(input?.components)) return [];
  return input.components.flatMap((component) => (
    typeof component === "object"
    && component !== null
    && "component" in component
    && typeof component.component === "string"
      ? [component.component]
      : []
  ));
}

function appendMcpTextExchange(
  options: LanguageModelV3CallOptions,
  toolCallId: string,
  toolName: string,
  input: Record<string, unknown>,
  output: Record<string, unknown>,
): void {
  options.prompt.push({
    content: [{ input, toolCallId, toolName, type: "tool-call" }],
    role: "assistant",
  });
  options.prompt.push({
    content: [{
      output: { type: "text", value: JSON.stringify(output) },
      toolCallId,
      toolName,
      type: "tool-result",
    }],
    role: "tool",
  });
}

function researchContext(): Record<string, unknown> {
  return {
    authoring_constraints: {
      holdings_count: { maximum: 100, minimum: 1 },
      neutralizations: ["none", "industry"],
      rebalance_every_sessions: { maximum: 20, minimum: 1 },
      universes: ["top300", "top1000"],
    },
    data_overview: {
      market_coverage: { end: "2024-01-31", start: "2024-01-02" },
    },
    folders: {
      items: [{ id: "folder_default", is_default: true, name: "Research" }],
    },
  };
}

function alphaCatalog(): Record<string, unknown> {
  return {
    builtins: [{ identifier: "abs" }, { identifier: "pct_change" }, { identifier: "rank" }],
    fields: [{ identifier: "close" }],
    unknown_identifiers: [],
  };
}

function acceptedRun(): Record<string, unknown> {
  return {
    outcome: "accepted",
    replayed: false,
    retry_after_seconds: 2,
    run_id: "run_0123456789abcdef0123",
    status: "queued",
  };
}

function pollingDetail(
  input: Record<string, unknown>,
  status: string,
  availableResultSections: readonly string[],
): Record<string, unknown> {
  return {
    available_result_sections: [...availableResultSections],
    id: typeof input.run_id === "string" ? input.run_id : "run_0123456789abcdef0123",
    input: {
      formula: "rank(-abs(pct_change(close, 1)))",
      hypothesis: "Stable recent returns should persist.",
      research_kind: availableResultSections.includes("strategy_summary")
        ? "strategy_backtest"
        : "factor_evaluation",
    },
    progress: { phase: status === "running" ? "research" : status },
    retry_after_seconds: ["queued", "running", "cancelling"].includes(status) ? 2 : null,
    status,
  };
}

function factorResult(): Record<string, unknown> {
  return {
    factor: {
      horizons: {
        "5": {
          summary: {
            rank_ic: { mean: 0.12 },
            top_bottom_return: 0.034,
          },
        },
      },
    },
    research_kind: "factor_evaluation",
    run_id: "run_0123456789abcdef0123",
    section: "factor",
  };
}

function strategyResult(): Record<string, unknown> {
  return {
    metrics: {
      maximum_drawdown: { value: -0.08 },
      net_cumulative_return: 0.17,
      sharpe: 1.23,
    },
    research_kind: "strategy_backtest",
    run_id: "run_abcdef0123456789abcd",
    section: "strategy_summary",
  };
}

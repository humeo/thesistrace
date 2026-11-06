import { RequestContext } from "@mastra/core/request-context";
import { createTool, noopObserve } from "@mastra/core/tools";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { createResearchCodeModeHost } from "./research-code-mode.js";
import type { McpRun, McpToolFailure, DiscoveredMcpTools } from "./mcp-run.js";
import type { CodeModeActivity } from "./code-mode-activity.js";

describe("Research Code Mode", () => {
  it("offers authenticated reads through code while preserving direct business commands", () => {
    const tool = (id: string) => createTool({ id, description: "Fixture", inputSchema: z.object({}), execute: async () => ({ value: 42 }) });
    const run: McpRun = { tools: { get_research_context: tool("get_research_context"),
      submit_research_run: tool("submit_research_run"), stop_daily_track: tool("stop_daily_track"),
      unknown_tool: tool("unknown_tool") }, close: async () => {},
      hasFatalToolFailure: () => false, toolFailure: () => undefined };
    const scope = createResearchCodeModeHost().forRun({ mcpRun: run,
      signal: new AbortController().signal, deadline: performance.now() + 30_000,
      onFatal: () => {}, onActivity: () => {} });
    expect(Object.keys(scope.tools).sort()).toEqual(["execute_typescript", "submit_research_run"]);
    expect(scope.instructions).toContain("external_get_research_context");
    expect(scope.instructions).not.toContain("external_submit_research_run");
    expect(scope.instructions).not.toContain("external_stop_daily_track");
  });

  it("computes across reads with independent call identities and the original request context", async () => {
    const ids: string[] = [];
    const request = new RequestContext();
    const read = createTool({ id: "server-prefixed-name", description: "Read a value", inputSchema: z.object({ value: z.number() }),
      execute: async (input, context) => {
        expect(context.requestContext).toBe(request);
        ids.push(context.agent!.toolCallId);
        return { value: input.value };
      } });
    const { scope, activity } = fixture({ get_alpha_catalog: read });
    const result = await scope.tools.execute_typescript.execute!({ code: 'const rows = await Promise.all([19, 23].map(value => external_get_alpha_catalog({value}))); return rows.reduce((sum, row) => sum + row.value, 0);' }, invocation("outer", request));
    expect(result).toMatchObject({ success: true, result: 42 });
    expect(new Set(ids).size).toBe(2);
    expect(ids.every(id => /^[a-f0-9-]{36}:external:[12]$/.test(id))).toBe(true);
    expect(activity.filter(item => item.status === "complete")).toHaveLength(2);
  });

  it("preserves schema validation failures and lets the model correct the program", async () => {
    const { scope, activity } = fixture({ get_alpha_catalog: createTool({ id: "get_alpha_catalog", description: "Read", inputSchema: z.object({ count: z.number().int().positive() }), execute: async () => 42 }) });
    const rejected = await scope.tools.execute_typescript.execute!({ code: 'return await external_get_alpha_catalog({count: "wrong"});' }, invocation());
    expect(rejected).toMatchObject({ success: false, code: "TOOL_REJECTION", error: { message: expect.stringContaining("count") } });
    expect(activity.at(-1)).toMatchObject({ status: "failed", failureCode: "TOOL_REJECTION" });
    expect(scope.hasFatalToolFailure()).toBe(false);
    await expect(scope.tools.execute_typescript.execute!({ code: 'return await external_get_alpha_catalog({count: 1});' }, invocation("corrected")))
      .resolves.toMatchObject({ success: true, result: 42 });
  });

  it("does not let program error handling swallow a fatal MCP failure", async () => {
    const failures = new Map<string, McpToolFailure>();
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}), execute: async (_args, context) => {
      failures.set(context.agent!.toolCallId, { code: "MCP_AUTHENTICATION", fatal: true });
      return { code: "FORBIDDEN" };
    } });
    const { scope, onFatal } = fixture({ get_research_context: read }, failures);
    const result = await scope.tools.execute_typescript.execute!({ code: 'try { await external_get_research_context({}); } catch {} return {success: true};' }, invocation());
    expect(result).toMatchObject({ success: false, code: "MCP_AUTHENTICATION" });
    expect(scope.toolFailure("outer")).toEqual({ code: "MCP_AUTHENTICATION", fatal: true });
    expect(onFatal).toHaveBeenCalledWith("MCP_AUTHENTICATION");
  });

  it("limits actual parallel reads and stops a program that exceeds the call budget", async () => {
    let active = 0, peak = 0;
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}), execute: async () => {
      active++; peak = Math.max(peak, active);
      await new Promise<void>(resolve => setImmediate(resolve)); active--;
      return 1;
    } });
    const { scope } = fixture({ get_research_context: read });
    await expect(scope.tools.execute_typescript.execute!({ code: 'const values = await Promise.all(Array.from({length: 9}, () => external_get_research_context({}))); return values.reduce((a,b) => a+b, 0);' }, invocation()))
      .resolves.toMatchObject({ success: true, result: 9 });
    expect(peak).toBeLessThanOrEqual(4);
    await expect(scope.tools.execute_typescript.execute!({ code: 'for (let i=0; i<33; i++) await external_get_research_context({}); return 33;' }, invocation("too-many")))
      .resolves.toMatchObject({ success: false, code: "AGENT_LIMIT" });
  });

  it.each([
    'return await external_submit_research_run({});',
    'return await external_execute_typescript({code: "return 42"});',
    'return await external_unknown_tool({});',
  ])("keeps commands, recursion and undiscovered capabilities outside the program: %s", async code => {
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}), execute: async () => 42 });
    const { scope } = fixture({ get_research_context: read });
    await expect(scope.tools.execute_typescript.execute!({ code }, invocation()))
      .resolves.toMatchObject({ success: false, code: "TOOL_REJECTION" });
    expect(scope.hasFatalToolFailure()).toBe(false);
  });

  it("retains successful reads when another read has a recoverable business rejection", async () => {
    const failures = new Map<string, McpToolFailure>();
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({ missing: z.boolean() }),
      execute: async (input, context) => {
        if (!input.missing) return { value: 42 };
        failures.set(context.agent!.toolCallId, { code: "TOOL_REJECTION", fatal: false });
        return { isError: true, code: "NOT_FOUND" };
      } });
    const { scope, activity, onFatal } = fixture({ get_research_context: read }, failures);
    await expect(scope.tools.execute_typescript.execute!({ code: 'const rows = await Promise.all([false, true].map(missing => external_get_research_context({missing}))); return rows.filter(row => !row.isError);' }, invocation()))
      .resolves.toMatchObject({ success: true, result: [{ value: 42 }] });
    expect(activity.filter(item => item.status === "complete")).toHaveLength(1);
    expect(activity.filter(item => item.status === "failed")).toHaveLength(1);
    expect(onFatal).not.toHaveBeenCalled();
  });

  it("preserves the failure of an unchanged rejected read returned by the program", async () => {
    const failures = new Map<string, McpToolFailure>();
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}),
      execute: async (_input, context) => {
        failures.set(context.agent!.toolCallId, { code: "MCP_TRANSIENT", fatal: false });
        return { isError: true, code: "TEMPORARILY_UNAVAILABLE", retry_after_seconds: 3 };
      } });
    const { scope, onFatal } = fixture({ get_research_context: read }, failures);
    await expect(scope.tools.execute_typescript.execute!({ code: 'return await external_get_research_context({});' }, invocation()))
      .resolves.toMatchObject({ code: "MCP_TRANSIENT", "thesistrace/agent-tool-outcome": "failed" });
    expect(scope.toolFailure("outer")).toEqual({ code: "MCP_TRANSIENT", fatal: false });
    expect(onFatal).not.toHaveBeenCalled();
  });

  it.each([
    "/*" + "x".repeat(64 * 1024) + "*/ return 1;",
    'return "x".repeat(256 * 1024);',
    'try { await external_get_research_context({value: "x".repeat(70000)}); } catch {} return 42;',
    'for (let i = 0; i < 17; i++) await external_get_research_context({}); return 42;',
  ])("makes source, final-result and cumulative read budgets fatal", async code => {
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}), execute: async () => "x".repeat(512 * 1024 - 32) });
    const { scope, onFatal } = fixture({ get_research_context: read });
    await expect(scope.tools.execute_typescript.execute!({ code }, invocation()))
      .resolves.toMatchObject({ success: false, code: "AGENT_LIMIT" });
    expect(scope.hasFatalToolFailure()).toBe(true);
    expect(onFatal).toHaveBeenCalledWith("AGENT_LIMIT");
  });

  it("cancels active and queued reads on Stop without starting additional requests", async () => {
    let started = 0;
    let ready!: () => void;
    const fourStarted = new Promise<void>(resolve => { ready = resolve; });
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}),
      execute: async (_input, context) => {
        if (++started === 4) ready();
        return new Promise((_resolve, reject) => context.abortSignal!.addEventListener("abort", () => reject(context.abortSignal!.reason), { once: true }));
      } });
    const { scope, controller, activity, onFatal } = fixture({ get_research_context: read });
    const result = scope.tools.execute_typescript.execute!({ code: 'return await Promise.all(Array.from({length: 12}, () => external_get_research_context({})));' }, invocation());
    const stopped = expect(result).rejects.toMatchObject({ code: "AGENT_RUN_INTERRUPTED" });
    await fourStarted;
    controller.abort();
    await stopped;
    expect(started).toBe(4);
    expect(activity.filter(item => item.status === "failed")).toHaveLength(4);
    expect(onFatal).not.toHaveBeenCalled();
  });

  it("admits at most eight programs on a Host and releases capacity after Stop", async () => {
    const host = createResearchCodeModeHost();
    const controllers = Array.from({ length: 8 }, () => new AbortController());
    let started = 0;
    let ready!: () => void;
    const allStarted = new Promise<void>(resolve => { ready = resolve; });
    const blocked = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}),
      execute: async (_input, context) => {
        if (++started === 8) ready();
        return new Promise((_resolve, reject) => context.abortSignal!.addEventListener("abort", () => reject(context.abortSignal!.reason), { once: true }));
      } });
    const tools = { get_research_context: blocked };
    const forRun = (controller: AbortController) => host.forRun({ mcpRun: { tools, close: async () => {},
      toolFailure: () => undefined, hasFatalToolFailure: () => false }, signal: controller.signal,
      deadline: performance.now() + 30_000, onFatal: () => {}, onActivity: () => {} });
    const executions = controllers.map((controller, index) => forRun(controller).tools.execute_typescript.execute!({ code: 'return await external_get_research_context({});' }, invocation(`outer-${index}`)));
    const settled = Promise.allSettled(executions);
    try {
      await allStarted;
      await expect(forRun(new AbortController()).tools.execute_typescript.execute!({ code: "return 42;" }, invocation("overflow")))
        .resolves.toMatchObject({ success: false, code: "AGENT_CAPACITY" });
      expect(started).toBe(8);
    } finally {
      controllers.forEach(controller => controller.abort());
      await settled;
    }
    await expect(forRun(new AbortController()).tools.execute_typescript.execute!({ code: "return 42;" }, invocation("available")))
      .resolves.toMatchObject({ success: true, result: 42 });
  });

  it("rejects a second simultaneous program in one Run and cancels its active program", async () => {
    let ready!: () => void;
    const started = new Promise<void>(resolve => { ready = resolve; });
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}),
      execute: async (_input, context) => {
        ready();
        return new Promise((_resolve, reject) => context.abortSignal!.addEventListener("abort", () => reject(context.abortSignal!.reason), { once: true }));
      } });
    const { scope, onFatal } = fixture({ get_research_context: read });
    const first = scope.tools.execute_typescript.execute!({ code: 'return await external_get_research_context({});' }, invocation("first"));
    await started;
    await expect(scope.tools.execute_typescript.execute!({ code: "return 42;" }, invocation("second")))
      .resolves.toMatchObject({ code: "AGENT_CAPACITY" });
    await expect(first).resolves.toMatchObject({ code: "AGENT_CAPACITY" });
    expect(scope.toolFailure("first")).toEqual({ code: "AGENT_CAPACITY", fatal: true });
    expect(onFatal).toHaveBeenCalledOnce();
  });

  it("bounds execution by the remaining Run deadline", async () => {
    const read = createTool({ id: "get_research_context", description: "Read", inputSchema: z.object({}), execute: async () => 42 });
    const onFatal = vi.fn();
    const scope = createResearchCodeModeHost().forRun({ mcpRun: { tools: { get_research_context: read },
      close: async () => {}, toolFailure: () => undefined, hasFatalToolFailure: () => false },
      signal: new AbortController().signal, deadline: performance.now() + 25, onFatal, onActivity: () => {} });
    await expect(scope.tools.execute_typescript.execute!({ code: "while (true) {}" }, invocation()))
      .resolves.toMatchObject({ code: "AGENT_LIMIT" });
    expect(onFatal).toHaveBeenCalledWith("AGENT_LIMIT");
  });
});

function invocation(id = "outer", requestContext = new RequestContext()) {
  return { requestContext, observe: noopObserve,
    agent: { agentId: "research", toolCallId: id, messages: [], suspend: async () => {} } };
}

function fixture(tools: DiscoveredMcpTools, failures = new Map<string, McpToolFailure>()) {
  const activity: CodeModeActivity[] = [];
  const onFatal = vi.fn();
  const controller = new AbortController();
  const scope = createResearchCodeModeHost().forRun({ mcpRun: { tools,
    close: async () => {}, toolFailure: id => failures.get(id), hasFatalToolFailure: () => [...failures.values()].some(failure => failure.fatal) },
    signal: controller.signal, deadline: performance.now() + 30_000, onFatal, onActivity: value => activity.push(value) });
  return { scope, activity, onFatal, controller };
}

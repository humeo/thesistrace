import { createServer } from "node:http";
import { RequestContext } from "@mastra/core/request-context";
import { noopLogger } from "@mastra/core/logger";
import { createTool, noopObserve } from "@mastra/core/tools";
import { MCPServer } from "@mastra/mcp";
import { expect, it, vi } from "vitest";
import { z } from "zod";
import type { AgentSettings } from "./config.js";
import { createMcpRunFactory, type McpRun } from "./mcp-run.js";
import { createResearchCodeModeHost } from "./research-code-mode.js";
import type { CodeModeActivity } from "./code-mode-activity.js";

it.each(["stop", "deadline"] as const)("releases real MCP HTTP requests and queued reads after %s", async mode => {
  let reads = 0, returned = 0, abortedHttp = 0;
  let ready!: () => void, release!: () => void, lateReturned!: () => void;
  const fourStarted = new Promise<void>(resolve => { ready = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const allReturned = new Promise<void>(resolve => { lateReturned = resolve; });
  const server = new MCPServer({ id: "cancel-fixture", name: "cancel-fixture", version: "1.0.0", protocolVersion: "2026-07-28",
    tools: { get_research_context: createTool({ id: "get_research_context", description: "Held real HTTP read", inputSchema: z.object({}),
      execute: async () => {
        if (++reads === 4) ready();
        await held;
        if (++returned === 4) lateReturned();
        return { private: "late-mcp-result-canary" };
      } }) } });
  server.__setLogger(noopLogger);
  const http = createServer((req, res) => {
    expect(req.headers.authorization).toBe("Bearer cancellation-fixture");
    if (req.method === "POST") res.on("close", () => { if (!res.writableEnded) abortedHttp++; });
    void server.startHTTP({ req, res, url: new URL(req.url!, "http://127.0.0.1"), httpPath: "/mcp" })
      .catch(() => { if (!res.destroyed) res.writeHead(500).end(); });
  });
  await new Promise<void>(resolve => http.listen(0, "127.0.0.1", resolve));
  const address = http.address();
  if (!address || typeof address === "string") throw new Error("HTTP fixture did not bind");
  const factory = createMcpRunFactory({ authInternalOrigin: "http://auth.fixture", mcpClockSkewSeconds: 30,
    mcpInternalUrl: `http://127.0.0.1:${address.port}/mcp`, runMaxWallSeconds: 30 } as AgentSettings, {
    fetch: async () => Response.json({ access_token: "cancellation-fixture", token_type: "Bearer", expires_in: 360 }),
  });
  const host = createResearchCodeModeHost();
  const controller = new AbortController();
  const activity: CodeModeActivity[] = [];
  const onFatal = vi.fn();
  let run: McpRun | undefined, next: McpRun | undefined;
  try {
    run = await factory(new Headers(), `http-${mode}`);
    const scope = host.forRun({ mcpRun: run, signal: controller.signal,
      deadline: performance.now() + (mode === "deadline" ? 1_000 : 30_000), onFatal, onActivity: value => activity.push(value) });
    const result = scope.tools.execute_typescript.execute!({ code: 'return await Promise.all(Array.from({length:8}, () => external_get_research_context({})));' }, invocation("held"));
    const expected = mode === "stop" ? expect(result).rejects.toMatchObject({ code: "AGENT_RUN_INTERRUPTED" })
      : expect(result).resolves.toMatchObject({ code: "AGENT_LIMIT" });
    await fourStarted;
    if (mode === "stop") controller.abort();
    await expected;
    await vi.waitFor(() => expect(abortedHttp).toBe(4), { timeout: 2_000 });
    expect(reads).toBe(4);
    if (mode === "stop") expect(onFatal).not.toHaveBeenCalled();
    else expect(onFatal).toHaveBeenCalledWith("AGENT_LIMIT");
    release();
    await allReturned;
    expect(activity.some(value => value.status === "complete")).toBe(false);
    expect(JSON.stringify(activity)).not.toContain("late-mcp-result-canary");
    next = await factory(new Headers(), `http-after-${mode}`);
    const recovered = host.forRun({ mcpRun: next, signal: new AbortController().signal,
      deadline: performance.now() + 10_000, onFatal: () => {}, onActivity: () => {} });
    await expect(recovered.tools.execute_typescript.execute!({ code: "return 42;" }, invocation("recovered")))
      .resolves.toMatchObject({ success: true, result: 42 });
  } finally {
    controller.abort(); release();
    await Promise.allSettled([run?.close(), next?.close(), server.close()]);
    http.closeAllConnections();
    await new Promise<void>(resolve => http.close(() => resolve()));
  }
}, 10_000);

function invocation(toolCallId: string) {
  return { requestContext: new RequestContext(), observe: noopObserve,
    agent: { agentId: "research", toolCallId, messages: [], suspend: async () => {} } };
}
